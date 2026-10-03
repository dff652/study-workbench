"""Synthetic acceptance for exact question split/merge lineage."""
from io import BytesIO
import tempfile
import uuid

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image

from app.catalogue import services as catalogue
from app.catalogue.forms import MergeForm
from app.catalogue.models import QuestionLabel, QuestionLineage
from app.persistence import services as core
from app.persistence.models import EntityRecord, HouseholdMember, RevisionRecord
from app.web import services as materials
from app.web.models import QuestionSource


def key():
    return uuid.uuid4().hex


def png(color):
    output = BytesIO()
    Image.new("RGB", (80, 60), color).save(output, format="PNG")
    return output.getvalue()


class QuestionLineageTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.owner = get_user_model().objects.create_user(username=f"catalogue-owner-{suffix}")
        self.viewer = get_user_model().objects.create_user(username=f"catalogue-viewer-{suffix}")
        self.other = get_user_model().objects.create_user(username=f"catalogue-other-{suffix}")
        self.household = core.create_household(self.owner, f"catalogue-house-{suffix}")
        self.other_household = core.create_household(self.other, f"catalogue-other-house-{suffix}")
        HouseholdMember.objects.create(household=self.household, user=self.viewer, role=HouseholdMember.Role.VIEWER)
        self.data_root = tempfile.TemporaryDirectory(prefix="swb-catalogue-test-")
        self.addCleanup(self.data_root.cleanup)
        self.settings = override_settings(SWB_DATA_ROOT=self.data_root.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.material = materials.create_material(self.owner, self.household.pk, "合成原图", key())
        self.other_material = materials.create_material(self.other, self.other_household.pk, "另一家庭", key())

    def make_sources(self, material, colors):
        sources = []
        for index, color in enumerate(colors):
            page = materials.upload_page(self.owner if material == self.material else self.other,
                material.pk, SimpleUploadedFile(f"source-{index}.png", png(color), content_type="image/png"), key())["page_id"]
            preview = materials.preview_file(self.owner if material == self.material else self.other, page, 0)
            sources.append({"page_id": page, "rotation": 0, "preview_sha256": preview.sha256,
                "display_bbox": [2 + index, 4 + index, 40 + index, 35 + index]})
        return sources

    def make_question(self, number, text, colors):
        sources = self.make_sources(self.material, colors)
        saved = materials.save_question(self.owner, self.material.pk, printed_text=text,
            original_number=number, sources=sources, request_key=key(), reason="合成题目录入")
        return saved

    def test_split_keeps_parent_exact_and_copies_ordered_regions_with_replay(self):
        source = self.make_question("J1-1", "原题：求周长", [(190, 40, 40), (40, 190, 40)])
        entity = EntityRecord.objects.get(household=self.household, kind="question", stable_id=source["question_id"])
        source_revision = entity.head_revision
        original_payload = source_revision.payload
        token = catalogue.prepare_context(self.owner, self.household.pk, "split", [source["revision_id"]])
        request_key = key()
        result = catalogue.split_question(self.owner, self.household.pk, source_revision_id=source["revision_id"],
            context_token=token, children=[
                {"original_number": "J1-1(a)", "printed_text": "求半圆弧长"},
                {"original_number": "J1-1(b)", "printed_text": "求直径"},
            ], reason="将原题拆成两问", request_key=request_key)
        replay = catalogue.split_question(self.owner, self.household.pk, source_revision_id=source["revision_id"],
            context_token=token, children=[
                {"original_number": "J1-1(a)", "printed_text": "求半圆弧长"},
                {"original_number": "J1-1(b)", "printed_text": "求直径"},
            ], reason="将原题拆成两问", request_key=request_key)

        self.assertEqual(replay, result)
        self.assertEqual(QuestionLineage.objects.count(), 1)
        entity.refresh_from_db()
        self.assertEqual(entity.head_revision_id, source["revision_id"])
        self.assertEqual(entity.head_revision.payload, original_payload)
        target_entities = [EntityRecord.objects.get(household=self.household, kind="question", stable_id=qid)
            for qid in result["target_question_ids"]]
        self.assertEqual(len(target_entities), 2)
        expected_images = [ref["image_id"] for ref in original_payload["evidence_refs"]]
        for child, target_revision_id in zip(target_entities, result["target_revision_ids"]):
            revision = child.head_revision
            self.assertEqual(child.identity["parent_question_id"], source["question_id"])
            self.assertEqual(revision.payload["parent_question_revision_id"], source["revision_id"])
            self.assertEqual(revision.payload["review_state"], "draft")
            self.assertEqual([ref["image_id"] for ref in revision.payload["evidence_refs"]], expected_images)
            self.assertEqual(revision.payload["evidence_refs"][0]["sequence"], 1)
            self.assertEqual(revision.payload["evidence_refs"][1]["sequence"], 2)
            self.assertEqual(child.published_revision_id, None)
            self.assertTrue(QuestionSource.objects.filter(revision_id=target_revision_id,
                original_number__in=("J1-1(a)", "J1-1(b)"), material=self.material).exists())
        lineage = QuestionLineage.objects.get()
        self.assertEqual(lineage.source_revision_ids, [source["revision_id"]])
        self.assertEqual(lineage.target_revision_ids, result["target_revision_ids"])
        self.assertEqual(lineage.actor_id, self.owner.pk)
        self.assertEqual(lineage.reason, "将原题拆成两问")
        source_trace = catalogue.question_detail(self.owner, entity.pk)["lineages"][0]
        target_trace = catalogue.question_detail(self.owner, target_entities[0].pk)["lineages"][0]
        self.assertEqual([row.pk for row in source_trace["targets"]], result["target_revision_ids"])
        self.assertEqual([row.pk for row in target_trace["sources"]], [source["revision_id"]])

        child = target_entities[0]
        child_data = materials.question_detail(self.owner, child.stable_id)
        additional_source = self.make_sources(self.material, [(50, 140, 80)])
        materials.save_question(self.owner, self.material.pk, printed_text="子题人工修订后的题干",
            original_number="J1-1(a)", sources=[*child_data["sources"], *additional_source],
            question_id=child.stable_id, expected_context=child_data["edit_context"],
            reason="补充来源并修订题干", request_key=key())
        child.refresh_from_db()
        self.assertEqual(child.identity["parent_question_id"], source["question_id"])
        self.assertEqual(child.head_revision.payload["parent_question_revision_id"], source["revision_id"])
        self.assertEqual(QuestionLineage.objects.get().source_revision_ids, [source["revision_id"]])
        self.assertEqual(QuestionLineage.objects.get().target_revision_ids, result["target_revision_ids"])
        revised_trace = catalogue.question_detail(self.owner, child.pk)["lineages"][0]
        self.assertEqual([row.pk for row in revised_trace["sources"]], [source["revision_id"]])

    def test_merge_requires_current_unique_local_sources_and_preserves_region_order(self):
        first = self.make_question("J1-2", "第一来源", [(170, 30, 30), (30, 170, 30)])
        second = self.make_question("J1-3", "第二来源", [(30, 30, 170)])
        source_ids = [first["revision_id"], second["revision_id"]]
        token = catalogue.prepare_context(self.owner, self.household.pk, "merge", source_ids)
        request_key = key()
        result = catalogue.merge_questions(self.owner, self.household.pk, source_revision_ids=source_ids,
            context_token=token, original_number="J1-2+3", printed_text="人工合并后的题干",
            reason="合并同一图形的两个小问", request_key=request_key)
        replay = catalogue.merge_questions(self.owner, self.household.pk, source_revision_ids=source_ids,
            context_token=token, original_number="J1-2+3", printed_text="人工合并后的题干",
            reason="合并同一图形的两个小问", request_key=request_key)
        self.assertEqual(replay, result)
        self.assertEqual(QuestionLineage.objects.count(), 1)
        merged = EntityRecord.objects.get(household=self.household, kind="question",
            stable_id=result["target_question_ids"][0])
        self.assertEqual(merged.identity["parent_question_id"], None)
        self.assertEqual(merged.head_revision.payload["parent_question_revision_id"], None)
        self.assertEqual(merged.head_revision.payload["review_state"], "draft")
        self.assertEqual(merged.published_revision_id, None)
        source_image_order = [ref["image_id"] for revision_id in source_ids
            for ref in RevisionRecord.objects.get(pk=revision_id).payload["evidence_refs"]]
        target_image_order = [ref["image_id"] for ref in merged.head_revision.payload["evidence_refs"]]
        self.assertEqual(target_image_order, list(dict.fromkeys(source_image_order)))
        evidence = merged.head_revision.payload["evidence_refs"]
        self.assertEqual([ref["sequence"] for ref in evidence], list(range(1, len(evidence) + 1)))
        metadata = QuestionSource.objects.get(revision=merged.head_revision)
        self.assertEqual(metadata.material_id, self.material.pk)
        self.assertEqual([row["sequence"] for row in metadata.sources], list(range(1, len(evidence) + 1)))
        lineage = QuestionLineage.objects.get()
        self.assertEqual(lineage.source_revision_ids, source_ids)
        self.assertEqual(lineage.target_revision_ids, result["target_revision_ids"])
        source_entity = EntityRecord.objects.get(household=self.household, kind="question", stable_id=first["question_id"])
        trace = catalogue.question_detail(self.owner, source_entity.pk)["lineages"][0]
        self.assertEqual([row.pk for row in trace["targets"]], result["target_revision_ids"])
        reverse = catalogue.question_detail(self.owner, merged.pk)["lineages"][0]
        self.assertEqual([row.pk for row in reverse["sources"]], source_ids)

        with self.assertRaises(core.PersistenceError):
            catalogue.prepare_context(self.owner, self.household.pk, "merge", [first["revision_id"], first["revision_id"]])
        with self.assertRaises(core.PersistenceError):
            catalogue.prepare_context(self.owner, self.household.pk, "merge", [first["revision_id"], "foreign-revision"])

    def test_cross_material_merge_keeps_entered_number_and_immutable_label(self):
        first = self.make_question("A1", "第一份资料", [(170, 30, 30)])
        original_material = self.material
        self.material = materials.create_material(self.owner, self.household.pk, "第二份资料", key())
        second = self.make_question("B2", "第二份资料", [(30, 30, 170)])
        self.material = original_material
        source_ids = [first["revision_id"], second["revision_id"]]
        args = {"source_revision_ids": source_ids,
            "context_token": catalogue.prepare_context(self.owner, self.household.pk, "merge", source_ids),
            "original_number": "合题 A1+B2", "printed_text": "跨资料人工合题",
            "reason": "保留两份来源", "request_key": key()}
        result = catalogue.merge_questions(self.owner, self.household.pk, **args)
        self.assertEqual(catalogue.merge_questions(self.owner, self.household.pk, **args), result)
        revision_id = result["target_revision_ids"][0]
        label = QuestionLabel.objects.get(revision_id=revision_id)
        self.assertEqual(label.original_number, "合题 A1+B2")
        self.assertEqual(label.created_by, self.owner)
        self.assertEqual(QuestionLabel.objects.count(), 1)
        self.assertFalse(QuestionSource.objects.filter(revision_id=revision_id).exists())
        entry = next(row for row in catalogue.question_index(self.owner, self.household.pk)["questions"]
            if row["revision"].pk == revision_id)
        self.assertEqual(entry["number"], "合题 A1+B2")
        self.assertEqual(QuestionLineage.objects.get().source_revision_ids, source_ids)
        self.assertEqual(len(RevisionRecord.objects.get(pk=revision_id).payload["evidence_refs"]), 2)
        with self.assertRaises(DatabaseError), transaction.atomic():
            QuestionLabel.objects.filter(pk=revision_id).update(original_number="覆盖题号")
        with self.assertRaises(DatabaseError), transaction.atomic():
            QuestionLabel.objects.filter(pk=revision_id).delete()
        for actor in (self.viewer, self.other):
            with self.assertRaises(DatabaseError), transaction.atomic():
                QuestionLabel.objects.create(revision_id=first["revision_id"], original_number="A1",
                    created_by=actor)

        split = catalogue.split_question(self.owner, self.household.pk, source_revision_id=revision_id,
            context_token=catalogue.prepare_context(self.owner, self.household.pk, "split", [revision_id]),
            children=[{"original_number": "C1", "printed_text": "第一问"},
                {"original_number": "C2", "printed_text": "第二问"}], reason="继续拆分跨资料合题", request_key=key())
        self.assertEqual(set(QuestionLabel.objects.filter(revision_id__in=split["target_revision_ids"])
            .values_list("original_number", flat=True)), {"C1", "C2"})

    def test_stale_or_tampered_context_and_write_permissions_are_rejected(self):
        source = self.make_question("J1-4", "待拆分题目", [(120, 120, 30)])
        entity = EntityRecord.objects.get(household=self.household, kind="question", stable_id=source["question_id"])
        token = catalogue.prepare_context(self.owner, self.household.pk, "split", [source["revision_id"]])
        with self.assertRaises(core.PersistenceError) as caught:
            catalogue.split_question(self.viewer, self.household.pk, source_revision_id=source["revision_id"],
                context_token=token, children=[{"original_number": "1a", "printed_text": ""},
                    {"original_number": "1b", "printed_text": ""}], reason="viewer", request_key=key())
        self.assertEqual(caught.exception.code, "permission_denied")
        with self.assertRaises(core.PersistenceError):
            catalogue.split_question(self.owner, self.household.pk, source_revision_id=source["revision_id"],
                context_token=token[:-1] + ("A" if token[-1] != "A" else "B"), children=[
                    {"original_number": "1a", "printed_text": ""}, {"original_number": "1b", "printed_text": ""}],
                reason="tampered", request_key=key())

        data = materials.question_detail(self.owner, source["question_id"])
        materials.save_question(self.owner, self.material.pk, printed_text="已编辑的新题干",
            original_number="J1-4", sources=data["sources"], question_id=source["question_id"],
            expected_context=data["edit_context"], reason="更正题干", request_key=key())
        with self.assertRaises(core.PersistenceError) as caught:
            catalogue.split_question(self.owner, self.household.pk, source_revision_id=source["revision_id"],
                context_token=token, children=[{"original_number": "1a", "printed_text": ""},
                    {"original_number": "1b", "printed_text": ""}], reason="stale", request_key=key())
        self.assertEqual(caught.exception.code, "head_conflict")
        with self.assertRaises(core.PersistenceError):
            catalogue.prepare_context(self.other, self.household.pk, "split", [source["revision_id"]])
        with self.assertRaises(core.PersistenceError):
            catalogue.prepare_context(self.owner, self.household.pk, "split", ["foreign-revision"])

    def test_exact_replay_returns_receipt_even_after_source_head_changes(self):
        source = self.make_question("J1-6", "拆分后继续修订的题目", [(60, 130, 190)])
        token = catalogue.prepare_context(self.owner, self.household.pk, "split", [source["revision_id"]])
        children = [{"original_number": "J1-6(a)", "printed_text": "子题一"},
            {"original_number": "J1-6(b)", "printed_text": "子题二"}]
        request_key = key()
        first = catalogue.split_question(self.owner, self.household.pk, source_revision_id=source["revision_id"],
            context_token=token, children=children, reason="首次拆分", request_key=request_key)

        current = materials.question_detail(self.owner, source["question_id"])
        materials.save_question(self.owner, self.material.pk, printed_text="来源题目后来有更正",
            original_number="J1-6", sources=current["sources"], question_id=source["question_id"],
            expected_context=current["edit_context"], reason="更新来源题目", request_key=key())
        replay = catalogue.split_question(self.owner, self.household.pk, source_revision_id=source["revision_id"],
            context_token=token, children=children, reason="首次拆分", request_key=request_key)

        self.assertEqual(replay, first)
        self.assertEqual(QuestionLineage.objects.count(), 1)

    def test_merge_form_rejects_unhashable_json_revision_values(self):
        form = MergeForm(data={"request_key": key(), "household_id": str(self.household.pk),
            "context_token": "signed-context", "source_revision_ids": '[[], "revision"]',
            "original_number": "1+2", "printed_text": "合并题干", "reason": "人工合并"})
        self.assertFalse(form.is_valid())
        self.assertIn("source_revision_ids", form.errors)

    def test_split_http_requires_login_csrf_and_write_membership(self):
        source = self.make_question("J1-7", "HTTP 权限测试题", [(120, 90, 40)])
        entity = EntityRecord.objects.get(household=self.household, kind="question", stable_id=source["question_id"])
        url = reverse("catalogue:question_split", kwargs={"entity_id": entity.pk})
        owner_client = Client(enforce_csrf_checks=True)
        login_response = owner_client.get(url)
        self.assertEqual(login_response.status_code, 302)
        self.assertIn("/accounts/login/", login_response["Location"])
        owner_client.force_login(self.owner)
        form_data = {"request_key": key(), "household_id": str(self.household.pk),
            "source_revision_id": source["revision_id"],
            "context_token": catalogue.prepare_context(self.owner, self.household.pk, "split", [source["revision_id"]]),
            "reason": "HTTP 拆题", "child_1_number": "J1-7(a)", "child_1_text": "第一问",
            "child_2_number": "J1-7(b)", "child_2_text": "第二问"}
        self.assertEqual(owner_client.post(url, form_data).status_code, 403)
        owner_page = owner_client.get(url)
        self.assertEqual(owner_page.status_code, 200)
        form_data["csrfmiddlewaretoken"] = owner_client.cookies["csrftoken"].value

        viewer_client = Client(enforce_csrf_checks=True)
        viewer_client.force_login(self.viewer)
        viewer_page = viewer_client.get(url)
        self.assertEqual(viewer_page.status_code, 200)
        viewer_form = {**form_data, "request_key": key(),
            "context_token": catalogue.prepare_context(self.viewer, self.household.pk, "split", [source["revision_id"]]),
            "csrfmiddlewaretoken": viewer_client.cookies["csrftoken"].value}
        self.assertEqual(viewer_client.post(url, viewer_form).status_code, 404)

        form_data["request_key"] = key()
        self.assertEqual(owner_client.post(url, form_data).status_code, 302)
        self.assertEqual(QuestionLineage.objects.count(), 1)

    def test_lineage_database_guards_enforce_target_relation_and_append_only(self):
        source = self.make_question("J1-5", "父题", [(120, 20, 20)])
        token = catalogue.prepare_context(self.owner, self.household.pk, "split", [source["revision_id"]])
        split = catalogue.split_question(self.owner, self.household.pk, source_revision_id=source["revision_id"],
            context_token=token, children=[{"original_number": "J1-5(a)", "printed_text": "子题甲"},
                {"original_number": "J1-5(b)", "printed_text": "子题乙"}], reason="测试不可变", request_key=key())
        lineage = QuestionLineage.objects.get()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                QuestionLineage.objects.filter(pk=lineage.pk).update(reason="篡改")
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                QuestionLineage.objects.filter(pk=lineage.pk).delete()
        source_ids = [source["revision_id"], "another-current-source"]
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                QuestionLineage.objects.create(household=self.household, action="merge",
                    source_revision_ids=source_ids, target_revision_ids=[split["target_revision_ids"][0]],
                    actor=self.owner, reason="不匹配 parent", recorded_at=lineage.recorded_at)
