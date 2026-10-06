"""Household-scoped manual knowledge, method, type and exact question links."""
from dataclasses import replace
import json
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import F

from app.domain import (
    KnowledgeItem, KnowledgeRevision, KnowledgeQuestionLinkRevision, Method, MethodRevision,
    MethodQuestionLinkRevision, QuestionType, QuestionTypeRevision, QuestionTypeLinkRevision,
    ReviewState, seal_revision,
)
from app.domain.contracts import EvidencePurpose
from app.domain.presentation import validate_display
from app.imports.models import LegacyIndexEntry
from app.catalogue.models import QuestionLabel
from app.persistence import services as core
from app.persistence.adapter import ObjectKey
from app.persistence.models import EntityRecord, EvidenceRecord, HouseholdMember, ImageRecord, RevisionDependency, RevisionRecord
from . import records
from .models import MaterialPage, MaterialSet, PagePreview, QuestionSource


NODE_TYPES = {
    "knowledge": ("knowledge_items", "knowledge_id", KnowledgeItem, "knowledge_question_links",
                  "knowledge_question", "knowledge_revision_id", "link_knowledge", KnowledgeQuestionLinkRevision),
    "method": ("methods", "method_id", Method, "method_question_links",
               "method_question", "method_revision_id", "link_method", MethodQuestionLinkRevision),
    "question_type": ("question_types", "question_type_id", QuestionType, "question_type_links",
                      "question_type_link", "question_type_revision_id", "link_question_type", QuestionTypeLinkRevision),
}
NODE_TITLES = {"knowledge": "知识点", "method": "方法", "question_type": "题型"}


def _required(value, name, limit):
    if not isinstance(value, str) or "\x00" in value or len(value) > limit or not value.strip():
        raise core.PersistenceError("invalid_input", f"{name}不能为空且不能超过 {limit} 个字符。")
    return value.strip()


def _optional(value, name, limit):
    if value is None:
        return ""
    if not isinstance(value, str) or "\x00" in value or len(value) > limit:
        raise core.PersistenceError("invalid_input", f"{name}不能超过 {limit} 个字符。")
    return value.strip()


def _lines(value, name, limit):
    text = _optional(value, name, limit)
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def _typed_node(bundle, kind, stable_id):
    field, id_field, _cls, *_ = NODE_TYPES[kind]
    return next((item for item in getattr(bundle, field) if getattr(item, id_field) == stable_id), None)


def _node_previous(bundle, kind, stable_id, revision_id=None):
    item = _typed_node(bundle, kind, stable_id)
    if item is None:
        return None, None
    if revision_id:
        revision = next((row for row in item.revisions if row.header.revision_id == revision_id), None)
    else:
        revision = item.revisions[-1] if item.revisions else None
    return item, revision


def _revision_for(bundle, kind, revision_id):
    for node_kind, (field, _id_field, _cls, *_rest) in NODE_TYPES.items():
        for item in getattr(bundle, field):
            for revision in item.revisions:
                if revision.header.revision_id == revision_id:
                    return node_kind, item, revision
    for item in bundle.questions:
        for revision in item.revisions:
            if revision.header.revision_id == revision_id:
                return "question", item, revision
    return None


def _parse_source_json(sources):
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except (TypeError, ValueError) as exc:
            raise core.PersistenceError("invalid_region", "来源区域数据无效，请重新选择。") from exc
    if not isinstance(sources, list):
        raise core.PersistenceError("invalid_region", "来源区域列表无效。")
    return sources


def _merge_source_refs(old_refs, new_refs, replace_sources):
    refs = tuple(new_refs) if replace_sources else (*old_refs, *new_refs)
    if len(refs) > 30:
        raise core.PersistenceError("invalid_region", "一个修订最多保留 30 个来源区域。")
    return tuple(replace(ref, sequence=index) for index, ref in enumerate(refs, 1))


@transaction.atomic
def save_node(actor, household_id, kind, *, data, request_key, reason, stable_id=None,
              expected_context=None):
    if kind not in NODE_TYPES:
        raise core.PersistenceError("invalid_input", "节点类型无效。")
    household = records.household(actor, household_id, write=True)
    reason = _required(reason, "修订说明", 1000)
    sources = _parse_source_json(data.get("sources", []))
    replace_sources = bool(data.get("replace_sources", False))
    if kind == "knowledge":
        content = {
            "definition": _required(data.get("definition"), "定义、公式与例题", 20000),
            "display_markup": _optional(data.get("display_markup", ""), "公式与重点排版", 24000) or None,
            "conditions": _lines(data.get("conditions", ""), "适用条件", 6000),
            "common_errors": _lines(data.get("common_errors", ""), "易错点", 6000),
        }
    elif kind == "method":
        content = {
            "name": _required(data.get("name"), "方法名称", 200),
            "conditions": _lines(data.get("conditions", ""), "适用条件", 6000),
            "steps": _lines(data.get("steps", ""), "步骤", 12000),
            "notes": _lines(data.get("notes", ""), "备注", 6000),
            "parent_revision_id": _optional(data.get("parent_revision_id", ""), "上级方法修订", 160) or None,
        }
    else:
        content = {
            "name": _required(data.get("name"), "题型名称", 200),
            "structural_features": _lines(data.get("structural_features", ""), "结构特征", 6000),
            "conditions": _lines(data.get("conditions", ""), "适用条件", 6000),
        }

    creating = stable_id is None

    fingerprint_content = dict(content)
    if kind == "knowledge" and content["display_markup"] is None:
        fingerprint_content.pop("display_markup")
    normalized = {
        "household": household.pk, "kind": kind, "stable_id": stable_id,
        "content": fingerprint_content, "sources": sources, "replace_sources": replace_sources,
        "reason": reason, "expected_context": expected_context,
    }

    def build(bundle):
        owner_id = stable_id or f"web-{kind}-{uuid4().hex}"
        revision_id=None
        expected_heads={}
        if not creating:
            row=records.entity(household.pk,kind,stable_id)
            if row.head_revision_id is None:
                raise core.PersistenceError('missing_revision','节点没有可修订的当前版本。')
            if not isinstance(expected_context,dict):
                raise core.PersistenceError('stale_context','修订凭据缺失或已过期，请重新打开节点。')
            expected_heads=records.check_edit(row.head_revision,expected_context)
            revision_id=row.head_revision_id
        expected = expected_heads if not creating else {ObjectKey(kind, owner_id): None}
        item, previous_domain = _node_previous(bundle, kind, owner_id, revision_id)
        if revision_id and (item is None or previous_domain is None):
            raise core.PersistenceError("head_conflict", "节点版本已变化，请重新打开。")
        previous_record = records.entity(household.pk, kind, owner_id).head_revision if revision_id else None
        source_regions, selected_refs = records.source_refs(
            actor, household.pk, sources, purpose=EvidencePurpose.DEFINITION)
        old_refs = previous_domain.source_refs if previous_domain and not replace_sources else ()
        refs = _merge_source_refs(old_refs, selected_refs, replace_sources)
        header = records.header(actor, owner_id, reason, previous_record)
        if kind == "knowledge":
            try:
                validate_display(content["display_markup"], content["definition"], refs)
            except (TypeError, ValueError) as exc:
                raise core.PersistenceError("invalid_input", str(exc)) from exc
            revision = seal_revision(KnowledgeRevision(header, ReviewState.DRAFT,
                content["definition"], content["conditions"], content["common_errors"], refs,
                display_markup=content["display_markup"]))
        elif kind == "method":
            revision = seal_revision(MethodRevision(header, ReviewState.DRAFT,
                content["name"], content["conditions"], content["steps"], content["notes"],
                content["parent_revision_id"], refs))
        else:
            revision = seal_revision(QuestionTypeRevision(header, ReviewState.DRAFT,
                content["name"], content["structural_features"], content["conditions"], refs))
        if item is None:
            _field, id_field, cls, *_ = NODE_TYPES[kind]
            updated_item = cls(**{id_field: owner_id, "household_id": household.pk, "revisions": (revision,)})
            bundle = replace(bundle, **{NODE_TYPES[kind][0]: (*getattr(bundle, NODE_TYPES[kind][0]), updated_item)})
        else:
            updated_item = replace(item, revisions=(*item.revisions, revision))
            collection = tuple(updated_item if current == item else current for current in getattr(bundle, NODE_TYPES[kind][0]))
            bundle = replace(bundle, **{NODE_TYPES[kind][0]: collection})
        if source_regions:
            bundle = replace(bundle, regions=(*bundle.regions, *source_regions))
        return bundle, expected, {"kind": kind, "stable_id": owner_id, "revision_id": revision.header.revision_id}

    return records.command(actor, household.pk, request_key, f"knowledge_{kind}_{'create' if creating else 'edit'}",
                           normalized, build)


def _link_spec(kind):
    if kind not in NODE_TYPES:
        raise core.PersistenceError("invalid_input", "关联节点类型无效。")
    return NODE_TYPES[kind]


@transaction.atomic
def create_link(actor, household_id, *, kind, node_revision_id, question_revision_id,
                role, request_key, reason):
    household = records.household(actor, household_id, write=True)
    spec = _link_spec(kind)
    link_field, link_entity_kind, target_field, target_role, link_cls = spec[3:]
    role = _required(role, "关系类型", 40)
    if kind == "method" and role not in {"primary", "auxiliary"}:
        raise core.PersistenceError("invalid_input", "方法关联必须标为主方法或辅助方法。")
    if kind == "knowledge" and role != "applies" or kind == "question_type" and role != "belongs":
        raise core.PersistenceError("invalid_input", "关系类型与节点类型不匹配。")
    reason = _required(reason, "关联说明", 1000)
    normalized = {"household": household.pk, "kind": kind,
        "node_revision_id": node_revision_id, "question_revision_id": question_revision_id,
        "role": role, "reason": reason}

    def build(bundle):
        link_id = f"web-{link_entity_kind}-{uuid4().hex}"
        target = _revision_for(bundle, kind, node_revision_id)
        question = _revision_for(bundle, "question", question_revision_id)
        if target is None or target[0] != kind or question is None or question[0] != "question":
            raise core.PersistenceError("missing_link_reference", "所选精确版本不属于当前家庭或已不存在。")
        header = records.header(actor, link_id, reason)
        revision = seal_revision(link_cls(link_id, household.pk, header,
            question_revision_id, node_revision_id, role, ReviewState.DRAFT))
        bundle = replace(bundle, **{link_field: (*getattr(bundle, link_field), revision)})
        expected = {ObjectKey(link_entity_kind, link_id): None}
        return bundle, expected, {"kind": link_entity_kind, "stable_id": link_id, "revision_id": revision.header.revision_id}

    return records.command(actor, household.pk, request_key, "knowledge_link_create", normalized, build)


@transaction.atomic
def review_revision(actor, entity_id, revision_id, *, action, reason, context, request_key):
    row = EntityRecord.objects.select_related("household").get(pk=entity_id)
    records.household(actor, row.household_id, write=True)
    return records.review(actor, row.household_id, row.kind, row.stable_id, revision_id,
        action=action, reason=reason, context=context, request_key=request_key)


def _question_labels(household_id):
    labels = {}

    def add(entity_id, value):
        values = labels.setdefault(entity_id, [])
        if value not in values:
            values.append(value)

    for entry in LegacyIndexEntry.objects.filter(batch__household_id=household_id).select_related("question_revision__entity").order_by("ordinal"):
        add(entry.question_revision.entity_id, f"{entry.book}-{entry.number}")
    for source in QuestionSource.objects.filter(revision__entity__household_id=household_id).select_related("revision__entity"):
        if source.original_number:
            add(source.revision.entity_id, source.original_number)
    source_revision_ids = QuestionSource.objects.filter(revision__entity__household_id=household_id).exclude(
        original_number="").values_list("revision_id", flat=True)
    for label in QuestionLabel.objects.filter(revision__entity__household_id=household_id,
            revision__entity__kind="question").exclude(revision_id__in=source_revision_ids).select_related(
                "revision__entity"):
        if label.original_number:
            add(label.revision.entity_id, label.original_number)
    return labels


def _node_label(row, kind):
    payload = row.payload if row else {}
    name = payload.get("name") or (payload.get("definition", "")[:72] if kind == "knowledge" else "")
    return name or "未命名条目"


def _home_nodes(household_id):
    result = {}
    for kind, label in NODE_TITLES.items():
        result[kind] = [
            {"stable_id": row.stable_id, "entity": row, "name": _node_label(row.head_revision, kind),
             "state": row.head_revision.review_projection.state if row.head_revision_id else "draft"}
            for row in EntityRecord.objects.filter(household_id=household_id, kind=kind)
                .select_related("head_revision__review_projection", "published_revision__review_projection")
                .order_by("stable_id")
        ]
    return result


def _home_question_rows(household_id, *, practice=False):
    labels = _question_labels(household_id)
    legacy_ids = set(LegacyIndexEntry.objects.filter(batch__household_id=household_id)
        .values_list("question_revision__entity_id", flat=True))
    heads = {(kind, stable_id): revision_id for kind, stable_id, revision_id in
        EntityRecord.objects.filter(household_id=household_id).values_list("kind", "stable_id", "head_revision_id")}
    rows = EntityRecord.objects.filter(household_id=household_id, kind="question").select_related(
        "head_revision__review_projection", "published_revision__review_projection").order_by("stable_id")
    result = []
    sources_by_revision = {}
    pages = {str(page.pk): page for page in MaterialPage.objects.filter(material__household_id=household_id).select_related('material')}
    for source in QuestionSource.objects.filter(revision__entity__household_id=household_id):
        for ref in source.sources:
            page = pages.get(str(ref.get('page_id', '')))
            if page:
                sources_by_revision.setdefault(source.revision_id, []).append(f'{page.material.title} · 第 {page.position} 页')
    for entity in rows:
        current = entity.published_revision if practice else entity.head_revision
        if current is None:
            continue
        payload = current.payload
        number = ", ".join(dict.fromkeys(labels.get(entity.pk, ())))
        missing = bool(payload.get("missing_fields")) or not payload.get("evidence_refs") or any(
            ref.get("region_missing") or ref.get("gaps") for ref in payload.get("evidence_refs", ()))
        legacy = entity.pk in legacy_ids
        state = current.review_projection.state
        dependencies_changed = any(heads.get((item['kind'], item['stable_id'])) != item['head_revision_id'] for item in current.dependency_heads)
        if practice and (entity.head_revision_id != current.pk or state != 'accepted' or missing or dependencies_changed or not (payload.get('working_text') or payload.get('printed_text') or '').strip()):
            continue
        if state == "draft" and any(heads.get((item["kind"], item["stable_id"])) != item["head_revision_id"]
                                     for item in current.dependency_heads):
            state = "stale"
        result.append({"entity": entity, "revision": current, "number": number or "—",
            "title": (payload.get("working_text") or payload.get("printed_text") or
                      (f"旧索引 {number}" if legacy else "题干待补")),
            "state": state,
            "legacy": legacy, "missing": missing,
            "published_revision_id": entity.published_revision_id,
            "source_labels": list(dict.fromkeys(sources_by_revision.get(current.pk, ())))})
    return result


def _question_entities_for_node(actor, household_id, kind, stable_id, *, role=None):
    trace = core.published_trace(actor, household_id, node=ObjectKey(kind, stable_id))
    question_revision_ids = set(trace["question_revision_ids"])
    if kind == "method" and role:
        link_rows = RevisionRecord.objects.filter(
            entity__household_id=household_id, entity__kind="method_question",
            entity__published_revision_id=F("pk"),
            review_projection__state="accepted", payload__role=role,
            outgoing_dependencies__role="link_method",
            outgoing_dependencies__target_id__in=trace["node_revision_ids"],
        )
        matching_question_ids = set()
        for link_id in link_rows.values_list("pk", flat=True):
            matching_question_ids.update(RevisionDependency.objects.filter(
                source_id=link_id, role="link_question",
                target_id__in=question_revision_ids).values_list("target_id", flat=True))
        question_revision_ids.intersection_update(matching_question_ids)
    ids = set(RevisionRecord.objects.filter(pk__in=question_revision_ids,
        entity__household_id=household_id, entity__kind="question").values_list("entity_id", flat=True))
    if kind == "method":
        revision_ids = list(RevisionRecord.objects.filter(entity__household_id=household_id,
            entity__kind="method", entity__stable_id=stable_id).values_list("pk", flat=True))
        legacy = LegacyIndexEntry.objects.filter(batch__household_id=household_id).filter(
            models_Q_primary_or_aux(revision_ids, role=role))
        ids.update(legacy.values_list("question_revision__entity_id", flat=True))
    return ids


def models_Q_primary_or_aux(revision_ids, *, role=None):
    from django.db.models import Q
    if role == "primary":
        return Q(primary_method_revision_id__in=revision_ids)
    if role == "auxiliary":
        query = Q(pk__in=[])
        for revision_id in revision_ids:
            query |= Q(auxiliary_method_revision_ids__contains=[revision_id])
        return query
    query = Q(primary_method_revision_id__in=revision_ids)
    for revision_id in revision_ids:
        query |= Q(auxiliary_method_revision_ids__contains=[revision_id])
    return query


def _material_question_revision_ids(household_id, material_id, current_revision_ids, *, subject=None):
    source_rows = QuestionSource.objects.filter(
        material__household_id=household_id,
        revision__entity__household_id=household_id,
        revision__entity__kind="question")
    if material_id is not None:
        source_rows = source_rows.filter(material_id=material_id)
    if subject is not None:
        from . import subjects
        selected = subjects.classified(MaterialSet.objects.filter(household_id=household_id)).filter(school_subject=subject)
        source_rows = source_rows.filter(material_id__in=selected.values("pk"))
    source_rows = source_rows.values_list("revision_id", "sources")
    matched = set()
    region_revision_ids = set()
    for revision_id, sources in source_rows:
        if revision_id in current_revision_ids:
            matched.add(revision_id)
        if not isinstance(sources, list):
            continue
        for source in sources:
            region_revision_id = source.get("region_revision_id") if isinstance(source, dict) else None
            if isinstance(region_revision_id, str) and region_revision_id:
                region_revision_ids.add(region_revision_id)
    if region_revision_ids and current_revision_ids:
        matched.update(EvidenceRecord.objects.filter(
            source_id__in=current_revision_ids,
            source__entity__household_id=household_id,
            source__entity__kind="question",
            region_id__in=region_revision_ids,
            region__entity__household_id=household_id,
            region__entity__kind="region",
        ).values_list("source_id", flat=True))
    return matched


@transaction.atomic
def index_data(actor, household_id, filters=None):
    house = records.household(actor, household_id)
    nodes = _home_nodes(house.pk)
    filters = filters or {}
    practice = filters.get('mode') == 'learn'
    questions = _home_question_rows(house.pk, practice=practice)
    subject = filters.get("subject")
    if subject:
        from . import subjects
        subjects.validate(subject)
        current_ids = {row["revision"].pk for row in questions}
        allowed = _material_question_revision_ids(house.pk, None, current_ids, subject=subject)
        if subject == "unknown":
            assigned = _material_question_revision_ids(house.pk, None, current_ids)
            allowed.update(current_ids - assigned)
        questions = [row for row in questions if row["revision"].pk in allowed]
    material_id = str(filters.get("material_id", "")).strip()
    if material_id:
        try:
            material_key = UUID(material_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise core.PersistenceError("not_found", "资料不属于当前家庭。") from exc
        if not MaterialSet.objects.filter(pk=material_key, household=house).exists():
            raise core.PersistenceError("not_found", "资料不属于当前家庭。")
        current_revision_ids = {row["revision"].pk for row in questions}
        matching_revision_ids = _material_question_revision_ids(
            house.pk, material_key, current_revision_ids)
        questions = [row for row in questions if row["revision"].pk in matching_revision_ids]
    number = str(filters.get("number", "")).strip().casefold()
    if number:
        questions = [row for row in questions if number in row["number"].casefold()
                     or number in row["entity"].stable_id.casefold()]
    review = filters.get("review")
    if review:
        questions = [row for row in questions if row["state"] == review]
    for kind, field in (("knowledge", "knowledge_id"), ("method", "method_id"), ("question_type", "question_type_id")):
        stable_id = filters.get(field)
        if stable_id:
            if not EntityRecord.objects.filter(household=house, kind=kind, stable_id=stable_id).exists():
                raise core.PersistenceError("not_found", "筛选节点不属于当前家庭。")
            role = filters.get("method_role") if kind == "method" else None
            if role not in (None, "", "primary", "auxiliary"):
                raise core.PersistenceError("invalid_input", "方法角色筛选无效。")
            allowed = _question_entities_for_node(actor, house.pk, kind, stable_id, role=role or None)
            questions = [row for row in questions if row["entity"].pk in allowed]
    if filters.get("method_role") and not filters.get("method_id"):
        raise core.PersistenceError("invalid_input", "请先选择方法，再筛选主方法或辅助方法。")
    if filters.get("method_role") not in (None, "", "primary", "auxiliary"):
        raise core.PersistenceError("invalid_input", "方法角色筛选无效。")
    tree = method_tree_data(house.pk)
    materials = list(MaterialSet.objects.filter(household=house).order_by("title", "id"))
    can_write = HouseholdMember.objects.filter(household=house, user=actor,
        role__in=(HouseholdMember.Role.OWNER, HouseholdMember.Role.REVIEWER)).exists()
    return {"household": house, "can_write": can_write, "practice": practice, "nodes": nodes, "questions": questions,
        "method_tree": tree, "materials": materials}


@transaction.atomic
def method_revision_choices(actor, household_id, *, exclude_entity_id=None):
    house = records.household(actor, household_id)
    rows = RevisionRecord.objects.filter(entity__household=house, entity__kind="method").exclude(
        entity_id=exclude_entity_id).select_related("entity", "review_projection", "entity__published_revision")
    return [(row.pk, f"{row.payload.get('name', '未命名方法')} · r{row.revision_no} · {_state_label(row.review_projection.state)}"
             + (" · 已发布" if row.entity.published_revision_id == row.pk else ""))
            for row in rows.order_by("entity__stable_id", "revision_no")]


def _state_label(state):
    return {"draft": "待审核", "accepted": "已审核", "rejected": "已退回",
            "withdrawn": "已撤回", "stale": "依赖已变化"}.get(state, state)


@transaction.atomic
def method_tree_data(household_id):
    all_rows = list(RevisionRecord.objects.filter(entity__household_id=household_id,
        entity__kind="method").select_related("entity", "review_projection", "entity__published_revision"))
    by_id = {row.pk: row for row in all_rows}
    current = [row for row in all_rows if row.entity.head_revision_id == row.pk]
    included = {row.pk: row for row in current}
    for row in current:
        parent_id = row.payload.get("parent_revision_id")
        visited = set()
        while parent_id and parent_id not in visited and parent_id in by_id:
            visited.add(parent_id)
            included[parent_id] = by_id[parent_id]
            parent_id = by_id[parent_id].payload.get("parent_revision_id")
    children = {}
    roots = []
    for row in included.values():
        parent_id = row.payload.get("parent_revision_id")
        if parent_id in included:
            children.setdefault(parent_id, []).append(row)
        else:
            roots.append(row)
    def make(row, path):
        if row.pk in path:
            return {"row": row, "children": [], "cycle": True}
        next_path = {*path, row.pk}
        parent = by_id.get(row.payload.get("parent_revision_id"))
        return {"row": row, "children": [make(child, next_path) for child in sorted(children.get(row.pk, ()), key=lambda value: (value.payload.get("name", ""), value.entity.stable_id))],
                "current": row.entity.head_revision_id == row.pk,
                "parent_outdated": bool(parent and parent.entity.head_revision_id != parent.pk)}
    return [make(row, set()) for row in sorted(roots, key=lambda value: (value.payload.get("name", ""), value.entity.stable_id))]


def _source_cards(actor, household_id, revision):
    result = []
    for ref in revision.payload.get("source_refs",revision.payload.get("evidence_refs",())) if revision else ():
        image = ImageRecord.objects.filter(household_id=household_id, stable_id=ref.get("image_id")).first()
        if image is None:
            result.append({"ref": ref, "missing_image": True})
            continue
        region = RevisionRecord.objects.filter(pk=ref.get("region_revision_id"), entity__household_id=household_id,
            entity__kind="region").select_related("entity").first() if ref.get("region_revision_id") else None
        page = MaterialPage.objects.filter(image=image, material__household_id=household_id).select_related(
            "material").order_by("position", "id").first()
        preview = PagePreview.objects.filter(image=image, rotation=0).first()
        geometry = region.payload.get("geometry") if region else None
        overlay = ""
        if geometry and image.payload.get("width") and image.payload.get("height"):
            x0, y0, x1, y1 = geometry
            overlay = (f"left:{100*x0/image.payload['width']:.4f}%;top:{100*y0/image.payload['height']:.4f}%;"
                       f"width:{100*(x1-x0)/image.payload['width']:.4f}%;height:{100*(y1-y0)/image.payload['height']:.4f}%;")
        result.append({"ref": ref, "image": image, "page": page, "preview": preview,
            "region": region, "geometry": geometry, "overlay_style": overlay,
            "region_missing": ref.get("region_missing", False) or not geometry,
            "gaps": ref.get("gaps", ())})
    return result


def _question_card(revision, labels):
    entity = revision.entity
    number = ", ".join(dict.fromkeys(labels.get(entity.pk, ()))) or "—"
    payload = revision.payload
    legacy = entity.pk in set(LegacyIndexEntry.objects.filter(batch__household_id=entity.household_id)
        .values_list("question_revision__entity_id", flat=True))
    return {"entity": entity, "revision": revision, "number": number,
        "title": payload.get("working_text") or payload.get("printed_text") or
            (f"旧索引 {number}" if legacy else "题干待补"),
        "state": revision.review_projection.state, "legacy": legacy,
        "missing": bool(payload.get("missing_fields")) or not payload.get("evidence_refs")}


def _link_rows_for_target(actor, household_id, kind, entity):
    spec = _link_spec(kind)
    _field, _id_field, _cls, _link_field, link_entity_kind, target_field, target_role, _link_cls = spec
    trace = core.published_trace(actor, household_id, node=ObjectKey(kind, entity.stable_id))
    published_questions = set(trace["question_revision_ids"])
    published_nodes = set(trace["node_revision_ids"])
    dependencies = RevisionDependency.objects.filter(source__entity__household_id=household_id,
        source__entity__kind=link_entity_kind, role=target_role,
        target__entity_id=entity.pk).select_related("source__entity", "source__review_projection", "target__entity")
    rows = {}
    for dep in dependencies:
        link = dep.source
        qdep = link.outgoing_dependencies.filter(role="link_question").select_related(
            "target__entity", "target__review_projection").first()
        if qdep is None:
            continue
        question = qdep.target
        current = (link.entity.published_revision_id == link.pk
            and link.review_projection.state == "accepted"
            and dep.target_id in published_nodes and question.pk in published_questions)
        outdated = (link.entity.head_revision_id != link.pk
            or dep.target.entity.head_revision_id != dep.target_id
            or question.entity.head_revision_id != question.pk
            or (dep.target.entity.published_revision_id is not None
                and dep.target.entity.published_revision_id != dep.target_id)
            or (question.entity.published_revision_id is not None
                and question.entity.published_revision_id != question.pk))
        pending = (not outdated and (dep.target.entity.published_revision_id != dep.target_id
            or question.entity.published_revision_id != question.pk
            or link.review_projection.state != "accepted"))
        rows[link.pk] = {"link": link, "question_revision": question,
            "node_revision": dep.target, "current": current,
            "outdated": outdated, "pending": pending,
            "state": link.review_projection.state}
    return sorted(rows.values(), key=lambda item: (item["question_revision"].entity.stable_id,
        item["question_revision"].revision_no, item["link"].revision_no))


def _links_for_question(actor, household_id, revision_ids):
    labels = _question_labels(household_id)
    result = {revision_id: [] for revision_id in revision_ids}
    candidates = RevisionRecord.objects.filter(entity__household_id=household_id,
        entity__kind__in=("knowledge_question", "method_question", "question_type_link"),
        outgoing_dependencies__role="link_question", outgoing_dependencies__target_id__in=revision_ids).distinct().select_related(
            "entity", "entity__published_revision", "review_projection")
    trace_cache = {}
    for link in candidates:
        qdep = link.outgoing_dependencies.filter(role="link_question").select_related("target__entity").first()
        target_dep = link.outgoing_dependencies.exclude(role="link_question").select_related("target__entity").first()
        if not qdep or not target_dep:
            continue
        qrid = qdep.target_id
        node_kind = target_dep.target.entity.kind
        if node_kind not in NODE_TYPES:
            continue
        node = target_dep.target.entity
        key = (node_kind, node.stable_id)
        if key not in trace_cache:
            trace_cache[key] = core.published_trace(actor, household_id, node=ObjectKey(*key))
        trace = trace_cache[key]
        current = (link.entity.published_revision_id == link.pk and link.review_projection.state == "accepted"
            and qrid in trace["question_revision_ids"] and target_dep.target_id in trace["node_revision_ids"])
        outdated = (link.entity.head_revision_id != link.pk
            or target_dep.target.entity.head_revision_id != target_dep.target_id
            or qdep.target.entity.head_revision_id != qrid
            or (target_dep.target.entity.published_revision_id is not None
                and target_dep.target.entity.published_revision_id != target_dep.target_id)
            or (qdep.target.entity.published_revision_id is not None
                and qdep.target.entity.published_revision_id != qrid))
        pending = (not outdated and (target_dep.target.entity.published_revision_id != target_dep.target_id
            or qdep.target.entity.published_revision_id != qrid or link.review_projection.state != "accepted"))
        result[qrid].append({"link": link, "node": node, "node_revision": target_dep.target,
            "current": current,
            "outdated": outdated, "pending": pending,
            "state": link.review_projection.state, "kind": node_kind})
    for revision_id in result:
        result[revision_id].sort(key=lambda item: (item["kind"], item["node"].stable_id,
            item["node_revision"].revision_no, item["link"].revision_no))
    return result


@transaction.atomic
def node_detail(actor, entity_id):
    entity = EntityRecord.objects.select_related("household", "head_revision", "published_revision").get(pk=entity_id)
    if entity.kind not in NODE_TYPES:
        raise core.PersistenceError("not_found", "知识节点不存在。")
    records.household(actor, entity.household_id)
    data = records.detail(actor, entity.household_id, entity.kind, entity.stable_id)
    history = data["history"]
    for row in history:
        row.web_review_state = row.review_projection.state
        row.web_review_context = core.review_context(actor, entity.household_id, row.pk)
        row.web_sources = _source_cards(actor, entity.household_id, row)
        row.web_can_review = (row.pk == entity.head_revision_id and row.review_projection.state in ("draft", "stale"))
        row.web_can_withdraw = entity.published_revision_id == row.pk
    links = _link_rows_for_target(actor, entity.household_id, entity.kind, entity)
    labels = _question_labels(entity.household_id)
    for row in links:
        row["question"] = _question_card(row["question_revision"], labels)
    bundle = core.read_snapshot_bundle(actor, entity.household_id)
    method_choices = method_revision_choices(actor, entity.household_id,
        exclude_entity_id=entity.pk if entity.kind == "method" else None)
    q_choices = question_revision_choices(bundle, labels)
    node_choices = node_revision_choices(bundle, entity.household_id, entity.kind, entity.stable_id)
    return {**data, "entity": entity, "history": history, "links": links,
        "current_sources": _source_cards(actor, entity.household_id, entity.head_revision),
        "parent_revision": RevisionRecord.objects.filter(pk=data["current"].get("parent_revision_id"),
            entity__household_id=entity.household_id, entity__kind="method").select_related("entity").first()
            if entity.kind == "method" else None,
        "method_choices": method_choices, "question_choices": q_choices,
        "node_choices": node_choices, "published_trace": core.published_trace(
            actor, entity.household_id, node=ObjectKey(entity.kind, entity.stable_id)),
        "household": entity.household}


def question_revision_choices(bundle, labels=None):
    choices = []
    labels = labels or {}
    for question in bundle.questions:
        for revision in question.revisions:
            title = revision.working_text or revision.printed_text or ", ".join(labels.get(question.question_id, ())) or "题干待补"
            choices.append((revision.header.revision_id, f"{title[:72]} · r{revision.header.revision_no}"))
    return sorted(choices, key=lambda row: (row[1].casefold(), row[0]))


def node_revision_choices(bundle, household_id, kind=None, stable_id=None):
    choices = []
    for node_kind, (field, id_field, _cls, *_rest) in NODE_TYPES.items():
        if kind and node_kind != kind:
            continue
        for item in getattr(bundle, field):
            if stable_id and getattr(item, id_field) != stable_id:
                continue
            for revision in item.revisions:
                label = revision.name if hasattr(revision, "name") else revision.definition[:72]
                choices.append((revision.header.revision_id, f"{NODE_TITLES[node_kind]}：{label[:72]} · r{revision.header.revision_no}"))
    return sorted(choices, key=lambda row: (row[1].casefold(), row[0]))


def practice_ready(entity):
    revision = entity.head_revision
    payload = revision.payload
    if entity.published_revision_id != revision.pk or revision.review_projection.state != 'accepted':
        return False
    if payload.get('missing_fields') or not payload.get('evidence_refs') or not (payload.get('working_text') or payload.get('printed_text') or '').strip():
        return False
    if any(ref.get('region_missing') or ref.get('gaps') for ref in payload['evidence_refs']):
        return False
    heads = {(kind, stable): head for kind, stable, head in EntityRecord.objects.filter(
        household_id=entity.household_id).values_list('kind', 'stable_id', 'head_revision_id')}
    return all(heads.get((item['kind'], item['stable_id'])) == item['head_revision_id'] for item in revision.dependency_heads)


def practice_unavailable_reason(entity):
    revision = entity.head_revision
    if entity.published_revision_id != revision.pk:
        return '当前题目版本尚未发布；旧发布版本仍保留为历史。'
    if revision.review_projection.state != 'accepted':
        return '当前题目版本尚未通过人工核定。'
    if revision.payload.get('missing_fields') or not revision.payload.get('evidence_refs'):
        return '题干或来源仍有缺项，请继续整理后核定。'
    return '来源或依赖版本需要重新核对，请继续整理并查看审核历史。'


@transaction.atomic
def question_detail(actor, entity_id):
    entity = EntityRecord.objects.select_related("household", "head_revision", "published_revision").get(pk=entity_id)
    if entity.kind != "question":
        raise core.PersistenceError("not_found", "题目不存在。")
    records.household(actor, entity.household_id)
    data = records.detail(actor, entity.household_id, "question", entity.stable_id)
    labels = _question_labels(entity.household_id)
    metadata = QuestionSource.objects.filter(revision=data["current"].get("header", {}).get("revision_id")).select_related("material").first()
    history = data["history"]
    revision_ids = [row.pk for row in history]
    associations = _links_for_question(actor, entity.household_id, revision_ids)
    for row in history:
        row.web_review_state = row.review_projection.state
        row.web_review_context = core.review_context(actor, entity.household_id, row.pk)
        row.web_sources = _source_cards(actor, entity.household_id, row)
        row.web_links = associations.get(row.pk, [])
        row.web_number = ", ".join(dict.fromkeys(labels.get(entity.pk, ()))) or "—"
        row.web_can_review = row.pk == entity.head_revision_id and row.review_projection.state in ("draft", "stale")
        row.web_can_withdraw = entity.published_revision_id == row.pk
    bundle = core.read_snapshot_bundle(actor, entity.household_id)
    all_nodes = node_revision_choices(bundle, entity.household_id)
    all_question_choices = question_revision_choices(bundle, labels)
    own_revision_ids = set(revision_ids)
    qchoices = [(revision_id, label) for revision_id, label in all_question_choices if revision_id in own_revision_ids]
    current_revision_id = entity.head_revision_id
    from app.printing.services import accepted_answer
    reference_answer, _ = accepted_answer(entity.head_revision)
    can_write = HouseholdMember.objects.filter(household=entity.household, user=actor,
        user__is_active=True, role__in=('owner', 'reviewer')).exists()
    return {**data, "entity": entity, "history": history, "associations": associations,
        "reference_answer": reference_answer, "can_write": can_write, "practice_ready": practice_ready(entity),
        "practice_unavailable_reason": practice_unavailable_reason(entity),
        "current_sources": _source_cards(actor, entity.household_id, entity.head_revision),
        "current_links": associations.get(current_revision_id, []),
        "number": ", ".join(dict.fromkeys(labels.get(entity.pk, ()))) or "—",
        "material": metadata.material if metadata else None,
        "node_choices": all_nodes, "question_choices": qchoices,
        "household": entity.household}


@transaction.atomic
def source_image(actor, image_record_id):
    image = ImageRecord.objects.select_related("household").get(pk=image_record_id)
    records.household(actor, image.household_id)
    return image
