"""Fabricated proposals exercise the human confirmation transaction, never a gateway."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.test import TransactionTestCase
from django.db import connections

from app.ai import services as ai, review_services as review
from app.ai.models import ModelRun
from app.persistence import services as core
from app.persistence.models import EntityRecord, EvidenceRecord, HouseholdMember, ReviewDecision, RevisionRecord
from app.persistence.adapter import ObjectKey
from app.web import services as materials, knowledge_services as knowledge, learning_services as learning
from tests.ai import test_services as fixtures

key = fixtures.key


class ConfirmationTests(TransactionTestCase):
    setUp = fixtures.AIWorkflowTests.setUp
    config_data = fixtures.AIWorkflowTests.config_data
    make_config = fixtures.AIWorkflowTests.make_config
    make_question = fixtures.AIWorkflowTests.make_question
    make_blank_question = fixtures.AIWorkflowTests.make_blank_question
    region_for = fixtures.AIWorkflowTests.region_for
    queue_question = fixtures.AIWorkflowTests.queue_question
    proposal_response = fixtures.AIWorkflowTests.proposal_response
    run_with_response = fixtures.AIWorkflowTests.run_with_response

    def ready(self, *, blank=True):
        question = self.make_blank_question() if blank else self.published
        run = self.queue_question(question, image=blank)
        self.run_with_response(run, self.proposal_response(run, printed_text='合成识别：3 + 4 = ?'))
        return run, question

    def confirm(self, run, **overrides):
        values = dict(expected=review.review_context(self.owner, run.pk)['context'], checked=True,
            reason='人工对照合成来源，保留未知', request_key=key())
        values.update(overrides)
        return review.confirm_run(self.owner, run.pk, **values)

    def test_single_confirmation_keeps_source_history_and_exact_replay_does_not_republish(self):
        run, blank = self.ready()
        expected = review.review_context(self.owner, run.pk)['context']
        request_key = key()
        first = self.confirm(run, expected=expected, request_key=request_key)
        self.assertEqual(self.confirm(run, expected=expected, request_key=request_key), first)
        head = EntityRecord.objects.get(kind='question', stable_id=blank['question_id'])
        self.assertEqual(head.revisions.count(), 2)
        self.assertEqual(head.published_revision_id, first['revision_ids'][0])
        self.assertTrue(review.review_context(self.owner, run.pk)['confirmed'])
        self.assertIsNone(RevisionRecord.objects.get(pk=blank['revision_id']).payload['printed_text'])
        context = core.review_context(self.owner, self.household.pk, head.published_revision_id)
        core.review_revision(self.owner, self.household.pk, head.published_revision_id, action='withdraw',
            expected_head=context['expected_head'], expected_dependencies=context['expected_dependencies'],
            expected_decision_id=context['expected_decision_id'], request_key=key(), reason='合成撤回')
        self.assertEqual(self.confirm(run, expected=expected, request_key=request_key), first)
        head.refresh_from_db()
        self.assertIsNone(head.published_revision_id)
        with self.assertRaises(core.PersistenceError):
            self.confirm(run, expected=expected)

    def test_changed_source_and_changed_output_reject_the_displayed_form(self):
        run, blank = self.ready()
        expected = review.review_context(self.owner, run.pk)['context']
        detail = materials.question_detail(self.owner, blank['question_id'])
        materials.save_question(self.owner, self.material.pk, printed_text='人工已补新版本',
            original_number='AI-OCR', sources=[self.source], question_id=blank['question_id'],
            expected_context=detail['edit_context'], request_key=key(), reason='更新来源')
        with self.assertRaises(core.PersistenceError):
            self.confirm(run, expected=expected)
        run.refresh_from_db()
        self.assertEqual(run.status, 'awaiting_review')
        self.assertEqual(run.output_revision_ids, [])
        run2, _ = self.ready()
        ai.apply_run(self.owner, run2.pk, request_key=key())
        expected2 = review.review_context(self.owner, run2.pk)['context']
        rid = expected2['outputs'][0]['revision_id']
        context = core.review_context(self.owner, self.household.pk, rid)
        core.review_revision(self.owner, self.household.pk, rid, action='reject',
            expected_head=context['expected_head'], expected_dependencies=context['expected_dependencies'],
            expected_decision_id=context['expected_decision_id'], request_key=key(), reason='合成退回')
        with self.assertRaises(core.PersistenceError):
            self.confirm(run2, expected=expected2)

    def test_incomplete_proposal_rolls_back_draft_and_review_without_losing_proposal(self):
        blank = self.make_blank_question()
        run = self.queue_question(blank, image=True)
        response = json.loads(self.proposal_response(run, printed_text=None))
        response['proposal']['missing_fields'] = ['题干看不清']
        self.run_with_response(run, json.dumps(response))
        before = (RevisionRecord.objects.count(), ReviewDecision.objects.count())
        with self.assertRaises(core.PersistenceError):
            self.confirm(run)
        run.refresh_from_db()
        self.assertEqual(run.status, 'awaiting_review')
        self.assertEqual(run.response['proposal']['missing_fields'], ['题干看不清'])
        self.assertEqual(before, (RevisionRecord.objects.count(), ReviewDecision.objects.count()))

    def test_confirmation_requires_explicit_assent_and_current_authority(self):
        run, _ = self.ready()
        with self.assertRaises(core.PersistenceError):
            self.confirm(run, checked=False)
        context = review.review_context(self.owner, run.pk)['context']
        for actor in (self.reviewer, self.viewer, self.other):
            with self.assertRaises(core.PersistenceError):
                review.confirm_run(actor, run.pk, expected=context, checked=True,
                    reason='不能代替任务作者', request_key=key())
        HouseholdMember.objects.filter(household=self.household, user=self.owner).delete()
        with self.assertRaises(core.PersistenceError):
            self.confirm(run, expected=context)

    def test_concurrent_confirmations_publish_once_without_partial_drafts(self):
        run, blank = self.ready()
        expected = review.review_context(self.owner, run.pk)['context']
        barrier = Barrier(2)
        def submit():
            try:
                barrier.wait(timeout=10)
                return self.confirm(run, expected=expected)
            except core.PersistenceError as exc:
                return exc.code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn('stale_context', results)
        entity = EntityRecord.objects.get(kind='question', stable_id=blank['question_id'])
        self.assertEqual(entity.revisions.count(), 2)
        self.assertEqual(ReviewDecision.objects.filter(revision=entity.published_revision).count(), 1)

    def test_printed_difference_confirms_an_erratum_without_changing_question_or_child_records(self):
        run, question = self.ready(blank=False)
        first = self.confirm(run)
        row = RevisionRecord.objects.get(pk=first['revision_ids'][0])
        self.assertEqual(row.entity.kind, 'erratum')
        self.assertEqual(row.payload['target_revision_id'], question['revision_id'])
        original = EntityRecord.objects.get(kind='question', stable_id=question['question_id'])
        self.assertEqual(original.head_revision_id, question['revision_id'])
        self.assertEqual(original.published_revision_id, question['revision_id'])
        self.assertFalse(EntityRecord.objects.filter(kind__in=['attempt', 'assessment']).exists())

    def test_knowledge_confirmation_retains_exact_question_and_original_sources(self):
        context = ai.selection_context(self.owner, self.household.pk, 'knowledge')
        rid = self.published['revision_id']
        run = ai.queue_run(self.owner, self.household.pk, task_kind='knowledge',
            source_revision_ids=[rid], question_revision_ids=[rid], selection_token=context['token'], request_key=key())
        self.run_with_response(run, json.dumps({'schema_version': 'study-workbench.ai.v1', 'task': 'knowledge',
            'source_revision_ids': [rid], 'tool_calls': [], 'proposal': {
                'definition': '加法的合成定义', 'conditions': ['此处仅为合成测试'], 'common_errors': []}}))
        result = self.confirm(run)
        row = RevisionRecord.objects.get(pk=result['revision_ids'][0])
        self.assertEqual(row.review_projection.state, 'accepted')
        self.assertEqual(row.evidence.count(), 1)
        self.assertEqual(len(result['link_revision_ids']), 1)
        forward = core.published_trace(self.owner, self.household.pk, node=ObjectKey('knowledge', row.entity.stable_id))
        self.assertIn(rid, forward['question_revision_ids'])
        image = row.evidence.get().image
        reverse = core.published_trace(self.owner, self.household.pk, image_id=image.stable_id)
        self.assertIn(row.pk, reverse['node_revision_ids'])

    def test_variant_confirmation_uses_existing_math_and_creator_gate(self):
        method = knowledge.save_node(self.owner, self.household.pk, 'method', data={
            'name': '合成加法', 'conditions': '', 'steps': '核对等式', 'notes': '',
            'parent_revision_id': '', 'sources': '[]'}, request_key=key(), reason='合成方法')
        c = core.review_context(self.owner, self.household.pk, method['revision_id'])
        core.review_revision(self.owner, self.household.pk, method['revision_id'], action='accept',
            expected_head=c['expected_head'], expected_dependencies=c['expected_dependencies'],
            expected_decision_id=c['expected_decision_id'], request_key=key(), reason='合成核对')
        context = ai.selection_context(self.reviewer, self.household.pk, 'variant')
        rid = self.published['revision_id']
        run = ai.queue_run(self.reviewer, self.household.pk, task_kind='variant', source_revision_ids=[method['revision_id']],
            question_revision_ids=[rid], selection_token=context['token'], request_key=key())
        # The fixture's helper executes as owner, so request explicitly as creator.
        ai.request_execution(self.reviewer, run.pk)
        import os
        response = {'schema_version': 'study-workbench.ai.v1', 'task': 'variant', 'tool_calls': [],
            'source_revision_ids': [rid, method['revision_id']], 'proposal': {'text': '合成 3 + 4 = ?',
                'answer_expression': '3+4', 'check_expression': '7', 'target_method_revision_id': method['revision_id']}}
        with patch.dict(os.environ, {'SWB_MODEL_API_KEY': 'fabricated-test-secret'}), patch(
                'app.ai.services.chat_completion', return_value=(json.dumps(response), {'prompt_tokens': 20, 'completion_tokens': 10})):
            ai.execute_run(run.pk)
        self.assertFalse(review.review_context(self.owner, run.pk)['can_confirm'])
        with self.assertRaises(core.PersistenceError):
            self.confirm(run)
        result = review.confirm_run(self.reviewer, run.pk, expected=review.review_context(self.reviewer, run.pk)['context'],
            checked=True, reason='合成题目与等式已核对', request_key=key())
        self.assertEqual(RevisionRecord.objects.get(pk=result['revision_ids'][0]).review_projection.state, 'accepted')

    def test_unknown_assessments_append_for_exact_attempt_and_never_infer_mastery(self):
        learner = learning.create_profile(self.owner, self.household.pk, display_name='合成学生', grade='', request_key=key())
        learner_id = learner['learner_id']
        learning.save_observation(self.owner, self.household.pk, profile_context_id=learner_id,
            legibility='blank', author_state='confirmed', author_learner_id=learner_id,
            confirmation_basis='合成作者核对；并非已完成', actual_date_state='unknown', actual_date=None,
            notes='合成空白课堂来源，内容未知', sources=[self.source], reason='合成空白来源', request_key=key())
        choices = learning.learner_create_choices(self.owner, learner_id)
        attempt = learning.create_attempt(self.owner, learner_id, question_id=self.published['question_id'],
            attempt_kind='first', source_kind='classroom_note', independence='not_independent',
            prompt_status='unknown', prompts=(), actual_date_state='unknown', actual_date=None,
            legibility='blank', answer_text='', authorship_basis='合成课堂来源，不推断独立',
            observation_values=[choices['observation_choices'][0][0]], previous_attempt_id=None,
            context=choices['context'], request_key=key())
        arow = EntityRecord.objects.get(kind='attempt', stable_id=attempt['attempt_id']).head_revision
        region_id = str(EvidenceRecord.objects.get(source__entity__kind='observation').region_id)
        saved_ids = []
        for _ in range(2):
            c = ai.selection_context(self.owner, self.household.pk, 'assessment')
            rid = self.published['revision_id']
            run = ai.queue_run(self.owner, self.household.pk, task_kind='assessment', source_revision_ids=[rid],
                question_revision_ids=[rid], attempt_revision_id=arow.pk, selected_region_revision_ids=[region_id],
                selection_token=c['token'], request_key=key())
            self.run_with_response(run, json.dumps({'schema_version': 'study-workbench.ai.v1', 'task': 'assessment',
                'source_revision_ids': [rid, region_id], 'tool_calls': [], 'proposal': {'dimensions': [
                    {'dimension': dim, 'judgment': 'unknown', 'basis': 'undetermined',
                     'source_region_revision_ids': [], 'rationale': '空白不能判断', 'unknown_reason': '没有可见作答'}
                    for dim in ('answer', 'method', 'process', 'calculation', 'notation')]}}))
            saved_ids.extend(self.confirm(run)['revision_ids'])
        self.assertEqual(len(set(saved_ids)), 2)
        self.assertEqual(EntityRecord.objects.filter(kind='attempt').count(), 1)
        for rid in saved_ids:
            row = RevisionRecord.objects.get(pk=rid)
            self.assertEqual(row.payload['attempt_revision_id'], arow.pk)
            self.assertTrue(all(dim['judgment'] == 'unknown' for dim in row.payload['dimensions']))
        self.assertFalse(learning.attempt_detail(self.owner, attempt['attempt_id'])['independent_success'])
