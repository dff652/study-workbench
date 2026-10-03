"""Authenticated learner archive pages."""
from datetime import date
from functools import wraps
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, SuspiciousOperation
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app.domain import (
    ActualDateState, AttemptKind, BasisKind, DimensionKind, Independence,
    Judgment, Legibility, PromptStatus, ReviewState, SourceKind,
)
from app.persistence import services as core
from app.persistence.models import EntityRecord
from . import learning_services as services, records
from .learning_forms import (
    AssessmentForm, AttemptForm, CorrectionForm, ObservationForm, ProfileForm, ReviewForm,
)
from .learning_labels import (
    ATTEMPT_KIND_LABELS, ATTEMPT_STATE_LABELS, BASIS_LABELS, DIMENSION_LABELS, INDEPENDENCE_LABELS,
    JUDGMENT_LABELS, LEGIBILITY_LABELS, PROMPT_STATUS_LABELS, REVIEW_STATE_LABELS,
    SOURCE_KIND_LABELS, label as learning_label,
)


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
    message = "内容或依赖已改变，请重新打开当前记录后重试。" if status == 409 else "操作未完成，请检查输入后重试。"
    return render(request, "web/message.html", {"title": "操作未完成", "message": message}, status=status)


def _form_failure(request, form, template, context, message, *, status=400):
    form.add_error(None, message)
    return render(request, template, {**context, "form": form}, status=status)


def _household_id_for_profile(actor, learner_id):
    row = EntityRecord.objects.filter(kind="learner", stable_id=learner_id).select_related("household").first()
    if row is None:
        raise Http404
    services.visible_household(actor, row.household_id)
    return row.household_id


def _household_id_for_kind(actor, kind, stable_id):
    row = EntityRecord.objects.filter(kind=kind, stable_id=stable_id).select_related("household").first()
    if row is None:
        raise Http404
    services.visible_household(actor, row.household_id)
    return row.household_id


def _source_history(actor, household_id, bundle, entity):
    return [{"revision": revision,
             "sources": services._source_cards(actor, household_id, bundle, revision.evidence_refs)}
            for revision in reversed(entity.revisions)]


def _observation_form_data(form, profiles, page_cards, *, is_edit=False):
    return {"form": form, "profiles": profiles, "page_cards": page_cards,
            "submit_label": "保存来源观察", "is_edit": is_edit,
            "storage_key": form["request_key"].value() if form["request_key"].value() else "new"}


def _attempt_form_data(form, choices, *, page_title, learner_id=None, learners=(), allow_identity=False):
    return {"form": form, "page_title": page_title, "learner_id": learner_id,
            "learners": learners, "allow_identity": allow_identity,
            "questions": choices["questions"], "prior_attempts": choices["prior_attempts"],
            "observations": choices["observation_choices"], "submit_label": "保存作答记录"}


def _attempt_initial(revision, attempt, context_token):
    return {"request_key": uuid4(), "learner_id": attempt.learner_id,
        "question_id": attempt.question_id, "attempt_kind": revision.attempt_kind.value,
        "source_kind": revision.source_kind.value, "independence": revision.independence.value,
        "prompt_status": revision.prompt_status.value, "prompts": "\n".join(revision.prompts),
        "actual_date_state": revision.actual_date_state.value, "actual_date": revision.actual_date or "",
        "legibility": revision.legibility.value, "answer_text": revision.answer_text or "",
        "authorship_basis": revision.authorship_basis,
        "observation_values": [f"{item.observation_id}|{item.observation_revision_id}" for item in revision.observation_refs],
        "previous_attempt_id": attempt.previous_attempt_id or "", "context_token": context_token}


def _assessment_initial(revision, evidence_refs):
    evidence_indices = {ref: str(index) for index, ref in enumerate(evidence_refs)}
    result = {}
    for dimension in revision.dimensions:
        key = dimension.dimension.value
        result[key] = {"judgment": dimension.judgment.value, "basis": dimension.basis.value,
            "evidence": [evidence_indices[ref] for ref in dimension.evidence_refs if ref in evidence_indices],
            "rationale": dimension.rationale, "unknown_reason": dimension.unknown_reason or ""}
    return result


def _assessment_form(form, evidence_choices, errata_choices, *, is_edit=False):
    return {"form": form, "evidence_choices": evidence_choices,
            "errata_choices": errata_choices, "is_edit": is_edit,
            "dimensions": form.dimension_fields}


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def index(request):
    try:
        data = services.profile_list(request.user, request.GET.get("household") or None)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    form = ProfileForm(initial={"request_key": uuid4(), "household_id": data["household_id"]},
                       households=data["households"])
    return render(request, "learning/index.html", {**data, "form": form})


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def profile_new(request):
    households = services.household_options(request.user)
    if request.method == "GET":
        form = ProfileForm(initial={"request_key": uuid4()}, households=households)
    else:
        form = ProfileForm(request.POST, households=households)
        if form.is_valid():
            try:
                result = services.create_profile(request.user, form.cleaned_data["household_id"],
                    display_name=form.cleaned_data["display_name"], grade=form.cleaned_data["grade"],
                    request_key=str(form.cleaned_data["request_key"]))
            except core.PersistenceError as exc:
                return _failure(request, exc)
            return redirect("learning:profile_detail", learner_id=result["learner_id"])
    return render(request, "learning/profile_form.html", {"form": form, "households": households},
                  status=400 if request.method == "POST" else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def profile_detail(request, learner_id):
    try:
        data = services.profile_detail(request.user, learner_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    question_filter = request.GET.get("question", "")
    knowledge_filter = request.GET.get("knowledge", "")
    type_filter = request.GET.get("type", "")
    review_filter = request.GET.get("review", "")
    error_filter = request.GET.get("error", "")
    attempts = data["attempts"]
    if question_filter and question_filter not in {item["attempt"].question_id for item in attempts}:
        raise Http404
    if knowledge_filter and knowledge_filter not in {item["stable_id"] for item in data["knowledge_options"]}:
        raise Http404
    if type_filter and type_filter not in {item["stable_id"] for item in data["type_options"]}:
        raise Http404
    if question_filter:
        attempts = [item for item in attempts if item["attempt"].question_id == question_filter]
    if knowledge_filter:
        attempts = [item for item in attempts if knowledge_filter in item["knowledge_ids"]]
    if type_filter:
        attempts = [item for item in attempts if type_filter in item["type_ids"]]
    if review_filter:
        attempts = [item for item in attempts if any(row["state"] == review_filter for row in item["assessments"])]
    if error_filter == "yes":
        attempts = [item for item in attempts if any(
            row["state"] in ("accepted", "rejected", "draft") and any(
                dimension.judgment in (Judgment.INCORRECT, Judgment.PARTIAL) for dimension in row["revision"].dimensions)
            for row in item["assessments"])]
    from_date = request.GET.get("from", "")
    to_date = request.GET.get("to", "")
    try:
        from_date_value = date.fromisoformat(from_date) if from_date else None
        to_date_value = date.fromisoformat(to_date) if to_date else None
    except ValueError as exc:
        raise Http404 from exc
    if from_date_value and to_date_value and from_date_value > to_date_value:
        raise Http404
    if from_date:
        attempts = [item for item in attempts if item["revision"].actual_date_state.value == "known"
            and item["revision"].actual_date
            and date.fromisoformat(item["revision"].actual_date) >= from_date_value]
    if to_date:
        attempts = [item for item in attempts if item["revision"].actual_date_state.value == "known"
            and item["revision"].actual_date
            and date.fromisoformat(item["revision"].actual_date) <= to_date_value]
    data.update({"attempts": sorted(attempts, key=lambda item: item["sort_date"], reverse=True),
        "filters": {"question": question_filter, "knowledge": knowledge_filter, "type": type_filter,
            "review": review_filter, "error": error_filter, "from": from_date, "to": to_date}})
    for item in data["attempts"]:
        item["detail_url"] = reverse("learning:attempt_detail", kwargs={"attempt_id": item["attempt"].attempt_id})
        revision = item["revision"]
        item["attempt_kind_label"] = learning_label(ATTEMPT_KIND_LABELS, revision.attempt_kind)
        item["source_kind_label"] = learning_label(SOURCE_KIND_LABELS, revision.source_kind)
        item["independence_label"] = learning_label(INDEPENDENCE_LABELS, revision.independence)
        item["prompt_status_label"] = learning_label(PROMPT_STATUS_LABELS, revision.prompt_status)
        item["legibility_label"] = learning_label(LEGIBILITY_LABELS, revision.legibility)
        for assessment in item["assessments"]:
            assessment["state_label"] = learning_label(REVIEW_STATE_LABELS, assessment["state"])
            assessment["dimension_labels"] = [{
                "dimension": learning_label(DIMENSION_LABELS, dimension.dimension),
                "judgment": learning_label(JUDGMENT_LABELS, dimension.judgment),
                "basis": learning_label(BASIS_LABELS, dimension.basis),
            } for dimension in assessment["revision"].dimensions]
    return render(request, "learning/profile.html", data)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def observation_new(request):
    household_id = request.GET.get("household") if request.method == "GET" else request.POST.get("household_id")
    if not household_id:
        raise Http404
    try:
        data = services.observation_new_context(request.user, household_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    initial = {"request_key": uuid4(), "profile_context_id": "", "legibility": Legibility.UNKNOWN.value,
        "author_state": "unknown", "actual_date_state": "unknown", "sources": "[]"}
    initial["household_id"] = household_id
    if request.method == "GET":
        form = ObservationForm(initial=initial, profiles=data["profiles"])
    else:
        form = ObservationForm(request.POST, profiles=data["profiles"])
        if form.is_valid():
            try:
                result = services.save_observation(request.user, household_id,
                    profile_context_id=form.cleaned_data["profile_context_id"], legibility=form.cleaned_data["legibility"],
                    author_state=form.cleaned_data["author_state"], author_learner_id=form.cleaned_data["author_learner_id"],
                    confirmation_basis=form.cleaned_data["confirmation_basis"], actual_date_state=form.cleaned_data["actual_date_state"],
                    actual_date=form.cleaned_data["actual_date"], notes=form.cleaned_data["notes"],
                    sources=form.cleaned_data["sources"], request_key=str(form.cleaned_data["request_key"]),
                    reason=form.cleaned_data["reason"])
            except core.PersistenceError as exc:
                if exc.code in ("invalid_input", "invalid_region", "preview_changed"):
                    form.add_error(None, "来源观察未保存，请检查信息、证据缺口和原图区域。")
                    return render(request, "learning/observation_form.html", {
                        **_observation_form_data(form, data["profiles"], data["page_cards"]),
                        "household_id": household_id, "page_title": "新建来源观察"}, status=400)
                return _failure(request, exc)
            return redirect("learning:observation_detail", observation_id=result["observation_id"])
    return render(request, "learning/observation_form.html", {
        **_observation_form_data(form, data["profiles"], data["page_cards"]),
        "household_id": household_id, "page_title": "新建来源观察"},
        status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def observation_detail(request, observation_id):
    try:
        data = services.observation_edit_context(request.user, observation_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    data["history"] = _source_history(request.user, data["household_id"], data["bundle"], data["observation"])
    data["current_revision"] = data["observation"].revisions[-1]
    data["current_legibility_label"] = learning_label(LEGIBILITY_LABELS, data["current_revision"].legibility)
    data["edit_url"] = reverse("learning:observation_edit", kwargs={"observation_id": observation_id})
    return render(request, "learning/observation.html", data)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def observation_edit(request, observation_id):
    try:
        data = services.observation_edit_context(request.user, observation_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    revision = data["observation"].revisions[-1]
    context = data["edit_context"]
    token = records.sign_context(data["household_id"], "observation", observation_id, "edit", context)
    initial = {"request_key": uuid4(), "profile_context_id": data["observation"].profile_context_id or "",
        "legibility": revision.legibility.value, "author_state": revision.author_state.value,
        "author_learner_id": revision.author_learner_id or "", "confirmation_basis": revision.confirmation_basis or "",
        "actual_date_state": revision.actual_date_state.value, "actual_date": revision.actual_date or "",
        "notes": revision.notes, "sources": "[]", "reason": "", "context_token": token,
        "household_id": str(data["household_id"])}
    if request.method == "GET":
        form = ObservationForm(initial=initial, profiles=data["profiles"])
    else:
        form = ObservationForm(request.POST, profiles=data["profiles"])
        if form.is_valid():
            try:
                expected = records.read_context(form.cleaned_data["context_token"], data["household_id"],
                    "observation", observation_id, "edit")
                result = services.save_observation(request.user, data["household_id"], observation_id=observation_id,
                    profile_context_id=form.cleaned_data["profile_context_id"], legibility=form.cleaned_data["legibility"],
                    author_state=form.cleaned_data["author_state"], author_learner_id=form.cleaned_data["author_learner_id"],
                    confirmation_basis=form.cleaned_data["confirmation_basis"], actual_date_state=form.cleaned_data["actual_date_state"],
                    actual_date=form.cleaned_data["actual_date"], notes=form.cleaned_data["notes"], sources=form.cleaned_data["sources"],
                    clear_sources=form.cleaned_data["clear_sources"], expected_context=expected,
                    request_key=str(form.cleaned_data["request_key"]), reason=form.cleaned_data["reason"])
            except core.PersistenceError as exc:
                if exc.code in ("invalid_input", "invalid_region", "preview_changed"):
                    form.add_error(None, "新观察修订未保存，请检查填写内容和原图区域。")
                    return render(request, "learning/observation_form.html", {
                        **_observation_form_data(form, data["profiles"], data["page_cards"], is_edit=True),
                        "existing_sources": data["sources"],
                        "household_id": data["household_id"], "page_title": "补充来源观察"}, status=400)
                return _failure(request, exc)
            return redirect("learning:observation_detail", observation_id=result["observation_id"])
    return render(request, "learning/observation_form.html", {
        **_observation_form_data(form, data["profiles"], data["page_cards"], is_edit=True),
        "existing_sources": data["sources"],
        "observation_url": reverse("learning:observation_detail", kwargs={"observation_id": observation_id}),
        "household_id": data["household_id"], "page_title": "补充来源观察"},
        status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def attempt_new(request, learner_id):
    try:
        choices = services.learner_create_choices(request.user, learner_id)
        household_id = _household_id_for_profile(request.user, learner_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    token = records.sign_context(household_id, "learner", learner_id, "attempt-create", choices["context"])
    initial = {"request_key": uuid4(), "learner_id": learner_id, "attempt_kind": AttemptKind.FIRST.value,
        "source_kind": SourceKind.UNKNOWN.value, "independence": Independence.UNKNOWN.value,
        "prompt_status": PromptStatus.UNKNOWN.value, "actual_date_state": ActualDateState.UNKNOWN.value,
        "legibility": Legibility.UNKNOWN.value, "sources": "[]", "context_token": token}
    if request.method == "GET":
        form = AttemptForm(initial=initial, learner_id=learner_id, questions=choices["questions"],
            observations=choices["observation_choices"], prior_attempts=choices["prior_attempts"])
    else:
        form = AttemptForm(request.POST, learner_id=learner_id, questions=choices["questions"],
            observations=choices["observation_choices"], prior_attempts=choices["prior_attempts"])
        if form.is_valid():
            try:
                context = records.read_context(form.cleaned_data["context_token"], household_id,
                    "learner", learner_id, "attempt-create")
                result = services.create_attempt(request.user, learner_id,
                    question_id=form.cleaned_data["question_id"], attempt_kind=form.cleaned_data["attempt_kind"],
                    source_kind=form.cleaned_data["source_kind"], independence=form.cleaned_data["independence"],
                    prompt_status=form.cleaned_data["prompt_status"], prompts=form.cleaned_data["prompts"],
                    actual_date_state=form.cleaned_data["actual_date_state"], actual_date=form.cleaned_data["actual_date"],
                    legibility=form.cleaned_data["legibility"], answer_text=form.cleaned_data["answer_text"],
                    authorship_basis=form.cleaned_data["authorship_basis"], observation_values=form.cleaned_data["observation_values"],
                    previous_attempt_id=form.cleaned_data["previous_attempt_id"], context=context,
                    request_key=str(form.cleaned_data["request_key"]))
            except core.PersistenceError as exc:
                return _failure(request, exc)
            return redirect("learning:attempt_detail", attempt_id=result["attempt_id"])
    data = _attempt_form_data(form, choices, page_title="新增一次作答", learner_id=learner_id)
    data["profile_url"] = reverse("learning:profile_detail", kwargs={"learner_id": learner_id})
    return render(request, "learning/attempt_form.html", data,
                  status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def attempt_detail(request, attempt_id):
    try:
        data = services.attempt_detail(request.user, attempt_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    data["edit_url"] = reverse("learning:attempt_edit", kwargs={"attempt_id": attempt_id})
    data["correction_url"] = reverse("learning:attempt_correct", kwargs={"attempt_id": attempt_id})
    data["assessment_new_url"] = reverse("learning:assessment_new", kwargs={"attempt_id": attempt_id})
    revision = data["current_revision"]
    data["current_labels"] = {
        "attempt_kind": learning_label(ATTEMPT_KIND_LABELS, revision.attempt_kind),
        "source_kind": learning_label(SOURCE_KIND_LABELS, revision.source_kind),
        "independence": learning_label(INDEPENDENCE_LABELS, revision.independence),
        "prompt_status": learning_label(PROMPT_STATUS_LABELS, revision.prompt_status),
        "legibility": learning_label(LEGIBILITY_LABELS, revision.legibility),
    }
    for history in data["history"]:
        revision = history["revision"]
        history["labels"] = {
            "state": learning_label(ATTEMPT_STATE_LABELS, revision.state),
            "attempt_kind": learning_label(ATTEMPT_KIND_LABELS, revision.attempt_kind),
            "source_kind": learning_label(SOURCE_KIND_LABELS, revision.source_kind),
            "independence": learning_label(INDEPENDENCE_LABELS, revision.independence),
            "prompt_status": learning_label(PROMPT_STATUS_LABELS, revision.prompt_status),
        }
    for item in data["assessments"]:
        item["detail_url"] = reverse("learning:assessment_detail", kwargs={"assessment_id": item["assessment"].assessment_id})
        item["edit_url"] = reverse("learning:assessment_edit", kwargs={"assessment_id": item["assessment"].assessment_id})
        item["state_label"] = learning_label(REVIEW_STATE_LABELS, item["state"])
        item["dimension_labels"] = [{
            "dimension": learning_label(DIMENSION_LABELS, dimension.dimension),
            "judgment": learning_label(JUDGMENT_LABELS, dimension.judgment),
            "basis": learning_label(BASIS_LABELS, dimension.basis),
        } for dimension in item["revision"].dimensions]
    return render(request, "learning/attempt.html", data)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def attempt_edit(request, attempt_id):
    try:
        data = services.attempt_edit_context(request.user, attempt_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    attempt = data["attempt"]
    revision = attempt.revisions[-1]
    context = {"edit_context": data["edit_context"],
               "observation_heads": data["choices"]["context"]["observation_heads"]}
    token = records.sign_context(data["household_id"], "attempt", attempt_id, "edit", context)
    initial = _attempt_initial(revision, attempt, token)
    if request.method == "GET":
        questions = data["choices"]["questions"]
        if not any(item["question_id"] == attempt.question_id for item in questions):
            questions = [*questions, {"question_id": attempt.question_id, "label": f"已记录题目 {attempt.question_id}（历史修订）"}]
        prior_attempts = data["choices"]["prior_attempts"]
        if attempt.previous_attempt_id and not any(item[0] == attempt.previous_attempt_id for item in prior_attempts):
            prior_attempts = [*prior_attempts, (attempt.previous_attempt_id, f"前次作答 {attempt.previous_attempt_id}")]
        form = AttemptForm(initial=initial, learner_id=attempt.learner_id,
            questions=questions, observations=data["choices"]["observation_choices"],
            prior_attempts=prior_attempts, identity_locked=True)
    else:
        questions = data["choices"]["questions"]
        if not any(item["question_id"] == attempt.question_id for item in questions):
            questions = [*questions, {"question_id": attempt.question_id, "label": f"已记录题目 {attempt.question_id}（历史修订）"}]
        prior_attempts = data["choices"]["prior_attempts"]
        if attempt.previous_attempt_id and not any(item[0] == attempt.previous_attempt_id for item in prior_attempts):
            prior_attempts = [*prior_attempts, (attempt.previous_attempt_id, f"前次作答 {attempt.previous_attempt_id}")]
        form = AttemptForm(request.POST, initial=initial, learner_id=attempt.learner_id,
            questions=questions, observations=data["choices"]["observation_choices"],
            prior_attempts=prior_attempts, identity_locked=True)
        if form.is_valid():
            try:
                expected = records.read_context(form.cleaned_data["context_token"], data["household_id"], "attempt", attempt_id, "edit")
                services.append_attempt_revision(request.user, attempt_id,
                    attempt_kind=form.cleaned_data["attempt_kind"], source_kind=form.cleaned_data["source_kind"],
                    independence=form.cleaned_data["independence"], prompt_status=form.cleaned_data["prompt_status"],
                    prompts=form.cleaned_data["prompts"], actual_date_state=form.cleaned_data["actual_date_state"],
                    actual_date=form.cleaned_data["actual_date"], legibility=form.cleaned_data["legibility"],
                    answer_text=form.cleaned_data["answer_text"], authorship_basis=form.cleaned_data["authorship_basis"],
                    observation_values=form.cleaned_data["observation_values"], expected_context=expected,
                    request_key=str(form.cleaned_data["request_key"]))
            except core.PersistenceError as exc:
                return _failure(request, exc)
            return redirect("learning:attempt_detail", attempt_id=attempt_id)
    return render(request, "learning/attempt_form.html", _attempt_form_data(form, data["choices"],
        page_title="更正本次作答记录（追加修订）", learner_id=attempt.learner_id),
        status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def attempt_correct(request, attempt_id):
    try:
        data = services.attempt_edit_context(request.user, attempt_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    attempt = data["attempt"]
    if attempt.revisions[-1].state.value != "active":
        return _failure(request, core.PersistenceError("invalid_input", "已撤回的作答不能再次替代。"))
    bundle = data["bundle"]
    all_choices = services._attempt_choices(request.user, data["household_id"], bundle)
    all_choices["prior_attempts"] = [item for item in all_choices["prior_attempts"] if item[0] != attempt_id]
    replacement_context = data["edit_context"]
    token_context = {**all_choices["context"], "replacement_context": replacement_context}
    token = records.sign_context(data["household_id"], "attempt", attempt_id, "correct", token_context)
    initial = _attempt_initial(attempt.revisions[-1], attempt, token)
    initial["learner_id"] = attempt.learner_id
    initial["attempt_kind"] = AttemptKind.FIRST.value
    initial["previous_attempt_id"] = ""
    if request.method == "GET":
        form = CorrectionForm(initial=initial, learners=bundle.learners, questions=all_choices["questions"],
            observations=all_choices["observation_choices"], prior_attempts=all_choices["prior_attempts"])
    else:
        form = CorrectionForm(request.POST, learners=bundle.learners, questions=all_choices["questions"],
            observations=all_choices["observation_choices"], prior_attempts=all_choices["prior_attempts"])
        if form.is_valid():
            try:
                context = records.read_context(form.cleaned_data["context_token"], data["household_id"], "attempt", attempt_id, "correct")
                result = services.create_attempt(request.user, form.cleaned_data["learner_id"],
                    question_id=form.cleaned_data["question_id"], attempt_kind=form.cleaned_data["attempt_kind"],
                    source_kind=form.cleaned_data["source_kind"], independence=form.cleaned_data["independence"],
                    prompt_status=form.cleaned_data["prompt_status"], prompts=form.cleaned_data["prompts"],
                    actual_date_state=form.cleaned_data["actual_date_state"], actual_date=form.cleaned_data["actual_date"],
                    legibility=form.cleaned_data["legibility"], answer_text=form.cleaned_data["answer_text"],
                    authorship_basis=form.cleaned_data["authorship_basis"], observation_values=form.cleaned_data["observation_values"],
                    previous_attempt_id=form.cleaned_data["previous_attempt_id"], context=context,
                    request_key=str(form.cleaned_data["request_key"]), replacement_for=attempt_id)
            except core.PersistenceError as exc:
                return _failure(request, exc)
            return redirect("learning:attempt_detail", attempt_id=result["attempt_id"])
    return render(request, "learning/attempt_form.html", _attempt_form_data(form, all_choices,
        page_title="更正作者或题目身份（保留旧作答）", allow_identity=True, learners=bundle.learners),
        status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def assessment_new(request, attempt_id):
    try:
        data = services.assessment_context(request.user, attempt_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    token = records.sign_context(data["household_id"], "attempt", attempt_id, "assessment-create", data["context"])
    if request.method == "GET":
        form = AssessmentForm(initial={"request_key": uuid4(), "context_token": token},
            evidence_choices=data["evidence_choices"][0], errata_choices=data["errata_choices"])
    else:
        form = AssessmentForm(request.POST, evidence_choices=data["evidence_choices"][0], errata_choices=data["errata_choices"])
        if form.is_valid():
            try:
                context = records.read_context(form.cleaned_data["context_token"], data["household_id"],
                    "attempt", attempt_id, "assessment-create")
                values = form.dimension_values()
                values["context_errata"] = form.cleaned_data["context_errata"]
                result = services.save_assessment(request.user, attempt_id, values=values, context=context,
                    request_key=str(form.cleaned_data["request_key"]), reason=form.cleaned_data["reason"])
            except core.PersistenceError as exc:
                return _failure(request, exc)
            return redirect("learning:assessment_detail", assessment_id=result["assessment_id"])
    return render(request, "learning/assessment_form.html", {
        **_assessment_form(form, data["evidence_choices"][0], data["errata_choices"]),
        "attempt": data["attempt"], "profile_url": reverse("learning:profile_detail", kwargs={"learner_id": data["attempt"].learner_id}),
        "source_cards": services._source_cards(request.user, data["household_id"], data["bundle"],
            services._evidence_for_attempt(data["bundle"], data["attempt"].revisions[-1]))},
        status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def assessment_edit(request, assessment_id):
    try:
        data = services.assessment_edit_context(request.user, assessment_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    revision = data["assessment"].revisions[-1]
    initial_dimensions = _assessment_initial(revision, data["evidence_refs"])
    token = records.sign_context(data["household_id"], "assessment", assessment_id, "edit", data["context"])
    initial = {"request_key": uuid4(), "context_token": token, "reason": ""}
    initial.update({f"{key}_{field}": value for key, fields in initial_dimensions.items() for field, value in fields.items()})
    initial["context_errata"] = list(revision.context_erratum_revision_ids)
    if request.method == "GET":
        form = AssessmentForm(initial=initial, evidence_choices=data["evidence_choices"],
            errata_choices=data["errata_choices"])
    else:
        form = AssessmentForm(request.POST, evidence_choices=data["evidence_choices"], errata_choices=data["errata_choices"])
        if form.is_valid():
            try:
                context = records.read_context(form.cleaned_data["context_token"], data["household_id"],
                    "assessment", assessment_id, "edit")
                values = form.dimension_values()
                values["context_errata"] = form.cleaned_data["context_errata"]
                services.save_assessment(request.user, data["assessment"].attempt_id, values=values, context=context,
                    request_key=str(form.cleaned_data["request_key"]), assessment_id=assessment_id,
                    reason=form.cleaned_data["reason"])
            except core.PersistenceError as exc:
                return _failure(request, exc)
            return redirect("learning:assessment_detail", assessment_id=assessment_id)
    return render(request, "learning/assessment_form.html", {
        **_assessment_form(form, data["evidence_choices"], data["errata_choices"], is_edit=True),
        "attempt": data["attempt"], "profile_url": reverse("learning:profile_detail", kwargs={"learner_id": data["attempt"].learner_id}),
        "source_cards": services._source_cards(request.user, data["household_id"], data["bundle"], data["evidence_refs"])},
        status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def assessment_detail(request, assessment_id):
    try:
        data = services.assessment_detail(request.user, assessment_id)
        review_context = services.review_form_context(request.user, assessment_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    current_revision = data["current_revision"]
    review_state = review_context["review_context"]
    review_form = ReviewForm(initial={"request_key": uuid4(), "revision_id": current_revision.header.revision_id,
        "context_token": records.sign_context(data["household_id"], "assessment", assessment_id,
            "review", review_state)})
    data["review_form"] = review_form
    data["current_state"] = review_state.get("state", "draft")
    data["can_review_current"] = current_revision.header.revision_id == review_state.get("expected_head")
    data["current_state_label"] = learning_label(REVIEW_STATE_LABELS, data["current_state"])
    for row in data["dimensions"]:
        dimension = row["dimension"]
        row["dimension_label"] = learning_label(DIMENSION_LABELS, dimension.dimension)
        row["judgment_label"] = learning_label(JUDGMENT_LABELS, dimension.judgment)
        row["basis_label"] = learning_label(BASIS_LABELS, dimension.basis)
    for history in data["history"]:
        history["state_label"] = learning_label(REVIEW_STATE_LABELS, history["state"])
        history["dimension_labels"] = [{
            "dimension": learning_label(DIMENSION_LABELS, dimension.dimension),
            "judgment": learning_label(JUDGMENT_LABELS, dimension.judgment),
            "basis": learning_label(BASIS_LABELS, dimension.basis),
        } for dimension in history["revision"].dimensions]
    data["edit_url"] = reverse("learning:assessment_edit", kwargs={"assessment_id": assessment_id})
    data["attempt_url"] = reverse("learning:attempt_detail", kwargs={"attempt_id": data["attempt"].attempt_id})
    data["profile_url"] = reverse("learning:profile_detail", kwargs={"learner_id": data["attempt"].learner_id})
    return render(request, "learning/assessment.html", data)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
def assessment_review(request, assessment_id):
    form = ReviewForm(request.POST)
    if not form.is_valid():
        return _failure(request, core.PersistenceError("invalid_input", "审核内容无效。"))
    household_id = _household_id_for_kind(request.user, "assessment", assessment_id)
    try:
        context = records.read_context(form.cleaned_data["context_token"], household_id,
            "assessment", assessment_id, "review")
        services.review_assessment(request.user, assessment_id, form.cleaned_data["revision_id"],
            action=form.cleaned_data["action"], reason=form.cleaned_data["reason"], context=context,
            request_key=str(form.cleaned_data["request_key"]))
    except core.PersistenceError as exc:
        return _failure(request, exc)
    return redirect("learning:assessment_detail", assessment_id=assessment_id)
