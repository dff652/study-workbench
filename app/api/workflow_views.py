"""Material and SOP adapters. POST commands delegate to authorized services."""
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse
from django.db import transaction
from django.db.models import Q, OuterRef, Subquery, F
from app.persistence.models import EntityRecord
from urllib.parse import urlencode
from app.web import services as materials
from app.web import subjects
from app.web.models import MaterialSet
from app.web.models import PageReadingRevision
from app.printing import packets
from app.workflows import services as workflows, exchange
from .views import api, household
from . import progress
from app.solutions.models import SolutionOutput
from app.solutions.queries import output_row


def body(request, fields):
    value = exchange.decode(request.body)
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError
    return value


def material_row(row):
    return {"id": str(row.pk), "title": row.title, "page_count": row.pages.count(),
            "classification": subjects.current(row),
            "created_at": row.created_at, "material_url": reverse("web:material_detail", args=[row.pk]),
            "prepare_url": reverse("printing:packet_prepare", args=[row.pk])}


def available_outputs():
    failed = Q()
    for name in ('content', 'math', 'subject', 'pdf_visual', 'word_pc', 'word_macos'):
        failed |= Q(result__contains={'checks': {name: {'status': 'fail'}}})
    return SolutionOutput.objects.filter(state__in=('output_check', 'complete'), result__has_key='documents').exclude(
        result__documents=[]).exclude(failed)


@api()
def material_list(request):
    hid = household(request)
    rows = materials.list_materials(request.user).filter(household_id=hid)
    query = request.GET.get("q", "").strip()[:200]
    if query:
        document_materials = SolutionOutput.objects.filter(revision__material__household_id=hid,
            result__documents__icontains=query).values('revision__material_id')
        rows = rows.filter(Q(title__icontains=query) | Q(pk__in=document_materials))
    subject = request.GET.get("subject", "")
    if subject:
        subjects.validate(subject)
        rows = subjects.classified(rows).filter(school_subject=subject)
    try:
        page = int(request.GET.get("page", "1"))
        page_size = int(request.GET.get("page_size", "20"))
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Invalid material page")
    document_mode = request.GET.get('document_mode', '')
    if document_mode:
        if document_mode not in ('solution', 'knowledge'):
            raise ValueError('Invalid document type')
        recent = available_outputs().filter(revision__material_id=OuterRef('pk'), revision__mode=document_mode
            ).order_by('-created_at', '-pk').values('created_at')[:1]
        rows = rows.annotate(latest_document_at=Subquery(recent)).order_by(F('latest_document_at').desc(nulls_last=True), '-created_at', '-pk')
    else:
        rows = rows.order_by("-created_at", "-pk")
    total = rows.count()
    start = (page - 1) * page_size
    selected = list(rows[start:start + page_size])
    selected_ids = [row.pk for row in selected]
    processing = {row['id']: row for row in progress.materials(request.user, hid, selected_ids)['materials']}
    outputs = {}
    latest = available_outputs().filter(revision__material_id__in=selected_ids).select_related('revision').order_by(
        'revision__material_id', 'revision__mode', '-created_at', '-pk').distinct('revision__material_id', 'revision__mode')
    for output in latest:
        serialized = output_row(output)
        if serialized['documents'] and not any(check.get('status') == 'fail' for check in serialized['checks'].values()):
            outputs.setdefault(str(output.revision.material_id), []).append({
                'mode': output.revision.mode, 'created_at': output.created_at,
                'revision_version': output.revision.version, 'state': output.state,
                'documents': serialized['documents'], 'zip_url': serialized['zip_url']})
    return {"items": [{**material_row(row), 'processing': processing.get(str(row.pk)),
                       'available_outputs': outputs.get(str(row.pk), [])} for row in selected], "total": total,
            "page": page, "page_size": page_size, "has_next": start + page_size < total, "query": query, "subject": subject}


@api()
@transaction.atomic
def classification(request, material_id):
    row = materials._material(request.user, material_id)
    rows = row.classifications.select_related("created_by").order_by("-version")
    before = request.GET.get("before")
    if before is not None:
        try:
            before = int(before)
            if before < 1:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("Invalid classification history cursor")
        rows = rows.filter(version__lt=before)
    selected = list(rows[:51])
    return {"classification": subjects.current(row), "history": [{"version": item.version, "subject": item.subject,
        "reason": item.reason, "author": item.created_by.get_username(), "created_at": item.created_at.isoformat()}
        for item in selected[:50]], "history_next_before": selected[49].version if len(selected) > 50 else None}


@api("POST")
@transaction.atomic
def classification_save(request, material_id):
    value = body(request, {"subject", "expected_version", "request_key", "reason"})
    saved = subjects.save(request.user, material_id, **value)
    row = materials._material(request.user, material_id)
    return {"material": material_row(row), "saved_classification": {"subject": saved.subject, "version": saved.version}}


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
    questions = [{**row, 'edit_url': reverse('web:question_detail', args=[row['question_id']]),
                  'answer_url': reverse('printing:answer', args=[row['revision_id']]) if row['confirmed'] else None,
                  'association_url': reverse('knowledge:question_detail', args=[
                      EntityRecord.objects.get(kind='question', stable_id=row['question_id'],
                          household=state['material'].household).pk])} for row in state['questions']]
    return {"ready": state["ready"], "gaps": state["gaps"], "content_gaps": content_gaps, "questions": questions}


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
    value = body(request, {"request_key", "proposal", "learner_id", "evidence_scope"})
    job = workflows.create(request.user, material_id, request_key=value.get("request_key"),
        proposal=value.get("proposal"), learner_id=value.get("learner_id"),
        evidence_scope=value.get("evidence_scope", "selected_learner_history"))
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
        "assets": {key: {"media_type": item["media_type"], "preview_url":
            reverse("api:workflow_asset", args=[job.pk]) + '?' + urlencode({'key':key})}
            for key, item in job.input.get('assets', {}).items() if item['media_type'] == 'image/png'},
        "readiness": ready_row(request.user, job.material_id), "links": links,
        "events": [{"version": event.version, "action": event.action, "details": event.details,
                    "created_at": event.created_at} for event in job.events.all()]}


@api()
def asset(request, job_id):
    job = workflows.detail(request.user, job_id)
    key = request.GET.get('key', '')
    item = job.input.get('assets', {}).get(key)
    if item is None or item['media_type'] != 'image/png':
        raise Http404
    from app.workflows.assets import decode_assets
    return HttpResponse(decode_assets({key:item})[key], content_type='image/png')


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
