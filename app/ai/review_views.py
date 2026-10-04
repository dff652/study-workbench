"""Private, explicit review and confirmation pages for model proposals."""
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from app.persistence import services as core
from app.persistence.models import EvidenceRecord, RevisionRecord
from app.web import records
from app.web.models import MaterialPage, QuestionSource
from . import review_services
from . import views as ai_views
from .review_forms import ConfirmReviewForm

_DIMENSIONS = {
    "answer": "答案",
    "method": "方法",
    "process": "过程",
    "calculation": "计算",
    "notation": "表达规范",
}
_JUDGMENTS = {"correct": "正确", "incorrect": "错误", "partial": "部分正确", "unknown": "未知"}
_BASES = {"observed": "直接观察", "inferred": "推断", "undetermined": "未确定"}


def _form_initial(data):
    run = data["run"]
    return {"context": records.sign_context(data["household_id"], "model_run", str(run.pk),
        "confirm", data["context"]), "request_key": uuid4().hex}


def _decorate(request, data, form=None, *, status=200, action_error=""):
    run = data["run"]
    data["task_label"] = ai_views.TASK_LABELS.get(run.task_kind, "模型任务")
    data["run_status"] = ai_views.STATUS_LABELS.get(run.status, "未知状态")
    data["form"] = (form or ConfirmReviewForm(initial=_form_initial(data))) if data["can_confirm"] else None
    data["output_links"] = ai_views._output_links(data["household_id"], run.output_revision_ids)
    data["action_error"] = action_error

    question_ids = list(dict.fromkeys(map(str, run.question_revision_ids)))
    questions = list(RevisionRecord.objects.filter(pk__in=question_ids,
        entity__household_id=data["household_id"], entity__kind="question")
        .select_related("entity").order_by("revision_no"))
    data["source_questions"] = [{
        "revision_no": row.revision_no,
        "text": row.payload.get("printed_text") or row.payload.get("working_text") or "（原题干为空）",
        "printed_text_display": row.payload.get("printed_text") or "（原题印刷内容为空）",
        "url": reverse("knowledge:question_detail", kwargs={"entity_id": row.entity_id}) + f"#revision-{row.pk}",
    } for row in questions]
    questions_by_id = {str(row.pk): row for row in questions}
    source_question = questions_by_id.get(question_ids[0]) if question_ids else None
    data["question_source_has_printed_text"] = bool(
        source_question and source_question.payload.get("printed_text"))
    data["manual_revision_link"] = None
    if questions and data["writable"] and run.task_kind == "question":
        question = questions[0]
        if question.entity.published_revision_id == question.pk:
            data["manual_revision_link"] = {
                "label": "手动修订印刷文字建议", "url": reverse("printing:erratum", kwargs={"pk": question.pk})}
        else:
            data["manual_revision_link"] = {
                "label": "手动补充题目草稿", "url": reverse("web:question_edit",
                    kwargs={"question_id": question.entity.stable_id})}

    source_page_ids = set()
    question_source_region_ids = set()
    for source in QuestionSource.objects.filter(revision_id__in=[row.pk for row in questions]).values_list(
            "sources", flat=True):
        for item in source:
            if item.get("page_id"):
                source_page_ids.add(str(item["page_id"]))
            if item.get("region_revision_id"):
                question_source_region_ids.add(str(item["region_revision_id"]))
    fallback_page_ids = set()
    unmapped_region_ids = set(map(str, run.selected_region_revision_ids)) - question_source_region_ids
    if unmapped_region_ids:
        image_ids = (EvidenceRecord.objects.filter(region_id__in=unmapped_region_ids,
            source__entity__household_id=data["household_id"], image__household_id=data["household_id"])
            .values_list("image_id", flat=True).distinct())
        fallback_page_ids.update(str(value) for value in MaterialPage.objects.filter(
            image_id__in=image_ids, material__household_id=data["household_id"])
            .values_list("pk", flat=True))
    fallback_page_ids -= source_page_ids
    pages = MaterialPage.objects.filter(pk__in=source_page_ids | fallback_page_ids,
        material__household_id=data["household_id"]).order_by("position", "id")
    data["source_pages"] = [{"page_id": str(page.pk),
        "label": (f"原图来源 · 第 {page.position} 页" if str(page.pk) in source_page_ids
            else f"同一原图的资料页入口 · 第 {page.position} 页"),
        "url": reverse("web:page_detail", kwargs={"page_id": page.pk})} for page in pages]

    data["attempt_link"] = None
    if run.attempt_revision_id:
        attempt = RevisionRecord.objects.filter(pk=run.attempt_revision_id,
            entity__household_id=data["household_id"], entity__kind="attempt").select_related("entity").first()
        if attempt:
            data["attempt_link"] = {"label": f"查看精确作答修订 r{attempt.revision_no} · {attempt.pk}",
                "answer_text": attempt.payload.get("answer_text"),
                "url": reverse("learning:attempt_detail", kwargs={"attempt_id": attempt.entity.stable_id})}

    data["target_method"] = None
    method_id = (data.get("proposal") or {}).get("target_method_revision_id")
    if run.task_kind == "variant" and method_id:
        method = RevisionRecord.objects.filter(pk=method_id, entity__household_id=data["household_id"],
            entity__kind="method").select_related("entity").first()
        if method:
            data["target_method"] = {"revision_no": method.revision_no,
                "url": reverse("knowledge:node_detail", kwargs={"entity_id": method.entity_id})
                    + f"#revision-{method.pk}"}

    proposal = data.get("proposal") or {}
    proposed_text = proposal.get("printed_text")
    original_printed_text = (source_question.payload.get("printed_text") or "") if source_question else ""
    data["question_proposal_is_printed_difference"] = bool(
        original_printed_text and proposed_text and proposed_text != original_printed_text)
    dimensions = {item["dimension"]: item for item in proposal.get("dimensions", [])}
    data["assessment_dimensions"] = [{
        **dimensions[dimension],
        "dimension_label": _DIMENSIONS[dimension],
        "judgment_label": _JUDGMENTS[dimensions[dimension]["judgment"]],
        "basis_label": _BASES[dimensions[dimension]["basis"]],
    } for dimension in _DIMENSIONS if dimension in dimensions]

    data["next_run_id"] = None
    if data["confirmed"] and data["writable"]:
        data["next_run_id"] = review_services.next_pending(request.user,
            data["household_id"], exclude_run_id=run.pk)
    return render(request, "ai/review.html", data, status=status)


@ai_views._not_found
@login_required(login_url=ai_views.LOGIN_URL)
@require_GET
@never_cache
def review(request, run_id):
    try:
        data = review_services.review_context(request.user, run_id)
    except core.PersistenceError as exc:
        return ai_views._failure(request, exc)
    return _decorate(request, data)


@ai_views._not_found
@login_required(login_url=ai_views.LOGIN_URL)
@require_POST
@csrf_protect
@never_cache
def confirm(request, run_id):
    try:
        data = review_services.review_context(request.user, run_id)
    except core.PersistenceError as exc:
        return ai_views._failure(request, exc)
    form = ConfirmReviewForm(request.POST)
    if not form.is_valid():
        return _decorate(request, data, form, status=400)
    try:
        expected = records.read_context(form.cleaned_data["context"], data["household_id"],
            "model_run", str(data["run"].pk), "confirm")
        review_services.confirm_run(request.user, run_id, expected=expected,
            checked=form.cleaned_data["checked"], reason=form.cleaned_data["reason"],
            request_key=form.cleaned_data["request_key"])
    except core.PersistenceError as exc:
        if exc.code in {"permission_denied", "not_found", "unauthorized", "object_not_found"}:
            return ai_views._failure(request, exc)
        if any(part in exc.code for part in ("conflict", "stale", "changed")):
            try:
                data = review_services.review_context(request.user, run_id)
            except core.PersistenceError as refresh_error:
                return ai_views._failure(request, refresh_error)
            form = ConfirmReviewForm(initial=_form_initial(data))
            return _decorate(request, data, form, status=409, action_error=str(exc))
        form.add_error(None, str(exc))
        return _decorate(request, data, form, status=400)
    return redirect("ai:review", run_id=run_id)
