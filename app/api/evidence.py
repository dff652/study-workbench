"""Read-only projections of the existing evidence report; never infer mastery."""
from datetime import date

from django.urls import reverse
from django.db import transaction

from app.domain.attempt_ordering import order_attempts
from app.domain import SourceKind
from app.persistence.models import EntityRecord, RevisionRecord
from app.persistence import services as core
from app.study import services as study
from app.web import records


def scope(actor, household_id, learner_id):
    records.household(actor, household_id)
    try:
        learner = EntityRecord.objects.get(household_id=household_id, kind="learner", stable_id=learner_id)
    except EntityRecord.DoesNotExist:
        raise core.PersistenceError("not_found", "学习者不存在。") from None
    return learner


def filters(query):
    result = {key: query.get(key, "") for key in ("date_from", "date_to", "source_kind")}
    for key in ("date_from", "date_to"):
        if result[key] and (len(result[key]) != 10 or date.fromisoformat(result[key]).isoformat() != result[key]):
            raise ValueError("日期格式无效。")
    if result["date_from"] and result["date_to"] and result["date_from"] > result["date_to"]:
        raise ValueError("开始日期不能晚于结束日期。")
    if result["source_kind"] and result["source_kind"] not in {item.value for item in SourceKind}:
        raise ValueError("来源类型无效。")
    return result


@transaction.atomic
def projection(actor, household_id, learner_id, query):
    learner = scope(actor, household_id, learner_id)
    selected = filters(query)
    report = study.evidence_report(actor, learner.pk)
    history_count = sum(row['state'] == 'active' for row in report['attempts'])
    attempt_ids = [row['attempt_id'] for row in report['attempts']]
    initial_recorded_at = {
        stable_id: payload.get('header', {}).get('recorded_at')
        for stable_id, payload in RevisionRecord.objects.filter(
            entity__household_id=household_id, entity__kind="attempt",
            entity__stable_id__in=attempt_ids, revision_no=1,
        ).values_list("entity__stable_id", "payload")
    }
    question_pks = dict(EntityRecord.objects.filter(household_id=household_id, kind="question")
                        .values_list("stable_id", "pk"))
    rows = []
    unknown_dates = 0
    for raw in report["attempts"]:
        raw = dict(raw)
        if raw["actual_date"] is not None:
            raw["actual_date"] = str(raw["actual_date"])
        if selected["source_kind"] and raw["source_kind"] != selected["source_kind"]:
            continue
        if raw["state"] == "active" and raw["actual_date_state"] != "known":
            unknown_dates += 1
        if selected["date_from"] or selected["date_to"]:
            if raw["actual_date_state"] != "known" or not raw["actual_date"]:
                continue
            if selected["date_from"] and raw["actual_date"] < selected["date_from"]:
                continue
            if selected["date_to"] and raw["actual_date"] > selected["date_to"]:
                continue
        row = dict(raw)
        row["attempt_url"] = reverse("learning:attempt_detail", args=[row["attempt_id"]])
        row["learner_id"] = learner_id
        row["created_at"] = initial_recorded_at.get(row["attempt_id"])
        pk = question_pks.get(row["question_id"])
        row["question_url"] = reverse("knowledge:question_detail", args=[pk]) if pk else None
        rows.append(row)
    rows = order_attempts(rows)
    active = [row for row in rows if row["state"] == "active"]
    ids = {row["attempt_id"] for row in active}
    findings = {
        "observed_correct_methods": [row for row in report["observed_correct_methods"] if row["attempt_id"] in ids],
        "insufficient_evidence": [row for row in report["insufficient_evidence"] if row["attempt_id"] in ids],
        "repeated_errors": [],
        "known_actual_date_intervals": [row for row in report["known_actual_date_intervals"]
            if row["from_attempt_id"] in ids and row["to_attempt_id"] in ids],
    }
    for group in report["repeated_errors"]:
        evidence = [row for row in group["evidence"] if row["attempt_id"] in ids]
        if len(evidence) >= 2:
            findings["repeated_errors"].append({**group, "evidence": evidence, "occurrence_count": len(evidence)})
    metrics = {
        "attempt_count": len(active), "question_count": len({row["question_id"] for row in active}),
        "source_counts": {kind.value: sum(row["source_kind"] == kind.value for row in active) for kind in SourceKind},
        "unknown_date_count": unknown_dates,
        "independent_success_count": sum(row["independent_success"] for row in active),
        "independent_success_rate": None, "rate_state": "not_provided",
        "repeated_error_count": len(findings["repeated_errors"]),
        "insufficient_evidence_count": len({row["attempt_id"] for row in findings["insufficient_evidence"]}),
    }
    recent = active[:6]
    finding_ids = {row['attempt_id'] for key in ('observed_correct_methods', 'insufficient_evidence')
                   for row in findings[key]}
    return {"history_attempt_count": history_count, "recent_attempts": recent,
            "finding_attempts": [row for row in active if row['attempt_id'] in finding_ids],
            "scope": {"household_id": str(household_id), "learner_id": learner_id,
                       **selected, "metric_version": "evidence.v1"},
            "metrics": metrics, "findings": findings, "items": rows,
            "links": {"profile_url": reverse("learning:profile_detail", args=[learner_id]),
                "record_attempt_url": reverse("learning:attempt_new", args=[learner_id]),
                "report_url": reverse("study:report", args=[learner.pk]),
                "schedule_url": reverse("study:schedule_new", args=[learner.pk])}}
