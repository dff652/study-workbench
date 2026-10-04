import io
from pathlib import Path
import tempfile
import uuid
import unittest
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from app.persistence import services as core
from app.persistence.models import HouseholdMember,ImageRecord,EntityRecord,ReviewDecision
from app.web import services
from app.web.images import original_bbox,preview_bytes,digest
from app.web.models import MaterialPage,PagePreview,QuestionSource


def image_bytes(color='white',exif=False):
    image=Image.new('RGB',(80,60),color)
    image.putpixel((0,0),(255,0,0))
    result=io.BytesIO()
    if exif:
        info=Image.Exif();info[274]=6;image.save(result,format='PNG',exif=info)
    else:
        image.save(result,format='PNG')
    return result.getvalue()


def upload(name='source.png',raw=None):
    return SimpleUploadedFile(name,raw if raw is not None else image_bytes(),content_type='text/plain')


def key():
    return uuid.uuid4().hex


class GeometryTests(SimpleTestCase):
    def test_quarter_turn_inverse_rectangles_and_visible_corner(self):
        expected={0:(5,10,30,40),90:(10,30,40,55),180:(50,20,75,50),270:(40,5,70,30)}
        for rotation,box in expected.items():
            self.assertEqual(original_bbox([5,10,30,40],80,60,rotation),box)
        png,w,h=preview_bytes(image_bytes(exif=True),90)
        self.assertEqual((w,h),(60,80))
        with Image.open(io.BytesIO(png)) as image:
            self.assertEqual(image.getpixel((59,0)),(255,0,0))
            self.assertFalse(image.getexif())

    def test_invalid_geometry_and_nonfinite_input_fail(self):
        for box,rotation in [([0,0,0,10],0),([0,0,81,60],0),([0,0,float('nan'),10],0),([0,0,1,1],45)]:
            with self.assertRaises(core.PersistenceError): original_bbox(box,80,60,rotation)


class ManualServicesTests(TransactionTestCase):
    def setUp(self):
        User=get_user_model()
        self.owner=User.objects.create_user('owner',password='synthetic-only')
        self.viewer=User.objects.create_user('viewer',password='synthetic-only')
        self.other=User.objects.create_user('other',password='synthetic-only')
        self.house=core.create_household(self.owner,'house-one')
        self.other_house=core.create_household(self.other,'house-two')
        HouseholdMember.objects.create(household=self.house,user=self.viewer,role='viewer')
        self.temporary=tempfile.TemporaryDirectory(prefix='swb-web-tests-')
        self.override=override_settings(SWB_DATA_ROOT=self.temporary.name);self.override.enable()
        self.material=services.create_material(self.owner,self.house.pk,'合成资料',key())

    def tearDown(self):
        self.override.disable();self.temporary.cleanup()

    def page(self,name='source.png',raw=None):
        return services.upload_page(self.owner,self.material.pk,upload(name,raw),key())['page_id']

    def source(self,page_id,rotation=0):
        preview=services.preview_file(self.owner,page_id,rotation)
        return {'page_id':page_id,'rotation':rotation,'preview_sha256':preview.sha256,'display_bbox':[5,10,30,40]}

    def question(self,sources=None,text='2＋3＝？'):
        sources=sources if sources is not None else [self.source(self.page())]
        return services.save_question(self.owner,self.material.pk,printed_text=text,original_number='J1-1',sources=sources,
            request_key=key(),reason='按原图录入')

    def test_save_and_confirm_is_atomic_idempotent_and_preserves_history(self):
        source=self.source(self.page());request=key()
        inputs=dict(printed_text='2＋3＝？',original_number='合成1',sources=[source],
            request_key=request,reason='已对照原图核对',confirm=True)
        first=services.save_question(self.owner,self.material.pk,**inputs)
        self.assertEqual(first,services.save_question(self.owner,self.material.pk,**inputs))
        entity=EntityRecord.objects.get(stable_id=first['question_id'],household=self.house)
        self.assertEqual(entity.published_revision_id,first['revision_id'])
        self.assertEqual(ReviewDecision.objects.filter(revision_id=first['revision_id']).count(),1)
        context=services.question_detail(self.owner,entity.stable_id)['edit_context']
        second=services.save_question(self.owner,self.material.pk,**{**inputs,'printed_text':'2＋4＝？',
            'question_id':entity.stable_id,'expected_context':context,'request_key':key()})
        entity.refresh_from_db();self.assertEqual(entity.published_revision_id,second['revision_id'])
        self.assertEqual(entity.revisions.count(),2)
        self.assertEqual(entity.revisions.get(pk=first['revision_id']).payload['printed_text'],'2＋3＝？')

    def test_confirmation_does_not_accept_blank_or_leave_a_partial_save(self):
        source=self.source(self.page());before=EntityRecord.objects.count()
        with self.assertRaises(core.PersistenceError):
            services.save_question(self.owner,self.material.pk,printed_text='',original_number='合成空白',
                sources=[source],request_key=key(),reason='来源待补',confirm=True)
        self.assertEqual(EntityRecord.objects.count(),before)
        with patch('app.web.services.core.review_revision',side_effect=core.PersistenceError('probe','合成失败')):
            with self.assertRaises(core.PersistenceError):
                services.save_question(self.owner,self.material.pk,printed_text='2＋3＝？',original_number='合成回滚',
                    sources=[source],request_key=key(),reason='合成事务回滚',confirm=True)
        self.assertEqual(EntityRecord.objects.count(),before)

    def test_duplicate_bytes_reuse_image_but_keep_source_associations_and_replay(self):
        request_key=key()
        first=services.upload_page(self.owner,self.material.pk,upload(),request_key)
        repeated=services.upload_page(self.owner,self.material.pk,upload(),request_key)
        duplicate=services.upload_page(self.owner,self.material.pk,upload('renamed.jpg'),key())
        self.assertEqual(first,repeated);self.assertTrue(duplicate['duplicate_image'])
        self.assertEqual(ImageRecord.objects.count(),1);self.assertEqual(MaterialPage.objects.count(),2)
        self.assertEqual(PagePreview.objects.count(),4)
        image=ImageRecord.objects.get()
        self.assertEqual(services.asset_path(image.payload['storage_key'],image.sha256).read_bytes(),image_bytes())
        root=Path(self.temporary.name)
        for path in [root,*root.rglob('*')]:
            self.assertEqual(path.stat().st_mode&0o777,0o700 if path.is_dir() else 0o600)

    def test_invalid_decode_size_and_pixels_do_not_create_metadata_or_files(self):
        for file,patcher in [(upload(raw=b'<html>wrong</html>'),patch('app.web.images.MAX_PIXELS',16_000_000)),
                (upload(),patch('app.web.images.MAX_PIXELS',10)),(upload(),patch('app.web.images.MAX_UPLOAD_BYTES',8))]:
            with patcher,self.assertRaises(core.PersistenceError): services.upload_page(self.owner,self.material.pk,file,key())
        self.assertEqual(ImageRecord.objects.count(),0);self.assertEqual(MaterialPage.objects.count(),0)
        self.assertEqual(list(Path(self.temporary.name).rglob('*.png')),[])

    def test_late_database_failure_rolls_back_metadata_and_only_new_files(self):
        original=core._receipt
        def fail(house,actor,request_key,operation,fingerprint,result):
            if operation=='web_upload': raise core.PersistenceError('synthetic_failure','late failure')
            return original(house,actor,request_key,operation,fingerprint,result)
        with patch.object(core,'_receipt',side_effect=fail),self.assertRaises(core.PersistenceError):
            services.upload_page(self.owner,self.material.pk,upload(),key())
        self.assertEqual(ImageRecord.objects.count(),0);self.assertEqual(PagePreview.objects.count(),0)
        self.assertEqual(MaterialPage.objects.count(),0)
        self.assertEqual(list(Path(self.temporary.name).rglob('*.png')),[])

    def test_permissions_recheck_active_account_and_membership(self):
        page=self.page()
        services.page_detail(self.viewer,page)
        for actor in (self.viewer,self.other):
            with self.assertRaises(core.PersistenceError): services.upload_page(actor,self.material.pk,upload(),key())
        with self.assertRaises(core.PersistenceError): services.page_detail(self.other,page)
        self.owner.is_active=False;self.owner.save()
        with self.assertRaises(core.PersistenceError): services.page_detail(self.owner,page)

    def test_reordering_requires_complete_permutation_and_preserves_image_identity(self):
        pages=[self.page('first.png'),self.page('second.png')]
        result=services.reorder_pages(self.owner,self.material.pk,list(reversed(pages)),key())
        self.assertEqual([str(p.pk) for p in services.material_detail(self.owner,self.material.pk)['pages']],list(reversed(pages)))
        with self.assertRaises(core.PersistenceError): services.reorder_pages(self.owner,self.material.pk,[pages[0],pages[0]],key())
        self.assertEqual(ImageRecord.objects.count(),1)

    def test_multiple_sources_and_rotation_bind_original_regions_without_learning_inference(self):
        pages=[self.page(),self.page('second.png',image_bytes('blue'))]
        sources=[self.source(pages[0],90),self.source(pages[1],270)]
        saved=self.question(sources)
        detail=services.question_detail(self.owner,saved['question_id'])
        self.assertEqual(detail['sources'][0]['original_bbox'],[10,30,40,55])
        self.assertEqual(detail['sources'][1]['original_bbox'],[40,5,70,30])
        self.assertEqual([ref['sequence'] for ref in detail['current']['evidence_refs']],[1,2])
        self.assertEqual(len(services.page_detail(self.owner,pages[0])['questions']),1)
        self.assertFalse(EntityRecord.objects.filter(kind__in=('learner','attempt','assessment','observation')).exists())

    def test_edit_preserves_old_content_geometry_publication_and_rejects_stale_context(self):
        saved=self.question();detail=services.question_detail(self.owner,saved['question_id'])
        services.review_question(self.owner,saved['question_id'],saved['revision_id'],action='accept',reason='已核对印刷题干和区域',
            context=detail['review_context'],request_key=key())
        old_sources=detail['sources'];old_payload=detail['current']
        source={**old_sources[0],'display_bbox':[1,2,40,50]}
        changed=services.save_question(self.owner,self.material.pk,printed_text='2＋4＝？',original_number='J1-1',sources=[source],
            question_id=saved['question_id'],expected_context=detail['edit_context'],reason='按原图更正录入',request_key=key())
        current=services.question_detail(self.owner,saved['question_id'])
        self.assertNotEqual(saved['revision_id'],changed['revision_id']);self.assertEqual(len(current['history']),2)
        entity=current['question'];self.assertEqual(entity.published_revision_id,saved['revision_id'])
        self.assertEqual(current['history'][1].payload,old_payload)
        self.assertEqual(QuestionSource.objects.get(revision_id=saved['revision_id']).sources,old_sources)
        with self.assertRaises(core.PersistenceError):
            services.save_question(self.owner,self.material.pk,printed_text='stale',original_number='J1-1',sources=[source],
                question_id=saved['question_id'],expected_context=detail['edit_context'],reason='stale',request_key=key())
        with self.assertRaises(core.PersistenceError):
            services.review_question(self.owner,saved['question_id'],saved['revision_id'],action='reject',reason='stale',
                context=detail['review_context'],request_key=key())

    def test_empty_text_is_missing_and_cannot_be_accepted(self):
        saved=self.question(text='');detail=services.question_detail(self.owner,saved['question_id'])
        self.assertTrue(detail['current']['missing_fields'])
        with self.assertRaises(core.PersistenceError):
            services.review_question(self.owner,saved['question_id'],saved['revision_id'],action='accept',reason='cannot accept',
                context=detail['review_context'],request_key=key())
        self.assertEqual(ReviewDecision.objects.count(),0)

    def test_foreign_page_and_tampered_preview_cannot_be_sources(self):
        material=services.create_material(self.other,self.other_house.pk,'other',key())
        foreign=services.upload_page(self.other,material.pk,upload(),key())['page_id']
        with self.assertRaises(MaterialPage.DoesNotExist): self.question([{'page_id':foreign,'rotation':0,'preview_sha256':'a'*64,'display_bbox':[0,0,1,1]}])
        page=self.page();preview=services.preview_file(self.owner,page,0)
        path=services.asset_path(preview.storage_key,preview.sha256);path.write_bytes(b'changed')
        with self.assertRaises(core.PersistenceError): self.question([self.source(page)])
        self.assertEqual(EntityRecord.objects.filter(kind='question').count(),0)

    def test_native_page_family_and_append_only_source_guards(self):
        page=MaterialPage.objects.get(pk=self.page());preview=PagePreview.objects.first()
        other_material=services.create_material(self.other,self.other_house.pk,'other',key())
        with self.assertRaises(DatabaseError),transaction.atomic():
            MaterialPage.objects.create(material=other_material,image=page.image,position=1,original_name='bad')
        with self.assertRaises(DatabaseError),transaction.atomic():
            PagePreview.objects.filter(pk=preview.pk).update(sha256='b'*64)
        saved=self.question([self.source(str(page.pk))])
        with self.assertRaises(DatabaseError),transaction.atomic():
            QuestionSource.objects.filter(pk=saved['revision_id']).update(original_number='changed')
