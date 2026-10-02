"""Household-scoped question split/merge with exact revision lineage."""
from dataclasses import replace
from uuid import uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from app.domain import Question, QuestionRevision, ReviewState, seal_revision
from app.persistence import services as core
from app.persistence.adapter import ObjectKey
from app.persistence.models import EntityRecord, RevisionRecord
from app.web import knowledge_services
from app.web import records
from app.web.models import QuestionSource
from .models import QuestionLineage


MAX_SOURCES = 20
MAX_CHILDREN = 10


def _text(value, field, limit, *, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str) or "\x00" in value or len(value) > limit:
        raise core.PersistenceError("invalid_input", f"{field}格式无效或超过 {limit} 个字符。")
    value = value.strip()
    if required and not value:
        raise core.PersistenceError("invalid_input", f"{field}不能为空。")
    return value


def _ordered_questions(actor, household_id, revision_ids):
    if not isinstance(revision_ids, (list, tuple)) or not revision_ids or len(revision_ids) > MAX_SOURCES:
        raise core.PersistenceError("invalid_input", f"来源题目数量须为 1 至 {MAX_SOURCES}。")
    ids = [_text(value, "题目修订", 160, required=True) for value in revision_ids]
    if len(set(ids)) != len(ids):
        raise core.PersistenceError("invalid_input", "来源题目不能重复选择。")
    found = {row.pk: row for row in RevisionRecord.objects.filter(
        pk__in=ids, entity__household_id=household_id, entity__kind="question").select_related("entity")}
    if len(found) != len(ids):
        raise core.PersistenceError("not_found", "有来源题目不属于当前家庭，或修订已不存在。")
    rows = [found[revision_id] for revision_id in ids]
    if len({row.entity_id for row in rows}) != len(rows):
        raise core.PersistenceError("invalid_input", "同一题目的不同修订不能重复作为来源。")
    for row in rows:
        if row.entity.head_revision_id != row.pk:
            raise core.PersistenceError("head_conflict", "来源题目已产生新修订，请刷新后重新选择。")
    return rows


def _source_context(rows, action):
    contexts = [records.edit_context(row) for row in rows]
    return {"action": action, "source_revision_ids": [row.pk for row in rows],
        "source_contexts": contexts}


@transaction.atomic
def prepare_context(actor, household_id, action, revision_ids):
    if action not in {QuestionLineage.Action.SPLIT, QuestionLineage.Action.MERGE}:
        raise core.PersistenceError("invalid_input", "拆分或合题操作无效。")
    household = records.household(actor, household_id)
    rows = _ordered_questions(actor, household.pk, revision_ids)
    if action == QuestionLineage.Action.SPLIT and len(rows) != 1:
        raise core.PersistenceError("invalid_input", "拆题只接受一个来源题目版本。")
    if action == QuestionLineage.Action.MERGE and len(rows) < 2:
        raise core.PersistenceError("invalid_input", "合题至少选择两个不同题目版本。")
    context = _source_context(rows, action)
    return records.sign_context(household.pk, "catalogue", action, "lineage", context)


def _read_context(actor, household_id, action, token, revision_ids):
    context = records.read_context(token, household_id, "catalogue", action, "lineage")
    if context.get("action") != action or context.get("source_revision_ids") != list(revision_ids):
        raise core.PersistenceError("stale_context", "来源题目或操作与签名凭据不符，请刷新后重试。")
    rows = _ordered_questions(actor, household_id, revision_ids)
    expected_context = _source_context(rows, action)
    if context.get("source_contexts") != expected_context["source_contexts"]:
        raise core.PersistenceError("head_conflict", "来源题目或其完整依赖已变化，请重新选择。")
    expected = {}
    for row, source_context in zip(rows, context["source_contexts"]):
        expected[ObjectKey("question", row.entity.stable_id)] = row.pk
        for dependency in source_context.get("expected_dependencies", ()):
            key = ObjectKey(dependency["kind"], dependency["stable_id"])
            previous = expected.setdefault(key, dependency["head_revision_id"])
            if previous != dependency["head_revision_id"]:
                raise core.PersistenceError("head_conflict", "来源依赖版本互相冲突，请刷新后重试。")
    return rows, expected


def _domain_question_revisions(bundle):
    return {revision.header.revision_id: revision for question in bundle.questions
        for revision in question.revisions}


def _copy_evidence(revisions):
    refs = []
    seen = set()
    for revision in revisions:
        for ref in revision.evidence_refs:
            key = (ref.household_id, ref.image_id, ref.image_sha256, ref.granularity,
                ref.region_id, ref.region_revision_id, ref.region_missing, ref.purpose, ref.gaps)
            if key in seen:
                continue
            seen.add(key)
            refs.append(replace(ref, sequence=len(refs) + 1))
    return tuple(refs)


def _new_question(actor, household_id, stable_id, reason, printed_text, parent_revision_id, evidence_refs):
    text = printed_text or None
    header = records.header(actor, stable_id, reason)
    revision = seal_revision(QuestionRevision(header, ReviewState.DRAFT, parent_revision_id,
        text, text, () if text else ("printed_text", "working_text"), evidence_refs))
    return Question(stable_id, household_id, None, (revision,)), revision


def _question_source_metadata(source_rows, target_texts):
    metadata = [QuestionSource.objects.filter(revision_id=row.pk).select_related("material").first()
        for row in source_rows]
    if not metadata or any(item is None for item in metadata):
        return [None for _ in target_texts]
    if len({item.material_id for item in metadata}) != 1:
        return [None for _ in target_texts]
    material = metadata[0].material
    sources, seen_regions = [], set()
    for item in metadata:
        for source in item.sources:
            region_revision_id = source.get("region_revision_id")
            if region_revision_id and region_revision_id in seen_regions:
                continue
            if region_revision_id:
                seen_regions.add(region_revision_id)
            sources.append(source)
    sources = [{**source, "sequence": index} for index, source in enumerate(sources, 1)]
    return [(material, original_number, sources) for original_number in target_texts]


def _save_lineage(actor, household_id, action, source_ids, target_ids, reason):
    if QuestionLineage.objects.filter(household_id=household_id, action=action,
            source_revision_ids=source_ids, target_revision_ids=target_ids).exists():
        return
    QuestionLineage.objects.create(household_id=household_id, action=action,
        source_revision_ids=source_ids, target_revision_ids=target_ids, actor=actor,
        reason=reason, recorded_at=timezone.now())


def _attach_sources(target_revision_ids, metadata):
    for revision_id, value in zip(target_revision_ids, metadata):
        if value is None or QuestionSource.objects.filter(revision_id=revision_id).exists():
            continue
        material, original_number, sources = value
        QuestionSource.objects.create(revision_id=revision_id, material=material,
            original_number=original_number, sources=sources)


@transaction.atomic
def split_question(actor, household_id, *, source_revision_id, context_token, children,
                   reason, request_key):
    household = records.household(actor, household_id, write=True)
    source_revision_id = _text(source_revision_id, "题目修订", 160, required=True)
    context_token = _text(context_token, "操作凭据", 10000, required=True)
    children = list(children) if isinstance(children, (list, tuple)) else None
    if not children or len(children) < 2 or len(children) > MAX_CHILDREN:
        raise core.PersistenceError("invalid_input", f"拆题至少建立 2 个、最多 {MAX_CHILDREN} 个子题。")
    normalized_children, number_set = [], set()
    for child in children:
        if not isinstance(child, dict):
            raise core.PersistenceError("invalid_input", "子题内容无效。")
        number = _text(child.get("original_number"), "子题题号", 80, required=True)
        text = _text(child.get("printed_text"), "子题题干", 20000)
        if number in number_set:
            raise core.PersistenceError("invalid_input", "子题题号不能重复。")
        number_set.add(number)
        normalized_children.append({"original_number": number, "printed_text": text})
    reason = _text(reason, "拆题说明", 1000, required=True)
    normalized = {"household": household.pk, "action": "split", "source_revision_ids": [source_revision_id],
        "children": normalized_children, "reason": reason, "context_token": context_token}
    build_state = {"created": False, "source_metadata": []}

    def build(bundle):
        rows, expected_heads = _read_context(actor, household.pk, QuestionLineage.Action.SPLIT,
            context_token, [source_revision_id])
        source = rows[0]
        source_question_id = source.entity.stable_id
        domain_revisions = _domain_question_revisions(bundle)
        source_revision = domain_revisions.get(source.pk)
        if source_revision is None:
            raise core.PersistenceError("not_found", "来源题目修订已不存在。")
        copied_refs = _copy_evidence([source_revision])
        source_metadata = _question_source_metadata(rows,
            [row["original_number"] for row in normalized_children])
        questions = []
        target_revision_ids, target_question_ids = [], []
        for child in normalized_children:
            question_id = f"web-q-{uuid4().hex}"
            question, revision = _new_question(actor, household.pk, question_id, reason,
                child["printed_text"], source.pk, copied_refs)
            question = replace(question, parent_question_id=source_question_id)
            questions.append(question)
            target_question_ids.append(question_id)
            target_revision_ids.append(revision.header.revision_id)
        bundle = replace(bundle, questions=(*bundle.questions, *questions))
        expected = {**expected_heads, **{ObjectKey("question", qid): None for qid in target_question_ids}}
        build_state["created"] = True
        build_state["source_metadata"] = source_metadata
        return bundle, expected, {"source_revision_ids": [source.pk], "target_revision_ids": target_revision_ids,
            "target_question_ids": target_question_ids, "action": "split"}

    result = records.command(actor, household.pk, request_key, "question_split", normalized, build)
    if build_state["created"]:
        _save_lineage(actor, household.pk, "split", result["source_revision_ids"],
            result["target_revision_ids"], reason)
        _attach_sources(result["target_revision_ids"], build_state["source_metadata"])
    return result


@transaction.atomic
def merge_questions(actor, household_id, *, source_revision_ids, context_token,
                    original_number, printed_text, reason, request_key):
    household = records.household(actor, household_id, write=True)
    source_revision_ids = list(source_revision_ids) if isinstance(source_revision_ids, (list, tuple)) else None
    if not source_revision_ids or len(source_revision_ids) < 2 or len(source_revision_ids) > MAX_SOURCES:
        raise core.PersistenceError("invalid_input", "合题至少需要两个来源题目版本。")
    source_revision_ids = [_text(value, "题目修订", 160, required=True) for value in source_revision_ids]
    context_token = _text(context_token, "操作凭据", 10000, required=True)
    original_number = _text(original_number, "合并题号", 80, required=True)
    printed_text = _text(printed_text, "合并题干", 20000)
    reason = _text(reason, "合题说明", 1000, required=True)
    normalized = {"household": household.pk, "action": "merge", "source_revision_ids": source_revision_ids,
        "original_number": original_number, "printed_text": printed_text, "reason": reason,
        "context_token": context_token}
    build_state = {"created": False, "source_metadata": []}

    def build(bundle):
        rows, expected_heads = _read_context(actor, household.pk, QuestionLineage.Action.MERGE,
            context_token, source_revision_ids)
        domain_revisions = _domain_question_revisions(bundle)
        source_domain_revisions = [domain_revisions.get(row.pk) for row in rows]
        if any(revision is None for revision in source_domain_revisions):
            raise core.PersistenceError("not_found", "有来源题目修订已不存在。")
        refs = _copy_evidence(source_domain_revisions)
        source_ids = [row.pk for row in rows]
        source_metadata = _question_source_metadata(rows, [original_number])
        question_id = f"web-q-{uuid4().hex}"
        question, revision = _new_question(actor, household.pk, question_id, reason,
            printed_text, None, refs)
        bundle = replace(bundle, questions=(*bundle.questions, question))
        expected = {**expected_heads, ObjectKey("question", question_id): None}
        build_state["created"] = True
        build_state["source_metadata"] = source_metadata
        return bundle, expected, {"source_revision_ids": source_ids,
            "target_revision_ids": [revision.header.revision_id],
            "target_question_ids": [question_id], "action": "merge"}

    result = records.command(actor, household.pk, request_key, "question_merge", normalized, build)
    if build_state["created"]:
        _save_lineage(actor, household.pk, "merge", result["source_revision_ids"],
            result["target_revision_ids"], reason)
        _attach_sources(result["target_revision_ids"], build_state["source_metadata"])
    return result


@transaction.atomic
def question_index(actor, household_id):
    records.household(actor, household_id)
    data = knowledge_services.index_data(actor, household_id)
    return {"household": data["household"], "questions": data["questions"]}


def _lineage_rows(household_id, revision_ids):
    query = Q()
    for revision_id in revision_ids:
        query |= Q(source_revision_ids__contains=[revision_id]) | Q(target_revision_ids__contains=[revision_id])
    rows = QuestionLineage.objects.filter(household_id=household_id).filter(query).order_by("recorded_at", "pk")
    result = []
    for row in rows:
        source_revisions = list(RevisionRecord.objects.filter(pk__in=row.source_revision_ids,
            entity__household_id=household_id).select_related("entity", "review_projection"))
        target_revisions = list(RevisionRecord.objects.filter(pk__in=row.target_revision_ids,
            entity__household_id=household_id).select_related("entity", "review_projection"))
        source_by_id = {revision.pk: revision for revision in source_revisions}
        target_by_id = {revision.pk: revision for revision in target_revisions}
        result.append({"lineage": row,
            "sources": [source_by_id[rid] for rid in row.source_revision_ids if rid in source_by_id],
            "targets": [target_by_id[rid] for rid in row.target_revision_ids if rid in target_by_id]})
    return result


@transaction.atomic
def question_detail(actor, entity_id):
    entity = EntityRecord.objects.select_related("household", "head_revision", "published_revision").get(pk=entity_id)
    if entity.kind != "question":
        raise core.PersistenceError("not_found", "题目不存在。")
    records.household(actor, entity.household_id)
    data = records.detail(actor, entity.household_id, "question", entity.stable_id)
    history = data["history"]
    for row in history:
        row.web_review_context = core.review_context(actor, entity.household_id, row.pk)
        row.web_sources = knowledge_services._source_cards(actor, entity.household_id, row)
    return {**data, "entity": entity, "history": history,
        "current_sources": knowledge_services._source_cards(actor, entity.household_id, entity.head_revision),
        "lineages": _lineage_rows(entity.household_id, [row.pk for row in history]),
        "household": entity.household}
