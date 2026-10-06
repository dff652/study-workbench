"""Authenticated schedule and evidence-report pages."""
from functools import wraps
from uuid import uuid4
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, SuspiciousOperation
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from app.persistence import services as core
from app.persistence.models import EntityRecord, HouseholdMember
from app.web import records
from . import services
from .forms import ScheduleEventForm, ScheduleForm


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


def _failure(request, error, *, status=None):
    code = getattr(error, "code", "")
    if code in {"not_found", "permission_denied", "unauthorized", "object_not_found"}:
        raise Http404
    if status is None:
        status = 409 if any(part in code for part in ("conflict", "stale", "changed")) else 400
    message = "计划或来源已经改变，请重新打开当前页面。" if status == 409 else "操作未完成，请检查输入后重试。"
    return render(request, "web/message.html", {"title": "操作未完成", "message": message}, status=status)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def index(request):
    try:
        data = services.home(request.user, request.GET.get("household") or None)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    for row in data["schedules"]:
        row["detail_url"] = reverse("study:schedule_detail", kwargs={"schedule_pk": row["schedule"].pk})
    for row in data["profile_links"]:
        row["report_url"] = reverse("study:report", kwargs={"learner_entity_pk": row["entity_pk"]})
        row["schedule_new_url"] = reverse("study:schedule_new", kwargs={"learner_entity_pk": row["entity_pk"]})
    for row in data['variants']:
        row['question_url'] = reverse('knowledge:question_detail', kwargs={'entity_id':row['provenance'].question_id})
    return render(request, "study/index.html", data)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
@never_cache
def schedule_new(request, learner_entity_pk):
    try:
        data = services.new_schedule_context(request.user, learner_entity_pk)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    token = records.sign_context(data["household_id"], "study_learner", str(learner_entity_pk),
        "schedule-create", data["context"])
    initial = {"request_key": uuid4(), "context_token": token}
    if request.method == "GET":
        form = ScheduleForm(initial=initial, questions=data["questions"])
    else:
        form = ScheduleForm(request.POST, questions=data["questions"])
        if form.is_valid():
            try:
                context = records.read_context(form.cleaned_data["context_token"], data["household_id"],
                    "study_learner", str(learner_entity_pk), "schedule-create")
                result = services.create_schedule(request.user, learner_entity_pk,
                    question_revision_id=form.cleaned_data["question_revision_id"],
                    due_date=form.cleaned_data["due_date"], goal=form.cleaned_data["goal"],
                    prompt_plan=form.cleaned_data["prompt_plan"], reason=form.cleaned_data["reason"],
                    context=context, request_key=str(form.cleaned_data["request_key"]))
            except core.PersistenceError as exc:
                return _failure(request, exc)
            return redirect("study:schedule_detail", schedule_pk=result["schedule_pk"])
    return render(request, "study/schedule_form.html", {"form": form, "learner": data["learner"],
        "page_title": "安排一次复习", "submit_label": "保存计划",
        "back_url": reverse("study:index")}, status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
@never_cache
def schedule_detail(request, schedule_pk):
    try:
        data = services.schedule_detail(request.user, schedule_pk)
        choices = services.schedule_attempt_choices(request.user, schedule_pk)["choices"]
    except core.PersistenceError as exc:
        return _failure(request, exc)
    if request.method == 'POST':
        # Closed plans have no new choices. Retain their exact existing binding
        # for an identical lost-response replay; the command rejects new events.
        known = {item['revision'].header.revision_id for item in choices}
        choices = [*choices, *({'revision': item['revision'], 'label': '已保存的完成关联'}
            for item in data['completion_history'] if item['revision'] and item['revision'].header.revision_id not in known)]
    token = records.sign_context(data["household_id"], "study_schedule", str(schedule_pk),
        "schedule-event", data["context"])
    initial = {"request_key": uuid4(), "context_token": token, "action": "rescheduled"}
    selected_revision = request.GET.get('attempt_revision', '')
    if selected_revision in {str(item['revision'].header.revision_id) for item in choices}:
        initial.update(action='completed', attempt_revision_id=selected_revision)
        data['saved_attempt_pending'] = True
    elif selected_revision:
        data['saved_attempt_unavailable'] = True
    if request.method == "GET":
        form = ScheduleEventForm(initial=initial, attempts=choices)
    else:
        form = ScheduleEventForm(request.POST, attempts=choices)
        if form.is_valid():
            try:
                context = records.read_context(form.cleaned_data["context_token"], data["household_id"],
                    "study_schedule", str(schedule_pk), "schedule-event")
                result = services.append_schedule_event(request.user, schedule_pk,
                    action=form.cleaned_data["action"], context=context,
                    due_date=form.cleaned_data["due_date"], goal=form.cleaned_data["goal"],
                    prompt_plan=form.cleaned_data["prompt_plan"],
                    attempt_revision_id=form.cleaned_data["attempt_revision_id"],
                    reason=form.cleaned_data["reason"], request_key=str(form.cleaned_data["request_key"]))
            except core.PersistenceError as exc:
                return _failure(request, exc)
            return redirect("study:schedule_detail", schedule_pk=result["schedule_pk"])
    data["form"] = form
    data["attempt_choices"] = choices
    data['can_write'] = HouseholdMember.objects.filter(household_id=data['household_id'], user=request.user, user__is_active=True, role__in=('owner', 'reviewer')).exists()
    data['record_attempt_url'] = reverse('learning:attempt_new', args=[data['schedule'].learner.stable_id]) + '?' + urlencode({'question': data['schedule'].target_question_revision.entity.stable_id, 'kind': 'retest', 'plan': schedule_pk})
    data["index_url"] = '/app/?' + urlencode({'view': 'progress', 'household': data['household_id'], 'learner': data['schedule'].learner.stable_id})
    return render(request, "study/schedule_detail.html", data,
        status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def report(request, learner_entity_pk):
    try:
        data = services.evidence_report(request.user, learner_entity_pk, material_id=request.GET.get("material") or None)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    from app.api import progress
    data['household_id'] = str(EntityRecord.objects.get(pk=learner_entity_pk, kind='learner').household_id)
    selected_questions = set(data['scope_question_ids']) if data.get('material_id') else None
    data['association_groups'] = progress.learner(request.user, data['household_id'], data['learner']['learner_id'], question_ids=selected_questions)['groups']
    data["index_url"] = '/app/?' + urlencode({'view': 'progress', 'household': data['household_id'], 'learner': data['learner']['learner_id'], 'tab': 'evidence'})
    data["json_url"] = reverse("study:report_json", kwargs={"learner_entity_pk": learner_entity_pk})
    data["print_report_url"] = reverse("printing:evidence_report", kwargs={"pk": learner_entity_pk})
    if data.get("material_id"):
        suffix = "?" + urlencode({"material": data["material_id"]})
        data["json_url"] += suffix
        data["print_report_url"] += suffix
    return render(request, "study/report.html", data)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def report_json(request, learner_entity_pk):
    try:
        data = services.evidence_report(request.user, learner_entity_pk, material_id=request.GET.get("material") or None)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    response = JsonResponse(data, json_dumps_params={"ensure_ascii": False, "indent": 2})
    response["Content-Disposition"] = f'attachment; filename="study-evidence-{learner_entity_pk}.json"'
    response["Cache-Control"] = "private, no-store, max-age=0"
    return response
