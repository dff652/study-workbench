"""One human content confirmation, retaining native versions and source evidence."""
from django.db import transaction
from django.db.models import F, Q
from django.urls import reverse

from app.persistence import services as core
from app.persistence.models import EntityRecord, RevisionRecord
from app.printing import services as printing
from app.printing.models import TeacherAnswerRevision
from app.web import services as materials, knowledge_services as knowledge, records, page_reading
from app.web.models import QuestionSource, MaterialPage
from app.workflows import services as workflows, importer

NODE_FIELDS = {kind: importer.FIELDS[kind] - {"sources", "display_markup"}
               for kind in knowledge.NODE_TYPES}


def _context(material):
    return {"source_stamp": workflows.stamp(material)}


def _begin(actor, material, value, action, *, checked_required=True):
    reason = materials._text(value.get("reason"), 1000)
    if checked_required and value.get("checked") is not True:
        raise ValueError("请明确核对并确认内容。")
    key = materials._text(value.get("request_key"), 160)
    fingerprint = core._digest({"action": action, "material": str(material.pk), "input": value})
    replay = core._replay(material.household, actor, key, "web_record", fingerprint)
    if replay is None and value.get("expected") != _context(material):
        raise core.PersistenceError("stale_context", "资料内容、答案或来源已变化，请重新打开。")
    return reason, key, fingerprint, replay


def sources(actor, material, rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 30:
        raise ValueError("请选择来源区域。")
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"page_id", "bbox"}:
            raise ValueError("来源字段无效。")
        page = MaterialPage.objects.select_related("image").get(pk=row["page_id"], material=material)
        box = row["bbox"]
        if (not isinstance(box, list) or len(box) != 4 or any(type(n) is not int for n in box)
                or not 0 <= box[0] < box[2] <= page.image.payload["width"]
                or not 0 <= box[1] < box[3] <= page.image.payload["height"]):
            raise ValueError("请使用有效的原图整数坐标。")
        preview = materials.preview_file(actor, page.pk, 0)
        result.append({"page_id": str(page.pk), "rotation": 0,
                       "preview_sha256": preview.sha256, "display_bbox": box})
    return result


@transaction.atomic
def detail(actor, material_id):
    material = materials._material(actor, material_id)
    questions = []
    metadata = QuestionSource.objects.filter(material=material,
        revision_id=F("revision__entity__head_revision_id")).select_related(
            "revision__entity", "revision__review_projection").order_by("original_number", "revision_id")
    for item in metadata:
        revision = item.revision
        answer = TeacherAnswerRevision.objects.filter(question_revision=revision).order_by("-revision_no").first()
        decision = answer.decisions.order_by("-pk").first() if answer else None
        questions.append({"id": revision.entity.stable_id, "revision_id": revision.pk,
            "number": item.original_number, "printed_text": revision.payload.get("printed_text") or "",
            "working_text": revision.payload.get("working_text") or "",
            "missing_fields": revision.payload.get('missing_fields', []),
            "sources_ready": bool(revision.payload.get('evidence_refs')) and not any(
                ref.get('region_missing') or ref.get('gaps') for ref in revision.payload.get('evidence_refs', [])),
            "sources": [{"page_id": ref["page_id"], "bbox": ref["original_bbox"]} for ref in item.sources],
            "confirmed": revision.entity.published_revision_id == revision.pk and revision.review_projection.state == "accepted",
            "answer": {"body": answer.body, "formulas": answer.formulas, "basis": answer.basis,
                       "confirmed": bool(decision and decision.action == "accepted")} if answer else None,
            "edit_context": materials._edit_context(revision),
            "question_url": reverse("knowledge:question_detail", args=[revision.entity.pk])})
    links = knowledge._links_for_question(actor, material.household_id, [row["revision_id"] for row in questions])
    node_ids = {row["node"].pk for linked in links.values() for row in linked if row["current"]}
    image_ids = material.pages.values_list("image_id", flat=True)
    nodes = EntityRecord.objects.filter(household=material.household, kind__in=knowledge.NODE_TYPES,
        published_revision_id=F("head_revision_id"), published_revision__review_projection__state="accepted").filter(
            Q(pk__in=node_ids) | Q(head_revision__evidence__image_id__in=image_ids)).distinct().select_related("head_revision")
    return {"context": _context(material), "questions": questions,
        "nodes": [{"id": node.stable_id, "kind": node.kind,
                   "label": (node.head_revision.payload.get("name") or node.head_revision.payload.get("definition") or "待补名称")[:120],
                   "node_url": reverse("knowledge:node_detail", args=[node.pk])} for node in nodes]}


@transaction.atomic
def save(actor, material_id, value):
    material = materials._material(actor, material_id, write=True)
    reason, key, fingerprint, replay = _begin(actor, material, value, "content-confirm")
    if replay is not None:
        return replay
    child = "content-" + core._digest(key)
    refs = sources(actor, material, value.get("sources"))
    question_id = value.get("question_id")
    expected = None
    unchanged = False
    if question_id:
        entity = EntityRecord.objects.get(household=material.household, kind="question", stable_id=question_id)
        metadata = QuestionSource.objects.get(material=material, revision=entity.head_revision)
        expected = materials._edit_context(entity.head_revision)
        unchanged = (entity.published_revision_id == entity.head_revision_id
            and entity.head_revision.review_projection.state == "accepted"
            and entity.head_revision.payload.get("printed_text") == value.get("printed_text")
            and metadata.original_number == value.get("original_number", "")
            and [{"page_id": ref["page_id"], "bbox": ref["original_bbox"]} for ref in metadata.sources] == value.get("sources"))
    if unchanged:
        result = {"question_id": question_id, "revision_id": entity.head_revision_id}
    else:
        result = materials.save_question(actor, material.pk, printed_text=value.get("printed_text"),
            original_number=value.get("original_number", ""), sources=refs, request_key=child + "-question",
            reason=reason, question_id=question_id, expected_context=expected, confirm=True)
    revision = RevisionRecord.objects.get(pk=result["revision_id"])
    answer = value.get("answer")
    if answer is not None:
        if not isinstance(answer, dict) or set(answer) != {"body", "formulas", "basis"}:
            raise ValueError("答案字段无效。")
        printing.save_answer(actor, material.household_id, revision.pk, **answer,
            expected=printing.answer_context(revision), request_key=child + "-answer", confirm=True)
    nodes = value.get("nodes", [])
    if not isinstance(nodes, list) or len(nodes) > 3:
        raise ValueError("一次最多三个新节点。")
    for index, row in enumerate(nodes):
        if not isinstance(row, dict) or set(row) != {"kind", "data"} or row["kind"] not in NODE_FIELDS:
            raise ValueError("知识节点字段无效。")
        kind, data = row["kind"], row["data"]
        if not isinstance(data, dict) or set(data) - NODE_FIELDS[kind]:
            raise ValueError("知识内容字段無效。")
        saved = knowledge.save_node(actor, material.household_id, kind, data={**data, "sources": refs},
            reason=reason, request_key=f"{child}-node-{index}")
        entity = EntityRecord.objects.get(household=material.household, kind=kind, stable_id=saved["stable_id"])
        importer._accept(actor, entity, saved["revision_id"], reason, f"{child}-node-{index}")
        link = knowledge.create_link(actor, material.household_id, kind=kind,
            node_revision_id=saved["revision_id"], question_revision_id=revision.pk,
            role={"knowledge": "applies", "method": "primary", "question_type": "belongs"}[kind],
            reason=reason, request_key=f"{child}-link-{index}")
        entity = EntityRecord.objects.get(household=material.household, kind=link["kind"], stable_id=link["stable_id"])
        importer._accept(actor, entity, link["revision_id"], reason, f"{child}-link-{index}")
    return core._receipt(material.household, actor, key, "web_record", fingerprint, result)


@transaction.atomic
def draft(actor, material_id, value):
    material = materials._material(actor, material_id, write=True)
    reason, key, fingerprint, replay = _begin(actor, material, value, "content-draft", checked_required=False)
    if replay is not None:
        return replay
    question_id = value.get("question_id")
    expected = None
    if question_id:
        entity = EntityRecord.objects.get(household=material.household, kind="question", stable_id=question_id)
        QuestionSource.objects.get(material=material, revision=entity.head_revision)
        expected = materials._edit_context(entity.head_revision)
    result = materials.save_question(actor, material.pk, printed_text=value.get("printed_text", ""),
        original_number=value.get("original_number", ""), sources=sources(actor, material, value.get("sources")),
        reason=reason, question_id=question_id, expected_context=expected,
        request_key="content-draft-" + core._digest(key), confirm=False)
    return core._receipt(material.household, actor, key, "web_record", fingerprint, result)


@transaction.atomic
def erratum(actor, material_id, value):
    material = materials._material(actor, material_id, write=True)
    reason, key, fingerprint, replay = _begin(actor, material, value, "content-erratum")
    if replay is not None:
        return replay
    child = "content-" + core._digest(key)
    entity = EntityRecord.objects.get(household=material.household, kind="question", stable_id=value.get("question_id"))
    row = entity.head_revision
    QuestionSource.objects.get(material=material, revision=row)
    saved = printing.save_erratum(actor, material.household_id, row.pk,
        corrected_text=value.get("corrected_text"), basis=value.get("basis"),
        expected=records.edit_context(row), request_key=child + "-erratum")
    err = EntityRecord.objects.get(household=material.household, kind="erratum", stable_id=saved["erratum_id"])
    importer._accept(actor, err, saved["revision_id"], reason, child + "-erratum")
    result = printing.apply_erratum(actor, material.household_id, saved["revision_id"],
        expected=records.edit_context(row), request_key=child + "-apply")
    entity.refresh_from_db()
    importer._accept(actor, entity, result["revision_id"], reason, child + "-question")
    result["erratum_revision_id"] = saved["revision_id"]
    return core._receipt(material.household, actor, key, "web_record", fingerprint, result)


def reading_row(row):
    return {"reading": row.reading, "coverage": row.coverage,
        "partitions": [{"kind": part["kind"], "bbox": part["original_bbox"]} for part in row.partitions],
        "pending_items": [item.strip() for item in row.pending_items.splitlines() if item.strip()], "basis": row.basis,
        "revision_no": row.revision_no, "recorded_at": row.created_at}


def reading_detail(actor, page_id):
    data = page_reading.detail(actor, page_id)
    return {"context": data["context"], "current": reading_row(data["history"][0]) if data["history"] else None,
            "history": [reading_row(row) for row in data["history"]]}


@transaction.atomic
def reading_save(actor, page_id, value):
    page = MaterialPage.objects.select_related("image", "material").get(pk=page_id)
    records.household(actor, page.material.household_id, write=True)
    partitions = value.get("partitions")
    if not isinstance(partitions, list) or len(partitions) > 100:
        raise ValueError("分区数量无效。")
    refs = []
    pending = value.get("pending_items", [])
    if (not isinstance(pending, list) or len(pending) > 100
            or any(not isinstance(item, str) or not item.strip() or len(item) > 1000 for item in pending)):
        raise ValueError("待补事项须为明确文本列表。")
    for part in partitions:
        if not isinstance(part, dict) or set(part) != {"kind", "bbox"}:
            raise ValueError("分区字段无效。")
        ref = sources(actor, page.material, [{"page_id": str(page.pk), "bbox": part["bbox"]}])[0]
        refs.append({**ref, "kind": part["kind"]})
    return page_reading.save(actor, page.pk, reading=value.get("reading"), coverage=value.get("coverage"),
        sources=refs, pending_items="\n".join(pending), basis=value.get("basis"),
        expected=value.get("expected"), request_key=value.get("request_key"))
