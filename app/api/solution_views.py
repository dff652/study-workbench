"""Same-origin companion editor and private artifact endpoints."""
from django.http import FileResponse
from app.domain.arithmetic import ArithmeticError, formula_ast

from app.solutions import jobs, queries, rendering, services
from app.solutions.models import SolutionAsset, SolutionRevision
from app.web.services import asset_path
from app.workflows.exchange import decode
from .views import api
from .workflow_views import body


@api("POST")
def formula_preview(request):
    value = body(request, {"expression"})
    try:
        return {"formula": formula_ast(value.get("expression"))}
    except ArithmeticError as exc:
        from app.persistence.services import PersistenceError
        raise PersistenceError("invalid_solution", str(exc)) from exc


@api()
def workspace(request, material_id):
    return queries.workspace(request.user, material_id)


@api()
def history(request, material_id):
    return queries.history_page(request.user, material_id, request.GET.get("before"))


@api()
def outputs(request, material_id):
    return queries.outputs_page(request.user, material_id, request.GET.get("before"))


@api("POST")
def save(request, material_id):
    value = body(request, {"content", "expected_version", "request_key", "reason"})
    saved = services.save(request.user, material_id, **value)
    return {**queries.workspace(request.user, material_id),
        "saved_revision": queries.revision_row(saved), "saved_source_stamp": saved.source_stamp}


@api("POST")
def action(request, material_id):
    value = body(request, {"action", "expected_version", "request_key", "reason"})
    result = services.action(request.user, material_id, **value)
    return {**queries.workspace(request.user, material_id), "command_result": result}


@api()
def revision(request, revision_id):
    row = SolutionRevision.objects.select_related("material", "author").get(pk=revision_id)
    services.material(request.user, row.material_id)
    return {"revision": queries.revision_row(row)}


@api("POST")
def upload(request, material_id):
    services.upload_asset(request.user, material_id, request.FILES.get("file"),
        kind=request.POST.get("kind"), label=request.POST.get("label"), basis=request.POST.get("basis"),
        source=decode(request.POST.get("source", "null").encode()), request_key=request.POST.get("request_key"))
    return queries.workspace(request.user, material_id)


@api("POST")
def source_asset(request, material_id):
    value = body(request, {"kind", "label", "basis", "source", "request_key"})
    services.derive_asset(request.user, material_id, **value)
    return queries.workspace(request.user, material_id)


@api()
def asset(request, asset_id):
    row = SolutionAsset.objects.get(pk=asset_id)
    services.material(request.user, row.material_id)
    return FileResponse(asset_path(row.storage_key, row.sha256).open("rb"), content_type="image/png")


@api("POST")
def output_action(request, output_id):
    value = body(request, {"action", "expected_version", "request_key", "reason", "checks"})
    row = jobs.action(request.user, output_id, **value)
    result = queries.workspace(request.user, row.revision.material_id, row.revision.mode)
    if not any(item["id"] == str(row.pk) for item in result["outputs"]):
        result["outputs"].append(queries.output_row(row))
    return result


@api()
def output_detail(request, output_id):
    return {"output": queries.output_row(jobs.get(request.user, output_id))}


@api()
def output_file(request, output_id, document_id, name):
    row = jobs.get(request.user, output_id)
    path = rendering.output_file(row, document_id, name)
    media = "application/pdf" if name.endswith(".pdf") else "image/png" if name.endswith(".png") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    response = FileResponse(path.open("rb"), content_type=media, as_attachment=name.endswith(".docx"),
                            filename=(document_id + ".docx") if name.endswith(".docx") else name)
    if media == 'application/pdf':
        response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@api()
def output_zip(request, output_id):
    row = jobs.get(request.user, output_id)
    if row.state not in {"output_check", "complete"} or not row.result.get("documents"):
        from django.http import Http404
        raise Http404
    prefix = "knowledge" if row.revision.mode == "knowledge" else "solutions"
    return FileResponse(rendering.archive(row), content_type="application/zip", as_attachment=True,
                        filename=f"{prefix}-v{row.revision.version}.zip")
