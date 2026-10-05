"""Regression boundaries for the UX remediation; only synthetic learning data."""
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse

from app.web import knowledge_services as knowledge
from app.web import learning_services as learning
from app.web import services as materials
from app.web.learning_forms import ProfileForm
from tests.web import test_learning_http as fixtures
from tests.solutions import test_workflow as solution_fixtures
from app.solutions.models import SolutionOutput


class GradeFormTests(SimpleTestCase):
    def form(self, grade='', other='', initial=None):
        return ProfileForm({'request_key': str(uuid4()), 'household_id': 'synthetic-house',
            'display_name': '合成学习者', 'grade': grade, 'other_grade': other},
            households=[SimpleNamespace(household_id='synthetic-house')], initial=initial)

    def test_standard_other_and_unknown_grades_keep_their_meaning(self):
        for value in ('', '三年级', '初二', '高三'):
            form = self.form(value)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data['grade'], value)
        form = self.form('__other__', '国际班 Year 4')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['grade'], '国际班 Year 4')
        self.assertFalse(self.form('__other__').is_valid())
        form = self.form('原有自由文本', initial={'grade': '原有自由文本'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['grade'], '原有自由文本')


class UXRecordTests(TransactionTestCase):
    setUp = fixtures.LearningHTTPTests.setUp
    create_confirmed_observation = fixtures.LearningHTTPTests.create_confirmed_observation
    create_attempt = fixtures.LearningHTTPTests.create_attempt

    def learner(self):
        return learning.create_profile(self.owner, self.household.pk, display_name='合成档案',
                                       grade='旧值保留', request_key=uuid4().hex)['learner_id']

    def test_same_day_same_question_choices_identify_each_real_event(self):
        learner = self.learner()
        self.create_confirmed_observation(learner)
        first = self.create_attempt(learner)
        choices = learning.learner_create_choices(self.owner, learner)
        second = learning.create_attempt(self.owner, learner, question_id=self.question_id,
            attempt_kind='retest', source_kind='assisted_answer', independence='not_independent',
            prompt_status='given', prompts=('合成提示',), actual_date_state='known',
            actual_date=date(2026, 10, 3), legibility='readable', answer_text='不同答案 6',
            authorship_basis='合成作者确认', observation_values=[choices['observation_choices'][0][0]], previous_attempt_id=first,
            context=choices['context'], request_key=uuid4().hex)['attempt_id']
        choices = learning.learner_create_choices(self.owner, learner)
        third = learning.create_attempt(self.owner, learner, question_id=self.question_id,
            attempt_kind='retry', source_kind='unknown', independence='unknown', prompt_status='unknown',
            prompts=(), actual_date_state='known', actual_date=date(2026, 10, 3), legibility='unknown', answer_text='',
            authorship_basis='确认作者，条件未记录', observation_values=[choices['observation_choices'][0][0]], previous_attempt_id=second,
            context=choices['context'], request_key=uuid4().hex)['attempt_id']
        choices = learning.learner_create_choices(self.owner, learner)
        fourth = learning.create_attempt(self.owner, learner, question_id=self.question_id,
            attempt_kind='retry', source_kind='unknown', independence='unknown', prompt_status='unknown',
            prompts=(), actual_date_state='unknown', actual_date=None, legibility='unknown', answer_text='',
            authorship_basis='确认作者，日期及条件未记录', observation_values=[choices['observation_choices'][0][0]], previous_attempt_id=third,
            context=choices['context'], request_key=uuid4().hex)['attempt_id']
        labels = dict(learning.learner_create_choices(self.owner, learner)['prior_attempts'])
        self.assertEqual(len(set(labels.values())), 4)
        for event in (first, second, third):
            self.assertIn('2026-10-03', labels[event])
        self.assertIn('首次', labels[first])
        self.assertIn('复测', labels[second])
        self.assertIn('不同答案 6', labels[second])
        self.assertIn('确认非独立', labels[second])
        self.assertIn('提示情况未知', labels[third])
        self.assertIn('日期未知', labels[fourth])
        self.assertNotIn(self.question_id, labels[first])
        detail = learning.attempt_detail(self.owner, third)
        self.assertEqual(detail['attempt'].previous_attempt_id, second)
        self.assertEqual(learning.attempt_detail(self.owner, fourth)['attempt'].previous_attempt_id, third)
        overview = self.client.get(f'/api/v1/learners/{learner}/overview/', {'household': self.household.pk}).json()
        self.assertEqual(overview['history_attempt_count'], 4)
        self.assertEqual(overview['recent_attempts'][-1]['actual_date_state'], 'unknown')
        self.assertIsNone(overview['recent_attempts'][-1]['actual_date'])
        zero = self.client.get(f'/api/v1/learners/{learner}/overview/',
            {'household': self.household.pk, 'date_from': '2099-01-01'}).json()
        self.assertEqual(zero['history_attempt_count'], 4)
        self.assertEqual(zero['metrics']['attempt_count'], 0)
        self.assertEqual(zero['metrics']['unknown_date_count'], 1)

    def test_new_draft_of_published_question_stays_out_of_practice(self):
        detail = materials.question_detail(self.owner, self.question_id)
        materials.save_question(self.owner, self.material.pk, question_id=self.question_id,
            expected_context=detail['edit_context'], printed_text='新版本尚未核定',
            original_number='changed', sources=[self.source], request_key=uuid4().hex, reason='合成修订')
        rows = knowledge.index_data(self.owner, self.household.pk, {'mode': 'learn'})['questions']
        self.assertEqual(rows, [])

    def test_material_listing_exposes_recorded_processing_and_retest_prefill_stays_scoped(self):
        learner = self.learner()
        rows = self.client.get('/api/v1/materials/', {'household': self.household.pk}).json()['items']
        row = next(item for item in rows if item['id'] == str(self.material.pk))
        self.assertEqual(row['processing']['page_count'], 1)
        self.assertEqual(row['processing']['questions_confirmed'], 1)
        response = self.client.get(reverse('learning:attempt_new', args=[learner]),
            {'question': self.question_id, 'kind': 'retest'})
        self.assertEqual(response.context['form'].initial['question_id'], self.question_id)
        self.assertEqual(response.context['form'].initial['attempt_kind'], 'retest')
        outside = self.client.get(reverse('learning:attempt_new', args=[learner]), {'question': 'outside'})
        self.assertNotIn('question_id', outside.context['form'].initial)

    def test_practice_excludes_drafts_while_manager_keeps_them(self):
        draft = materials.save_question(self.owner, self.material.pk, printed_text='尚未核定的合成题',
            original_number='draft', sources=[self.source], request_key=uuid4().hex, reason='合成草稿')
        learning_rows = knowledge.index_data(self.owner, self.household.pk, {'mode': 'learn'})['questions']
        management = knowledge.index_data(self.owner, self.household.pk, {'mode': 'manage'})['questions']
        self.assertEqual({row['entity'].stable_id for row in learning_rows}, {self.question_id})
        self.assertIn(draft['question_id'], {row['entity'].stable_id for row in management})
        self.assertTrue(learning_rows[0]['source_labels'])

    def test_existing_learners_show_before_creation_and_old_grade_is_kept(self):
        learner = self.learner()
        response = self.client.get(reverse('learning:index'), {'household': self.household.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '旧值保留')
        self.assertContains(response, '＋ 新建学习者')
        self.assertNotContains(response, 'name="display_name"')
        self.assertContains(response, '尚无作答记录')
        self.assertEqual(response.context['profile_cards'][0]['profile'].learner_id, learner)


class DocumentEntryTests(TransactionTestCase):
    setUp = solution_fixtures.SolutionTests.setUp
    create_observation = solution_fixtures.SolutionTests.create_observation
    content = solution_fixtures.SolutionTests.content
    save = solution_fixtures.SolutionTests.save

    def output(self, revision, title, checks=None):
        return SolutionOutput.objects.create(revision=revision, requested_by=self.owner,
            request_key=uuid4().hex, fingerprint='synthetic', state='output_check', result={
                'documents': [{'id': 'combined', 'title': title, 'organization': 'combined',
                    'page_count': 1, 'formats': ['docx'], 'previews': []}],
                **({'checks': checks} if checks is not None else {})})

    def test_recent_document_order_precedes_material_pagination_and_document_search_is_scoped(self):
        revision = self.save()
        self.output(revision, '旧的合成讲解')
        self.output(revision, '分数与单位合成讲解')
        materials.create_material(self.owner, self.household.pk, '新资料暂无文档', uuid4().hex)
        self.client.force_login(self.owner)
        endpoint = '/api/v1/materials/'
        response = self.client.get(endpoint, {'household': self.household.pk, 'document_mode': 'solution', 'page_size': 1}).json()
        self.assertEqual(response['items'][0]['id'], str(self.material.pk))
        docs = response['items'][0]['available_outputs'][0]['documents']
        self.assertEqual(docs[0]['title'], '分数与单位合成讲解')
        self.assertTrue(docs[0]['docx_url'])
        self.assertIsNone(docs[0]['pdf_url'])
        found = self.client.get(endpoint, {'household': self.household.pk, 'q': '分数与单位'}).json()
        self.assertEqual([row['id'] for row in found['items']], [str(self.material.pk)])
        self.client.force_login(self.other)
        outside = self.client.get(endpoint, {'household': self.other_household.pk, 'q': '分数与单位'}).json()
        self.assertEqual(outside['items'], [])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(endpoint, {'household': self.household.pk, 'document_mode': 'invalid'}).status_code, 400)

    def test_failed_formal_check_never_becomes_the_available_document(self):
        revision = self.save()
        self.output(revision, '可用的旧文档')
        self.output(revision, '检查退回的新文档', {'content': {'status': 'fail', 'notes': '合成退回'}})
        self.client.force_login(self.owner)
        row = self.client.get('/api/v1/materials/', {'household': self.household.pk}).json()['items'][0]
        self.assertEqual(row['available_outputs'][0]['documents'][0]['title'], '可用的旧文档')
