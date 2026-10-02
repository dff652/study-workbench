from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse

from app.operations.models import RetentionPolicyRevision, WorkTiming
from app.persistence.models import HouseholdMember
from app.study import services as study
from tests.study import test_services as study_tests


class OperationsHTTPTests(TransactionTestCase):
    setUp = study_tests.StudyServiceTests.setUp
    create_observation = study_tests.StudyServiceTests.create_observation
    publish_question_revision = study_tests.StudyServiceTests.publish_question_revision

    def test_index_hides_household_id_entry_and_shows_role_scoped_actions(self):
        reviewer = get_user_model().objects.create_user(username=f"operations-reviewer-{uuid4().hex[:8]}")
        HouseholdMember.objects.create(household=self.household, user=reviewer,
            role=HouseholdMember.Role.REVIEWER)

        self.client.force_login(self.owner)
        index = self.client.get(reverse("operations:index"))
        self.assertEqual(index.status_code, 200)
        self.assertContains(index, self.household.pk)
        self.assertContains(index, reverse("operations:retention_policy",
            kwargs={"household_id": self.household.pk}))
        self.assertContains(index, reverse("operations:work_timing_new",
            kwargs={"household_id": self.household.pk}))
        self.assertNotContains(index, "SWB_DATA_ROOT")
        self.assertEqual(self.client.get(reverse("operations:retention_policy",
            kwargs={"household_id": self.household.pk})).status_code, 200)

        self.client.force_login(self.viewer)
        viewer_index = self.client.get(reverse("operations:index"))
        self.assertContains(viewer_index, "只读成员")
        self.assertNotContains(viewer_index, reverse("operations:retention_policy",
            kwargs={"household_id": self.household.pk}))
        self.assertEqual(self.client.get(reverse("operations:work_timing_new",
            kwargs={"household_id": self.household.pk})).status_code, 404)

        self.client.force_login(reviewer)
        reviewer_index = self.client.get(reverse("operations:index"))
        self.assertNotContains(reviewer_index, reverse("operations:retention_policy",
            kwargs={"household_id": self.household.pk}))
        self.assertEqual(self.client.get(reverse("operations:work_timing_new",
            kwargs={"household_id": self.household.pk})).status_code, 200)

    def test_retention_and_timing_forms_append_scoped_rows(self):
        self.client.force_login(self.owner)
        policy_url = reverse("operations:retention_policy", kwargs={"household_id": self.household.pk})
        response = self.client.post(policy_url, {"request_key": str(uuid4()),
            "archive_after_days": "", "delete_after_days": "", "reason": "合成页面策略"})
        self.assertRedirects(response, policy_url)
        self.assertEqual(RetentionPolicyRevision.objects.get().reason, "合成页面策略")

        context = study.new_schedule_context(self.owner, self.learner_entity.pk)
        question_revision_id = context["questions"][0]["revision_id"]
        timing_url = reverse("operations:work_timing_new", kwargs={"household_id": self.household.pk})
        timing_context = self.client.get(timing_url)
        self.assertEqual(timing_context.status_code, 200)
        token = timing_context.context["form"].initial["context_token"]
        response = self.client.post(timing_url, {"request_key": str(uuid4()),
            "context_token": token, "question_revision_id": question_revision_id,
            "attempt_revision_id": "", "kind": "model_correction", "seconds": "42",
            "reason": "合成的人工修订估计"})
        self.assertRedirects(response, timing_url)
        timing = WorkTiming.objects.get()
        self.assertEqual(timing.question_revision_id, question_revision_id)
        self.assertEqual(timing.kind, WorkTiming.Kind.MODEL_CORRECTION)

    def test_exact_completed_timing_post_replays_after_question_changes(self):
        self.client.force_login(self.owner)
        url = reverse("operations:work_timing_new", kwargs={"household_id": self.household.pk})
        token = self.client.get(url).context["form"].initial["context_token"]
        values = {"request_key": str(uuid4()), "context_token": token,
            "question_revision_id": self.question_revision_id, "attempt_revision_id": "",
            "kind": "manual_entry", "seconds": "55", "reason": "合成重放"}
        self.assertRedirects(self.client.post(url, values), url)
        self.publish_question_revision("4 × 3 = ?")
        self.assertRedirects(self.client.post(url, values), url)
        self.assertEqual(WorkTiming.objects.count(), 1)
        changed = dict(values, seconds="56")
        self.assertEqual(self.client.post(url, changed).status_code, 409)
        new_request = dict(values, request_key=str(uuid4()))
        self.assertEqual(self.client.post(url, new_request).status_code, 400)
