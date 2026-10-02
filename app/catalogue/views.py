"""Private HTTP views for question split/merge and reverse lineage."""
from functools import wraps
import json
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from app.persistence import services as core
from app.persistence.models import EntityRecord, RevisionRecord
from app.web import knowledge_services
from app.web import services as web_services
from app.web.knowledge_views import _decorate_sources
from . import services
from .forms import HouseholdForm, MergeForm, MergeSelectionForm, SplitForm


LOGIN_URL = "/accounts/login/"


def _not_found(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ObjectDoesNotExist as exc:
            raise Http404 from exc
        except ImproperlyConfigured:
            return render(request, "catalogue/message.html", {
                "title": "服务尚未就绪", "message": "私有资料存储尚未配置，请稍后重试。",
            }, status=503)
    return wrapped


def _failure(request, error):
    code = getattr(error, "code", "")
    if code in {"not_found", "permission_denied", "unauthorized", "object_not_found"}:
        raise Http404
    if code in {"head_conflict", "stale_context", "dependency_conflict", "stale_dependencies"}:
        return render(request, "catalogue/message.html", {
            "title": "来源已变化", "message": "来源题目或其依赖已有新版本；本次拆分或合并未保存，请重新选择。",
        }, status=409)
    return render(request, "catalogue/message.html", {
        "title": "操作未完成", "message": str(error) or "请检查输入后重试。",
    }, status=400)


def _households(actor):
    return web_services.list_households(actor)


def _household_id(request):
    source = request.POST if request.method == "POST" else request.GET
    return source.get("household_id", "")


def _questions_for_household(actor, household_id):
    return services.question_index(actor, household_id)["questions"]


def _detail_context(request, data):
    entity = data["entity"]
    labels = knowledge_services._question_labels(entity.household_id)
    number = ", ".join(dict.fromkeys(labels.get(entity.pk, ()))) or "—"
    for row in data["history"]:
        row.web_sources = _decorate_sources(request, row.web_sources)
    data["current_sources"] = _decorate_sources(request, data["current_sources"])
    for lineage in data["lineages"]:
        lineage["source_links"] = [(row, reverse("catalogue:question_detail", kwargs={"entity_id": row.entity.pk}))
            for row in lineage["sources"]]
        lineage["target_links"] = [(row, reverse("catalogue:question_detail", kwargs={"entity_id": row.entity.pk}))
            for row in lineage["targets"]]
    current = data["current"]
    parent_revision = RevisionRecord.objects.filter(pk=current.get("parent_question_revision_id"),
        entity__household_id=entity.household_id, entity__kind="question").select_related("entity").first()
    return {**data, "number": number, "parent_revision": parent_revision,
        "split_url": reverse("catalogue:question_split", kwargs={"entity_id": entity.pk}),
        "question_url": reverse("knowledge:question_detail", kwargs={"entity_id": entity.pk}),
        "current_missing": bool(current.get("missing_fields")) or not current.get("evidence_refs") or any(
            ref.get("region_missing") or ref.get("gaps") for ref in current.get("evidence_refs", ())) }


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def index(request):
    households = _households(request.user)
    household_id = _household_id(request)
    if not household_id and len(households) == 1:
        return redirect(f"{reverse('catalogue:index')}?household_id={households[0].household_id}")
    form = HouseholdForm(request.POST if request.method == "POST" else request.GET or None,
        households=households, initial={"household_id": household_id})
    home = None
    if form.is_valid():
        household_id = form.cleaned_data["household_id"]
        try:
            home = services.question_index(request.user, household_id)
        except core.PersistenceError as exc:
            return _failure(request, exc)
    return render(request, "catalogue/index.html", {"form": form, "home": home,
        "has_households": bool(households)})


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
def question_detail(request, entity_id):
    try:
        data = services.question_detail(request.user, entity_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    return render(request, "catalogue/question.html", _detail_context(request, data))


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def question_split(request, entity_id):
    try:
        data = services.question_detail(request.user, entity_id)
        entity = data["entity"]
        source_revision_id = entity.head_revision_id
        context_token = services.prepare_context(request.user, entity.household_id, "split", [source_revision_id])
    except core.PersistenceError as exc:
        return _failure(request, exc)
    initial = {"request_key": uuid4(), "household_id": entity.household_id,
        "source_revision_id": source_revision_id, "context_token": context_token}
    if request.method == "GET":
        form = SplitForm(initial=initial)
    else:
        form = SplitForm(request.POST)
        if form.is_valid():
            if str(form.cleaned_data["household_id"]) != str(entity.household_id):
                return _failure(request, core.PersistenceError("stale_context", "家庭与当前题目不符。"))
            try:
                result = services.split_question(request.user, entity.household_id,
                    source_revision_id=form.cleaned_data["source_revision_id"],
                    context_token=form.cleaned_data["context_token"], children=form.cleaned_data["children"],
                    reason=form.cleaned_data["reason"], request_key=str(form.cleaned_data["request_key"]))
                return redirect("catalogue:question_detail", entity_id=EntityRecord.objects.get(
                    household_id=entity.household_id, kind="question", stable_id=result["target_question_ids"][0]).pk)
            except core.PersistenceError as exc:
                return _failure(request, exc)
    data["current_sources"] = _decorate_sources(request, data["current_sources"])
    return render(request, "catalogue/split.html", {"form": form, "entity": entity,
        "household": entity.household, "current": data["current"], "source_cards": data["current_sources"],
        "number": ", ".join(dict.fromkeys(knowledge_services._question_labels(entity.household_id).get(entity.pk, ()))) or "—"},
        status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def merge(request):
    households = _households(request.user)
    household_id = _household_id(request)
    if not household_id and len(households) == 1:
        return redirect(f"{reverse('catalogue:merge')}?household_id={households[0].household_id}")
    if not household_id:
        return render(request, "catalogue/choose_household.html", {"households": households}, status=200)
    try:
        questions = _questions_for_household(request.user, household_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    choices = [(row["revision"].pk, f"{row['number']} · {row['title'][:90]} · r{row['revision'].revision_no}".strip())
        for row in questions]
    if request.method == "GET":
        selection_form = MergeSelectionForm(question_choices=choices, initial={"household_id": household_id})
        return render(request, "catalogue/merge.html", {"selection_form": selection_form, "questions": questions,
            "household_id": household_id, "phase": "select"})

    if request.POST.get("phase") == "save":
        form = MergeForm(request.POST)
        if form.is_valid():
            if str(form.cleaned_data["household_id"]) != str(household_id):
                return _failure(request, core.PersistenceError("stale_context", "家庭选择与当前页面不符。"))
            source_ids = form.cleaned_data["source_revision_ids"]
            try:
                result = services.merge_questions(request.user, household_id,
                    source_revision_ids=source_ids, context_token=form.cleaned_data["context_token"],
                    original_number=form.cleaned_data["original_number"], printed_text=form.cleaned_data["printed_text"],
                    reason=form.cleaned_data["reason"], request_key=str(form.cleaned_data["request_key"]))
                target = EntityRecord.objects.get(household_id=household_id, kind="question",
                    stable_id=result["target_question_ids"][0])
                return redirect("catalogue:question_detail", entity_id=target.pk)
            except core.PersistenceError as exc:
                return _failure(request, exc)
        source_ids = []
        try:
            source_ids = json.loads(request.POST.get("source_revision_ids", "[]"))
        except (TypeError, ValueError):
            pass
        selected = [row for row in questions if row["revision"].pk in source_ids]
        return render(request, "catalogue/merge.html", {"create_form": form, "selected": selected,
            "household_id": household_id, "phase": "save"}, status=400)

    selection_form = MergeSelectionForm(request.POST, question_choices=choices)
    if not selection_form.is_valid():
        return render(request, "catalogue/merge.html", {"selection_form": selection_form,
            "questions": questions, "household_id": household_id, "phase": "select"}, status=400)
    if str(selection_form.cleaned_data["household_id"]) != str(household_id):
        return _failure(request, core.PersistenceError("stale_context", "家庭选择与当前页面不符。"))
    source_ids = selection_form.cleaned_data["source_revision_ids"]
    try:
        token = services.prepare_context(request.user, household_id, "merge", source_ids)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    create_form = MergeForm(initial={"request_key": uuid4(),
        "household_id": household_id, "context_token": token,
        "source_revision_ids": json.dumps(source_ids, ensure_ascii=False)})
    selected = [row for row in questions if row["revision"].pk in source_ids]
    return render(request, "catalogue/merge.html", {"create_form": create_form, "selected": selected,
        "household_id": household_id, "phase": "save"})
