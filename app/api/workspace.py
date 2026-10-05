"""Same-origin screen adapter for the existing, permission-checked business forms.

The browser receives only a sanitized main-content fragment. No template scripts,
styles, external URLs or arbitrary view dispatch are permitted. Business commands
continue to use their original validation, version binding and transactions.
"""
from copy import copy
from html import escape
import re
from urllib.parse import unquote, urljoin, urlsplit

from django.http import Http404, QueryDict
from django.urls import Resolver404, resolve
from lxml import etree, html

from .views import api, error, response


PAGES = {
    "web": {"index", "help", "members", "material_new", "material_detail", "reorder_pages",
            "page_detail", "page_reading", "derivative_create", "question_new",
            "question_detail", "question_edit", "question_review"},
    "knowledge": {"index", "node_new", "node_detail", "node_edit", "node_link", "review",
                  "question_detail", "question_link"},
    "learning": {"index", "profile_new", "profile_detail", "observation_new", "observation_detail",
                 "observation_edit", "attempt_new", "attempt_detail", "attempt_edit", "attempt_correct",
                 "assessment_new", "assessment_detail", "assessment_edit", "assessment_review"},
    "catalogue": {"index", "merge", "question_detail", "question_split"},
    "study": {"index", "schedule_new", "schedule_detail", "report"},
    "ai": {"index", "config", "run_new", "run_create", "run_detail", "review", "confirm",
           "run_execute", "run_cancel", "run_apply"},
    "operations": {"index", "retention_policy", "work_timing_new"},
    "printing": {"index", "arithmetic", "snapshot", "diagrams", "evidence_report",
                 "answer", "erratum", "packet_prepare", "packet"},
}
WIDGETS = {"web/regions.js": "regions", "web/order.js": "order", "web/derivatives.js": "derivatives"}
TAGS = set("a abbr article aside b blockquote br button canvas caption code col colgroup dd details div dl dt em fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hr i img input label legend li main nav ol optgroup option p pre section select small span strong sub summary sup table tbody td textarea tfoot th thead time tr ul".split())
ATTRS = set("id class name type value checked selected disabled readonly required multiple hidden open method enctype placeholder rows cols size min max step minlength maxlength pattern accept autocomplete for role title alt width height loading tabindex colspan rowspan scope aria-label aria-labelledby aria-describedby aria-live aria-hidden aria-expanded aria-controls aria-selected".split())
CSS_VALUE = re.compile(r"(?:[0-9.]+(?:%|px|rem|em)?|auto|none|block|inline-block|relative|absolute|center|left|right)\Z")
CSS_KEYS = {"top", "left", "right", "bottom", "width", "height", "max-width", "max-height", "display", "position", "text-align"}


def local_url(value, base="/"):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value) or "\\" in value:
        raise ValueError("Invalid local address")
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or value.startswith("//"):
        raise ValueError("Only same-origin paths are supported")
    result = urljoin(base, value)
    if not result.startswith("/") or result.startswith("//"):
        raise ValueError("Invalid local address")
    return result


def allowed_target(value):
    url = local_url(value)
    parts = urlsplit(url)
    path = unquote(parts.path, errors="strict")
    if path.startswith("//") or "\\" in path or any(ord(char) < 32 for char in path):
        raise Http404
    try:
        match = resolve(path)
    except Resolver404 as exc:
        raise Http404 from exc
    if match.url_name != "legacy-materials" and match.url_name not in PAGES.get(match.namespace, set()):
        raise Http404
    return url, parts, match


def fragment(raw, url):
    document = html.fromstring(raw)
    mains = document.xpath("//main")
    if not mains:
        raise ValueError("No business content")
    main = mains[0]
    widgets = []
    for source in document.xpath("//script[@src]/@src"):
        for suffix, widget in WIDGETS.items():
            stem = re.escape(suffix.removesuffix(".js"))
            if re.search(r"/" + stem + r"(?:\.[a-f0-9]{8,64})?\.js(?:\?.*)?$", source) and widget not in widgets:
                widgets.append(widget)
    for element in list(main.iterdescendants()):
        if not any(parent is main for parent in element.iterancestors()):
            continue
        if not isinstance(element.tag, str):
            element.getparent().remove(element)
            continue
        if element.tag in {"script", "style", "iframe", "object", "embed", "link", "meta", "base", "svg", "math"}:
            element.drop_tree()
            continue
        if element.tag == "noscript":
            element.tag = "div"
        elif element.tag not in TAGS:
            element.drop_tag()
            continue
        for key, value in list(element.attrib.items()):
            if key in {"href", "src", "action", "formaction"}:
                try:
                    element.set(key, local_url(value, url))
                except ValueError:
                    del element.attrib[key]
            elif key == "style":
                declarations = []
                for declaration in value.split(";"):
                    name, sep, val = declaration.partition(":")
                    if sep and name.strip() in CSS_KEYS and CSS_VALUE.fullmatch(val.strip()):
                        declarations.append(f"{name.strip()}:{val.strip()}")
                element.set(key, ";".join(declarations))
            elif key.startswith("data-") and not key.startswith("data-on"):
                if key.endswith(("url", "src")):
                    try:
                        element.set(key, local_url(value, url))
                    except ValueError:
                        del element.attrib[key]
            elif key not in ATTRS:
                del element.attrib[key]
        if element.tag == "form":
            element.set("action", local_url(element.get("action", url), url))
        if element.tag == "img":
            element.set("loading", "lazy")
    title = " ".join(main.xpath(".//h1//text()")) or "学习工作台"
    markup = escape(main.text or "") + "".join(etree.tostring(child, encoding="unicode", method="html") for child in main)
    return {"url": url, "title": title.strip(), "html": markup, "widgets": widgets}


def learner_scope(match):
    """Stored scope of a learner-bound page, after its view authorized access."""
    from app.persistence.models import EntityRecord
    if match.namespace == "study" and match.url_name == "schedule_detail":
        from app.study.models import StudySchedule
        schedule = StudySchedule.objects.select_related("learner").get(pk=match.kwargs["schedule_pk"])
        return {"household_id": str(schedule.household_id), "learner_id": schedule.learner.stable_id}
    if match.namespace == "study" and "learner_entity_pk" in match.kwargs:
        row = EntityRecord.objects.get(pk=match.kwargs["learner_entity_pk"], kind="learner")
    elif match.namespace == "printing" and match.url_name == "evidence_report":
        row = EntityRecord.objects.get(pk=match.kwargs["pk"], kind="learner")
    elif match.namespace == "learning":
        kind = next((kind for kind in ("learner", "attempt", "assessment", "observation")
                     if kind + "_id" in match.kwargs), None)
        if kind is None:
            return None
        row = EntityRecord.objects.filter(kind=kind, stable_id=match.kwargs[kind + "_id"]).first()
        if row.kind == "assessment":
            row = EntityRecord.objects.get(household_id=row.household_id, kind="attempt",
                                          stable_id=row.identity["attempt_id"])
    else:
        return None
    learner_id = (row.stable_id if row.kind == "learner" else row.identity.get("profile_context_id")
                  if row.kind == "observation" else row.identity["learner_id"])
    return {"household_id": str(row.household_id), "learner_id": learner_id} if learner_id else None


def page_scope(match, request):
    """Bind private form recovery to the authorized object, never a browser's stale selector."""
    scope = learner_scope(match)
    if scope:
        return scope
    from app.persistence import services as core
    from app.persistence.models import EntityRecord, Household, RevisionRecord
    from app.web.models import MaterialPage, MaterialSet
    values = match.kwargs
    household_id = None
    if 'material_id' in values:
        household_id = MaterialSet.objects.get(pk=values['material_id']).household_id
    elif 'page_id' in values:
        household_id = MaterialPage.objects.select_related('material').get(pk=values['page_id']).material.household_id
    elif 'entity_id' in values:
        household_id = EntityRecord.objects.get(pk=values['entity_id']).household_id
    elif 'question_id' in values:
        household_id = EntityRecord.objects.get(kind='question', stable_id=values['question_id']).household_id
    elif match.namespace == 'learning' and any(name + '_id' in values for name in ('learner', 'attempt', 'assessment', 'observation')):
        kind = next(name for name in ('learner', 'attempt', 'assessment', 'observation') if name + '_id' in values)
        household_id = EntityRecord.objects.get(kind=kind, stable_id=values[kind + '_id']).household_id
    elif match.namespace == 'printing' and match.url_name in {'diagrams', 'answer', 'erratum'}:
        household_id = RevisionRecord.objects.select_related('entity').get(pk=values['pk']).entity.household_id
    elif match.namespace == 'printing' and match.url_name == 'snapshot':
        from app.printing.models import ExportSnapshot
        household_id = ExportSnapshot.objects.get(pk=values['pk']).household_id
    elif match.namespace == 'ai' and 'run_id' in values:
        from app.ai.models import ModelRun
        household_id = ModelRun.objects.get(pk=values['run_id']).household_id
    else:
        household_id = values.get('household_id')
        if household_id is None:
            params = request.POST if request.method == 'POST' else request.GET
            household_id = params.get('household_id') or params.get('household')
    if household_id is None:
        return None
    owner = Household.objects.get(pk=household_id)
    core.require_household_access(request.user, owner)
    return {'household_id': str(owner.pk), 'learner_id': ''}


def dispatch(request):
    url, parts, match = allowed_target(request.GET.get("url", ""))
    forwarded = copy(request)
    forwarded.path = forwarded.path_info = unquote(parts.path, errors="strict")
    forwarded.GET = QueryDict(parts.query)
    forwarded.META = {**request.META, "PATH_INFO": forwarded.path_info, "QUERY_STRING": parts.query,
                      "HTTP_ACCEPT": "text/html", "HTTP_X_REQUESTED_WITH": ""}
    forwarded.__dict__.pop("headers", None)
    forwarded.resolver_match = match
    result = match.func(forwarded, *match.args, **match.kwargs)
    if 300 <= result.status_code < 400:
        destination = local_url(result["Location"], url)
        if urlsplit(destination).path != "/app/":
            allowed_target(destination)
        return {"redirect": destination}
    if result.status_code in {401, 403, 404, 405}:
        return error("unavailable", "当前账号无法进行此操作，请返回检查权限或记录。", result.status_code)
    if "text/html" not in result.get("Content-Type", "") or getattr(result, "streaming", False):
        raise Http404
    page = fragment(result.content, url)
    scope = page_scope(match, forwarded)
    if scope:
        page["scope"] = scope
    return response({"page": page}, status=result.status_code)


@api()
def page(request):
    return dispatch(request)


@api("POST")
def submit(request):
    return dispatch(request)
