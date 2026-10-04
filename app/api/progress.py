"""Progress describes recorded work and evidence, never inferred mastery."""
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from app.domain import SourceKind
from app.persistence.adapter import ObjectKey
from app.persistence import services as core
from app.persistence.models import EntityRecord, RevisionRecord
from app.study import services as study
from app.web import records
from app.web.models import MaterialSet, QuestionSource
from app.workflows.models import WorkflowJob
from . import evidence


def scope(household_id, learner_id=None):
    result = {"household_id": str(household_id), "metric_version": "progress.v1",
              "as_of": timezone.localdate().isoformat()}
    if learner_id is not None:
        result["learner_id"] = learner_id
    return result


@transaction.atomic
def materials(actor, household_id):
    records.household(actor, household_id)
    rows = MaterialSet.objects.filter(household_id=household_id).prefetch_related(
        "pages__reading_revisions").order_by("-created_at", "pk")
    question_counts = {}
    sources = QuestionSource.objects.filter(material__household_id=household_id,
        revision_id=F("revision__entity__head_revision_id")).select_related(
            "revision__entity", "revision__review_projection")
    for source in sources:
        revision = source.revision
        if revision.review_projection.state == "withdrawn":
            continue
        counts = question_counts.setdefault(source.material_id, [0, 0])
        confirmed = revision.entity.published_revision_id == revision.pk and revision.review_projection.state == "accepted"
        counts[0 if confirmed else 1] += 1
    totals = dict.fromkeys(("material_count", "page_count", "pages_complete", "pages_unread",
        "pages_need_retake", "questions_confirmed", "questions_pending", "open_workflows", "completed_workflows"), 0)
    result = []
    for material in rows:
        row = {"id": str(material.pk), "title": material.title, "page_count": 0,
               "pages_complete": 0, "pages_unread": 0, "pages_need_retake": 0,
               "material_url": reverse("web:material_detail", args=[material.pk])}
        for page in material.pages.all():
            row["page_count"] += 1
            reading = next(iter(page.reading_revisions.all()), None)
            if reading is None or reading.reading == "unread":
                row["pages_unread"] += 1
            elif reading.reading == "needs_retake":
                row["pages_need_retake"] += 1
            elif reading.coverage == "complete" and not reading.pending_items:
                row["pages_complete"] += 1
        row["questions_confirmed"], row["questions_pending"] = question_counts.get(material.pk, [0, 0])
        totals["material_count"] += 1
        for key in row.keys() & totals.keys():
            totals[key] += row[key]
        if len(result) < 200:
            result.append(row)
    jobs = WorkflowJob.objects.filter(material__household_id=household_id)
    totals["completed_workflows"] = jobs.filter(state="complete").count()
    totals["open_workflows"] = jobs.exclude(state__in=("complete", "cancelled")).count()
    return {"scope": scope(household_id), "counts": totals, "materials": result,
            "total": totals["material_count"]}


@transaction.atomic
def learner(actor, household_id, learner_id):
    report = evidence.projection(actor, household_id, learner_id, {})
    active = [row for row in report["items"] if row["state"] == "active"]
    insufficient = {row["attempt_id"] for row in report["findings"]["insufficient_evidence"]}
    nodes = EntityRecord.objects.filter(household_id=household_id,
        kind__in=("knowledge", "method", "question_type"), head_revision_id=F("published_revision_id"),
        published_revision__review_projection__state="accepted").select_related("published_revision")
    groups = []
    for node in nodes.order_by("kind", "stable_id"):
        trace = core.published_trace(actor, household_id, node=ObjectKey(node.kind, node.stable_id))
        question_ids = set(RevisionRecord.objects.filter(pk__in=trace["question_revision_ids"])
                           .values_list("entity__stable_id", flat=True))
        attempts = [row for row in active if row["question_revision_id"] in trace["question_revision_ids"]]
        payload = node.published_revision.payload
        groups.append({"id": node.stable_id, "kind": node.kind,
            "label": (payload.get("name") or payload.get("definition") or "待补名称")[:120],
            "question_count": len(question_ids), "attempt_count": len(attempts),
            "independent_success_count": sum(row["independent_success"] for row in attempts),
            "unknown_evidence_count": sum(row["attempt_id"] in insufficient for row in attempts),
            "source_counts": {kind.value: sum(row["source_kind"] == kind.value for row in attempts) for kind in SourceKind},
            "node_url": reverse("knowledge:node_detail", args=[node.pk])})
    return {"scope": scope(household_id, learner_id), "groups": groups}


@transaction.atomic
def schedules(actor, household_id, learner_id):
    profile = evidence.scope(actor, household_id, learner_id)
    items = []
    counts = dict.fromkeys(("pending", "overdue", "completed", "cancelled"), 0)
    today = timezone.localdate()
    for raw in study.home(actor, household_id)["schedules"]:
        row, latest = raw["schedule"], raw["latest"]
        if row.learner_id != profile.pk or latest is None:
            continue
        detail = study.schedule_detail(actor, row.pk)
        completions = {item["event"].pk: item for item in detail["completion_history"]}
        history = []
        for event in detail["history"]:
            bound = completions.get(event.pk)
            history.append({"revision_no": event.revision_no, "action": event.action,
                "due_date": event.due_date, "reason": event.reason,
                "attempt_revision_id": event.completed_attempt_revision_id,
                "actual_date": bound["actual_date"] if bound else None,
                "recorded_at": event.recorded_at})
        choices = []
        for choice in study.schedule_attempt_choices(actor, row.pk)["choices"]:
            revision = choice["revision"]
            kind = revision.source_kind.value
            label = {"independent_answer": "独立作答", "classroom_note": "课堂笔记",
                     "assisted_answer": "提示后完成"}.get(kind, "来源未知")
            choices.append({"revision_id": revision.header.revision_id,
                "label": f"{choice['actual_date'] or '实际日期未知'} · {label}",
                "actual_date": choice["actual_date"], "source_kind": kind})
        if latest.action in ("planned", "rescheduled"):
            counts["pending"] += 1
            counts["overdue"] += latest.due_date < today
        elif latest.action == "cancelled":
            counts["cancelled"] += 1
        elif latest.action == "completed" and latest.completed_attempt_revision_id:
            counts["completed"] += 1
        items.append({"id": row.pk, "question_id": row.target_question_revision.entity.stable_id,
            "question_text": raw["target_question"].get("working_text") or raw["target_question"].get("printed_text") or "题干待补",
            "goal": latest.goal, "prompt_plan": latest.prompt_plan, "due_date": latest.due_date,
            "state": latest.action, "target_stale": raw["target_stale"], "context": detail["context"],
            "detail_url": reverse("study:schedule_detail", args=[row.pk]),
            "history": history, "attempt_choices": choices})
    return {"scope": scope(household_id, learner_id), "counts": counts, "items": items}
