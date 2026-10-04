import json
import zipfile
from unittest.mock import patch

from django.test import Client, TransactionTestCase
from django.urls import reverse

from app.exports.contracts import ExportError, digest
from app.persistence import services as core
from app.persistence.models import RevisionRecord
from app.printing import packets, services
from app.printing.models import TeacherAnswerRevision
from app.web import services as materials
from tests.printing import test_services as fixtures
from tests.web.test_services import key


class FiveBookTests(TransactionTestCase):
    setUp=fixtures.PrintTests.setUp
    tearDown=fixtures.PrintTests.tearDown
    page=fixtures.PrintTests.page
    source=fixtures.PrintTests.source
    question=fixtures.PrintTests.question
    published=fixtures.PrintTests.published
    def test_packet_freezes_five_purposes_repeats_and_rejects_modified_files(self):
        q=self.published()
        self.assertFalse(packets.readiness(self.owner,self.material.pk)['ready'])
        answer=services.save_answer(self.owner,self.house.pk,q.pk,body='1/2',formulas=[],basis='通分复算',
            expected=services.answer_context(q),request_key=key(),confirm=True)
        self.assertEqual(services.accepted_answer(q)[0].pk,answer['answer_id'])
        packet_id=packets.generate(self.owner,self.material.pk)
        self.assertEqual(packets.generate(self.owner,self.material.pk),packet_id)
        material,manifest=packets.read(self.viewer,self.material.pk,packet_id)
        self.assertEqual([b['purpose'] for b in manifest['books']],[p for p,_ in packets.BOOKS])
        self.assertEqual(manifest['question_revisions'],[q.pk])
        self.assertEqual(manifest['evidence_scope'],'not_recorded')
        with packets.archive(self.owner,material.pk,packet_id) as spool,zipfile.ZipFile(spool) as archive:
            self.assertEqual(len(archive.namelist()),21)
            for book in manifest['books']:
                for name,record in book['files'].items():
                    self.assertEqual(digest(archive.read(book['label']+'/'+name)),record['sha256'])
            report=json.loads(archive.read('03_学习证据与待测项目/content.json'))
            self.assertIn('未知',json.dumps(report,ensure_ascii=False))
            practice=json.loads(archive.read('04_独立复测无提示/content.json'))
            self.assertTrue(all(b['role'] in {'title','question','instruction','answer_space'} for p in practice['pages'] for b in p))
        with self.assertRaises(core.PersistenceError):packets.read(self.other,material.pk,packet_id)
        with self.assertRaises(core.PersistenceError):packets.generate(self.viewer,material.pk)
        old=manifest['books'][3]
        path=services.snapshot_file(self.owner,old['snapshot_id'],'document.pdf')
        path.write_bytes(b'broken')
        with self.assertRaises(ExportError):packets.archive(self.owner,material.pk,packet_id)

    def test_new_draft_blocks_new_packet_and_old_packet_keeps_its_versions(self):
        q=self.published()
        services.save_answer(self.owner,self.house.pk,q.pk,body='1/2',formulas=[],basis='通分复算',
            expected=services.answer_context(q),request_key=key(),confirm=True)
        packet_id=packets.generate(self.owner,self.material.pk)
        before=packets.read(self.owner,self.material.pk,packet_id)[1]
        context=materials.question_detail(self.owner,q.entity.stable_id)['edit_context']
        materials.save_question(self.owner,self.material.pk,question_id=q.entity.stable_id,printed_text='2+4=?',
            sources=[self.source(self.page())],original_number='1',reason='新修订未核对',expected_context=context,request_key=key())
        with self.assertRaises(core.PersistenceError) as caught:packets.generate(self.owner,self.material.pk)
        self.assertEqual(caught.exception.code,'packet_incomplete')
        self.assertEqual(packets.read(self.owner,self.material.pk,packet_id)[1],before)

    def test_answer_confirm_rolls_back_on_failed_confirmation_and_replays(self):
        q=self.published()
        inputs=dict(body='1/2',formulas=[],basis='复算',expected=services.answer_context(q),request_key=key(),confirm=True)
        before=TeacherAnswerRevision.objects.count()
        with patch('app.printing.services.review_answer',side_effect=core.PersistenceError('probe','合成失败')):
            with self.assertRaises(core.PersistenceError):services.save_answer(self.owner,self.house.pk,q.pk,**inputs)
        self.assertEqual(TeacherAnswerRevision.objects.count(),before)
        answer=services.save_answer(self.owner,self.house.pk,q.pk,**inputs)
        self.assertEqual(services.save_answer(self.owner,self.house.pk,q.pk,**inputs),answer)
        self.assertEqual(services.accepted_answer(q)[0].decisions.count(),1)

    def test_http_packet_requires_csrf_and_supports_owner_download(self):
        q=self.published()
        services.save_answer(self.owner,self.house.pk,q.pk,body='1/2',formulas=[],basis='复算',
            expected=services.answer_context(q),request_key=key(),confirm=True)
        url=reverse('printing:packet_prepare',kwargs={'material_id':self.material.pk})
        protected=Client(enforce_csrf_checks=True); protected.force_login(self.owner)
        self.assertEqual(protected.post(url,{}).status_code,403)
        self.client.force_login(self.owner)
        response=self.client.post(url,{})
        self.assertEqual(response.status_code,302,response.content.decode())
        self.assertContains(self.client.get(response.headers['Location']),'下载五册与校验清单 ZIP')
        packet_id=response.headers['Location'].rstrip('/').split('/')[-1]
        downloaded=self.client.get(reverse('printing:packet_download',kwargs={'material_id':self.material.pk,'packet_id':packet_id}))
        self.assertEqual(downloaded.status_code,200)
        downloaded.close()

    def test_five_books_support_more_than_thirty_questions_without_dropping_any(self):
        source=self.source(self.page())
        revision_ids=[]
        for index in range(31):
            saved=materials.save_question(self.owner,self.material.pk,printed_text=f'{index+1}. 1+1=?',
                original_number=str(index+1),sources=[source],reason='合成批次核对',request_key=key(),confirm=True)
            revision_ids.append(saved['revision_id'])
            question=RevisionRecord.objects.get(pk=saved['revision_id'])
            services.save_answer(self.owner,self.house.pk,question.pk,body='2',formulas=[],basis='合成加法复算',
                expected=services.answer_context(question),request_key=key(),confirm=True)
        with self.assertRaises(core.PersistenceError):
            services.export_questions(self.owner,self.house.pk,revision_ids,title='普通单册',purpose='independent_practice')
        packet_id=packets.generate(self.owner,self.material.pk)
        _,manifest=packets.read(self.owner,self.material.pk,packet_id)
        self.assertEqual(manifest['question_revisions'],revision_ids)
        practice=next(book for book in manifest['books'] if book['purpose']=='independent_practice')
        document=json.loads(services.snapshot_file(self.owner,practice['snapshot_id'],'content.json').read_bytes())
        self.assertGreater(len(document['pages']),1)
        blocks=[block for page in document['pages'] for block in page]
        self.assertEqual(sum(block['role']=='question' for block in blocks),31)
        self.assertEqual(sum(block['kind']=='space' for block in blocks),31)

    def test_preflight_lists_unconfirmed_practice_image_and_creates_no_packet(self):
        saved=materials.save_question(self.owner,self.material.pk,printed_text='sqrt(x)',
            display_markup='[[image:1|sqrt(x)]]',sources=[self.source(self.page())],
            original_number='图片待核对',reason='原图含未知内容',request_key=key(),confirm=True)
        question=RevisionRecord.objects.get(pk=saved['revision_id'])
        services.save_answer(self.owner,self.house.pk,question.pk,body='合成答案',formulas=[],basis='合成核对',
            expected=services.answer_context(question),request_key=key(),confirm=True)
        state=packets.readiness(self.owner,self.material.pk)
        self.assertFalse(state['ready'])
        self.assertTrue(any('图片尚未确认' in gap for gap in state['gaps']))
        with self.assertRaises(core.PersistenceError):packets.generate(self.owner,self.material.pk)
        from app.printing.models import ExportSnapshot
        self.assertEqual(ExportSnapshot.objects.count(),0)
