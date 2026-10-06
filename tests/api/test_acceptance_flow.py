"""Task context is explicitly confirmed, never auto-completes a plan."""
from uuid import uuid4
from urllib.parse import urlencode
from django.test import Client, TransactionTestCase
from app.persistence.models import EntityRecord
from app.study.models import StudySchedule, ScheduleRevision
from app.web import learning_services as learning, services as materials
from tests.study import test_services as fixtures


class AcceptanceFlowTests(TransactionTestCase):
    create_observation=fixtures.StudyServiceTests.create_observation
    setUp=fixtures.StudyServiceTests.setUp
    create_attempt=fixtures.StudyServiceTests.create_attempt
    create_schedule=fixtures.StudyServiceTests.create_schedule
    schedule_context=fixtures.StudyServiceTests.schedule_context
    save_and_review=fixtures.StudyServiceTests.save_and_review

    def test_saved_retest_returns_exact_version_for_confirmation_and_keeps_plan_pending(self):
        previous=self.create_attempt()
        plan,_=self.create_schedule()
        client=Client();client.force_login(self.owner)
        url=f'/learning/profile/{self.learner_id}/attempt/new/?'+urlencode({'question':self.question_id,'kind':'retest','plan':plan['schedule_pk']})
        page=client.get(url)
        self.assertEqual(page.status_code,200,page.content)
        form=page.context['form']
        data={'request_key':str(uuid4()),'context_token':form.initial['context_token'],
            'question_id':self.question_id,'learner_id':self.learner_id,'attempt_kind':'retest',
            'source_kind':'independent_answer','independence':'confirmed_independent','prompt_status':'none_confirmed',
            'actual_date_state':'known','actual_date':'2026-10-01','legibility':'readable',
            'answer_text':'8','authorship_basis':'合成当面确认','previous_attempt_id':previous['attempt_id'],
            'observation_values':learning.learner_create_choices(self.owner,self.learner_id)['observation_choices'][0][0]}
        saved=client.post(url,data)
        self.assertEqual(saved.status_code,302,saved.content)
        self.assertIn('attempt_revision=',saved['Location'])
        confirm=client.get(saved['Location'])
        self.assertEqual(confirm.status_code,200,confirm.content)
        self.assertContains(confirm,'待确认关联')
        selected=confirm.context['form'].initial['attempt_revision_id']
        self.assertNotEqual(selected,previous['revision_id'])
        self.assertEqual((StudySchedule.objects.count(),ScheduleRevision.objects.count()),(1,1))
        initial=confirm.context['form'].initial
        complete=client.post(saved['Location'],{**initial,'action':'completed','attempt_revision_id':selected,'reason':'核对精确版本后确认完成'})
        self.assertEqual(complete.status_code,302,complete.content)
        self.assertEqual(ScheduleRevision.objects.order_by('revision_no').last().completed_attempt_revision_id,selected)
        replay=client.post(saved['Location'],{**initial,'action':'completed','attempt_revision_id':selected,'reason':'核对精确版本后确认完成'})
        self.assertEqual(replay.status_code,302)
        self.assertEqual(ScheduleRevision.objects.count(),2)

    def test_plan_context_cannot_cross_family_or_question(self):
        plan,_=self.create_schedule()
        client=Client();client.force_login(self.other)
        url=f'/learning/profile/{self.learner_id}/attempt/new/?question={self.question_id}&plan={plan["schedule_pk"]}'
        self.assertEqual(client.get(url).status_code,404)
        client.force_login(self.owner)
        self.assertEqual(client.get(url.replace(self.question_id,'unpublished-question')).status_code,404)

    def test_draft_detail_has_management_copy_and_no_practice_save_action(self):
        draft=materials.save_question(self.owner,self.material.pk,printed_text='待核对题目',original_number='D',sources=[self.source],request_key=fixtures.key(),reason='合成草稿')
        entity=EntityRecord.objects.get(kind='question',stable_id=draft['question_id'])
        client=Client();client.force_login(self.owner)
        url=f'/knowledge/question/{entity.pk}/?learner={self.learner_id}'
        page=client.get(url)
        self.assertEqual(page.status_code,200,page.content)
        self.assertContains(page,'当前不能开始练习')
        self.assertNotContains(page,'记录这次真实作答')
        self.assertContains(page, '继续整理这道题')
        from django.urls import reverse
        self.assertContains(page, reverse('web:question_edit', args=[entity.stable_id]))
        client.force_login(self.viewer)
        readonly = client.get(url)
        self.assertNotContains(readonly, '继续整理这道题')
        client.force_login(self.owner)
        self.assertEqual(client.get(f'/learning/profile/{self.learner_id}/attempt/new/?question={draft["question_id"]}').status_code,404)

    def test_published_question_with_new_draft_cannot_be_entered_as_student_practice(self):
        detail = materials.question_detail(self.owner, self.question_id)
        materials.save_question(self.owner, self.material.pk, printed_text='待核对的新题干', original_number='新版本',
            sources=[self.source], question_id=self.question_id, expected_context=detail['edit_context'], request_key=fixtures.key(), reason='合成未发布修订')
        client = Client(); client.force_login(self.owner)
        self.assertEqual(client.get(f'/learning/profile/{self.learner_id}/attempt/new/?question={self.question_id}').status_code, 404)

    def test_report_summary_uses_active_conditions_current_assessment_and_scoped_open_plans(self):
        from app.study import services as study
        from django.urls import reverse
        attempt = self.create_attempt()
        plan, _ = self.create_schedule()
        report = study.evidence_report(self.owner, self.learner_entity.pk)
        self.assertEqual(report['summary']['active_attempt_count'], 1)
        self.assertEqual(report['summary']['conditions_confirmed_count'], 1)
        self.assertEqual(report['summary']['pending_assessment_count'], 1)
        self.assertEqual(report['summary']['pending_retest_count'], 1)
        self.save_and_review(attempt['attempt_id'])
        self.assertEqual(study.evidence_report(self.owner, self.learner_entity.pk)['summary']['pending_assessment_count'], 0)
        study.append_schedule_event(self.owner, plan['schedule_pk'], action='cancelled',
            context=study.schedule_detail(self.owner, plan['schedule_pk'])['context'], reason='合成取消', request_key=fixtures.key())
        self.assertEqual(study.evidence_report(self.owner, self.learner_entity.pk)['summary']['pending_retest_count'], 0)
        empty = materials.create_material(self.owner, self.household.pk, '空资料范围', fixtures.key())
        scoped = study.evidence_report(self.owner, self.learner_entity.pk, material_id=empty.pk)['summary']
        self.assertEqual((scoped['active_attempt_count'], scoped['pending_assessment_count'], scoped['pending_retest_count']), (0, 0, 0))
        client = Client(); client.force_login(self.viewer)
        page = client.get(reverse('study:report', args=[self.learner_entity.pk]))
        self.assertContains(page, '完成条件与下一步')
        self.assertContains(page, '待评价 0 次')

    def test_student_post_cannot_replace_task_with_a_published_question_having_new_draft(self):
        second = materials.save_question(self.owner, self.material.pk, printed_text='另一道已核定题',
            original_number='Q2', sources=[self.source], confirm=True, request_key=fixtures.key(), reason='合成核定')
        detail = materials.question_detail(self.owner, second['question_id'])
        materials.save_question(self.owner, self.material.pk, question_id=second['question_id'],
            expected_context=detail['edit_context'], printed_text='Q2尚未核定的新题干', original_number='Q2',
            sources=[self.source], request_key=fixtures.key(), reason='合成草稿')
        client = Client(); client.force_login(self.owner)
        url = f'/learning/profile/{self.learner_id}/attempt/new/?question={self.question_id}'
        form = client.get(url).context['form']
        response = client.post(url, {'request_key': fixtures.key(), 'context_token': form.initial['context_token'],
            'learner_id': self.learner_id, 'question_id': second['question_id'], 'attempt_kind': 'first',
            'source_kind': 'independent_answer', 'independence': 'confirmed_independent', 'prompt_status': 'none_confirmed',
            'actual_date_state': 'known', 'actual_date': '2026-10-07', 'legibility': 'readable',
            'answer_text': '合成回答', 'authorship_basis': '合成确认',
            'observation_values': learning.learner_create_choices(self.owner, self.learner_id)['observation_choices'][0][0]})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, '当前学习任务的题目不能在这里替换', status_code=400)
        self.assertEqual(EntityRecord.objects.filter(kind='attempt').count(), 0)
