"""A plan completion is a real attempt, never a UI counter mutation."""
import json
from datetime import date
from unittest.mock import patch
from django.test import Client, TransactionTestCase
from app.study.models import StudySchedule, ScheduleRevision
from app.web import page_reading, knowledge_services, learning_services as learning
from app.study import services as study
from app.web.models import MaterialPage
from app.persistence.models import EntityRecord
from app.workflows import importer
from tests.study import test_services as fixtures

key = fixtures.key


class ProgressAPITests(TransactionTestCase):
    setUp = fixtures.StudyServiceTests.setUp
    create_observation = fixtures.StudyServiceTests.create_observation
    create_attempt = fixtures.StudyServiceTests.create_attempt
    save_and_review = fixtures.StudyServiceTests.save_and_review

    def url(self, part):
        return f"/api/v1/learners/{self.learner_id}/{part}/?household={self.household.pk}"

    def post(self, client, url, value):
        return client.post(url, json.dumps(value), content_type="application/json")

    def test_material_counts_are_read_only_and_keep_partial_unknown(self):
        client = Client()
        client.force_login(self.viewer)
        url = f"/api/v1/progress/?household={self.household.pk}"
        response = client.get(url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response.json()["counts"]["pages_unread"], 1)
        self.assertEqual(response.json()["counts"]["questions_confirmed"], 1)
        page = MaterialPage.objects.get(pk=self.page_id)
        page_reading.save(self.owner, self.page_id, reading="read", coverage="partial",
            sources=[{**self.source, "kind": "unknown"}], pending_items="字迹看不清",
            basis="合成整页核对", expected=page_reading.context(page), request_key=key())
        self.assertEqual(client.get(url).json()["counts"]["pages_complete"], 0)
        self.assertEqual(client.get(url.replace(self.household.pk, self.other_household.pk)).status_code, 404)

    def test_groups_deduplicate_assessments_and_use_confirmed_trace(self):
        saved = knowledge_services.save_node(self.owner, self.household.pk, "knowledge",
            data={"definition": "乘法", "sources": [self.source]}, request_key=key(), reason="合成知识")
        node = EntityRecord.objects.get(kind="knowledge", stable_id=saved["stable_id"])
        importer._accept(self.owner, node, saved["revision_id"], "核对合成知识", key())
        link = knowledge_services.create_link(self.owner, self.household.pk, kind="knowledge",
            question_revision_id=self.question_revision_id, node_revision_id=saved["revision_id"],
            role="applies", reason="合成关联", request_key=key())
        entity = EntityRecord.objects.get(kind=link["kind"], stable_id=link["stable_id"])
        importer._accept(self.owner, entity, link["revision_id"], "核对合成关联", key())
        client = Client()
        client.force_login(self.owner)
        untested = client.get(self.url("progress")).json()["groups"][0]
        self.assertEqual((untested["question_count"], untested["attempt_count"]), (1, 0))
        attempt = self.create_attempt()
        self.save_and_review(attempt["attempt_id"])
        self.save_and_review(attempt["attempt_id"])
        group = client.get(self.url("progress")).json()["groups"][0]
        self.assertEqual((group["attempt_count"], group["independent_success_count"]), (1, 1))
        self.assertNotIn("mastery_rate", group)

    def test_schedule_creation_completion_history_stale_and_exact_replay(self):
        client = Client()
        client.force_login(self.owner)
        options = client.get(self.url("schedules/options"))
        self.assertEqual(options.status_code, 200, options.content)
        value = {"question_revision_id": self.question_revision_id, "due_date": "2026-10-01",
            "goal": "独立复测", "prompt_plan": "", "reason": "合成复习安排",
            "expected": options.json()["context"], "request_key": key()}
        created = self.post(client, self.url("schedules"), value)
        self.assertEqual(created.status_code, 200, created.content)
        self.assertEqual(self.post(client, self.url("schedules"), value).json(), created.json())
        self.assertEqual(StudySchedule.objects.count(), 1)
        schedule_id = created.json()["schedule_id"]
        url = f"/api/v1/schedules/{schedule_id}/actions/"
        row = client.get(self.url("schedules")).json()["items"][0]
        complete = {"action": "completed", "expected": row["context"], "reason": "实际复测完成", "request_key": key()}
        self.assertEqual(self.post(client, url, complete).status_code, 400)
        attempt = self.create_attempt()
        complete.update(attempt_revision_id=attempt["revision_id"], request_key=key())
        self.assertEqual(self.post(client, url, complete).status_code, 200)
        self.assertEqual(self.post(client, url, complete).status_code, 200)
        self.assertEqual(ScheduleRevision.objects.count(), 2)
        row = client.get(self.url("schedules")).json()["items"][0]
        self.assertEqual(row["history"][-1]["actual_date"], "2026-10-01")
        self.assertEqual(row["attempt_choices"], [])
        self.assertEqual(self.post(client, url, {**complete, "request_key": key()}).status_code, 409)

    def test_plan_permissions_csrf_and_cross_household(self):
        owner = Client()
        owner.force_login(self.owner)
        options = owner.get(self.url("schedules/options")).json()
        value = {"question_revision_id": self.question_revision_id, "due_date": "2026-10-08",
            "goal": "复测", "prompt_plan": "", "reason": "合成安排",
            "expected": options["context"], "request_key": key()}
        viewer = Client()
        viewer.force_login(self.viewer)
        self.assertEqual(self.post(viewer, self.url("schedules"), value).status_code, 404)
        stranger = Client()
        stranger.force_login(self.other)
        self.assertEqual(stranger.get(self.url("schedules")).status_code, 404)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.owner)
        self.assertEqual(self.post(protected, self.url("schedules"), value).status_code, 403)
        self.assertEqual(StudySchedule.objects.count(), 0)

    def test_completion_choices_distinguish_same_day_same_source_events_and_keep_exact_binding(self):
        client = Client()
        client.force_login(self.owner)
        options = client.get(self.url('schedules/options')).json()
        created = self.post(client, self.url('schedules'), {
            'question_revision_id': self.question_revision_id, 'due_date': '2026-10-01',
            'goal': '同日复测', 'prompt_plan': '', 'reason': '合成辨识检查',
            'expected': options['context'], 'request_key': key()})
        self.assertEqual(created.status_code, 200, created.content)
        events = []
        for kind, day in (('first', date(2026, 10, 1)), ('retry', date(2026, 10, 1)),
                          ('retest', date(2026, 10, 1)), ('retry', None)):
            choices = learning.learner_create_choices(self.owner, self.learner_id)
            event = learning.create_attempt(self.owner, self.learner_id, question_id=self.question_id,
                attempt_kind=kind, source_kind='independent_answer', independence='confirmed_independent',
                prompt_status='none_confirmed', prompts=(), actual_date_state='known' if day else 'unknown',
                actual_date=day, legibility='readable', answer_text='8', authorship_basis='人工确认合成作者',
                observation_values=[choices['observation_choices'][0][0]],
                previous_attempt_id=events[-1]['attempt_id'] if events else None,
                context=choices['context'], request_key=key())
            revision = learning.attempt_detail(self.owner, event['attempt_id'])['current_revision']
            events.append({**event, 'revision_id': revision.header.revision_id})
        schedule_id = created.json()['schedule_id']
        row = client.get(self.url('schedules')).json()['items'][0]
        labels = {choice['revision_id']: choice['label'] for choice in row['attempt_choices']}
        self.assertEqual(len(set(labels.values())), 4)
        for event, kind in zip(events[:3], ('首次', '重做', '复测')):
            label = labels[event['revision_id']]
            for text in ('2026-10-01', kind, '独立作答', '人工确认独立', '人工确认无提示', '8', event['attempt_id'][-8:]):
                self.assertIn(text, label)
        self.assertIn('日期未知', labels[events[-1]['revision_id']])
        native_labels = {choice['revision'].header.revision_id: choice['label']
                         for choice in study.schedule_attempt_choices(self.owner, schedule_id)['choices']}
        self.assertEqual(labels, native_labels)
        done = self.post(client, f'/api/v1/schedules/{schedule_id}/actions/', {
            'action': 'completed', 'attempt_revision_id': events[1]['revision_id'],
            'expected': row['context'], 'reason': '明确关联第二次真实作答', 'request_key': key()})
        self.assertEqual(done.status_code, 200, done.content)
        latest = ScheduleRevision.objects.filter(schedule_id=schedule_id).order_by('-revision_no').first()
        self.assertEqual(latest.completed_attempt_revision_id, events[1]['revision_id'])

    def test_overdue_uses_server_date_and_only_pending_plans(self):
        client = Client()
        client.force_login(self.owner)
        options = client.get(self.url("schedules/options")).json()
        value = {"question_revision_id": self.question_revision_id, "due_date": "2026-10-01",
            "goal": "复测", "prompt_plan": "", "reason": "合成日期边界",
            "expected": options["context"], "request_key": key()}
        created = self.post(client, self.url("schedules"), value)
        self.assertEqual(created.status_code, 200, created.content)
        for today, expected in ((date(2026, 9, 30), False), (date(2026, 10, 1), False),
                                (date(2026, 10, 2), True)):
            with patch("app.api.progress.timezone.localdate", return_value=today):
                body = client.get(self.url("schedules")).json()
            self.assertIs(body["items"][0]["overdue"], expected)
            self.assertEqual(body["counts"]["overdue"], int(expected))
        row = body["items"][0]
        cancelled = self.post(client, f"/api/v1/schedules/{created.json()['schedule_id']}/actions/",
            {"action": "cancelled", "expected": row["context"], "reason": "合成取消",
             "request_key": key()})
        self.assertEqual(cancelled.status_code, 200, cancelled.content)
        with patch("app.api.progress.timezone.localdate", return_value=date(2026, 10, 2)):
            body = client.get(self.url("schedules")).json()
        self.assertIs(body["items"][0]["overdue"], False)
        self.assertEqual(body["counts"]["overdue"], 0)
        self.assertEqual(body["counts"]["cancelled"], 1)
