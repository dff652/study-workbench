"""Synthetic HTTP coverage for the learner archive and assessment pages."""
from datetime import date
import os
import tempfile
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils.html import strip_tags

from app.persistence import services as core
from app.persistence.models import EntityRecord, HouseholdMember, ReviewProjection
from app.web import knowledge_services as knowledge
from app.web import learning_services as learning
from app.web import services as materials
from tests.web.test_http import hidden_fields, synthetic_png


def key():
    return str(uuid4())


class LearningHTTPTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="swb-learning-http-")
        os.chmod(directory.name, 0o700)
        self.addCleanup(directory.cleanup)
        settings = override_settings(SWB_DATA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)

        self.owner = get_user_model().objects.create_user(
            username=f"learning-http-{uuid4().hex[:8]}", password="synthetic-only")
        self.household = core.create_household(self.owner, f"learning-http-{uuid4().hex}")
        self.client = Client()
        self.client.force_login(self.owner)
        self.material = materials.create_material(self.owner, self.household.pk, "合成学习 HTTP 样例", key())
        uploaded = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile("learning-http.png", synthetic_png(), content_type="image/png"), key())
        self.page_id = uploaded["page_id"]
        preview = materials.preview_file(self.owner, self.page_id, 0)
        self.source = {"page_id": self.page_id, "rotation": 0, "preview_sha256": preview.sha256,
            "display_bbox": [8, 8, 100, 70]}

        question = materials.save_question(self.owner, self.material.pk, printed_text="3 + 2 = ?",
            original_number="HTTP-1", sources=[self.source], request_key=key(), reason="合成学习 HTTP 题目")
        detail = materials.question_detail(self.owner, question["question_id"])
        materials.review_question(self.owner, question["question_id"], question["revision_id"],
            action="accept", reason="合成题目审核", context=detail["review_context"], request_key=key())
        self.question_id = question["question_id"]

    def create_profile(self):
        response = self.client.get(reverse("learning:profile_new"))
        self.assertEqual(response.status_code, 200)
        payload = {**hidden_fields(response), "household_id": str(self.household.pk),
            "display_name": "小禾", "grade": "三年级"}
        response = self.client.post(reverse("learning:profile_new"), payload)
        self.assertEqual(response.status_code, 302, response.content.decode("utf-8"))
        return response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

    def create_confirmed_observation(self, learner_id):
        result = learning.save_observation(self.owner, self.household.pk,
            profile_context_id=learner_id, legibility="readable", author_state="confirmed",
            author_learner_id=learner_id, confirmation_basis="家长确认由小禾完成",
            actual_date_state="known", actual_date=date(2026, 10, 3), notes="合成原图作答观察",
            sources=[self.source], reason="录入确认观察", request_key=key())
        return result["observation_id"]

    def create_attempt(self, learner_id):
        choices = learning.learner_create_choices(self.owner, learner_id)
        result = learning.create_attempt(self.owner, learner_id, question_id=self.question_id,
            attempt_kind="first", source_kind="independent_answer", independence="confirmed_independent",
            prompt_status="none_confirmed", prompts=(), actual_date_state="known",
            actual_date=date(2026, 10, 3), legibility="readable", answer_text="5",
            authorship_basis="家长当面确认作者和作答日期",
            observation_values=[choices["observation_choices"][0][0]], previous_attempt_id=None,
            context=choices["context"], request_key=key())
        return result["attempt_id"]

    def assessment_payload(self, response, attempt_id):
        fields = hidden_fields(response)
        context = learning.assessment_context(self.owner, attempt_id)
        evidence = context["evidence_choices"][0][0][0]
        payload = {**fields, "reason": "按原图填写五维评价"}
        for dimension in ("answer", "method", "process", "calculation", "notation"):
            if dimension in ("answer", "process"):
                payload.update({f"{dimension}_judgment": "correct", f"{dimension}_basis": "observed",
                    f"{dimension}_evidence": [evidence], f"{dimension}_rationale": "原图显示此项正确",
                    f"{dimension}_unknown_reason": ""})
            else:
                payload.update({f"{dimension}_judgment": "unknown", f"{dimension}_basis": "undetermined",
                    f"{dimension}_rationale": "", f"{dimension}_unknown_reason": "此维度未评价"})
        return payload

    def test_profile_filters_by_stable_node_ids_and_combines_date_review_and_error(self):
        learner_id = self.create_profile()
        self.create_confirmed_observation(learner_id)
        attempt_id = self.create_attempt(learner_id)
        question_revision_id = EntityRecord.objects.get(household=self.household, kind="question",
            stable_id=self.question_id).published_revision_id

        def accepted_node(kind, values):
            node = knowledge.save_node(self.owner, self.household.pk, kind,
                data={**values, "sources": "[]"}, request_key=key(), reason="建立档案筛选节点")
            entity = EntityRecord.objects.get(household=self.household, kind=kind,
                stable_id=node["stable_id"])
            context = core.review_context(self.owner, self.household.pk, node["revision_id"])
            core.review_revision(self.owner, self.household.pk, node["revision_id"], action="accept",
                expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
                expected_decision_id=context["expected_decision_id"], request_key=key(), reason="确认档案筛选节点")
            return node

        knowledge_node = accepted_node("knowledge", {"definition": "相同显示名称",
            "conditions": "", "common_errors": ""})
        type_node = accepted_node("question_type", {"name": "相同显示名称",
            "structural_features": "", "conditions": ""})
        for kind, node, role in (("knowledge", knowledge_node, "applies"),
                ("question_type", type_node, "belongs")):
            link = knowledge.create_link(self.owner, self.household.pk, kind=kind,
                node_revision_id=node["revision_id"], question_revision_id=question_revision_id,
                role=role, request_key=key(), reason="固定档案题目关系")
            link_kind = "knowledge_question" if kind == "knowledge" else "question_type_link"
            entity = EntityRecord.objects.get(household=self.household, kind=link_kind,
                stable_id=link["stable_id"])
            context = core.review_context(self.owner, self.household.pk, link["revision_id"])
            core.review_revision(self.owner, self.household.pk, link["revision_id"], action="accept",
                expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
                expected_decision_id=context["expected_decision_id"], request_key=key(), reason="确认档案题目关系")

        assessment_url = reverse("learning:assessment_new", kwargs={"attempt_id": attempt_id})
        form = self.client.get(assessment_url)
        self.assertEqual(form.status_code, 200)
        payload = self.assessment_payload(form, attempt_id)
        payload["answer_judgment"] = "incorrect"
        payload["answer_rationale"] = "合成错误证据"
        saved = self.client.post(assessment_url, payload)
        self.assertEqual(saved.status_code, 302, saved.content.decode("utf-8"))

        filters = {"knowledge": knowledge_node["stable_id"], "type": type_node["stable_id"],
            "from": "2026-10-03", "to": "2026-10-03", "review": "draft", "error": "yes"}
        profile = self.client.get(reverse("learning:profile_detail", kwargs={"learner_id": learner_id}), filters)
        self.assertEqual(profile.status_code, 200)
        self.assertEqual([item["attempt"].attempt_id for item in profile.context["attempts"]], [attempt_id])
        self.assertEqual(profile.context["filters"]["knowledge"], knowledge_node["stable_id"])
        self.assertEqual(profile.context["filters"]["type"], type_node["stable_id"])

    def test_profile_and_unknown_observation_http_keep_author_and_date_unknown(self):
        learner_id = self.create_profile()
        profile = self.client.get(reverse("learning:profile_detail", kwargs={"learner_id": learner_id}))
        self.assertEqual(profile.status_code, 200)

        url = reverse("learning:observation_new")
        form = self.client.get(f"{url}?household={self.household.pk}")
        self.assertEqual(form.status_code, 200)
        payload = {**hidden_fields(form), "household_id": str(self.household.pk),
            "profile_context_id": learner_id, "legibility": "unknown", "author_state": "unknown",
            "author_learner_id": "", "confirmation_basis": "", "actual_date_state": "unknown",
            "actual_date": "", "notes": "作者和发生日期均未确认；没有可用区域。",
            "sources": "[]", "reason": "保留未知观察"}
        saved = self.client.post(url, payload)
        self.assertEqual(saved.status_code, 302, saved.content.decode("utf-8"))
        observation_id = saved.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

        bundle = core.read_snapshot_bundle(self.owner, self.household.pk)
        observation = next(item for item in bundle.observations if item.observation_id == observation_id)
        revision = observation.revisions[-1]
        self.assertEqual(revision.author_state.value, "unknown")
        self.assertIsNone(revision.author_learner_id)
        self.assertIsNone(revision.confirmed_by)
        self.assertIsNone(revision.confirmed_at)
        self.assertIsNone(revision.confirmation_basis)
        self.assertIsNone(revision.actual_date)
        self.assertEqual(revision.evidence_refs, ())

        detail_url = reverse("learning:observation_detail", kwargs={"observation_id": observation_id})
        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("未知".encode(), detail.content)
        self.assertEqual(self.client.get(reverse("learning:observation_edit",
            kwargs={"observation_id": observation_id})).status_code, 200)

    def test_attempt_assessment_pages_review_actual_projection_and_replay(self):
        learner_id = learning.create_profile(self.owner, self.household.pk,
            display_name="小禾", grade="三年级", request_key=key())["learner_id"]
        self.create_confirmed_observation(learner_id)
        attempt_id = self.create_attempt(learner_id)

        attempt_url = reverse("learning:attempt_detail", kwargs={"attempt_id": attempt_id})
        attempt = self.client.get(attempt_url)
        self.assertEqual(attempt.status_code, 200)
        self.assertIn("原图".encode(), attempt.content)
        self.assertEqual(self.client.get(reverse("learning:attempt_edit",
            kwargs={"attempt_id": attempt_id})).status_code, 200)

        assessment_url = reverse("learning:assessment_new", kwargs={"attempt_id": attempt_id})
        form = self.client.get(assessment_url)
        self.assertEqual(form.status_code, 200)
        saved = self.client.post(assessment_url, self.assessment_payload(form, attempt_id))
        self.assertEqual(saved.status_code, 302, saved.content.decode("utf-8"))
        assessment_id = saved.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
        initial_revision_id = learning.assessment_detail(self.owner, assessment_id)["current_revision"].header.revision_id
        detail_url = reverse("learning:assessment_detail", kwargs={"assessment_id": assessment_id})
        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("答案".encode(), detail.content)
        self.assertContains(detail, "答案：正确 · 直接观察到")

        edit_url = reverse("learning:assessment_edit", kwargs={"assessment_id": assessment_id})
        edit_form = self.client.get(edit_url)
        self.assertEqual(edit_form.status_code, 200)
        revised = self.client.post(edit_url, self.assessment_payload(edit_form, attempt_id))
        self.assertEqual(revised.status_code, 302, revised.content.decode("utf-8"))
        current = learning.assessment_detail(self.owner, assessment_id)["current_revision"]
        current_revision_id = current.header.revision_id
        self.assertNotEqual(current_revision_id, initial_revision_id)
        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context["current_revision"].header.revision_id, current_revision_id)
        self.assertEqual(detail.context["review_form"].initial["revision_id"], current_revision_id)
        self.assertIn("人工审核".encode(), detail.content)
        self.assertContains(detail, "答案：正确 · 直接观察到")

        review_payload = hidden_fields(detail)
        review_payload.update({"action": "accept", "reason": "人工确认答案与过程", "request_key": key()})
        review_url = reverse("learning:assessment_review", kwargs={"assessment_id": assessment_id})
        accepted = self.client.post(review_url, review_payload)
        self.assertEqual(accepted.status_code, 302, accepted.content.decode("utf-8"))
        replay = self.client.post(review_url, review_payload)
        self.assertEqual(replay.status_code, 302, replay.content.decode("utf-8"))

        revision = learning.assessment_detail(self.owner, assessment_id)["current_revision"]
        entity = EntityRecord.objects.get(kind="assessment", stable_id=assessment_id)
        projection = ReviewProjection.objects.get(revision_id=revision.header.revision_id)
        self.assertEqual(projection.state, "accepted")
        self.assertEqual(entity.published_revision_id, revision.header.revision_id)
        self.assertTrue(learning.attempt_detail(self.owner, attempt_id)["independent_success"])
        profile = self.client.get(reverse("learning:profile_detail", kwargs={"learner_id": learner_id}))
        self.assertEqual(profile.status_code, 200)
        self.assertContains(profile, "独立作答")
        self.assertContains(profile, "人工确认独立")
        self.assertContains(profile, "答案：正确／直接观察到")
        learner_entity = EntityRecord.objects.get(kind="learner", stable_id=learner_id)
        study_report = self.client.get(reverse("study:report", kwargs={"learner_entity_pk": learner_entity.pk}))
        self.assertEqual(study_report.status_code, 200)
        self.assertContains(study_report, "独立作答 / 人工确认独立")
        self.assertIn("答案：正确 / 直接观察到", strip_tags(study_report.content.decode()))
        self.assertIn(reverse("printing:evidence_report", kwargs={"pk": learner_entity.pk}).encode(), study_report.content)

    def test_attempt_edit_posts_append_revision_without_rewriting_disabled_identity(self):
        learner_id = learning.create_profile(self.owner, self.household.pk,
            display_name="小禾", grade="三年级", request_key=key())["learner_id"]
        self.create_confirmed_observation(learner_id)
        first_attempt_id = self.create_attempt(learner_id)
        choices = learning.learner_create_choices(self.owner, learner_id)
        second = learning.create_attempt(self.owner, learner_id, question_id=self.question_id,
            attempt_kind="retry", source_kind="independent_answer", independence="confirmed_independent",
            prompt_status="none_confirmed", prompts=(), actual_date_state="known",
            actual_date=date(2026, 10, 3), legibility="readable", answer_text="5",
            authorship_basis="家长当面确认作者和作答日期",
            observation_values=[choices["observation_choices"][0][0]], previous_attempt_id=first_attempt_id,
            context=choices["context"], request_key=key())
        attempt_id = second["attempt_id"]
        before = learning.attempt_detail(self.owner, attempt_id)
        before_revision = before["current_revision"]
        edit_url = reverse("learning:attempt_edit", kwargs={"attempt_id": attempt_id})
        form = self.client.get(edit_url)
        self.assertEqual(form.status_code, 200)
        payload = {**hidden_fields(form),
            "attempt_kind": before_revision.attempt_kind.value,
            "source_kind": before_revision.source_kind.value,
            "independence": before_revision.independence.value,
            "prompt_status": before_revision.prompt_status.value,
            "prompts": "\n".join(before_revision.prompts),
            "actual_date_state": before_revision.actual_date_state.value,
            "actual_date": before_revision.actual_date or "",
            "legibility": before_revision.legibility.value,
            "answer_text": before_revision.answer_text or "",
            "authorship_basis": before_revision.authorship_basis,
            "observation_values": [f"{item.observation_id}|{item.observation_revision_id}"
                for item in before_revision.observation_refs],
            "reason": "补充本次作答记录"}
        self.assertNotIn("question_id", payload)
        self.assertNotIn("previous_attempt_id", payload)
        saved = self.client.post(edit_url, payload)
        self.assertEqual(saved.status_code, 302, saved.content.decode("utf-8"))

        after = learning.attempt_detail(self.owner, attempt_id)
        self.assertEqual(len(after["history"]), 2)
        self.assertEqual(after["attempt"].question_id, self.question_id)
        self.assertEqual(after["attempt"].previous_attempt_id, first_attempt_id)
        self.assertTrue(all(item["revision"].question_revision_id == before_revision.question_revision_id
            for item in after["history"]))

    def test_viewer_foreign_profile_and_stale_assessment_context_are_denied(self):
        learner_id = learning.create_profile(self.owner, self.household.pk,
            display_name="小禾", grade="三年级", request_key=key())["learner_id"]
        self.create_confirmed_observation(learner_id)
        attempt_id = self.create_attempt(learner_id)

        viewer = get_user_model().objects.create_user(username=f"learning-viewer-{uuid4().hex[:8]}")
        HouseholdMember.objects.create(household=self.household, user=viewer,
            role=HouseholdMember.Role.VIEWER)
        viewer_client = Client()
        viewer_client.force_login(viewer)
        profile_form = viewer_client.get(reverse("learning:profile_new"))
        self.assertEqual(profile_form.status_code, 200)
        denied = viewer_client.post(reverse("learning:profile_new"), {
            **hidden_fields(profile_form), "household_id": str(self.household.pk),
            "display_name": "不应创建", "grade": ""})
        self.assertEqual(denied.status_code, 404)

        foreign_owner = get_user_model().objects.create_user(username=f"learning-foreign-{uuid4().hex[:8]}")
        foreign_household = core.create_household(foreign_owner, f"learning-foreign-{uuid4().hex}")
        foreign_profile = learning.create_profile(foreign_owner, foreign_household.pk,
            display_name="另一家庭", grade="", request_key=key())
        foreign = self.client.get(reverse("learning:profile_detail", kwargs={
            "learner_id": foreign_profile["learner_id"]}))
        self.assertEqual(foreign.status_code, 404)
        foreign_node = knowledge.save_node(foreign_owner, foreign_household.pk, "knowledge", data={
            "definition": "另一家庭知识点", "conditions": "", "common_errors": "", "sources": "[]"},
            request_key=key(), reason="跨家庭筛选边界")
        local_profile = self.create_profile()
        foreign_filter = self.client.get(reverse("learning:profile_detail", kwargs={
            "learner_id": local_profile}), {"knowledge": foreign_node["stable_id"]})
        self.assertEqual(foreign_filter.status_code, 404)

        assessment_url = reverse("learning:assessment_new", kwargs={"attempt_id": attempt_id})
        form = self.client.get(assessment_url)
        self.assertEqual(form.status_code, 200)
        stale_payload = self.assessment_payload(form, attempt_id)
        edit = learning.attempt_edit_context(self.owner, attempt_id)
        previous = edit["attempt"].revisions[-1]
        expected = {"edit_context": edit["edit_context"],
            "observation_heads": edit["choices"]["context"]["observation_heads"]}
        learning.append_attempt_revision(self.owner, attempt_id,
            attempt_kind=previous.attempt_kind, source_kind=previous.source_kind,
            independence=previous.independence, prompt_status=previous.prompt_status,
            prompts=previous.prompts, actual_date_state=previous.actual_date_state,
            actual_date=previous.actual_date, legibility=previous.legibility,
            answer_text=previous.answer_text, authorship_basis=previous.authorship_basis,
            observation_values=[f"{item.observation_id}|{item.observation_revision_id}"
                for item in previous.observation_refs], expected_context=expected, request_key=key())
        stale = self.client.post(assessment_url, stale_payload)
        self.assertEqual(stale.status_code, 409)
