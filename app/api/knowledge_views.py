"""Knowledge companion API; shared jobs and assets keep their object permissions."""
from app.solutions import queries, services
from .views import api
from .workflow_views import body


@api()
def workspace(request, material_id):
    return queries.workspace(request.user, material_id, "knowledge")


@api()
def history(request, material_id):
    return queries.history_page(request.user, material_id, request.GET.get("before"), "knowledge")


@api()
def outputs(request, material_id):
    return queries.outputs_page(request.user, material_id, request.GET.get("before"), "knowledge")


@api("POST")
def save(request, material_id):
    value = body(request, {"content", "expected_version", "request_key", "reason"})
    saved = services.save(request.user, material_id, **value, mode="knowledge")
    return {**queries.workspace(request.user, material_id, "knowledge"),
        "saved_revision": queries.revision_row(saved), "saved_source_stamp": saved.source_stamp}


@api("POST")
def action(request, material_id):
    value = body(request, {"action", "expected_version", "request_key", "reason"})
    result = services.action(request.user, material_id, **value, mode="knowledge")
    return {**queries.workspace(request.user, material_id, "knowledge"), "command_result": result}
