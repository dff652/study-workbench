from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import tempfile
import threading
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TransactionTestCase

from app.domain import ContractError
from app.imports.models import LegacyImportBatch, LegacyIndexEntry
from app.imports.package import prepare_legacy_import
from app.imports.services import import_prepared, legacy_trace
from app.persistence.adapter import ObjectKey, split_bundle
from app.persistence.models import EntityRecord, HouseholdMember, ImageRecord, RequestReceipt, RevisionRecord
from app.persistence.services import PersistenceError, create_household, read_snapshot_bundle, stage_bundle
from tests.domain.test_contract_scenarios import reseal
from .fixtures import source_fixture


class LegacyImportAcceptance(TransactionTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        inventory, _, data, _ = source_fixture(self.temporary.name)
        _, self.prepared = prepare_legacy_import(inventory, data, household_id="import-synthetic", dataset_key="synthetic-v1")
        self.actor = get_user_model().objects.create_user(username="import-owner")
        self.household = create_household(self.actor, "import-synthetic")

    def test_import_replay_and_unknowns_do_not_publish_or_create_attempts(self):
        result = import_prepared(self.actor, self.prepared)
        before = list(RevisionRecord.objects.order_by("pk").values_list("pk", "content_hash"))
        replay = import_prepared(self.actor, self.prepared)
        self.assertFalse(result["already_imported"])
        self.assertTrue(replay["already_imported"])
        self.assertEqual(result["batch_id"], replay["batch_id"])
        self.assertEqual(sum(replay["added"].values()), 0)
        self.assertEqual(RevisionRecord.objects.order_by("pk").values_list("pk", "content_hash").count(), len(before))
        self.assertEqual(list(RevisionRecord.objects.order_by("pk").values_list("pk", "content_hash")), before)
        self.assertEqual(LegacyImportBatch.objects.count(), 1)
        self.assertEqual(LegacyIndexEntry.objects.count(), 2)
        self.assertEqual(RequestReceipt.objects.count(), 1)
        restored = read_snapshot_bundle(self.actor, self.household.pk)
        actual_images, actual_entities = split_bundle(restored)
        expected_images, expected_entities = split_bundle(self.prepared.conversion.bundle)
        self.assertEqual({i["image_id"]: i for i in actual_images}, {i["image_id"]: i for i in expected_images})
        self.assertEqual(actual_entities, expected_entities)
        self.assertEqual(len(restored.images), 3)
        self.assertEqual(len(restored.observations), 3)
        self.assertEqual(restored.attempts, ())
        self.assertEqual(restored.assessments, ())
        self.assertEqual(restored.errata, ())
        self.assertFalse(EntityRecord.objects.exclude(published_revision=None).exists())
        self.assertTrue(all(q.revisions[0].working_text is None for q in restored.questions))
        self.assertTrue(all(o.revisions[0].author_state.value == "unknown" for o in restored.observations))

    def test_replay_preserves_later_question_revision_and_original_index_pin(self):
        import_prepared(self.actor, self.prepared)
        bundle = read_snapshot_bundle(self.actor, self.household.pk)
        q = bundle.questions[0]
        old = q.revisions[0]
        newer = reseal(old, header=replace(old.header, revision_id=old.header.revision_id + "-next", revision_no=2,
            previous_revision_id=old.header.revision_id, content_hash="", change_reason="Synthetic metadata revision"))
        changed = replace(bundle, questions=(replace(q, revisions=(old, newer)), *bundle.questions[1:]))
        stage_bundle(self.actor, changed, request_key="later-draft", expected_heads={ObjectKey("question", q.question_id): old.header.revision_id})
        import_prepared(self.actor, self.prepared)
        self.assertEqual(EntityRecord.objects.get(kind="question", stable_id=q.question_id).head_revision_id, newer.header.revision_id)
        self.assertTrue(RevisionRecord.objects.filter(pk=old.header.revision_id).exists())
        self.assertFalse(LegacyIndexEntry.objects.filter(question_revision_id=newer.header.revision_id).exists())

    def test_draft_forward_reverse_cross_page_and_unindexed_photo_trace(self):
        import_prepared(self.actor, self.prepared)
        forward = legacy_trace(self.actor, self.household.pk, "synthetic-v1", book="J1", number="1")
        self.assertEqual(forward["index_state"], "draft")
        self.assertEqual([p["token"] for p in forward["entries"][0]["photos"]], ["000001", "000002"])
        reverse = legacy_trace(self.actor, self.household.pk, "synthetic-v1", photo_token="000002")
        self.assertEqual(len(reverse["entries"]), 2)
        self.assertEqual(len(legacy_trace(self.actor, self.household.pk, "synthetic-v1", group=5)["entries"]), 1)
        unused = legacy_trace(self.actor, self.household.pk, "synthetic-v1", photo_token="000003")
        self.assertEqual(unused["entries"], [])
        self.assertIsNotNone(unused["source_photo"])
        parent = legacy_trace(self.actor, self.household.pk, "synthetic-v1", book="W1", number="2")
        self.assertEqual(parent["entries"], [])
        self.assertTrue(parent["questions"][0]["implicit_parent"])
        self.assertIn(parent["questions"][0]["question_revision_id"], [q["question_revision_id"] for q in reverse["questions"]])

    def test_changed_registered_source_is_rejected_by_database_dataset_guard(self):
        from app.imports.package import canonical, digest, read_json
        import_prepared(self.actor, self.prepared)
        with tempfile.TemporaryDirectory() as base:
            inventory, source, data, description = source_fixture(base)
            record = description["files"][0]
            rows = read_json((source / record["path"]).read_bytes())
            rows[0]["feature"] = "Changed registered summary"
            raw = canonical(rows)
            (source / record["path"]).write_bytes(raw)
            record.update(size_bytes=len(raw), sha256=digest(raw))
            inventory.write_bytes(canonical(description))
            _, changed = prepare_legacy_import(inventory, data, household_id=self.household.pk, dataset_key="synthetic-v1")
            with self.assertRaises(PersistenceError) as caught:
                import_prepared(self.actor, changed)
            self.assertEqual(caught.exception.code, "import_source_conflict")
        self.assertEqual(LegacyIndexEntry.objects.count(), 2)
        self.assertEqual(RequestReceipt.objects.count(), 1)

    def test_viewer_outsider_and_inactive_actor_cannot_import_even_on_replay(self):
        import_prepared(self.actor, self.prepared)
        viewer = get_user_model().objects.create_user(username="import-viewer")
        HouseholdMember.objects.create(household=self.household, user=viewer, role="viewer")
        self.assertEqual(len(legacy_trace(viewer, self.household.pk, "synthetic-v1")["entries"]), 2)
        outsider = get_user_model().objects.create_user(username="import-outsider")
        for actor in (viewer, outsider):
            with self.assertRaises(PersistenceError):
                import_prepared(actor, self.prepared)
        with self.assertRaises(PersistenceError):
            legacy_trace(outsider, self.household.pk, "synthetic-v1")
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
        with self.assertRaises(PersistenceError):
            import_prepared(self.actor, self.prepared)

    def test_modified_package_is_rejected_without_rows(self):
        import copy
        manifest = dict(self.prepared.manifest, index_rows=[])
        with self.assertRaises(ContractError):
            import_prepared(self.actor, replace(self.prepared, manifest=manifest))
        changed = copy.deepcopy(self.prepared)
        changed.conversion.index_rows[0]["raw"]["feature"] = "Changed in memory after byte verification"
        with self.assertRaises(ContractError):
            import_prepared(self.actor, changed)
        self.assertFalse(RevisionRecord.objects.exists())
        self.assertFalse(LegacyImportBatch.objects.exists())

    def test_late_entry_failure_rolls_back_bundle_receipt_and_batch(self):
        with patch("app.imports.services.LegacyIndexEntry.objects.bulk_create", side_effect=RuntimeError("Late synthetic failure")):
            with self.assertRaises(RuntimeError):
                import_prepared(self.actor, self.prepared)
        for model in (ImageRecord, EntityRecord, RevisionRecord, RequestReceipt, LegacyImportBatch, LegacyIndexEntry):
            self.assertEqual(model.objects.count(), 0)

    def test_native_provenance_update_delete_and_forged_mapping_are_rejected(self):
        import_prepared(self.actor, self.prepared)
        batch = LegacyImportBatch.objects.get()
        for sql in (lambda: LegacyImportBatch.objects.filter(pk=batch.pk).update(dataset_key="rewrite"),
                    lambda: LegacyIndexEntry.objects.all().update(raw={}),
                    lambda: LegacyIndexEntry.objects.all().delete()):
            with self.assertRaises(IntegrityError), transaction.atomic():
                sql()
        entry = LegacyIndexEntry.objects.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LegacyIndexEntry.objects.create(batch=batch, ordinal=3, book="J1", number="forged",
                question_revision=entry.primary_method_revision, primary_method_revision=entry.question_revision,
                raw=entry.raw, photo_tokens=entry.photo_tokens, auxiliary_method_revision_ids=[])

    def test_competing_imports_create_one_batch_and_one_receipt(self):
        barrier = threading.Barrier(2)
        def importing(_):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                barrier.wait(timeout=10)
                return import_prepared(actor, self.prepared)["already_imported"]
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(importing, range(2))), [False, True])
        self.assertEqual(LegacyImportBatch.objects.count(), 1)
        self.assertEqual(RequestReceipt.objects.count(), 1)

    def test_native_entry_rejects_wrong_type_and_other_household_even_with_matching_manifest(self):
        import copy
        import_prepared(self.actor, self.prepared)
        original = LegacyImportBatch.objects.get()
        entry = LegacyIndexEntry.objects.first()
        outsider = get_user_model().objects.create_user(username="native-other-owner")
        other = create_household(outsider, "native-other-household")
        for index, (household, actor, wrong_type) in enumerate(((self.household, self.actor, True), (other, outsider, False))):
            sha = str(index + 1) * 64
            manifest = copy.deepcopy(original.manifest)
            manifest.update(household_id=household.pk, dataset_key=f"native-forged-{index}", source_digest=sha)
            if wrong_type:
                manifest["index_rows"][0]["question_revision_id"] = entry.primary_method_revision_id
            receipt = RequestReceipt.objects.create(household=household, actor=actor,
                request_key=f"legacy-import:{sha}", operation="stage", request_hash="0" * 64, result={})
            batch = LegacyImportBatch.objects.create(household=household, imported_by=actor, receipt=receipt,
                dataset_key=manifest["dataset_key"], source_digest=sha, prepared_at=original.prepared_at,
                manifest=manifest, counts=manifest["counts"])
            with self.assertRaises(IntegrityError), transaction.atomic():
                LegacyIndexEntry.objects.create(batch=batch, ordinal=1, book=entry.book, number=entry.number,
                    question_revision_id=manifest["index_rows"][0]["question_revision_id"],
                    primary_method_revision_id=entry.primary_method_revision_id, raw=entry.raw,
                    photo_tokens=entry.photo_tokens, auxiliary_method_revision_ids=entry.auxiliary_method_revision_ids)
