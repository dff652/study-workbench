"""Private HTTP endpoints for version-pinned teaching diagrams."""
from pathlib import Path
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.utils.cache import patch_cache_control
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods

from app.exports.contracts import ExportError
from app.persistence import services as core
from app.web import records
from app.web.views import _failure
from . import diagram_services
from .diagram_forms import DiagramForm
from .views import _signed


def _source_choices(question):
    return [(ref["region_revision_id"], f"原图区域 {index}")
        for index, ref in enumerate(question.payload.get("evidence_refs", []), 1)
        if ref.get("region_revision_id")]


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
@never_cache
def diagrams(request, pk):
    try:
        data = diagram_services.details(request.user, pk)
    except ObjectDoesNotExist as exc:
        raise Http404 from exc
    except core.PersistenceError as exc:
        return _failure(request, exc)

    question = data["question"]
    context_token = _signed(question, "diagram", data["context"])
    initial = {"context": context_token, "request_key": uuid4().hex,
        "placement": "question", "width_points": 320, "min_label_points": 12}
    if request.method == "GET":
        form = DiagramForm(initial=initial)
        status = 200
    else:
        form = DiagramForm(request.POST, request.FILES, initial=initial)
        status = 400
    form.fields["source_region_id"].choices = _source_choices(question)

    if request.method == "POST" and form.is_valid():
        try:
            expected = records.read_context(request.POST.get("context", ""),
                question.entity.household_id, "question", question.pk, "diagram")
            values = form.cleaned_data
            diagram_services.save_diagram(request.user, question.pk,
                placement=values["placement"], png_upload=values["png_upload"],
                vector_upload=values["vector_upload"], source_region_id=values["source_region_id"],
                alt=values["alt"], conditions=values["conditions"],
                width_points=values["width_points"], min_label_points=values["min_label_points"],
                independent_safe=values["independent_safe"], basis=values["basis"],
                expected=expected, request_key=values["request_key"])
            return redirect(f"{request.path}?saved=1")
        except core.PersistenceError as exc:
            if exc.code in {"invalid_input"}:
                form.add_error(None, str(exc))
                status = 400
            else:
                return _failure(request, exc)
        except (ValueError, ExportError) as exc:
            form.add_error(None, str(exc))
            status = 400
    elif request.method == "POST":
        status = 400

    response = render(request, "printing/diagrams.html", {
        "question": question, "history": data["history"], "form": form,
        "can_write": data["can_write"], "saved": request.GET.get("saved") == "1",
    }, status=status)
    patch_cache_control(response, private=True, no_store=True)
    return response


@login_required
@require_GET
@never_cache
def diagram_file(request, pk, name):
    try:
        path = diagram_services.diagram_file(request.user, pk, name)
    except ObjectDoesNotExist as exc:
        raise Http404 from exc
    except core.PersistenceError as exc:
        return _failure(request, exc)

    if name == "png":
        response = FileResponse(path.open("rb"), content_type="image/png")
        response["Content-Disposition"] = 'inline; filename="teaching-diagram.png"'
    elif name == "vector":
        suffix = Path(path.name).suffix.lower()
        if suffix not in {".pdf", ".svg"}:
            raise Http404
        response = FileResponse(path.open("rb"), content_type="application/octet-stream",
            as_attachment=True, filename=f"teaching-diagram{suffix}")
    else:
        raise Http404
    response["X-Content-Type-Options"] = "nosniff"
    patch_cache_control(response, private=True, no_store=True)
    return response
