"""Synthetic acceptance for B2a knowledge nodes and exact typed links."""
import tempfile
import uuid

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from PIL import Image
from io import BytesIO

from app.domain.contracts import EvidencePurpose
from app.imports.models import LegacyIndexEntry
from app.imports.package import prepare_legacy_import
from app.imports.services import import_prepared
from app.persistence import services as core
from app.persistence.adapter import ObjectKey
from app.persistence.models import EntityRecord, EvidenceRecord, HouseholdMember
from app.web import knowledge_services as knowledge
from app.web import services as materials
from tests.imports.fixtures import source_fixture


def request_key():
    return uuid.uuid4().hex


def synthetic_png():
    output = BytesIO()
    Image.new("RGB", (80, 60), (210, 220, 230)).save(output, format="PNG")
    return output.getvalue()


class KnowledgeServicesTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username=f"knowledge-owner-{uuid.uuid4().hex[:8]}")
        self.viewer = get_user_model().objects.create_user(username=f"knowledge-viewer-{uuid.uuid4().hex[:8]}")
        self.household = core.create_household(self.owner, f"knowledge-house-{uuid.uuid4().hex}")
        HouseholdMember.objects.create(household=self.household, user=self.viewer, role=HouseholdMember.Role.VIEWER)
        self.data_root = tempfile.TemporaryDirectory(prefix="swb-knowledge-test-")
        self.addCleanup(self.data_root.cleanup)
        self.settings = override_settings(SWB_DATA_ROOT=self.data_root.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.material = materials.create_material(self.owner, self.household.pk, "合成来源", request_key())

    def source(self):
        page = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile("synthetic.png", synthetic_png(), content_type="image/png"), request_key())["page_id"]
        preview = materials.preview_file(self.owner, page, 0)
        return {"page_id": page, "rotation": 0, "preview_sha256": preview.sha256,
            "display_bbox": [5, 5, 60, 45]}

    def question(self):
        return materials.save_question(self.owner, self.material.pk, printed_text="2 + 3 = ?",
            original_number="J1-1", sources=[self.source()], request_key=request_key(), reason="合成题目")

    def save_node(self, kind, values, *, stable_id=None, expected_context=None):
        return knowledge.save_node(self.owner, self.household.pk, kind, data={
            "sources": "[]", "replace_sources": False, **values,
        }, request_key=request_key(), reason="合成知识整理", stable_id=stable_id,
            expected_context=expected_context)

    def accept(self, entity, revision_id):
        context = core.review_context(self.owner, self.household.pk, revision_id)
        return core.review_revision(self.owner, self.household.pk, revision_id, action="accept",
            expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
            expected_decision_id=context["expected_decision_id"], request_key=request_key(), reason="合成验收")

    def test_all_node_kinds_keep_native_revisions_and_definition_source_refs(self):
        source = self.source()
        created = self.save_node("knowledge", {"definition": "圆面积 $A=\\pi r^2$\n例：r=2",
            "conditions": "半径已知\n单位一致", "common_errors": "忘记平方", "sources": [source]})
        knowledge_row = EntityRecord.objects.get(household=self.household, kind="knowledge",
            stable_id=created["stable_id"])
        self.assertEqual(knowledge_row.head_revision.payload["definition"], "圆面积 $A=\\pi r^2$\n例：r=2")
        self.assertEqual(knowledge_row.head_revision.payload["conditions"], ["半径已知", "单位一致"])
        self.assertEqual(knowledge_row.head_revision.payload["common_errors"], ["忘记平方"])
        evidence = EvidenceRecord.objects.get(source=knowledge_row.head_revision)
        self.assertEqual(evidence.purpose, EvidencePurpose.DEFINITION.value)
        self.assertEqual(len(knowledge.node_detail(self.owner,knowledge_row.pk)['current_sources']),1)

        method = self.save_node("method", {"name": "配方法", "conditions": "二次式",
            "steps": "移项\n配方", "notes": "保持等式", "parent_revision_id": ""})
        child = self.save_node("method", {"name": "首项系数非一时配方", "conditions": "a 不等于 1",
            "steps": "先提取 a", "notes": "", "parent_revision_id": method["revision_id"]})
        method_detail = knowledge.node_detail(self.owner,
            EntityRecord.objects.get(household=self.household, kind="method", stable_id=child["stable_id"]).pk)
        self.assertEqual(method_detail["parent_revision"].pk, method["revision_id"])

        question_type = self.save_node("question_type", {"name": "圆面积计算",
            "structural_features": "给出半径", "conditions": "求面积"})
        self.assertEqual(EntityRecord.objects.get(kind="question_type", stable_id=question_type["stable_id"])
            .head_revision.payload["structural_features"], ["给出半径"])

        before = knowledge.node_detail(self.owner, knowledge_row.pk)
        edited = self.save_node("knowledge", {"definition": "新定义", "conditions": "", "common_errors": ""},
            stable_id=created["stable_id"], expected_context=before["edit_context"])
        knowledge_row.refresh_from_db()
        self.assertEqual(knowledge_row.head_revision_id, edited["revision_id"])
        self.assertEqual(knowledge_row.published_revision_id, None)
        self.assertEqual(knowledge_row.revisions.count(), 2)
        self.assertEqual(knowledge_row.revisions.get(pk=created["revision_id"]).payload["definition"],
            "圆面积 $A=\\pi r^2$\n例：r=2")

        old_context=knowledge.node_detail(self.owner,knowledge_row.pk)['edit_context']
        retry_key=request_key()
        args=dict(data={'definition':'幂的定义','sources':[]},request_key=retry_key,reason='重放验收',
            stable_id=created['stable_id'],expected_context=old_context)
        once=knowledge.save_node(self.owner,self.household.pk,'knowledge',**args)
        self.assertEqual(once,knowledge.save_node(self.owner,self.household.pk,'knowledge',**args))
        knowledge_row.refresh_from_db();self.assertEqual(knowledge_row.revisions.count(),3)

        with self.assertRaises(core.PersistenceError):
            knowledge.save_node(self.viewer, self.household.pk, "knowledge", data={
                "definition": "viewer cannot write", "sources": "[]"}, request_key=request_key(), reason="forbidden")

    def test_exact_links_publish_only_with_published_endpoints_and_reverse_trace(self):
        question = self.question()
        node = self.save_node("knowledge", {"definition": "三的加法", "conditions": "", "common_errors": ""})
        question_entity = EntityRecord.objects.get(household=self.household, kind="question",
            stable_id=question["question_id"])
        node_entity = EntityRecord.objects.get(household=self.household, kind="knowledge",
            stable_id=node["stable_id"])
        link = knowledge.create_link(self.owner, self.household.pk, kind="knowledge",
            node_revision_id=node["revision_id"], question_revision_id=question["revision_id"],
            role="applies", request_key=request_key(), reason="对应练习")
        link_entity = EntityRecord.objects.get(household=self.household, kind="knowledge_question",
            stable_id=link["stable_id"])
        with self.assertRaises(core.PersistenceError) as caught:
            self.accept(link_entity, link["revision_id"])
        self.assertEqual(caught.exception.code, "unaccepted_dependency")

        self.accept(question_entity, question["revision_id"])
        self.accept(node_entity, node["revision_id"])
        self.accept(link_entity, link["revision_id"])
        trace = core.published_trace(self.owner, self.household.pk,
            node=ObjectKey("knowledge", node["stable_id"]))
        self.assertEqual(trace["question_revision_ids"], [question["revision_id"]])
        self.assertEqual(trace["node_revision_ids"], [node["revision_id"]])
        node_detail = knowledge.node_detail(self.owner, node_entity.pk)
        question_detail = knowledge.question_detail(self.owner, question_entity.pk)
        self.assertEqual(node_detail["links"][0]["question"]["entity"].pk, question_entity.pk)
        self.assertEqual(question_detail["current_links"][0]["node"].pk, node_entity.pk)
        self.assertTrue(node_detail["links"][0]["current"])

        primary = self.save_node("method", {"name": "竖式计算", "conditions": "", "steps": "", "notes": ""})
        auxiliary = self.save_node("method", {"name": "估算校验", "conditions": "", "steps": "", "notes": ""})
        primary_entity = EntityRecord.objects.get(household=self.household, kind="method", stable_id=primary["stable_id"])
        auxiliary_entity = EntityRecord.objects.get(household=self.household, kind="method", stable_id=auxiliary["stable_id"])
        self.accept(primary_entity, primary["revision_id"])
        self.accept(auxiliary_entity, auxiliary["revision_id"])
        primary_link = knowledge.create_link(self.owner, self.household.pk, kind="method",
            node_revision_id=primary["revision_id"], question_revision_id=question["revision_id"],
            role="primary", request_key=request_key(), reason="主要方法")
        primary_link_entity = EntityRecord.objects.get(household=self.household, kind="method_question",
            stable_id=primary_link["stable_id"])
        self.accept(primary_link_entity, primary_link["revision_id"])
        auxiliary_link = knowledge.create_link(self.owner, self.household.pk, kind="method",
            node_revision_id=auxiliary["revision_id"], question_revision_id=question["revision_id"],
            role="auxiliary", request_key=request_key(), reason="辅助校验")
        auxiliary_link_entity = EntityRecord.objects.get(household=self.household, kind="method_question",
            stable_id=auxiliary_link["stable_id"])
        self.accept(auxiliary_link_entity, auxiliary_link["revision_id"])
        second_primary = self.save_node("method", {"name": "拆分计算", "conditions": "", "steps": "", "notes": ""})
        second_primary_entity = EntityRecord.objects.get(household=self.household, kind="method",
            stable_id=second_primary["stable_id"])
        self.accept(second_primary_entity, second_primary["revision_id"])
        conflicting_link = knowledge.create_link(self.owner, self.household.pk, kind="method",
            node_revision_id=second_primary["revision_id"], question_revision_id=question["revision_id"],
            role="primary", request_key=request_key(), reason="冲突的主方法")
        conflicting_entity = EntityRecord.objects.get(household=self.household, kind="method_question",
            stable_id=conflicting_link["stable_id"])
        with self.assertRaises(core.PersistenceError) as caught:
            self.accept(conflicting_entity, conflicting_link["revision_id"])
        self.assertEqual(caught.exception.code, "multiple_primary_methods")

        edited = self.save_node("knowledge", {"definition": "三的加法修订", "conditions": "", "common_errors": ""},
            stable_id=node["stable_id"], expected_context=node_detail["edit_context"])
        self.accept(node_entity, edited["revision_id"])
        node_detail = knowledge.node_detail(self.owner, node_entity.pk)
        self.assertEqual(node_detail["links"][0]["node_revision"].pk, node["revision_id"])
        self.assertTrue(node_detail["links"][0]["outdated"])
        self.assertFalse(node_detail["links"][0]["current"])
        question_detail = knowledge.question_detail(self.owner, question_entity.pk)
        self.assertFalse(question_detail["current_links"][0]["current"])

    def test_old_imported_index_remains_visible_with_missing_text_and_region(self):
        source_dir = tempfile.TemporaryDirectory(prefix="swb-legacy-index-")
        self.addCleanup(source_dir.cleanup)
        inventory, _, data, _ = source_fixture(source_dir.name)
        _, prepared = prepare_legacy_import(inventory, data, household_id=self.household.pk,
            dataset_key="knowledge-test-v1")
        import_prepared(self.owner, prepared)

        home = knowledge.index_data(self.owner, self.household.pk)
        legacy_entity_ids = set(LegacyIndexEntry.objects.values_list("question_revision__entity_id", flat=True))
        indexed_rows = [row for row in home["questions"] if row["entity"].pk in legacy_entity_ids]
        self.assertEqual(len(indexed_rows), 2)
        self.assertTrue(all(row["legacy"] and row["missing"] for row in indexed_rows))
        old = indexed_rows[0]["entity"]
        detail = knowledge.question_detail(self.owner, old.pk)
        self.assertTrue(detail["current"]["missing_fields"])
        self.assertIsNone(old.published_revision_id)
        self.assertTrue(LegacyIndexEntry.objects.filter(question_revision_id=old.head_revision_id).exists())
