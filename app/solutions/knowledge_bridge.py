"""Pinned knowledge compilation through the existing native printing engine."""
from dataclasses import replace
from html import escape
import json
from pathlib import Path

from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics

from app.domain.arithmetic import formula_ast
from app.exports.contracts import Block, canonical, digest
from app.exports.renderer import _footer_status, _register_fonts
from app.persistence import services as core
from app.printing.layout import paginate
from app.web import subjects
from . import bridge, knowledge_schema
from .vendor import knowledge_model as model
from .vendor.common import WorkflowError

PIN = "961f966f02f2c00e3c43b2dfd3e17ad19e345fa5"


def verify_vendor():
    root = Path(__file__).parent / "vendor"
    manifest = json.loads((root / "KNOWLEDGE_SOURCE.json").read_text())
    names = {"knowledge_model.py", "contracts.py", "sources.py", "common.py"}
    if manifest["commit"] != PIN or set(manifest["files"]) != names:
        raise core.PersistenceError("knowledge_tool_changed", "知识讲解工具版本发生变化，请核对部署。")
    for name, record in manifest["files"].items():
        if digest((root / name).read_bytes()) != record["adapted_sha256"]:
            raise core.PersistenceError("knowledge_tool_changed", "知识讲解工具校验失败，请核对部署。")
    return manifest


def companion_content(revision, assets):
    verify_vendor()
    content, snapshot = revision.content, revision.sources
    manifest, mapping = snapshot["manifest"], snapshot["page_mapping"]
    source_by_id = {item["source_id"]: item for item in manifest["sources"]}
    used_lectures = {item["lecture_id"] for item in content["knowledge"]}
    result = {"schema_version": model.SCHEMA_VERSION, "batch_id": manifest["batch_id"],
        "revision_id": f"revision-{revision.pk}", "title": content["title"] or revision.material.title,
        "learner_level": content["learner_level"], "sources_sha256": digest(canonical(manifest)),
        "lectures": [{"lecture_id": lecture["id"], "title": lecture["title"], "subject": lecture["rule_profile"]}
            for lecture in content["lectures"] if lecture["id"] in used_lectures],
        "knowledge": [], "assets": [], "outputs": content["outputs"], "unknowns": []}
    used_assets = set()
    for item in content["knowledge"]:
        pages, blocks = [], []
        for step in item["steps"]:
            if step["new_page"] and blocks:
                pages.append(blocks)
                blocks = []
            section = step["section"]
            if step["text"].strip():
                blocks.append({"kind": "p", "content": escape(step["text"]).replace("\n", "<br/>"),
                    "role": "method", "section": section})
            if step["formula"]:
                blocks.append({"kind": "math", "content": formula_ast(step["formula"]), "role": "method", "section": section})
            if step["figure"] is not None:
                figure = step["figure"]
                asset = assets[figure["asset_id"]]
                if str(asset.pk) not in used_assets:
                    result["assets"].append({"storage_key": asset.storage_key, "sha256": asset.sha256,
                        "kind": asset.kind, "source_id": mapping[asset.source["page_id"]] if asset.source else None,
                        "region": asset.source["region"] if asset.source else None, "basis": asset.basis})
                    used_assets.add(str(asset.pk))
                blocks.append({"kind": "diagram", "role": figure["role"], "section": section, "content": {
                    "storage_key": asset.storage_key, "sha256": asset.sha256,
                    "source_ref": asset.label + "；依据：" + asset.basis,
                    "alt": figure["caption"] or asset.label, "width_mm": figure["width_mm"], "no_hint_confirmed": False}})
        if blocks:
            pages.append(blocks)
        references = []
        for ref in item["sources"]:
            source = source_by_id[mapping[ref["page_id"]]]
            references.append({"source_id": source["source_id"], "source_file": source["storage_key"],
                "source_sha256": source["sha256"], "printed_page": ref["printed_page"] or None})
        result["knowledge"].append({"knowledge_id": item["id"], "lecture_id": item["lecture_id"], "order": item["order"],
            "title": item["title"], "kind": item["kind"], "origin": item["origin"], "source_refs": references,
            "original": item["original"] or None, "statement": item["statement"], "definitions": item["definitions"] or None,
            "conditions": item["conditions"], "dependencies": item["dependencies"], "pages": pages,
            "corrections": item["corrections"], "unknowns": item["unknowns"]})
    try:
        bridge.verify_assets(result, manifest, Path(settings.SWB_DATA_ROOT), validate=model.validate_content)
    except WorkflowError as exc:
        messages = {"missing_explanation": "每条知识需要五部分实质讲解；推导不能只列标题或公式。",
            "missing_conclusion": "结论部分须重述完整结论，不能只写计算值或省略条件。",
            "missing_output": "请至少选择一种文档组织和输出格式。",
            "invalid_knowledge": "知识的名称、结论、条件、层级或来源尚未齐备，请核对待补清单。"}
        raise core.PersistenceError("knowledge_incomplete", messages.get(exc.code,
            "知识内容或来源不完整，请核对依赖、原图、讲解部分及输出选择。")) from exc
    return result


def _native(document, content, revision):
    native = bridge.native_document(document, content["lectures"])
    pages = []
    by_id = {item["id"]: item for item in revision.content["knowledge"]}
    numbers = {item["id"]: index for index, item in enumerate(revision.content["knowledge"], 1)}
    profiles = {lecture["id"]: lecture["rule_profile"] for lecture in revision.content["lectures"]}
    positions = {str(page.pk): page.position for page in revision.material.pages.all()}
    # Change only the human-facing source label; the recipe retains exact storage keys and hashes.
    item_id = native.document_id.removeprefix("knowledge-")
    for index, page in enumerate(native.pages):
        item = by_id.get(item_id)
        if native.document_id == "inventory":
            item = by_id[content["knowledge"][index]["knowledge_id"]]
        blocks = []
        for block in page:
            if item and block.kind == "h" and isinstance(block.content, str) and block.content.startswith(escape(item["id"]) + " "):
                block = replace(block, content=f"知识 {numbers[item['id']]} " + block.content[len(escape(item["id"])) + 1:])
            if item and block.kind == "small" and isinstance(block.content, str) and block.content.startswith("<b>证明／讲解依赖：</b>") and item["dependencies"]:
                names = "；".join(f"知识 {numbers[identifier]}：{by_id[identifier]['title']}" for identifier in item["dependencies"])
                block = replace(block, content="<b>证明／讲解依赖：</b>" + escape(names))
            if item and block.kind == "small" and isinstance(block.content, str) and block.content.startswith("<b>来源：</b>"):
                label = "；".join(f"第 {positions[ref['page_id']]} 页／印刷页 {ref['printed_page'] or '未确认'}" for ref in item["sources"])
                block = replace(block, content="<b>来源：</b>" + escape(label or "基础／补充，无原页来源"))
            blocks.append(block)
        if item and (index == 0 or native.document_id == "inventory"):
            label = subjects.LABELS[revision.content["school_subject"]] + "；" + knowledge_schema.PROFILES[profiles[item["lecture_id"]]]
            blocks.insert(1, Block("small", "学校学科与讲解依据：" + escape(label)))
        pages.append(tuple(blocks))
    return replace(native, pages=tuple(pages))


def _footer_title(document, fonts):
    """Fit the repeated label; the complete title remains in the body and recipe."""
    font = _register_fonts(fonts)[0]["regular"]
    count = len(document.pages)
    footer = f"{_footer_status(document)} | {count}/{count}"
    available = A4[0] - 104 - pdfmetrics.stringWidth(footer, font, 8)
    if pdfmetrics.stringWidth(document.title, font, 8) <= available:
        return document.title
    lower, upper = 0, len(document.title)
    while lower < upper:
        midpoint = (lower + upper + 1) // 2
        if pdfmetrics.stringWidth(document.title[:midpoint] + "...", font, 8) <= available:
            lower = midpoint
        else:
            upper = midpoint - 1
    return document.title[:lower] + "..."


def plans(content, revision, fonts=None, root=None):
    """Measure each full knowledge body once; every organization reuses those pages."""
    raw_plans = model.compile_documents(content)
    numbers = {item["knowledge_id"]: index for index, item in enumerate(content["knowledge"], 1)}
    originals = {item["knowledge_id"]: _native(model._knowledge_document(content, item), content, revision)
                 for item in content["knowledge"]}
    if fonts is not None:
        originals = {key: replace(document, pages=tuple(measured for page in document.pages
            for measured in paginate(list(page), fonts, root))) for key, document in originals.items()}
    result = []
    for plan in raw_plans:
        document = _native(plan["document"], content, revision)
        identifier = document.document_id
        ids = plan["knowledge_ids"]
        organization = "inventory" if identifier == "inventory" else "per_knowledge" if identifier.startswith("knowledge-") else "per_lecture" if identifier.startswith("lecture-") else "combined"
        if organization == "inventory":
            pages, mapping = [], []
            for page, item_id in zip(document.pages, plan["page_knowledge"], strict=True):
                measured = paginate(list(page), fonts, root) if fonts is not None else [page]
                pages.extend(measured)
                mapping.extend([item_id] * len(measured))
        else:
            cover_count = plan["page_knowledge"].count(None)
            covers = []
            for page in document.pages[:cover_count]:
                blocks = []
                for block in page:
                    if block.kind == "table":
                        rows, widths = block.content
                        rows = [rows[0]] + [[str(numbers[row[0]]), row[1], "0"] for row in rows[1:]]
                        block = replace(block, content=[rows, widths])
                    blocks.append(block)
                covers.extend(paginate(blocks, fonts, root) if fonts is not None else [tuple(blocks)])
            starts, position = {}, len(covers) + 1
            for item_id in ids:
                starts[str(numbers[item_id])] = position
                position += len(originals[item_id].pages)
            pages, mapping = [], []
            for page in covers:
                blocks = []
                for block in page:
                    if block.kind == "table":
                        rows, widths = block.content
                        # Page numbers fit this fixed-width column; changing them
                        # does not change the measured title rows or body pages.
                        rows = [rows[0]] + [[row[0], row[1], str(starts[row[0]])] for row in rows[1:]]
                        block = replace(block, content=[rows, widths])
                    blocks.append(block)
                pages.append(tuple(blocks)); mapping.append(None)
            for item_id in ids:
                pages.extend(originals[item_id].pages)
                mapping.extend([item_id] * len(originals[item_id].pages))
        document = replace(document, pages=tuple(pages))
        if fonts is not None:
            document = replace(document, title=_footer_title(document, fonts))
        result.append({**plan, "document": document, "organization": organization,
                       "page_knowledge": mapping})
    return result
