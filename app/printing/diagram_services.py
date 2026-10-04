"""Confirmed teaching diagrams bound to exact question versions and original regions."""
import fcntl
from contextlib import contextmanager
from contextvars import ContextVar
import io
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from django.conf import settings
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from app.exports.contracts import Block, ExportDocument, SourceRef, digest, resolve_diagram, validate_document
from app.exports.snapshots import private_directory
from app.persistence import services as core
from app.persistence.models import RevisionRecord
from app.web import records, services as materials
from app.web.models import QuestionSource
from . import services
from .models import TeachingDiagramRevision


PLACEMENTS = ('question', 'answer')
MAX_BYTES = 8 * 1024 * 1024
_BATCH_FILES = ContextVar('diagram_batch_files', default=None)


@contextmanager
def file_batch():
    """Hold the file lock through the enclosing durable database commit/rollback."""
    if _BATCH_FILES.get() is not None:
        raise RuntimeError('Nested diagram file batches are unsupported')
    root = private_directory(settings.SWB_DATA_ROOT)
    fd = os.open(root / '.diagram-files.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    created = []
    with os.fdopen(fd, 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        token = _BATCH_FILES.set(created)
        try:
            yield
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        finally:
            _BATCH_FILES.reset(token)


def diagram_context(question):
    return {'question': records.edit_context(question), 'diagrams': {
        placement: TeachingDiagramRevision.objects.filter(question_revision=question, placement=placement)
        .order_by('-revision_no').values_list('pk', flat=True).first()
        for placement in PLACEMENTS}}


def current_diagrams(question):
    return [row for placement in PLACEMENTS if (row := TeachingDiagramRevision.objects.filter(
        question_revision=question, placement=placement).order_by('-revision_no').first()) is not None]


@transaction.atomic
def details(actor, question_revision_id):
    question = RevisionRecord.objects.select_related('entity').get(pk=question_revision_id, entity__kind='question')
    owner = records.household(actor, question.entity.household_id)
    can_write = False
    try:
        services.published_question(owner.pk, question.pk)
        core.require_household_access(actor, owner, write=True)
        can_write = question.entity.head_revision_id == question.pk
    except core.PersistenceError:
        pass
    history = list(TeachingDiagramRevision.objects.filter(question_revision=question).select_related('question_revision').order_by('-pk'))
    source = QuestionSource.objects.filter(revision=question).first()
    pages = {value['region_revision_id']: value['page_id'] for value in source.sources} if source else {}
    for row in history:
        row.source_page_id = pages.get(row.content['source_ref'].split('|', 1)[0])
    return {'question': question, 'history': history, 'context': diagram_context(question), 'can_write': can_write}


def _upload(upload):
    if upload is None or not hasattr(upload, 'read'):
        raise core.PersistenceError('invalid_input', '请选择本机图示文件。')
    upload.seek(0)
    raw = upload.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise core.PersistenceError('invalid_input', '每个图示文件须为 1 字节至 8 MiB。')
    return raw


def _validate_uploads(png, vector, suffix):
    try:
        with Image.open(io.BytesIO(png)) as image:
            if image.format != 'PNG' or image.width * image.height > 16_000_000:
                raise ValueError
            image.verify()
        with Image.open(io.BytesIO(png)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise core.PersistenceError('invalid_input', '题面图须为可解码 PNG，最多 1600 万像素。') from exc
    try:
        if suffix == '.pdf' and vector.startswith(b'%PDF-'):
            return
        if suffix != '.svg':
            raise ValueError
        text = vector.decode('utf-8-sig')
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise ValueError
        if ET.fromstring(text).tag not in ('svg', '{http://www.w3.org/2000/svg}svg'):
            raise ValueError
    except (ValueError, ET.ParseError) as exc:
        raise core.PersistenceError('invalid_input', '矢量来源须为 PDF 或 SVG；不执行或内嵌 SVG。') from exc


def save_diagram(actor, question_revision_id, *, placement, png_upload, vector_upload, source_region_id,
                 alt, conditions, width_points, min_label_points, independent_safe, basis, expected, request_key):
    """The explicit save action confirms metadata; replaces append a new version."""
    if placement not in PLACEMENTS or type(independent_safe) is not bool:
        raise core.PersistenceError('invalid_input', '请选择题面图或解析图，并明确无提示状态。')
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 30:
        raise core.PersistenceError('invalid_input', '请逐行填写 1～30 条构造条件。')
    png, vector = _upload(png_upload), _upload(vector_upload)
    suffix = Path(str(vector_upload.name)).suffix.lower()
    _validate_uploads(png, vector, suffix)
    basis = materials._text(basis, 4000)
    alt = materials._text(alt, 2000)
    conditions = [materials._text(value, 1000) for value in conditions]
    if not basis or not alt or not all(conditions):
        raise core.PersistenceError('invalid_input', '图示说明、构造条件和核对依据不能为空。')
    inputs = {'question': question_revision_id, 'placement': placement, 'png': digest(png),
        'vector': digest(vector), 'suffix': suffix, 'source_region_id': source_region_id, 'alt': alt,
        'conditions': conditions, 'width_points': width_points, 'min_label_points': min_label_points,
        'independent_safe': independent_safe, 'basis': basis, 'expected': expected}
    fingerprint = core._digest(inputs)
    if _BATCH_FILES.get() is None:
        with file_batch():
            with transaction.atomic(durable=True):
                return _save_validated(actor, question_revision_id, placement, source_region_id, alt, conditions,
                    width_points, min_label_points, independent_safe, basis, expected, request_key,
                    fingerprint, png, vector, suffix)
    with transaction.atomic():
        return _save_validated(actor, question_revision_id, placement, source_region_id, alt, conditions,
            width_points, min_label_points, independent_safe, basis, expected, request_key,
            fingerprint, png, vector, suffix)


def _save_validated(actor, question_revision_id, placement, source_region_id, alt, conditions,
                    width_points, min_label_points, independent_safe, basis, expected, request_key,
                    fingerprint, png, vector, suffix):
    root = private_directory(settings.SWB_DATA_ROOT)
    created = _BATCH_FILES.get()
    initial = RevisionRecord.objects.select_related('entity').get(pk=question_revision_id, entity__kind='question')
    owner = records.household(actor, initial.entity.household_id, write=True)
    replay = core._replay(owner, actor, request_key, 'web_record', fingerprint)
    if replay:
        return replay
    question = services.published_question(owner.pk, initial.pk)
    if question.entity.head_revision_id != question.pk or expected != diagram_context(question):
        raise core.PersistenceError('head_conflict', '题目或教学图版本已改变，请重新打开。')
    reference = next((r for r in question.payload['evidence_refs']
        if r.get('region_revision_id') == source_region_id), None)
    if reference is None:
        raise core.PersistenceError('invalid_input', '图示须关联本题版本的原图区域。')
    prefix = 'prints/diagrams/' + digest(str(owner.pk).encode())[:24] + '/'
    content = {'storage_key': prefix + digest(png) + '.png', 'sha256': digest(png),
        'vector_storage_key': prefix + digest(vector) + suffix, 'vector_sha256': digest(vector),
        'source_ref': source_region_id + '|' + reference['image_sha256'], 'alt': alt,
        'conditions': conditions, 'width_points': width_points, 'min_label_points': min_label_points,
        'independent_safe': independent_safe}
    validate_document(ExportDocument('diagram-check', '教学图核对', 'parent_answers',
        ((Block('diagram', content, placement),),),
        SourceRef(question.entity.stable_id, question.content_hash, 'accepted', question.pk)))
    for key, raw in ((content['storage_key'], png), (content['vector_storage_key'], vector)):
        destination = root / key
        private_directory(destination.parent)
        try:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            if destination.is_symlink():
                raise core.PersistenceError('asset_conflict', '图示文件冲突，保留现有来源。')
            materials.asset_path(key, digest(raw))
        else:
            # Register exclusive ownership before any write/flush/fsync can fail.
            created.append(destination)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
    resolve_diagram(content, root)
    previous = TeachingDiagramRevision.objects.filter(question_revision=question, placement=placement).order_by('-revision_no').first()
    row = TeachingDiagramRevision.objects.create(household=owner, question_revision=question,
        placement=placement, revision_no=previous.revision_no + 1 if previous else 1,
        previous=previous, content=content, basis=basis, created_by=actor)
    return core._receipt(owner, actor, request_key, 'web_record', fingerprint, {'diagram_id': row.pk})



@transaction.atomic
def diagram_file(actor, diagram_id, name):
    row = TeachingDiagramRevision.objects.get(pk=diagram_id)
    records.household(actor, row.household_id)
    if name not in ('png', 'vector'):
        raise core.PersistenceError('not_found', '图示文件不存在。')
    prefix = 'vector_' if name == 'vector' else ''
    return materials.asset_path(row.content[prefix + 'storage_key'], row.content[prefix + 'sha256'])
