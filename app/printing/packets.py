"""Five-book delivery from one locked material scope and verified snapshots."""
import json
from html import escape
from pathlib import Path
import re
import tempfile
import zipfile

from django.conf import settings
from django.db import transaction

from app.exports.contracts import Block, ExportError, canonical, digest
from app.exports.snapshots import private_directory, write_private
from app.domain.presentation import display_lines
from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.web import records, services as materials
from app.web.models import QuestionSource
from . import services
from .models import ExportSnapshot
from .diagram_services import current_diagrams


BOOKS = (
    ('knowledge_summary','01_知识整理'),
    ('classification_index','02_逐题分类索引'),
    ('evidence_report','03_学习证据与待测项目'),
    ('independent_practice','04_独立复测无提示'),
    ('parent_answers','05_家长答案与依据'),
)
SCHEMA = 'study-workbench.five-books.v1'


@transaction.atomic
def readiness(actor, material_id):
    material=materials.material_detail(actor,material_id)['material']
    records.household(actor,material.household_id)
    entity_ids=QuestionSource.objects.filter(material=material).values_list('revision__entity_id',flat=True)
    entities=EntityRecord.objects.filter(pk__in=entity_ids,kind='question',household=material.household)
    rows=[]; gaps=[]; content_gaps=[]; diagram_revisions=[]
    linked_questions=set()
    links=EntityRecord.objects.filter(household=material.household,
        kind__in=('knowledge_question','method_question','question_type_link'),
        published_revision__review_projection__state='accepted').select_related('published_revision')
    for link in links:
        if all(dependency.target.entity.published_revision_id==dependency.target_id and
               dependency.target.review_projection.state=='accepted'
               for dependency in link.published_revision.outgoing_dependencies.select_related('target__entity','target__review_projection')):
            linked_questions.add(link.published_revision.payload['question_revision_id'])
    for entity in entities.select_related('head_revision','published_revision').order_by('pk'):
        revision=entity.head_revision
        number=QuestionSource.objects.filter(material=material,revision=revision).values_list('original_number',flat=True).first()
        label=number or '未编号题目'
        entry={'question_id':entity.stable_id,'revision_id':revision.pk,'number':label,
            'text':revision.payload.get('working_text') or '题干待补','confirmed':False,'answer_ready':False}
        try:
            services.published_question(material.household_id,revision.pk)
            entry['confirmed']=True
            entry['answer_ready']=services.accepted_answer(revision)[0] is not None
            if (revision.payload.get('display_markup') and not revision.payload.get('image_print_confirmed') and
                any(line.kind=='image' for line in display_lines(revision.payload['display_markup']))):
                gaps.append(f'{label}：独立复测图片尚未确认无作答或提示。')
            for diagram in current_diagrams(revision):
                diagram_revisions.append({'diagram_id': diagram.pk, 'question_revision_id': revision.pk,
                    'placement': diagram.placement, 'revision_no': diagram.revision_no,
                    'png_sha256': diagram.content['sha256'], 'vector_sha256': diagram.content['vector_sha256']})
                if diagram.placement == 'question' and not diagram.content['independent_safe']:
                    gaps.append(f'{label}：教学题面图尚未确认无答案或方法提示。')
        except core.PersistenceError:
            gaps.append(f'{label}：题干、原图区域或内容确认待补。')
        if entry['confirmed'] and not entry['answer_ready']:
            gaps.append(f'{label}：家长答案与依据待确认。')
        if revision.pk not in linked_questions:
            content_gaps.append(f'{label}：知识、方法或题型关联待补。')
        rows.append(entry)
    if not rows:gaps.append('尚无题目，请先对照原图录入。')
    if len(rows)>150:gaps.append('单次五册最多 150 道题，请拆分资料集。')
    learners=list(EntityRecord.objects.filter(household=material.household,kind='learner').select_related('head_revision').order_by('pk'))
    return {'material':material,'questions':rows,'gaps':gaps,'content_gaps':content_gaps,'ready':not gaps,
        'learners':learners,'diagram_revisions':diagram_revisions}


def _packet_root(material,*,create=False):
    root=Path(settings.SWB_DATA_ROOT).resolve()
    path=root/'packets'/digest(str(material.household_id).encode())[:24]/str(material.pk)
    if not path.resolve().is_relative_to(root):raise ExportError('invalid_packet','交付目录无效。')
    return private_directory(path) if create else path


def _unknown_report(actor,material,revision_ids):
    provenance={'material_id':str(material.pk),'question_revisions':revision_ids,'learner':None,'evidence_state':'not_recorded'}
    blocks=[Block('title','学习证据与待测项目','title'),
        Block('p','本次未选择学习者，未关联独立复测记录。本册只列待测项目，不推断掌握。','instruction')]
    for position,revision_id in enumerate(revision_ids,1):
        question=services.published_question(material.household_id,revision_id)
        blocks.append(Block('p',escape(f'{position}. '+question.payload['working_text']),'assessment'))
        blocks.append(Block('small','本册未关联课堂笔记、提示后完成或独立作答；正确性、方法与掌握：未知。','assessment'))
    return services._export_blocks(actor,material.household,'学习证据与待测项目','evidence_report',
        blocks,provenance,digest(canonical(provenance)),None)


@transaction.atomic
def generate(actor,material_id,*,learner_id=None,evidence_scope="selected_learner_history"):
    if evidence_scope not in ('material_questions','selected_learner_history'):
        raise core.PersistenceError('invalid_input','请选择学习证据范围。')
    state=readiness(actor,material_id)
    material=state['material']
    records.household(actor,material.household_id,write=True)
    if state['gaps']:
        raise core.PersistenceError('packet_incomplete','五册尚未齐备：'+'；'.join(state['gaps'][:10]))
    learner=None
    if learner_id is not None:
        learner=EntityRecord.objects.get(pk=learner_id,household=material.household,kind='learner')
    revision_ids=[entry['revision_id'] for entry in state['questions']]
    books=[]
    for purpose,label in BOOKS:
        if purpose=='evidence_report':
            snapshot=services.export_evidence_report(actor,learner.pk,material_id=material.pk if evidence_scope=='material_questions' else None) if learner else _unknown_report(actor,material,revision_ids)
        else:
            snapshot=services.export_questions(actor,material.household_id,revision_ids,
                title=material.title[:110]+' · '+label,purpose=purpose,_packet=True)
        files={name:{'sha256':digest((path:=services.snapshot_file(actor,snapshot.pk,name)).read_bytes()),
                     'size_bytes':path.stat().st_size}
            for name in ('document.pdf','document.docx','content.json','snapshot.json')}
        books.append({'purpose':purpose,'label':label,'snapshot_id':snapshot.pk,'export_id':snapshot.export_id,'files':files})
    manifest={'schema_version':SCHEMA,'material_id':str(material.pk),'household_id':str(material.household_id),
        'question_revisions':revision_ids,'learner_id':learner.pk if learner else None,
        'evidence_scope':evidence_scope if learner else 'not_recorded',
        'content_gaps':state['content_gaps'],'release_state':'layout_check_required','books':books}
    if state['diagram_revisions']:
        manifest['diagram_revisions'] = state['diagram_revisions']
    packet_id=digest(canonical(manifest))
    root=_packet_root(material,create=True)
    destination=root/(packet_id+'.json')
    try:write_private(destination,manifest)
    except FileExistsError:
        if destination.is_symlink() or destination.read_bytes()!=canonical(manifest):
            raise ExportError('packet_conflict','五册清单冲突，保留现有文件。')
    return packet_id


@transaction.atomic
def read(actor,material_id,packet_id):
    material=materials.material_detail(actor,material_id)['material']
    if not isinstance(packet_id,str) or not re.fullmatch('[0-9a-f]{64}',packet_id):
        raise core.PersistenceError('not_found','交付清单不存在。')
    path=_packet_root(material)/(packet_id+'.json')
    if not path.is_file() or path.is_symlink():raise core.PersistenceError('not_found','交付清单不存在。')
    manifest=json.loads(path.read_bytes())
    if (digest(canonical(manifest))!=packet_id or manifest.get('schema_version')!=SCHEMA or
        manifest.get('material_id')!=str(material.pk) or manifest.get('household_id')!=str(material.household_id) or
        [(book.get('purpose'),book.get('label')) for book in manifest.get('books',[])]!=list(BOOKS)):
        raise ExportError('invalid_packet','五册清单被修改。')
    for book in manifest['books']:
        snapshot=ExportSnapshot.objects.get(pk=book['snapshot_id'],household=material.household,
            export_id=book['export_id'],purpose=book['purpose'])
        for name,record in book['files'].items():
            raw=services.snapshot_file(actor,snapshot.pk,name).read_bytes()
            if digest(raw)!=record['sha256'] or len(raw)!=record['size_bytes']:
                raise ExportError('packet_hash_mismatch','五册文件与交付清单不一致。')
    return material,manifest


@transaction.atomic
def archive(actor,material_id,packet_id):
    """Private spool returned to FileResponse; never writes the NAS."""
    material,manifest=read(actor,material_id,packet_id)
    spool=tempfile.TemporaryFile()
    try:
        with zipfile.ZipFile(spool,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',canonical(manifest))
            for book in manifest['books']:
                for name,record in book['files'].items():
                    raw=services.snapshot_file(actor,book['snapshot_id'],name).read_bytes()
                    if digest(raw)!=record['sha256']:raise ExportError('packet_hash_mismatch','输出文件已变化。')
                    archive.writestr(book['label']+'/'+name,raw)
        spool.seek(0)
        return spool
    except BaseException:
        spool.close()
        raise
