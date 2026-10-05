"""Closed, resumable local SOP; model execution retains its existing consent gate."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from app.exports.contracts import canonical, digest, ExportError
from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.web import records, services as materials
from app.printing import packets, services as printing
from . import exchange, importer
from .models import WorkflowJob, WorkflowEvent


def stamp(material):
    pages = list(material.pages.order_by("position").values_list("id", "position", "image__sha256"))
    heads = list(EntityRecord.objects.filter(household=material.household).order_by("pk")
                 .values_list("pk", "head_revision_id", "published_revision_id"))
    from app.printing.models import TeacherAnswerRevision, AnswerDecision
    answers = list(TeacherAnswerRevision.objects.filter(household=material.household).order_by("pk").values_list("pk", "revision_no"))
    decisions = list(AnswerDecision.objects.filter(answer__household=material.household).order_by("pk").values_list("pk", "action"))
    from app.printing.models import TeachingDiagramRevision
    from app.web.models import PageReadingRevision
    diagrams = list(TeachingDiagramRevision.objects.filter(household=material.household).order_by("pk").values_list("pk", "revision_no"))
    readings = list(PageReadingRevision.objects.filter(page__material=material).order_by("pk").values_list("pk", "revision_no"))
    return core._digest({"pages": [[str(x) for x in row] for row in pages], "heads": heads,
                         "answers": answers, "decisions": decisions, "diagrams": diagrams, "readings": readings})


def _job(actor, job_id, write=False):
    row = WorkflowJob.objects.select_related("material__household", "created_by").get(pk=job_id)
    records.household(actor, row.material.household_id, write=write)
    if write:
        row = WorkflowJob.objects.select_for_update().select_related("material__household", "created_by").get(pk=job_id)
    return row


def _event(job, actor, action, details=None, *, initial=False):
    if not initial:
        job.version += 1
        job.save()
    WorkflowEvent.objects.create(job=job, version=job.version, action=action, actor=actor, details=details or {})


@transaction.atomic
def create(actor, material_id, *, request_key, proposal=None, learner_id=None, evidence_scope="selected_learner_history"):
    material = materials._material(actor, material_id, write=True)
    request_key = materials._text(request_key, 160)
    if learner_id is not None:
        EntityRecord.objects.get(household=material.household, kind="learner", stable_id=learner_id)
    value = proposal if proposal is not None else {"schema_version": exchange.SCHEMA, "sources": [], "records": []}
    if proposal is not None:
        exchange.validate(value, {str(page.pk): page for page in material.pages.select_related("image")})
    if evidence_scope not in ("material_questions", "selected_learner_history"):
        raise core.PersistenceError("invalid_input", "请选择学习证据范围。")
    identity = {"input": value, "learner_id": learner_id, "actor": actor.pk}
    # Preserve fingerprints for old callers using the established all-history default.
    if evidence_scope != "selected_learner_history":
        identity["evidence_scope"] = evidence_scope
    fingerprint = digest(canonical(identity))
    previous = WorkflowJob.objects.filter(material=material, request_key=request_key).first()
    if previous:
        if previous.fingerprint != fingerprint:
            raise core.PersistenceError("request_conflict", "请求键已对应其他输入。")
        return previous
    job = WorkflowJob.objects.create(material=material, created_by=actor, request_key=request_key,
        fingerprint=fingerprint, input=value, source_stamp=stamp(material),
        state="needs_review" if value["records"] else "ready", result={"learner_id": learner_id, "evidence_scope": evidence_scope})
    _event(job, actor, "created", {"record_count": len(value["records"]), "ai_requested": False}, initial=True)
    return job


def context(job):
    return {"version": job.version, "source_stamp": job.source_stamp}


def action(actor, job_id, *, action, expected, request_key, reason="", checks=None):
    if action == "confirm":
        from app.printing.diagram_services import file_batch
        # The lock outlives the outer commit; rollback removes only newly written files.
        with file_batch():
            with transaction.atomic(durable=True):
                return _action(actor, job_id, action=action, expected=expected, request_key=request_key,
                               reason=reason, checks=checks)
    return _action(actor, job_id, action=action, expected=expected, request_key=request_key, reason=reason, checks=checks)


@transaction.atomic
def _action(actor, job_id, *, action, expected, request_key, reason="", checks=None):
    job = _job(actor, job_id, write=True)
    request_key = materials._text(request_key, 160)
    inputs = {"job": str(job.pk), "action": action, "expected": expected, "reason": reason, "checks": checks}
    fingerprint = core._digest(inputs)
    replay = core._replay(job.material.household, actor, request_key, "web_record", fingerprint)
    if replay:
        return job  # A receipt never restores an obsolete state or publication.
    if expected != context(job):
        raise core.PersistenceError("stale_context", "任务已改变，请刷新。")
    if action in {"confirm", "queue", "resume"} and stamp(job.material) != job.source_stamp:
        raise core.PersistenceError("source_changed", "资料或关联版本已变化，请建立新任务。")
    if action == "confirm" and job.state == "needs_review":
        reason = materials._text(reason, 1000)
        job.result["mapping"] = importer.apply(actor, job, reason)
        job.source_stamp = stamp(job.material)
        job.state = "ready"
    elif action in {"queue", "resume"} and job.state in ({"ready"} if action == "queue" else {"failed"}):
        from . import preparation
        preparation.ensure_output_ready(job)
        _verify_originals(job.material)
        if not packets.readiness(actor, job.material_id)["ready"]:
            raise core.PersistenceError("packet_incomplete", "请先完成题干与家长答案核对。")
        job.state, job.error_code, job.started_at = "queued", "", None
    elif action == "cancel" and job.state not in {"complete", "cancelled"}:
        from . import preparation
        preparation.cancel_all(actor, job)
        job.state = "cancelled"
    elif action == "check_output" and job.state == "output_check":
        if checks != {"pdf": True, "docx": True, "purposes": True}:
            raise core.PersistenceError("output_unchecked", "请检查 PDF、Word 和五册用途。")
        reason = materials._text(reason, 1000)
        packets.read(actor, job.material_id, job.result["packet_id"])
        job.state = "complete"
    else:
        raise core.PersistenceError("invalid_state", "此阶段不能执行该动作。")
    _event(job, actor, action, {"reason": reason, "checks": checks, "state": job.state})
    core._receipt(job.material.household, actor, request_key, "web_record", fingerprint, {"job_id": str(job.pk)})
    return job


@transaction.atomic
def detail(actor, job_id):
    return _job(actor, job_id)


@transaction.atomic
def _claim(job_id):
    row = WorkflowJob.objects.select_related("material__household", "created_by").get(pk=job_id)
    try:
        row = _job(row.created_by, row.pk, write=True)
    except core.PersistenceError:
        row = WorkflowJob.objects.select_for_update().get(pk=job_id)
        if row.state == "queued":
            row.state, row.error_code = "failed", "permission_changed"
            _event(row, None, "failed", {"error_code": row.error_code})
        return None
    if row.state != "queued":
        return None
    row.state, row.started_at = "running", timezone.now()
    _event(row, None, "started")
    return row


def execute_next():
    for identity in WorkflowJob.objects.filter(state="queued").order_by("created_at").values_list("pk", flat=True)[:20]:
        job = _claim(identity)
        if job:
            break
    else:
        return None
    try:
        with transaction.atomic():
            current = _job(job.created_by, job.pk, write=True)
            if current.state != "running" or current.version != job.version:
                return current
            if stamp(job.material) != job.source_stamp:
                raise core.PersistenceError("source_changed", "资料版本已变化。")
            _verify_originals(job.material)
            learner = job.result.get("learner_id")
            learner_pk = EntityRecord.objects.get(household=job.material.household, kind="learner", stable_id=learner).pk if learner else None
            packet_id = packets.generate(job.created_by, job.material_id, learner_id=learner_pk, evidence_scope=job.result.get("evidence_scope", "selected_learner_history"))
            current.refresh_from_db()
            # Completion commits only for the exact claim; a late worker cannot revive cancellation.
            if current.state == "running" and current.version == job.version:
                current.result["packet_id"] = packet_id
                current.state = "output_check"
                _event(current, None, "rendered", {"packet_id": packet_id})
                job = current
    except (core.PersistenceError, ExportError) as exc:
        _fail(job, exc.code)
    except Exception:
        _fail(job, "render_failed")  # Private content and exception messages stay out of worker logs.
    return WorkflowJob.objects.get(pk=job.pk)


@transaction.atomic
def _fail(job, code):
    current = WorkflowJob.objects.select_for_update().get(pk=job.pk)
    if current.state == "running" and current.version == job.version:
        current.state, current.error_code = "failed", code
        _event(current, None, "failed", {"error_code": code})


@transaction.atomic
def recover_interrupted():
    for job in WorkflowJob.objects.select_for_update().filter(state="running", started_at__lt=timezone.now() - timedelta(minutes=30)):
        job.state, job.error_code = "failed", "interrupted"
        _event(job, None, "interrupted")
    # Resume is explicit and local; this never repeats a model request.


def _verify_originals(material):
    for page in material.pages.select_related("image"):
        materials.asset_path(page.image.payload["storage_key"], page.image.sha256)
