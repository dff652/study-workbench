"""Synthetic acceptance for B2a knowledge nodes and exact typed links."""
from dataclasses import replace
import tempfile
import uuid

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from PIL import Image
from io import BytesIO

from app.catalogue import services as catalogue
from app.catalogue.models import QuestionLabel
from app.domain import ReviewState, seal_revision
from app.domain.contracts import EvidencePurpose, EvidenceRef, Granularity
from app.imports.models import LegacyIndexEntry
from app.imports.package import prepare_legacy_import
from app.imports.services import import_prepared
from app.persistence import services as core
from app.persistence.adapter import ObjectKey
from app.persistence.models import EntityRecord, EvidenceRecord, HouseholdMember, RevisionRecord
from app.printing import services as printing
from app.web import knowledge_services as knowledge
from app.web import records
from app.web import services as materials
from app.web.knowledge_forms import IndexForm
from app.web.models import QuestionSource
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

    def source(self, material=None):
        material = material or self.material
        page = materials.upload_page(self.owner, material.pk,
            SimpleUploadedFile("synthetic.png", synthetic_png(), content_type="image/png"), request_key())["page_id"]
        preview = materials.preview_file(self.owner, page, 0)
        return {"page_id": page, "rotation": 0, "preview_sha256": preview.sha256,
            "display_bbox": [5, 5, 60, 45]}

    def question(self, material=None, *, printed_text="2 + 3 = ?", original_number="J1-1"):
        material = material or self.material
        return materials.save_question(self.owner, material.pk, printed_text=printed_text,
            original_number=original_number, sources=[self.source(material)], request_key=request_key(), reason="合成题目")

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

    def withdraw(self, revision_id):
        context = core.review_context(self.owner, self.household.pk, revision_id)
        return core.review_revision(self.owner, self.household.pk, revision_id, action="withdraw",
            expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
            expected_decision_id=context["expected_decision_id"], request_key=request_key(), reason="撤回关系")

    def test_all_node_kinds_keep_native_revisions_and_definition_source_refs(self):
        source = self.source()
        created = self.save_node("knowledge", {"definition": "圆面积 $A=\\pi r^2$\n例：r=2",
            "display_markup": "**圆面积** $A=\\pi r^2$\n例：r=2",
            "conditions": "半径已知\n单位一致", "common_errors": "忘记平方", "sources": [source]})
        knowledge_row = EntityRecord.objects.get(household=self.household, kind="knowledge",
            stable_id=created["stable_id"])
        self.assertEqual(knowledge_row.head_revision.payload["definition"], "圆面积 $A=\\pi r^2$\n例：r=2")
        self.assertEqual(knowledge_row.head_revision.payload["conditions"], ["半径已知", "单位一致"])
        self.assertEqual(knowledge_row.head_revision.payload["common_errors"], ["忘记平方"])
        self.assertEqual(knowledge_row.head_revision.payload["display_markup"],
            "**圆面积** $A=\\pi r^2$\n例：r=2")
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
        self.assertIsNone(knowledge_row.head_revision.payload.get("display_markup"))

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

    def test_knowledge_display_markup_is_validated_against_text_and_exact_source_sequence(self):
        source = self.source()
        valid = self.save_node("knowledge", {"definition": "参考\n图例",
            "display_markup": "参考\n[[image:1|图例]]", "conditions": "", "common_errors": "",
            "sources": [source]})
        revision = EntityRecord.objects.get(household=self.household, kind="knowledge",
            stable_id=valid["stable_id"]).head_revision
        self.assertEqual(revision.payload["display_markup"], "参考\n[[image:1|图例]]")

        for markup, definition in (("另一段正文", "原始正文"),
                ("参考\n[[image:2|图例]]", "参考\n图例")):
            with self.subTest(markup=markup), self.assertRaises(core.PersistenceError) as caught:
                self.save_node("knowledge", {"definition": definition, "display_markup": markup,
                    "conditions": "", "common_errors": "", "sources": [source]})
            self.assertEqual(caught.exception.code, "invalid_input")

    def test_knowledge_display_markup_is_part_of_request_fingerprint(self):
        request_id = request_key()
        data = {"definition": "同一正文", "display_markup": "**同一**正文",
            "conditions": "", "common_errors": "", "sources": "[]"}
        knowledge.save_node(self.owner, self.household.pk, "knowledge", data=data,
            request_key=request_id, reason="排版幂等指纹")
        changed = {**data, "display_markup": "==同一==正文"}
        with self.assertRaises(core.PersistenceError) as caught:
            knowledge.save_node(self.owner, self.household.pk, "knowledge", data=changed,
                request_key=request_id, reason="排版幂等指纹")
        self.assertEqual(caught.exception.code, "request_conflict")

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
        self.assertEqual(indexed_rows[0]["state"], "draft")
        self.assertTrue(LegacyIndexEntry.objects.filter(question_revision_id=old.head_revision_id).exists())

        for entry in LegacyIndexEntry.objects.filter(batch__household=self.household):
            for revision_id in (entry.primary_method_revision_id, *entry.auxiliary_method_revision_ids):
                if not revision_id:
                    continue
                method = RevisionRecord.objects.get(pk=revision_id).entity
                self.assertIn(entry.question_revision.entity_id,
                    knowledge._question_entities_for_node(self.owner, self.household.pk,
                        "method", method.stable_id))

    def test_index_filters_only_published_exact_links_for_all_node_kinds(self):
        question = self.question()
        question_entity = EntityRecord.objects.get(household=self.household, kind="question",
            stable_id=question["question_id"])
        self.accept(question_entity, question["revision_id"])
        cases = (
            ("knowledge", {"definition": "精确知识点", "conditions": "", "common_errors": ""}, "applies"),
            ("method", {"name": "精确方法", "conditions": "", "steps": "", "notes": ""}, "primary"),
            ("question_type", {"name": "精确题型", "structural_features": "", "conditions": ""}, "belongs"),
        )
        for kind, values, role in cases:
            with self.subTest(kind=kind):
                node = self.save_node(kind, values)
                node_entity = EntityRecord.objects.get(household=self.household, kind=kind,
                    stable_id=node["stable_id"])
                self.accept(node_entity, node["revision_id"])
                filter_key = {"knowledge": "knowledge_id", "method": "method_id",
                    "question_type": "question_type_id"}[kind]

                link = knowledge.create_link(self.owner, self.household.pk, kind=kind,
                    node_revision_id=node["revision_id"], question_revision_id=question["revision_id"],
                    role=role, request_key=request_key(), reason="精确发布关系")
                self.assertEqual(knowledge.index_data(self.owner, self.household.pk,
                    {filter_key: node["stable_id"]})["questions"], [])
                link_entity = EntityRecord.objects.get(household=self.household,
                    kind={"knowledge": "knowledge_question", "method": "method_question",
                        "question_type": "question_type_link"}[kind], stable_id=link["stable_id"])
                self.accept(link_entity, link["revision_id"])
                filtered = knowledge.index_data(self.owner, self.household.pk,
                    {filter_key: node["stable_id"]})["questions"]
                self.assertEqual([row["entity"].pk for row in filtered], [question_entity.pk])

                detail = knowledge.node_detail(self.owner, node_entity.pk)
                updated_values = {**values}
                if kind == "knowledge":
                    updated_values["definition"] = "精确知识点修订"
                else:
                    updated_values["name"] += "修订"
                updated = self.save_node(kind, updated_values, stable_id=node["stable_id"],
                    expected_context=detail["edit_context"])
                self.accept(node_entity, updated["revision_id"])
                filtered = knowledge.index_data(self.owner, self.household.pk,
                    {filter_key: node["stable_id"]})["questions"]
                self.assertEqual(filtered, [])
                if kind == "method":
                    self.assertEqual(knowledge.index_data(self.owner, self.household.pk,
                        {filter_key: node["stable_id"], "method_role": role})["questions"], [])

                if kind == "method":
                    self.withdraw(link["revision_id"])

                current_link = knowledge.create_link(self.owner, self.household.pk, kind=kind,
                    node_revision_id=updated["revision_id"], question_revision_id=question["revision_id"],
                    role=role, request_key=request_key(), reason="新节点版本关系")
                current_link_entity = EntityRecord.objects.get(household=self.household,
                    kind={"knowledge": "knowledge_question", "method": "method_question",
                        "question_type": "question_type_link"}[kind], stable_id=current_link["stable_id"])
                self.accept(current_link_entity, current_link["revision_id"])
                filtered = knowledge.index_data(self.owner, self.household.pk,
                    {filter_key: node["stable_id"]})["questions"]
                self.assertEqual([row["entity"].pk for row in filtered], [question_entity.pk])

                self.withdraw(current_link["revision_id"])
                filtered = knowledge.index_data(self.owner, self.household.pk,
                    {filter_key: node["stable_id"]})["questions"]
                self.assertEqual(filtered, [])

    def test_index_combines_material_node_number_review_and_method_role_filters(self):
        question = self.question()
        alternate = materials.create_material(self.owner, self.household.pk, self.material.title, request_key())
        page_id = materials.upload_page(self.owner, alternate.pk,
            SimpleUploadedFile("alternate.png", synthetic_png(), content_type="image/png"), request_key())["page_id"]
        preview = materials.preview_file(self.owner, page_id, 0)
        alternate_source = {"page_id": page_id, "rotation": 0, "preview_sha256": preview.sha256,
            "display_bbox": [5, 5, 60, 45]}
        other_question = materials.save_question(self.owner, alternate.pk, printed_text="6 + 7 = ?",
            original_number="ALT-2", sources=[alternate_source], request_key=request_key(), reason="另一份合成题目")
        question_entities = []
        for saved in (question, other_question):
            entity = EntityRecord.objects.get(household=self.household, kind="question",
                stable_id=saved["question_id"])
            self.accept(entity, saved["revision_id"])
            question_entities.append(entity)

        knowledge_node = self.save_node("knowledge", {"definition": "同名知识点",
            "conditions": "", "common_errors": ""})
        method = self.save_node("method", {"name": "同名方法", "conditions": "", "steps": "", "notes": ""})
        question_type = self.save_node("question_type", {"name": "同名题型",
            "structural_features": "", "conditions": ""})
        for kind, saved in (("knowledge", knowledge_node), ("method", method), ("question_type", question_type)):
            entity = EntityRecord.objects.get(household=self.household, kind=kind, stable_id=saved["stable_id"])
            self.accept(entity, saved["revision_id"])
        relations = (
            ("knowledge", knowledge_node, question, "applies"),
            ("question_type", question_type, question, "belongs"),
            ("method", method, question, "primary"),
            ("method", method, other_question, "auxiliary"),
        )
        for kind, node, target_question, role in relations:
            link = knowledge.create_link(self.owner, self.household.pk, kind=kind,
                node_revision_id=node["revision_id"], question_revision_id=target_question["revision_id"],
                role=role, request_key=request_key(), reason="精确检索关系")
            link_kind = {"knowledge": "knowledge_question", "method": "method_question",
                "question_type": "question_type_link"}[kind]
            self.accept(EntityRecord.objects.get(household=self.household, kind=link_kind,
                stable_id=link["stable_id"]), link["revision_id"])

        composite = {"material_id": str(self.material.pk), "knowledge_id": knowledge_node["stable_id"],
            "method_id": method["stable_id"], "method_role": "primary",
            "question_type_id": question_type["stable_id"], "number": "J1-1", "review": "accepted"}
        rows = knowledge.index_data(self.owner, self.household.pk, composite)["questions"]
        self.assertEqual([row["entity"].pk for row in rows], [question_entities[0].pk])
        rows = knowledge.index_data(self.owner, self.household.pk,
            {"material_id": str(alternate.pk), "method_id": method["stable_id"],
                "method_role": "auxiliary", "number": "ALT-2", "review": "accepted"})["questions"]
        self.assertEqual([row["entity"].pk for row in rows], [question_entities[1].pk])
        self.assertEqual(knowledge.index_data(self.owner, self.household.pk,
            {**composite, "material_id": str(alternate.pk)})["questions"], [])

        home = knowledge.index_data(self.owner, self.household.pk)
        form = IndexForm({"household_id": str(self.household.pk)},
            households=[HouseholdMember.objects.get(household=self.household, user=self.owner)],
            household_id=str(self.household.pk), nodes=home["nodes"], materials=home["materials"])
        material_choices = dict(form.fields["material_id"].choices)
        self.assertIn(str(self.material.pk), material_choices[str(self.material.pk)])
        self.assertIn(str(alternate.pk), material_choices[str(alternate.pk)])
        method_choices = dict(form.fields["method_id"].choices)
        self.assertIn(method["stable_id"][-8:], method_choices[method["stable_id"]])

        foreign_owner = get_user_model().objects.create_user(username=f"foreign-{uuid.uuid4().hex[:8]}")
        foreign_household = core.create_household(foreign_owner, f"foreign-{uuid.uuid4().hex}")
        foreign_material = materials.create_material(foreign_owner, foreign_household.pk, "同名资料", request_key())
        with self.assertRaises(core.PersistenceError) as caught:
            knowledge.index_data(self.owner, self.household.pk, {"material_id": str(foreign_material.pk)})
        self.assertEqual(caught.exception.code, "not_found")
        with self.assertRaises(core.PersistenceError) as caught:
            knowledge.index_data(self.owner, self.household.pk, {"method_role": "primary"})
        self.assertEqual(caught.exception.code, "invalid_input")

    def test_material_filter_follows_region_anchor_after_reviewed_erratum_on_merge(self):
        first = self.question()
        second_material = materials.create_material(self.owner, self.household.pk, "勘误用的另一资料", request_key())
        second = self.question(second_material, printed_text="另一题", original_number="J2-1")
        merge_sources = [first["revision_id"], second["revision_id"]]
        merge_context = catalogue.prepare_context(self.owner, self.household.pk, "merge", merge_sources)
        merged = catalogue.merge_questions(self.owner, self.household.pk, source_revision_ids=merge_sources,
            context_token=merge_context, original_number="J1-1+J2-1", printed_text="合题印刷错误",
            reason="为勘误准备合成题", request_key=request_key())
        question_revision = RevisionRecord.objects.get(pk=merged["target_revision_ids"][0])
        self.assertTrue(QuestionLabel.objects.filter(revision=question_revision,
            original_number="J1-1+J2-1").exists())
        self.assertFalse(QuestionSource.objects.filter(revision=question_revision).exists())

        erratum_result = printing.save_erratum(self.owner, self.household.pk, question_revision.pk,
            corrected_text="合题订正后的题干", basis="核对两份合成资料", expected=records.edit_context(question_revision),
            request_key=request_key())
        erratum = RevisionRecord.objects.get(pk=erratum_result["revision_id"])
        self.accept(erratum.entity, erratum.pk)
        applied = printing.apply_erratum(self.owner, self.household.pk, erratum.pk,
            expected=records.edit_context(question_revision), request_key=request_key())

        current = RevisionRecord.objects.get(pk=applied["revision_id"])
        self.assertEqual(current.payload["working_text"], "合题订正后的题干")
        self.assertTrue(QuestionLabel.objects.filter(revision=current,
            original_number="J1-1+J2-1").exists())
        self.assertFalse(QuestionSource.objects.filter(revision=current).exists())
        old_regions = set(EvidenceRecord.objects.filter(source=question_revision).values_list("region_id", flat=True))
        current_regions = set(EvidenceRecord.objects.filter(source=current).values_list("region_id", flat=True))
        self.assertEqual(current_regions, old_regions)

        for material in (self.material, second_material):
            rows = knowledge.index_data(self.owner, self.household.pk,
                {"material_id": str(material.pk)})["questions"]
            self.assertIn(current.entity_id, {row["entity"].pk for row in rows})

    def test_material_filter_follows_split_and_mixed_material_merge_region_anchors(self):
        first = self.question(original_number="J1-1")
        second_material = materials.create_material(self.owner, self.household.pk, "另一合成资料", request_key())
        second = self.question(second_material, printed_text="另一题", original_number="J2-1")

        merge_sources = [first["revision_id"], second["revision_id"]]
        merge_context = catalogue.prepare_context(self.owner, self.household.pk, "merge", merge_sources)
        merged = catalogue.merge_questions(self.owner, self.household.pk, source_revision_ids=merge_sources,
            context_token=merge_context, original_number="J1-1+J2-1", printed_text="两份资料合成题",
            reason="合成跨资料合题", request_key=request_key())
        merged_revision = RevisionRecord.objects.get(pk=merged["target_revision_ids"][0])
        self.assertFalse(QuestionSource.objects.filter(revision=merged_revision).exists())
        self.assertTrue(QuestionLabel.objects.filter(revision=merged_revision,
            original_number="J1-1+J2-1").exists())

        merged_entity_id = merged_revision.entity_id
        split_context = catalogue.prepare_context(self.owner, self.household.pk, "split",
            [merged_revision.pk])
        split = catalogue.split_question(self.owner, self.household.pk, source_revision_id=merged_revision.pk,
            context_token=split_context, children=[
                {"original_number": "J1-1+J2-1(a)", "printed_text": "子题甲"},
                {"original_number": "J1-1+J2-1(b)", "printed_text": "子题乙"},
            ], reason="拆分无单一资料的合题", request_key=request_key())
        self.assertFalse(QuestionSource.objects.filter(revision_id__in=split["target_revision_ids"]).exists())
        split_question_entities = {EntityRecord.objects.get(household=self.household, kind="question",
            stable_id=stable_id).pk for stable_id in split["target_question_ids"]}

        for material in (self.material, second_material):
            rows = knowledge.index_data(self.owner, self.household.pk,
                {"material_id": str(material.pk)})["questions"]
            self.assertIn(merged_entity_id, {row["entity"].pk for row in rows})
            self.assertTrue(split_question_entities.issubset({row["entity"].pk for row in rows}))

    def test_material_filter_does_not_infer_cross_material_match_from_shared_image(self):
        first = self.question()
        second_material = materials.create_material(self.owner, self.household.pk, "同图另一资料", request_key())
        second = self.question(second_material, original_number="J2-1")
        first_revision = RevisionRecord.objects.get(pk=first["revision_id"])
        second_revision = RevisionRecord.objects.get(pk=second["revision_id"])
        first_evidence = EvidenceRecord.objects.get(source=first_revision)
        second_evidence = EvidenceRecord.objects.get(source=second_revision)
        self.assertEqual(first_evidence.image.sha256, second_evidence.image.sha256)
        self.assertNotEqual(first_evidence.region_id, second_evidence.region_id)

        rows = knowledge.index_data(self.owner, self.household.pk,
            {"material_id": str(self.material.pk)})["questions"]
        self.assertEqual([row["entity"].stable_id for row in rows], [first["question_id"]])

    def test_material_filter_keeps_whole_image_question_unknown_without_region_anchor(self):
        saved = self.question()
        bundle = core.read_snapshot_bundle(self.owner, self.household.pk)
        question = next(item for item in bundle.questions if item.question_id == saved["question_id"])
        previous = question.revisions[-1]
        image = next(item for item in bundle.images if item.image_id == previous.evidence_refs[0].image_id)
        whole_image = EvidenceRef(self.household.pk, image.image_id, image.sha256,
            Granularity.WHOLE_IMAGE, None, None, True, EvidencePurpose.QUESTION, 1, ("region_missing",))
        current = seal_revision(replace(previous,
            header=records.header(self.owner, question.question_id, "来源区域仍未知",
                RevisionRecord.objects.get(pk=previous.header.revision_id)),
            review_state=ReviewState.DRAFT, evidence_refs=(whole_image,)))
        updated_question = replace(question, revisions=(*question.revisions, current))
        updated_bundle = replace(bundle, questions=tuple(updated_question if item.question_id == question.question_id
            else item for item in bundle.questions))
        core.stage_bundle(self.owner, updated_bundle, request_key=request_key(), expected_heads={
            ObjectKey("question", question.question_id): previous.header.revision_id})

        current_record = RevisionRecord.objects.get(pk=current.header.revision_id)
        evidence = EvidenceRecord.objects.get(source=current_record)
        self.assertIsNone(evidence.region_id)
        self.assertEqual(evidence.image_id, EvidenceRecord.objects.get(source_id=saved["revision_id"]).image_id)
        self.assertTrue(QuestionSource.objects.filter(material=self.material,
            revision_id=saved["revision_id"]).exists())
        rows = knowledge.index_data(self.owner, self.household.pk,
            {"material_id": str(self.material.pk)})["questions"]
        self.assertEqual(rows, [])
