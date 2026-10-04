"""Authenticated HTML and private image responses for manual review."""
import json
from functools import wraps
from pathlib import Path
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist, SuspiciousOperation
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app.persistence.services import PersistenceError
from . import services
from .forms import MaterialForm, QuestionForm, ReorderPagesForm, ReviewForm, UploadPageForm
from .derivative_forms import DerivativeForm
from . import derivatives


LOGIN_URL = "/accounts/login/"
CONTEXT_SALT = "study-workbench.question-context.v1"
CONTEXT_MAX_AGE = 60 * 60


def _failure(request, error, *, json_response=False):
    code = getattr(error, "code", "")
    if code in {"not_found", "permission_denied", "unauthorized", "object_not_found"}:
        raise Http404
    if "conflict" in code or "stale" in code or "changed" in code:
        status, message = 409, "内容或来源已变化，请重新打开并确认当前版本。"
    elif code == "invalid_image":
        status, message = 400, "文件不是有效的 JPEG/PNG 图片，或图片损坏、超过像素上限。"
    elif code == "upload_too_large":
        status, message = 400, "单张照片超过 12 MiB 上限。"
    elif code in {"invalid_region", "missing_region"}:
        status, message = 400, "原图区域无效，请重新框选并检查坐标。"
    elif code in {"invalid_input", "invalid_order", "missing_text"}:
        status, message = 400, "提交内容不完整或不符合要求，请检查后重试。"
    else:
        status, message = 400, "操作未完成，请检查输入后重试。"
    if json_response:
        return JsonResponse({"ok": False, "message": message}, status=status)
    return render(request, "web/message.html", {"title": "操作未完成", "message": message}, status=status)


def _not_found(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ObjectDoesNotExist as exc:
            raise Http404 from exc
        except ImproperlyConfigured:
            return render(request, "web/message.html", {
                "title": "服务尚未就绪",
                "message": "私有资料存储尚未配置，请稍后重试。",
            }, status=503)
    return wrapped


def _request_wants_json(request):
    return "application/json" in request.headers.get("Accept", "") or request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _current_revision(data):
    current = data["current"]
    header = current.get("header", {}) if isinstance(current, dict) else {}
    return str(header.get("revision_id", ""))


def _issue_context(question_id, revision_id, snapshot, purpose):
    return signing.dumps({
        "purpose": purpose,
        "question_id": str(question_id),
        "revision_id": str(revision_id),
        "context": snapshot,
    }, salt=CONTEXT_SALT)


def _read_context(token, question_id, purpose):
    try:
        value = signing.loads(token, salt=CONTEXT_SALT, max_age=CONTEXT_MAX_AGE)
    except signing.BadSignature as exc:
        raise SuspiciousOperation("Invalid signed question context") from exc
    if (not isinstance(value, dict) or value.get("purpose") != purpose
            or value.get("question_id") != str(question_id)
            or not isinstance(value.get("revision_id"), str)
            or not isinstance(value.get("context"), dict)):
        raise SuspiciousOperation("Invalid signed question context")
    return value


def _page_cards(actor, pages):
    cards = []
    for page in pages:
        page_id = str(page.id)
        detail = services.page_detail(actor, page_id)
        previews = detail["previews"]
        preview = next((row for row in previews if row.rotation == 0), previews[0] if previews else None)
        cards.append({
            "page_id": page_id,
            "position": page.position,
            "original_name": page.original_name,
            "preview": preview,
            "preview_url": reverse("web:page_preview", kwargs={"page_id": page_id, "rotation": preview.rotation}) if preview else "",
            "preview_options": [
                {"rotation": row.rotation, "width": row.width, "height": row.height, "sha256": row.sha256,
                 "url": reverse("web:page_preview", kwargs={"page_id": page_id, "rotation": row.rotation})}
                for row in previews
            ],
            "questions": detail["questions"],
            "page_url": reverse("web:page_detail", kwargs={"page_id": page_id}),
        })
    return cards


def _source_card(actor, source, page_cache):
    page_id = source["page_id"]
    if page_id not in page_cache:
        page_cache[page_id] = services.page_detail(actor, page_id)
    detail = page_cache[page_id]
    page = detail["page"]
    card = {
        **source,
        "page_position": page.position,
        "page_name": page.original_name,
        "page_url": reverse("web:page_detail", kwargs={"page_id": page_id}),
        "preview_url": "",
        "region_style": "",
    }
    preview = next((row for row in detail["previews"] if row.rotation == source["rotation"]), None)
    if preview:
        x0, y0, x1, y1 = source["display_bbox"]
        card["preview_url"] = reverse("web:page_preview", kwargs={"page_id": page_id, "rotation": source["rotation"]})
        card["preview_width"] = preview.width
        card["preview_height"] = preview.height
        card["region_style"] = (
            f"left:{100 * x0 / preview.width:.4f}%;top:{100 * y0 / preview.height:.4f}%;"
            f"width:{100 * (x1 - x0) / preview.width:.4f}%;height:{100 * (y1 - y0) / preview.height:.4f}%;"
        )
    return card


def _question_form_response(request, material, page_cards, form, *, editing, question_id=None, status=200):
    return render(request, "web/question_form.html", {
        "material": material,
        "page_cards": page_cards,
        "form": form,
        "page_title": "修订题目" if editing else "录入题目",
        "submit_label": "保存新修订" if editing else "保存为待审核草稿",
        "is_edit": editing,
        "question_url": reverse("web:question_detail", kwargs={"question_id": question_id}) if editing else "",
    }, status=status)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
def index(request):
    from django.conf import settings
    if request.path == "/" and settings.SWB_FRONTEND_DEFAULT:
        return redirect("frontend")
    materials = services.list_materials(request.user)
    households = services.list_households(request.user)
    return render(request, "web/index.html", {
        "materials": materials,
        "new_form": MaterialForm(initial={"request_key": uuid4()}, households=households),
        "households": households,
    })


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
def material_new(request):
    households = services.list_households(request.user)
    form = MaterialForm(request.POST, households=households)
    if not form.is_valid():
        return render(request, "web/index.html", {
            "materials": services.list_materials(request.user),
            "new_form": form,
            "households": households,
        }, status=400)
    try:
        material = services.create_material(
            request.user,
            form.cleaned_data["household_id"],
            form.cleaned_data["title"],
            str(form.cleaned_data["request_key"]),
        )
    except PersistenceError as exc:
        return _failure(request, exc)
    return redirect("web:material_detail", material_id=material.id)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def material_detail(request, material_id):
    if request.method == "POST":
        form = UploadPageForm(request.POST, request.FILES)
        if not form.is_valid():
            if _request_wants_json(request):
                return JsonResponse({"ok": False, "message": "请选择有效照片。"}, status=400)
            detail = services.material_detail(request.user, material_id)
            return render(request, "web/material.html", {
                **detail, "upload_form": form,
                "order_form": ReorderPagesForm(initial={"request_key": uuid4(), "ids": json.dumps([str(p.id) for p in detail["pages"]])}),
                "upload_result": "",
                "question_new_url": reverse("web:question_new", kwargs={"material_id": material_id}),
            }, status=400)
        try:
            result = services.upload_page(
                request.user, material_id, form.cleaned_data["image"], str(form.cleaned_data["request_key"])
            )
        except PersistenceError as exc:
            return _failure(request, exc, json_response=_request_wants_json(request))
        if _request_wants_json(request):
            return JsonResponse({"ok": True, **result})
        return redirect(f"{reverse('web:material_detail', kwargs={'material_id': material_id})}?upload={'duplicate' if result['duplicate_image'] else 'saved'}")

    try:
        detail = services.material_detail(request.user, material_id)
    except PersistenceError as exc:
        return _failure(request, exc)
    return render(request, "web/material.html", {
        **detail,
        "upload_form": UploadPageForm(initial={"request_key": uuid4()}),
        "order_form": ReorderPagesForm(initial={
            "request_key": uuid4(),
            "ids": json.dumps([str(page.id) for page in detail["pages"]]),
        }),
        "upload_result": request.GET.get("upload", ""),
        "question_new_url": reverse("web:question_new", kwargs={"material_id": material_id}),
    })


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
def reorder_pages(request, material_id):
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body)
            form = ReorderPagesForm({"ids": json.dumps(payload["ids"]), "request_key": payload["request_key"]})
        except (ValueError, TypeError, KeyError):
            return JsonResponse({"ok": False, "message": "页面顺序无效，请刷新后重试。"}, status=400)
    else:
        form = ReorderPagesForm(request.POST)
    if not form.is_valid():
        if _request_wants_json(request):
            return JsonResponse({"ok": False, "message": "页面顺序无效，请刷新后重试。"}, status=400)
        return _failure(request, PersistenceError("invalid_input", "Invalid page order"))
    try:
        result = services.reorder_pages(
            request.user, material_id, form.cleaned_data["ids"], str(form.cleaned_data["request_key"])
        )
    except PersistenceError as exc:
        return _failure(request, exc, json_response=_request_wants_json(request))
    if _request_wants_json(request):
        return JsonResponse({"ok": True, **(result if isinstance(result, dict) else {})})
    return redirect("web:material_detail", material_id=material_id)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
def page_detail(request, page_id):
    try:
        detail = services.page_detail(request.user, page_id)
    except PersistenceError as exc:
        return _failure(request, exc)
    page = detail["page"]
    previews = detail["previews"]
    default_preview = next((row for row in previews if row.rotation == 0), previews[0] if previews else None)
    question_cards = []
    for question in detail["questions"]:
        try:
            question_data = services.question_detail(request.user, question.stable_id)
            original_number = question_data["original_number"]
        except ObjectDoesNotExist:
            question_cards.append({
                "question_id": question.stable_id,
                "original_number": "旧索引题目，题干与区域待补",
                "url": "",
            })
            continue
        except PersistenceError as exc:
            return _failure(request, exc)
        question_cards.append({
            "question_id": question.stable_id,
            "original_number": original_number or "未编号题目",
            "url": reverse("web:question_detail", kwargs={"question_id": question.stable_id}),
        })
    return render(request, "web/page.html", {
        **detail,
        "preview_links": [
            {"rotation": row.rotation, "width": row.width, "height": row.height,
             "sha256": row.sha256,
             "url": reverse("web:page_preview", kwargs={"page_id": str(page.id), "rotation": row.rotation})}
            for row in previews
        ],
        "default_preview": default_preview,
        "default_preview_url": reverse("web:page_preview", kwargs={"page_id": str(page.id), "rotation": default_preview.rotation}) if default_preview else "",
        "question_cards": question_cards,
        "question_new_url": reverse("web:question_new", kwargs={"material_id": str(page.material_id)}),
        "derivatives": page.derivatives.order_by('-created_at'),
        "derivative_form": DerivativeForm(initial={'request_key':uuid4(),'rotation':0,
            'preview_sha256':default_preview.sha256 if default_preview else '',
            'display_bbox':[0,0,page.image.payload['width'],page.image.payload['height']]}),
    })


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def page_preview(request, page_id, rotation):
    try:
        preview = services.preview_file(request.user, page_id, rotation)
        path = services.asset_path(preview.storage_key, preview.sha256)
        stream = Path(path).open("rb")
    except (PersistenceError, OSError, ValueError) as exc:
        if isinstance(exc, PersistenceError):
            return _failure(request, exc)
        return _failure(request, exc)
    response = FileResponse(stream, content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
@never_cache
def derivative_create(request,page_id):
    form=DerivativeForm(request.POST)
    if not form.is_valid():return _failure(request,PersistenceError('invalid_input','请检查派生处理参数。'))
    try:
        derivatives.create_derivative(request.user,page_id,**form.cleaned_data)
    except (PersistenceError,ValueError,TypeError) as exc:
        return _failure(request,exc)
    return redirect('web:page_detail',page_id=page_id)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def derivative_file(request,derivative_id):
    try:row,path=derivatives.derivative_file(request.user,derivative_id)
    except (PersistenceError,OSError,ValueError) as exc:return _failure(request,exc)
    response=FileResponse(path.open('rb'),content_type='image/png')
    response['Cache-Control']='private, no-store'
    response['X-Content-Type-Options']='nosniff'
    return response


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def question_new(request, material_id):
    try:
        material_data = services.material_detail(request.user, material_id)
        page_cards = _page_cards(request.user, material_data["pages"])
    except PersistenceError as exc:
        return _failure(request, exc)
    if request.method == "GET":
        form = QuestionForm(initial={"request_key": uuid4(), "sources": "[]", "reason": "对照原图录入题目"})
    else:
        form = QuestionForm(request.POST)
        if form.is_valid():
            try:
                result = services.save_question(
                    request.user, material_id,
                    printed_text=form.cleaned_data["printed_text"],
                    display_markup=form.cleaned_data["display_markup"] or None,
                    image_print_confirmed=form.cleaned_data['image_print_confirmed'],
                    original_number=form.cleaned_data["original_number"],
                    sources=form.cleaned_data["sources"],
                    request_key=str(form.cleaned_data["request_key"]),
                    reason=form.cleaned_data["reason"],
                    confirm=request.POST.get('submit_action')=='confirm',
                )
            except PersistenceError as exc:
                if exc.code in {"missing_region", "invalid_region"}:
                    form.add_error("sources", "请重新检查所选原图区域。")
                    return _question_form_response(request, material_data["material"], page_cards, form, editing=False, status=400)
                return _failure(request, exc)
            return redirect("web:question_detail", question_id=result["question_id"])
    return _question_form_response(
        request, material_data["material"], page_cards, form, editing=False,
        status=400 if request.method == "POST" and not form.is_valid() else 200,
    )


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
def question_detail(request, question_id):
    try:
        data = services.question_detail(request.user, question_id)
        if data['material'] is None:
            return redirect('knowledge:question_detail', entity_id=data['question'].pk)
        page_cache = {}
        source_links = [_source_card(request.user, source, page_cache) for source in data["sources"]]
        for revision in data["history"]:
            try:
                metadata = revision.questionsource
            except ObjectDoesNotExist:
                metadata = None
            revision.web_original_number = metadata.original_number if metadata else ""
            revision.web_printed_text = revision.payload.get("printed_text") or ""
            revision.web_history_sources = [
                _source_card(request.user, source, page_cache) for source in metadata.sources
            ] if metadata else []
    except PersistenceError as exc:
        return _failure(request, exc)
    revision_id = _current_revision(data)
    review_form = ReviewForm(initial={
        "request_key": uuid4(),
        "revision_id": revision_id,
        "context_token": _issue_context(question_id, revision_id, data["review_context"], "review"),
    })
    for revision in data["history"]:
        try:
            revision.web_review_decisions = list(revision.review_decisions.select_related("actor").order_by("recorded_at"))
            revision.web_review_state = revision.review_projection.state
        except AttributeError:
            revision.web_review_decisions = []
            revision.web_review_state = "draft"
    return render(request, "web/question.html", {
        **data,
        "review_form": review_form,
        "current_revision_id": revision_id,
        "current_revision_no": data["history"][0].revision_no if data["history"] else "?",
        "current_state": data["review_context"].get("state", "draft"),
        "edit_url": reverse("web:question_edit", kwargs={"question_id": question_id}),
        "source_links": source_links,
    })


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def question_edit(request, question_id):
    try:
        data = services.question_detail(request.user, question_id)
        if data['material'] is None:
            return redirect('knowledge:question_detail', entity_id=data['question'].pk)
        page_cards = _page_cards(request.user, services.material_detail(request.user, str(data["material"].id))["pages"])
    except PersistenceError as exc:
        return _failure(request, exc)
    revision_id = _current_revision(data)
    current = data["current"]
    if request.method == "GET":
        sources = [{key: source[key] for key in ("page_id", "rotation", "preview_sha256", "display_bbox")}
                   for source in data["sources"]]
        form = QuestionForm(initial={
            "request_key": uuid4(),
            "original_number": data["original_number"],
            "printed_text": current.get("printed_text", ""),
            "display_markup": current.get("display_markup", ""),
            "sources": json.dumps(sources),
            "reason": "对照原图修订题目",
            "context_token": _issue_context(question_id, revision_id, data["edit_context"], "edit"),
        })
    else:
        form = QuestionForm(request.POST)
        if form.is_valid():
            try:
                signed = _read_context(form.cleaned_data["context_token"], question_id, "edit")
            except (SuspiciousOperation, signing.BadSignature):
                return _failure(request, PersistenceError("stale_context", "The edit context is invalid"))
            try:
                result = services.save_question(
                    request.user, str(data["material"].id),
                    printed_text=form.cleaned_data["printed_text"],
                    display_markup=form.cleaned_data["display_markup"] or None,
                    image_print_confirmed=form.cleaned_data['image_print_confirmed'],
                    original_number=form.cleaned_data["original_number"],
                    sources=form.cleaned_data["sources"],
                    request_key=str(form.cleaned_data["request_key"]),
                    reason=form.cleaned_data["reason"],
                    question_id=question_id,
                    expected_context=signed["context"],
                    confirm=request.POST.get('submit_action')=='confirm',
                )
            except PersistenceError as exc:
                if exc.code in {"missing_region", "invalid_region"}:
                    form.add_error("sources", "请重新检查所选原图区域。")
                    return _question_form_response(request, data["material"], page_cards, form,
                                                   editing=True, question_id=question_id, status=400)
                return _failure(request, exc)
            return redirect("web:question_detail", question_id=result["question_id"])
    return _question_form_response(
        request, data["material"], page_cards, form, editing=True, question_id=question_id,
        status=400 if request.method == "POST" and not form.is_valid() else 200,
    )


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
def question_review(request, question_id):
    form = ReviewForm(request.POST)
    if not form.is_valid():
        return _failure(request, PersistenceError("invalid_input", "Invalid review"))
    try:
        signed = _read_context(form.cleaned_data["context_token"], question_id, "review")
    except (SuspiciousOperation, signing.BadSignature):
        return _failure(request, PersistenceError("stale_context", "The review context is invalid"))
    if signed["revision_id"] != form.cleaned_data["revision_id"]:
        return _failure(request, PersistenceError("stale_context", "The review revision changed"))
    try:
        services.review_question(
            request.user, question_id, signed["revision_id"],
            action=form.cleaned_data["action"], reason=form.cleaned_data["reason"],
            context=signed["context"], request_key=str(form.cleaned_data["request_key"]),
        )
    except PersistenceError as exc:
        return _failure(request, exc)
    return redirect("web:question_detail", question_id=question_id)
