"""Explicit human confirmation of a model proposal, in one atomic transaction.

Provider completion never publishes content. This facade joins the existing
draft builder and native review gate, retaining their version and evidence rules.
"""
from uuid import uuid4

from django.db import transaction

from app.persistence import services as core
from app.persistence.models import RevisionRecord
from app.web import records, services as materials, knowledge_services
from . import services
from .models import ModelRun


def _context(actor, run):
    return {"status": run.status, "response_hash": core._digest(run.response),
        "inputs_current": services._still_current(run),
        "outputs": [{"revision_id": rid, "review": core.review_context(
            actor, run.household_id, rid)} for rid in run.output_revision_ids]}


def _can_confirm(data, context):
    run = data["run"]
    if run.task_kind == ModelRun.TaskKind.MATERIAL:
        return False  # The material workspace binds its stage, sources and content together.
    # Use the same task ownership rule as apply_run, including creator-only variants.
    permitted = data["writable"] and (run.actor_id == data["actor_id"] or data["owner"])
    if run.task_kind == "variant" and run.actor_id != data["actor_id"]:
        permitted = False
    if not permitted:
        return False
    if run.status == ModelRun.Status.AWAITING_REVIEW:
        return context["inputs_current"]
    if run.status == ModelRun.Status.APPLIED:
        if run.task_kind == 'knowledge' and not context['inputs_current']:
            return False
        return bool(context["outputs"]) and all(item["review"]["state"] == "draft"
            and item["review"]["expected_head"] == item["revision_id"] for item in context["outputs"])
    return False


@transaction.atomic
def review_context(actor, run_id):
    data = services.run_detail(actor, run_id)
    from app.persistence.models import HouseholdMember
    data.update(actor_id=actor.pk, owner=HouseholdMember.objects.filter(
        household_id=data["household_id"], user=actor, role="owner").exists())
    run = data["run"]
    context = _context(actor, run)
    outputs = context["outputs"]
    confirmed = bool(outputs) and all(item["review"]["state"] == "accepted"
        and RevisionRecord.objects.get(pk=item["revision_id"]).entity.published_revision_id == item["revision_id"]
        for item in outputs)
    data.update(context=context, can_confirm=_can_confirm(data, context), confirmed=confirmed,
        proposal=(run.response or {}).get("proposal"))
    if run.status == ModelRun.Status.AWAITING_REVIEW and not context["inputs_current"]:
        data["block_message"] = "来源或依赖已改变，这份建议不能确认；请重新创建任务。"
    elif not data["can_confirm"] and not confirmed:
        data["block_message"] = "此任务或生成内容当前不能确认；请查看任务状态和历史。"
    return data


@transaction.atomic
def confirm_run(actor, run_id, *, expected, checked, reason, request_key):
    """A checkbox is explicit assent, including retaining any unknown judgments.

Exact POST replay returns its historic receipt; it never re-publishes withdrawn
or superseded content. A fresh request always checks the full displayed context.
    """
    reference = ModelRun.objects.get(pk=run_id)
    owner = records.household(actor, reference.household_id, write=True)
    data = review_context(actor, run_id)
    if not data["writable"] or not (reference.actor_id == actor.pk or data["owner"]):
        raise core.PersistenceError("permission_denied", "无权确认此任务。")
    if reference.task_kind == "variant" and reference.actor_id != actor.pk:
        raise core.PersistenceError("permission_denied", "变式由创建任务的成员确认。")
    reason = materials._text(reason, 1000)
    if checked is not True or not reason or not isinstance(expected, dict):
        raise core.PersistenceError("invalid_input", "请核对内容并明确确认，填写核对依据。")
    fingerprint = core._digest({"action": "ai-confirm", "run": str(run_id),
        "expected": expected, "checked": checked, "reason": reason})
    replay = core._replay(owner, actor, request_key, "web_record", fingerprint)
    if replay is not None:
        return replay
    if expected != data["context"] or not data["can_confirm"]:
        raise core.PersistenceError("stale_context", "建议、来源或确认状态已改变，请重新打开。")
    result = services.apply_run(actor, run_id, request_key=f"ai-confirm-build-{uuid4().hex}")
    if result.get("stale") or not result["revision_ids"]:
        raise core.PersistenceError("stale_context", "来源已改变。")
    decisions = []
    for rid in result["revision_ids"]:
        context = core.review_context(actor, owner.pk, rid)
        row = RevisionRecord.objects.select_related('entity').get(pk=rid)
        decisions.append(records.review(actor, owner.pk, row.entity.kind, row.entity.stable_id, rid,
            action="accept", reason=reason, context=context,
            request_key=f"ai-confirm-review-{uuid4().hex}"))
    links = []
    if reference.task_kind == 'knowledge':
        for qid in reference.question_revision_ids:
            link = knowledge_services.create_link(actor, owner.pk, kind='knowledge',
                node_revision_id=result['revision_ids'][0], question_revision_id=qid,
                role='applies', reason=reason, request_key=f'ai-confirm-link-{uuid4().hex}')
            c = core.review_context(actor, owner.pk, link['revision_id'])
            records.review(actor, owner.pk, link['kind'], link['stable_id'], link['revision_id'],
                action='accept', reason=reason, context=c, request_key=f'ai-confirm-link-review-{uuid4().hex}')
            links.append(link['revision_id'])
    return core._receipt(owner, actor, request_key, "web_record", fingerprint,
        {**result, "confirmed": True, "decisions": decisions, 'link_revision_ids': links})


@transaction.atomic
def next_pending(actor, household_id, *, exclude_run_id=None):
    """Bounded navigation; skipped or blocked proposals remain in task history."""
    records.household(actor, household_id)
    runs = ModelRun.objects.filter(household_id=household_id,
        status__in=(ModelRun.Status.AWAITING_REVIEW, ModelRun.Status.APPLIED)).exclude(
            pk=exclude_run_id).order_by("-created_at", "-id")[:100]
    for run in runs:
        if review_context(actor, run.pk)["can_confirm"]:
            return run.pk
    return None
