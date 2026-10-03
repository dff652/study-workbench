import json
from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.test import TransactionTestCase
from app.catalogue import services as catalogue
from app.catalogue.models import QuestionLabel
from app.persistence import services as core
from app.persistence.models import EntityRecord, HouseholdMember, RevisionRecord
from app.web import services as materials, records
from app.web import knowledge_services
from app.web.models import QuestionSource
from app.printing import services
from app.printing.models import TeacherAnswerRevision, AnswerDecision, ExportSnapshot
from tests.web.test_services import ManualServicesTests, key


class PrintTests(TransactionTestCase):
    setUp=ManualServicesTests.setUp
    tearDown=ManualServicesTests.tearDown
    page=ManualServicesTests.page
    source=ManualServicesTests.source
    question=ManualServicesTests.question

    def published(self,text='1/3 + 1/6 = ?'):
        q=self.question(text=text)
        context=core.review_context(self.owner,self.house.pk,q['revision_id'])
        core.review_revision(self.owner,self.house.pk,q['revision_id'],action='accept',reason='核对合成题干',
            request_key=key(),**{k:context[k] for k in ['expected_head','expected_dependencies','expected_decision_id']})
        return RevisionRecord.objects.get(pk=q['revision_id'])

    def answer(self,q,text='1/2'):
        return services.save_answer(self.owner,self.house.pk,q.pk,body=text,
            formulas=[['f',['t','1'],['t','2']]],basis='有理数通分复算',
            expected=services.answer_context(q),request_key=key())

    def accept_revision(self,revision_id):
        context=core.review_context(self.owner,self.house.pk,revision_id)
        return core.review_revision(self.owner,self.house.pk,revision_id,action='accept',reason='合成打印依赖验收',
            request_key=key(),**{k:context[k] for k in ['expected_head','expected_dependencies','expected_decision_id']})

    def withdraw_revision(self,revision_id):
        context=core.review_context(self.owner,self.house.pk,revision_id)
        return core.review_revision(self.owner,self.house.pk,revision_id,action='withdraw',reason='合成新增审核决定',
            request_key=key(),**{k:context[k] for k in ['expected_head','expected_dependencies','expected_decision_id']})

    def test_teacher_answers_append_review_replay_and_stale_guard(self):
        q=self.published();expected=services.answer_context(q);request_key=key()
        inputs=dict(body='1/2',formulas=[],basis='通分',expected=expected,request_key=request_key)
        first=services.save_answer(self.owner,self.house.pk,q.pk,**inputs)
        self.assertEqual(first,services.save_answer(self.owner,self.house.pk,q.pk,**inputs))
        a=TeacherAnswerRevision.objects.get(pk=first['answer_id'])
        services.review_answer(self.owner,a.pk,action='accepted',reason='独立复算',expected=services.answer_context(q),request_key=key())
        self.answer(q,'另一份解析')
        self.assertEqual(services.accepted_answer(q)[0].pk,a.pk)
        self.assertEqual(a.body,'1/2');self.assertEqual(TeacherAnswerRevision.objects.count(),2)
        with self.assertRaises(core.PersistenceError):services.save_answer(self.owner,self.house.pk,q.pk,**{**inputs,'request_key':key()})
        with self.assertRaises(DatabaseError),transaction.atomic():TeacherAnswerRevision.objects.filter(pk=a.pk).update(body='覆盖')
        with self.assertRaises(DatabaseError),transaction.atomic():AnswerDecision.objects.all().delete()

    def test_question_formula_emphasis_source_fallback_and_history(self):
        text='重点\n1/2\n(-2)^2\n(x^2)^3\nsqrt(x)'
        markup='**重点**\n[[math:1/2]]\n[[math:(-2)^2]]\n[[math:(x^2)^3]]\n[[image:1|sqrt(x)]]'
        result=materials.save_question(self.owner,self.material.pk,printed_text=text,display_markup=markup,
            image_print_confirmed=True,
            original_number='公式1',sources=[self.source(self.page())],request_key=key(),reason='合成排版核对')
        self.accept_revision(result['revision_id'])
        q=RevisionRecord.objects.get(pk=result['revision_id'])
        before=q.payload.copy()
        snapshot=services.export_questions(self.owner,self.house.pk,[q.pk],title='公式独立练习',purpose='independent_practice')
        raw=services.snapshot_file(self.owner,snapshot.pk,'content.json').read_bytes()
        content=json.loads(raw)
        blocks=[block for page in content['pages'] for block in page]
        self.assertEqual(sum(b['kind']=='math' for b in blocks),3)
        self.assertEqual(sum(b['kind']=='formula_image' for b in blocks),1)
        self.assertTrue(any('<b>重点</b>'==b.get('content') for b in blocks))
        self.assertFalse(any(b['role'] in {'answer','method','classification','assessment'} for b in blocks))
        import zipfile
        with zipfile.ZipFile(services.snapshot_file(self.owner,snapshot.pk,'document.docx')) as archive:
            xml=archive.read('word/document.xml').decode()
        self.assertIn('m:f',xml);self.assertIn('m:sSup',xml);self.assertIn('w:b',xml)
        edit=materials.question_detail(self.owner,q.entity.stable_id)
        materials.save_question(self.owner,self.material.pk,printed_text=text,display_markup=markup.replace('**重点**','==重点=='),
            original_number='公式1',sources=[self.source(self.page())],question_id=q.entity.stable_id,
            expected_context=edit['edit_context'],request_key=key(),reason='重点样式新版本')
        q.refresh_from_db();self.assertEqual(q.payload,before)
        self.assertEqual(services.snapshot_file(self.owner,snapshot.pk,'content.json').read_bytes(),raw)

    def test_unconfirmed_formula_image_blocks_independent_practice(self):
        result=materials.save_question(self.owner,self.material.pk,printed_text='sqrt(x)',display_markup='[[image:1|sqrt(x)]]',
            original_number='图片未核定',sources=[self.source(self.page())],request_key=key(),reason='图像可能含未知手写')
        self.accept_revision(result['revision_id'])
        with self.assertRaises(core.PersistenceError) as caught:
            services.export_questions(self.owner,self.house.pk,[result['revision_id']],title='独立练习',purpose='independent_practice')
        self.assertEqual(caught.exception.code,'image_review_required')

    def test_print_modes_download_authorization_duplicate_hash_and_edit_history(self):
        q=self.published()
        with self.assertRaises(core.PersistenceError):services.export_questions(self.owner,self.house.pk,[q.pk],title='答案',purpose='parent_answers')
        a=TeacherAnswerRevision.objects.get(pk=self.answer(q)['answer_id'])
        services.review_answer(self.owner,a.pk,action='accepted',reason='复算通过',expected=services.answer_context(q),request_key=key())
        practice=services.export_questions(self.owner,self.house.pk,[q.pk],title='独立练习',purpose='independent_practice')
        answers=services.export_questions(self.owner,self.house.pk,[q.pk],title='家长答案',purpose='parent_answers')
        self.assertEqual(practice.pk,services.export_questions(self.owner,self.house.pk,[q.pk],title='独立练习',purpose='independent_practice').pk)
        document=json.loads(services.snapshot_file(self.owner,practice.pk,'content.json').read_text())
        self.assertFalse(any(b['role'] in {'method','answer','classification','assessment'} for p in document['pages'] for b in p))
        self.assertEqual(answers.provenance['answers'][0]['answer_id'],a.pk)
        for actor in (self.other,):
            with self.assertRaises(core.PersistenceError):services.snapshot_file(actor,practice.pk,'document.pdf')
        self.client.force_login(self.viewer)
        response=self.client.get(f'/prints/snapshots/{practice.pk}/document.pdf/')
        self.assertEqual(response.status_code,200);self.assertIn('no-store',response['Cache-Control']);response.close()
        self.client.logout();self.assertEqual(self.client.get(f'/prints/snapshots/{practice.pk}/document.pdf/').status_code,302)
        with self.assertRaises(DatabaseError),transaction.atomic():ExportSnapshot.objects.filter(pk=practice.pk).update(title='覆盖')
        path=services.snapshot_file(self.owner,practice.pk,'document.pdf');path.write_bytes(b'modified')
        from app.exports.contracts import ExportError
        with self.assertRaises(ExportError):services.snapshot_file(self.owner,practice.pk,'document.pdf')

    def test_snapshot_provenance_pins_link_and_node_review_decisions(self):
        q=self.published()
        node=knowledge_services.save_node(self.owner,self.house.pk,'knowledge',data={
            'definition':'合成知识节点','conditions':'','common_errors':'','sources':'[]'},
            request_key=key(),reason='建立合成打印依赖')
        self.accept_revision(node['revision_id'])
        link=knowledge_services.create_link(self.owner,self.house.pk,kind='knowledge',
            node_revision_id=node['revision_id'],question_revision_id=q.pk,role='applies',
            request_key=key(),reason='合成题目知识关联')
        self.accept_revision(link['revision_id'])
        node_revision=RevisionRecord.objects.get(pk=node['revision_id'])
        link_revision=RevisionRecord.objects.get(pk=link['revision_id'])
        node_decision=str(node_revision.review_projection.decision_id)
        link_decision=str(link_revision.review_projection.decision_id)

        snapshot=services.export_questions(self.owner,self.house.pk,[q.pk],title='合成知识整理',purpose='knowledge_summary')
        self.assertEqual(snapshot.provenance['nodes'][0]['review_decision_id'],node_decision)
        self.assertEqual(snapshot.provenance['links'][0]['review_decision_id'],link_decision)

        self.withdraw_revision(link['revision_id'])
        self.withdraw_revision(node['revision_id'])
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.provenance['nodes'][0]['review_decision_id'],node_decision)
        self.assertEqual(snapshot.provenance['links'][0]['review_decision_id'],link_decision)
        node_revision=RevisionRecord.objects.select_related('review_projection').get(pk=node['revision_id'])
        link_revision=RevisionRecord.objects.select_related('review_projection').get(pk=link['revision_id'])
        self.assertNotEqual(str(node_revision.review_projection.decision_id),node_decision)
        self.assertNotEqual(str(link_revision.review_projection.decision_id),link_decision)

    def test_knowledge_formula_and_highlight_print_without_practice_hint(self):
        q=self.published('计算题')
        node=knowledge_services.save_node(self.owner,self.house.pk,'knowledge',data={
            'definition':'性质\n1/2\n(-2)^2\n(x^2)^3',
            'display_markup':'==性质==\n[[math:1/2]]\n[[math:(-2)^2]]\n[[math:(x^2)^3]]',
            'conditions':'先核对底数','common_errors':'不要忽略负号','sources':'[]'},request_key=key(),reason='公式知识核对')
        self.accept_revision(node['revision_id'])
        link=knowledge_services.create_link(self.owner,self.house.pk,kind='knowledge',node_revision_id=node['revision_id'],
            question_revision_id=q.pk,role='applies',request_key=key(),reason='知识对应题目')
        self.accept_revision(link['revision_id'])
        summary=services.export_questions(self.owner,self.house.pk,[q.pk],title='知识公式',purpose='knowledge_summary')
        content=json.loads(services.snapshot_file(self.owner,summary.pk,'content.json').read_text())
        blocks=[b for p in content['pages'] for b in p]
        self.assertEqual(sum(b['kind']=='math' for b in blocks),3)
        self.assertTrue(any('backcolor' in str(b['content']) for b in blocks))
        self.assertTrue(any('适用条件：先核对底数' in str(b['content']) for b in blocks))
        practice=services.export_questions(self.owner,self.house.pk,[q.pk],title='独立练习',purpose='independent_practice')
        raw=services.snapshot_file(self.owner,practice.pk,'content.json').read_text()
        self.assertNotIn('先核对底数',raw);self.assertNotIn('不要忽略负号',raw)

    def test_erratum_review_changes_working_text_preserves_print_and_no_child_records(self):
        q=self.published('1+1=3')
        result=services.save_erratum(self.owner,self.house.pk,q.pk,corrected_text='1+1=2',basis='整数加法复算',
            expected=records.edit_context(q),request_key=key())
        e=RevisionRecord.objects.get(pk=result['revision_id'])
        with self.assertRaises(core.PersistenceError):services.apply_erratum(self.owner,self.house.pk,e.pk,expected=records.edit_context(q),request_key=key())
        c=core.review_context(self.owner,self.house.pk,e.pk)
        records.review(self.owner,self.house.pk,'erratum',e.entity.stable_id,e.pk,action='accept',reason='复算',context=c,request_key=key())
        revised=services.apply_erratum(self.owner,self.house.pk,e.pk,expected=records.edit_context(q),request_key=key())
        new=RevisionRecord.objects.get(pk=revised['revision_id'])
        self.assertEqual(new.payload['printed_text'],'1+1=3');self.assertEqual(new.payload['working_text'],'1+1=2')
        self.assertEqual(q.payload['working_text'],'1+1=3')
        self.assertEqual(EntityRecord.objects.filter(kind__in=['attempt','assessment']).count(),0)
        c=core.review_context(self.owner,self.house.pk,new.pk)
        records.review(self.owner,self.house.pk,'question',new.entity.stable_id,new.pk,action='accept',reason='按勘误接受',context=c,request_key=key())

    def test_erratum_preserves_cross_material_question_label(self):
        first=self.question(text='来自第一份资料的题目')
        original_material=self.material
        self.material=materials.create_material(self.owner,self.house.pk,'第二份合成资料',key())
        second=self.question(text='来自第二份资料的题目')
        self.material=original_material

        source_ids=[first['revision_id'],second['revision_id']]
        merged=catalogue.merge_questions(self.owner,self.house.pk,
            source_revision_ids=source_ids,
            context_token=catalogue.prepare_context(self.owner,self.house.pk,'merge',source_ids),
            original_number='合题 J1-1+J1-2',printed_text='合并题印刷错误',
            reason='合并两份资料中的来源题',request_key=key())
        old_revision_id=merged['target_revision_ids'][0]
        original_label=QuestionLabel.objects.get(revision_id=old_revision_id)
        self.assertEqual(original_label.original_number,'合题 J1-1+J1-2')
        self.assertFalse(QuestionSource.objects.filter(revision_id=old_revision_id).exists())

        question=RevisionRecord.objects.get(pk=old_revision_id)
        erratum_result=services.save_erratum(self.owner,self.house.pk,question.pk,
            corrected_text='合并题订正后的题干',basis='核对两份合成资料',
            expected=records.edit_context(question),request_key=key())
        erratum=RevisionRecord.objects.get(pk=erratum_result['revision_id'])
        reviewer=get_user_model().objects.create_user(username=f'print-reviewer-{key()}')
        HouseholdMember.objects.create(household=self.house,user=reviewer,role='reviewer')
        review_context=core.review_context(reviewer,self.house.pk,erratum.pk)
        records.review(reviewer,self.house.pk,'erratum',erratum.entity.stable_id,erratum.pk,
            action='accept',reason='核实资料勘误',context=review_context,request_key=key())
        applied=services.apply_erratum(reviewer,self.house.pk,erratum.pk,
            expected=records.edit_context(question),request_key=key())

        new_label=QuestionLabel.objects.get(revision_id=applied['revision_id'])
        original_label.refresh_from_db()
        self.assertEqual(original_label.original_number,'合题 J1-1+J1-2')
        self.assertEqual(new_label.original_number,original_label.original_number)
        self.assertEqual(new_label.created_by,reviewer)
        self.assertFalse(QuestionSource.objects.filter(revision_id=applied['revision_id']).exists())

    def test_answer_cannot_cross_family_or_be_written_by_viewer(self):
        q=self.published()
        for actor,house in [(self.viewer,self.house),(self.other,self.house)]:
            with self.assertRaises(core.PersistenceError):services.save_answer(actor,house.pk,q.pk,body='1/2',formulas=[],basis='复算',expected=services.answer_context(q),request_key=key())
        with self.assertRaises(DatabaseError),transaction.atomic():TeacherAnswerRevision.objects.create(household=self.other_house,
            question_revision=q,revision_no=1,body='x',basis='x',created_by=self.other)

    def test_unsupported_formula_has_source_labelled_image_fallback(self):
        q=self.published()
        region=q.payload['evidence_refs'][0]['region_revision_id']
        fallback=services.source_formula_image(self.owner,self.house.pk,q.pk,region,'原图中的不支持公式')
        a=services.save_answer(self.owner,self.house.pk,q.pk,body='见来源公式图片',formulas=[fallback],basis='人工核对原图',
            expected=services.answer_context(q),request_key=key())
        services.review_answer(self.owner,a['answer_id'],action='accepted',reason='来源核对',expected=services.answer_context(q),request_key=key())
        snapshot=services.export_questions(self.owner,self.house.pk,[q.pk],title='图片公式回退',purpose='parent_answers')
        document=json.loads(services.snapshot_file(self.owner,snapshot.pk,'content.json').read_text())
        self.assertTrue(any(b['kind']=='formula_image' and region in b['content']['source_ref'] for p in document['pages'] for b in p))
        with self.assertRaises(core.PersistenceError):services.source_formula_image(self.other,self.house.pk,q.pk,region,'越权')

    def test_long_question_paginates_without_losing_text(self):
        text='请计算并写出每一步的依据。'*300
        q=self.published(text)
        snapshot=services.export_questions(self.owner,self.house.pk,[q.pk],title='长题分页',purpose='independent_practice')
        document=json.loads(services.snapshot_file(self.owner,snapshot.pk,'content.json').read_text())
        self.assertGreater(len(document['pages']),1)
        from html import unescape
        printed=''.join(unescape(b['content']).replace('<br/>','\n') for p in document['pages'] for b in p if b['role']=='question')
        self.assertEqual(printed,'1. '+text)


from tests.study import test_services as study_fixture


class EvidencePrintTests(TransactionTestCase):
    setUp=study_fixture.StudyServiceTests.setUp
    create_observation=study_fixture.StudyServiceTests.create_observation
    create_attempt=study_fixture.StudyServiceTests.create_attempt
    save_and_review=study_fixture.StudyServiceTests.save_and_review

    def test_report_freezes_real_attempt_review_and_unknown_dimensions(self):
        attempt=self.create_attempt()
        evaluation=self.save_and_review(attempt['attempt_id'])
        exported=services.export_evidence_report(self.owner,self.learner_entity.pk)
        report=exported.provenance['report']
        self.assertEqual(report['attempts'][0]['attempt_revision_id'],attempt['revision_id'])
        self.assertEqual(report['attempts'][0]['assessments'][0]['assessment_revision_id'],evaluation['revision_id'])
        self.assertTrue(report['insufficient_evidence'])
        document=json.loads(services.snapshot_file(self.owner,exported.pk,'content.json').read_text())
        self.assertEqual(document['purpose'],'evidence_report')
        self.assertEqual(document['source']['state'],'draft')
        with self.assertRaises(core.PersistenceError):services.export_evidence_report(self.other,self.learner_entity.pk)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(f'/prints/reports/{self.learner_entity.pk}/').status_code,200)
