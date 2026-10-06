"""Synthetic learning record acceptance tests with isolated source images."""
from datetime import date
from io import BytesIO
import os
import tempfile
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase, override_settings
from PIL import Image

from app.persistence import services as core
from app.persistence.models import EntityRecord, ReviewProjection
from app.web import knowledge_services as knowledge
from app.web import learning_services as learning
from app.web import services as materials


def key():
    return str(uuid4())


def png_bytes(color=(235, 238, 242)):
    output = BytesIO()
    Image.new("RGB", (120, 80), color=color).save(output, format="PNG")
    return output.getvalue()


class LearningServiceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="swb-learning-test-")
        os.chmod(directory.name, 0o700)
        self.addCleanup(directory.cleanup)
        settings = override_settings(SWB_DATA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)

        self.owner = get_user_model().objects.create_user(
            username=f"learning-owner-{uuid4().hex[:8]}", password="synthetic-only")
        self.household = core.create_household(self.owner, f"learning-{uuid4().hex}")
        self.material = materials.create_material(
            self.owner, self.household.pk, "合成学习样例", key())
        uploaded = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile("synthetic.png", png_bytes(), content_type="image/png"), key())
        self.page_id = uploaded["page_id"]
        self.preview = materials.preview_file(self.owner, self.page_id, 0)
        self.source = {"page_id": self.page_id, "rotation": 0,
            "preview_sha256": self.preview.sha256, "display_bbox": [8, 8, 95, 70]}

        question = materials.save_question(self.owner, self.material.pk,
            printed_text="2 + 3 = ?", original_number="J1-1", sources=[self.source],
            request_key=key(), reason="合成题目")
        question_detail = materials.question_detail(self.owner, question["question_id"])
        materials.review_question(self.owner, question["question_id"], question["revision_id"],
            action="accept", reason="合成题干和区域已核对",
            context=question_detail["review_context"], request_key=key())
        self.question_id = question["question_id"]
        self.question_revision_id = question["revision_id"]

        profile = learning.create_profile(self.owner, self.household.pk,
            display_name="小禾", grade="三年级", request_key=key())
        self.learner_id = profile["learner_id"]
        observation = learning.save_observation(self.owner, self.household.pk,
            profile_context_id=self.learner_id, legibility="readable", author_state="confirmed",
            author_learner_id=self.learner_id, confirmation_basis="家长确认该页由小禾独立完成",
            actual_date_state="known", actual_date=date(2026, 10, 3),
            notes="合成原图中的一次作答", sources=[self.source], reason="录入来源观察", request_key=key())
        self.observation_id = observation["observation_id"]

    def create_attempt(self, *, choices=None, source_kind="independent_answer", independence="confirmed_independent",
                       prompt_status="none_confirmed", actual_date_state="known", actual_date=None):
        if actual_date is None and actual_date_state == "known":
            actual_date = date(2026, 10, 3)
        choices = choices or learning.learner_create_choices(self.owner, self.learner_id)
        observation_value = choices["observation_choices"][0][0]
        return learning.create_attempt(self.owner, self.learner_id, question_id=self.question_id,
            attempt_kind="first", source_kind=source_kind, independence=independence,
            prompt_status=prompt_status, prompts=("口头提示",) if prompt_status == "given" else (),
            actual_date_state=actual_date_state, actual_date=actual_date,
            legibility="readable", answer_text="5", authorship_basis="家长当面确认",
            observation_values=[observation_value], previous_attempt_id=None,
            context=choices["context"], request_key=key())

    def save_question_revision(self, printed_text, original_number, *, accept=False):
        detail = materials.question_detail(self.owner, self.question_id)
        saved = materials.save_question(self.owner, self.material.pk, printed_text=printed_text,
            original_number=original_number, sources=[self.source], question_id=self.question_id,
            expected_context=detail["edit_context"], request_key=key(), reason="修订合成题目")
        if accept:
            detail = materials.question_detail(self.owner, self.question_id)
            materials.review_question(self.owner, self.question_id, saved["revision_id"],
                action="accept", reason="核对合成题目修订", context=detail["review_context"],
                request_key=key())
        return saved

    def accept_correct_assessment(self, attempt_id):
        context = learning.assessment_context(self.owner, attempt_id)
        evidence_index = context["evidence_choices"][0][0][0]
        values = {"context_errata": []}
        for dimension in ("answer", "method", "process", "calculation", "notation"):
            if dimension in ("answer", "process"):
                values[dimension] = {"judgment": "correct", "basis": "observed",
                    "evidence": [evidence_index], "rationale": "原图可见", "unknown_reason": ""}
            else:
                values[dimension] = {"judgment": "unknown", "basis": "undetermined",
                    "evidence": [], "rationale": "", "unknown_reason": "本次没有评价该维度"}
        saved = learning.save_assessment(self.owner, attempt_id, values=values,
            context=context["context"], request_key=key(), reason="合成五维评价")
        review_context = learning.review_form_context(self.owner, saved["assessment_id"])
        learning.review_assessment(self.owner, saved["assessment_id"], saved["revision_id"],
            action="accept", reason="答案与过程已对照原图", context=review_context["review_context"],
            request_key=key())
        return saved

    def test_unknown_author_and_unknown_date_are_retained_without_creating_an_attempt_source(self):
        saved = learning.save_observation(self.owner, self.household.pk,
            profile_context_id=self.learner_id, legibility="unknown", author_state="unknown",
            author_learner_id=self.learner_id, confirmation_basis="不应被保存",
            actual_date_state="unknown", actual_date=None,
            notes="作者、日期和可读性均未确认；没有可用区域。", sources=[],
            reason="保留未知信息", request_key=key())
        bundle = core.read_snapshot_bundle(self.owner, self.household.pk)
        observation = next(row for row in bundle.observations if row.observation_id == saved["observation_id"])
        revision = observation.revisions[-1]
        self.assertEqual(revision.author_state.value, "unknown")
        self.assertIsNone(revision.author_learner_id)
        self.assertIsNone(revision.confirmed_by)
        self.assertIsNone(revision.confirmed_at)
        self.assertIsNone(revision.confirmation_basis)
        self.assertIsNone(revision.actual_date)
        self.assertEqual(revision.evidence_refs, ())

        choices = learning.learner_create_choices(self.owner, self.learner_id)
        with self.assertRaises(core.PersistenceError):
            learning.create_attempt(self.owner, self.learner_id, question_id=self.question_id,
                attempt_kind="first", source_kind="unknown", independence="unknown",
                prompt_status="unknown", prompts=(), actual_date_state="unknown", actual_date=None,
                legibility="unknown", answer_text="", authorship_basis="尚未确认",
                observation_values=[f"{observation.observation_id}|{revision.header.revision_id}"],
                previous_attempt_id=None, context=choices["context"], request_key=key())

    def test_distinct_attempts_keep_evaluations_separate_and_require_actual_acceptance(self):
        first = self.create_attempt()
        second = self.create_attempt()
        self.assertNotEqual(first["attempt_id"], second["attempt_id"])

        first_assessment = self.accept_correct_assessment(first["attempt_id"])
        second_assessment = self.accept_correct_assessment(second["attempt_id"])
        first_detail = learning.attempt_detail(self.owner, first["attempt_id"])
        second_detail = learning.attempt_detail(self.owner, second["attempt_id"])
        self.assertEqual(first_detail["attempt"].attempt_id, first["attempt_id"])
        self.assertEqual(second_detail["attempt"].attempt_id, second["attempt_id"])
        self.assertEqual(first_detail["assessments"][0]["assessment"].attempt_id, first["attempt_id"])
        self.assertEqual(second_detail["assessments"][0]["assessment"].attempt_id, second["attempt_id"])
        self.assertTrue(first_detail["independent_success"])
        self.assertTrue(second_detail["independent_success"])

        assessment_entity = EntityRecord.objects.get(kind="assessment", stable_id=first_assessment["assessment_id"])
        projection = ReviewProjection.objects.get(revision_id=first_assessment["revision_id"])
        self.assertEqual(projection.state, "accepted")
        published_revision_id = assessment_entity.published_revision_id
        self.assertEqual(published_revision_id, first_assessment["revision_id"])

        EntityRecord.objects.filter(pk=assessment_entity.pk).update(published_revision=None)
        self.assertFalse(learning.attempt_detail(self.owner, first["attempt_id"])["independent_success"])
        EntityRecord.objects.filter(pk=assessment_entity.pk).update(published_revision_id=published_revision_id)
        self.assertTrue(learning.attempt_detail(self.owner, first["attempt_id"])["independent_success"])

        review_context = learning.review_form_context(self.owner, first_assessment["assessment_id"])
        learning.review_assessment(self.owner, first_assessment["assessment_id"], first_assessment["revision_id"],
            action="reject", reason="测试实际审核投影控制显示", context=review_context["review_context"], request_key=key())
        projection.refresh_from_db()
        self.assertEqual(projection.state, "rejected")
        self.assertFalse(learning.attempt_detail(self.owner, first["attempt_id"])["independent_success"])

        before = learning.assessment_edit_context(self.owner, first_assessment["assessment_id"])
        context = before["context"]
        evidence_index = before["evidence_choices"][0][0][0]
        revised_values = {"context_errata": []}
        for dimension in ("answer", "method", "process", "calculation", "notation"):
            if dimension in ("answer", "process"):
                revised_values[dimension] = {"judgment": "correct", "basis": "observed",
                    "evidence": [evidence_index], "rationale": "复核原图", "unknown_reason": ""}
            else:
                revised_values[dimension] = {"judgment": "unknown", "basis": "undetermined",
                    "evidence": [], "rationale": "", "unknown_reason": "保留未评估"}
        learning.save_assessment(self.owner, first["attempt_id"], values=revised_values,
            context=context, request_key=key(), assessment_id=first_assessment["assessment_id"],
            reason="追加一次复核")
        history = learning.assessment_detail(self.owner, first_assessment["assessment_id"])
        self.assertEqual(len(history["history"]), 2)
        self.assertEqual(history["current_revision"].attempt_revision_id,
                         first_detail["current_revision"].header.revision_id)
        self.assertFalse(learning.attempt_detail(self.owner, first["attempt_id"])["independent_success"])
        self.assertTrue(learning.attempt_detail(self.owner, second["attempt_id"])["independent_success"])

    def test_question_choices_pin_publication_and_entity_head_separately(self):
        draft = self.save_question_revision("2 + 3 = 5", "J1-2")
        choices = learning.learner_create_choices(self.owner, self.learner_id)
        self.assertEqual(choices["context"]["question_versions"][self.question_id],
            self.question_revision_id)
        self.assertEqual(choices["context"]["question_heads"][self.question_id], draft["revision_id"])

        attempt = self.create_attempt(choices=choices)
        detail = learning.attempt_detail(self.owner, attempt["attempt_id"])
        self.assertEqual(detail["current_revision"].question_revision_id, self.question_revision_id)

        self.save_question_revision("2 + 3 = 6", "J1-3")
        with self.assertRaises(core.PersistenceError) as raised:
            self.create_attempt(choices=choices)
        self.assertEqual(raised.exception.code, "head_conflict")

    def test_profile_uses_exact_question_revision_and_marks_old_relation_as_history(self):
        first = self.create_attempt()
        node = knowledge.save_node(self.owner, self.household.pk, "knowledge", data={
            "definition": "加法知识", "conditions": "", "common_errors": "", "sources": "[]"},
            request_key=key(), reason="建立合成知识点")
        review = core.review_context(self.owner, self.household.pk, node["revision_id"])
        core.review_revision(self.owner, self.household.pk, node["revision_id"], action="accept",
            expected_head=review["expected_head"], expected_dependencies=review["expected_dependencies"],
            expected_decision_id=review["expected_decision_id"], request_key=key(), reason="确认知识点")
        link = knowledge.create_link(self.owner, self.household.pk, kind="knowledge",
            node_revision_id=node["revision_id"], question_revision_id=self.question_revision_id,
            role="applies", request_key=key(), reason="对应合成题目")
        review = core.review_context(self.owner, self.household.pk, link["revision_id"])
        core.review_revision(self.owner, self.household.pk, link["revision_id"], action="accept",
            expected_head=review["expected_head"], expected_dependencies=review["expected_dependencies"],
            expected_decision_id=review["expected_decision_id"], request_key=key(), reason="确认题目关系")

        same_name_node = knowledge.save_node(self.owner, self.household.pk, "knowledge", data={
            "definition": "加法知识", "conditions": "", "common_errors": "", "sources": "[]"},
            request_key=key(), reason="建立同名但身份不同的知识点")
        review = core.review_context(self.owner, self.household.pk, same_name_node["revision_id"])
        core.review_revision(self.owner, self.household.pk, same_name_node["revision_id"], action="accept",
            expected_head=review["expected_head"], expected_dependencies=review["expected_dependencies"],
            expected_decision_id=review["expected_decision_id"], request_key=key(), reason="确认同名知识点")
        same_name_link = knowledge.create_link(self.owner, self.household.pk, kind="knowledge",
            node_revision_id=same_name_node["revision_id"], question_revision_id=self.question_revision_id,
            role="applies", request_key=key(), reason="同名知识点精确关系")
        review = core.review_context(self.owner, self.household.pk, same_name_link["revision_id"])
        core.review_revision(self.owner, self.household.pk, same_name_link["revision_id"], action="accept",
            expected_head=review["expected_head"], expected_dependencies=review["expected_dependencies"],
            expected_decision_id=review["expected_decision_id"], request_key=key(), reason="确认同名知识点关系")

        self.save_question_revision("2 + 3 = 5", "J1-2", accept=True)
        second = self.create_attempt()
        profile = learning.profile_detail(self.owner, self.learner_id)
        attempts = {item["attempt"].attempt_id: item for item in profile["attempts"]}

        old = attempts[first["attempt_id"]]
        current = attempts[second["attempt_id"]]
        self.assertIn("J1-1", old["question_label"])
        self.assertIn("r1", old["question_label"])
        self.assertIn("J1-2", current["question_label"])
        self.assertIn("r2", current["question_label"])
        self.assertEqual(len(old["knowledge_labels"]), 2)
        self.assertTrue(all("加法知识" in label and "历史关系" in label for label in old["knowledge_labels"]))
        self.assertEqual(old["knowledge_ids"], frozenset((node["stable_id"], same_name_node["stable_id"])))
        self.assertEqual(len(set(old["knowledge_labels"])), 2)
        self.assertTrue(all('同名条目' in label for label in old['knowledge_labels']))
        self.assertTrue(all(stable_id[-8:] not in " ".join(old["knowledge_labels"])
            for stable_id in (node["stable_id"], same_name_node["stable_id"])))
        self.assertEqual({item["stable_id"] for item in profile["knowledge_options"]},
            {node["stable_id"], same_name_node["stable_id"]})
        self.assertEqual(len({item["label"] for item in profile["knowledge_options"]}), 2)
        self.assertEqual(current["knowledge_labels"], ())
        self.assertEqual(current["knowledge_ids"], frozenset())

        review = core.review_context(self.owner, self.household.pk, same_name_link["revision_id"])
        core.review_revision(self.owner, self.household.pk, same_name_link["revision_id"], action="withdraw",
            expected_head=review["expected_head"], expected_dependencies=review["expected_dependencies"],
            expected_decision_id=review["expected_decision_id"], request_key=key(), reason="撤回同名关系")
        withdrawn_profile = learning.profile_detail(self.owner, self.learner_id)
        withdrawn_old = next(item for item in withdrawn_profile["attempts"]
            if item["attempt"].attempt_id == first["attempt_id"])
        self.assertEqual(withdrawn_old["knowledge_ids"], frozenset((node["stable_id"],)))
        self.assertEqual({item["stable_id"] for item in withdrawn_profile["knowledge_options"]},
            {node["stable_id"]})

    def test_identity_correction_withdraws_old_attempt_and_keeps_its_assessment_link(self):
        original = self.create_attempt()
        assessment = self.accept_correct_assessment(original["attempt_id"])
        replacement_profile = learning.create_profile(self.owner, self.household.pk,
            display_name="小禾（更正作者）", grade="三年级", request_key=key())
        replacement_learner_id = replacement_profile["learner_id"]
        learning.save_observation(self.owner, self.household.pk,
            profile_context_id=replacement_learner_id, legibility="readable", author_state="confirmed",
            author_learner_id=replacement_learner_id, confirmation_basis="家长确认作者身份",
            actual_date_state="known", actual_date=date(2026, 10, 3), notes="替代作者的合成观察",
            sources=[self.source], reason="补录更正作者的来源观察", request_key=key())

        choices = learning.learner_create_choices(self.owner, replacement_learner_id)
        observation_value = choices["observation_choices"][0][0]
        replacement = learning.create_attempt(self.owner, replacement_learner_id,
            question_id=self.question_id, attempt_kind="first", source_kind="independent_answer",
            independence="confirmed_independent", prompt_status="none_confirmed", prompts=(),
            actual_date_state="known", actual_date=date(2026, 10, 3), legibility="readable",
            answer_text="5", authorship_basis="更正后的作者当面确认",
            observation_values=[observation_value], previous_attempt_id=None,
            context={**choices["context"], "replacement_context": learning.attempt_edit_context(
                self.owner, original["attempt_id"])["edit_context"]},
            request_key=key(), replacement_for=original["attempt_id"])

        original_history = learning.attempt_detail(self.owner, original["attempt_id"])
        replacement_detail = learning.attempt_detail(self.owner, replacement["attempt_id"])
        self.assertEqual(original_history["current_revision"].state.value, "withdrawn")
        self.assertEqual(original_history["current_revision"].replacement_attempt_id, replacement["attempt_id"])
        self.assertEqual(replacement_detail["attempt"].supersedes_attempt_id, original["attempt_id"])
        self.assertEqual(original_history["assessments"][0]["assessment"].assessment_id,
                         assessment["assessment_id"])
        self.assertEqual(original_history["assessments"][0]["assessment"].attempt_id,
                         original["attempt_id"])
        self.assertFalse(original_history["independent_success"])
        old_profile_attempts = learning.profile_detail(self.owner, self.learner_id)["attempts"]
        replacement_profile_attempts = learning.profile_detail(self.owner, replacement_learner_id)["attempts"]
        self.assertEqual([item["attempt"].attempt_id for item in old_profile_attempts],
                         [original["attempt_id"]])
        self.assertEqual(old_profile_attempts[0]["revision"].state.value, "withdrawn")
        self.assertEqual([item["attempt"].attempt_id for item in replacement_profile_attempts],
                         [replacement["attempt_id"]])
        self.assertEqual(replacement_profile_attempts[0]["revision"].state.value, "active")
        client = Client()
        client.force_login(self.owner)
        old_overview = client.get(
            f"/api/v1/learners/{self.learner_id}/overview/?household={self.household.pk}").json()
        old_history = client.get(
            f"/api/v1/learners/{self.learner_id}/attempts/?household={self.household.pk}").json()
        replacement_overview = client.get(
            f"/api/v1/learners/{replacement_learner_id}/overview/?household={self.household.pk}").json()
        self.assertEqual(old_overview["recent_attempts"], [])
        self.assertEqual([(row["attempt_id"], row["state"]) for row in old_history["items"]],
                         [(original["attempt_id"], "withdrawn")])
        self.assertEqual([row["attempt_id"] for row in replacement_overview["recent_attempts"]],
                         [replacement["attempt_id"]])

    def test_prompted_classroom_unknown_and_date_mismatch_never_count_as_independent_success(self):
        attempts = [
            self.create_attempt(source_kind="assisted_answer", independence="not_independent",
                prompt_status="given"),
            self.create_attempt(source_kind="classroom_note", independence="not_independent",
                prompt_status="unknown"),
            self.create_attempt(source_kind="unknown", independence="unknown", prompt_status="unknown"),
            self.create_attempt(actual_date=date(2026, 10, 4)),
            self.create_attempt(actual_date_state="unknown", actual_date=None),
        ]
        for attempt in attempts:
            with self.subTest(attempt=attempt["attempt_id"]):
                self.accept_correct_assessment(attempt["attempt_id"])
                detail = learning.attempt_detail(self.owner, attempt["attempt_id"])
                self.assertFalse(detail["independent_success"])

    def test_assessment_evidence_indices_reject_negative_and_non_integer_values(self):
        attempt = self.create_attempt()
        context = learning.assessment_context(self.owner, attempt["attempt_id"])
        evidence_index = context["evidence_choices"][0][0][0]
        for invalid_index in ("-1", None):
            values = {"context_errata": []}
            for dimension in ("answer", "method", "process", "calculation", "notation"):
                if dimension == "answer":
                    selected = [invalid_index]
                    judgment, basis, rationale, unknown_reason = "correct", "observed", "原图可见", ""
                elif dimension == "process":
                    selected = [evidence_index]
                    judgment, basis, rationale, unknown_reason = "correct", "observed", "原图可见", ""
                else:
                    selected = []
                    judgment, basis, rationale, unknown_reason = "unknown", "undetermined", "", "未评价"
                values[dimension] = {"judgment": judgment, "basis": basis, "evidence": selected,
                    "rationale": rationale, "unknown_reason": unknown_reason}
            with self.subTest(invalid_index=invalid_index), self.assertRaises(core.PersistenceError) as raised:
                learning.save_assessment(self.owner, attempt["attempt_id"], values=values,
                    context=context["context"], request_key=key(), reason="无效证据索引")
            self.assertEqual(raised.exception.code, "invalid_input")
