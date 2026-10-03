"""Freeze reviewed versions, keeping independent practice free of hints."""
from dataclasses import replace
from html import escape
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4
import io
import math
from PIL import Image

from django.db import transaction
from django.conf import settings

from app.domain.contracts import Erratum, ErratumRevision, ErratumTargetKind, ReviewState, seal_revision
from app.exports.contracts import Block, ExportDocument, SourceRef, ExportError, canonical, digest, validate_math, resolve_formula_image
from app.exports.fonts import prepare_fonts
from app.exports.snapshots import export_document, private_directory, verify_snapshot, write_private
from app.persistence import services as core
from app.persistence.models import EntityRecord, RevisionRecord, ReviewProjection
from app.web import records, services as materials
from .models import TeacherAnswerRevision, AnswerDecision, ExportSnapshot
from .layout import paginate
from app.exports.body import body_blocks
from app.domain.presentation import display_lines


def _text(value, limit=20000):
    return materials._text(value, limit)


def published_question(household_id, revision_id):
    row = RevisionRecord.objects.select_related('entity').get(pk=revision_id,
        entity__household_id=household_id, entity__kind='question')
    if row.entity.published_revision_id != row.pk or row.review_projection.state != 'accepted':
        raise core.PersistenceError('stale_context', '请选择当前已审核题目。')
    if row.payload['missing_fields'] or not row.payload['working_text']:
        raise core.PersistenceError('missing_text', '题干仍有缺口。')
    return row


def answer_context(question):
    answer = TeacherAnswerRevision.objects.filter(question_revision=question).order_by('-revision_no').first()
    decision = answer.decisions.order_by('-pk').first() if answer else None
    return {'question': records.edit_context(question), 'answer': answer.pk if answer else None,
        'decision': decision.pk if decision else None}


@transaction.atomic
def save_answer(actor, household_id, question_revision_id, *, body, formulas, basis, expected, request_key):
    owner = records.household(actor, household_id, write=True)
    inputs = {'question':question_revision_id, 'body':body, 'formulas':formulas, 'basis':basis, 'expected':expected}
    fingerprint = core._digest(inputs)
    replay = core._replay(owner, actor, request_key, 'web_record', fingerprint)
    if replay: return replay
    question = published_question(household_id, question_revision_id)
    if expected != answer_context(question):
        raise core.PersistenceError('head_conflict', '题目、答案或审核状态已改变。')
    if not isinstance(formulas, list) or len(formulas)>20:
        raise core.PersistenceError('invalid_input', '公式列表无效。')
    for formula in formulas:
        if isinstance(formula,dict):
            prefix='prints/assets/'+digest(str(owner.pk).encode())[:24]+'/'
            allowed={f"{r['region_revision_id']}|{r['image_sha256']}" for r in question.payload['evidence_refs'] if r.get('region_revision_id')}
            if set(formula)!={'storage_key','sha256','source_ref','alt','width_points'} or not formula['storage_key'].startswith(prefix) or formula['source_ref'] not in allowed:
                raise core.PersistenceError('invalid_input','公式图片须引用当前题目的原图区域。')
            resolve_formula_image(formula,settings.SWB_DATA_ROOT)
        else:validate_math(formula)
    previous = TeacherAnswerRevision.objects.filter(question_revision=question).order_by('-revision_no').first()
    answer = TeacherAnswerRevision.objects.create(household=owner, question_revision=question,
        revision_no=previous.revision_no+1 if previous else 1, previous=previous,
        body=_text(body), formulas=formulas, basis=_text(basis,4000),
        source_refs=question.payload['evidence_refs'], created_by=actor)
    return core._receipt(owner, actor, request_key, 'web_record', fingerprint, {'answer_id':answer.pk})


@transaction.atomic
def review_answer(actor, answer_id, *, action, reason, expected, request_key):
    answer = TeacherAnswerRevision.objects.select_related('question_revision').get(pk=answer_id)
    owner = records.household(actor, answer.household_id, write=True)
    fingerprint = core._digest({'answer':answer_id, 'action':action, 'reason':reason, 'expected':expected})
    replay = core._replay(owner, actor, request_key, 'web_record', fingerprint)
    if replay: return replay
    question = published_question(owner.pk, answer.question_revision_id)
    if expected != answer_context(question) or expected['answer'] != answer.pk:
        raise core.PersistenceError('head_conflict', '答案或审核状态已改变。')
    if action not in {'accepted','rejected','withdrawn'}:
        raise core.PersistenceError('invalid_input', '审核动作无效。')
    previous = answer.decisions.order_by('-pk').first()
    if action=='withdrawn' and (not previous or previous.action!='accepted'):
        raise core.PersistenceError('invalid_input', '仅可撤回已接受答案。')
    decision = AnswerDecision.objects.create(answer=answer, action=action, reason=_text(reason,1000),
        previous=previous, actor=actor)
    return core._receipt(owner, actor, request_key, 'web_record', fingerprint, {'decision_id':decision.pk})


def accepted_answer(question):
    # A new draft or rejection leaves the previous accepted version available.
    for answer in TeacherAnswerRevision.objects.filter(question_revision=question).order_by('-revision_no'):
        decision = answer.decisions.order_by('-pk').first()
        if decision and decision.action=='accepted': return answer, decision
    return None, None


@transaction.atomic
def source_formula_image(actor,household_id,question_revision_id,region_revision_id,alt):
    records.household(actor,household_id,write=True)
    question=published_question(household_id,question_revision_id)
    reference=next((r for r in question.payload['evidence_refs'] if r.get('region_revision_id')==region_revision_id),None)
    if reference is None:raise core.PersistenceError('invalid_input','公式图片区域不属于当前题目。')
    return _source_ref_image(household_id,reference,alt)


def _source_ref_image(household_id,reference,alt):
    region_revision_id=reference['region_revision_id']
    region=RevisionRecord.objects.select_related('original_image').get(pk=region_revision_id,
        entity__household_id=household_id,entity__kind='region')
    original=region.original_image
    path=materials.asset_path(original.payload['storage_key'],reference['image_sha256'])
    x0,y0,x1,y1=region.payload['geometry']
    with Image.open(path) as image:
        cropped=image.crop((math.floor(x0),math.floor(y0),math.ceil(x1),math.ceil(y1))).convert('RGB')
        stream=io.BytesIO();cropped.save(stream,format='PNG');raw=stream.getvalue()
    sha=digest(raw)
    key='prints/assets/'+digest(str(household_id).encode())[:24]+'/'+sha+'.png'
    destination=Path(settings.SWB_DATA_ROOT)/key
    private_directory(destination.parent)
    try:write_private(destination,raw)
    except FileExistsError:materials.asset_path(key,sha)
    return {'storage_key':key,'sha256':sha,'source_ref':region_revision_id+'|'+reference['image_sha256'],
        'alt':_text(alt,2000),'width_points':min(300,max(50,(x1-x0)*0.75))}


@transaction.atomic
def save_erratum(actor, household_id, question_revision_id, *, corrected_text, basis, expected, request_key):
    """Erratum is about printed content, separate from an assessment of a child."""
    def build(bundle):
        row = RevisionRecord.objects.get(pk=question_revision_id, entity__household_id=household_id, entity__kind='question')
        heads = records.check_edit(row, expected)
        original = row.payload['printed_text']
        corrected = _text(corrected_text)
        if corrected == original:
            raise core.PersistenceError('invalid_input', '勘误须说明印刷原文与订正的区别。')
        identity = 'erratum-'+uuid4().hex
        # Read exact typed evidence from the existing contract bundle.
        question = next(q for q in bundle.questions if q.question_id==row.entity.stable_id)
        revision = next(r for r in question.revisions if r.header.revision_id==row.pk)
        value = seal_revision(ErratumRevision(records.header(actor,identity,'记录讲义勘误'),
            ErratumTargetKind.QUESTION,row.pk,original,corrected,_text(basis,4000),
            revision.evidence_refs,ReviewState.DRAFT,None))
        return replace(bundle,errata=(*bundle.errata,Erratum(identity,household_id,(value,)))),heads,{
            'erratum_id':identity,'revision_id':value.header.revision_id}
    return records.command(actor, household_id, request_key, 'erratum',
        {'question':question_revision_id,'text':corrected_text,'basis':basis,'expected':expected},build)


@transaction.atomic
def apply_erratum(actor, household_id, erratum_revision_id, *, expected, request_key):
    def build(bundle):
        erratum=RevisionRecord.objects.select_related('entity').get(pk=erratum_revision_id,
            entity__household_id=household_id,entity__kind='erratum')
        if erratum.entity.published_revision_id!=erratum.pk or erratum.review_projection.state!='accepted':
            raise core.PersistenceError('invalid_input','先审核勘误依据。')
        row=RevisionRecord.objects.select_related('entity').get(pk=erratum.payload['target_revision_id'],
            entity__household_id=household_id,entity__kind='question')
        heads=records.check_edit(row,expected)
        if row.entity.head_revision_id!=row.pk:
            raise core.PersistenceError('head_conflict','题目已有更新，不能自动套用旧勘误。')
        question=next(q for q in bundle.questions if q.question_id==row.entity.stable_id)
        old=question.revisions[-1]
        revision=seal_revision(replace(old,header=records.header(actor,question.question_id,'按已审核勘误订正',row),
            review_state=ReviewState.DRAFT,working_text=erratum.payload['corrected_text'],display_markup=None,image_print_confirmed=None,
            erratum_revision_ids=(*old.erratum_revision_ids,erratum.pk)))
        questions=tuple(replace(q,revisions=(*q.revisions,revision)) if q.question_id==question.question_id else q for q in bundle.questions)
        heads.update(records.check_edit(erratum,records.edit_context(erratum)))
        return replace(bundle,questions=questions),heads,{'question_id':question.question_id,'revision_id':revision.header.revision_id}
    result=records.command(actor,household_id,request_key,'apply_erratum',
        {'erratum':erratum_revision_id,'expected':expected},build)
    from app.catalogue.models import QuestionLabel
    from app.web.models import QuestionSource
    row=RevisionRecord.objects.get(pk=result['revision_id'])
    old=QuestionSource.objects.filter(revision_id=row.previous_id).first()
    if old and not QuestionSource.objects.filter(revision=row).exists():
        QuestionSource.objects.create(revision=row,material=old.material,original_number=old.original_number,sources=old.sources)
    old_label=QuestionLabel.objects.filter(revision_id=row.previous_id).first()
    if old_label and not QuestionLabel.objects.filter(revision=row).exists():
        QuestionLabel.objects.create(revision=row,original_number=old_label.original_number,created_by=actor)
    return result


def _font_inputs():
    return dict(regular_source=os.environ.get('SWB_CJK_REGULAR','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
        bold_source=os.environ.get('SWB_CJK_BOLD','/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'),
        math_source=os.environ.get('SWB_MATH_FONT','/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'),
        cjk_notice=Path(__file__).resolve().parents[2]/'licenses/Noto-OFL.txt',
        math_notice=Path(__file__).resolve().parents[2]/'licenses/DejaVu-fonts.txt')


@transaction.atomic
def export_questions(actor, household_id, revision_ids, *, title, purpose):
    owner=records.household(actor, household_id, write=True)
    if purpose not in {'independent_practice','parent_answers','knowledge_summary','classification_index'}:
        raise core.PersistenceError('invalid_input','打印用途无效。')
    if not isinstance(revision_ids,list) or not 1<=len(revision_ids)<=30 or len(set(revision_ids))!=len(revision_ids):
        raise core.PersistenceError('invalid_input','请选择 1～30 道不同题目。')
    questions=[published_question(household_id,rid) for rid in revision_ids]
    blocks=[Block('title',escape(_text(title,160)),'title')]
    provenance={'questions':[], 'answers':[], 'nodes':[], 'links':[]}
    for position,question in enumerate(questions,1):
        provenance['questions'].append({'revision_id':question.pk,'content_hash':question.content_hash,
            'review_decision_id':str(question.review_projection.decision_id),
            'evidence_refs':question.payload['evidence_refs']})
        if question.payload.get('display_markup'):
            if purpose=='independent_practice' and not question.payload.get('image_print_confirmed') and any(
                    line.kind=='image' for line in display_lines(question.payload['display_markup'])):
                raise core.PersistenceError('image_review_required','独立练习的图片须先人工核对没有作答、提示或方法笔记，并追加已审核版本。')
            blocks.append(Block('small',f'{position}.','question'))
            blocks.extend(_revision_blocks(question,owner.pk,'question'))
        else:
            blocks.append(Block('p',escape(f'{position}. '+question.payload['working_text']).replace('\n','<br/>'),'question'))
        if question.payload['header']['origin']=='ai':
            blocks.append(Block('small','AI 生成题目 · 已人工审核；来源区域仅表示生成依据。','instruction'))
        if purpose=='independent_practice':
            blocks.append(Block('space',100,'answer_space'))
        elif purpose=='parent_answers':
            answer,decision=accepted_answer(question)
            if answer is None:
                raise core.PersistenceError('missing_answer','所选题目尚无已审核家长答案，请先录入并审核。')
            provenance['answers'].append({'answer_id':answer.pk,'decision_id':decision.pk,'body':answer.body,
                'formulas':answer.formulas,'basis':answer.basis,'source_refs':answer.source_refs})
            blocks.extend([Block('p',escape(answer.body).replace('\n','<br/>'),'answer'),
                *[Block('formula_image' if isinstance(formula,dict) else 'math',formula,'answer') for formula in answer.formulas],
                Block('small',escape('依据：'+answer.basis),'answer')])
        else:
            links=EntityRecord.objects.filter(household=owner,kind__in=('knowledge_question','method_question','question_type_link'),
                published_revision__isnull=False).select_related('published_revision','published_revision__review_projection')
            for link in links:
                payload=link.published_revision.payload
                if link.published_revision.review_projection.state!='accepted': continue
                if payload.get('question_revision_id')!=question.pk: continue
                keys={'knowledge_question':'knowledge_revision_id','method_question':'method_revision_id','question_type_link':'question_type_revision_id'}
                target=RevisionRecord.objects.select_related('entity','review_projection').get(pk=payload[keys[link.kind]],entity__household=owner)
                if target.entity.published_revision_id!=target.pk or target.review_projection.state!='accepted': continue
                provenance['links'].append({'revision_id':link.published_revision_id,'content_hash':link.published_revision.content_hash,
                    'review_decision_id':str(link.published_revision.review_projection.decision_id)})
                provenance['nodes'].append({'revision_id':target.pk,'content_hash':target.content_hash,
                    'review_decision_id':str(target.review_projection.decision_id)})
                blocks.extend(_revision_blocks(target,owner.pk,'body'))
                if purpose=='knowledge_summary':
                    for field,label in [('conditions','适用条件'),('steps','步骤'),('common_errors','易错点')]:
                        for value in target.payload.get(field,()):
                            blocks.append(Block('p',escape(label+'：'+value),'body'))
    source_hash=digest(canonical(provenance))
    return _export_blocks(actor,owner,title,purpose,blocks,provenance,source_hash,questions[0].pk)


def _revision_blocks(revision,household_id,role):
    payload=revision.payload
    text=payload.get('working_text') or payload.get('definition') or payload.get('name') or ''
    refs=payload.get('evidence_refs',payload.get('source_refs',[]))
    def resolve(sequence,alt):
        ref=next((ref for ref in refs if ref['sequence']==sequence and ref.get('region_revision_id')),None)
        if ref is None:raise core.PersistenceError('invalid_display','排版图片缺少本版本来源。')
        return _source_ref_image(household_id,ref,alt)
    return body_blocks(text,payload.get('display_markup'),role=role,image_resolver=resolve)


def _export_blocks(actor,owner,title,purpose,blocks,provenance,source_hash,revision_id):
    pages=tuple(tuple(blocks[n:n+300]) for n in range(0,len(blocks),300))
    document=ExportDocument('web-'+source_hash[:24],title,purpose,tuple(pages),
        SourceRef('household-'+digest(str(owner.pk).encode())[:16],source_hash,
            'draft' if purpose=='evidence_report' else 'accepted',revision_id))
    root=private_directory(Path(settings.SWB_DATA_ROOT)/'prints'/digest(str(owner.pk).encode())[:24])
    with tempfile.TemporaryDirectory(prefix='font-',dir=root) as work:
        fonts,manifest=prepare_fonts([document],Path(work)/'fonts',**_font_inputs())
        document=replace(document,pages=paginate(blocks,fonts,settings.SWB_DATA_ROOT))
        from app.operations.models import ExportRetirementRecord
        retired_ids=set(ExportRetirementRecord.objects.filter(household=owner).values_list('snapshot__export_id',flat=True))
        directory,exported=export_document(document,root,fonts,manifest,asset_root=settings.SWB_DATA_ROOT,
            forbidden_export_ids=retired_ids)
    manifest_raw=(directory/'snapshot.json').read_bytes()
    row,_=ExportSnapshot.objects.get_or_create(household=owner,export_id=exported['export_id'],defaults={
        'purpose':purpose,'title':title,'storage_key':str(directory.relative_to(Path(settings.SWB_DATA_ROOT).resolve())),
        'manifest_sha256':digest(manifest_raw),'provenance':provenance,'created_by':actor})
    return row


@transaction.atomic
def export_evidence_report(actor,learner_entity_pk):
    from app.study.services import evidence_report
    from app.web.learning_labels import label as learning_label, ATTEMPT_STATE_LABELS
    learner=EntityRecord.objects.get(pk=learner_entity_pk,kind='learner')
    owner=records.household(actor,learner.household_id,write=True)
    report=evidence_report(actor,learner.pk)
    # Freeze real review projections and source references, not a mastery score.
    provenance={'report':report,'learner_entity_id':learner.pk}
    title='学习证据报告：'+report['learner']['display_name'][:30]
    blocks=[Block('title',escape(title),'title'),Block('p',
        '逐次记录实际审核状态。课堂、提示后、来源不明、空白和不清晰的作答分别保留；未知不推断为掌握。','instruction')]
    for attempt in report['attempts']:
        blocks.append(Block('h',escape(attempt['question_text'][:120]),'assessment'))
        fields=[('作答身份','attempt_id'),('作答版本','attempt_revision_id'),('题目版本','question_revision_id'),
                ('作答状态','state'),('实际日期','actual_date'),('录入时间','recorded_at'),('来源类型','source_kind'),
                ('独立性','independence'),('提示情况','prompt_status'),('可读性','legibility')]
        descriptions=[]
        for label,field in fields:
            value=attempt.get(field + '_label',attempt.get(field))
            if field=='state':value=learning_label(ATTEMPT_STATE_LABELS,value)
            descriptions.append(f'{label}：{value or "未知"}')
        details='\n'.join(descriptions)
        details+='\n独立成功证据：'+('符合当前人工证据条件' if attempt['independent_success'] else '未确认')
        blocks.append(Block('small',escape(details).replace('\n','<br/>'),'assessment'))
        for assessment in attempt['assessments']:
            blocks.append(Block('p',escape('评价 '+assessment['assessment_revision_id']+'；实际审核状态 '+assessment['review_state_label']),'assessment'))
            for dimension in assessment['dimensions']:
                text=f"{dimension['dimension_label']}：{dimension['judgment_label']} / {dimension['basis_label']}\n{dimension['rationale']}"
                if dimension['unknown_reason']:text+='\n未知原因：'+dimension['unknown_reason']
                for source in dimension['sources']:
                    text+='\n来源：'+source['image_id']+' / '+(source['region_revision_id'] or '整图')
                blocks.append(Block('small',escape(text).replace('\n','<br/>'),'assessment'))
    for label,key in [('已观察到的方法或过程','observed_correct_methods'),('证据不足或未知','insufficient_evidence'),
            ('重复错误证据','repeated_errors'),('已知实际日期间隔','known_actual_date_intervals')]:
        blocks.append(Block('h',label,'assessment'))
        for row in report[key]:
            if key=='known_actual_date_intervals':
                text=f"{row['from_actual_date']} → {row['to_actual_date']}：间隔 {row['days']} 天；作答 {row['from_attempt_id']} → {row['to_attempt_id']}"
            elif key=='repeated_errors':
                text=f"题目 {row['question_id']} · {row['dimension_label']} · {row['occurrence_count']} 次。"
                text+='\n'+'\n'.join(f"作答 {item['attempt_id']} · 评价 {item['assessment_revision_id']} · {item['judgment_label']}" for item in row['evidence'])
            elif key=='insufficient_evidence':
                text=f"作答 {row['attempt_id']} · {row.get('dimension_label') or '整体'}：{row['reason']}"
            else:
                text=f"{row['dimension_label']} · 作答 {row['attempt_id']} · 评价 {row['assessment_revision_id']}"
            blocks.append(Block('small',escape(text).replace('\n','<br/>'),'assessment'))
        if not report[key]:blocks.append(Block('small','暂无符合条件的证据。','assessment'))
    source_hash=digest(canonical(provenance))
    # A report intentionally contains both reviewed and unknown records.
    return _export_blocks(actor,owner,title,'evidence_report',blocks,provenance,source_hash,None)


@transaction.atomic
def snapshot_file(actor, snapshot_id, name):
    row=ExportSnapshot.objects.get(pk=snapshot_id)
    records.household(actor,row.household_id)
    from app.operations.services import snapshot_availability
    if snapshot_availability(actor, snapshot_id)['status']=='retired':
        raise core.PersistenceError('snapshot_retired','此导出文件已退役；来源版本及退役账本仍保留。')
    if name not in {'document.pdf','document.docx','content.json','snapshot.json'}:
        raise core.PersistenceError('invalid_input','文件类型无效。')
    manifest_path=materials.asset_path(row.storage_key+'/snapshot.json',row.manifest_sha256)
    manifest=verify_snapshot(manifest_path.parent)
    if name=='snapshot.json':return manifest_path
    return materials.asset_path(row.storage_key+'/'+name,manifest['files'][name]['sha256'])
