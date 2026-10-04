"""Fixed material preparation stages, recorded in immutable workflow events."""
from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.utils import timezone

from app.ai import services as ai
from app.ai.models import ModelRun
from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.web import services as materials
from app.web.models import QuestionSource
from app.web import content_confirmation as content
from . import services as workflows, content_schema
from .models import WorkflowEvent

MAX_REQUESTS = 4
MAX_SECONDS = 600


def events(job):
    return list(job.events.filter(action="preparation_queued"))


def _stage(job, run_id):
    event = job.events.filter(action="preparation_queued", details__run_id=str(run_id)).first()
    if event is None:
        raise core.PersistenceError("not_found", "本资料任务没有此阶段。")
    return event, ModelRun.objects.select_for_update().get(pk=run_id)


def _current(job):
    if job.state not in ("ready", "needs_review") or (job.input["records"] and not job.result.get("mapping")):
        raise core.PersistenceError("invalid_state", "请先核对来源包；已进入输出的任务不能新增模型阶段。")
    if workflows.stamp(job.material) != job.source_stamp:
        raise core.PersistenceError("source_changed", "资料已变化，请建立新任务。")


def _expired(job):
    first = job.events.filter(action="preparation_queued").first()
    return bool(first and timezone.now() >= first.created_at + timedelta(seconds=MAX_SECONDS))


def check_send(run):
    """Also called at the provider send gate; an expired batch never sends."""
    event = WorkflowEvent.objects.filter(action="preparation_queued", details__run_id=str(run.pk)).select_related("job__material__household").first()
    if event is None:
        raise core.PersistenceError("invalid_state", "模型任务没有对应资料阶段。")
    job = event.job
    _current(job)
    if _expired(job):
        raise core.PersistenceError("batch_expired", "本批次准备时间已到，请使用已核对内容或建立新任务。")
    later = job.events.filter(action="preparation_queued", version__gt=event.version,
        details__question_id=event.details["question_id"]).exists()
    if later:
        raise core.PersistenceError("stale_context", "此阶段已被明确重做。")


def _expected(job, run):
    return {"job": workflows.context(job), "material": content._context(job.material),
            "stage_id": str(run.pk), "state": run.status, "response_sha256": core._digest(run.response)}


@transaction.atomic
def detail(actor, job_id):
    job = workflows._job(actor, job_id)
    config = ai.latest_config(job.material.household_id)
    history = events(job)
    skipped = set(job.events.filter(action="preparation_cancelled").values_list("details__run_id", flat=True))
    stages = []
    for event in history:
        run = ModelRun.objects.get(pk=event.details["run_id"])
        current = (job.state in ("ready", "needs_review") and not _expired(job)
            and workflows.stamp(job.material) == job.source_stamp and ai._still_current(run)
            and not any(later.details["question_id"] == event.details["question_id"] and later.version > event.version for later in history))
        proposal = (run.response or {}).get("proposal")
        stages.append({"id": str(run.pk), "state": "cancelled" if str(run.pk) in skipped else run.status,
            "question_id": event.details["question_id"], "sources": event.details["sources"],
            "proposal": proposal, "can_confirm": bool(current and str(run.pk) not in skipped and run.status == "awaiting_review"),
            "expected": _expected(job, run), "error_code": run.error_code or None,
            "record_count": len(content_schema.records(proposal, [{"source_id": ref["page_id"], "bbox": ref["bbox"]}
                for ref in event.details["sources"]])["records"]) if proposal else 0,
            "created_at": event.created_at})
    limit = job.result.get("preparation_limits", {})
    return {"job": job, "config": {"enabled": bool(config and config.cloud_enabled and ai._has_explicit_outbound_confirmation(config)),
        "outbound_scope": config.outbound_scope if config else None,
        "max_requests": limit.get("max_requests", MAX_REQUESTS),
        "max_seconds": MAX_SECONDS, "budget_usd": limit.get("budget_usd", str(config.batch_budget) if config else None)},
        "stages": stages, "limits": {"used_requests": len(history),
        "max_requests": limit.get("max_requests", MAX_REQUESTS), "max_seconds": MAX_SECONDS}}


def _begin(actor, job, value, action):
    key = materials._text(value.get("request_key"), 160)
    reason = materials._text(value.get("reason"), 1000)
    fingerprint = core._digest({"job": str(job.pk), "action": action, "value": value})
    replay = core._replay(job.material.household, actor, key, "web_record", fingerprint)
    return key, reason, fingerprint, replay


@transaction.atomic
def queue(actor, job_id, value):
    job = workflows._job(actor, job_id, write=True)
    key, reason, fingerprint, replay = _begin(actor, job, value, "preparation")
    if replay is not None:
        return job, replay["stage_id"]
    if value.get("expected") != workflows.context(job):
        raise core.PersistenceError("stale_context", "任务版本已变化。")
    _current(job)
    history = events(job)
    config = ai.latest_config(job.material.household_id)
    if not config or not config.cloud_enabled or not ai._has_explicit_outbound_confirmation(config):
        raise core.PersistenceError("model_disabled", "模型未启用，请使用人工核对。")
    if config.outbound_scope != "selected_regions":
        raise core.PersistenceError("model_scope", "图像整理需要明确允许选定图像区域。")
    limits = job.result.get("preparation_limits", {"config_id": str(config.pk),
        "max_requests": MAX_REQUESTS, "budget_usd": str(config.batch_budget)})
    if limits["config_id"] != str(config.pk):
        raise core.PersistenceError("source_changed", "模型配置已变更，请建立新任务。")
    if len(history) >= limits["max_requests"]:
        raise core.PersistenceError("batch_call_limit", "本批次已达到累计请求上限。")
    if _expired(job):
        raise core.PersistenceError("batch_expired", "本批次准备时间已到。")
    spent = sum((run.estimated_cost if run.estimated_cost is not None else config.reserved_per_call)
                for run in ModelRun.objects.filter(pk__in=[event.details["run_id"] for event in history]))
    if Decimal(spent) + config.reserved_per_call > Decimal(limits["budget_usd"]):
        raise core.PersistenceError("budget_exceeded", "本批次准备预算不足。")
    refs = content.sources(actor, job.material, value.get("sources"))
    if len(refs) > 20:
        raise ValueError("一个模型阶段最多选择二十个明确区域。")
    question_id = value.get("question_id")
    child = "preparation-" + core._digest(key)
    if question_id:
        entity = EntityRecord.objects.get(household=job.material.household, kind="question", stable_id=question_id)
        source = QuestionSource.objects.get(material=job.material, revision=entity.head_revision)
        original_refs = [{"page_id": row["page_id"], "bbox": row["original_bbox"]} for row in source.sources]
        if original_refs != value["sources"]:
            raise core.PersistenceError("source_changed", "重做沿用原阶段的明确来源区域。")
        previous = next((event for event in reversed(history) if event.details["question_id"] == question_id), None)
        if previous:
            ai.cancel_run(actor, previous.details["run_id"])
        revision_id = entity.head_revision_id
    else:
        seed = materials.save_question(actor, job.material_id, printed_text="", original_number="", sources=refs,
            request_key=child + "-source", reason=reason, confirm=False)
        question_id, revision_id = seed["question_id"], seed["revision_id"]
    selected = ai.selection_context(actor, job.material.household_id, "material")
    source = QuestionSource.objects.get(revision_id=revision_id)
    run = ai.queue_run(actor, job.material.household_id, task_kind="material", source_revision_ids=[revision_id],
        question_revision_ids=[revision_id], selected_region_revision_ids=[row["region_revision_id"] for row in source.sources],
        selection_token=selected["token"], request_key=child + "-model")
    ai.request_execution(actor, run.pk)
    job.source_stamp = workflows.stamp(job.material)
    job.result["preparation_limits"] = limits
    workflows._event(job, actor, "preparation_queued", {"run_id": str(run.pk), "question_id": question_id,
        "question_revision_id": revision_id, "sources": value["sources"], "reason": reason,
        "source_stamp": job.source_stamp, "limits": limits})
    core._receipt(job.material.household, actor, key, "web_record", fingerprint, {"stage_id": str(run.pk)})
    return job, str(run.pk)


@transaction.atomic
def confirm(actor, job_id, stage_id, value):
    job = workflows._job(actor, job_id, write=True)
    key, reason, fingerprint, replay = _begin(actor, job, value, "preparation-confirm")
    if replay is not None:
        return job, replay
    event, run = _stage(job, stage_id)
    if value.get("expected") != _expected(job, run):
        raise core.PersistenceError("stale_context", "草稿或任务版本已变化。")
    check_send(run)
    if run.status != "awaiting_review" or not ai._still_current(run):
        raise core.PersistenceError("stale_context", "模型阶段不能确认。")
    if value.get("sources") != event.details["sources"]:
        raise core.PersistenceError("source_changed", "核对须保留本阶段来源区域。")
    native = {key: item for key, item in value.items() if key != "expected"}
    native.update(expected=content._context(job.material), question_id=event.details["question_id"],
        request_key="preparation-confirm-" + core._digest(key))
    result = content.save(actor, job.material_id, native)
    run.status, run.output_revision_ids = "applied", [result["revision_id"]]
    run.save(update_fields=("status", "output_revision_ids"))
    job.source_stamp = workflows.stamp(job.material)
    workflows._event(job, actor, "preparation_confirmed", {"run_id": str(run.pk), "question_id": result["question_id"],
        "revision_id": result["revision_id"], "response_sha256": core._digest(run.response), "reason": reason})
    core._receipt(job.material.household, actor, key, "web_record", fingerprint, result)
    return job, result


@transaction.atomic
def cancel(actor, job_id, stage_id, value):
    job = workflows._job(actor, job_id, write=True)
    key, reason, fingerprint, replay = _begin(actor, job, value, "preparation-cancel")
    if replay is not None:
        return job
    _event, run = _stage(job, stage_id)
    if value.get("expected") != _expected(job, run) or job.state in ("complete", "cancelled"):
        raise core.PersistenceError("stale_context", "阶段或任务已改变。")
    if run.status == "applied":
        raise core.PersistenceError("invalid_state", "已确认内容不能通过取消模型阶段撤回。")
    ai.cancel_run(actor, run.pk)
    workflows._event(job, actor, "preparation_cancelled", {"run_id": str(run.pk), "reason": reason})
    core._receipt(job.material.household, actor, key, "web_record", fingerprint, {"job_id": str(job.pk)})
    return job


def cancel_all(actor, job):
    for event in events(job):
        run = ModelRun.objects.get(pk=event.details["run_id"])
        if run.status in ("queued", "running", "awaiting_review"):
            ai.cancel_run(actor, run.pk)


def ensure_output_ready(job):
    latest = {event.details["question_id"]: event for event in events(job)}
    skipped = set(job.events.filter(action="preparation_cancelled").values_list("details__run_id", flat=True))
    for event in latest.values():
        run = ModelRun.objects.get(pk=event.details["run_id"])
        if run.status != "applied" and str(run.pk) not in skipped:
            raise core.PersistenceError("preparation_incomplete", "还有内容阶段待核对或明确取消。")
