"""Product projections; private storage paths and tool fingerprints stay server-side."""
from django.urls import reverse
from django.db.models import Q
from urllib.parse import quote

from app.persistence import services as core
from app.web.models import QuestionSource
from . import schema, services
from .models import SolutionOutput


CHECK_NAMES = ("content", "math", "pdf_visual", "word_pc", "word_macos")
STATES = {"queued": "等待生成", "running": "正在生成", "output_check": "可预览，待检查",
          "complete": "检查已记录，可下载", "failed": "生成未完成", "cancelled": "已取消"}


def default_checks():
    return {name: {"status": "not_tested", "notes": ""} for name in CHECK_NAMES}


def output_row(row):
    result = row.result
    documents = []
    for item in result.get("documents", []):
        def url(name):
            return reverse("api:solution_output_file", args=[row.pk, item["id"], name])
        documents.append({"id": item["id"], "title": item["title"], "organization": item["organization"],
            "question_ids": item["question_ids"], "page_count": item["page_count"],
            "pdf_url": url("document.pdf") if "pdf" in item["formats"] else None,
            "docx_url": url("document.docx") if "docx" in item["formats"] else None,
            "previews": [url(name) for name in item["previews"]]})
    message = ""
    if row.state == "failed":
        message = {"source_changed": "来源已更新，请比较后保存新版本再生成。",
                   "permission_changed": "访问权限已变化，请联系家庭所有者。",
                   "layout_overflow": "有段落或图示超出版面，请缩短段落或减小图示后生成新版本。",
                   "missing_renderer_tool": "服务缺少预览工具，请由管理员检查安装。",
                   "interrupted": "后台处理已中断，可以重试；旧文档仍保留。"}.get(
                       row.error_code, "生成未完成，请核对内容和图示后重试；旧文档仍保留。")
    downloadable = row.state in {"output_check", "complete"} and not any(
        item["status"] == "fail" for item in result.get("checks", {}).values())
    return {"id": str(row.pk), "revision_id": row.revision_id, "revision_version": row.revision.version,
        "version": row.version, "state": row.state, "state_label": STATES[row.state], "message": message,
        "created_at": row.created_at.isoformat(), "documents": documents,
        "checks": result.get("checks", default_checks()),
        "zip_url": reverse("api:solution_output_zip", args=[row.pk]) if downloadable and result.get("zip") else None}


def revision_row(row, *, include_content=True):
    result = {"id": row.pk, "version": row.version, "created_at": row.created_at.isoformat(),
        "author": row.author.get_username(), "reason": row.reason, "confirmed": row.confirmations.exists()}
    if include_content:
        result.update(content=row.content, gaps=schema.gaps(row.content))
    return result


def _history(material, before=None):
    rows = material.solution_revisions.select_related("author").prefetch_related("confirmations").order_by("-version")
    if before is not None:
        rows = rows.filter(version__lt=before)
    selected = list(rows[:101])
    return selected[:100], selected[99].version if len(selected) > 100 else None


def _nodes(revisions, history):
    referenced = {link["revision_id"] for revision in history for question in revision.content["questions"]
                  for link in question["links"]}
    result = []
    for item in revisions.values():
        if item.entity.kind not in ("knowledge", "method", "question_type"):
            continue
        historical = item.entity.published_revision_id != item.pk
        if historical and item.pk not in referenced:
            continue
        result.append({"revision_id": item.pk, "kind": item.entity.kind,
            "label": (item.payload.get("name") or item.payload.get("definition") or "未命名条目")[:130] +
                f" · 第 {item.revision_no} 版" + ("（历史版本）" if historical else ""),
            "detail_url": reverse("knowledge:node_detail", args=[item.entity_id]) + "#revision-" + quote(item.pk, safe="")})
    return result


def _outputs(material, before=None):
    rows = SolutionOutput.objects.filter(revision__material=material).select_related("revision").order_by("-created_at", "-pk")
    if before is not None:
        cursor = rows.filter(pk=before).first()
        if cursor is None:
            raise core.PersistenceError("not_found", "没有找到可访问的文档历史。")
        rows = rows.filter(Q(created_at__lt=cursor.created_at) | Q(created_at=cursor.created_at, pk__lt=cursor.pk))
    selected = list(rows[:51])
    return [output_row(row) for row in selected[:50]], str(selected[49].pk) if len(selected) > 50 else None


def history_page(actor, material_id, before=None):
    row = services.material(actor, material_id)
    if before is not None:
        try:
            before = int(before)
            if before < 1:
                raise ValueError
        except (ValueError, TypeError):
            raise core.PersistenceError("invalid_solution", "历史版本范围无效，请重新读取。")
    history, cursor = _history(row, before)
    _, revisions, _ = services.inputs(row)
    return {"history": [revision_row(item, include_content=False) for item in history],
            "nodes": _nodes(revisions, history), "history_next_before": cursor}


def outputs_page(actor, material_id, before=None):
    row = services.material(actor, material_id)
    outputs, cursor = _outputs(row, before)
    return {"outputs": outputs, "output_next_before": cursor}


def workspace(actor, material_id):
    row = services.material(actor, material_id)
    pages, revisions, assets = services.inputs(row)
    try:
        core.require_household_access(actor, row.household, write=True)
        writable = True
    except core.PersistenceError:
        writable = False
    current = services.latest(row)
    history, history_cursor = _history(row)
    outputs, output_cursor = _outputs(row)
    question_sources = QuestionSource.objects.filter(material=row).select_related("revision__entity")
    questions = []
    for source in question_sources:
        question = source.revision
        if question.entity.published_revision_id != question.pk:
            continue
        refs = []
        for ref in source.sources:
            if ref["page_id"] in pages:
                refs.append({"page_id": ref["page_id"], "region": ref.get("original_bbox")})
        statement = question.payload.get("printed_text") or question.payload.get("working_text") or ""
        questions.append({"revision_id": question.pk, "label": (source.original_number + " · " + statement)[:160],
            "statement": statement, "sources": refs,
            "detail_url": reverse("knowledge:question_detail", args=[question.entity_id])})
    nodes = _nodes(revisions, history)
    return {"material": {"id": str(row.pk), "title": row.title}, "writable": writable,
        "revision": revision_row(current) if current else None,
        "initial_content": {"schema_version": schema.SCHEMA, "title": row.title + " · 逐题解析",
            "lectures": [{"id": "lecture-1", "title": "第 1 讲"}], "questions": [],
            "outputs": {"per_question": ["pdf", "docx"], "per_lecture": [], "combined": ["pdf", "docx"]}},
        "history": [revision_row(item, include_content=False) for item in history],
        "history_next_before": history_cursor,
        "outputs": outputs, "output_next_before": output_cursor,
        "assets": [{"id": str(item.pk), "kind": item.kind, "label": item.label, "basis": item.basis,
            "source": item.source, "width": item.width, "height": item.height,
            "url": reverse("api:solution_asset", args=[item.pk])} for item in assets.values()],
        "pages": [{"id": str(page.pk), "label": f"第 {page.position} 页", "width": page.image.payload["width"],
            "height": page.image.payload["height"], "preview_url": reverse("web:page_preview", args=[page.pk, 0]),
            "detail_url": reverse("web:page_detail", args=[page.pk])} for page in pages.values()],
        "questions": questions, "nodes": nodes}
