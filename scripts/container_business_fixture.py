"""Synthetic-only business records for the isolated container restore verifier.

Run through verify_container.py, never against an existing household.
"""
import django
import json
import sys
from datetime import date
from uuid import uuid4

django.setup()
from django.contrib.auth import get_user_model
from app.persistence.models import EntityRecord
from app.domain.arithmetic import formula_ast
from app.web.models import MaterialPage
from app.web import services as materials, learning_services as learning
from app.printing import services as printing
from app.study import services as study
from app.catalogue import services as catalogue
from app.ai import services as ai
from app.operations import services as operations

payload = json.load(sys.stdin)
actor = get_user_model().objects.get(username=payload['username'])
page = MaterialPage.objects.select_related('material').get(pk=payload['page_id'])
household_id = page.material.household_id
if not page.material.title.startswith('合成容器验收'):
    raise SystemExit('Refusing non-synthetic material')
key = lambda: str(uuid4())
preview = materials.preview_file(actor, page.pk, 0)
source = dict(page_id=str(page.pk), rotation=0, preview_sha256=preview.sha256,
              display_bbox=[2, 2, 28, 20])
question = materials.save_question(actor, page.material_id, printed_text='4 × 2 = ?',
    original_number='合成验收题', sources=[source], request_key=key(), reason='隔离验收')
detail = materials.question_detail(actor, question['question_id'])
materials.review_question(actor, question['question_id'], question['revision_id'],
    action='accept', reason='合成题核对', context=detail['review_context'], request_key=key())
profile = learning.create_profile(actor, household_id, display_name='合成学习者',
    grade='三年级', request_key=key())
learner = EntityRecord.objects.get(household_id=household_id, kind='learner', stable_id=profile['learner_id'])
obs = learning.save_observation(actor, household_id, profile_context_id=learner.stable_id,
    legibility='readable', author_state='confirmed', author_learner_id=learner.stable_id,
    confirmation_basis='合成测试确认', actual_date_state='known', actual_date=date(2026, 10, 1),
    notes='人工合成区域', sources=[source], reason='合成来源', request_key=key())
attempts = []
for source_kind, independence, prompt_status in (
        ('classroom_note', 'not_independent', 'unknown'),
        ('assisted_answer', 'not_independent', 'given'),
        ('independent_answer', 'confirmed_independent', 'none_confirmed')):
    choices = learning.learner_create_choices(actor, learner.stable_id)
    selected = next(value for value, _ in choices['observation_choices'] if value.startswith(obs['observation_id']+'|'))
    attempt = learning.create_attempt(actor, learner.stable_id, question_id=question['question_id'],
        attempt_kind='first', source_kind=source_kind, independence=independence,
        prompt_status=prompt_status, prompts=('合成提示',) if source_kind=='assisted_answer' else (),
        actual_date_state='known', actual_date=date(2026, 10, 1), legibility='readable',
        answer_text='8', authorship_basis='合成当面确认', observation_values=[selected],
        previous_attempt_id=None, context=choices['context'], request_key=key())
    attempts.append(attempt)
context = learning.assessment_context(actor, attempts[-1]['attempt_id'])
evidence = context['evidence_choices'][0][0][0]
values = {'context_errata': []}
for name in ('answer', 'method', 'process', 'calculation', 'notation'):
    observed = name in ('answer', 'process')
    values[name] = dict(judgment='correct' if observed else 'unknown',
        basis='observed' if observed else 'undetermined', evidence=[evidence] if observed else [],
        rationale='合成区域可见' if observed else '', unknown_reason='' if observed else '未评价')
assessment = learning.save_assessment(actor, attempts[-1]['attempt_id'], values=values,
    context=context['context'], request_key=key(), reason='合成评价')
review = learning.review_form_context(actor, assessment['assessment_id'])
learning.review_assessment(actor, assessment['assessment_id'], assessment['revision_id'],
    action='accept', reason='合成验收核对', context=review['review_context'], request_key=key())
qrow = printing.published_question(household_id, question['revision_id'])
answer = printing.save_answer(actor, household_id, qrow.pk, body='8', formulas=[formula_ast('4*2')],
    basis='合成人工答案', expected=printing.answer_context(qrow), request_key=key())
printing.review_answer(actor, answer['answer_id'], action='accepted', reason='人工核对',
    expected=printing.answer_context(qrow), request_key=key())
exports = [printing.export_questions(actor, household_id, [qrow.pk], title='合成练习', purpose='independent_practice'),
           printing.export_questions(actor, household_id, [qrow.pk], title='合成家长答案', purpose='parent_answers'),
           printing.export_evidence_report(actor, learner.pk)]
plan_context = study.new_schedule_context(actor, learner.pk)
plan = study.create_schedule(actor, learner.pk, question_revision_id=qrow.pk,
    due_date=date(2026, 10, 8), goal='合成独立复测计划', prompt_plan='', reason='合成验收',
    context=plan_context['context'], request_key=key())
split_context = catalogue.prepare_context(actor, household_id, 'split', [qrow.pk])
catalogue.split_question(actor, household_id, source_revision_id=qrow.pk, context_token=split_context,
    children=[{'printed_text':'4 × 2 = ?', 'original_number':'合成a'},
              {'printed_text':'2 × 4 = ?', 'original_number':'合成b'}], reason='合成拆题追溯', request_key=key())
ai.create_model_config(actor, household_id, data={'provider_label':'未启用的合成配置',
    'base_url':'https://model.example.test/v1', 'model':'manual-configuration-later',
    'cloud_enabled':False, 'outbound_scope':'reviewed_text'})
operations.append_retention_policy(actor, household_id, archive_after_days=None,
    delete_after_days=None, reason='合成验收默认长期保留', request_key=key())
timing_context = operations.work_timing_context(actor, household_id)
operations.record_work_timing(actor, household_id, question_revision_id=qrow.pk,
    attempt_revision_id=EntityRecord.objects.get(household_id=household_id,
        kind='attempt', stable_id=attempts[-1]['attempt_id']).head_revision_id,
    kind='manual_entry', seconds=60,
    reason='合成验收人工估计', context_token=timing_context['context_token'], request_key=key())
operations.retire_export_snapshot(actor, household_id, exports[0].pk,
    reason='合成验收退役与归档恢复')
ledger = operations.export_retirement_ledger(actor, household_id)
assert operations.verify_retirement_ledger(actor, household_id,
    ledger_id=ledger['ledger_id'])['matches']
print(json.dumps({'attempts':len(attempts), 'assessment':assessment['assessment_id'],
    'exports':[row.export_id for row in exports], 'schedule':plan['schedule_id'], 'model_disabled':True,
    'local_policy_and_timing':True, 'retired_export_archive_and_ledger':True}))
