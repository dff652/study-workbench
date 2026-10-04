"""Household-scoped manual ingestion; domain revisions and reviews stay append-only."""
from dataclasses import fields, replace
import fcntl
import os
from pathlib import Path
import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from app.domain.contracts import (Bundle, SCHEMA_VERSION, SourceImage, Question, QuestionRevision,
    RegionRevision, RevisionHeader, Origin, ReviewState, EvidenceRef, EvidencePurpose, Granularity, seal_revision)
from app.persistence import services as core
from app.persistence.adapter import ObjectKey
from app.persistence.models import Household, HouseholdMember, ImageRecord, EntityRecord, RevisionRecord, EvidenceRecord
from .images import digest, uploaded_bytes, preview_bytes, original_bbox, ROTATIONS
from .models import MaterialSet, MaterialPage, PagePreview, QuestionSource


def _text(value, limit, *, blank=False):
    if not isinstance(value,str) or len(value)>limit or ('\x00' in value) or (not blank and not value.strip()):
        raise core.PersistenceError('invalid_input','输入内容为空或超过上限。')
    return value.strip()


def _household(actor, household_id, write=False):
    household=Household.objects.select_for_update().get(pk=household_id)
    core.require_household_access(actor,household,write=write)
    return household


def list_households(actor):
    return HouseholdMember.objects.filter(user=actor,user__is_active=True).select_related('household').order_by('household_id')


def list_materials(actor):
    return MaterialSet.objects.filter(household__memberships__user=actor,
        household__memberships__user__is_active=True).select_related('household').order_by('-created_at')


def _material(actor, material_id, write=False):
    material=MaterialSet.objects.select_related('household').get(pk=material_id)
    _household(actor,material.household_id,write)
    return material


@transaction.atomic
def create_material(actor, household_id, title, request_key):
    household=_household(actor,household_id,True)
    title=_text(title,160)
    fingerprint=core._digest({'household':household.pk,'title':title})
    previous=core._replay(household,actor,request_key,'web_material',fingerprint)
    if previous:
        return MaterialSet.objects.get(pk=previous['material_id'],household=household)
    material=MaterialSet.objects.create(household=household,title=title,created_by=actor)
    core._receipt(household,actor,request_key,'web_material',fingerprint,{'material_id':str(material.pk)})
    return material


@transaction.atomic
def material_detail(actor,material_id):
    material=_material(actor,material_id)
    return {'material':material,'pages':list(material.pages.select_related('image').order_by('position'))}


def _root():
    if not settings.SWB_DATA_ROOT:
        raise ImproperlyConfigured('Set SWB_DATA_ROOT explicitly before uploading or reading files')
    root=Path(settings.SWB_DATA_ROOT).resolve()
    root.mkdir(parents=True,mode=0o700,exist_ok=True)
    if not root.is_dir() or root.stat().st_mode&0o077:
        raise core.PersistenceError('unsafe_storage','资料目录必须为私有目录。')
    return root


def asset_path(key,sha256):
    root=_root();relative=Path(key);path=(root/relative).resolve()
    if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root) or not path.is_file():
        raise core.PersistenceError('missing_asset','来源文件缺失或路径无效。')
    if digest(path.read_bytes())!=sha256:
        raise core.PersistenceError('asset_changed','来源文件哈希不一致。')
    return path


def _install(root,key,raw,created):
    path=(root/key).resolve()
    if not path.is_relative_to(root):
        raise core.PersistenceError("invalid_storage", "存储路径离开资料目录。")
    if path.exists():
        asset_path(key,digest(raw))
        return
    path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    parent=path.parent
    while parent.is_relative_to(root) and parent!=root:
        parent.chmod(0o700);parent=parent.parent
    temporary=path.parent/f'.writing-{uuid.uuid4().hex}'
    try:
        fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as handle:
            handle.write(raw);handle.flush();os.fsync(handle.fileno())
        temporary.rename(path)
        created.append(path)
    finally:
        temporary.unlink(missing_ok=True)


def _empty_bundle(household_id):
    return Bundle(schema_version=SCHEMA_VERSION,household_id=household_id,
        **{field.name:() for field in fields(Bundle) if field.name not in ('schema_version','household_id')})


def _previews(image,raw,root,created):
    for rotation in ROTATIONS:
        previous=PagePreview.objects.filter(image=image,rotation=rotation).first()
        if previous:
            asset_path(previous.storage_key,previous.sha256)
            continue
        png,width,height=preview_bytes(raw,rotation)
        key=f'web/{digest(image.household_id.encode())[:24]}/preview/{image.sha256}-{rotation}.png'
        _install(root,key,png,created)
        PagePreview.objects.create(image=image,rotation=rotation,width=width,height=height,sha256=digest(png),storage_key=key)


def upload_page(actor,material_id,uploaded_file,request_key):
    # One lock covers file install, durable DB commit/rollback, and failure cleanup.
    # This avoids deleting a new file that another request has already reused.
    material=MaterialSet.objects.select_related('household').get(pk=material_id)
    core.require_household_access(actor,material.household,write=True)
    raw,fmt,width,height=uploaded_bytes(uploaded_file)
    sha=digest(raw)
    name=str(uploaded_file.name).replace('\\','/').split('/')[-1][:255]
    fingerprint=core._digest({'material':str(material.pk),'sha':sha,'name':name})
    root=_root();created=[]
    descriptor=os.open(root/'.web-files.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            with transaction.atomic(durable=True):
                material=_material(actor,material_id,True)
                previous=core._replay(material.household,actor,request_key,'web_upload',fingerprint)
                if previous:
                    page=MaterialPage.objects.get(pk=previous['page_id'],material=material)
                    asset_path(page.image.payload['storage_key'],page.image.sha256)
                    if page.image.web_previews.count()!=4:
                        raise core.PersistenceError('missing_asset','预览记录不完整。')
                    for preview in page.image.web_previews.all(): asset_path(preview.storage_key,preview.sha256)
                    return previous
                image=ImageRecord.objects.filter(household=material.household,sha256=sha).first()
                duplicate=image is not None
                if image:
                    asset_path(image.payload['storage_key'],sha)
                else:
                    ext,media=('jpg','image/jpeg') if fmt=='JPEG' else ('png','image/png')
                    key=f'web/{digest(material.household_id.encode())[:24]}/original/{sha}.{ext}'
                    _install(root,key,raw,created)
                    record=SourceImage(f'web-image-{sha}',material.household_id,sha,key,media,width,height,timezone.now().isoformat())
                    core.stage_bundle(actor,replace(_empty_bundle(material.household_id),images=(record,)),
                        request_key=f'image-stage-{uuid.uuid4().hex}',expected_heads={})
                    image=ImageRecord.objects.get(household=material.household,sha256=sha)
                _previews(image,raw,root,created)
                position=material.pages.count()+1
                page=MaterialPage.objects.create(material=material,image=image,position=position,original_name=name)
                return core._receipt(material.household,actor,request_key,'web_upload',fingerprint,
                    {'page_id':str(page.pk),'duplicate_image':duplicate,'position':position})
        except BaseException:
            for path in reversed(created): path.unlink(missing_ok=True)
            raise


@transaction.atomic
def reorder_pages(actor,material_id,page_ids,request_key):
    material=_material(actor,material_id,True)
    if not isinstance(page_ids,list) or any(not isinstance(v,str) for v in page_ids):
        raise core.PersistenceError('invalid_order','页序格式无效。')
    fingerprint=core._digest({'material':str(material.pk),'pages':page_ids})
    previous=core._replay(material.household,actor,request_key,'web_order',fingerprint)
    if previous: return previous
    pages=list(material.pages.all())
    if len(page_ids)!=len(pages) or set(page_ids)!={str(page.pk) for page in pages}:
        raise core.PersistenceError('invalid_order','新顺序必须包含资料的每一页，且不得重复。')
    mapping={str(page.pk):page for page in pages}
    for position,page_id in enumerate(page_ids,1): mapping[page_id].position=position
    MaterialPage.objects.bulk_update(pages,['position'])
    return core._receipt(material.household,actor,request_key,'web_order',fingerprint,{'page_ids':page_ids})


def _page(actor,page_id):
    page=MaterialPage.objects.select_related('material__household','image').get(pk=page_id)
    _household(actor,page.material.household_id)
    if page.image.household_id!=page.material.household_id:
        raise core.PersistenceError('permission_denied','来源不属于该家庭。')
    return page


@transaction.atomic
def page_detail(actor,page_id):
    page=_page(actor,page_id)
    question_ids=EvidenceRecord.objects.filter(image=page.image,source__entity__kind='question').values_list('source__entity_id',flat=True)
    return {'page':page,'previews':list(page.image.web_previews.order_by('rotation')),
        'questions':list(EntityRecord.objects.filter(pk__in=question_ids,household=page.material.household))}


@transaction.atomic
def preview_file(actor,page_id,rotation):
    page=_page(actor,page_id)
    if type(rotation) is not int or rotation not in ROTATIONS:
        raise core.PersistenceError('invalid_rotation','旋转角度无效。')
    return PagePreview.objects.get(image=page.image,rotation=rotation)


def _edit_context(row):
    vector=[]
    for item in row.dependency_heads:
        head=EntityRecord.objects.get(household=row.entity.household,kind=item['kind'],stable_id=item['stable_id']).head_revision_id
        vector.append({**item,'head_revision_id':head})
    return {'expected_head':row.pk,'expected_dependencies':vector}


@transaction.atomic
def question_detail(actor,question_id):
    question=EntityRecord.objects.select_related('household','head_revision').get(kind='question',stable_id=question_id,household__memberships__user=actor,household__memberships__user__is_active=True)
    _household(actor,question.household_id)
    row=question.head_revision
    metadata=QuestionSource.objects.select_related('material').filter(revision=row).first()
    return {'question':question,'material':metadata.material if metadata else None,
        'original_number':metadata.original_number if metadata else '派生题目',
        'current':row.payload,'history':list(question.revisions.select_related('review_projection').order_by('-revision_no')),
        'sources':metadata.sources if metadata else [],'edit_context':_edit_context(row),
        'review_context':core.review_context(actor,question.household_id,row.pk)}


def _header(actor,owner_id,reason,previous=None):
    return RevisionHeader(f'web-rev-{uuid.uuid4().hex}',owner_id,previous.revision_no+1 if previous else 1,
        previous.pk if previous else None,str(actor.pk),timezone.now().isoformat(),Origin.HUMAN,reason,'')


@transaction.atomic
def save_question(actor,material_id,*,printed_text,original_number,sources,request_key,reason,
                  question_id=None,expected_context=None,display_markup=None,image_print_confirmed=None,confirm=False):
    material=_material(actor,material_id,True)
    text=_text(printed_text,20000,blank=True);number=_text(original_number,80,blank=True);reason=_text(reason,1000)
    if type(confirm) is not bool:
        raise core.PersistenceError('invalid_input','请明确选择保存草稿或确认内容。')
    if confirm and not text:
        raise core.PersistenceError('incomplete_question','题干尚未补齐，请先保存待补草稿。')
    if not isinstance(sources,list) or not 1<=len(sources)<=30:
        raise core.PersistenceError('missing_region','至少选择一个题目区域。')
    normalized=[]
    for source in sources:
        if not isinstance(source,dict) or not {'page_id','rotation','preview_sha256','display_bbox'}.issubset(source):
            raise core.PersistenceError('invalid_region','区域字段不完整。')
        page=MaterialPage.objects.select_related('image').get(pk=source['page_id'],material=material)
        if page.image.household_id!=material.household_id or type(source['rotation']) is not int:
            raise core.PersistenceError('invalid_region','来源或角度无效。')
        preview=preview_file(actor,page.pk,source['rotation'])
        if preview.sha256!=source['preview_sha256']:
            raise core.PersistenceError('preview_changed','预览已改变，请重新框选。')
        asset_path(preview.storage_key,preview.sha256)
        box=original_bbox(source['display_bbox'],page.image.payload['width'],page.image.payload['height'],source['rotation'])
        normalized.append({'page_id':str(page.pk),'rotation':source['rotation'],'preview_sha256':preview.sha256,
            'display_bbox':list(source['display_bbox']),'original_bbox':list(box)})
    display_markup=_text(display_markup,24000,blank=True) if display_markup else None
    if image_print_confirmed is not None and type(image_print_confirmed) is not bool:
        raise core.PersistenceError('invalid_input','打印图片需要明确的人工核对。')
    image_print_confirmed=True if image_print_confirmed is True else None
    fingerprint=core._digest({'material':str(material.pk),'question':question_id,'text':text,'number':number,
        **({'display_markup':display_markup} if display_markup is not None else {}),
        **({'image_print_confirmed':True} if image_print_confirmed else {}),
        **({'confirm':True} if confirm else {}),
        'sources':normalized,'reason':reason,'context':expected_context})
    previous_request=core._replay(material.household,actor,request_key,'web_question',fingerprint)
    if previous_request: return previous_request
    existing=core.read_snapshot_bundle(actor,material.household_id)
    previous=None;old_metadata=None;expected_heads={}
    if question_id:
        entity=EntityRecord.objects.get(household=material.household,kind='question',stable_id=question_id)
        previous=entity.head_revision
        old_metadata=QuestionSource.objects.get(revision=previous,material=material)
        if not isinstance(expected_context,dict) or expected_context!=_edit_context(previous):
            raise core.PersistenceError('head_conflict','题目或来源版本已变化，请重新打开。')
        expected_heads[ObjectKey('question',question_id)]=previous.pk
        for item in expected_context['expected_dependencies']:
            expected_heads[ObjectKey(item['kind'],item['stable_id'])]=item['head_revision_id']
    else:
        question_id=f'web-q-{uuid.uuid4().hex}'
    refs=[];regions=[]
    for sequence,source in enumerate(normalized,1):
        page=MaterialPage.objects.select_related('image').get(pk=source['page_id'])
        old_source=old_metadata.sources[sequence-1] if old_metadata and len(old_metadata.sources)>=sequence else None
        old_region=RevisionRecord.objects.get(pk=old_source['region_revision_id']) if old_source else None
        if old_region and old_region.original_image_id==page.image_id:
            region_id=old_region.entity.stable_id
            old_region=old_region.entity.head_revision
            expected_heads[ObjectKey('region',region_id)]=old_region.pk
        else:
            region_id=f'web-region-{uuid.uuid4().hex}';old_region=None
        region=seal_revision(RegionRevision(region_id,material.household_id,_header(actor,region_id,reason,old_region),
            page.image.stable_id,'original_pixels',tuple(source['original_bbox']),'question'))
        regions.append(region)
        source.update(region_revision_id=region.header.revision_id,sequence=sequence)
        refs.append(EvidenceRef(material.household_id,page.image.stable_id,page.image.sha256,Granularity.REGION,
            region_id,region.header.revision_id,False,EvidencePurpose.QUESTION,sequence))
    parent_revision=previous.payload.get('parent_question_revision_id') if previous else None
    unchanged_print=bool(previous and text==previous.payload.get('printed_text'))
    working_text=previous.payload.get('working_text') if unchanged_print else (text or None)
    erratum_ids=tuple(previous.payload.get('erratum_revision_ids',())) if unchanged_print else ()
    from app.domain.presentation import validate_display
    try:
        validate_display(display_markup,working_text,refs)
    except ValueError as exc:
        raise core.PersistenceError('invalid_display',str(exc)) from exc
    revision=seal_revision(QuestionRevision(_header(actor,question_id,reason,previous),ReviewState.DRAFT,parent_revision,
        text or None,working_text,() if text else ('printed_text','working_text'),tuple(refs),erratum_ids,display_markup,image_print_confirmed))
    questions=tuple(replace(q,revisions=(*q.revisions,revision)) if q.question_id==question_id else q for q in existing.questions)
    if previous is None: questions=(*questions,Question(question_id,material.household_id,None,(revision,)))
    bundle=replace(existing,regions=(*existing.regions,*regions),questions=questions)
    core.stage_bundle(actor,bundle,request_key=f'question-stage-{uuid.uuid4().hex}',expected_heads=expected_heads)
    QuestionSource.objects.create(revision_id=revision.header.revision_id,material=material,original_number=number,sources=normalized)
    if confirm:
        context=core.review_context(actor,material.household_id,revision.header.revision_id)
        core.review_revision(actor,material.household_id,revision.header.revision_id,action='accept',
            reason='家长保存并确认：'+reason,expected_head=context['expected_head'],
            expected_dependencies=context['expected_dependencies'],expected_decision_id=context['expected_decision_id'],
            request_key='confirm-'+core._digest({'request_key':request_key,'revision_id':revision.header.revision_id}))
    return core._receipt(material.household,actor,request_key,'web_question',fingerprint,
        {'question_id':question_id,'revision_id':revision.header.revision_id})


@transaction.atomic
def review_question(actor,question_id,revision_id,*,action,reason,context,request_key):
    entity=EntityRecord.objects.get(kind='question',stable_id=question_id,household__memberships__user=actor,household__memberships__user__is_active=True)
    _household(actor,entity.household_id,True)
    RevisionRecord.objects.get(pk=revision_id,entity=entity)
    if not isinstance(context,dict) or set(context)!={'expected_head','expected_dependencies','expected_decision_id','state'}:
        raise core.PersistenceError('invalid_context','审核凭据无效。')
    return core.review_revision(actor,entity.household_id,revision_id,action=action,reason=_text(reason,1000),
        expected_head=context['expected_head'],expected_dependencies=context['expected_dependencies'],
        expected_decision_id=context['expected_decision_id'],request_key=request_key)
