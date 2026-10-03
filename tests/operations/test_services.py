import hashlib
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import DatabaseError, transaction
from django.test import TransactionTestCase
from django.urls import reverse

from app.exports.contracts import ExportError, canonical, digest
from app.exports.snapshots import write_private
from app.operations import services as operations
from app.operations.models import ExportArchiveRecord, ExportRetirementRecord, RetentionPolicyRevision, WorkTiming
from app.persistence import services as core
from app.printing import services as printing
from app.printing.models import ExportSnapshot
from tests.study import test_services as study_tests

key = study_tests.key


class OperationsServiceTests(TransactionTestCase):
    setUp = study_tests.StudyServiceTests.setUp
    create_attempt = study_tests.StudyServiceTests.create_attempt
    create_observation = study_tests.StudyServiceTests.create_observation

    def test_default_policy_append_permissions_and_immutable_history(self):
        default = operations.retention_policy_detail(self.owner, self.household.pk)
        self.assertTrue(default["default_policy"])
        self.assertIsNone(default["archive_after_days"])
        self.assertIsNone(default["delete_after_days"])
        request_key = uuid4()
        first = operations.append_retention_policy(self.owner, self.household.pk,
            archive_after_days=30, delete_after_days=90, reason="合成保留策略",
            request_key=request_key)
        self.assertEqual(first.pk, operations.append_retention_policy(self.owner,
            self.household.pk, archive_after_days=30, delete_after_days=90,
            reason="合成保留策略", request_key=request_key).pk)
        self.assertEqual(first.revision_no, 1)
        with self.assertRaises(core.PersistenceError):
            operations.append_retention_policy(self.owner, self.household.pk,
                archive_after_days=30, delete_after_days=30, reason="不同内容",
                request_key=request_key)
        with self.assertRaises(core.PersistenceError):
            operations.append_retention_policy(self.viewer, self.household.pk,
                archive_after_days=None, delete_after_days=None, reason="越权",
                request_key=uuid4())
        with self.assertRaises(DatabaseError), transaction.atomic():
            RetentionPolicyRevision.objects.filter(pk=first.pk).update(reason="覆盖历史")

    def test_retention_page_exposes_each_data_type_lifecycle_and_unknown_provider_deletion(self):
        data = operations.retention_policy_detail(self.owner, self.household.pk)
        kinds = [item["kind"] for item in data["data_lifecycle_policy"]]
        self.assertEqual(kinds, ["原始照片", "派生文件与预览", "领域历史", "AI 响应",
            "运行日志", "备份", "导出", "供应商侧副本"])
        provider = data["data_lifecycle_policy"][-1]
        self.assertIn("未知", provider["default"])
        self.assertIn("没有供应商删除接口", provider["archive_retire"])
        self.client.force_login(self.owner)
        response = self.client.get(reverse("operations:retention_policy",
            kwargs={"household_id": self.household.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertIn("运行日志", response.content.decode())
        self.assertIn("不把本机退役记作供应商删除成功", response.content.decode())

    def test_manual_timing_binds_exact_question_and_current_attempt(self):
        attempt = self.create_attempt()
        context = operations.work_timing_context(self.owner, self.household.pk)
        request_key = uuid4()
        row = operations.record_work_timing(self.owner, self.household.pk,
            question_revision_id=self.question_revision_id,
            attempt_revision_id=attempt["revision_id"], kind=WorkTiming.Kind.MANUAL_ENTRY,
            seconds=135, reason="家长手工估计", context_token=context["context_token"],
            request_key=request_key)
        replay = operations.record_work_timing(self.owner, self.household.pk,
            question_revision_id=self.question_revision_id,
            attempt_revision_id=attempt["revision_id"], kind=WorkTiming.Kind.MANUAL_ENTRY,
            seconds=135, reason="家长手工估计", context_token="ignored on exact replay",
            request_key=request_key)
        self.assertEqual(replay.pk, row.pk)
        self.assertEqual(row.question_revision_id, self.question_revision_id)
        self.assertEqual(row.attempt_revision_id, attempt["revision_id"])
        self.assertEqual(WorkTiming.objects.count(), 1)
        with self.assertRaises(core.PersistenceError):
            operations.record_work_timing(self.owner, self.household.pk,
                question_revision_id=self.question_revision_id,
                attempt_revision_id="not-a-current-attempt", kind=WorkTiming.Kind.MODEL_CORRECTION,
                seconds=30, reason="无效作答", context_token=context["context_token"],
                request_key=uuid4())

    def test_question_edit_invalidates_prior_timing_context(self):
        context = operations.work_timing_context(self.owner, self.household.pk)
        detail = self._question_detail()
        from app.web import services as materials
        materials.save_question(self.owner, self.material.pk, printed_text="更新后的合成题干",
            original_number="K1", sources=[self.source], question_id=self.question_id,
            expected_context=detail["edit_context"], request_key=key(), reason="合成版本更新")
        with self.assertRaises(core.PersistenceError) as captured:
            operations.record_work_timing(self.owner, self.household.pk,
                question_revision_id=self.question_revision_id, kind=WorkTiming.Kind.MANUAL_ENTRY,
                seconds=30, reason="旧凭据", context_token=context["context_token"],
                request_key=uuid4())
        self.assertEqual(captured.exception.code, "stale_context")

    def _question_detail(self):
        from app.web import services as materials
        return materials.question_detail(self.owner, self.question_id)

    def test_retirement_preserves_archive_and_ledger_and_blocks_recreation(self):
        snapshot = printing.export_questions(self.owner, self.household.pk,
            [self.question_revision_id], title="合成退役检查", purpose="independent_practice")
        data_root = Path(settings.SWB_DATA_ROOT)
        original = data_root / snapshot.storage_key
        self.assertTrue(original.is_dir())
        retired = operations.retire_export_snapshot(self.owner, self.household.pk,
            snapshot.pk, reason="合成退役路径验收")
        self.assertFalse(original.exists())
        archive = data_root / retired.archive_storage_key
        self.assertTrue(archive.is_dir())
        self.assertEqual(ExportArchiveRecord.objects.count(), 1)
        self.assertEqual(ExportRetirementRecord.objects.count(), 1)
        self.assertEqual(operations.snapshot_availability(self.owner, snapshot.pk)["status"], "retired")

        self.client.force_login(self.owner)
        response = self.client.get(reverse("printing:download", kwargs={
            "pk": snapshot.pk, "name": "document.pdf"}))
        self.assertEqual(response.status_code, 410)
        with self.assertRaises(ExportError) as captured:
            printing.export_questions(self.owner, self.household.pk,
                [self.question_revision_id], title="合成退役检查", purpose="independent_practice")
        self.assertEqual(captured.exception.code, "snapshot_retired")
        self.assertFalse(original.exists())
        self.assertTrue(archive.is_dir())

        exported = operations.export_retirement_ledger(self.owner, self.household.pk)
        checked = operations.verify_retirement_ledger(self.owner, self.household.pk,
            ledger_id=exported["ledger_id"])
        self.assertTrue(checked["matches"])
        self.assertFalse(checked["missing_from_restored_database"])
        self.assertFalse(checked["not_in_selected_ledger"])
        self._write_bad_ledger(exported["ledger_id"], duplicate=True)
        with self.assertRaises(core.PersistenceError) as malformed:
            operations.verify_retirement_ledger(self.owner, self.household.pk,
                ledger_id=self._bad_ledger_id)
        self.assertEqual(malformed.exception.code, "invalid_ledger")

    def test_default_dry_run_keeps_files_and_due_policy_archives_then_retires(self):
        snapshot = printing.export_questions(self.owner, self.household.pk,
            [self.question_revision_id], title="合成到期维护", purpose="independent_practice")
        original = Path(settings.SWB_DATA_ROOT) / snapshot.storage_key
        now = snapshot.created_at + timedelta(days=95)
        preview = operations.retirement_candidates(self.owner, self.household.pk, now=now)
        self.assertEqual(preview["candidates"], [])
        self.assertTrue(original.is_dir())
        self.assertEqual(ExportArchiveRecord.objects.count(), 0)
        operations.append_retention_policy(self.owner, self.household.pk,
            archive_after_days=30, delete_after_days=90, reason="合成到期策略", request_key=key())
        archive_at = snapshot.created_at + timedelta(days=35)
        self.assertEqual(operations.retirement_candidates(self.owner, self.household.pk,
            now=archive_at)["candidates"][0]["action"], "archive")
        self.assertEqual(ExportArchiveRecord.objects.count(), 0)
        operations.retire_expired_exports(self.owner, self.household.pk,
            reason="合成显式归档", now=archive_at)
        self.assertTrue(original.is_dir())
        self.assertEqual(ExportArchiveRecord.objects.count(), 1)
        self.assertEqual(ExportRetirementRecord.objects.count(), 0)
        operations.retire_expired_exports(self.owner, self.household.pk,
            reason="合成显式退役", now=now)
        operations.retire_expired_exports(self.owner, self.household.pk,
            reason="合成重复维护", now=now)
        self.assertFalse(original.exists())
        self.assertEqual(ExportArchiveRecord.objects.count(), 1)
        self.assertEqual(ExportRetirementRecord.objects.count(), 1)
        with self.assertRaises(DatabaseError), transaction.atomic():
            ExportRetirementRecord.objects.all().update(reason="覆盖")
        with self.assertRaises(core.PersistenceError):
            operations.retirement_candidates(self.other, self.household.pk, now=now)

    def test_latest_ledger_reports_missing_rows_and_rejects_non_object_and_unsafe_paths(self):
        snapshot = printing.export_questions(self.owner, self.household.pk,
            [self.question_revision_id], title="合成独立账本", purpose="independent_practice")
        operations.retire_export_snapshot(self.owner, self.household.pk,
            snapshot.pk, reason="合成账本")
        exported = operations.export_retirement_ledger(self.owner, self.household.pk)
        original = Path(settings.SWB_DATA_ROOT) / exported["storage_key"]
        payload = json.loads(original.read_bytes())
        additional = dict(payload["entries"][0], snapshot_export_id="a" * 64,
            snapshot_id=999, retirement_id=999)
        payload["entries"].append(additional)
        def save(value):
            raw = canonical(value)
            ledger_id = digest(raw)
            write_private(original.parent / f"ledger-{ledger_id}.json", raw)
            return ledger_id
        checked = operations.verify_retirement_ledger(self.owner, self.household.pk,
            ledger_id=save(payload))
        self.assertFalse(checked["matches"])
        self.assertEqual(checked["missing_from_restored_database"], ["a" * 64])
        for malformed in ([1], dict(payload, schema_version="unknown"),
                dict(payload, entries=[dict(additional, storage_key="../../originals")])):
            with self.assertRaises(core.PersistenceError) as captured:
                operations.verify_retirement_ledger(self.owner, self.household.pk,
                    ledger_id=save(malformed))
            self.assertEqual(captured.exception.code, "invalid_ledger")
        with self.assertRaises(core.PersistenceError):
            operations.verify_retirement_ledger(self.owner, self.household.pk, ledger_id="../outside")

    def _write_bad_ledger(self, existing_ledger_id, *, duplicate):
        root = Path(settings.SWB_DATA_ROOT)
        existing = root / "retention-ledgers" / hashlib.sha256(
            str(self.household.pk).encode("utf-8")).hexdigest()[:24] / f"ledger-{existing_ledger_id}.json"
        payload = json.loads(existing.read_bytes())
        if duplicate:
            payload["entries"].append(dict(payload["entries"][0]))
        raw = canonical(payload)
        ledger_id = digest(raw)
        directory = existing.parent
        path = directory / f"ledger-{ledger_id}.json"
        write_private(path, raw)
        self._bad_ledger_id = ledger_id
