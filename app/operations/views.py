"""Authenticated household pages for private retention and manual timing."""
from functools import wraps
from uuid import UUID, uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, SuspiciousOperation
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from app.persistence import services as core
from . import services
from .forms import RetentionPolicyForm, WorkTimingForm
from .models import WorkTiming


LOGIN_URL = "/accounts/login/"


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
    conflict = any(part in code for part in ("conflict", "stale", "changed"))
    status = 409 if conflict else 400
    message = ("当前记录或页面凭据已改变，请刷新后重试。" if conflict
        else "操作未完成，请检查输入及本机私有目录配置。")
    return render(request, "web/message.html", {"title": "操作未完成", "message": message},
        status=status)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET"])
@never_cache
def index(request):
    try:
        data = services.operations_index(request.user)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    for row in data["households"]:
        household_id = row["household"].pk
        row["retention_url"] = (reverse("operations:retention_policy", kwargs={"household_id": household_id})
            if row["role"] == "owner" else None)
        row["timing_url"] = (reverse("operations:work_timing_new", kwargs={"household_id": household_id})
            if row["role"] in {"owner", "reviewer"} else None)
    return render(request, "operations/index.html", data)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
@never_cache
def retention_policy(request, household_id):
    try:
        data = services.retention_policy_detail(request.user, household_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    current = data["current"]
    initial = {"request_key": uuid4(), "archive_after_days": data["archive_after_days"],
        "delete_after_days": data["delete_after_days"]}
    if request.method == "GET":
        form = RetentionPolicyForm(initial=initial)
    else:
        form = RetentionPolicyForm(request.POST)
        if form.is_valid():
            try:
                services.append_retention_policy(request.user, household_id,
                    archive_after_days=form.cleaned_data["archive_after_days"],
                    delete_after_days=form.cleaned_data["delete_after_days"],
                    reason=form.cleaned_data["reason"], request_key=form.cleaned_data["request_key"])
                return redirect("operations:retention_policy", household_id=household_id)
            except core.PersistenceError as exc:
                return _failure(request, exc)
    return render(request, "operations/retention_policy.html", {**data, "form": form,
        "page_title": "本机导出保留策略"},
        status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
@never_cache
def work_timing_new(request, household_id):
    try:
        data = services.work_timing_context(request.user, household_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    initial = {"request_key": uuid4(), "context_token": data["context_token"],
        "kind": "manual_entry"}
    if request.method == "GET":
        form = WorkTimingForm(initial=initial, questions=data["question_choices"],
            attempts=data["attempt_choices"])
    else:
        # A completed request may pin versions no longer selectable for a new
        # record. Only its creator gets those choices; the service still checks
        # the exact request hash before allowing a replay.
        try:
            replay_key = UUID(request.POST.get("request_key", ""))
        except (ValueError, TypeError, AttributeError):
            replay_key = None
        prior = (WorkTiming.objects.filter(household_id=household_id,
            recorded_by=request.user, request_key=replay_key).first() if replay_key else None)
        if prior:
            data["question_choices"].append((prior.question_revision_id, prior.question_revision_id))
            if prior.attempt_revision_id:
                data["attempt_choices"].append((prior.attempt_revision_id, prior.attempt_revision_id))
        form = WorkTimingForm(request.POST, questions=data["question_choices"],
            attempts=data["attempt_choices"])
        if form.is_valid():
            try:
                services.record_work_timing(request.user, household_id,
                    question_revision_id=form.cleaned_data["question_revision_id"],
                    attempt_revision_id=form.cleaned_data["attempt_revision_id"] or None,
                    kind=form.cleaned_data["kind"], seconds=form.cleaned_data["seconds"],
                    reason=form.cleaned_data["reason"], context_token=form.cleaned_data["context_token"],
                    request_key=form.cleaned_data["request_key"])
                return redirect("operations:work_timing_new", household_id=household_id)
            except core.PersistenceError as exc:
                return _failure(request, exc)
    return render(request, "operations/work_timing_form.html", {**data, "form": form,
        "page_title": "记录题目处理用时"},
        status=400 if request.method == "POST" and not form.is_valid() else 200)
