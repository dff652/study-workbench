"""Household-scoped manual learner records and assessment workflow."""
from dataclasses import replace
from datetime import date
from uuid import uuid4

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from app.domain import (
    ActualDateState, Assessment, AssessmentDimension, AssessmentRevision,
    Attempt, AttemptKind, AttemptRevision, AttemptState, AuthorState, BasisKind,
    DimensionKind, Independence, Judgment, Legibility, ObservationRef,
    ObservationRevision, PromptStatus, ReviewState, SourceKind,
    SourceObservation, LearnerProfile, seal_revision,
)
from app.persistence import services as core
from app.persistence.adapter import ObjectKey
from app.persistence.models import EntityRecord, HouseholdMember, ImageRecord, RevisionRecord, ReviewProjection
from app.catalogue.models import QuestionLabel
from app.web import services as material_services
from app.web.models import MaterialPage, PagePreview, QuestionSource
from . import records
from .presentation import ui_label
from .learning_labels import attempt_choice_label


DIMENSIONS = (
    DimensionKind.ANSWER,
    DimensionKind.METHOD,
    DimensionKind.PROCESS,
    DimensionKind.CALCULATION,
    DimensionKind.NOTATION,
)


def _learner(bundle, learner_id):
    return next((item for item in bundle.learners if item.learner_id == learner_id), None)


def _question(bundle, question_id):
    return next((item for item in bundle.questions if item.question_id == question_id), None)


def _observation(bundle, observation_id):
    return next((item for item in bundle.observations if item.observation_id == observation_id), None)


def _attempt(bundle, attempt_id):
    return next((item for item in bundle.attempts if item.attempt_id == attempt_id), None)


def _assessment(bundle, assessment_id):
    return next((item for item in bundle.assessments if item.assessment_id == assessment_id), None)


def _revision(bundle, revision_id):
    for collection in (bundle.regions, bundle.questions, bundle.knowledge_items, bundle.methods,
                      bundle.question_types, bundle.observations, bundle.attempts, bundle.assessments,
                      bundle.errata):
        for item in collection:
            revisions = item.revisions if hasattr(item, "revisions") else (item,)
            for revision in revisions:
                if revision.header.revision_id == revision_id:
                    return revision
    return None


def _new_id(prefix):
    return f"{prefix}-{uuid4().hex}"


def _require_writable(actor, household_id):
    records.household(actor, household_id, write=True)


@transaction.atomic
def household_options(actor):
    return list(HouseholdMember.objects.filter(user=actor, user__is_active=True)
                .select_related("household").order_by("household_id"))


@transaction.atomic
def visible_household(actor, household_id):
    """Check membership before returning any household-scoped page data."""
    return records.household(actor, household_id)


@transaction.atomic
def profile_list(actor, household_id=None):
    rows = household_options(actor)
    if household_id is None and rows:
        household_id = str(rows[0].household_id)
    if household_id is None:
        return {"households": rows, "household_id": "", "profiles": [], "observations": [],
                "questions": [], "materials": [], "writable": False}
    household = visible_household(actor, household_id)
    bundle = core.read_snapshot_bundle(actor, household.pk)
    memberships = {str(row.household_id): row for row in rows}
    membership = memberships.get(str(household.pk))
    from app.study.models import StudySchedule
    plans = {}
    for schedule in StudySchedule.objects.filter(household=household).select_related('learner').prefetch_related('revisions'):
        latest = max(schedule.revisions.all(), key=lambda row: row.revision_no, default=None)
        if latest and latest.action in ('planned', 'rescheduled'):
            plans.setdefault(schedule.learner.stable_id, []).append(latest.due_date)
    profile_cards = []
    for profile in sorted(bundle.learners, key=lambda item: (item.display_name.casefold(), item.learner_id)):
        attempts = [item.revisions[-1] for item in bundle.attempts if item.learner_id == profile.learner_id and item.revisions[-1].state is AttemptState.ACTIVE]
        dates = [item.actual_date for item in attempts if item.actual_date_state is ActualDateState.KNOWN and item.actual_date]
        due = plans.get(profile.learner_id, [])
        profile_cards.append({'profile': profile, 'attempt_count': len(attempts), 'recent_date': max(dates, default=None),
                              'plan_count': len(due), 'next_due': min(due, default=None)})
    return {
        "households": rows,
        "household_id": str(household.pk),
        "profiles": sorted(bundle.learners, key=lambda item: (item.display_name.casefold(), item.learner_id)),
        "profile_cards": profile_cards,
        "observations": sorted(bundle.observations, key=lambda item: item.revisions[-1].header.recorded_at, reverse=True),
        "questions": _published_question_choices(actor, household.pk, bundle),
        "materials": list(material_services.list_materials(actor).filter(household_id=household.pk)),
        "writable": bool(membership and membership.role in ("owner", "reviewer")),
    }


@transaction.atomic
def create_profile(actor, household_id, *, display_name, grade, request_key):
    _require_writable(actor, household_id)
    display_name = _clean_text(display_name, 120, "学习者称呼")
    grade = _clean_text(grade, 80, "年级", allow_blank=True) or None

    def build(bundle):
        learner_id = _new_id("learner")
        learner = LearnerProfile(learner_id, str(household_id), display_name, grade)
        return replace(bundle, learners=(*bundle.learners, learner)), {}, {"learner_id": learner_id}

    return records.command(actor, household_id, request_key, "learner_profile.create",
                           {"display_name": display_name, "grade": grade}, build)


def _clean_text(value, limit, label, *, allow_blank=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise core.PersistenceError("invalid_input", f"{label}内容无效。")
    text = value.strip()
    if not text and not allow_blank:
        raise core.PersistenceError("invalid_input", f"请填写{label}。")
    return text


def _profile_or_404(actor, learner_id):
    row = EntityRecord.objects.filter(kind="learner", stable_id=learner_id).select_related("household").first()
    if row is None:
        raise core.PersistenceError("not_found", "学习者档案不存在。")
    records.household(actor, row.household_id)
    return row.household_id


@transaction.atomic
def profile_detail(actor, learner_id):
    household_id = _profile_or_404(actor, learner_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    profile = _learner(bundle, learner_id)
    if profile is None:
        raise core.PersistenceError("not_found", "学习者档案不存在。")
    observations = [item for item in bundle.observations
                    if item.profile_context_id == learner_id or any(
                        revision.author_learner_id == learner_id for revision in item.revisions)]
    attempts = [item for item in bundle.attempts if item.learner_id == learner_id]
    return _profile_view(actor, household_id, bundle, profile, observations, attempts)


def _published_question_choices(actor, household_id, bundle):
    rows = (EntityRecord.objects.filter(household_id=household_id, kind="question", published_revision__isnull=False)
            .select_related("published_revision", "published_revision__review_projection")
            .order_by("stable_id"))
    questions = {item.question_id: item for item in bundle.questions}
    numbers = _question_numbers_by_revision(household_id, [row.published_revision_id for row in rows])
    result = []
    for row in rows:
        revision = row.published_revision
        if revision.entity_id != row.pk or revision.review_projection.state != "accepted":
            continue
        question = questions.get(row.stable_id)
        if question is None:
            continue
        qrev = next((item for item in question.revisions if item.header.revision_id == revision.pk), None)
        if qrev is None:
            continue
        text = qrev.working_text or qrev.printed_text or "题干待补"
        number = numbers.get(str(revision.pk), "")
        revision_no = qrev.header.revision_no
        result.append({"question_id": question.question_id, "revision_id": revision.pk,
                       "head_revision_id": row.head_revision_id, "revision_no": revision_no,
                       "label": f"{number + ' · ' if number else ''}{text[:140]} · r{revision_no}"})
    return result


def _question_numbers_by_revision(household_id, revision_ids):
    revision_ids = tuple(revision_ids)
    if not revision_ids:
        return {}
    numbers = {}
    sources = QuestionSource.objects.filter(revision_id__in=revision_ids,
        revision__entity__household_id=household_id, revision__entity__kind="question")
    for source in sources:
        if source.original_number:
            numbers[str(source.revision_id)] = source.original_number
    for label in QuestionLabel.objects.filter(revision_id__in=revision_ids,
            revision__entity__household_id=household_id, revision__entity__kind="question").select_related(
                "revision"):
        key = str(label.revision_id)
        if key not in numbers and label.original_number:
            numbers[key] = label.original_number
    return numbers


def _question_revision_labels(household_id, bundle):
    revisions = {revision.header.revision_id: revision
        for question in bundle.questions for revision in question.revisions}
    numbers = _question_numbers_by_revision(household_id, revisions)
    labels = {}
    for revision_id, revision in revisions.items():
        text = revision.working_text or revision.printed_text or "题干待补"
        number = numbers.get(str(revision_id), "")
        revision_no = revision.header.revision_no
        labels[revision_id] = f"{number + ' · ' if number else ''}{text[:140]} · r{revision_no}"
    return labels


def _profile_view(actor, household_id, bundle, profile, observations, attempts):
    question_options = _published_question_choices(actor, household_id, bundle)
    qlabels = _question_revision_labels(household_id, bundle)
    knowledge_by_question, types_by_question = _published_node_labels(household_id)
    attempt_infos = []
    error_choices = set()
    review_states = set()
    for attempt in attempts:
        current = attempt.revisions[-1]
        assessment_rows = _actual_assessments(actor, household_id, bundle, attempt)
        for info in assessment_rows:
            review_states.add(info["state"])
            if any(d.judgment in (Judgment.INCORRECT, Judgment.PARTIAL) for d in info["revision"].dimensions):
                error_choices.add("error")
        question_revision_id = current.question_revision_id
        question_label = qlabels.get(question_revision_id, attempt.question_id)
        knowledge_nodes = knowledge_by_question.get(question_revision_id, ())
        type_nodes = types_by_question.get(question_revision_id, ())
        attempt_infos.append({
            "attempt": attempt,
            "revision": current,
            "question_label": question_label,
            "knowledge_labels": tuple(item["label"] for item in knowledge_nodes),
            "knowledge_ids": frozenset(item["stable_id"] for item in knowledge_nodes),
            "type_labels": tuple(item["label"] for item in type_nodes),
            "type_ids": frozenset(item["stable_id"] for item in type_nodes),
            "assessments": assessment_rows,
            "independent_success": _independent_success(actor, household_id, bundle, attempt, assessment_rows),
            "sort_date": str(current.actual_date) if current.actual_date_state is ActualDateState.KNOWN and current.actual_date else '',
        })
    obs_infos = []
    for observation in observations:
        latest = observation.revisions[-1]
        author = _learner(bundle, latest.author_learner_id)
        obs_infos.append({"observation": observation, "revision": latest,
                          "author_name": author.display_name if author else "未知",
                          "sources": _source_cards(actor, household_id, bundle, latest.evidence_refs)})
    return {"household_id": str(household_id), "profile": profile, "observations": obs_infos,
            "attempts": attempt_infos,
            "knowledge_options": _profile_node_options(knowledge_by_question),
            "type_options": _profile_node_options(types_by_question),
            "review_options": sorted(review_states), "error_options": sorted(error_choices),
            "question_options": question_options}


def _published_node_labels(household_id):
    questions_for_knowledge, questions_for_type = {}, {}
    rows = (EntityRecord.objects.filter(household_id=household_id,
            kind__in=("knowledge_question", "question_type_link"), published_revision__isnull=False)
            .select_related("published_revision", "published_revision__review_projection"))
    for row in rows:
        revision = row.published_revision
        if revision.review_projection.state != "accepted":
            continue
        payload = revision.payload
        qrev_id = payload.get("question_revision_id")
        question_revision = RevisionRecord.objects.filter(pk=qrev_id,
            entity__household_id=household_id, entity__kind="question").select_related(
                "entity", "review_projection").first()
        if question_revision is None:
            continue
        target_id = payload.get("knowledge_revision_id") if row.kind == "knowledge_question" else payload.get("question_type_revision_id")
        target_kind = "knowledge" if row.kind == "knowledge_question" else "question_type"
        target_revision = RevisionRecord.objects.filter(pk=target_id,
            entity__household_id=household_id, entity__kind=target_kind).select_related(
                "entity", "review_projection").first()
        if target_revision is None:
            continue
        node_id = target_revision.entity.stable_id
        name = (target_revision.payload.get("definition", "")[:100] or "未命名知识点") if target_kind == "knowledge" else (
            target_revision.payload.get("name", "未命名题型"))
        label = f"{name} · 第 {target_revision.revision_no} 版"
        historical = (question_revision.entity.published_revision_id != question_revision.pk
                or question_revision.review_projection.state != "accepted"
                or target_revision.entity.published_revision_id != target_revision.pk
                or target_revision.review_projection.state != "accepted")
        if historical:
            label += "（历史关系）"
        bucket = questions_for_knowledge if row.kind == "knowledge_question" else questions_for_type
        bucket.setdefault(qrev_id, {})[(node_id, target_revision.pk)] = {
            "stable_id": node_id, "name": name, "revision_no": target_revision.revision_no,
            "label": label, "historical": historical,
        }
    from .presentation import distinct_choices
    nodes = {(item['stable_id'], item['name']): item['name']
        for bucket in (questions_for_knowledge, questions_for_type)
        for rows in bucket.values() for item in rows.values()}
    names = dict(distinct_choices(sorted(nodes.items(), key=lambda item: (item[1].casefold(), item[0]))))
    for bucket in (questions_for_knowledge, questions_for_type):
        for values in bucket.values():
            for item in values.values():
                item['display_name'] = names[(item['stable_id'], item['name'])]
                item['label'] = f"{item['display_name']} · 第 {item['revision_no']} 版" + (
                    '（历史关系）' if item['historical'] else '')
    return ({key: tuple(sorted(value.values(), key=lambda item: (item["name"].casefold(), item["stable_id"])))
             for key, value in questions_for_knowledge.items()},
            {key: tuple(sorted(value.values(), key=lambda item: (item["name"].casefold(), item["stable_id"])))
             for key, value in questions_for_type.items()})


def _profile_node_options(relationships_by_question):
    nodes = {}
    historical_ids = set()
    for relationships in relationships_by_question.values():
        for relationship in relationships:
            if relationship["historical"]:
                historical_ids.add(relationship["stable_id"])
            current = nodes.get(relationship["stable_id"])
            if current is None or relationship["revision_no"] > current["revision_no"]:
                nodes[relationship["stable_id"]] = relationship
    return [{"stable_id": stable_id,
        "label": row['display_name'] + ("（含历史关系）" if stable_id in historical_ids else "")}
        for stable_id, row in sorted(nodes.items(), key=lambda item: (item[1]["name"].casefold(), item[0]))]


def _actual_assessments(actor, household_id, bundle, attempt):
    result = []
    rows = EntityRecord.objects.filter(household_id=household_id, kind="assessment").select_related("head_revision", "published_revision")
    assessments = {item.assessment_id: item for item in bundle.assessments}
    for row in rows:
        assessment = assessments.get(row.stable_id)
        if assessment is None or assessment.attempt_id != attempt.attempt_id:
            continue
        for revision in assessment.revisions:
            projection = ReviewProjection.objects.filter(revision_id=revision.header.revision_id).select_related("decision").first()
            if projection is None:
                continue
            result.append({"assessment": assessment, "revision": revision, "projection": projection,
                           "state": projection.state,
                           "current": row.head_revision_id == revision.header.revision_id,
                           "published": row.published_revision_id == revision.header.revision_id,
                           "url_id": assessment.assessment_id})
    return sorted(result, key=lambda item: (item["revision"].header.recorded_at, item["revision"].header.revision_no), reverse=True)


def _independent_success(actor, household_id, bundle, attempt, assessments):
    current = attempt.revisions[-1]
    attempt_row = EntityRecord.objects.filter(household_id=household_id, kind="attempt",
                                              stable_id=attempt.attempt_id).only("head_revision_id").first()
    if (current.state is not AttemptState.ACTIVE or current.source_kind is not SourceKind.INDEPENDENT_ANSWER
            or current.independence is not Independence.CONFIRMED_INDEPENDENT
            or current.prompt_status is not PromptStatus.NONE_CONFIRMED
            or current.actual_date_state is not ActualDateState.KNOWN or current.legibility is not Legibility.READABLE
            or attempt_row is None or attempt_row.head_revision_id != current.header.revision_id):
        return False
    observations = {item.observation_id: item for item in bundle.observations}
    verified = set()
    for ref in current.observation_refs:
        observation = observations.get(ref.observation_id)
        revision = next((item for item in observation.revisions if item.header.revision_id == ref.observation_revision_id), None) if observation else None
        observation_row = EntityRecord.objects.filter(household_id=household_id, kind="observation",
            stable_id=ref.observation_id).only("head_revision_id").first()
        if (not observation or not revision or observation.revisions[-1].header.revision_id != revision.header.revision_id
                or observation_row is None or observation_row.head_revision_id != revision.header.revision_id
                or revision.author_state is not AuthorState.CONFIRMED
                or revision.author_learner_id != attempt.learner_id or revision.legibility is not Legibility.READABLE
                or not revision.confirmed_by or not revision.confirmed_at or not revision.confirmation_basis
                or revision.actual_date_state is not ActualDateState.KNOWN
                or revision.actual_date != current.actual_date):
            continue
        verified.update(revision.evidence_refs)
    if not verified:
        return False
    accepted = [item for item in assessments if item["state"] == "accepted" and item["current"]
                and item["published"]
                and item["revision"].attempt_revision_id == current.header.revision_id]
    if any(d.judgment in (Judgment.INCORRECT, Judgment.PARTIAL)
           for item in accepted for d in item["revision"].dimensions):
        return False
    for item in accepted:
        dimensions = {dimension.dimension: dimension for dimension in item["revision"].dimensions}
        answer, process = dimensions.get(DimensionKind.ANSWER), dimensions.get(DimensionKind.PROCESS)
        if not answer or not process:
            continue
        if all(d.judgment is Judgment.CORRECT and d.basis is BasisKind.OBSERVED and d.evidence_refs
               and set(d.evidence_refs).issubset(verified) for d in (answer, process)):
            return True
    return False


@transaction.atomic
def learner_create_choices(actor, learner_id):
    household_id = _profile_or_404(actor, learner_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    profile = _learner(bundle, learner_id)
    return _attempt_choices(actor, household_id, bundle, profile.learner_id)


def _attempt_choices(actor, household_id, bundle, learner_id=None):
    questions = _published_question_choices(actor, household_id, bundle)
    observation_choices = []
    obs_heads = {}
    for observation in bundle.observations:
        latest = observation.revisions[-1]
        if latest.author_state is not AuthorState.CONFIRMED or not latest.evidence_refs:
            continue
        if learner_id and latest.author_learner_id != learner_id:
            continue
        value = f"{observation.observation_id}|{latest.header.revision_id}"
        label = f"{latest.actual_date or '日期未知'} · {latest.notes[:80] or '来源观察'} · {len(latest.evidence_refs)} 个区域"
        observation_choices.append((value, label))
        obs_heads[observation.observation_id] = latest.header.revision_id
    prior = []
    question_labels = {item['question_id']: item['label'] for item in questions}
    for attempt in bundle.attempts:
        if learner_id and attempt.learner_id != learner_id:
            continue
        current = attempt.revisions[-1]
        title = question_labels.get(attempt.question_id, '历史题目')
        prior.append((attempt.attempt_id, attempt_choice_label(attempt.attempt_id, current, title)))
    token_context = {
        "question_versions": {item["question_id"]: item["revision_id"] for item in questions},
        "question_heads": {item["question_id"]: item["head_revision_id"] for item in questions},
        "observation_heads": obs_heads,
        "attempt_ids": [item[0] for item in prior],
    }
    return {"questions": questions, "observation_choices": observation_choices,
            "prior_attempts": prior, "context": token_context,
            "observation_head_map": obs_heads}


def _parse_observation_values(values):
    refs = []
    for raw in values:
        if not isinstance(raw, str) or "|" not in raw:
            raise core.PersistenceError("invalid_input", "来源观察选择无效。")
        observation_id, revision_id = raw.split("|", 1)
        refs.append(ObservationRef(observation_id, revision_id))
    if not refs or len(set(refs)) != len(refs):
        raise core.PersistenceError("invalid_input", "请至少选择一条作答来源观察。")
    return tuple(refs)


def _validate_attempt_source(bundle, refs, learner_id, legibility, answer_text):
    by_id = {item.observation_id: item for item in bundle.observations}
    evidence = []
    for ref in refs:
        observation = by_id.get(ref.observation_id)
        revision = next((item for item in observation.revisions if item.header.revision_id == ref.observation_revision_id), None) if observation else None
        if (observation is None or revision is None or observation.revisions[-1].header.revision_id != revision.header.revision_id
                or revision.author_state is not AuthorState.CONFIRMED or revision.author_learner_id != learner_id):
            raise core.PersistenceError("invalid_input", "作答来源必须是当前版本且已人工确认属于该学习者的观察。")
        evidence.extend(revision.evidence_refs)
    if not evidence:
        raise core.PersistenceError("invalid_input", "作答需要关联至少一个可追溯的原图区域。")
    if legibility in (Legibility.BLANK, Legibility.ILLEGIBLE) and answer_text:
        raise core.PersistenceError("invalid_input", "空白或看不清的笔迹不能录入答案文字。")


def _date_value(date_value, state):
    if state is ActualDateState.UNKNOWN:
        return None
    if isinstance(date_value, date):
        return date_value.isoformat()
    if isinstance(date_value, str) and date_value:
        try:
            return date.fromisoformat(date_value).isoformat()
        except ValueError as exc:
            raise core.PersistenceError("invalid_input", "实际作答日期无效。") from exc
    raise core.PersistenceError("invalid_input", "请选择已知日期或明确标记日期未知。")


def _confirm_question(bundle, household_id, question_id, expected_revision):
    question = _question(bundle, question_id)
    if question is None:
        raise core.PersistenceError("invalid_input", "题目不存在。")
    row = EntityRecord.objects.filter(household_id=household_id, kind="question", stable_id=question_id,
                                      published_revision__isnull=False).select_related("published_revision", "published_revision__review_projection").first()
    if row is None or row.published_revision_id != expected_revision or row.published_revision.review_projection.state != "accepted":
        raise core.PersistenceError("stale_context", "题目发布版本已改变，请重新打开页面。")
    revision = next((item for item in question.revisions if item.header.revision_id == expected_revision), None)
    if revision is None:
        raise core.PersistenceError("stale_context", "题目修订已改变，请重新打开页面。")
    return revision


def _confirm_observations(bundle, selected_refs, expected_heads, learner_id, household_id, heads):
    by_id = {item.observation_id: item for item in bundle.observations}
    for ref in selected_refs:
        expected = expected_heads.get(ref.observation_id)
        observation = by_id.get(ref.observation_id)
        if expected is None or observation is None or observation.revisions[-1].header.revision_id != expected:
            raise core.PersistenceError("stale_context", "来源观察已改变，请重新打开页面。")
        revision = next((item for item in observation.revisions if item.header.revision_id == ref.observation_revision_id), None)
        if (revision is None or revision.header.revision_id != expected or revision.author_state is not AuthorState.CONFIRMED
                or revision.author_learner_id != learner_id):
            raise core.PersistenceError("invalid_input", "作答来源必须是当前版本且已人工确认属于该学习者的观察。")
        heads[ObjectKey("observation", observation.observation_id)] = expected


@transaction.atomic
def create_attempt(actor, learner_id, *, question_id, attempt_kind, source_kind, independence,
                   prompt_status, prompts, actual_date_state, actual_date, legibility, answer_text,
                   authorship_basis, observation_values, previous_attempt_id, context,
                   request_key, replacement_for=None):
    household_id = _profile_or_404(actor, learner_id)
    if replacement_for:
        old_household_id = _entity_household(actor, "attempt", replacement_for)
        if str(old_household_id) != str(household_id):
            raise core.PersistenceError("invalid_input", "替代作答必须保存在同一家庭。")
    question_id = _clean_text(question_id, 160, "题目")
    attempt_kind = attempt_kind if isinstance(attempt_kind, AttemptKind) else AttemptKind(attempt_kind)
    source_kind = source_kind if isinstance(source_kind, SourceKind) else SourceKind(source_kind)
    independence = independence if isinstance(independence, Independence) else Independence(independence)
    prompt_status = prompt_status if isinstance(prompt_status, PromptStatus) else PromptStatus(prompt_status)
    actual_date_state = actual_date_state if isinstance(actual_date_state, ActualDateState) else ActualDateState(actual_date_state)
    legibility = legibility if isinstance(legibility, Legibility) else Legibility(legibility)
    prompts = tuple(_clean_text(item, 240, "提示内容") for item in prompts if item.strip())
    answer_text = _clean_text(answer_text, 10000, "答案", allow_blank=True) or None
    authorship_basis = _clean_text(authorship_basis, 1000, "作者确认依据")
    actual_date = _date_value(actual_date, actual_date_state)
    selected_refs = _parse_observation_values(observation_values)
    if source_kind in (SourceKind.CLASSROOM_NOTE, SourceKind.COPIED_WORK) and independence is Independence.CONFIRMED_INDEPENDENT:
        raise core.PersistenceError("invalid_input", "课堂笔记或抄录不能标记为已确认独立。")
    if source_kind is SourceKind.INDEPENDENT_ANSWER and independence is Independence.NOT_INDEPENDENT:
        raise core.PersistenceError("invalid_input", "独立作答来源不能同时标记为非独立。")
    if independence is Independence.CONFIRMED_INDEPENDENT and (source_kind is not SourceKind.INDEPENDENT_ANSWER or prompt_status is not PromptStatus.NONE_CONFIRMED):
        raise core.PersistenceError("invalid_input", "确认独立需要独立作答来源，并明确确认没有提示。")
    if attempt_kind is AttemptKind.FIRST and previous_attempt_id:
        raise core.PersistenceError("invalid_input", "首次作答不应引用前次作答。")

    def build(bundle):
        learner = _learner(bundle, learner_id)
        if learner is None:
            raise core.PersistenceError("not_found", "学习者档案不存在。")
        expected_revision = context.get("question_versions", {}).get(question_id)
        expected_head = context.get("question_heads", {}).get(question_id)
        if expected_head is None:
            raise core.PersistenceError("stale_context", "题目版本已改变，请重新打开页面。")
        question_revision = _confirm_question(bundle, household_id, question_id, expected_revision)
        heads = {ObjectKey("question", question_id): expected_head}
        _confirm_observations(bundle, selected_refs, context.get("observation_heads", {}), learner_id, household_id, heads)
        _validate_attempt_source(bundle, selected_refs, learner_id, legibility, answer_text)
        if previous_attempt_id:
            if previous_attempt_id not in context.get("attempt_ids", []):
                raise core.PersistenceError("stale_context", "前次作答已改变，请重新打开页面。")
            previous = _attempt(bundle, previous_attempt_id)
            if previous is None or previous.learner_id != learner_id or previous.question_id != question_id:
                raise core.PersistenceError("invalid_input", "前次作答必须属于同一学习者和题目。")
        elif attempt_kind is not AttemptKind.FIRST:
            raise core.PersistenceError("invalid_input", "订正、重做或复测需要选择前次作答。")
        attempt_id = _new_id("attempt")
        header = records.header(actor, attempt_id, "新增一次人工作答")
        revision = seal_revision(AttemptRevision(header, question_revision.header.revision_id, attempt_kind,
            source_kind, independence, prompt_status, prompts, actual_date_state, actual_date,
            legibility, answer_text, authorship_basis, selected_refs, AttemptState.ACTIVE))
        attempt = Attempt(attempt_id, household_id, learner_id, question_id, previous_attempt_id or None,
                          replacement_for, (revision,))
        observations = bundle.observations
        if replacement_for:
            old = _attempt(bundle, replacement_for)
            if old is None or old.revisions[-1].state is not AttemptState.ACTIVE:
                raise core.PersistenceError("stale_context", "待更正作答已发生变化。")
            old_row = records.entity(household_id, "attempt", replacement_for).head_revision
            if context.get("replacement_context") != records.edit_context(old_row):
                raise core.PersistenceError("head_conflict", "待更正作答或依赖已改变。")
            old_heads = records.check_edit(old_row, context["replacement_context"])
            heads.update(old_heads)
            old_current = old.revisions[-1]
            withdrawn = seal_revision(replace(old_current,
                header=records.header(actor, replacement_for, "作者或题目身份更正：撤回旧作答", old_row),
                state=AttemptState.WITHDRAWN, withdrawal_reason="identity_error", replacement_attempt_id=attempt_id))
            observations_attempts = tuple(replace(item, revisions=(*item.revisions, withdrawn)) if item.attempt_id == replacement_for else item
                                         for item in bundle.attempts)
        else:
            observations_attempts = bundle.attempts
        return replace(bundle, attempts=(*observations_attempts, attempt)), heads, {"attempt_id": attempt_id}

    inputs = {"learner_id": learner_id, "question_id": question_id, "attempt_kind": attempt_kind.value,
              "source_kind": source_kind.value, "independence": independence.value, "prompt_status": prompt_status.value,
              "prompts": prompts, "actual_date_state": actual_date_state.value, "actual_date": actual_date,
              "legibility": legibility.value, "answer_text": answer_text, "authorship_basis": authorship_basis,
              "observation_values": list(observation_values), "previous_attempt_id": previous_attempt_id,
              "context": context, "replacement_for": replacement_for}
    return records.command(actor, household_id, request_key, "learner_attempt.create", inputs, build)


@transaction.atomic
def attempt_edit_context(actor, attempt_id):
    household_id = _entity_household(actor, "attempt", attempt_id)
    data = records.detail(actor, household_id, "attempt", attempt_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    attempt = _attempt(bundle, attempt_id)
    choices = _attempt_choices(actor, household_id, bundle, attempt.learner_id)
    return {**data, "bundle": bundle, "attempt": attempt, "choices": choices, "household_id": household_id}


def _entity_household(actor, kind, stable_id):
    row = EntityRecord.objects.filter(kind=kind, stable_id=stable_id).select_related("household").first()
    if row is None:
        raise core.PersistenceError("not_found", "记录不存在。")
    records.household(actor, row.household_id)
    return row.household_id


@transaction.atomic
def append_attempt_revision(actor, attempt_id, *, attempt_kind, source_kind, independence, prompt_status,
                            prompts, actual_date_state, actual_date, legibility, answer_text, authorship_basis,
                            observation_values, expected_context, request_key):
    household_id = _entity_household(actor, "attempt", attempt_id)
    attempt_kind = AttemptKind(attempt_kind)
    source_kind = SourceKind(source_kind)
    independence = Independence(independence)
    prompt_status = PromptStatus(prompt_status)
    actual_date_state = ActualDateState(actual_date_state)
    legibility = Legibility(legibility)
    prompts = tuple(_clean_text(item, 240, "提示内容") for item in prompts if item.strip())
    answer_text = _clean_text(answer_text, 10000, "答案", allow_blank=True) or None
    authorship_basis = _clean_text(authorship_basis, 1000, "作者确认依据")
    actual_date = _date_value(actual_date, actual_date_state)
    selected_refs = _parse_observation_values(observation_values)

    def build(bundle):
        current = _attempt(bundle, attempt_id)
        if current is None or current.revisions[-1].state is not AttemptState.ACTIVE:
            raise core.PersistenceError("stale_context", "当前作答已撤回或不存在。")
        row = records.entity(household_id, "attempt", attempt_id).head_revision
        edit_context = expected_context.get("edit_context")
        if not isinstance(edit_context, dict):
            raise core.PersistenceError("stale_context", "作答编辑凭据无效，请重新打开页面。")
        heads = records.check_edit(row, edit_context)
        qrev = _revision(bundle, current.revisions[-1].question_revision_id)
        _confirm_observations(bundle, selected_refs, expected_context.get("observation_heads", {}), current.learner_id, household_id, heads)
        _validate_attempt_source(bundle, selected_refs, current.learner_id, legibility, answer_text)
        if source_kind in (SourceKind.CLASSROOM_NOTE, SourceKind.COPIED_WORK) and independence is Independence.CONFIRMED_INDEPENDENT:
            raise core.PersistenceError("invalid_input", "课堂笔记或抄录不能标记为已确认独立。")
        if source_kind is SourceKind.INDEPENDENT_ANSWER and independence is Independence.NOT_INDEPENDENT:
            raise core.PersistenceError("invalid_input", "独立作答来源不能同时标记为非独立。")
        if independence is Independence.CONFIRMED_INDEPENDENT and (source_kind is not SourceKind.INDEPENDENT_ANSWER or prompt_status is not PromptStatus.NONE_CONFIRMED):
            raise core.PersistenceError("invalid_input", "确认独立需要独立作答来源，并明确确认没有提示。")
        if attempt_kind is AttemptKind.FIRST and current.previous_attempt_id:
            raise core.PersistenceError("invalid_input", "首次作答不能引用前次作答。")
        prior = current.revisions[-1]
        header = records.header(actor, attempt_id, "补充或更正本次作答元数据", row)
        revision = seal_revision(AttemptRevision(header, qrev.header.revision_id, attempt_kind, source_kind,
            independence, prompt_status, prompts, actual_date_state, actual_date, legibility, answer_text,
            authorship_basis, selected_refs, AttemptState.ACTIVE))
        changed = replace(current, revisions=(*current.revisions, revision))
        return replace(bundle, attempts=tuple(changed if item.attempt_id == attempt_id else item for item in bundle.attempts)), heads, {"revision_id": revision.header.revision_id}

    inputs = {"attempt_id": attempt_id, "attempt_kind": attempt_kind.value, "source_kind": source_kind.value,
              "independence": independence.value, "prompt_status": prompt_status.value, "prompts": prompts,
              "actual_date_state": actual_date_state.value, "actual_date": actual_date, "legibility": legibility.value,
              "answer_text": answer_text, "authorship_basis": authorship_basis, "observation_values": list(observation_values),
              "expected_context": expected_context}
    return records.command(actor, household_id, request_key, "learner_attempt.edit", inputs, build)


@transaction.atomic
def observation_create_context(actor, household_id):
    visible_household(actor, household_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    return {"profiles": bundle.learners}


@transaction.atomic
def save_observation(actor, household_id, *, observation_id=None, profile_context_id=None, legibility,
                     author_state, author_learner_id=None, confirmation_basis="", actual_date_state,
                     actual_date=None, notes, sources, clear_sources=False, expected_context=None,
                     request_key, reason):
    _require_writable(actor, household_id)
    legibility = Legibility(legibility)
    author_state = AuthorState(author_state)
    actual_date_state = ActualDateState(actual_date_state)
    notes = _clean_text(notes, 2000, "观察说明")
    reason = _clean_text(reason, 1000, "修订说明")
    confirmation_basis = _clean_text(confirmation_basis, 1000, "作者确认依据", allow_blank=True)
    actual_date = _date_value(actual_date, actual_date_state)
    if author_state is AuthorState.CONFIRMED:
        if not author_learner_id or not confirmation_basis:
            raise core.PersistenceError("invalid_input", "确认作者时请选择学习者并填写确认依据。")
    else:
        author_learner_id = None
        confirmation_basis = ""
    if observation_id is None and not sources and not notes:
        raise core.PersistenceError("invalid_input", "无来源区域时请说明观察缺少的证据。")

    def build(bundle):
        if profile_context_id and _learner(bundle, profile_context_id) is None:
            raise core.PersistenceError("invalid_input", "关联档案不存在。")
        previous_item = _observation(bundle, observation_id) if observation_id else None
        if observation_id and previous_item is None:
            raise core.PersistenceError("not_found", "来源观察不存在。")
        if previous_item and (profile_context_id or None) != previous_item.profile_context_id:
            raise core.PersistenceError("invalid_input", "档案上下文属于观察稳定身份，不能原地更改。")
        old_row = records.entity(household_id, "observation", observation_id).head_revision if observation_id else None
        heads = records.check_edit(old_row, expected_context) if old_row else {}
        evidence = previous_item.revisions[-1].evidence_refs if previous_item and not sources and not clear_sources else ()
        regions = ()
        if sources:
            regions, evidence = records.source_refs(actor, household_id, sources)
        if not evidence and not notes.strip():
            raise core.PersistenceError("invalid_input", "无来源区域时请说明观察缺少的证据。")
        stable_id = observation_id or _new_id("observation")
        header = records.header(actor, stable_id, reason, old_row)
        revision = seal_revision(ObservationRevision(header, tuple(evidence), legibility, author_state,
            author_learner_id, str(actor.pk) if author_state is AuthorState.CONFIRMED else None,
            timezone.now().isoformat() if author_state is AuthorState.CONFIRMED else None,
            confirmation_basis or None if author_state is AuthorState.CONFIRMED else None,
            actual_date_state, actual_date, notes))
        if previous_item:
            observation = replace(previous_item, revisions=(*previous_item.revisions, revision))
            observations = tuple(observation if item.observation_id == observation_id else item for item in bundle.observations)
        else:
            observation = SourceObservation(stable_id, household_id, profile_context_id or None, (revision,))
            observations = (*bundle.observations, observation)
        return replace(bundle, regions=(*bundle.regions, *regions), observations=observations), heads, {"observation_id": stable_id}

    inputs = {"observation_id": observation_id, "profile_context_id": profile_context_id or None,
              "legibility": legibility.value, "author_state": author_state.value, "author_learner_id": author_learner_id,
              "confirmation_basis": confirmation_basis, "actual_date_state": actual_date_state.value,
              "actual_date": actual_date, "notes": notes, "sources": sources, "clear_sources": clear_sources,
              "expected_context": expected_context, "reason": reason}
    return records.command(actor, household_id, request_key, "learner_observation.save", inputs, build)


@transaction.atomic
def observation_edit_context(actor, observation_id):
    household_id = _entity_household(actor, "observation", observation_id)
    data = records.detail(actor, household_id, "observation", observation_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    observation = _observation(bundle, observation_id)
    row = data["entity"].head_revision
    return {**data, "bundle": bundle, "observation": observation, "household_id": household_id,
            "sources": _source_cards(actor, household_id, bundle, observation.revisions[-1].evidence_refs),
            "profiles": bundle.learners, "page_cards": _page_cards(actor, household_id),
            "edit_context": records.edit_context(row)}


@transaction.atomic
def observation_new_context(actor, household_id):
    household = visible_household(actor, household_id)
    bundle = core.read_snapshot_bundle(actor, household.pk)
    return {"household_id": household.pk, "bundle": bundle, "profiles": bundle.learners,
            "page_cards": _page_cards(actor, household.pk)}


def _page_cards(actor, household_id):
    cards = []
    pages = (MaterialPage.objects.filter(material__household_id=household_id)
             .select_related("image").order_by("material_id", "position"))
    for page in pages:
        options = list(PagePreview.objects.filter(image=page.image).order_by("rotation"))
        preview = next((row for row in options if row.rotation == 0), options[0] if options else None)
        if not preview:
            continue
        page_id = str(page.pk)
        cards.append({"page_id": page_id, "position": page.position, "original_name": page.original_name,
            "preview": preview, "preview_url": reverse("web:page_preview", kwargs={"page_id": page_id, "rotation": preview.rotation}),
            "preview_options": [{"rotation": row.rotation, "width": row.width, "height": row.height,
                "sha256": row.sha256, "url": reverse("web:page_preview", kwargs={"page_id": page_id, "rotation": row.rotation})} for row in options],
            "page_url": reverse("web:page_detail", kwargs={"page_id": page_id})})
    return cards


def _source_cards(actor, household_id, bundle, refs):
    if not refs:
        return []
    image_ids = {ref.image_id for ref in refs}
    image_rows = {row.stable_id: row for row in ImageRecord.objects.filter(
        household_id=household_id, stable_id__in=image_ids)}
    pages = {page.image.stable_id: page for page in MaterialPage.objects.filter(
        material__household_id=household_id, image__stable_id__in=image_ids).select_related("image", "material")}
    regions = {row.header.revision_id: row for row in bundle.regions}
    cards = []
    for ref in refs:
        image = image_rows.get(ref.image_id)
        page = pages.get(ref.image_id)
        if not image or not page:
            cards.append({"missing": True, "ref": ref, "label": "原图页无法定位"})
            continue
        preview = PagePreview.objects.filter(image=image, rotation=0).first()
        if preview is None:
            cards.append({"missing": True, "ref": ref, "label": "原图预览缺失"})
            continue
        region = regions.get(ref.region_revision_id) if ref.region_revision_id else None
        geometry = region.geometry if region else None
        width, height = image.payload["width"], image.payload["height"]
        style = ""
        if geometry and width and height:
            x0, y0, x1, y1 = geometry
            style = (f"left:{100*x0/width:.4f}%;top:{100*y0/height:.4f}%;"
                     f"width:{100*(x1-x0)/width:.4f}%;height:{100*(y1-y0)/height:.4f}%")
        cards.append({"missing": False, "ref": ref, "label": page.original_name or "原图",
            "page_url": reverse("web:page_detail", kwargs={"page_id": str(page.pk)}),
            "preview_url": reverse("web:page_preview", kwargs={"page_id": str(page.pk), "rotation": 0}),
            "region_style": style, "region": region, "purpose": ref.purpose.value})
    return cards


def _evidence_for_attempt(bundle, attempt_revision):
    obs_by_id = {item.observation_id: item for item in bundle.observations}
    refs, seen = [], set()
    for obsref in attempt_revision.observation_refs:
        observation = obs_by_id.get(obsref.observation_id)
        revision = next((row for row in observation.revisions if row.header.revision_id == obsref.observation_revision_id), None) if observation else None
        if revision:
            for ref in revision.evidence_refs:
                if ref not in seen:
                    seen.add(ref)
                    refs.append(ref)
    return tuple(refs)


@transaction.atomic
def attempt_detail(actor, attempt_id):
    household_id = _entity_household(actor, "attempt", attempt_id)
    data = records.detail(actor, household_id, "attempt", attempt_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    attempt = _attempt(bundle, attempt_id)
    learner = _learner(bundle, attempt.learner_id)
    question = _question(bundle, attempt.question_id)
    current = attempt.revisions[-1]
    assessments = _actual_assessments(actor, household_id, bundle, attempt)
    evidence = _evidence_for_attempt(bundle, current)
    histories = []
    for revision in attempt.revisions:
        histories.append({"revision": revision, "sources": _source_cards(actor, household_id, bundle, _evidence_for_attempt(bundle, revision))})
    return {**data, "bundle": bundle, "household_id": household_id, "attempt": attempt,
        "learner": learner, "question": question, "current_revision": current,
        "sources": _source_cards(actor, household_id, bundle, evidence),
        "history": histories, "assessments": assessments,
        "independent_success": _independent_success(actor, household_id, bundle, attempt, assessments)}


@transaction.atomic
def assessment_context(actor, attempt_id):
    household_id = _entity_household(actor, "attempt", attempt_id)
    data = records.detail(actor, household_id, "attempt", attempt_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    attempt = _attempt(bundle, attempt_id)
    choices = _assessment_evidence_choices(bundle, attempt.revisions[-1])
    eligible_errata = _accepted_errata(actor, household_id, bundle)
    row = data["entity"].head_revision
    context = {"attempt_edit_context": records.edit_context(row),
               "attempt_revision_id": attempt.revisions[-1].header.revision_id}
    return {"household_id": household_id, "attempt": attempt, "bundle": bundle,
        "question_revision_id": attempt.revisions[-1].question_revision_id,
        "context": context, "evidence_choices": choices, "errata_choices": eligible_errata}


def _assessment_evidence_choices(bundle, attempt_revision):
    refs = _evidence_for_attempt(bundle, attempt_revision)
    return [(str(index), f"来源 {index + 1} · {'已选区域' if ref.region_id else '整张原图'} · {ui_label(ref.purpose.value)}")
            for index, ref in enumerate(refs)], refs


def _accepted_errata(actor, household_id, bundle):
    result = []
    rev_ids = [revision.header.revision_id for item in bundle.errata for revision in item.revisions]
    rows = (RevisionRecord.objects.filter(pk__in=rev_ids, entity__household_id=household_id,
            review_projection__state="accepted", entity__published_revision_id__isnull=False)
            .select_related("entity", "review_projection"))
    for row in rows:
        if row.entity.published_revision_id != row.pk:
            continue
        erratum = next((item for item in bundle.errata if any(rev.header.revision_id == row.pk for rev in item.revisions)), None)
        if erratum:
            result.append((row.pk, f"{row.payload['printed_text'][:90]} → {row.payload['corrected_text'][:90]}"))
    return sorted(result)


def _assessment_dimensions(values, evidence_refs, attempt_revision):
    dimensions = []
    for kind in DIMENSIONS:
        key = kind.value
        row = values[key]
        judgment = Judgment(row["judgment"])
        basis = BasisKind(row["basis"])
        chosen = row.get("evidence", [])
        refs = []
        for raw_index in chosen:
            try:
                if isinstance(raw_index, bool):
                    raise ValueError
                index = int(raw_index)
                if index < 0 or index >= len(evidence_refs) or str(index) != str(raw_index):
                    raise ValueError
                ref = evidence_refs[index]
            except (TypeError, ValueError, IndexError) as exc:
                raise core.PersistenceError("invalid_input", "评价证据选择无效。") from exc
            if ref not in refs:
                refs.append(ref)
        rationale = _clean_text(row.get("rationale", ""), 2000, f"{key}评价依据", allow_blank=True)
        unknown_reason = _clean_text(row.get("unknown_reason", ""), 1000, f"{key}未知原因", allow_blank=True) or None
        if judgment is Judgment.UNKNOWN and not unknown_reason:
            raise core.PersistenceError("invalid_input", f"{key}标为无法判断时必须写明未知原因。")
        if basis is BasisKind.UNDETERMINED and not unknown_reason:
            raise core.PersistenceError("invalid_input", f"{key}依据尚未确定时必须说明原因。")
        if basis is BasisKind.INFERRED and not rationale:
            raise core.PersistenceError("invalid_input", f"{key}为推测判断时必须说明推测依据。")
        if judgment is Judgment.CORRECT:
            if (basis is not BasisKind.OBSERVED or not refs or attempt_revision.legibility is not Legibility.READABLE):
                raise core.PersistenceError("invalid_input", f"{key}只有在笔迹清楚且有直接区域证据时才能标记正确。")
        if basis is BasisKind.OBSERVED and judgment is not Judgment.UNKNOWN and not refs:
            raise core.PersistenceError("invalid_input", f"{key}的已观察判断必须关联原图区域。")
        if judgment is not Judgment.UNKNOWN and basis is not BasisKind.UNDETERMINED:
            unknown_reason = None
        dimensions.append(AssessmentDimension(kind, judgment, basis, tuple(refs), rationale, unknown_reason))
    if not any(d.dimension is DimensionKind.ANSWER for d in dimensions) or not any(d.dimension is DimensionKind.PROCESS for d in dimensions):
        raise core.PersistenceError("invalid_input", "评价必须分别包含答案和过程维度。")
    return tuple(dimensions)


@transaction.atomic
def assessment_edit_context(actor, assessment_id):
    household_id = _entity_household(actor, "assessment", assessment_id)
    data = records.detail(actor, household_id, "assessment", assessment_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    assessment = _assessment(bundle, assessment_id)
    attempt = _attempt(bundle, assessment.attempt_id)
    evidence_choices, evidence_refs = _assessment_evidence_choices(bundle, attempt.revisions[-1])
    context = {"assessment_edit_context": records.edit_context(data["entity"].head_revision),
               "attempt_edit_context": records.edit_context(records.entity(household_id, "attempt", attempt.attempt_id).head_revision),
               "attempt_revision_id": attempt.revisions[-1].header.revision_id}
    return {**data, "household_id": household_id, "bundle": bundle, "assessment": assessment,
            "attempt": attempt, "evidence_choices": evidence_choices, "evidence_refs": evidence_refs,
            "errata_choices": _accepted_errata(actor, household_id, bundle), "context": context}


@transaction.atomic
def save_assessment(actor, attempt_id, *, values, context, request_key, assessment_id=None, reason=""):
    household_id = _entity_household(actor, "attempt", attempt_id)
    context_key = "assessment_edit_context" if assessment_id else "attempt_edit_context"
    edit_context = context.get(context_key)
    attempt_edit_context = context.get("attempt_edit_context")
    if not isinstance(edit_context, dict):
        raise core.PersistenceError("stale_context", "评价编辑凭据无效，请重新打开页面。")
    context_attempt_revision = context.get("attempt_revision_id")
    context_errata = tuple(values.get("context_errata", []))

    def build(bundle):
        attempt = _attempt(bundle, attempt_id)
        if attempt is None:
            raise core.PersistenceError("not_found", "作答不存在。")
        attempt_row = records.entity(household_id, "attempt", attempt_id).head_revision
        if not isinstance(attempt_edit_context, dict) or records.edit_context(attempt_row) != attempt_edit_context:
            raise core.PersistenceError("head_conflict", "作答或来源已改变，请重新打开页面。")
        if attempt.revisions[-1].header.revision_id != context_attempt_revision:
            raise core.PersistenceError("head_conflict", "作答版本已改变，请重新打开页面。")
        heads = records.check_edit(attempt_row, attempt_edit_context)
        attempt_revision = attempt.revisions[-1]
        question_revision = attempt_revision.question_revision_id
        evidence_refs = _evidence_for_attempt(bundle, attempt_revision)
        dimensions = _assessment_dimensions(values, evidence_refs, attempt_revision)
        valid_errata = {item[0] for item in _accepted_errata(actor, household_id, bundle)}
        if set(context_errata) - valid_errata:
            raise core.PersistenceError("stale_context", "所选讲义勘误不再是当前已审核版本。")
        if assessment_id:
            assessment = _assessment(bundle, assessment_id)
            if assessment is None or assessment.attempt_id != attempt_id:
                raise core.PersistenceError("not_found", "评价与作答不匹配。")
            assessment_row = records.entity(household_id, "assessment", assessment_id).head_revision
            if records.edit_context(assessment_row) != context["assessment_edit_context"]:
                raise core.PersistenceError("head_conflict", "评价或其依赖已改变，请重新打开页面。")
            assessment_heads = records.check_edit(assessment_row, context["assessment_edit_context"])
            heads.update(assessment_heads)
            stable_id = assessment_id
            prior = assessment.revisions[-1]
            header = records.header(actor, stable_id, reason or "补充人工过程评价", assessment_row)
            revision = seal_revision(AssessmentRevision(header, attempt_revision.header.revision_id,
                question_revision, ReviewState.DRAFT, None, dimensions, context_errata))
            assessment = replace(assessment, revisions=(*assessment.revisions, revision))
            assessments = tuple(assessment if item.assessment_id == stable_id else item for item in bundle.assessments)
        else:
            stable_id = _new_id("assessment")
            header = records.header(actor, stable_id, reason or "新增人工过程评价")
            revision = seal_revision(AssessmentRevision(header, attempt_revision.header.revision_id,
                question_revision, ReviewState.DRAFT, None, dimensions, context_errata))
            assessment = Assessment(stable_id, household_id, attempt_id, (revision,))
            assessments = (*bundle.assessments, assessment)
        return replace(bundle, assessments=assessments), heads, {"assessment_id": stable_id,
                                                                  "revision_id": revision.header.revision_id}

    fingerprint_values = {key: (list(value) if isinstance(value, (list, tuple)) else value)
                          for key, value in values.items()}
    inputs = {"attempt_id": attempt_id, "assessment_id": assessment_id, "values": fingerprint_values,
              "context": context, "reason": reason}
    return records.command(actor, household_id, request_key, "learner_assessment.save", inputs, build)


@transaction.atomic
def review_assessment(actor, assessment_id, revision_id, *, action, reason, context, request_key):
    household_id = _entity_household(actor, "assessment", assessment_id)
    item = records.entity(household_id, "assessment", assessment_id)
    if not item.revisions.filter(pk=revision_id).exists():
        raise core.PersistenceError("not_found", "评价版本不存在。")
    return records.review(actor, household_id, "assessment", assessment_id, revision_id,
                          action=action, reason=reason, context=context, request_key=request_key)


@transaction.atomic
def review_form_context(actor, assessment_id):
    household_id = _entity_household(actor, "assessment", assessment_id)
    data = records.detail(actor, household_id, "assessment", assessment_id)
    return {**data, "household_id": household_id,
            "review_context": core.review_context(actor, household_id, data["entity"].head_revision_id)}


@transaction.atomic
def assessment_detail(actor, assessment_id):
    household_id = _entity_household(actor, "assessment", assessment_id)
    data = records.detail(actor, household_id, "assessment", assessment_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    assessment = _assessment(bundle, assessment_id)
    attempt = _attempt(bundle, assessment.attempt_id)
    attempt_revision = attempt.revisions[-1]
    details = []
    for revision in assessment.revisions:
        row = RevisionRecord.objects.select_related("review_projection").get(pk=revision.header.revision_id)
        details.append({"revision": revision, "state": row.review_projection.state,
                        "current": data["entity"].head_revision_id == row.pk,
                        "published": data["entity"].published_revision_id == row.pk})
    current_revision = next((item for item in assessment.revisions
        if item.header.revision_id == data["entity"].head_revision_id), None)
    if current_revision is None:
        raise core.PersistenceError("missing_revision", "当前评价修订不存在。")
    evaluated_attempt_revision = next((item for item in attempt.revisions
        if item.header.revision_id == current_revision.attempt_revision_id), attempt.revisions[-1])
    dimensions = [{"dimension": item,
                   "sources": _source_cards(actor, household_id, bundle, item.evidence_refs)}
                  for item in current_revision.dimensions]
    return {**data, "bundle": bundle, "household_id": household_id, "assessment": assessment,
            "attempt": attempt, "attempt_revision": attempt_revision,
            "evaluated_attempt_revision": evaluated_attempt_revision, "history": details,
            "sources": _source_cards(actor, household_id, bundle, _evidence_for_attempt(bundle, attempt_revision)),
            "current_revision": current_revision, "dimensions": dimensions}
