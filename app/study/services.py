"""Household-scoped study plans, evidence reports and generated variants."""
from dataclasses import replace
from datetime import date
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from app.domain import (
    Origin, Question, QuestionRevision, ReviewState, RevisionHeader, seal_revision,
)
from app.domain.arithmetic import ArithmeticError as FormulaError, check_arithmetic
from app.domain.contracts import ContractError, EvidencePurpose
from app.persistence import services as core
from app.persistence.adapter import ObjectKey
from app.persistence.models import EntityRecord, RevisionRecord, ReviewProjection
from app.web import learning_services as learning
from app.web.learning_labels import (
    ATTEMPT_KIND_LABELS, ATTEMPT_STATE_LABELS, BASIS_LABELS, DIMENSION_LABELS, INDEPENDENCE_LABELS,
    JUDGMENT_LABELS, LEGIBILITY_LABELS, PROMPT_STATUS_LABELS, REVIEW_STATE_LABELS,
    SOURCE_KIND_LABELS, label as learning_label,
)
from app.web import records
from .models import ScheduleRevision, StudySchedule, VariantProvenance


def _clean_text(value, label, limit, *, allow_blank=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise core.PersistenceError("invalid_input", f"{label}内容无效。")
    value = value.strip()
    if not value and not allow_blank:
        raise core.PersistenceError("invalid_input", f"请填写{label}。")
    return value


def _date_value(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise core.PersistenceError("invalid_input", "计划日期无效。") from exc
    raise core.PersistenceError("invalid_input", "请填写计划日期。")


def _entity(actor, entity_pk, kind):
    row = EntityRecord.objects.filter(pk=entity_pk, kind=kind).select_related("household").first()
    if row is None:
        raise core.PersistenceError("not_found", "记录不存在。")
    records.household(actor, row.household_id)
    return row


def _accepted_current_revision(household_id, kind, revision_id, *, require_head=True):
    revision = (RevisionRecord.objects.filter(pk=revision_id, entity__household_id=household_id,
        entity__kind=kind).select_related("entity", "review_projection").first())
    if (revision is None or (require_head and revision.entity.head_revision_id != revision.pk)
            or revision.entity.published_revision_id != revision.pk
            or revision.review_projection.state != "accepted"):
        raise core.PersistenceError("stale_context", "目标必须是当前已接受并发布的精确版本。")
    return revision


def _study_command(actor, household_id, request_key, action, inputs, build):
    """Commit app-specific append-only rows with the shared web_record receipt."""
    household = records.household(actor, household_id, write=True)
    try:
        fingerprint = core._digest({"action": action, "inputs": inputs})
    except (TypeError, ValueError) as exc:
        raise core.PersistenceError("invalid_input", "请求内容无效。") from exc
    replay = core._replay(household, actor, request_key, "web_record", fingerprint)
    if replay:
        return replay
    try:
        bundle = core.read_snapshot_bundle(actor, household_id)
        new_bundle, expected_heads, result, persist = build(bundle)
        core.stage_bundle(actor, new_bundle, request_key=f"study-stage-{uuid4().hex}",
                          expected_heads=expected_heads)
        persist()
    except core.PersistenceError:
        raise
    except ContractError as exc:
        raise core.PersistenceError("invalid_input", "记录不符合当前来源或版本约束。") from exc
    return core._receipt(household, actor, request_key, "web_record", fingerprint, result)


@transaction.atomic
def home(actor, household_id=None):
    households = list(learning.household_options(actor))
    if household_id in (None, ""):
        household_id = str(households[0].household_id) if households else ""
    if not household_id:
        return {"households": households, "household_id": "", "profiles": [],
                "schedules": [], "questions": [], "writable": False}
    membership = next((item for item in households if str(item.household_id) == str(household_id)), None)
    if membership is None:
        raise core.PersistenceError("permission_denied", "无权访问该家庭。")
    data = learning.profile_list(actor, household_id)
    bundle = core.read_snapshot_bundle(actor, household_id)
    profiles = {item.learner_id: item for item in bundle.learners}
    learner_entities = {row.stable_id: row for row in EntityRecord.objects.filter(
        household_id=household_id, kind="learner", stable_id__in=profiles)}
    schedule_rows = (StudySchedule.objects.filter(household_id=household_id)
        .select_related("learner", "target_question_revision", "target_question_revision__entity")
        .prefetch_related("revisions").order_by("-created_at", "-pk"))
    schedules = []
    for row in schedule_rows:
        history = list(row.revisions.all())
        latest = history[-1] if history else None
        target = row.target_question_revision
        schedules.append({
            "schedule": row,
            "learner": profiles.get(row.learner.stable_id),
            "latest": latest,
            "history": history,
            "target_question_revision": target,
            "target_question": target.payload,
            "target_stale": target.entity.published_revision_id != target.pk,
            "active": bool(latest and latest.action in (ScheduleRevision.Action.PLANNED,
                                                         ScheduleRevision.Action.RESCHEDULED)),
        })
    variants = []
    variant_rows = (VariantProvenance.objects.filter(household_id=household_id)
        .select_related("question", "parent_question_revision", "target_method_revision",
                        "question__head_revision", "question__published_revision")
        .order_by("-created_at", "-pk"))
    for provenance in variant_rows:
        head = provenance.question.head_revision
        variants.append({"provenance": provenance,
            "question_id": provenance.question.stable_id,
            "generated_text": provenance.generated_text,
            "parent_text": provenance.parent_question_revision.payload.get("working_text")
                or provenance.parent_question_revision.payload.get("printed_text") or "题干待补",
            "method_name": provenance.target_method_revision.payload.get("name") or "方法待补",
            "review_state": head.review_projection.state if head else "missing",
            "current": bool(head and provenance.question.published_revision_id == head.pk),
        })
    profile_links = [{"profile": profile, "entity_pk": learner_entities[profile.learner_id].pk}
        for profile in sorted(bundle.learners, key=lambda item: item.display_name.casefold())
        if profile.learner_id in learner_entities]
    return {"households": households, "household_id": str(household_id),
            "profiles": sorted(bundle.learners, key=lambda item: item.display_name.casefold()),
            "profile_links": profile_links, "questions": data["questions"],
            "schedules": schedules, "variants": variants,
            "writable": membership.role in ("owner", "reviewer")}


@transaction.atomic
def new_schedule_context(actor, learner_entity_pk):
    learner = _entity(actor, learner_entity_pk, "learner")
    data = learning.profile_list(actor, learner.household_id)
    profile = next((item for item in data["profiles"] if item.learner_id == learner.stable_id), None)
    if profile is None:
        raise core.PersistenceError("not_found", "学习者档案不存在。")
    question_versions = {item["question_id"]: item["revision_id"] for item in data["questions"]}
    question_heads = {item["question_id"]: item["head_revision_id"] for item in data["questions"]}
    context = {"learner_entity_pk": learner.pk, "learner_id": learner.stable_id,
               "question_versions": question_versions, "question_heads": question_heads}
    return {"household_id": learner.household_id, "learner": profile,
            "questions": data["questions"], "context": context}


@transaction.atomic
def create_schedule(actor, learner_entity_pk, *, question_revision_id, due_date, goal,
                    prompt_plan="", reason, context, request_key):
    learner = _entity(actor, learner_entity_pk, "learner")
    household_id = str(learner.household_id)
    if (not isinstance(context, dict) or context.get("learner_entity_pk") != learner.pk
            or context.get("learner_id") != learner.stable_id
            or not isinstance(context.get("question_versions"), dict)
            or not isinstance(context.get("question_heads"), dict)):
        raise core.PersistenceError("stale_context", "计划创建凭据无效，请重新打开。")
    due_date = _date_value(due_date)
    goal = _clean_text(goal, "目标说明", 1200)
    prompt_plan = _clean_text(prompt_plan, "提示安排", 2000, allow_blank=True)
    reason = _clean_text(reason, "计划依据", 1000)
    question = RevisionRecord.objects.filter(pk=question_revision_id, entity__household_id=household_id,
        entity__kind="question").select_related("entity").first()
    if question is None or context["question_versions"].get(question.entity.stable_id) != question.pk:
        raise core.PersistenceError("stale_context", "所选题目已改变，请重新打开计划页面。")
    expected_head = context["question_heads"].get(question.entity.stable_id)
    if expected_head is None:
        raise core.PersistenceError("stale_context", "题目版本已改变，请重新打开计划页面。")

    def build(bundle):
        if (learner.household_id != household_id or learner.kind != "learner"
                or not any(item.learner_id == learner.stable_id for item in bundle.learners)):
            raise core.PersistenceError("not_found", "学习者档案不存在。")
        exact = _accepted_current_revision(household_id, "question", question.pk, require_head=False)
        expected = {
            ObjectKey("learner", learner.stable_id): None,
            ObjectKey("question", exact.entity.stable_id): expected_head,
        }
        schedule_id = uuid4()
        result = {"schedule_pk": None, "schedule_id": str(schedule_id)}

        def persist():
            schedule = StudySchedule.objects.create(schedule_id=schedule_id, household_id=household_id,
                learner=learner, target_question_revision=exact, created_by=actor)
            ScheduleRevision.objects.create(schedule=schedule, revision_no=1,
                action=ScheduleRevision.Action.PLANNED, due_date=due_date, goal=goal,
                prompt_plan=prompt_plan, reason=reason, previous=None, recorded_by=actor)
            result["schedule_pk"] = schedule.pk

        return bundle, expected, result, persist

    inputs = {"learner_entity_pk": learner_entity_pk, "question_revision_id": question_revision_id,
              "due_date": due_date.isoformat(), "goal": goal, "prompt_plan": prompt_plan,
              "reason": reason, "context": context}
    return _study_command(actor, household_id, request_key, "study_schedule.create", inputs, build)


@transaction.atomic
def stage_variant(actor, household_id, run_id, *, parent_question_revision_id,
                  target_method_revision_id, text, answer_expression, check_expression,
                  source_revision_ids, request_key):
    """Stage one validated AI variant as a shared, reviewable question draft."""
    household_id = str(household_id)
    parent_question_revision_id = str(parent_question_revision_id)
    target_method_revision_id = str(target_method_revision_id)
    if (not isinstance(source_revision_ids, list)
            or any(not isinstance(value, str) for value in source_revision_ids)
            or len(source_revision_ids) != len(set(source_revision_ids))):
        raise core.PersistenceError("invalid_input", "变式来源版本无效。")
    for value, label, limit in ((text, "变式题干", 12000),
                                (answer_expression, "答案公式", 512),
                                (check_expression, "复核公式", 512)):
        if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
            raise core.PersistenceError("invalid_input", f"{label}内容无效。")
    inputs = {"household_id": household_id, "run_id": str(run_id),
        "parent_question_revision_id": parent_question_revision_id,
        "target_method_revision_id": target_method_revision_id, "text": text,
        "answer_expression": answer_expression, "check_expression": check_expression,
        "source_revision_ids": source_revision_ids}

    def build(bundle):
        from app.ai.services import validated_variant_run

        trusted = validated_variant_run(actor, str(run_id), household_id=household_id,
            parent_question_revision_id=parent_question_revision_id,
            target_method_revision_id=target_method_revision_id, text=text,
            answer_expression=answer_expression, check_expression=check_expression,
            source_revision_ids=source_revision_ids, request_key=request_key)
        parent = _accepted_current_revision(household_id, "question",
                                             trusted["parent_question_revision_id"])
        method = _accepted_current_revision(household_id, "method",
                                             trusted["target_method_revision_id"])
        source_rows = trusted["source_revisions"]
        if (method.pk not in trusted["source_revision_ids"]
                or len(source_rows) != len(trusted["source_revision_ids"])):
            raise core.PersistenceError("stale_context", "变式来源已不可用。")
        for source in source_rows:
            _accepted_current_revision(household_id, source.entity.kind, source.pk)
        try:
            math = check_arithmetic(trusted["answer_expression"], trusted["check_expression"])
        except FormulaError as exc:
            raise core.PersistenceError("invalid_input", "变式公式无法复算。") from exc
        if math["matches"] is not True:
            raise core.PersistenceError("invalid_input", "变式答案与复核公式不一致。")

        parent_question = next((item for item in bundle.questions
            if item.question_id == parent.entity.stable_id), None)
        parent_domain_revision = next((item for item in parent_question.revisions
            if item.header.revision_id == parent.pk), None) if parent_question else None
        if not parent_domain_revision or not parent_domain_revision.evidence_refs:
            raise core.PersistenceError("invalid_input", "父题缺少可追溯的图像生成依据，不能生成变式。")
        evidence_refs = tuple(replace(ref, purpose=EvidencePurpose.OTHER, sequence=index)
            for index, ref in enumerate(parent_domain_revision.evidence_refs, 1))

        question_id = f"ai-variant-{uuid4().hex}"
        revision = seal_revision(QuestionRevision(
            RevisionHeader(f"ai-variant-rev-{uuid4().hex}", question_id, 1, None,
                str(actor.pk), timezone.now().isoformat(), Origin.AI, "AI 生成变式草稿", ""),
            ReviewState.DRAFT, parent.pk, None, trusted["text"], (), evidence_refs, ()))
        question = Question(question_id, household_id, parent.entity.stable_id, (revision,))
        new_bundle = replace(bundle, questions=(*bundle.questions, question))
        provenance_source_revision_ids = list(dict.fromkeys(
            [trusted["parent_question_revision_id"], *trusted["source_revision_ids"]]))
        expected = {ObjectKey(item["kind"], item["stable_id"]): item["head_revision_id"]
            for item in trusted["expected_heads"]}
        expected[ObjectKey("question", question_id)] = None
        result = {"question_id": question_id, "revision_id": revision.header.revision_id}

        def persist():
            question_row = EntityRecord.objects.get(household_id=household_id,
                kind="question", stable_id=question_id)
            VariantProvenance.objects.create(question=question_row,
                household_id=household_id, run_id=str(trusted["run"].pk),
                parent_question_revision=parent, target_method_revision=method,
                generated_text=trusted["text"],
                answer_expression=trusted["answer_expression"],
                check_expression=trusted["check_expression"],
                source_revision_ids=provenance_source_revision_ids, created_by=actor)

        return new_bundle, expected, result, persist

    return _study_command(actor, household_id, request_key, "study_variant.stage", inputs, build)


@transaction.atomic
def validate_variant_publication(actor, question_revision_id):
    """Recheck the real applied run and exact sources before a variant is published."""
    revision = (RevisionRecord.objects.filter(pk=question_revision_id, entity__kind="question")
        .select_related("entity", "review_projection").first())
    if revision is None:
        raise core.PersistenceError("not_found", "题目修订不存在。")
    provenance = (VariantProvenance.objects.filter(question=revision.entity)
        .select_related("question", "parent_question_revision", "target_method_revision").first())
    if provenance is None:
        return None

    from app.ai.models import ModelRun

    records.household(actor, provenance.household_id, write=True)
    run = ModelRun.objects.filter(pk=provenance.run_id, household_id=provenance.household_id).first()
    proposal = run.response.get("proposal") if run and isinstance(run.response, dict) else None
    revision_header = revision.payload.get("header")
    if (run is None or run.task_kind != ModelRun.TaskKind.VARIANT
            or run.status != ModelRun.Status.APPLIED
            or run.actor_id != provenance.created_by_id
            or revision.entity.household_id != provenance.household_id
            or revision.entity.head_revision_id != revision.pk
            or not isinstance(revision_header, dict)
            or revision_header.get("origin") != Origin.AI.value
            or revision.pk not in run.output_revision_ids
            or revision.payload.get("parent_question_revision_id") != provenance.parent_question_revision_id
            or revision.payload.get("working_text") != provenance.generated_text
            or revision.payload.get("missing_fields")
            or run.question_revision_ids != [provenance.parent_question_revision_id]
            or list(dict.fromkeys([provenance.parent_question_revision_id, *run.source_revision_ids]))
                != provenance.source_revision_ids
            or provenance.target_method_revision_id not in run.source_revision_ids
            or not isinstance(proposal, dict)
            or proposal.get("text") != provenance.generated_text
            or proposal.get("answer_expression") != provenance.answer_expression
            or proposal.get("check_expression") != provenance.check_expression
            or proposal.get("target_method_revision_id") != provenance.target_method_revision_id):
        raise core.PersistenceError("stale_context", "变式须对应真实、已应用且未过期的模型任务。")

    for item in (*run.expected_heads, *run.expected_dependencies):
        entity = EntityRecord.objects.filter(household_id=provenance.household_id,
            kind=item["kind"], stable_id=item["stable_id"]).only("head_revision_id").first()
        if (entity.head_revision_id if entity else None) != item["head_revision_id"]:
            raise core.PersistenceError("stale_context", "变式来源或依赖已改变。")
    for item in run.review_pointers:
        pointer = ReviewProjection.objects.filter(revision_id=item["revision_id"]).first()
        if (pointer is None or pointer.state != item["state"]
                or (str(pointer.decision_id) if pointer.decision_id else None) != item["decision_id"]):
            raise core.PersistenceError("stale_context", "变式来源审核状态已改变。")

    _accepted_current_revision(provenance.household_id, "question",
                               provenance.parent_question_revision_id)
    _accepted_current_revision(provenance.household_id, "method",
                               provenance.target_method_revision_id)
    source_rows = RevisionRecord.objects.filter(pk__in=provenance.source_revision_ids,
        entity__household_id=provenance.household_id).select_related("entity")
    if source_rows.count() != len(provenance.source_revision_ids):
        raise core.PersistenceError("stale_context", "变式来源版本已不可用。")
    for source in source_rows:
        _accepted_current_revision(provenance.household_id, source.entity.kind, source.pk)
    try:
        math = check_arithmetic(provenance.answer_expression, provenance.check_expression)
    except FormulaError as exc:
        raise core.PersistenceError("invalid_input", "变式公式无法复算。") from exc
    if math["matches"] is not True:
        raise core.PersistenceError("invalid_input", "变式答案与复核公式不一致。")
    return {"run_id": str(run.pk), "revision_id": revision.pk}


def _schedule(actor, schedule_pk):
    row = (StudySchedule.objects.filter(pk=schedule_pk).select_related(
        "household", "learner", "target_question_revision", "target_question_revision__entity").first())
    if row is None:
        raise core.PersistenceError("not_found", "复习计划不存在。")
    records.household(actor, row.household_id)
    if row.learner.kind != "learner":
        raise core.PersistenceError("not_found", "复习计划学习者不存在。")
    return row


@transaction.atomic
def schedule_detail(actor, schedule_pk):
    schedule = _schedule(actor, schedule_pk)
    revisions = list(schedule.revisions.select_related(
        "completed_attempt_revision", "recorded_by").order_by("revision_no"))
    latest = revisions[-1] if revisions else None
    target = schedule.target_question_revision
    bundle = core.read_snapshot_bundle(actor, schedule.household_id)
    profile = next((item for item in bundle.learners if item.learner_id == schedule.learner.stable_id), None)
    question = next((item for item in bundle.questions
        if any(rev.header.revision_id == target.pk for rev in item.revisions)), None)
    attempt_revisions = {revision.header.revision_id: (attempt, revision)
        for attempt in bundle.attempts for revision in attempt.revisions}
    completions = []
    for event in revisions:
        bound = attempt_revisions.get(event.completed_attempt_revision_id)
        if bound:
            attempt, revision = bound
            completions.append({"event": event, "attempt": attempt, "revision": revision,
                "actual_date": revision.actual_date if revision.actual_date_state.value == "known" else None,
                "recorded_at": revision.header.recorded_at})
        elif event.action == ScheduleRevision.Action.COMPLETED:
            completions.append({"event": event, "attempt": None, "revision": None,
                "actual_date": None, "recorded_at": None})
    context = {"schedule_pk": schedule.pk,
        "head_revision_id": latest.pk if latest else None,
        "revision_no": latest.revision_no if latest else 0}
    return {"schedule": schedule, "history": revisions, "current_revision": latest,
        "learner": profile, "question": question, "target_question_revision": target,
        "target_stale": target.entity.published_revision_id != target.pk,
        "completion_history": completions, "household_id": str(schedule.household_id),
        "context": context}


@transaction.atomic
def schedule_attempt_choices(actor, schedule_pk):
    schedule = _schedule(actor, schedule_pk)
    latest = schedule.revisions.order_by("-revision_no").first()
    if latest is None or latest.action not in (ScheduleRevision.Action.PLANNED,
                                               ScheduleRevision.Action.RESCHEDULED):
        return {"schedule": schedule, "choices": []}
    bundle = core.read_snapshot_bundle(actor, schedule.household_id)
    choices = []
    for attempt in bundle.attempts:
        if attempt.learner_id != schedule.learner.stable_id or attempt.question_id != schedule.target_question_revision.entity.stable_id:
            continue
        revision = attempt.revisions[-1]
        if revision.question_revision_id != schedule.target_question_revision_id:
            continue
        entity = EntityRecord.objects.filter(household_id=schedule.household_id, kind="attempt",
            stable_id=attempt.attempt_id).only("head_revision_id").first()
        if revision.state.value != "active" or entity is None or entity.head_revision_id != revision.header.revision_id:
            continue
        actual_date = revision.actual_date if revision.actual_date_state.value == "known" else None
        label = f"{revision.actual_date or '实际日期未知'} · {revision.source_kind.value} · {attempt.attempt_id}"
        choices.append({"attempt": attempt, "revision": revision, "label": label,
                        "actual_date": actual_date, "recorded_at": revision.header.recorded_at})
    return {"schedule": schedule, "choices": choices}


@transaction.atomic
def append_schedule_event(actor, schedule_pk, *, action, context, due_date=None, goal=None,
                          prompt_plan=None, attempt_revision_id=None, reason, request_key):
    schedule = _schedule(actor, schedule_pk)
    household_id = str(schedule.household_id)
    try:
        action = ScheduleRevision.Action(action)
    except ValueError as exc:
        raise core.PersistenceError("invalid_input", "复习计划操作无效。") from exc
    if action is ScheduleRevision.Action.PLANNED:
        raise core.PersistenceError("invalid_input", "计划只能在创建时建立。")
    reason = _clean_text(reason, "变更依据", 1000)

    def build(bundle):
        actual = _schedule(actor, schedule_pk)
        events = list(actual.revisions.order_by("revision_no"))
        latest = events[-1] if events else None
        expected = context if isinstance(context, dict) else {}
        if (expected.get("schedule_pk") != actual.pk
                or expected.get("head_revision_id") != (latest.pk if latest else None)
                or expected.get("revision_no") != (latest.revision_no if latest else 0)):
            raise core.PersistenceError("head_conflict", "计划已经变更，请重新打开。")
        if latest is None or latest.action not in (ScheduleRevision.Action.PLANNED,
                                                   ScheduleRevision.Action.RESCHEDULED):
            raise core.PersistenceError("invalid_input", "已取消或完成的计划不能继续更改。")
        exact_attempt = None
        if action is ScheduleRevision.Action.RESCHEDULED:
            next_due_date = _date_value(due_date)
            next_goal = _clean_text(goal or "", "目标说明", 1200)
            next_prompts = _clean_text(prompt_plan or "", "提示安排", 2000, allow_blank=True)
        elif action is ScheduleRevision.Action.COMPLETED:
            if not attempt_revision_id:
                raise core.PersistenceError("invalid_input", "完成计划必须选择一次实际作答。")
            exact_attempt = RevisionRecord.objects.filter(pk=attempt_revision_id,
                entity__household_id=household_id, entity__kind="attempt").select_related("entity").first()
            pair = next(((attempt, revision) for attempt in bundle.attempts
                for revision in attempt.revisions if revision.header.revision_id == attempt_revision_id), None)
            if (exact_attempt is None or pair is None or exact_attempt.entity.head_revision_id != exact_attempt.pk
                    or pair[0].learner_id != actual.learner.stable_id
                    or pair[1].state.value != "active"
                    or pair[1].question_revision_id != actual.target_question_revision_id):
                raise core.PersistenceError("invalid_input", "完成记录须绑定同一学习者、同一精确题目版本的当前有效作答。")
            next_due_date, next_goal, next_prompts = latest.due_date, latest.goal, latest.prompt_plan
        elif action is ScheduleRevision.Action.CANCELLED:
            next_due_date, next_goal, next_prompts = latest.due_date, latest.goal, latest.prompt_plan
        else:
            raise core.PersistenceError("invalid_input", "复习计划操作无效。")
        heads = {
            ObjectKey("learner", actual.learner.stable_id): None,
            ObjectKey("question", actual.target_question_revision.entity.stable_id):
                actual.target_question_revision.entity.head_revision_id,
        }
        if exact_attempt is not None:
            heads[ObjectKey("attempt", exact_attempt.entity.stable_id)] = exact_attempt.pk
        next_event = {"revision_no": latest.revision_no + 1, "action": action,
            "due_date": next_due_date, "goal": next_goal, "prompt_plan": next_prompts,
            "attempt": exact_attempt, "previous": latest}

        def persist():
            ScheduleRevision.objects.create(schedule=actual, revision_no=next_event["revision_no"],
                action=next_event["action"], due_date=next_event["due_date"],
                goal=next_event["goal"], prompt_plan=next_event["prompt_plan"],
                completed_attempt_revision=next_event["attempt"], reason=reason,
                previous=next_event["previous"], recorded_by=actor)

        return bundle, heads, {"schedule_pk": actual.pk, "action": action.value}, persist

    inputs = {"schedule_pk": schedule.pk, "action": action.value, "context": context,
              "due_date": due_date.isoformat() if isinstance(due_date, date) else due_date,
              "goal": goal, "prompt_plan": prompt_plan,
              "attempt_revision_id": attempt_revision_id, "reason": reason}
    return _study_command(actor, household_id, request_key, "study_schedule.event", inputs, build)


def _source_rows(actor, household_id, bundle, refs):
    cards = learning._source_cards(actor, household_id, bundle, refs)
    result = []
    for ref, card in zip(refs, cards):
        result.append({"image_id": ref.image_id, "region_id": ref.region_id,
            "region_revision_id": ref.region_revision_id, "purpose": ref.purpose.value,
            "label": card.get("label", "原图证据"), "page_url": card.get("page_url"),
            "preview_url": card.get("preview_url"), "region_style": card.get("region_style", ""),
            "missing": bool(card.get("missing"))})
    return result


def _assessment_rows(actor, household_id, bundle, attempt_info, attempt, current_attempt_revision_id):
    rows = []
    actionable = []
    for item in attempt_info["assessments"]:
        revision = item["revision"]
        current_and_published = bool(item["current"] and item["published"]
            and revision.attempt_revision_id == current_attempt_revision_id)
        assessment = {"assessment_id": item["assessment"].assessment_id,
            "assessment_revision_id": revision.header.revision_id,
            "attempt_revision_id": revision.attempt_revision_id,
            "review_state": item["state"], "current": bool(item["current"]),
            "review_state_label": learning_label(REVIEW_STATE_LABELS, item["state"]),
            "published": bool(item["published"]),
            "reviewer_id": item["projection"].decision.actor_id if item["projection"].decision_id else None,
            "dimensions": []}
        for dimension in revision.dimensions:
            dimension_row = {"dimension": dimension.dimension.value,
                "judgment": dimension.judgment.value, "basis": dimension.basis.value,
                "dimension_label": learning_label(DIMENSION_LABELS, dimension.dimension),
                "judgment_label": learning_label(JUDGMENT_LABELS, dimension.judgment),
                "basis_label": learning_label(BASIS_LABELS, dimension.basis),
                "rationale": dimension.rationale, "unknown_reason": dimension.unknown_reason,
                "sources": _source_rows(actor, household_id, bundle, dimension.evidence_refs)}
            assessment["dimensions"].append(dimension_row)
        rows.append(assessment)
        if item["state"] == "accepted" and current_and_published:
            actionable.append((revision, assessment))
    return rows, actionable


@transaction.atomic
def evidence_report(actor, learner_entity_pk):
    learner_entity = _entity(actor, learner_entity_pk, "learner")
    profile_data = learning.profile_detail(actor, learner_entity.stable_id)
    bundle = core.read_snapshot_bundle(actor, learner_entity.household_id)
    profile = profile_data["profile"]
    question_revisions = {revision.header.revision_id: (question, revision)
        for question in bundle.questions for revision in question.revisions}
    attempts_by_id = {item.attempt_id: item for item in bundle.attempts}
    output_attempts = []
    insufficient = []
    observed_methods = []
    repeated = {}
    dated_by_question = {}

    for info in profile_data["attempts"]:
        attempt = info["attempt"]
        revision = info["revision"]
        attempt_row = {"attempt_id": attempt.attempt_id,
            "previous_attempt_id": attempt.previous_attempt_id,
            "attempt_revision_id": revision.header.revision_id,
            "state": revision.state.value,
            "state_label": learning_label(ATTEMPT_STATE_LABELS, revision.state),
            "withdrawal_reason": revision.withdrawal_reason,
            "replacement_attempt_id": revision.replacement_attempt_id,
            "attempt_kind": revision.attempt_kind.value,
            "attempt_kind_label": learning_label(ATTEMPT_KIND_LABELS, revision.attempt_kind),
            "question_id": attempt.question_id,
            "question_revision_id": revision.question_revision_id,
            "actual_date_state": revision.actual_date_state.value,
            "actual_date": revision.actual_date if revision.actual_date_state.value == "known" else None,
            "recorded_at": revision.header.recorded_at,
            "source_kind": revision.source_kind.value,
            "source_kind_label": learning_label(SOURCE_KIND_LABELS, revision.source_kind),
            "independence": revision.independence.value,
            "independence_label": learning_label(INDEPENDENCE_LABELS, revision.independence),
            "prompt_status": revision.prompt_status.value,
            "prompt_status_label": learning_label(PROMPT_STATUS_LABELS, revision.prompt_status),
            "prompts": list(revision.prompts),
            "legibility": revision.legibility.value,
            "legibility_label": learning_label(LEGIBILITY_LABELS, revision.legibility),
            "answer_text": revision.answer_text,
            "independent_success": bool(info["independent_success"]),
            "sources": _source_rows(actor, learner_entity.household_id, bundle,
                learning._evidence_for_attempt(bundle, revision)),
        }
        question_info = question_revisions.get(revision.question_revision_id)
        if question_info:
            question, question_revision = question_info
            attempt_row["question_text"] = question_revision.working_text or question_revision.printed_text or "题干待补"
            attempt_row["question_revision_number"] = question_revision.header.revision_no
        else:
            attempt_row["question_text"] = "题目修订无法定位"
            attempt_row["question_revision_number"] = None

        assessment_rows, actionable = _assessment_rows(actor, learner_entity.household_id,
            bundle, info, attempt, revision.header.revision_id)
        if revision.state.value != "active":
            actionable = []
        attempt_row["assessments"] = assessment_rows
        output_attempts.append(attempt_row)
        if revision.state.value == "active" and revision.actual_date_state.value == "known" and revision.actual_date:
            dated_by_question.setdefault(attempt.question_id, []).append(
                (revision.actual_date, revision.header.recorded_at, attempt.attempt_id))

        gaps = []
        if revision.source_kind.value != "independent_answer":
            gaps.append("来源类型不是已确认的独立作答。")
        if revision.independence.value != "confirmed_independent":
            gaps.append("独立性尚未得到人工确认。")
        if revision.prompt_status.value != "none_confirmed" or revision.prompts:
            gaps.append("有提示或提示情况未知。")
        if revision.legibility.value != "readable":
            gaps.append("笔迹不清楚或可读性未知。")
        if revision.actual_date_state.value != "known":
            gaps.append("实际作答日期未知。")
        if not actionable:
            gaps.append("没有当前、已接受并发布且对应本次作答版本的评价。")
        if actionable:
            dimensions_seen = set()
            for assessed_revision, assessment_row in actionable:
                for dimension in assessment_row["dimensions"]:
                    dimensions_seen.add(dimension["dimension"])
                    if (dimension["judgment"] == "unknown" or dimension["basis"] == "undetermined"
                            or not dimension["sources"]):
                        insufficient.append({"attempt_id": attempt.attempt_id,
                            "assessment_revision_id": assessed_revision.header.revision_id,
                            "dimension": dimension["dimension"],
                            "dimension_label": learning_label(DIMENSION_LABELS, dimension["dimension"]),
                            "judgment": dimension["judgment"], "basis": dimension["basis"],
                            "judgment_label": dimension["judgment_label"],
                            "basis_label": dimension["basis_label"],
                            "reason": dimension["unknown_reason"] or "缺少直接原图证据。",
                            "sources": dimension["sources"]})
                    if (dimension["dimension"] in ("method", "process")
                            and dimension["judgment"] == "correct" and dimension["basis"] == "observed"
                            and dimension["sources"]):
                        observed_methods.append({"attempt_id": attempt.attempt_id,
                            "attempt_revision_id": revision.header.revision_id,
                            "assessment_revision_id": assessed_revision.header.revision_id,
                            "question_id": attempt.question_id,
                            "question_revision_id": assessed_revision.question_revision_id,
                            "dimension": dimension["dimension"],
                            "dimension_label": dimension["dimension_label"], "sources": dimension["sources"]})
                    if (dimension["judgment"] in ("incorrect", "partial")
                            and dimension["basis"] == "observed" and dimension["sources"]):
                        group = repeated.setdefault((attempt.question_id, dimension["dimension"]), {})
                        group[attempt.attempt_id] = {"attempt_id": attempt.attempt_id,
                            "attempt_revision_id": assessed_revision.attempt_revision_id,
                            "assessment_revision_id": assessed_revision.header.revision_id,
                            "question_revision_id": assessed_revision.question_revision_id,
                            "judgment": dimension["judgment"], "basis": dimension["basis"],
                            "judgment_label": dimension["judgment_label"],
                            "basis_label": dimension["basis_label"],
                            "sources": dimension["sources"]}
            for dimension_name in ("answer", "method", "process", "calculation", "notation"):
                if dimension_name not in dimensions_seen:
                    insufficient.append({"attempt_id": attempt.attempt_id,
                        "assessment_revision_id": actionable[0][0].header.revision_id,
                        "dimension": dimension_name,
                        "dimension_label": learning_label(DIMENSION_LABELS, dimension_name),
                        "judgment": "unknown", "basis": "undetermined",
                        "judgment_label": learning_label(JUDGMENT_LABELS, "unknown"),
                        "basis_label": learning_label(BASIS_LABELS, "undetermined"),
                        "reason": "当前评价未包含该维度。", "sources": []})
        if gaps:
            insufficient.append({"attempt_id": attempt.attempt_id,
                "assessment_revision_id": None, "dimension": None,
                "dimension_label": None,
                "judgment": "unknown", "basis": "undetermined",
                "judgment_label": learning_label(JUDGMENT_LABELS, "unknown"),
                "basis_label": learning_label(BASIS_LABELS, "undetermined"),
                "reason": "；".join(gaps), "sources": attempt_row["sources"]})

    error_groups = []
    for (question_id, dimension), evidence in repeated.items():
        if len(evidence) >= 2:
            error_groups.append({"question_id": question_id, "dimension": dimension,
                                 "dimension_label": learning_label(DIMENSION_LABELS, dimension),
                                 "occurrence_count": len(evidence),
                                 "evidence": list(evidence.values())})
    interval_days = []
    for question_id, dated in dated_by_question.items():
        dated.sort(key=lambda item: (item[0], item[1], item[2]))
        for first, second in zip(dated, dated[1:]):
            interval_days.append({"question_id": question_id,
                "from_attempt_id": first[2], "to_attempt_id": second[2],
                "from_actual_date": first[0], "to_actual_date": second[0],
                "days": (date.fromisoformat(second[0]) - date.fromisoformat(first[0])).days})
    return {"learner": {"learner_id": profile.learner_id, "display_name": profile.display_name,
                        "grade": profile.grade},
        "generated_at": timezone.now().isoformat(), "attempts": output_attempts,
        "observed_correct_methods": observed_methods, "insufficient_evidence": insufficient,
        "repeated_errors": error_groups, "known_actual_date_intervals": interval_days}
