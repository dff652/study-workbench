"""Page inventory with original-pixel traceability and append-only human updates."""
from django.db import transaction

from app.persistence import services as core
from . import records, services
from .images import original_bbox
from .models import MaterialPage, PageReadingRevision

KINDS = {'theory': '理论／知识', 'question': '印刷题目', 'diagram': '图示',
    'handwriting': '手写内容（作者／独立性未知）', 'unknown': '看不清／来源未知'}


def context(page):
    return {'head': PageReadingRevision.objects.filter(page=page).values_list('pk', flat=True).first(),
        'original_sha256': page.image.sha256}


@transaction.atomic
def detail(actor, page_id):
    page = MaterialPage.objects.select_related('image', 'material').get(pk=page_id)
    owner = records.household(actor, page.material.household_id)
    writable = True
    try:
        core.require_household_access(actor, owner, write=True)
    except core.PersistenceError:
        writable = False
    return {'page': page, 'history': list(page.reading_revisions.select_related('created_by')),
        'context': context(page), 'writable': writable}


def _partitions(actor, page, sources):
    if not isinstance(sources, list) or len(sources) > 100:
        raise core.PersistenceError('invalid_region', '整页最多记录 100 个分区。')
    result = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != {'kind', 'page_id', 'rotation', 'preview_sha256', 'display_bbox'}:
            raise core.PersistenceError('invalid_region', '请明确每个分区的内容类型和原图区域。')
        if not isinstance(source['kind'], str) or source['kind'] not in KINDS or source['page_id'] != str(page.pk) or type(source['rotation']) is not int:
            raise core.PersistenceError('invalid_region', '分区类型、页码或方向无效。')
        display_box = source['display_bbox']
        limit = max(page.image.payload['width'], page.image.payload['height'])
        if not isinstance(display_box, (list, tuple)) or len(display_box) != 4 or any(
                type(value) not in (int, float) or not 0 <= value <= limit or value != int(value)
                for value in display_box):
            raise core.PersistenceError('invalid_region', '整页分区请使用图片范围内的整数像素坐标。')
        display_box = [int(value) for value in display_box]
        preview = services.preview_file(actor, page.pk, source['rotation'])
        if preview.sha256 != source['preview_sha256']:
            raise core.PersistenceError('preview_changed', '预览已变化。')
        services.asset_path(preview.storage_key, preview.sha256)
        box = original_bbox(display_box, page.image.payload['width'],
            page.image.payload['height'], source['rotation'])
        result.append({**source, 'display_bbox': display_box,
            'original_bbox': list(box), 'image_id': page.image.stable_id,
            'original_sha256': page.image.sha256})
    return result


@transaction.atomic
def save(actor, page_id, *, reading, coverage, sources, pending_items, basis, expected, request_key):
    page = MaterialPage.objects.select_related('image', 'material').get(pk=page_id)
    owner = records.household(actor, page.material.household_id, write=True)
    basis = services._text(basis, 1000)
    pending_items = services._text(pending_items, 4000, blank=True)
    try:
        fingerprint = core._digest({'action': 'page-reading', 'page': str(page_id), 'reading': reading,
            'coverage': coverage, 'sources': sources, 'pending': pending_items, 'basis': basis, 'expected': expected})
    except (TypeError, ValueError) as exc:
        raise core.PersistenceError('invalid_input', '整页请求含无效数值或内容。') from exc
    replay = core._replay(owner, actor, request_key, 'web_record', fingerprint)
    if replay is not None:
        return replay
    if expected != context(page):
        raise core.PersistenceError('head_conflict', '整页状态已变化，请重新打开。')
    if reading not in ('unread', 'read', 'needs_retake') or coverage not in ('partial', 'complete'):
        raise core.PersistenceError('invalid_input', '请明确阅读与分区状态。')
    services.asset_path(page.image.payload['storage_key'], page.image.sha256)
    partitions = _partitions(actor, page, sources)
    if coverage == 'complete' and (reading != 'read' or not partitions or pending_items
            or any(row['kind'] == 'unknown' for row in partitions)):
        raise core.PersistenceError('invalid_input', '有待补、未知区域或尚未阅读时，保留待补分区。')
    if reading == 'needs_retake' and not pending_items:
        raise core.PersistenceError('invalid_input', '请记录待重拍的原因。')
    previous = page.reading_revisions.first()
    row = PageReadingRevision.objects.create(page=page, household=owner, created_by=actor,
        previous=previous, revision_no=previous.revision_no + 1 if previous else 1,
        original_sha256=page.image.sha256, reading=reading, coverage=coverage,
        partitions=partitions, pending_items=pending_items, basis=basis)
    return core._receipt(owner, actor, request_key, 'web_record', fingerprint,
        {'page_id': str(page.pk), 'reading_revision_id': row.pk, 'revision_no': row.revision_no})
