"""Synthetic provider only: source binding, no automatic publication, batch limits."""
from datetime import timedelta
import json
import os
from unittest.mock import patch
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone
from app.ai import services as ai
from app.ai.models import ModelRun, ModelBudgetReservation
from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.workflows import preparation, services as workflows
from tests.study import test_services as fixtures

key = fixtures.key


class PreparationTests(TransactionTestCase):
    create_observation = fixtures.StudyServiceTests.create_observation

    def setUp(self):
        fixtures.StudyServiceTests.setUp(self)
        self.extra_settings = override_settings(SWB_TEST_OWNER=self.owner.username,
            SWB_AI_ALLOW_TEST_HTTP=True, SWB_PRODUCTION=False)
        self.extra_settings.enable()
        self.addCleanup(self.extra_settings.disable)
        self.job = workflows.create(self.owner, self.material.pk, request_key=key())
        self.config = ai.create_model_config(self.owner, self.household.pk, data={
            "provider_label": "合成供应商", "base_url": "http://127.0.0.1:1/v1", "model": "synthetic",
            "connection_route": "gateway", "upstream_state": "unknown", "known_upstream_providers": "",
            "retention_state": "unknown", "retention_description": "", "confirm_external_processing": True,
            "cloud_enabled": True, "outbound_scope": "selected_regions", "timeout_seconds": 2,
            "max_output_tokens": 1000, "max_input_chars": 16000, "max_calls": 4,
            "batch_budget": "10", "input_price_per_million": "1", "output_price_per_million": "1",
            "reserved_per_call": "0.1", "non_billable_gateway": False})

    def queue(self, question_id=None):
        self.job.refresh_from_db()
        value = {"expected": workflows.context(self.job), "request_key": key(), "reason": "准备合成题干",
            "sources": [{"page_id": self.page_id, "bbox": [8, 8, 100, 70]}]}
        if question_id:
            value["question_id"] = question_id
        self.job, stage = preparation.queue(self.owner, self.job.pk, value)
        return stage, value

    def execute_fixture(self, stage, proposal=None, side_effect=None):
        run = ModelRun.objects.get(pk=stage)
        proposal = proposal or {"printed_text": "3 × 3 = ?", "missing_fields": [],
            "nodes": [{"kind": "knowledge", "data": {"definition": "乘法"}}],
            "answer": {"body": "9", "formulas": [], "basis": "3 + 3 + 3"}}
        response = json.dumps({"schema_version": "study-workbench.ai.v1", "task": "material",
            "source_revision_ids": list(dict.fromkeys(run.source_revision_ids + run.question_revision_ids + run.selected_region_revision_ids)),
            "proposal": proposal, "tool_calls": []})
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-secret"}), \
             patch("app.ai.services.chat_completion", side_effect=side_effect,
                   return_value=(response, {"prompt_tokens": 50, "completion_tokens": 100})) as provider:
            result = ai.execute_run(run.pk)
        return result, provider

    def test_one_confirmation_retains_source_and_full_history(self):
        stage, value = self.queue()
        self.assertEqual(preparation.queue(self.owner, self.job.pk, value)[1], stage)
        self.assertEqual(ModelRun.objects.count(), 1)
        result, provider = self.execute_fixture(stage)
        self.assertEqual(result.status, "awaiting_review", result.error_code)
        self.assertEqual(provider.call_count, 1)
        row = preparation.detail(self.owner, self.job.pk)["stages"][0]
        entity = EntityRecord.objects.get(kind="question", stable_id=row["question_id"])
        self.assertIsNone(entity.published_revision_id)
        value = {"expected": row["expected"], "request_key": key(), "reason": "人工逐项核对",
            "checked": True, "printed_text": row["proposal"]["printed_text"], "original_number": "P1",
            "sources": row["sources"], "answer": row["proposal"]["answer"], "nodes": row["proposal"]["nodes"]}
        _job, saved = preparation.confirm(self.owner, self.job.pk, stage, value)
        self.assertEqual(preparation.confirm(self.owner, self.job.pk, stage, value)[1], saved)
        entity.refresh_from_db()
        self.assertEqual(entity.published_revision_id, saved["revision_id"])
        self.assertEqual(entity.revisions.count(), 2)
        self.assertEqual(EntityRecord.objects.filter(kind="attempt").count(), 0)
        self.assertEqual(list(self.job.events.values_list("action", flat=True)),
            ["created", "preparation_queued", "preparation_confirmed"])
        result.refresh_from_db()
        self.assertEqual(result.status, "applied")

    def test_whole_batch_cancel_keeps_late_response_and_never_applies(self):
        stage, _value = self.queue()
        def late(*args, **kwargs):
            self.job.refresh_from_db()
            workflows.action(self.owner, self.job.pk, action="cancel", expected=workflows.context(self.job), request_key=key())
            run = ModelRun.objects.get(pk=stage)
            return json.dumps({"schema_version": "study-workbench.ai.v1", "task": "material",
                "source_revision_ids": list(dict.fromkeys(run.source_revision_ids + run.question_revision_ids + run.selected_region_revision_ids)),
                "proposal": {"printed_text": None, "missing_fields": ["printed_text"], "nodes": [], "answer": None}, "tool_calls": []}), {"prompt_tokens": 20, "completion_tokens": 20}
        result, _provider = self.execute_fixture(stage, side_effect=late)
        self.assertEqual(result.status, "cancelled")
        self.assertTrue(result.response)
        self.assertFalse(preparation.detail(self.owner, self.job.pk)["stages"][0]["can_confirm"])

    def test_redo_counts_all_requests_and_unconfirmed_stage_blocks_output(self):
        stage, _value = self.queue()
        question_id = preparation.detail(self.owner, self.job.pk)["stages"][0]["question_id"]
        with self.assertRaises(core.PersistenceError) as blocked:
            preparation.ensure_output_ready(self.job)
        self.assertEqual(blocked.exception.code, "preparation_incomplete")
        for _ in range(3):
            self.queue(question_id)
        with self.assertRaises(core.PersistenceError) as limited:
            self.queue(question_id)
        self.assertEqual(limited.exception.code, "batch_call_limit")
        self.assertEqual(ModelRun.objects.count(), 4)
        self.assertEqual(preparation.detail(self.owner, self.job.pk)["limits"]["used_requests"], 4)

    def test_expired_send_gate_permissions_and_http(self):
        stage, _value = self.queue()
        instant = timezone.now() + timedelta(seconds=601)
        with patch("app.workflows.preparation.timezone.now", return_value=instant):
            result, provider = self.execute_fixture(stage)
        self.assertEqual(provider.call_count, 0)
        self.assertEqual(result.error_code, "batch_expired")
        self.assertEqual(ModelBudgetReservation.objects.get(run=result).state, "released")
        client = Client()
        client.force_login(self.viewer)
        url = f"/api/v1/workflows/{self.job.pk}/preparation/"
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.post(url, json.dumps({"request_key": key(), "reason": "无权请求"}), content_type="application/json").status_code, 404)
        client.force_login(self.other)
        self.assertEqual(client.get(url).status_code, 404)

    def test_failed_stage_can_be_explicitly_skipped_without_erasing_failure(self):
        stage, _value = self.queue()
        result, _provider = self.execute_fixture(stage, side_effect=lambda *_args, **_kwargs: ("{}", {}))
        self.assertEqual(result.status, "failed")
        row = preparation.detail(self.owner, self.job.pk)["stages"][0]
        preparation.cancel(self.owner, self.job.pk, stage, {"expected": row["expected"],
            "request_key": key(), "reason": "保留失败证据，转人工核对"})
        detail = preparation.detail(self.owner, self.job.pk)
        self.assertEqual(detail["stages"][0]["state"], "cancelled")
        self.assertFalse(detail["stages"][0]["can_confirm"])
        result.refresh_from_db()
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.error_code)
        preparation.ensure_output_ready(detail["job"])
        entity = EntityRecord.objects.get(kind="question", stable_id=row["question_id"])
        self.assertIsNone(entity.published_revision_id)
