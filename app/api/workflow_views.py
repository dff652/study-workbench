"""Material and SOP adapters. POST commands delegate to authorized services."""
from django.http import FileResponse
from django.urls import reverse
from app.web import services as materials
from app.web.models import MaterialSet
from app.web.models import PageReadingRevision
from app.printing import packets
from app.workflows import services as workflows, exchange
from .views import api, household


def body(request, fields):
    value = exchange.decode(request.body)
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError
    return value


def material_row(row):
    return {"id": str(row.pk), "title": row.title, "page_count": row.pages.count(),
            "created_at": row.created_at, "material_url": reverse("web:material_detail", args=[row.pk]),
            "prepare_url": reverse("printing:packet_prepare", args=[row.pk])}


@api()
def material_list(request):
    hid = household(request)
    rows = materials.list_materials(request.user).filter(household_id=hid)
    return {"items": [material_row(row) for row in rows[:200]], "total": rows.count()}


@api("POST")
def material_create(request):
    value = body(request, {"household_id", "title", "request_key"})
    row = materials.create_material(request.user, value.get("household_id"), value.get("title"), value.get("request_key"))
    return {"material": material_row(row)}


def ready_row(actor, material_id):
    state = packets.readiness(actor, material_id)
    content_gaps = list(state["content_gaps"])
    for page in state["material"].pages.order_by("position"):
        reading = PageReadingRevision.objects.filter(page=page).order_by("-revision_no").first()
        if not reading or reading.reading != "read" or reading.coverage != "complete" or reading.pending_items:
            content_gaps.append(f"第 {page.position} 页：整页阅读、分区或待补项尚未齐备；本任务只交付已确认题目，不代表整页整理完成。")
    return {"ready": state["ready"], "gaps": state["gaps"], "content_gaps": content_gaps, "questions": state["questions"]}


@api()
def material_detail(request, material_id):
    data = materials.material_detail(request.user, material_id)
    return {"material": material_row(data["material"]),
        "pages": [{"id": str(page.pk), "position": page.position, "sha256": page.image.sha256,
            "width": page.image.payload["width"], "height": page.image.payload["height"],
            "page_url": reverse("web:page_detail", args=[page.pk]),
            "preview_url": reverse("web:page_preview", args=[page.pk, 0])} for page in data["pages"]],
        "readiness": ready_row(request.user, material_id),
        "jobs": [job_row(job) for job in data["material"].workflow_jobs.order_by("-created_at")[:50]]}


@api("POST")
def upload(request, material_id):
    if set(request.FILES) != {"file"} or set(request.POST) != {"request_key"}:
        raise ValueError
    return materials.upload_page(request.user, material_id, request.FILES["file"], request.POST["request_key"])


def job_row(job):
    return {"id": str(job.pk), "material_id": str(job.material_id), "state": job.state,
            "context": workflows.context(job), "created_at": job.created_at, "updated_at": job.updated_at,
            "error_code": job.error_code or None, "record_count": len(job.input["records"]), "result": job.result}


@api("POST")
def create(request, material_id):
    value = body(request, {"request_key", "proposal", "learner_id"})
    job = workflows.create(request.user, material_id, request_key=value.get("request_key"),
        proposal=value.get("proposal"), learner_id=value.get("learner_id"))
    return {"job": job_row(job)}


@api()
def detail(request, job_id):
    job = workflows.detail(request.user, job_id)
    links = {"material_url": reverse("web:material_detail", args=[job.material_id]),
             "ai_url": "/ai/", "prepare_url": reverse("printing:packet_prepare", args=[job.material_id])}
    packet_id = job.result.get("packet_id")
    if packet_id:
        links["preview_url"] = reverse("printing:packet", args=[job.material_id, packet_id])
    if job.state == "complete":
        links["download_url"] = reverse("api:workflow_download", args=[job.pk])
    return {"job": job_row(job), "records": job.input["records"], "sources": job.input["sources"],
        "readiness": ready_row(request.user, job.material_id), "links": links,
        "events": [{"version": event.version, "action": event.action, "details": event.details,
                    "created_at": event.created_at} for event in job.events.all()]}


@api("POST")
def action(request, job_id):
    value = body(request, {"action", "expected", "request_key", "reason", "checks"})
    job = workflows.action(request.user, job_id, action=value.get("action"), expected=value.get("expected"),
        request_key=value.get("request_key"), reason=value.get("reason", ""), checks=value.get("checks"))
    return {"job": job_row(job)}


@api()
def download(request, job_id):
    job = workflows.detail(request.user, job_id)
    if job.state != "complete":
        raise ValueError
    return FileResponse(packets.archive(request.user, job.material_id, job.result["packet_id"]),
                        as_attachment=True, filename="study-workbench-five-books.zip")
