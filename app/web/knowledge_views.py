"""Private HTML views for B2a knowledge and exact question navigation."""
from functools import wraps
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app.persistence import services as core
from app.persistence.models import EntityRecord, ImageRecord, RevisionDependency, RevisionRecord
from . import knowledge_services as services
from . import services as web_services
from . import records
from .knowledge_forms import IndexForm, KnowledgeForm, LinkForm, MethodForm, NodeReviewForm, QuestionTypeForm
from .knowledge_forms import NODE_KINDS
from .records import read_context, sign_context


LOGIN_URL = "/accounts/login/"
FORM_TYPES = {"knowledge": KnowledgeForm, "method": MethodForm, "question_type": QuestionTypeForm}


def _not_found(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ObjectDoesNotExist as exc:
            raise Http404 from exc
        except ImproperlyConfigured:
            return render(request, "knowledge/message.html", {
                "title": "服务尚未就绪", "message": "私有资料存储尚未配置，请稍后重试。",
            }, status=503)
    return wrapped


def _failure(request, error):
    code = getattr(error, "code", "")
    if code in {"not_found", "permission_denied", "unauthorized", "object_not_found"}:
        raise Http404
    conflicts = {
        "head_conflict": "内容、来源或方法上级版本已变化；本次修订未保存，请重新打开当前节点。",
        "stale_context": "操作凭据无效或已超过一小时；请刷新页面后重新操作。",
        "stale_dependencies": "所选精确版本的依赖已变化；本次操作未发布，请重新选择当前版本。",
        "dependency_conflict": "关联版本或依赖清单已变化；请重新打开页面核对后再操作。",
        "unaccepted_dependency": "题目与节点的所选精确版本都须实际审核发布，才能审核此关联。",
        "multiple_primary_methods": "此题目版本已有一个已发布主方法；先撤回旧关联，或将新关联设为辅助方法。",
        "request_conflict": "请求编号已用于不同内容；请刷新后重新提交。",
        "preview_changed": "原图预览已变化；请重新框选来源区域。",
    }
    if code in conflicts or "conflict" in code or "stale" in code or "changed" in code:
        status = 409
        message = conflicts.get(code, "内容或依赖已变化；本次操作未完成，请重新打开页面核对。")
    elif code == "missing_asset":
        status, message = 410, "来源文件当前不可用，关联记录仍保留。"
    elif code in {"invalid_input", "invalid_region", "missing_region", "missing_link_reference"}:
        status, message = 400, str(error)
    else:
        status, message = 400, str(error) or "操作未完成，请检查输入后重试。"
    return render(request, "knowledge/message.html", {"title": "操作未完成", "message": message}, status=status)


def _decorate_sources(request, cards):
    for card in cards:
        ref = card['ref']
        purpose = ref.get('purpose', '')
        granularity = ref.get('granularity', '')
        card['purpose_label'] = {'question':'印刷题干', 'handwriting':'手写作答',
            'formula':'公式', 'diagram':'图示', 'definition':'定义', 'other':'其他来源／生成依据'}.get(purpose, purpose)
        card['granularity_label'] = {'whole_image':'整图', 'region':'区域'}.get(granularity, granularity)
        image = card.get("image")
        if not image:
            continue
        card["original_url"] = reverse("knowledge:source_image", kwargs={"image_id": image.pk})
        if card.get("page") and card.get("preview"):
            card["preview_url"] = reverse("web:page_preview", kwargs={"page_id": card["page"].pk, "rotation": 0})
            card["page_url"] = reverse("web:page_detail", kwargs={"page_id": card["page"].pk})
        else:
            card["preview_url"] = card["original_url"]
            card["page_url"] = card["original_url"]
    return cards


def _page_cards(actor, household_id):
    # The caller has already validated membership. Each image remains on the B1
    # private route; this form only reuses its signed preview and region checks.
    pages = web_services.MaterialPage.objects.filter(material__household_id=household_id).select_related(
        "material", "image").prefetch_related("image__web_previews").order_by("material__created_at", "position", "id")
    cards = []
    for page in pages:
        previews = list(page.image.web_previews.order_by("rotation"))
        if not previews:
            continue
        preview = next((row for row in previews if row.rotation == 0), previews[0])
        cards.append({
            "page_id": str(page.pk), "position": page.position,
            "label": f"{page.material.title} · 第 {page.position} 页",
            "original_name": page.original_name, "preview": preview,
            "preview_url": reverse("web:page_preview", kwargs={"page_id": page.pk, "rotation": preview.rotation}),
            "page_url": reverse("web:page_detail", kwargs={"page_id": page.pk}),
            "preview_options": [{"rotation": row.rotation, "width": row.width, "height": row.height,
                "sha256": row.sha256,
                "url": reverse("web:page_preview", kwargs={"page_id": page.pk, "rotation": row.rotation})}
                for row in previews],
        })
    return cards


def _initial_node(kind, data):
    current = data["current"]
    initial = {"request_key": uuid4(), "household_id": data["household"].pk,
        "context_token": sign_context(data["household"].pk, kind, data["entity"].stable_id,
            "edit", data["edit_context"]),
        "reason": "", "sources": "[]", "replace_sources": False}
    if kind == "knowledge":
        initial.update({"definition": current["definition"],
            "display_markup": current.get("display_markup") or "",
            "conditions": "\n".join(current["conditions"]),
            "common_errors": "\n".join(current["common_errors"])})
    elif kind == "method":
        initial.update({"name": current["name"], "conditions": "\n".join(current["conditions"]),
            "steps": "\n".join(current["steps"]), "notes": "\n".join(current["notes"]),
            "parent_revision_id": current["parent_revision_id"] or ""})
    else:
        initial.update({"name": current["name"],
            "structural_features": "\n".join(current["structural_features"]),
            "conditions": "\n".join(current["conditions"])})
    return initial


def _review_actions(entity, row):
    actions = []
    if row.pk == entity.head_revision_id and row.review_projection.state in {"draft", "stale"}:
        actions.extend(("reject",) if row.web_review_context.get("state") == "stale" else ("accept", "reject"))
    if entity.published_revision_id == row.pk:
        actions.append("withdraw")
    return actions


def _attach_review_forms(entity, history, kind):
    for row in history:
        row.web_review_state_label = services._state_label(row.review_projection.state)
        actions = _review_actions(entity, row)
        row.web_review_form = NodeReviewForm(initial={
            "request_key": uuid4(), "revision_id": row.pk,
            "context_token": sign_context(entity.household_id, kind, entity.stable_id,
                "review", row.web_review_context),
        }, actions=actions) if actions else None


def _prepare_link_forms(actor, household_id, items):
    for item in items:
        row = item["link"]
        row.web_review_context = core.review_context(actor, household_id, row.pk)
        _attach_review_forms(row.entity, [row], row.entity.kind)
        item["review_form"] = row.web_review_form


def _association_status(item):
    if item["current"]:
        return "当前已发布"
    if item["outdated"]:
        return "精确版本已过期"
    if item["state"] == "rejected":
        return "已退回"
    if item["state"] == "withdrawn":
        return "已撤回"
    if item["pending"]:
        return "待审核；题目与节点须先发布"
    return f"历史关联：{services._state_label(item['state'])}"


def _link_form(data, *, forced_kind=None, question_id=None):
    household_id = data["household"].pk
    form = LinkForm(node_choices=data["node_choices"], question_choices=data["question_choices"],
        forced_kind=forced_kind, initial={"request_key": uuid4(), "household_id": household_id,
            "kind": forced_kind or "knowledge",
            "role": {"knowledge": "applies", "method": "primary", "question_type": "belongs"}.get(
                forced_kind, "applies")})
    if question_id:
        own = [(row.pk, f"{row.payload.get('working_text') or row.payload.get('printed_text') or '旧索引题目'} · r{row.revision_no}")
               for row in data["history"]]
        form.fields["question_revision_id"].choices = own
        form.initial["question_revision_id"] = data["entity"].head_revision_id
    elif forced_kind:
        current_id = data["entity"].head_revision_id
        form.initial["node_revision_id"] = current_id
    return form


def _node_view_context(request, data, link_form=None):
    entity = data["entity"]
    kind = entity.kind
    _attach_review_forms(entity, data["history"], kind)
    data["current_sources"] = _decorate_sources(request, data["current_sources"])
    for row in data["history"]:
        row.web_sources = _decorate_sources(request, row.web_sources)
    for item in data["links"]:
        item["question_url"] = reverse("knowledge:question_detail", kwargs={"entity_id": item["question"]["entity"].pk})
        item["status_label"] = _association_status(item)
    _prepare_link_forms(request.user, data["household"].pk, data["links"])
    return {**data, "kind_label": dict(NODE_KINDS)[kind],
        "current_state_label": services._state_label(entity.head_revision.review_projection.state),
        "edit_url": reverse("knowledge:node_edit", kwargs={"entity_id": entity.pk}),
        "link_url": reverse("knowledge:node_link", kwargs={"entity_id": entity.pk}),
        "link_form": link_form or _link_form(data, forced_kind=kind),
        "title": services._node_label(entity.head_revision, kind)}


def _question_view_context(request, data, link_form=None):
    entity = data["entity"]
    _attach_review_forms(entity, data["history"], "question")
    for row in data["history"]:
        row.web_sources = _decorate_sources(request, row.web_sources)
        for item in row.web_links:
            item["node_url"] = reverse("knowledge:node_detail", kwargs={"entity_id": item["node"].pk})
            item["status_label"] = _association_status(item)
            item["review_url"] = reverse("knowledge:review", kwargs={"entity_id": item["link"].entity_id})
    _prepare_link_forms(request.user, data["household"].pk,
        [item for row in data["history"] for item in row.web_links])
    current = data["current"]
    from app.study.models import VariantProvenance
    variant = VariantProvenance.objects.filter(question=entity, household=data['household']).select_related(
        'parent_question_revision__entity', 'target_method_revision__entity').first()
    from app.web import learning_services
    learner_id = request.GET.get('learner', '')
    practice_learner = None
    if learner_id and data['practice_ready'] and EntityRecord.objects.filter(household=data['household'], kind='learner', stable_id=learner_id).exists():
        try:
            profile = learning_services.learner_create_choices(request.user, learner_id)
            if any(item['question_id'] == entity.stable_id for item in profile['questions']):
                practice_learner = learner_id
        except core.PersistenceError:
            pass
    return {**data, "practice_learner": practice_learner,
        "link_form": link_form or _link_form(data, question_id=entity.pk),
        "current_state_label": services._state_label(entity.head_revision.review_projection.state),
        "variant": variant,
        "edit_url": reverse('web:question_edit', args=[entity.stable_id]) if data['can_write'] and data['material'] else "", "title": data["number"], "source_cards": _decorate_sources(request, data["current_sources"]),
        "current_missing": bool(current.get("missing_fields")) or not current.get("evidence_refs")}


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def index(request):
    households = web_services.list_households(request.user)
    household_id = (request.POST if request.method == "POST" else request.GET).get("household_id", "")
    if not household_id and len(households) == 1:
        return redirect(f"{reverse('knowledge:index')}?{urlencode({'household_id': households[0].household_id})}")
    empty = {"household_id": household_id}
    home = None
    if household_id:
        try:
            home = services.index_data(request.user, household_id)
        except core.PersistenceError as exc:
            return _failure(request, exc)
    nodes = home["nodes"] if home else {}
    form_data = request.POST if request.method == "POST" else (request.GET or None)
    form = IndexForm(form_data, households=households, household_id=household_id, nodes=nodes,
        materials=home["materials"] if home else (),
        initial=empty if request.method == "GET" else None)
    if request.method == "POST":
        if form.is_valid():
            query = urlencode({key: value for key, value in form.cleaned_data.items() if value})
            return redirect(f"{reverse('knowledge:index')}?{query}")
        return render(request, "knowledge/index.html", {"form": form, "home": home,
            "has_households": bool(households), "kind_links": NODE_KINDS}, status=400)
    if home and form.is_valid():
        try:
            home = services.index_data(request.user, household_id, form.cleaned_data)
        except core.PersistenceError as exc:
            return _failure(request, exc)
    return render(request, "knowledge/index.html", {"form": form, "home": home,
        "has_households": bool(households), "kind_links": NODE_KINDS})


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def node_new(request, kind):
    if kind not in FORM_TYPES:
        raise Http404
    households = web_services.list_households(request.user)
    household_id = (request.POST if request.method == "POST" else request.GET).get("household_id", "")
    if not household_id and len(households) == 1:
        household_id = str(households[0].household_id)
    if not household_id:
        return render(request, "knowledge/choose_household.html", {"households": households,
            "kind": kind, "kind_label": dict(NODE_KINDS)[kind]})
    try:
        records_household = services.index_data(request.user, household_id)
        cards = _page_cards(request.user, household_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    if kind == "method":
        parent_choices = services.method_revision_choices(request.user, household_id)
    else:
        parent_choices = ()
    if request.method == "GET":
        form = FORM_TYPES[kind](initial={"request_key": uuid4(), "household_id": household_id,
            "sources": "[]", "reason": ""}, **({"parent_choices": parent_choices} if kind == "method" else {}))
    else:
        form = FORM_TYPES[kind](request.POST, **({"parent_choices": parent_choices} if kind == "method" else {}))
        if form.is_valid():
            try:
                if str(form.cleaned_data["household_id"]) != str(household_id):
                    raise core.PersistenceError("stale_context", "家庭选择与当前页面不符，请重新打开。")
                result = services.save_node(request.user, household_id, kind, data=form.cleaned_data,
                    request_key=str(form.cleaned_data["request_key"]), reason=form.cleaned_data["reason"])
                entity = EntityRecord.objects.get(household_id=household_id, kind=kind, stable_id=result["stable_id"])
                return redirect("knowledge:node_detail", entity_id=entity.pk)
            except core.PersistenceError as exc:
                return _failure(request, exc)
    return render(request, "knowledge/node_form.html", {
        "form": form, "kind": kind, "kind_label": dict(NODE_KINDS)[kind], "is_edit": False,
        "source_pages": cards, "source_cards": [], "source_warning": True,
        "household": records_household["household"],
    }, status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
def node_detail(request, entity_id):
    try:
        data = services.node_detail(request.user, entity_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    return render(request, "knowledge/node.html", _node_view_context(request, data))


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
def node_edit(request, entity_id):
    try:
        data = services.node_detail(request.user, entity_id)
        kind = data["entity"].kind
        cards = _page_cards(request.user, data["household"].pk)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    if request.method == "GET":
        form = FORM_TYPES[kind](initial=_initial_node(kind, data), **({"parent_choices": data["method_choices"]} if kind == "method" else {}))
    else:
        form = FORM_TYPES[kind](request.POST, **({"parent_choices": data["method_choices"]} if kind == "method" else {}))
        if form.is_valid():
            try:
                if str(form.cleaned_data["household_id"]) != str(data["household"].pk):
                    raise core.PersistenceError("stale_context", "家庭选择与当前节点不符，请重新打开。")
                context = read_context(form.cleaned_data["context_token"], data["household"].pk,
                    kind, data["entity"].stable_id, "edit")
                result = services.save_node(request.user, data["household"].pk, kind,
                    data=form.cleaned_data, request_key=str(form.cleaned_data["request_key"]),
                    reason=form.cleaned_data["reason"], stable_id=data["entity"].stable_id,
                    expected_context=context)
                return redirect("knowledge:node_detail", entity_id=data["entity"].pk)
            except core.PersistenceError as exc:
                return _failure(request, exc)
    return render(request, "knowledge/node_form.html", {
        "form": form, "kind": kind, "kind_label": dict(NODE_KINDS)[kind], "is_edit": True,
        "node": data["entity"], "source_pages": cards,
        "source_cards": _decorate_sources(request, data["current_sources"]),
        "source_warning": not bool(data["current_sources"]),
        "household": data["household"],
        "cancel_url": reverse("knowledge:node_detail", kwargs={"entity_id": data["entity"].pk}),
    }, status=400 if request.method == "POST" and not form.is_valid() else 200)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
def node_link(request, entity_id):
    try:
        data = services.node_detail(request.user, entity_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    kind = data["entity"].kind
    form = LinkForm(request.POST, node_choices=data["node_choices"], question_choices=data["question_choices"],
        forced_kind=kind)
    if not form.is_valid():
        return render(request, "knowledge/node.html", _node_view_context(request, data, form), status=400)
    if str(form.cleaned_data["household_id"]) != str(data["household"].pk):
        return _failure(request, core.PersistenceError("stale_context", "家庭选择与当前节点不符，请重新打开。"))
    try:
        services.create_link(request.user, data["household"].pk, kind=kind,
            node_revision_id=form.cleaned_data["node_revision_id"],
            question_revision_id=form.cleaned_data["question_revision_id"],
            role=form.cleaned_data["role"], request_key=str(form.cleaned_data["request_key"]),
            reason=form.cleaned_data["reason"])
    except core.PersistenceError as exc:
        return _failure(request, exc)
    return redirect("knowledge:node_detail", entity_id=data["entity"].pk)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
def question_detail(request, entity_id):
    try:
        data = services.question_detail(request.user, entity_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    return render(request, "knowledge/question.html", _question_view_context(request, data))


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
def question_link(request, entity_id):
    try:
        data = services.question_detail(request.user, entity_id)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    form = LinkForm(request.POST, node_choices=data["node_choices"], question_choices=data["question_choices"])
    if not form.is_valid():
        return render(request, "knowledge/question.html", _question_view_context(request, data, form), status=400)
    if str(form.cleaned_data["household_id"]) != str(data["household"].pk):
        return _failure(request, core.PersistenceError("stale_context", "家庭选择与当前题目不符，请重新打开。"))
    try:
        services.create_link(request.user, data["household"].pk,
            kind=form.cleaned_data["kind"], node_revision_id=form.cleaned_data["node_revision_id"],
            question_revision_id=form.cleaned_data["question_revision_id"], role=form.cleaned_data["role"],
            request_key=str(form.cleaned_data["request_key"]), reason=form.cleaned_data["reason"])
    except core.PersistenceError as exc:
        return _failure(request, exc)
    return redirect("knowledge:question_detail", entity_id=data["entity"].pk)


@_not_found
@login_required(login_url=LOGIN_URL)
@require_POST
def review(request, entity_id):
    form = NodeReviewForm(request.POST)
    if not form.is_valid():
        return _failure(request, core.PersistenceError("invalid_input", "审核表单无效，请刷新后重试。"))
    try:
        entity = EntityRecord.objects.select_related("household").get(pk=entity_id)
        kind, stable_id = entity.kind, entity.stable_id
        if kind not in {"question", "knowledge", "method", "question_type",
                        "knowledge_question", "method_question", "question_type_link"}:
            raise Http404
        context = read_context(form.cleaned_data["context_token"], entity.household_id,
            kind, stable_id, "review")
        payload_context = context
        services.review_revision(request.user, entity_id, form.cleaned_data["revision_id"],
            action=form.cleaned_data["action"], reason=form.cleaned_data["reason"],
            context=payload_context, request_key=str(form.cleaned_data["request_key"]))
    except core.PersistenceError as exc:
        return _failure(request, exc)
    if kind == "question":
        return redirect("knowledge:question_detail", entity_id=entity_id)
    if kind in FORM_TYPES:
        return redirect("knowledge:node_detail", entity_id=entity_id)
    dependency = RevisionDependency.objects.filter(source__entity_id=entity_id,
        role="link_question").select_related("target__entity").first()
    if dependency:
        return redirect("knowledge:question_detail", entity_id=dependency.target.entity_id)
    raise Http404


@_not_found
@login_required(login_url=LOGIN_URL)
@require_GET
@never_cache
def source_image(request, image_id):
    try:
        image = services.source_image(request.user, image_id)
        path = web_services.asset_path(image.payload["storage_key"], image.sha256)
    except core.PersistenceError as exc:
        return _failure(request, exc)
    content_type = image.payload.get("media_type", "")
    if content_type not in {"image/jpeg", "image/png"}:
        return _failure(request, core.PersistenceError("invalid_input", "只允许显示 JPEG 或 PNG 原图。"))
    response = FileResponse(path.open("rb"), content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    patch_cache_control(response, private=True, no_store=True)
    return response
