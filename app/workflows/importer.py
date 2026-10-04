"""Apply a human-confirmed structured proposal via existing native services."""
from app.persistence.models import EntityRecord, RevisionRecord
from app.persistence import services as core
from app.web import services as materials, knowledge_services as knowledge, learning_services as learning
from app.printing import services as printing
from .exchange import fail
from .assets import FIELDS as DIAGRAM_FIELDS, validate_records

FIELDS = {
    "question": {"printed_text", "original_number", "sources", "display_markup", "image_print_confirmed"},
    "knowledge": {"definition", "conditions", "common_errors", "display_markup", "sources"},
    "method": {"name", "conditions", "steps", "notes", "sources"},
    "question_type": {"name", "structural_features", "conditions", "sources"},
    "answer": {"question", "body", "formulas", "basis"},
    "link": {"question", "node", "role"},
    "observation": {"sources", "legibility", "notes"},
    "diagram": DIAGRAM_FIELDS,
}


def apply(actor, job, reason):
    hid = job.material.household_id
    pages = {str(page.pk): page for page in job.material.pages.select_related("image")}
    sources = {row["id"]: pages[row["page_id"]] for row in job.input["sources"]}
    for page in sources.values():
        materials.asset_path(page.image.payload["storage_key"], page.image.sha256)
    mapping = {}
    assets = validate_records(job.input["records"], job.input.get("assets", {}))
    # Explicit topological order. Local IDs cannot refer to another input/job.
    order = {kind: index for index, kind in enumerate(("question", "knowledge", "method", "question_type", "observation", "answer", "diagram", "link"))}
    for row in sorted(job.input["records"], key=lambda item: order[item["kind"]]):
        kind, data = row["kind"], row["data"]
        if set(data) - FIELDS[kind]:
            fail("条目包含未实现字段；保留输入并拒绝确认，不静默丢弃。")
        key = "workflow-" + core._digest({"job": str(job.pk), "item": row["id"]})
        refs = []
        for ref in data.get("sources", []):
            page = sources[ref["source_id"]]
            preview = materials.preview_file(actor, str(page.pk), 0)
            refs.append({"page_id": str(page.pk), "rotation": 0,
                         "preview_sha256": preview.sha256, "display_bbox": ref["bbox"]})
        if kind == "question":
            result = materials.save_question(actor, job.material_id, printed_text=data.get("printed_text"),
                original_number=data.get("original_number", ""), sources=refs, request_key=key,
                reason=reason, display_markup=data.get("display_markup"),
                image_print_confirmed=data.get("image_print_confirmed"), confirm=True)
        elif kind in knowledge.NODE_TYPES:
            result = knowledge.save_node(actor, hid, kind, data={**data, "sources": refs},
                                         request_key=key, reason=reason)
            entity = EntityRecord.objects.get(household_id=hid, kind=kind, stable_id=result["stable_id"])
            _accept(actor, entity, result["revision_id"], reason, key)
        elif kind == "observation":
            # Text extraction does not establish authorship, date, or mastery.
            result = learning.save_observation(actor, hid, sources=refs,
                legibility=data.get("legibility", "unknown"), author_state="unknown",
                actual_date_state="unknown", notes=data.get("notes", ""),
                reason=reason, request_key=key)
        elif kind == "answer":
            question = _ref(mapping, data.get("question"), "question")
            revision = RevisionRecord.objects.get(pk=question["revision_id"], entity__household_id=hid)
            result = printing.save_answer(actor, hid, revision.pk, body=data.get("body"),
                formulas=data.get("formulas", []), basis=data.get("basis"),
                expected=printing.answer_context(revision), request_key=key, confirm=True)
        elif kind == "diagram":
            from django.core.files.uploadedfile import SimpleUploadedFile
            from app.printing import diagram_services
            from app.web.models import QuestionSource
            question = _ref(mapping, data["question"], "question")
            revision = RevisionRecord.objects.get(pk=question["revision_id"], entity__household_id=hid)
            source = data["source"]
            page = sources[source["source_id"]]
            region = next((ref for ref in QuestionSource.objects.get(revision=revision).sources
                if ref["page_id"] == str(page.pk) and ref["original_bbox"] == source["bbox"]), None)
            if region is None:
                fail("教学图缺少精确题目来源区域。")
            result = diagram_services.save_diagram(actor, revision.pk, placement=data["placement"],
                png_upload=SimpleUploadedFile(data["png_asset"], assets[data["png_asset"]]),
                vector_upload=SimpleUploadedFile(data["vector_asset"], assets[data["vector_asset"]]),
                source_region_id=region["region_revision_id"],
                **{name: data[name] for name in ("alt", "conditions", "width_points", "min_label_points", "independent_safe", "basis")},
                expected=diagram_services.diagram_context(revision), request_key=key)
        else:
            question = _ref(mapping, data.get("question"), "question")
            node = mapping.get(data.get("node"))
            if not node or node["kind"] not in knowledge.NODE_TYPES:
                fail("关联节点不在本次输入内。")
            result = knowledge.create_link(actor, hid, kind=node["kind"],
                question_revision_id=question["revision_id"], node_revision_id=node["revision_id"],
                role=data.get("role"), reason=reason, request_key=key)
            entity = EntityRecord.objects.get(household_id=hid, kind=result["kind"], stable_id=result["stable_id"])
            _accept(actor, entity, result["revision_id"], reason, key)
        mapping[row["id"]] = {**result, "kind": kind}
    return mapping


def _ref(mapping, identity, kind):
    row = mapping.get(identity)
    if not row or row["kind"] != kind:
        fail("本地关联身份缺失或类型不匹配。")
    return row


def _accept(actor, entity, revision_id, reason, key):
    context = core.review_context(actor, entity.household_id, revision_id)
    core.review_revision(actor, entity.household_id, revision_id, action="accept", reason=reason,
        expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
        expected_decision_id=context["expected_decision_id"], request_key=key + "-accept")
