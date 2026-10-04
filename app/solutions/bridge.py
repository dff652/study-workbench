"""Compile editable Workbench content through the pinned companion v1 contract."""
from html import escape
import json
from pathlib import Path

from app.domain.arithmetic import formula_ast
from app.exports.contracts import SCHEMA_VERSION, canonical, digest, document_from_dict
from app.persistence import services as core
from app.persistence.models import RevisionRecord
from . import schema
from .vendor import model, sources as source_contract


def verify_vendor():
    root = Path(__file__).parent / "vendor"
    manifest = json.loads((root / "SOURCE.json").read_text())
    if manifest["commit"] != "72e9a3d178859d47581db17a71bee3babaa31ee8":
        raise core.PersistenceError("solution_tool_changed", "解析工具版本发生变化，请核对部署。")
    for name, record in manifest["files"].items():
        if name not in {"model.py", "contracts.py", "sources.py", "common.py"} or digest((root / name).read_bytes()) != record["adapted_sha256"]:
            raise core.PersistenceError("solution_tool_changed", "解析工具校验失败，请核对部署。")
    return manifest


def source_manifest(material, content, pages):
    batch_id = "material-" + material.pk.hex
    used = {ref["page_id"] for question in content["questions"] for ref in question["sources"]}
    result, mapping = [], {}
    for page in sorted((pages[page_id] for page_id in used), key=lambda page: page.position):
        data = page.image.payload
        key = data["storage_key"]
        source_id = source_contract._source_id(batch_id, key)
        mapping[str(page.pk)] = source_id
        from app.web.services import asset_path
        original = asset_path(key, page.image.sha256)
        result.append({"source_id": source_id, "storage_key": key, "book": material.title,
            "token": f"{page.position:06}", "page_order": page.position,
            "sha256": page.image.sha256, "size": original.stat().st_size,
            "width": data["width"], "height": data["height"],
            "format": "PNG" if data["media_type"] == "image/png" else "JPEG"})
    return {"schema_version": "swf.sources.v1", "batch_id": batch_id,
            "expected_counts": {"sources": len(result)}, "sources": result}, mapping


def _text_block(value, role="method", kind="p"):
    return {"kind": kind, "content": escape(value).replace("\n", "<br/>"), "role": role}


def companion_content(revision, assets):
    verify_vendor()
    content, snapshot = revision.content, revision.sources
    manifest, mapping = snapshot["manifest"], snapshot["page_mapping"]
    used_lectures = {question["lecture_id"] for question in content["questions"]}
    result = {"schema_version": model.SCHEMA_VERSION, "batch_id": manifest["batch_id"],
        "revision_id": f"revision-{revision.pk}", "title": content["title"] or revision.material.title,
        "sources_sha256": digest(canonical(manifest)), "unknowns": [],
        "lectures": [{"lecture_id": item["id"], "title": item["title"]} for item in content["lectures"] if item["id"] in used_lectures],
        "questions": [], "assets": [], "outputs": content["outputs"]}
    missing = schema.gaps(content)
    linked = RevisionRecord.objects.in_bulk({link["revision_id"]
        for question in content["questions"] for link in question["links"]})
    used_assets = set()
    for question in content["questions"]:
        title = question["title"] or f"第 {question['number'] or len(result['questions']) + 1} 题"
        blocks = [_text_block(title, "title", "title")]
        statement = question["statement"]["text"] or None
        blocks.append(_text_block(statement or "题干待补，请对照原图核实。", "question"))
        parts = []
        parents = {part["parent_id"] for part in question["parts"]}
        for part in question["parts"]:
            part = {**part, "label": part["label"] or "小问"}
            parts.append({"part_id": part["id"], "parent_id": part["parent_id"], "label": part["label"],
                "statement": part["statement"] or None, "answer": part["answer"] or None, "unit": part["unit"] or None})
            if part["statement"]:
                blocks.append(_text_block(part["label"] + " " + part["statement"], "question"))
        for label, field in (("先想什么", "thinking"), ("本讲解法", "lecture_method"), ("其他解法", "alternative_method")):
            if question[field] or field == "lecture_method":
                blocks.extend([_text_block(label, "method", "h"), _text_block(question[field] or "解法待补。")])
        for index, step in enumerate(question["steps"], 1):
            if step.strip():
                blocks.append(_text_block(f"{index}. {step}"))
        for link in question["links"]:
            payload = linked[link["revision_id"]].payload
            label = payload.get("name") or payload.get("definition") or "未命名条目"
            relation = {"knowledge": "知识出处", "primary_method": "主要方法",
                        "secondary_method": "辅助方法", "question_type": "题型"}[link["relation"]]
            blocks.append(_text_block(f"{relation}：{label}", "method", "small"))
        for expression in question["formulas"]:
            if expression.strip():
                blocks.append({"kind": "math", "content": formula_ast(expression), "role": "method"})
        for part in parts:
            if part["part_id"] not in parents:
                blocks.append(_text_block(part["label"] + " 答案：" + (part["answer"] or "未知")
                    + (" " + part["unit"] if part["unit"] else "（单位待确认）"), "answer"))
        for note in question["pitfalls"]:
            if note.strip():
                blocks.append(_text_block("易错点：" + note, "method", "warn"))
        for correction in question["corrections"]:
            label = {"printing_error": "资料印刷勘误", "naming": "命名调整", "draft_correction": "草稿修正"}[correction["kind"]]
            blocks.append(_text_block(f"{label}：{correction['original']} → {correction['replacement']}；依据：{correction['basis']}", "method", "erratum"))
        unknowns = [item["message"] for item in missing if item["question_id"] == question["id"]]
        for note in unknowns:
            blocks.append(_text_block("待补：" + note, "method", "small"))
        for figure in question["figures"]:
            asset = assets[figure["asset_id"]]
            source_id = mapping[asset.source["page_id"]] if asset.source else None
            if str(asset.pk) not in used_assets:
                result["assets"].append({"storage_key": asset.storage_key, "sha256": asset.sha256,
                    "kind": asset.kind, "source_id": source_id,
                    "region": asset.source["region"] if asset.source else None, "basis": asset.basis})
                used_assets.add(str(asset.pk))
            blocks.append({"kind": "diagram", "role": figure["role"], "content": {
                "storage_key": asset.storage_key, "sha256": asset.sha256,
                "source_ref": asset.label + "；依据：" + asset.basis,
                "alt": figure["caption"] or asset.label, "width_mm": figure["width_mm"], "no_hint_confirmed": False}})
        result["questions"].append({"question_id": question["id"], "lecture_id": question["lecture_id"],
            "display_number": question["number"] or str(len(result["questions"]) + 1), "title": title,
            "statement": {"text": statement, "status": question["statement"]["status"] if statement else "unknown"},
            "source_refs": [{"source_id": mapping[ref["page_id"]], "sequence": index, "region": ref["region"]}
                            for index, ref in enumerate(question["sources"], 1)],
            "parts": parts, "pages": [blocks], "unknowns": unknowns, "corrections": question["corrections"]})
    model.validate_content(result, manifest)
    return result


def native_document(document, lectures=()):
    value = model.document_from_dict(document) if isinstance(document, dict) else document
    from .vendor.contracts import document_dict
    # Upstream documents deliberately share question block bodies between
    # organizations. Adapt a detached copy so translating one cannot mutate the others.
    data = json.loads(canonical(document_dict(value)))
    data["schema_version"] = SCHEMA_VERSION
    lecture_labels = {item["lecture_id"]: item["title"] for item in lectures}
    for page in data["pages"]:
        for block in page:
            if block["kind"] == "table" and data["document_id"] == "combined":
                for row in block["content"][0][1:]:
                    lecture_id, separator, number = row[0].partition("/")
                    if separator and lecture_id in lecture_labels:
                        row[0] = escape(lecture_labels[lecture_id]) + "／" + number
            if block["kind"] == "diagram":
                block["kind"] = "companion_image"
                content = block["content"]
                content["width_points"] = content.pop("width_mm") * 72 / 25.4
                content.pop("no_hint_confirmed")
    return document_from_dict(data)
