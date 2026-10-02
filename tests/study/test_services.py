from datetime import date
from io import BytesIO
import json
import os
import tempfile
from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image

from app.ai import services as ai
from app.ai.models import ModelConfig, ModelRun
from app.persistence import services as core
from app.persistence.models import EntityRecord, EvidenceRecord, HouseholdMember, ReviewProjection
from app.web import knowledge_services
from app.web import learning_services as learning
from app.web import services as materials
from app.study import services as study
from app.study.models import ScheduleRevision, StudySchedule, VariantProvenance


def key():
    return str(uuid4())


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (120, 80), color=(230, 234, 239)).save(output, format="PNG")
    return output.getvalue()


class StudyServiceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="swb-study-test-")
        os.chmod(directory.name, 0o700)
        self.addCleanup(directory.cleanup)
        settings = override_settings(SWB_DATA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.owner = get_user_model().objects.create_user(
            username=f"study-owner-{uuid4().hex[:8]}", password="synthetic-only")
        self.other = get_user_model().objects.create_user(
            username=f"study-other-{uuid4().hex[:8]}", password="synthetic-only")
        self.household = core.create_household(self.owner, f"study-{uuid4().hex}")
        self.other_household = core.create_household(self.other, f"study-other-{uuid4().hex}")
        self.viewer = get_user_model().objects.create_user(
            username=f"study-viewer-{uuid4().hex[:8]}", password="synthetic-only")
        HouseholdMember.objects.create(household=self.household, user=self.viewer,
            role=HouseholdMember.Role.VIEWER)

        self.material = materials.create_material(self.owner, self.household.pk, "合成题目", key())
        page = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile("study.png", png_bytes(), content_type="image/png"), key())
        self.page_id = page["page_id"]
        preview = materials.preview_file(self.owner, self.page_id, 0)
        self.source = {"page_id": self.page_id, "rotation": 0,
            "preview_sha256": preview.sha256, "display_bbox": [8, 8, 100, 70]}
        saved = materials.save_question(self.owner, self.material.pk,
            printed_text="4 × 2 = ?", original_number="K1", sources=[self.source],
            request_key=key(), reason="合成测试题")
        detail = materials.question_detail(self.owner, saved["question_id"])
        materials.review_question(self.owner, saved["question_id"], saved["revision_id"],
            action="accept", reason="合成题干已核对", context=detail["review_context"], request_key=key())
        self.question_id = saved["question_id"]
        self.question_revision_id = saved["revision_id"]

        profile = learning.create_profile(self.owner, self.household.pk,
            display_name="小禾", grade="三年级", request_key=key())
        self.learner_id = profile["learner_id"]
        self.learner_entity = EntityRecord.objects.get(kind="learner", stable_id=self.learner_id)
        self.observation = self.create_observation(date(2026, 10, 1))

    def create_observation(self, occurred):
        return learning.save_observation(self.owner, self.household.pk,
            profile_context_id=self.learner_id, legibility="readable", author_state="confirmed",
            author_learner_id=self.learner_id, confirmation_basis="家长人工确认",
            actual_date_state="known", actual_date=occurred, notes="合成的可辨作答区域",
            sources=[self.source], reason="录入合成观察", request_key=key())

    def create_attempt(self, *, occurred=date(2026, 10, 1), observation=None):
        choices = learning.learner_create_choices(self.owner, self.learner_id)
        selected = self.observation["observation_id"] if observation is None else observation["observation_id"]
        selected_observation = next(value for value, _ in choices["observation_choices"]
            if value.startswith(f"{selected}|"))
        result = learning.create_attempt(self.owner, self.learner_id, question_id=self.question_id,
            attempt_kind="first", source_kind="independent_answer", independence="confirmed_independent",
            prompt_status="none_confirmed", prompts=(), actual_date_state="known", actual_date=occurred,
            legibility="readable", answer_text="8", authorship_basis="当面确认",
            observation_values=[selected_observation], previous_attempt_id=None,
            context=choices["context"], request_key=key())
        current = learning.attempt_detail(self.owner, result["attempt_id"])["current_revision"]
        return {**result, "revision_id": current.header.revision_id}

    def save_and_review(self, attempt_id, *, judgment="correct"):
        context = learning.assessment_context(self.owner, attempt_id)
        evidence_index = context["evidence_choices"][0][0][0]
        values = {"context_errata": []}
        for name in ("answer", "method", "process", "calculation", "notation"):
            if name in ("answer", "process"):
                values[name] = {"judgment": judgment, "basis": "observed",
                    "evidence": [evidence_index], "rationale": "合成原图可见", "unknown_reason": ""}
            else:
                values[name] = {"judgment": "unknown", "basis": "undetermined",
                    "evidence": [], "rationale": "", "unknown_reason": "本次未评价该维度"}
        saved = learning.save_assessment(self.owner, attempt_id, values=values,
            context=context["context"], request_key=key(), reason="合成评价")
        review = learning.review_form_context(self.owner, saved["assessment_id"])
        learning.review_assessment(self.owner, saved["assessment_id"], saved["revision_id"],
            action="accept", reason="按合成原图核对", context=review["review_context"], request_key=key())
        return saved

    def schedule_context(self):
        return study.new_schedule_context(self.owner, self.learner_entity.pk)

    def create_schedule(self):
        context = self.schedule_context()
        result = study.create_schedule(self.owner, self.learner_entity.pk,
            question_revision_id=self.question_revision_id, due_date=date(2026, 10, 8),
            goal="独立完成两步计算", prompt_plan="先提醒检查乘法顺序", reason="复习安排",
            context=context["context"], request_key=key())
        return result, context

    def publish_question_revision(self, printed_text):
        detail = materials.question_detail(self.owner, self.question_id)
        saved = materials.save_question(self.owner, self.material.pk,
            printed_text=printed_text, original_number="K1", sources=[self.source],
            question_id=self.question_id, expected_context=detail["edit_context"],
            request_key=key(), reason="发布合成题目修订")
        detail = materials.question_detail(self.owner, self.question_id)
        materials.review_question(self.owner, self.question_id, saved["revision_id"],
            action="accept", reason="合成题目修订已核对",
            context=detail["review_context"], request_key=key())
        return saved["revision_id"]

    def create_variant_run(self):
        method = knowledge_services.save_node(self.owner, self.household.pk, "method", data={
            "name": "分步计算", "conditions": "整数四则运算", "steps": "先算乘法再计算",
            "notes": "", "parent_revision_id": "", "sources": "[]"},
            request_key=key(), reason="建立合成方法")
        method_context = core.review_context(self.owner, self.household.pk, method["revision_id"])
        core.review_revision(self.owner, self.household.pk, method["revision_id"], action="accept",
            expected_head=method_context["expected_head"],
            expected_dependencies=method_context["expected_dependencies"],
            expected_decision_id=method_context["expected_decision_id"],
            request_key=key(), reason="确认合成方法")
        config = ModelConfig.objects.create(household=self.household, revision_no=1,
            created_by=self.owner, provider_label="synthetic", base_url="https://unused.invalid/v1",
            model="synthetic", cloud_enabled=True, non_billable_gateway=True)
        selection = ai.selection_context(self.owner, self.household.pk, "variant")
        run = ai.queue_run(self.owner, self.household.pk, task_kind="variant",
            source_revision_ids=[method["revision_id"]],
            question_revision_ids=[self.question_revision_id],
            selection_token=selection["token"], request_key=key())
        response = {"schema_version":"study-workbench.ai.v1", "task":"variant",
            "source_revision_ids":[method['revision_id'],self.question_revision_id], "tool_calls":[],
            "proposal": {"text": "7 × 8 = ?", "answer_expression": "7 * 8",
                "check_expression": "56", "target_method_revision_id": method["revision_id"]}}
        ai.request_execution(self.owner,run.pk)
        with patch.dict(os.environ,{'SWB_MODEL_ALLOWED_HOSTS':'unused.invalid',
                'SWB_MODEL_API_KEY':'synthetic-only'},clear=False), patch('app.ai.services.chat_completion',
                return_value=(json.dumps(response),{'prompt_tokens':10,'completion_tokens':10})):
            ai.execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status,ModelRun.Status.AWAITING_REVIEW,run.error_code)
        return run, method

    def apply_variant_run(self):
        run, method = self.create_variant_run()
        request_key = key()
        applied = ai.apply_run(self.owner, run.pk, request_key=request_key)
        run.refresh_from_db()
        return run, method, request_key, applied

    def test_schedule_create_replay_survives_later_question_publication(self):
        context = self.schedule_context()["context"]
        request_key = key()
        command = {"question_revision_id": self.question_revision_id,
            "due_date": date(2026, 10, 8), "goal": "独立完成两步计算",
            "prompt_plan": "先提醒检查乘法顺序", "reason": "复习安排",
            "context": context, "request_key": request_key}
        created = study.create_schedule(self.owner, self.learner_entity.pk, **command)
        self.publish_question_revision("4 + 4 = ?")

        replay = study.create_schedule(self.owner, self.learner_entity.pk, **command)

        self.assertEqual(replay, created)
        self.assertEqual(StudySchedule.objects.count(), 1)

    def test_applied_variant_stages_exact_provenance_and_publication_gate(self):
        self.assertIsNone(study.validate_variant_publication(self.owner, self.question_revision_id))
        run, method, request_key, applied = self.apply_variant_run()
        self.assertEqual(run.status, ModelRun.Status.APPLIED)
        self.assertEqual(len(applied["revision_ids"]), 1)
        revision_id = applied["revision_ids"][0]
        question = EntityRecord.objects.get(kind="question", head_revision_id=revision_id)
        provenance = VariantProvenance.objects.get(question=question)
        self.assertEqual(provenance.run_id, str(run.pk))
        self.assertEqual(provenance.parent_question_revision_id, self.question_revision_id)
        self.assertEqual(provenance.target_method_revision_id, method["revision_id"])
        self.assertEqual(run.source_revision_ids, [method["revision_id"]])
        self.assertEqual(provenance.source_revision_ids,
                         [self.question_revision_id, method["revision_id"]])
        self.assertEqual(question.head_revision.payload["working_text"], "7 × 8 = ?")
        self.assertEqual(question.head_revision.payload["header"]["origin"], "ai")
        self.assertEqual(question.head_revision.payload["evidence_refs"][0]["purpose"], "other")
        variant_evidence = EvidenceRecord.objects.get(source=question.head_revision)
        parent_evidence = EvidenceRecord.objects.get(source_id=self.question_revision_id)
        self.assertEqual(variant_evidence.image_id, parent_evidence.image_id)
        self.assertEqual(variant_evidence.region_id, parent_evidence.region_id)
        self.assertEqual(variant_evidence.purpose, "other")

        replay = study.stage_variant(self.owner, str(self.household.pk), str(run.pk),
            parent_question_revision_id=self.question_revision_id,
            target_method_revision_id=method["revision_id"], text="7 × 8 = ?",
            answer_expression="7 * 8", check_expression="56",
            source_revision_ids=[method["revision_id"]], request_key=request_key)
        self.assertEqual(replay["revision_id"], revision_id)
        self.assertEqual(VariantProvenance.objects.filter(question=question).count(), 1)

        self.assertEqual(study.validate_variant_publication(self.owner, revision_id),
                         {"run_id": str(run.pk), "revision_id": revision_id})

        client = Client()
        client.force_login(self.owner)
        generic_url = reverse("knowledge:question_detail", kwargs={"entity_id": question.pk})
        legacy_detail_url = reverse("web:question_detail", kwargs={"question_id": question.stable_id})
        legacy_edit_url = reverse("web:question_edit", kwargs={"question_id": question.stable_id})
        detail_redirect = client.get(legacy_detail_url)
        self.assertRedirects(detail_redirect, generic_url)
        edit_redirect = client.get(legacy_edit_url)
        self.assertRedirects(edit_redirect, generic_url)

        generic = client.get(generic_url)
        self.assertEqual(generic.status_code, 200)
        self.assertContains(generic, "7 × 8 = ?")
        self.assertContains(generic, "AI 生成变式")
        self.assertContains(generic, "父题")
        self.assertContains(generic, "方法")
        self.assertContains(generic, "其他来源／生成依据")
        self.assertNotContains(generic, "印刷题干待补")

        page = client.get(reverse("web:page_detail", kwargs={"page_id": self.page_id}))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, legacy_detail_url)
        backlink = client.get(legacy_detail_url, follow=True)
        self.assertEqual(backlink.status_code, 200)
        self.assertEqual(backlink.redirect_chain, [(generic_url, 302)])

        client.force_login(self.other)
        self.assertEqual(client.get(generic_url).status_code, 404)

    def test_variant_publication_rejects_a_changed_source_method(self):
        run, method, _, applied = self.apply_variant_run()
        revision_id = applied["revision_ids"][0]
        method_entity = EntityRecord.objects.get(kind="method", stable_id=method["stable_id"])
        detail = knowledge_services.node_detail(self.owner, method_entity.pk)
        knowledge_services.save_node(self.owner, self.household.pk, "method", data={
            "name": "分步计算修订", "conditions": "整数四则运算", "steps": "先算乘法再计算",
            "notes": "", "parent_revision_id": "", "sources": "[]"},
            request_key=key(), reason="修订合成方法", stable_id=method["stable_id"],
            expected_context=detail["edit_context"])

        with self.assertRaises(core.PersistenceError):
            study.validate_variant_publication(self.owner, revision_id)

    def test_schedule_events_append_replay_and_reject_stale_or_terminal_writes(self):
        created, _ = self.create_schedule()
        replay_context = self.schedule_context()["context"]
        # A replay must use the original signed inputs and key, not a newly loaded context.
        original_context = study.new_schedule_context(self.owner, self.learner_entity.pk)["context"]
        # New commands create fresh identities; one command replay is exercised by event below.
        schedule_pk = created["schedule_pk"]
        detail = study.schedule_detail(self.owner, schedule_pk)
        event_key = key()
        event = {"action": "rescheduled", "context": detail["context"],
            "due_date": date(2026, 10, 10), "goal": "重新尝试", "prompt_plan": "先观察再提示",
            "reason": "时间调整"}
        changed = study.append_schedule_event(self.owner, schedule_pk, **event, request_key=event_key)
        replay = study.append_schedule_event(self.owner, schedule_pk, **event, request_key=event_key)
        self.assertEqual(changed, replay)
        self.assertEqual(ScheduleRevision.objects.filter(schedule_id=schedule_pk).count(), 2)
        with self.assertRaises(core.PersistenceError):
            study.append_schedule_event(self.owner, schedule_pk, **event, request_key=key())

        latest = study.schedule_detail(self.owner, schedule_pk)
        cancelled = study.append_schedule_event(self.owner, schedule_pk,
            action="cancelled", context=latest["context"], reason="取消本轮复习", request_key=key())
        self.assertEqual(cancelled["action"], "cancelled")
        history = study.schedule_detail(self.owner, schedule_pk)["history"]
        self.assertEqual([item.action for item in history], ["planned", "rescheduled", "cancelled"])
        self.assertEqual(history[0].due_date, date(2026, 10, 8))
        self.assertEqual(history[1].due_date, date(2026, 10, 10))
        with self.assertRaises(core.PersistenceError):
            study.append_schedule_event(self.owner, schedule_pk,
                action="rescheduled", context=study.schedule_detail(self.owner, schedule_pk)["context"],
                due_date=date(2026, 10, 12), goal="不应追加", reason="终态不能改期", request_key=key())

    def test_schedule_completion_binds_only_current_active_exact_attempt(self):
        created, _ = self.create_schedule()
        schedule_pk = created["schedule_pk"]
        choices = study.schedule_attempt_choices(self.owner, schedule_pk)["choices"]
        self.assertEqual(choices, [])
        attempt = self.create_attempt()
        choices = study.schedule_attempt_choices(self.owner, schedule_pk)["choices"]
        self.assertEqual([item["revision"].header.revision_id for item in choices],
                         [attempt["revision_id"]])
        self.publish_question_revision("4 + 4 = ?")
        newer_attempt = self.create_attempt(occurred=date(2026, 10, 2))
        choices = study.schedule_attempt_choices(self.owner, schedule_pk)["choices"]
        self.assertEqual([item["revision"].header.revision_id for item in choices],
                         [attempt["revision_id"]])
        self.assertNotEqual(newer_attempt["revision_id"], attempt["revision_id"])
        detail = study.schedule_detail(self.owner, schedule_pk)
        completion = study.append_schedule_event(self.owner, schedule_pk,
            action="completed", context=detail["context"], attempt_revision_id=attempt["revision_id"],
            reason="记录实际完成", request_key=key())
        self.assertEqual(completion["action"], "completed")
        after = study.schedule_detail(self.owner, schedule_pk)
        self.assertEqual(after["completion_history"][0]["revision"].header.revision_id, attempt["revision_id"])
        self.assertEqual(after["completion_history"][0]["actual_date"], "2026-10-01")
        self.assertEqual(after["completion_history"][0]["revision"].source_kind.value, "independent_answer")
        self.assertEqual(after["completion_history"][0]["revision"].prompt_status.value, "none_confirmed")

    def test_report_uses_real_review_projection_pins_versions_and_only_known_actual_dates(self):
        first = self.create_attempt()
        second = self.create_attempt(occurred=date(2026, 10, 2))
        first_eval = self.save_and_review(first["attempt_id"], judgment="incorrect")
        second_eval = self.save_and_review(second["attempt_id"], judgment="incorrect")
        projection = ReviewProjection.objects.get(revision_id=second_eval["revision_id"])
        self.assertEqual(projection.state, "accepted")

        report = study.evidence_report(self.owner, self.learner_entity.pk)
        self.assertEqual(len(report["attempts"]), 2)
        self.assertEqual({item["question_revision_id"] for item in report["attempts"]},
                         {self.question_revision_id})
        self.assertTrue(report["attempts"][0]["recorded_at"])
        self.assertEqual(report["known_actual_date_intervals"][0]["days"], 1)
        self.assertFalse(next(item for item in report["attempts"]
            if item["attempt_id"] == second["attempt_id"])["independent_success"])
        second_attempt_row = next(item for item in report["attempts"]
            if item["attempt_id"] == second["attempt_id"])
        second_assessment_row = second_attempt_row["assessments"][0]
        self.assertEqual(second_assessment_row["reviewer_id"], projection.decision.actor_id)
        error_pairs = {(item["question_id"], item["dimension"]) for item in report["repeated_errors"]}
        self.assertIn((self.question_id, "answer"), error_pairs)

        second_entity = EntityRecord.objects.get(kind="assessment", stable_id=second_eval["assessment_id"])
        EntityRecord.objects.filter(pk=second_entity.pk).update(published_revision=None)
        report = study.evidence_report(self.owner, self.learner_entity.pk)
        self.assertFalse(report["repeated_errors"])

    def test_identity_withdrawal_stays_in_report_history_but_not_in_learning_insights(self):
        original = self.create_attempt()
        self.save_and_review(original["attempt_id"], judgment="incorrect")
        replacement_profile = learning.create_profile(self.owner, self.household.pk,
            display_name="更正后的作者", grade="三年级", request_key=key())
        replacement_learner_id = replacement_profile["learner_id"]
        learning.save_observation(self.owner, self.household.pk,
            profile_context_id=replacement_learner_id, legibility="readable", author_state="confirmed",
            author_learner_id=replacement_learner_id, confirmation_basis="家长更正作者归属",
            actual_date_state="known", actual_date=date(2026, 10, 1), notes="更正作者的合成来源观察",
            sources=[self.source], reason="补充作者更正来源", request_key=key())
        choices = learning.learner_create_choices(self.owner, replacement_learner_id)
        observation_value = choices["observation_choices"][0][0]
        replacement_context = learning.attempt_edit_context(self.owner, original["attempt_id"])
        learning.create_attempt(self.owner, replacement_learner_id, question_id=self.question_id,
            attempt_kind="first", source_kind="independent_answer", independence="confirmed_independent",
            prompt_status="none_confirmed", prompts=(), actual_date_state="known",
            actual_date=date(2026, 10, 1), legibility="readable", answer_text="8",
            authorship_basis="更正后的作者当面确认", observation_values=[observation_value],
            previous_attempt_id=None, context={**choices["context"],
                "replacement_context": replacement_context["edit_context"]},
            request_key=key(), replacement_for=original["attempt_id"])

        report = study.evidence_report(self.owner, self.learner_entity.pk)
        self.assertEqual(len(report["attempts"]), 1)
        withdrawn = report["attempts"][0]
        self.assertEqual(withdrawn["attempt_id"], original["attempt_id"])
        self.assertEqual(withdrawn["state"], "withdrawn")
        self.assertEqual(withdrawn["withdrawal_reason"], "identity_error")
        self.assertIsNotNone(withdrawn["replacement_attempt_id"])
        self.assertFalse(withdrawn["independent_success"])
        self.assertEqual(report["observed_correct_methods"], [])
        self.assertEqual(report["repeated_errors"], [])
        self.assertEqual(report["known_actual_date_intervals"], [])

    def test_family_scope_and_viewer_write_boundary(self):
        context = self.schedule_context()
        with self.assertRaises(core.PersistenceError):
            study.new_schedule_context(self.other, self.learner_entity.pk)
        with self.assertRaises(core.PersistenceError):
            study.create_schedule(self.viewer, self.learner_entity.pk,
                question_revision_id=self.question_revision_id, due_date=date(2026, 10, 8),
                goal="查看者不能保存", reason="测试", context=context["context"], request_key=key())
        self.assertEqual(StudySchedule.objects.count(), 0)
