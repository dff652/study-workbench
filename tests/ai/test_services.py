"""Offline, fabricated household workflows for the optional model service."""
import json
import os
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, PngImagePlugin

from app.ai import services as ai
from app.ai.models import ModelBudgetReservation, ModelConfig, ModelRun
from app.ai.provider import ProviderFailure
from app.domain import Origin
from app.persistence import services as core
from app.persistence.models import EntityRecord, EvidenceRecord, HouseholdMember, RevisionRecord, ReviewProjection
from app.printing import services as printing
from app.web import services as materials
from app.web import knowledge_services
from app.web.records import edit_context


def key():
    return uuid.uuid4().hex


def png_bytes():
    output = BytesIO()
    image = Image.new("RGB", (80, 60), (210, 220, 230))
    image.putpixel((0, 0), (255, 0, 0))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("synthetic-note", "never forward original metadata")
    image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


class AIWorkflowTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.owner = get_user_model().objects.create_user(username=f"ai-owner-{suffix}", password="synthetic-only")
        self.reviewer = get_user_model().objects.create_user(username=f"ai-reviewer-{suffix}", password="synthetic-only")
        self.viewer = get_user_model().objects.create_user(username=f"ai-viewer-{suffix}", password="synthetic-only")
        self.household = core.create_household(self.owner, f"study-workbench-{suffix}")
        HouseholdMember.objects.create(household=self.household, user=self.reviewer, role="reviewer")
        HouseholdMember.objects.create(household=self.household, user=self.viewer, role="viewer")
        self.other = get_user_model().objects.create_user(username=f"ai-other-{suffix}", password="synthetic-only")
        self.other_household = core.create_household(self.other, f"ai-other-{suffix}")
        self.temp = tempfile.TemporaryDirectory(prefix="swb-ai-tests-")
        self.addCleanup(self.temp.cleanup)
        self.settings = override_settings(SWB_DATA_ROOT=self.temp.name,
            SWB_TEST_OWNER=self.owner.username, SWB_AI_ALLOW_TEST_HTTP=True, SWB_PRODUCTION=False)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.material = materials.create_material(self.owner, self.household.pk, "合成模型来源", key())
        self.original_bytes = png_bytes()
        self.page = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile("fabricated.png", self.original_bytes, content_type="image/png"), key())
        preview = materials.preview_file(self.owner, self.page["page_id"], 0)
        self.source = {"page_id": self.page["page_id"], "rotation": 0,
            "preview_sha256": preview.sha256, "display_bbox": [5, 6, 30, 36]}
        self.config = self.make_config()
        self.published = self.make_question("原始题干：3 + 4 = ?")

    def config_data(self, *, budget="10", reserved="0.1", scope="selected_regions",
                    cloud_enabled=True, confirm=True):
        return {
            "provider_label": "合成兼容服务", "base_url": "http://127.0.0.1:1/v1",
            "model": "fabricated-model", "connection_route": "gateway",
            "upstream_state": "unknown", "known_upstream_providers": "",
            "retention_state": "unknown", "retention_description": "",
            "confirm_external_processing": confirm,
            "cloud_enabled": cloud_enabled, "outbound_scope": scope,
            "timeout_seconds": 2, "max_output_tokens": 100, "max_input_chars": 2000,
            "max_calls": 4, "batch_budget": budget, "input_price_per_million": "1",
            "output_price_per_million": "1", "reserved_per_call": reserved,
            "non_billable_gateway": False,
        }

    def make_config(self, *, budget="10", reserved="0.1", scope="selected_regions"):
        return ai.create_model_config(self.owner, self.household.pk,
            data=self.config_data(budget=budget, reserved=reserved, scope=scope))

    def make_question(self, text):
        saved = materials.save_question(self.owner, self.material.pk, printed_text=text,
            original_number="AI-1", sources=[self.source], request_key=key(), reason="合成题目")
        context = core.review_context(self.owner, self.household.pk, saved["revision_id"])
        core.review_revision(self.owner, self.household.pk, saved["revision_id"], action="accept",
            expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
            expected_decision_id=context["expected_decision_id"], request_key=key(), reason="人工核对合成题干")
        return saved

    def make_blank_question(self):
        return materials.save_question(self.owner, self.material.pk, printed_text="",
            original_number="AI-OCR", sources=[self.source], request_key=key(), reason="创建空白合成题干")

    def region_for(self, revision_id):
        return str(EvidenceRecord.objects.get(source_id=revision_id, region__isnull=False).region_id)

    def queue_question(self, question, *, image=False, request_key=None):
        context = ai.selection_context(self.owner, self.household.pk, "question")
        revision_id = question["revision_id"]
        return ai.queue_run(self.owner, self.household.pk, task_kind="question",
            source_revision_ids=[revision_id], question_revision_ids=[revision_id],
            selected_region_revision_ids=[self.region_for(revision_id)] if image else [],
            selection_token=context["token"], request_key=request_key or key())

    def proposal_response(self, run, *, printed_text):
        allowed_ids = list(dict.fromkeys(run.source_revision_ids + run.question_revision_ids
            + run.selected_region_revision_ids))
        return json.dumps({"schema_version": "study-workbench.ai.v1", "task": "question",
            "source_revision_ids": allowed_ids, "proposal": {"printed_text": printed_text,
                "missing_fields": [], "classification_suggestion": None, "analysis_suggestion": None},
            "tool_calls": []}, ensure_ascii=False)

    def test_external_configuration_requires_manual_confirmation_and_auditable_unknowns(self):
        from app.ai.forms import ModelConfigForm

        state_fields = ("connection_route", "upstream_state", "retention_state")
        unconfigured_form = ModelConfigForm()
        for field in state_fields:
            self.assertTrue(unconfigured_form.fields[field].required)
            self.assertEqual(unconfigured_form.fields[field].choices[0], ("", "请选择"))
            self.assertIsNone(unconfigured_form[field].value())
        blank_data = self.config_data()
        for field in state_fields:
            blank_data[field] = ""
        blank_form = ModelConfigForm(data=blank_data)
        self.assertFalse(blank_form.is_valid())
        for field in state_fields:
            self.assertIn(field, blank_form.errors)
            self.assertIsNone(ModelConfigForm(initial={field: None})[field].value())
        saved_form = ModelConfigForm(initial={field: getattr(self.config, field) for field in state_fields})
        self.assertEqual([saved_form[field].value() for field in state_fields],
            [self.config.connection_route, self.config.upstream_state, self.config.retention_state])

        form = ModelConfigForm(data=self.config_data(confirm=False))
        self.assertFalse(form.is_valid())
        self.assertIn("confirm_external_processing", form.errors)
        with self.assertRaises(core.PersistenceError) as missing_confirmation:
            ai.create_model_config(self.owner, self.household.pk,
                data=self.config_data(confirm=False))
        self.assertEqual(missing_confirmation.exception.code, "model_consent_required")
        self.assertEqual(ModelConfig.objects.count(), 1)

        for changes in (
                {"upstream_state": "known", "known_upstream_providers": ""},
                {"retention_state": "known", "retention_description": ""},
                {"connection_route": ""}, {"upstream_state": ""}, {"retention_state": ""}):
            data = self.config_data()
            data.update(changes)
            with self.assertRaises(core.PersistenceError):
                ai.create_model_config(self.owner, self.household.pk, data=data)

        self.assertEqual(self.config.connection_route, ModelConfig.ConnectionRoute.GATEWAY)
        self.assertEqual(self.config.upstream_state, ModelConfig.DeclarationState.UNKNOWN)
        self.assertEqual(self.config.retention_state, ModelConfig.DeclarationState.UNKNOWN)
        self.assertEqual(self.config.outbound_confirmation_by_id, self.owner.pk)
        self.assertIsNotNone(self.config.outbound_confirmation_at)

    def test_task_binds_complete_consent_snapshot_and_scope_expansion_requires_new_confirmation(self):
        run = self.queue_question(self.published)
        self.assertEqual(run.config_snapshot, ai.config_snapshot(self.config))
        self.assertEqual(run.config_snapshot["config_id"], str(self.config.pk))
        self.assertEqual(run.config_snapshot["upstream_state"], "unknown")
        self.assertEqual(run.config_snapshot["retention_state"], "unknown")
        self.assertEqual(run.config_snapshot["outbound_confirmation_by"], str(self.owner.pk))
        self.assertEqual(run.config_snapshot["outbound_scope"], self.config.outbound_scope)

        changed = self.config_data(confirm=False, scope=ModelConfig.OutboundScope.SELECTED_REGIONS)
        changed.update(upstream_state="known", known_upstream_providers="Synthetic upstream")
        changed.update(retention_state="known", retention_description="供应商说明：留存期限未知")
        with self.assertRaises(core.PersistenceError) as missing_reconfirmation:
            ai.create_model_config(self.owner, self.household.pk, data=changed)
        self.assertEqual(missing_reconfirmation.exception.code, "model_consent_required")
        self.assertEqual(ModelConfig.objects.count(), 1)

        changed["confirm_external_processing"] = True
        expanded = ai.create_model_config(self.owner, self.household.pk, data=changed)
        self.assertEqual(expanded.revision_no, 2)
        self.assertEqual(expanded.known_upstream_providers, "Synthetic upstream")
        self.assertEqual(expanded.retention_description, "供应商说明：留存期限未知")
        self.assertEqual(expanded.outbound_confirmation_by_id, self.owner.pk)
        self.assertIsNotNone(expanded.outbound_confirmation_at)

    def test_pre_migration_configuration_and_task_cannot_reach_provider(self):
        base_run = self.queue_question(self.published)
        legacy = ModelConfig.objects.create(household=self.household, revision_no=2,
            created_by=self.owner, provider_label="旧合成服务", base_url="http://127.0.0.1:1/v1",
            model="legacy-model", cloud_enabled=True, outbound_scope=ModelConfig.OutboundScope.REVIEWED_TEXT,
            timeout_seconds=2, max_output_tokens=100, max_input_chars=2000, max_calls=4,
            batch_budget="10", input_price_per_million="1", output_price_per_million="1",
            reserved_per_call="0", non_billable_gateway=False)
        self.assertIsNone(legacy.connection_route)
        self.assertIsNone(legacy.outbound_confirmation_at)
        selection = ai.selection_context(self.owner, self.household.pk, "question")
        with self.assertRaises(core.PersistenceError) as queue_error:
            ai.queue_run(self.owner, self.household.pk, task_kind="question",
                source_revision_ids=[self.published["revision_id"]],
                question_revision_ids=[self.published["revision_id"]],
                selection_token=selection["token"], request_key=key())
        self.assertEqual(queue_error.exception.code, "model_consent_required")

        old_snapshot = ai.config_snapshot(legacy)
        for name in ("config_id", "connection_route", "upstream_state", "known_upstream_providers",
                "retention_state", "retention_description", "outbound_confirmation_by",
                "outbound_confirmation_at"):
            old_snapshot.pop(name)
        run = ModelRun.objects.create(household=self.household, actor=self.owner, config=legacy,
            config_snapshot=old_snapshot, task_kind=ModelRun.TaskKind.QUESTION,
            question_revision_ids=base_run.question_revision_ids,
            source_revision_ids=base_run.source_revision_ids,
            expected_heads=base_run.expected_heads, expected_dependencies=base_run.expected_dependencies,
            review_pointers=base_run.review_pointers, request_key=key(), fingerprint="a" * 64)
        ai.request_execution(self.owner, run.pk)
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False), \
                patch("app.ai.services.chat_completion") as provider_call:
            failed = ai.execute_run(run.pk)
        self.assertEqual(failed.status, ModelRun.Status.FAILED)
        self.assertEqual(failed.error_code, "model_consent_required")
        self.assertFalse(provider_call.called)
        self.assertFalse(ModelBudgetReservation.objects.filter(run=run).exists())

    def test_closed_configuration_is_rechecked_immediately_before_provider_call(self):
        run = self.queue_question(self.published)
        ai.request_execution(self.owner, run.pk)
        original_claim = ai._claim

        def claim_then_close(run_id):
            claim = original_claim(run_id)
            self.assertIsNotNone(claim)
            disabled = self.config_data(cloud_enabled=False, confirm=False,
                scope=ModelConfig.OutboundScope.REVIEWED_TEXT)
            ai.create_model_config(self.owner, self.household.pk, data=disabled)
            return claim

        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False), \
                patch("app.ai.services._claim", side_effect=claim_then_close), \
                patch("app.ai.services.chat_completion") as provider_call:
            failed = ai.execute_run(run.pk)
        self.assertEqual(failed.status, ModelRun.Status.FAILED)
        self.assertEqual(failed.error_code, "model_disabled")
        self.assertFalse(provider_call.called)
        reservation = ModelBudgetReservation.objects.get(run=run)
        self.assertEqual(reservation.state, ModelBudgetReservation.State.RELEASED)

    def test_cancel_between_claim_and_first_send_gate_releases_its_budget(self):
        self.config = self.make_config(budget="0.04")
        run = self.queue_question(self.published)
        ai.request_execution(self.owner, run.pk)
        original_claim = ai._claim
        state_at_cancel = []

        def claim_then_cancel(run_id):
            claim = original_claim(run_id)
            self.assertIsNotNone(claim)
            self.assertEqual(ModelBudgetReservation.objects.get(run_id=run_id).state,
                ModelBudgetReservation.State.HELD)
            ai.cancel_run(self.owner, run_id)
            state_at_cancel.append(ModelBudgetReservation.objects.get(run_id=run_id).state)
            return claim

        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False), \
                patch("app.ai.services._claim", side_effect=claim_then_cancel), \
                patch("app.ai.services.chat_completion") as provider_call:
            cancelled = ai.execute_run(run.pk)
        self.assertFalse(provider_call.called)
        self.assertEqual(state_at_cancel, [ModelBudgetReservation.State.RELEASED])
        self.assertEqual(cancelled.status, ModelRun.Status.CANCELLED)
        reservation = ModelBudgetReservation.objects.get(run=run)
        self.assertEqual(reservation.state, ModelBudgetReservation.State.RELEASED)
        self.assertEqual(reservation.actual_calls, 0)

        second_run = self.queue_question(self.published)
        ai.request_execution(self.owner, second_run.pk)
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False):
            self.assertIsNotNone(ai._claim(second_run.pk))

    def test_actor_membership_is_rechecked_at_external_send_gate(self):
        run = self.queue_question(self.published)
        ai.request_execution(self.owner, run.pk)
        original_claim = ai._claim

        def claim_then_remove_actor(run_id):
            claim = original_claim(run_id)
            self.assertIsNotNone(claim)
            HouseholdMember.objects.filter(household=self.household, user=self.owner).delete()
            return claim

        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False), \
                patch("app.ai.services._claim", side_effect=claim_then_remove_actor), \
                patch("app.ai.services.chat_completion") as provider_call:
            rejected = ai.execute_run(run.pk)
        self.assertEqual(rejected.status, ModelRun.Status.FAILED)
        self.assertEqual(rejected.error_code, "actor_not_authorized")
        self.assertFalse(provider_call.called)
        self.assertEqual(ModelBudgetReservation.objects.get(run=run).state,
            ModelBudgetReservation.State.RELEASED)

    def run_with_response(self, run, response):
        ai.request_execution(self.owner, run.pk)
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False), \
                patch("app.ai.services.chat_completion", return_value=(response,
                    {"prompt_tokens": 30, "completion_tokens": 20})):
            return ai.execute_run(run.pk)

    def test_queue_permission_and_replay_before_changed_choices(self):
        context = ai.selection_context(self.owner, self.household.pk, "question")
        data = {"task_kind": "question", "selection_token": context["token"],
            "request_key": key(), "source_revision_ids": [self.published["revision_id"]],
            "question_revision_ids": [self.published["revision_id"]], "attempt_revision_id": "",
            "selected_region_revision_ids": [], "include_attempt_text": ""}
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(reverse("ai:run_new", kwargs={"household_id": self.household.pk,
            "task_kind": "question"})).status_code, 302)
        client.force_login(self.owner)
        page = client.get(reverse("ai:run_new", kwargs={"household_id": self.household.pk,
            "task_kind": "question"}))
        self.assertEqual(page.status_code, 200)
        self.assertIn("no-store", page["Cache-Control"])
        data["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        first = client.post(reverse("ai:run_create", kwargs={"household_id": self.household.pk,
            "task_kind": "question"}), data)
        self.assertEqual(first.status_code, 302)
        run = ModelRun.objects.get()

        entity = EntityRecord.objects.get(kind="question", stable_id=self.published["question_id"])
        detail = materials.question_detail(self.owner, self.published["question_id"])
        materials.save_question(self.owner, self.material.pk, printed_text="人工新题干",
            original_number="AI-1", sources=detail["sources"], question_id=self.published["question_id"],
            expected_context=detail["edit_context"], reason="测试排队后的版本变化", request_key=key())
        entity.refresh_from_db()
        self.assertNotEqual(entity.head_revision_id, self.published["revision_id"])
        replay = client.post(reverse("ai:run_create", kwargs={"household_id": self.household.pk,
            "task_kind": "question"}), data)
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(replay["Location"], first["Location"])
        self.assertEqual(ModelRun.objects.count(), 1)

        viewer_context = ai.selection_context(self.viewer, self.household.pk, "question")
        with self.assertRaises(core.PersistenceError):
            ai.queue_run(self.viewer, self.household.pk, task_kind="question",
                source_revision_ids=[entity.head_revision_id], question_revision_ids=[entity.head_revision_id],
                selection_token=viewer_context["token"], request_key=key())

    def test_ocr_only_sends_selected_crop_and_applies_unpublished_question_draft(self):
        blank = self.make_blank_question()
        region_id = self.region_for(blank["revision_id"])
        run = self.queue_question(blank, image=True)
        content = self.proposal_response(run, printed_text="识别出的合成题干")

        # The generated image is a geometry-exact, re-encoded crop with no source metadata.
        messages = ai._messages(self.owner, run)
        user_content = messages[1]["content"]
        image_item = next(item for item in user_content if item["type"] == "image_url")
        import base64
        from PIL import Image
        from io import BytesIO
        crop_bytes = base64.b64decode(image_item["image_url"]["url"].split(",", 1)[1])
        with Image.open(BytesIO(crop_bytes)) as crop:
            self.assertEqual(crop.size, (25, 30))
            self.assertFalse(crop.getexif())
            self.assertNotIn("synthetic-note", crop.info)
        original = EvidenceRecord.objects.get(source_id=blank["revision_id"]).image
        self.assertEqual(materials.asset_path(original.payload["storage_key"], original.sha256).read_bytes(),
            self.original_bytes)
        self.assertIn(region_id, [str(value) for value in run.selected_region_revision_ids])

        done = self.run_with_response(run, content)
        self.assertEqual(done.status, ModelRun.Status.AWAITING_REVIEW)
        applied = ai.apply_run(self.owner, run.pk, request_key=key())
        self.assertEqual(len(applied["revision_ids"]), 1)
        head = EntityRecord.objects.get(kind="question", stable_id=blank["question_id"])
        self.assertIsNone(head.published_revision_id)
        self.assertEqual(head.head_revision.payload["printed_text"], "识别出的合成题干")
        self.assertEqual(head.head_revision.payload["header"]["origin"], Origin.AI.value)
        self.assertEqual(ReviewProjection.objects.get(revision_id=head.head_revision_id).state, "draft")
        self.assertTrue(EvidenceRecord.objects.filter(source_id=head.head_revision_id).exists())

    def test_outbound_character_limit_includes_task_prompt(self):
        run = self.queue_question(self.published)
        messages = ai._messages(self.owner, run)
        task_text = next(item["text"] for item in messages[1]["content"] if item["type"] == "text")
        run.config.max_input_chars = len(task_text) + len(messages[0]["content"]) - 1
        with self.assertRaises(core.PersistenceError) as caught:
            ai._messages(self.owner, run)
        self.assertEqual(caught.exception.code, "input_too_large")

    def test_printed_difference_is_separate_erratum_and_manual_apply_is_gated(self):
        run = self.queue_question(self.published)
        response = self.proposal_response(run, printed_text="模型建议的订正文句")
        self.run_with_response(run, response)
        result = ai.apply_run(self.owner, run.pk, request_key=key())
        run.refresh_from_db()
        erratum_revision_id = run.output_revision_ids[0]
        erratum = RevisionRecord.objects.get(pk=erratum_revision_id, entity__kind="erratum")
        question = EntityRecord.objects.get(kind="question", stable_id=self.published["question_id"])
        self.assertEqual(question.head_revision_id, self.published["revision_id"])
        self.assertEqual(question.published_revision_id, self.published["revision_id"])
        self.assertEqual(question.head_revision.payload["printed_text"], "原始题干：3 + 4 = ?")
        self.assertEqual(erratum.payload["target_revision_id"], self.published["revision_id"])
        self.assertEqual(erratum.payload["corrected_text"], "模型建议的订正文句")
        self.assertEqual(ReviewProjection.objects.get(revision=erratum).state, "draft")

        client = Client()
        client.force_login(self.owner)
        detail = client.get(reverse("ai:run_detail", kwargs={"run_id": run.pk}))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "模型建议的订正文句")
        self.assertContains(detail, "查看印刷文字订正与复核")
        self.assertIn("no-store", detail["Cache-Control"])

        context = core.review_context(self.owner, self.household.pk, erratum_revision_id)
        core.review_revision(self.owner, self.household.pk, erratum_revision_id, action="accept",
            expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
            expected_decision_id=context["expected_decision_id"], request_key=key(), reason="人工确认订正建议")
        new_q = printing.apply_erratum(self.owner, self.household.pk, erratum_revision_id,
            expected=edit_context(question.head_revision), request_key=key())
        self.assertNotEqual(new_q["revision_id"], self.published["revision_id"])
        draft = RevisionRecord.objects.get(pk=new_q["revision_id"])
        self.assertEqual(draft.payload["printed_text"], "原始题干：3 + 4 = ?")
        self.assertEqual(draft.payload["working_text"], "模型建议的订正文句")
        self.assertEqual(draft.payload["header"]["origin"], Origin.HUMAN.value)
        self.assertEqual(draft.payload["erratum_revision_ids"], [erratum_revision_id])
        context = core.review_context(self.owner, self.household.pk, draft.pk)
        core.review_revision(self.owner, self.household.pk, draft.pk, action="accept",
            expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
            expected_decision_id=context["expected_decision_id"], request_key=key(), reason="人工复核并接受订正题干")
        question.refresh_from_db()
        self.assertEqual(question.published_revision_id, draft.pk)
        self.assertEqual(result["revision_ids"], [erratum_revision_id])

    def test_preflight_asset_failure_closes_queued_task_without_reservation(self):
        blank = self.make_blank_question()
        run = self.queue_question(blank, image=True)
        evidence = EvidenceRecord.objects.get(source_id=blank["revision_id"])
        path = materials.asset_path(evidence.image.payload["storage_key"], evidence.image.sha256)
        path.unlink()
        ai.request_execution(self.owner, run.pk)
        failed = ai.execute_next()
        self.assertEqual(failed.pk, run.pk)
        self.assertEqual(failed.status, ModelRun.Status.STALE)
        self.assertEqual(failed.error_code, "stale_image")
        self.assertFalse(ModelBudgetReservation.objects.filter(run=run).exists())
        self.assertIsNone(ai.execute_next())

    def test_interrupted_worker_retains_unknown_reservation_without_retry(self):
        run = self.queue_question(self.published)
        ai.request_execution(self.owner, run.pk)
        # Claim reserves before network I/O; a fabricated key satisfies the
        # worker preflight without invoking any provider in this test.
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False):
            self.assertIsNotNone(ai._claim(run.pk))
        ModelRun.objects.filter(pk=run.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(ai.recover_interrupted(), 1)
        run.refresh_from_db()
        reservation = ModelBudgetReservation.objects.get(run=run)
        self.assertEqual(run.status, ModelRun.Status.FAILED)
        self.assertEqual(run.error_code, "failure_unknown")
        self.assertEqual(reservation.state, ModelBudgetReservation.State.UNKNOWN)
        self.assertGreater(reservation.reserved_cost, 0)
        self.assertIsNone(ai.execute_next())

    def test_cancelled_inflight_worker_keeps_late_result_without_reopening(self):
        run = self.queue_question(self.published)
        response = self.proposal_response(run, printed_text="晚到的模型建议")
        ai.request_execution(self.owner, run.pk)

        def late_result(_config, _messages, **_kwargs):
            ai.cancel_run(self.owner, run.pk)
            self.assertEqual(ModelBudgetReservation.objects.get(run=run).state,
                ModelBudgetReservation.State.UNKNOWN)
            return response, {"prompt_tokens": 30, "completion_tokens": 20}

        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False), \
                patch("app.ai.services.chat_completion", side_effect=late_result):
            done = ai.execute_run(run.pk)
        reservation = ModelBudgetReservation.objects.get(run=run)
        self.assertEqual(done.status, ModelRun.Status.CANCELLED)
        self.assertEqual(done.error_code, "cancelled_late_result")
        self.assertEqual(done.response["proposal"]["printed_text"], "晚到的模型建议")
        self.assertEqual(reservation.state, ModelBudgetReservation.State.SETTLED)
        self.assertEqual(reservation.actual_calls, 1)
        self.assertEqual(reservation.actual_cost, Decimal("0.000050"))
        with self.assertRaises(core.PersistenceError):
            ai.apply_run(self.owner, run.pk, request_key=key())

    def test_cancel_of_legacy_running_held_reservation_keeps_unknown(self):
        base_run = self.queue_question(self.published)
        legacy = ModelConfig.objects.create(household=self.household, revision_no=2,
            created_by=self.owner, provider_label="旧合成服务", base_url="http://127.0.0.1:1/v1",
            model="legacy-model", cloud_enabled=True, outbound_scope=ModelConfig.OutboundScope.REVIEWED_TEXT,
            timeout_seconds=2, max_output_tokens=100, max_input_chars=2000, max_calls=4,
            batch_budget="10", input_price_per_million="1", output_price_per_million="1",
            reserved_per_call="0", non_billable_gateway=False)
        old_snapshot = ai.config_snapshot(legacy)
        for name in ("config_id", "connection_route", "upstream_state", "known_upstream_providers",
                "retention_state", "retention_description", "outbound_confirmation_by",
                "outbound_confirmation_at"):
            old_snapshot.pop(name)
        run = ModelRun.objects.create(household=self.household, actor=self.owner, config=legacy,
            config_snapshot=old_snapshot, task_kind=ModelRun.TaskKind.QUESTION,
            question_revision_ids=base_run.question_revision_ids,
            source_revision_ids=base_run.source_revision_ids,
            expected_heads=base_run.expected_heads, expected_dependencies=base_run.expected_dependencies,
            review_pointers=base_run.review_pointers, request_key=key(), fingerprint="b" * 64)
        started_at = timezone.now()
        reserved_cost = Decimal("0.1")
        ModelRun.objects.filter(pk=run.pk).update(status=ModelRun.Status.RUNNING,
            started_at=started_at, call_started_at=started_at,
            lease_expires_at=started_at + timedelta(seconds=30), reserved_cost=reserved_cost)
        reservation = ModelBudgetReservation.objects.create(run=run, config=legacy,
            reserved_calls=1, reserved_cost=reserved_cost)

        cancelled = ai.cancel_run(self.owner, run.pk)
        reservation.refresh_from_db()
        self.assertEqual(cancelled.status, ModelRun.Status.CANCELLED)
        self.assertEqual(reservation.state, ModelBudgetReservation.State.UNKNOWN)
        self.assertEqual(reservation.actual_calls, 0)

    def test_unknown_tool_fails_closed_after_settling_known_usage(self):
        run = self.queue_question(self.published)
        allowed_ids = list(dict.fromkeys(run.source_revision_ids + run.question_revision_ids))
        content = json.dumps({"schema_version": "study-workbench.ai.v1", "task": "question",
            "source_revision_ids": allowed_ids, "proposal": {"printed_text": "合成建议",
                "missing_fields": [], "classification_suggestion": None, "analysis_suggestion": None},
            "tool_calls": [{"name": "read_local_file", "arguments": {"path": "/etc/passwd"}}]},
            ensure_ascii=False)
        done = self.run_with_response(run, content)
        self.assertEqual(done.status, ModelRun.Status.FAILED)
        self.assertEqual(done.error_code, "unknown_tool")
        self.assertIsNotNone(done.estimated_cost)
        reservation = ModelBudgetReservation.objects.get(run=run)
        self.assertEqual(reservation.state, ModelBudgetReservation.State.SETTLED)
        self.assertEqual(reservation.actual_calls, 1)

    def test_config_lock_keeps_parallel_image_reservations_within_budget(self):
        config = self.make_config(budget="0.15", reserved="0.1")
        self.config = config
        first = self.queue_question(self.published, image=True)
        second = self.queue_question(self.published, image=True)
        ai.request_execution(self.owner, first.pk)
        ai.request_execution(self.owner, second.pk)
        entered = threading.Event()
        release = threading.Event()
        response = self.proposal_response(first, printed_text="并发预算合成建议")

        def hold_first(_config, _messages, **_kwargs):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("synthetic worker was not released")
            return response, {"prompt_tokens": 30, "completion_tokens": 20}

        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False), \
                patch("app.ai.services.chat_completion", side_effect=hold_first):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(ai.execute_run, first.pk)
                try:
                    self.assertTrue(entered.wait(5))
                    second_result = ai.execute_run(second.pk)
                finally:
                    release.set()
                first_result = future.result(timeout=10)
        self.assertEqual(first_result.status, ModelRun.Status.AWAITING_REVIEW)
        self.assertEqual(second_result.status, ModelRun.Status.FAILED)
        self.assertEqual(second_result.error_code, "budget_exhausted")
        self.assertEqual(ModelBudgetReservation.objects.filter(config=config).count(), 1)

    def test_image_usage_above_fixed_reserve_is_settled_and_blocks_next_run(self):
        config = self.make_config(budget="0.15", reserved="0.1")
        self.config = config
        first = self.queue_question(self.published, image=True)
        response = self.proposal_response(first, printed_text="合成图像建议")
        ai.request_execution(self.owner, first.pk)
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False), \
                patch("app.ai.services.chat_completion", return_value=(response,
                    {"prompt_tokens": 200000, "completion_tokens": 20})):
            completed = ai.execute_run(first.pk)
        self.assertEqual(completed.status, ModelRun.Status.AWAITING_REVIEW)
        reservation = ModelBudgetReservation.objects.get(run=first)
        self.assertEqual(reservation.reserved_cost, Decimal("0.1"))
        self.assertEqual(reservation.actual_cost, Decimal("0.20002"))
        self.assertEqual(completed.estimated_cost, Decimal("0.20002"))

        second = self.queue_question(self.published, image=True)
        ai.request_execution(self.owner, second.pk)
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False), \
                patch("app.ai.services.chat_completion") as provider:
            rejected = ai.execute_run(second.pk)
        self.assertEqual(rejected.status, ModelRun.Status.FAILED)
        self.assertEqual(rejected.error_code, "budget_exhausted")
        provider.assert_not_called()
        self.assertFalse(ModelBudgetReservation.objects.filter(run=second).exists())

    def test_total_crop_pixel_limit_fails_before_open_or_reservation(self):
        run = self.queue_question(self.published, image=True)
        ai.request_execution(self.owner, run.pk)
        evidence = SimpleNamespace(
            region=SimpleNamespace(payload={"coordinate_space": "original_pixels",
                "geometry": [0, 0, 3000, 3000]}),
            image=SimpleNamespace(payload={"storage_key": "synthetic", "width": 4000, "height": 4000},
                sha256="synthetic"),
        )

        class FakeQuery:
            def select_related(self, *_args):
                return self

            def first(self):
                return evidence

        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False), \
                patch("app.ai.services.EvidenceRecord.objects.filter", return_value=FakeQuery()), \
                patch("app.ai.services.materials.asset_path") as asset_path, \
                patch("app.ai.services.Image.open") as image_open, \
                patch("app.ai.services.chat_completion") as provider:
            failed = ai.execute_run(run.pk)
        self.assertEqual(failed.status, ModelRun.Status.FAILED)
        self.assertEqual(failed.error_code, "input_too_large")
        asset_path.assert_not_called()
        image_open.assert_not_called()
        provider.assert_not_called()
        self.assertFalse(ModelBudgetReservation.objects.filter(run=run).exists())

    def test_total_crop_pixel_limit_counts_several_individually_allowed_regions(self):
        run = SimpleNamespace(task_kind=ModelRun.TaskKind.QUESTION,
            selected_region_revision_ids=["region-a", "region-b"], source_revision_ids=["source"],
            question_revision_ids=["question"], attempt_revision_id=None, household_id="household")
        evidence = {
            region_id: SimpleNamespace(
                region=SimpleNamespace(payload={"coordinate_space": "original_pixels",
                    "geometry": [0, 0, 2500, 2000]}),
                image=SimpleNamespace(payload={"storage_key": "synthetic", "width": 4000, "height": 3000},
                    sha256="synthetic"),
            ) for region_id in run.selected_region_revision_ids
        }

        class FakeQuery:
            def __init__(self, row):
                self.row = row

            def select_related(self, *_args):
                return self

            def first(self):
                return self.row

        class FakeCrop:
            width, height = 2500, 2000

            def convert(self, _mode):
                return self

            def save(self, output, **_kwargs):
                output.write(b"png")

        class FakeImage:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def crop(self, _box):
                return FakeCrop()

        def evidence_query(**kwargs):
            return FakeQuery(evidence[kwargs["region_id"]])

        with patch("app.ai.services.EvidenceRecord.objects.filter", side_effect=evidence_query), \
                patch("app.ai.services.materials.asset_path", return_value="synthetic") as asset_path, \
                patch("app.ai.services.Image.open", return_value=FakeImage()) as image_open:
            with self.assertRaises(core.PersistenceError) as caught:
                ai._crop_regions(self.owner, "household", run)
        self.assertEqual(caught.exception.code, "input_too_large")
        self.assertEqual(asset_path.call_count, 1)
        self.assertEqual(image_open.call_count, 1)

    def test_total_crop_png_limit_fails_without_reservation_or_provider_call(self):
        run = self.queue_question(self.published, image=True)
        ai.request_execution(self.owner, run.pk)

        class FakeCrop:
            width, height = 25, 30

            def convert(self, _mode):
                return self

            def save(self, output, **_kwargs):
                output.write(b"x" * (ai.MAX_TOTAL_CROP_PNG_BYTES + 1))

        class FakeImage:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def load(self):
                return None

            def convert(self, _mode):
                return self

            def crop(self, _box):
                return FakeCrop()

        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False), \
                patch("app.ai.services.Image.open", return_value=FakeImage()), \
                patch("app.ai.services.chat_completion") as provider:
            failed = ai.execute_run(run.pk)
        self.assertEqual(failed.status, ModelRun.Status.FAILED)
        self.assertEqual(failed.error_code, "input_too_large")
        provider.assert_not_called()
        self.assertFalse(ModelBudgetReservation.objects.filter(run=run).exists())

    def test_oversized_provider_payload_fails_before_reservation_or_call(self):
        run = self.queue_question(self.published)
        ai.request_execution(self.owner, run.pk)
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False), \
                patch("app.ai.services.prepare_request_payload",
                    side_effect=ProviderFailure("request_payload_too_large")), \
                patch("app.ai.services.chat_completion") as provider:
            failed = ai.execute_run(run.pk)
        self.assertEqual(failed.status, ModelRun.Status.FAILED)
        self.assertEqual(failed.error_code, "input_too_large")
        provider.assert_not_called()
        self.assertFalse(ModelBudgetReservation.objects.filter(run=run).exists())

    def test_answer_text_controls_are_assessment_only(self):
        client = Client()
        client.force_login(self.owner)
        question_url = reverse("ai:run_new", kwargs={"household_id": self.household.pk,
            "task_kind": "question"})
        question_page = client.get(question_url)
        self.assertEqual(question_page.status_code, 200)
        self.assertNotContains(question_page, 'name="attempt_revision_id"')
        self.assertNotContains(question_page, 'name="include_attempt_text"')
        assessment_url = reverse("ai:run_new", kwargs={"household_id": self.household.pk,
            "task_kind": "assessment"})
        assessment_page = client.get(assessment_url)
        self.assertContains(assessment_page, 'name="attempt_revision_id"')
        self.assertContains(assessment_page, 'name="include_attempt_text"')

        context = ai.selection_context(self.owner, self.household.pk, "question")
        with self.assertRaises(core.PersistenceError) as caught:
            ai.queue_run(self.owner, self.household.pk, task_kind="question",
                source_revision_ids=[self.published["revision_id"]],
                question_revision_ids=[self.published["revision_id"]],
                include_attempt_text=True, selection_token=context["token"], request_key=key())
        self.assertEqual(caught.exception.code, "invalid_input")
        self.assertEqual(ModelRun.objects.count(), 0)

    def test_variant_question_revision_cannot_pass_as_target_method(self):
        method = knowledge_services.save_node(self.owner, self.household.pk, "method", data={
            "name": "合成方法", "conditions": "", "steps": "检查算式",
            "notes": "", "parent_revision_id": "", "sources": "[]"},
            request_key=key(), reason="创建变式校验方法")
        method_context = core.review_context(self.owner, self.household.pk, method["revision_id"])
        core.review_revision(self.owner, self.household.pk, method["revision_id"], action="accept",
            expected_head=method_context["expected_head"],
            expected_dependencies=method_context["expected_dependencies"],
            expected_decision_id=method_context["expected_decision_id"],
            request_key=key(), reason="接受变式校验方法")
        selection = ai.selection_context(self.owner, self.household.pk, "variant")
        run = ai.queue_run(self.owner, self.household.pk, task_kind="variant",
            source_revision_ids=[method["revision_id"]],
            question_revision_ids=[self.published["revision_id"]],
            selection_token=selection["token"], request_key=key())
        proposal = {"schema_version": "study-workbench.ai.v1", "task": "variant",
            "source_revision_ids": [method["revision_id"], self.published["revision_id"]],
            "proposal": {"text": "合成变式", "answer_expression": "3 + 4",
                "check_expression": "7", "target_method_revision_id": self.published["revision_id"]},
            "tool_calls": []}
        ai.request_execution(self.owner, run.pk)
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only"}, clear=False), \
                patch("app.ai.services.chat_completion", return_value=(json.dumps(proposal),
                    {"prompt_tokens": 10, "completion_tokens": 10})):
            failed = ai.execute_run(run.pk)
        self.assertEqual(failed.status, ModelRun.Status.FAILED)
        self.assertEqual(failed.error_code, "response_unknown_source")
        self.assertIsNone(failed.response)

    def test_database_guards_preserve_configuration_and_selected_run_identity(self):
        run = self.queue_question(self.published)
        with self.assertRaises(DatabaseError), transaction.atomic():
            ModelConfig.objects.filter(pk=self.config.pk).update(model="tampered")
        with self.assertRaises(DatabaseError), transaction.atomic():
            ModelRun.objects.filter(pk=run.pk).update(source_revision_ids=["other-question"])

    def test_database_run_guard_rejects_unpublished_nonblank_question_even_with_region(self):
        draft = materials.save_question(self.owner, self.material.pk, printed_text="未发布工作草稿",
            original_number="AI-guard", sources=[self.source], request_key=key(), reason="构造数据库边界用草稿")
        region_id = self.region_for(draft["revision_id"])
        with self.assertRaises(DatabaseError), transaction.atomic():
            ModelRun.objects.create(household=self.household, actor=self.owner, config=self.config,
                config_snapshot=ai.config_snapshot(self.config), task_kind=ModelRun.TaskKind.QUESTION,
                question_revision_ids=[draft["revision_id"]], source_revision_ids=[draft["revision_id"]],
                selected_region_revision_ids=[region_id], request_key=key(), fingerprint="f" * 64)

    def test_reviewer_cannot_manage_another_members_run(self):
        run = self.queue_question(self.published)
        with self.assertRaises(core.PersistenceError):
            ai.request_execution(self.reviewer, run.pk)
        details = ai.run_detail(self.reviewer, run.pk)
        self.assertTrue(details["writable"])
        self.assertFalse(details["can_execute"])
        self.assertFalse(details["can_cancel"])

    def test_household_owner_cannot_apply_reviewer_created_variant_run(self):
        method = knowledge_services.save_node(self.owner, self.household.pk, "method", data={
            "name": "合成计算方法", "conditions": "", "steps": "先核对等式",
            "notes": "", "parent_revision_id": "", "sources": "[]"},
            request_key=key(), reason="合成变式授权测试方法")
        method_context = core.review_context(self.owner, self.household.pk, method["revision_id"])
        core.review_revision(self.owner, self.household.pk, method["revision_id"], action="accept",
            expected_head=method_context["expected_head"],
            expected_dependencies=method_context["expected_dependencies"],
            expected_decision_id=method_context["expected_decision_id"],
            request_key=key(), reason="确认合成方法")
        selection = ai.selection_context(self.reviewer, self.household.pk, "variant")
        run = ai.queue_run(self.reviewer, self.household.pk, task_kind="variant",
            source_revision_ids=[method["revision_id"]],
            question_revision_ids=[self.published["revision_id"]],
            selection_token=selection["token"], request_key=key())
        proposal = {"schema_version": "study-workbench.ai.v1", "task": "variant",
            "source_revision_ids": [method["revision_id"], self.published["revision_id"]],
            "proposal": {"text": "合成变式？", "answer_expression": "3 + 4",
                "check_expression": "7", "target_method_revision_id": method["revision_id"]},
            "tool_calls": []}
        ai.request_execution(self.reviewer, run.pk)
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "fabricated-test-secret"}, clear=False), \
                patch("app.ai.services.chat_completion", return_value=(json.dumps(proposal),
                    {"prompt_tokens": 10, "completion_tokens": 10})):
            completed = ai.execute_run(run.pk)
        self.assertEqual(completed.status, ModelRun.Status.AWAITING_REVIEW)

        owner_detail = ai.run_detail(self.owner, run.pk)
        reviewer_detail = ai.run_detail(self.reviewer, run.pk)
        self.assertFalse(owner_detail["can_apply"])
        self.assertTrue(reviewer_detail["can_apply"])
        with self.assertRaises(core.PersistenceError) as caught:
            ai.apply_run(self.owner, run.pk, request_key=key())
        self.assertEqual(caught.exception.code, "permission_denied")
        with self.assertRaises(core.PersistenceError) as caught:
            ai.validated_variant_run(self.owner, str(run.pk), household_id=str(self.household.pk),
                parent_question_revision_id=self.published["revision_id"],
                target_method_revision_id=method["revision_id"], text="合成变式？",
                answer_expression="3 + 4", check_expression="7",
                source_revision_ids=[method["revision_id"]], request_key=key())
        self.assertEqual(caught.exception.code, "permission_denied")
