from functools import wraps
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, SuspiciousOperation
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app.persistence import services as core
from app.persistence.models import EntityRecord, RevisionRecord
from . import services
from .forms import ModelConfigForm, RunSelectionForm
from .models import ModelRun

LOGIN_URL = "/accounts/login/"
TASK_LABELS = {"question": "题干识别草稿", "knowledge": "知识草稿",
    "assessment": "作答评价草稿", "variant": "变式题草稿"}
STATUS_LABELS = {"queued": "排队中", "running": "运行中", "awaiting_review": "待人工复核",
    "failed": "失败", "cancelled": "已取消", "stale": "已过期", "applied": "已应用"}


def _not_found(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ObjectDoesNotExist as exc:
            raise Http404 from exc
        except SuspiciousOperation as exc:
            return _failure(request, core.PersistenceError("stale_context", str(exc)))
    return wrapped


def _failure(request, error):
    code = getattr(error, "code", "")
    if code in {"not_found", "permission_denied", "unauthorized", "object_not_found"}:
        raise Http404
    status = 409 if any(part in code for part in ("conflict", "stale", "changed")) else 400
    message = "内容或依赖已改变，请重新打开任务。" if status == 409 else "操作未完成，请检查配置或选择。"
    return render(request, "ai/message.html", {"title": "AI 草稿任务", "message": message}, status=status)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def index(request):
    try:
        data = services.home_context(request.user, request.GET.get("household") or None)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    for run in data["runs"]:
        run.task_label = TASK_LABELS.get(run.task_kind, "模型任务")
        run.status_label = STATUS_LABELS.get(run.status, "未知状态")
    return render(request, "ai/index.html", data)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
@never_cache
def config(request, household_id):
    try:
        data = services.home_context(request.user, household_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    if not data["can_configure"]:
        raise Http404
    if request.method == "POST":
        form = ModelConfigForm(request.POST)
        if form.is_valid():
            try:
                row = services.create_model_config(request.user, household_id, data=form.cleaned_data)
            except core.PersistenceError as exc:
                return _failure(request, exc)
            return redirect("ai:index")
    else:
        config = data["config"]
        initial = ({field: getattr(config, field) for field in ModelConfigForm.base_fields if hasattr(config, field)}
            if config else {"cloud_enabled": False, "batch_budget": 0,
                "outbound_scope": "reviewed_text", "non_billable_gateway": False})
        form = ModelConfigForm(initial=initial)
    return render(request, "ai/config.html", {**data, "form": form})


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def run_new(request, household_id, task_kind):
    try:
        context = services.selection_context(request.user, household_id, task_kind)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    form = RunSelectionForm(context=context)
    return render(request, "ai/run_form.html", {"context": context, "form": form,
        "task_title": TASK_LABELS.get(task_kind, "模型任务")})


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
@never_cache
def run_create(request, household_id, task_kind):
    try:
        replay = services.replay_queued_request(request.user, household_id, task_kind=task_kind,
            source_revision_ids=request.POST.getlist("source_revision_ids"),
            question_revision_ids=request.POST.getlist("question_revision_ids"),
            attempt_revision_id=request.POST.get("attempt_revision_id") or None,
            selected_region_revision_ids=request.POST.getlist("selected_region_revision_ids"),
            include_attempt_text=request.POST.get("include_attempt_text") in ("on", "true", "1"),
            selection_token=request.POST.get("selection_token", ""),
            request_key=request.POST.get("request_key", ""))
    except core.PersistenceError as exc:
        return _failure(request, exc)
    if replay:
        return redirect("ai:run_detail", run_id=replay.pk)
    try:
        context = services.selection_context(request.user, household_id, task_kind)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    form = RunSelectionForm(request.POST, context=context)
    if not form.is_valid():
        return render(request, "ai/run_form.html", {"context": context, "form": form,
            "task_title": TASK_LABELS.get(task_kind, "模型任务")}, status=400)
    if form.cleaned_data["task_kind"] != task_kind:
        return _failure(request, core.PersistenceError("stale_context", "任务类型已改变。"))
    try:
        run = services.queue_run(request.user, household_id, task_kind=task_kind,
            source_revision_ids=form.cleaned_data["source_revision_ids"],
            question_revision_ids=form.cleaned_data["question_revision_ids"],
            attempt_revision_id=form.cleaned_data.get("attempt_revision_id") or None,
            selected_region_revision_ids=form.cleaned_data["selected_region_revision_ids"],
            include_attempt_text=form.cleaned_data.get("include_attempt_text", False),
            selection_token=form.cleaned_data["selection_token"],
            request_key=form.cleaned_data["request_key"])
    except core.PersistenceError as exc:
        return _failure(request, exc)
    return redirect("ai:run_detail", run_id=run.pk)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def run_detail(request, run_id):
    try:
        data = services.run_detail(request.user, run_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    if data["run"].status in (ModelRun.Status.AWAITING_REVIEW, ModelRun.Status.APPLIED):
        return redirect("ai:review", run_id=run_id)
    data["request_key"] = uuid4().hex
    data["run_status"] = STATUS_LABELS.get(data["run"].status, "未知状态")
    data["task_label"] = TASK_LABELS.get(data["run"].task_kind, "模型任务")
    data["proposal"] = data["run"].response.get("proposal") if data["run"].response else None
    data["output_links"] = _output_links(data["household_id"], data["run"].output_revision_ids)
    return render(request, "ai/run_detail.html", data)


def _output_links(household_id, revision_ids):
    links = []
    for revision in RevisionRecord.objects.filter(pk__in=revision_ids,
            entity__household_id=household_id).select_related("entity"):
        entity = revision.entity
        if entity.kind == "question":
            links.append({"label": "查看题目草稿与复核", "url": reverse("knowledge:question_detail",
                kwargs={"entity_id": entity.pk})})
        elif entity.kind in ("knowledge", "method", "question_type"):
            links.append({"label": "查看知识节点草稿与复核", "url": reverse("knowledge:node_detail",
                kwargs={"entity_id": entity.pk})})
        elif entity.kind == "assessment":
            links.append({"label": "查看作答评价草稿与复核", "url": reverse("learning:assessment_detail",
                kwargs={"assessment_id": entity.stable_id})})
        elif entity.kind == "erratum":
            target_id = revision.payload.get("target_revision_id")
            question = RevisionRecord.objects.filter(pk=target_id,
                entity__household_id=household_id, entity__kind="question").first()
            if question:
                links.append({"label": "查看印刷文字订正与复核", "url": reverse("printing:erratum",
                    kwargs={"pk": question.pk})})
    return links


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
@never_cache
def run_execute(request, run_id):
    try:
        services.request_execution(request.user, run_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    return redirect("ai:run_detail", run_id=run_id)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
@never_cache
def run_cancel(request, run_id):
    try:
        services.cancel_run(request.user, run_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    return redirect("ai:run_detail", run_id=run_id)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
@never_cache
def run_apply(request, run_id):
    try:
        result = services.apply_run(request.user, run_id, request_key=request.POST.get("request_key", ""))
    except core.PersistenceError as exc:
        return _failure(request, exc)
    if result.get("stale"):
        return render(request, "ai/message.html", {"title": "任务已过期",
            "message": "来源或依赖已改变，AI 结果保留为过期记录，未写入草稿。"}, status=409)
    return redirect("ai:run_detail", run_id=run_id)
