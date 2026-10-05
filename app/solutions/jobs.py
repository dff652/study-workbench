"""Bounded offline rendering jobs; late workers cannot revive cancelled work."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from app.exports.contracts import ExportError, canonical, digest
from app.persistence import services as core
from app.web import records, services as materials
from . import queries, rendering, schema, services
from .models import SolutionOutput, SolutionOutputEvent


@transaction.atomic
def get(actor, output_id, write=False):
    row = SolutionOutput.objects.select_related("revision__material__household", "requested_by").get(pk=output_id)
    records.household(actor, row.revision.material.household_id, write=write)
    if write:
        services.material(actor, row.revision.material_id, write=True)
        row = SolutionOutput.objects.select_for_update().select_related("revision__material__household", "requested_by").get(pk=row.pk)
    return row


def event(row, action, author=None, details=None):
    row.version += 1
    row.save()
    SolutionOutputEvent.objects.create(output=row, version=row.version, action=action,
                                      author=author, details=details or {})


@transaction.atomic
def action(actor, output_id, *, action, expected_version, request_key, reason, checks=None):
    row = get(actor, output_id, write=True)
    request_key = materials._text(request_key, 160)
    reason = materials._text(reason, 1000)
    fingerprint = digest(canonical({"output": str(row.pk), "action": action, "expected": expected_version,
                                   "reason": reason, "checks": checks}))
    house = row.revision.material.household
    if core._replay(house, actor, request_key, "web_record", fingerprint):
        return row
    if type(expected_version) is not int or row.version != expected_version:
        raise core.PersistenceError("stale_solution", "生成任务已更新，请刷新后查看当前状态。")
    if action == "cancel" and row.state in {"queued", "running", "failed", "output_check"}:
        row.state = "cancelled"
    elif action == "retry" and row.state == "failed":
        services.require_current_links(row.revision.material, row.revision.content)
        if row.revision.source_stamp != services.stamp(row.revision.material, row.revision.content):
            raise core.PersistenceError("source_changed", "来源已更新，请保存新版本后重新生成。")
        row.state, row.error_code, row.started_at = "queued", "", None
    elif action == "check" and row.state in {"output_check", "complete"}:
        schema.fields(checks, set(queries.check_names(row.revision.mode)))
        for check in checks.values():
            schema.fields(check, {"status", "notes"})
            if check["status"] not in ("pass", "fail", "not_tested"):
                schema.fail("请分别记录各项检查结果。")
            schema.text(check["notes"], 2000, empty=check["status"] == "not_tested")
        # Recheck every selected artifact before attaching human checks to it.
        for document in row.result["documents"]:
            for format_name in document["formats"]:
                rendering.output_file(row, document["id"], "document." + format_name)
        row.result = {**row.result, "checks": checks}
        row.state = "complete" if all(checks[name]["status"] == "pass" for name in ("content", "subject" if row.revision.mode == "knowledge" else "math", "pdf_visual")) and not any(
            check["status"] == "fail" for check in checks.values()) else "output_check"
    else:
        raise core.PersistenceError("invalid_state", "当前状态不能执行此操作。")
    event(row, action, actor, {"reason": reason, "checks": checks,
        "content_hash": row.revision.content_hash, "recipe_sha256": row.result.get("recipe_sha256")})
    core._receipt(house, actor, request_key, "web_record", fingerprint, {"output_id": str(row.pk)})
    return row


@transaction.atomic
def claim(output_id):
    initial = SolutionOutput.objects.select_related("requested_by", "revision__material").get(pk=output_id)
    try:
        row = get(initial.requested_by, output_id, write=True)
    except core.PersistenceError:
        row = SolutionOutput.objects.select_for_update().get(pk=output_id)
        if row.state == "queued":
            row.state, row.error_code = "failed", "permission_changed"
            event(row, "failed", details={"code": row.error_code})
        return None
    if row.state != "queued":
        return None
    row.state, row.started_at = "running", timezone.now()
    event(row, "started")
    return row


@transaction.atomic
def fail_claim(claimed, code):
    row = SolutionOutput.objects.select_for_update().get(pk=claimed.pk)
    if row.state == "running" and row.version == claimed.version:
        row.state, row.error_code = "failed", code[:80]
        event(row, "failed", details={"code": row.error_code})


def execute_next():
    output_id = SolutionOutput.objects.filter(state="queued").order_by("created_at").values_list("pk", flat=True).first()
    if output_id is None:
        return None
    claimed = claim(output_id)
    if claimed is None:
        return None
    try:
        services.require_current_links(claimed.revision.material, claimed.revision.content)
        if claimed.revision.source_stamp != services.stamp(claimed.revision.material, claimed.revision.content):
            raise core.PersistenceError("source_changed", "来源已变化。")
        _, _, assets = services.inputs(claimed.revision.material)
        result = rendering.render(claimed, assets)
        with transaction.atomic():
            row = get(claimed.requested_by, claimed.pk, write=True)
            if row.state == "running" and row.version == claimed.version:
                services.require_current_links(row.revision.material, row.revision.content)
                if row.revision.source_stamp != services.stamp(row.revision.material, row.revision.content):
                    raise core.PersistenceError("source_changed", "来源已变化。")
                row.result, row.state = result, "output_check"
                event(row, "rendered", details={"recipe_sha256": result["recipe_sha256"]})
    except Exception as exc:
        # Never write source content or exception strings into a worker log.
        code = getattr(exc, "code", "solution_render_failed")
        fail_claim(claimed, code if isinstance(code, str) else "solution_render_failed")
    return SolutionOutput.objects.get(pk=claimed.pk)


def recover_interrupted():
    before = timezone.now() - timedelta(minutes=30)
    for row in SolutionOutput.objects.filter(state="running", started_at__lt=before):
        fail_claim(row, "interrupted")
