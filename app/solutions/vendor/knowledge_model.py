"""Independent knowledge records, subject rules and source-bound compilation."""
from __future__ import annotations

from html import escape
from pathlib import Path, PurePosixPath
import re

from PIL import Image
from .sources import validate_manifest, verify_sources
from .contracts import (Block, ExportDocument, ExportError, SourceRef,
    TEXT_KINDS, document_dict, document_from_dict, plain_text, resolve_formula_image)
from .common import canonical, digest, fail, resolve_under, WorkflowError

SCHEMA_VERSION = "swf.knowledge-companion.v1"
REVIEW_SCHEMA = "swf.knowledge-review.v1"
ROOT = Path(__file__).resolve().parent.parent
SUBJECT_KINDS = {
    "mathematics": {"definition", "theorem", "strategy"},
    "science": {"definition", "empirical_rule", "strategy"},
    "language": {"definition", "interpretation", "strategy"},
    "humanities": {"definition", "interpretation", "strategy"},
}
SECTION_LABELS = {"thinking": "先想什么", "construction": "方法／构造及目的",
    "derivation": "完整推导／依据", "conclusion": "结论",
    "pitfall": "易错点／适用限制", "other": "其他讲解／证明"}
KIND_LABELS = {"definition": "定义", "theorem": "数学定理", "empirical_rule": "观察／经验结论",
    "interpretation": "文本解释", "strategy": "方法"}
ORIGIN_LABELS = {"source": "原页知识", "foundation": "基础知识", "supplement": "补充知识"}
CONTENT_KEYS = {"schema_version", "batch_id", "revision_id", "title", "learner_level",
    "sources_sha256", "lectures", "knowledge", "assets", "outputs", "unknowns"}
KNOWLEDGE_KEYS = {"knowledge_id", "lecture_id", "order", "title", "kind", "origin",
    "source_refs", "original", "statement", "definitions", "conditions", "dependencies",
    "pages", "corrections", "unknowns"}


def _fields(value, fields, name):
    if type(value) is not dict or set(value) != set(fields):
        fail("invalid_knowledge", name + " requires exact explicit fields")


def _text(value, name, nullable=False):
    if nullable and value is None:
        return
    if (type(value) is not str or not value.strip() or len(value) > 2000 or
            re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value)):
        fail("invalid_knowledge", name + " requires bounded nonempty text")


def _id(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        fail("invalid_knowledge", "Expected a local identifier")


def _sha(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        fail("invalid_knowledge", "Expected SHA-256")


def _list(value, name, maximum=100, nonempty=False):
    if type(value) is not list or len(value) > maximum or (nonempty and not value):
        fail("invalid_knowledge", name + " requires a bounded list")


def _notes(value, name, nonempty=False):
    _list(value, name, nonempty=nonempty)
    for item in value:
        _text(item, name)


def _enum(value, allowed):
    if type(value) is not str or value not in allowed:
        fail("invalid_knowledge", "Unsupported explicit value")


def _ids(values, allowed, name, complete=False):
    _list(values, name)
    for value in values:
        _id(value)
    if len(set(values)) != len(values) or not set(values) <= set(allowed):
        fail("invalid_knowledge", name + " contains repeated or unknown identifiers")
    if complete and set(values) != set(allowed):
        fail("incomplete_review", name + " must cover the complete scope")


def _key(value):
    if (type(value) is not str or not value or "\\" in value or
            any(ord(c) < 32 for c in value) or re.match(r"[A-Za-z]:", value)):
        fail("path_escape", "Resource requires a canonical relative PNG path")
    p = PurePosixPath(value)
    if p.is_absolute() or p.as_posix() != value or any(s in {"", ".", ".."} for s in value.split("/")):
        fail("path_escape", "Resource path must stay within its root")
    if p.suffix.lower() != ".png":
        fail("invalid_knowledge", "Resources must be PNG")


def _region(value, source=None):
    if (type(value) is not list or len(value) != 4 or any(type(n) is not int for n in value)
            or not 0 <= value[0] < value[2] or not 0 <= value[1] < value[3]):
        fail("invalid_region", "Crop requires four original-pixel coordinates")
    if source and (value[2] > source["width"] or value[3] > source["height"]):
        fail("invalid_region", "Crop exceeds its original")


def content_digest(content):
    return digest(canonical(content))


def _source_label(item):
    if not item["source_refs"]:
        return "本册基础／补充，无原页来源"
    return "; ".join(r["source_file"] + "／印刷页 " + (r["printed_page"] or "未确认") for r in item["source_refs"])


def _para(label, value, kind="small"):
    return Block(kind, "<b>" + escape(label) + "：</b>" + escape(value))


def _metadata(item, inventory=False):
    blocks = [Block("h", escape(item["knowledge_id"] + " " + item["title"])),
        _para("来源", _source_label(item)), _para("性质／归属", KIND_LABELS[item["kind"]] + "／" + ORIGIN_LABELS[item["origin"]]),
        _para("结论", item["statement"], "key"), _para("条件", "；".join(item["conditions"])),
        _para("图形与字母", item["definitions"] or "未另设图形／字母定义"),
        _para("证明／讲解依赖", ", ".join(item["dependencies"]) or "正文说明采用的基础知识")]
    if inventory:
        blocks += [_para("原结论", item["original"] or "基础／补充，无原页结论")]
    for c in item["corrections"]:
        blocks.append(_para("勘误", c["original"] + " → " + c["replacement"] + "；依据：" + c["basis"]))
    blocks.append(_para("待核项", "；".join(item["unknowns"]) or "无已记录待核项"))
    return blocks


def _knowledge_document(content, item):
    pages = []
    for number, raw_page in enumerate(item["pages"]):
        page = _metadata(item) if number == 0 else [Block("h", escape(item["knowledge_id"] + " " + item["title"] + "（续）"))]
        last_section = None
        for value in raw_page:
            if value["section"] != last_section:
                page.append(Block("h", SECTION_LABELS[value["section"]]))
                last_section = value["section"]
            page.append(Block(value["kind"], value["content"], value["role"]))
        pages.append(tuple(page))
    return ExportDocument("knowledge-" + item["knowledge_id"], item["title"], "knowledge_summary",
        tuple(pages), SourceRef(content["batch_id"], content_digest(content), "draft", content["revision_id"]))


def validate_content(content, sources=None):
    _fields(content, CONTENT_KEYS, "content")
    if content["schema_version"] != SCHEMA_VERSION:
        fail("invalid_knowledge", "Unsupported knowledge schema")
    for key in ("batch_id", "revision_id"):
        _id(content[key])
    for key in ("title", "learner_level"):
        _text(content[key], key)
    _sha(content["sources_sha256"]); _notes(content["unknowns"], "unknowns")
    source_by_id = None
    if sources is not None:
        validate_manifest(sources)
        if content["batch_id"] != sources["batch_id"] or content["sources_sha256"] != digest(canonical(sources)):
            fail("stale_sources", "Knowledge and source snapshots differ")
        source_by_id = {s["source_id"]: s for s in sources["sources"]}
    _list(content["lectures"], "lectures", nonempty=True)
    lectures = {}
    for item in content["lectures"]:
        _fields(item, {"lecture_id", "title", "subject"}, "lecture")
        _id(item["lecture_id"]); _text(item["title"], "lecture title"); _enum(item["subject"], SUBJECT_KINDS)
        if item["lecture_id"] in lectures:
            fail("duplicate_id", "Repeated lecture")
        lectures[item["lecture_id"]] = item
    _fields(content["outputs"], {"inventory", "per_knowledge", "per_lecture", "combined"}, "outputs")
    for formats in content["outputs"].values():
        _list(formats, "formats", 2)
        for value in formats:
            _enum(value, {"pdf", "docx"})
        if len(set(formats)) != len(formats):
            fail("invalid_knowledge", "Repeated output format")
    if not any(content["outputs"].values()):
        fail("missing_output", "Select at least one output")
    _list(content["assets"], "assets", maximum=300)
    assets = {}
    for asset in content["assets"]:
        _fields(asset, {"storage_key", "sha256", "kind", "source_id", "region", "basis"}, "asset")
        _key(asset["storage_key"]); _sha(asset["sha256"]); _text(asset["basis"], "asset basis")
        _enum(asset["kind"], {"source_crop", "source_image", "auxiliary"})
        if asset["storage_key"] in assets:
            fail("duplicate_id", "Repeated asset")
        if asset["kind"] == "auxiliary":
            if asset["source_id"] is not None or asset["region"] is not None:
                fail("invalid_knowledge", "New diagrams must not claim original pixels")
        else:
            _id(asset["source_id"])
            if source_by_id is not None and asset["source_id"] not in source_by_id:
                fail("unknown_source", "Unknown asset source")
            if asset["kind"] == "source_crop":
                _region(asset["region"], source_by_id.get(asset["source_id"]) if source_by_id else None)
            elif asset["region"] is not None:
                fail("invalid_region", "Full original image has no crop")
        assets[asset["storage_key"]] = asset
    _list(content["knowledge"], "knowledge", nonempty=True)
    items = {}; orders = set(); used_lectures = set(); used_assets = set()
    for item in content["knowledge"]:
        _fields(item, KNOWLEDGE_KEYS, "knowledge entry")
        _id(item["knowledge_id"]); _id(item["lecture_id"])
        if item["knowledge_id"] in items:
            fail("duplicate_id", "Repeated knowledge ID")
        if item["lecture_id"] not in lectures:
            fail("unknown_lecture", "Unknown knowledge lecture")
        if type(item["order"]) is not int or not 1 <= item["order"] <= 10000:
            fail("invalid_knowledge", "Order requires a positive integer")
        if (item["lecture_id"], item["order"]) in orders:
            fail("duplicate_order", "Repeated original order within lecture")
        orders.add((item["lecture_id"], item["order"])); used_lectures.add(item["lecture_id"])
        _enum(item["kind"], SUBJECT_KINDS[lectures[item["lecture_id"]]["subject"]])
        _enum(item["origin"], {"source", "foundation", "supplement"})
        for key in ("title", "statement"):
            _text(item[key], key)
        _text(item["original"], "original", nullable=item["origin"] != "source")
        _text(item["definitions"], "definitions", nullable=True)
        _notes(item["conditions"], "conditions", nonempty=True); _notes(item["unknowns"], "unknowns")
        _list(item["source_refs"], "source refs", nonempty=item["origin"] == "source")
        seen = set()
        for ref in item["source_refs"]:
            _fields(ref, {"source_id", "source_file", "source_sha256", "printed_page"}, "source reference")
            _id(ref["source_id"]); _sha(ref["source_sha256"]); _text(ref["printed_page"], "printed page", nullable=True)
            _text(ref["source_file"], "source file")
            path = PurePosixPath(ref["source_file"])
            if (path.is_absolute() or path.as_posix() != ref["source_file"] or "\\" in ref["source_file"] or
                    re.match(r"[A-Za-z]:", ref["source_file"]) or any(p in {"", ".", ".."} for p in ref["source_file"].split("/"))):
                fail("path_escape", "Source file must be a canonical relative source key")
            if ref["source_id"] in seen:
                fail("duplicate_id", "Repeated source in knowledge entry")
            seen.add(ref["source_id"])
            if source_by_id is not None:
                if ref["source_id"] not in source_by_id:
                    fail("unknown_source", "Unknown original source")
                if source_by_id[ref["source_id"]]["sha256"] != ref["source_sha256"]:
                    fail("stale_sources", "Reference names different original bytes")
                if source_by_id[ref["source_id"]]["storage_key"] != ref["source_file"]:
                    fail("stale_sources", "Source filename differs from its ledger entry")
        _list(item["corrections"], "corrections")
        for correction in item["corrections"]:
            _fields(correction, {"kind", "original", "replacement", "basis"}, "correction")
            _enum(correction["kind"], {"printing_error", "naming", "draft_correction"})
            for key in ("original", "replacement", "basis"):
                _text(correction[key], "correction " + key)
        _list(item["pages"], "pages", nonempty=True)
        substantive = set(); conclusion = []
        for page in item["pages"]:
            _list(page, "page blocks", maximum=300, nonempty=True)
            for block in page:
                _fields(block, {"kind", "content", "role", "section"}, "knowledge block")
                _enum(block["section"], SECTION_LABELS)
                if block["section"] in {"derivation", "other"} and block["role"] != "method":
                    fail("missing_explanation", "Derivation and other methods require method role")
                if block["kind"] in TEXT_KINDS - {"title", "sub", "h"}:
                    if type(block["content"]) is not str:
                        fail("invalid_knowledge", "Text block requires text")
                    text = plain_text(block["content"])
                    if text.strip():
                        substantive.add(block["section"])
                        if block["section"] == "conclusion": conclusion.append(text)
                if block["kind"] in {"diagram", "formula_image"}:
                    value = block["content"]
                    if type(value) is not dict or type(value.get("storage_key")) is not str:
                        fail("stale_asset", "Image block must name a declared resource")
                    key = value["storage_key"]
                    if key not in assets or value.get("sha256") != assets[key]["sha256"]:
                        fail("stale_asset", "Image differs from its declaration")
                    if assets[key]["kind"] != "auxiliary" and assets[key]["source_id"] not in seen:
                        fail("stale_asset", "Original diagram requires this knowledge's source reference")
                    used_assets.add(key)
        if not set(SECTION_LABELS) - {"other"} <= substantive:
            fail("missing_explanation", "All five explanatory sections need substantive text")
        if "".join(item["statement"].split()) not in "".join("".join(conclusion).split()):
            fail("missing_conclusion", "Conclusion must contain the complete checked statement")
        try:
            document_dict(_knowledge_document(content, item))
        except ExportError as exc:
            raise WorkflowError(exc.code, str(exc)) from exc
        items[item["knowledge_id"]] = item
    if used_lectures != set(lectures) or used_assets != set(assets):
        fail("unused_input", "Declare only lectures and assets used by selected knowledge")
    for item in items.values():
        _ids(item["dependencies"], items, "dependencies")
    active = set(); complete = set()
    def visit(identifier):
        if identifier in active:
            fail("dependency_cycle", "Knowledge depends on itself through a cycle")
        if identifier in complete: return
        active.add(identifier)
        for dependency in items[identifier]["dependencies"]: visit(dependency)
        active.remove(identifier); complete.add(identifier)
    for identifier in items: visit(identifier)


def compile_documents(content):
    validate_content(content)
    source = SourceRef(content["batch_id"], content_digest(content), "draft", content["revision_id"])
    originals = {k["knowledge_id"]: _knowledge_document(content, k) for k in content["knowledge"]}
    result = []
    def add(identifier, title, items, organization, stem, cover=False):
        formats = content["outputs"][organization]
        if not formats: return
        pages = []; mapping = []
        if organization == "inventory":
            for item in items:
                pages.append(tuple(_metadata(item, inventory=True))); mapping.append(item["knowledge_id"])
        else:
            if cover:
                count = (len(items) + 11) // 12
                starts = {}; position = count + 1
                for item in items:
                    starts[item["knowledge_id"]] = position
                    position += len(originals[item["knowledge_id"]].pages)
                for offset in range(0, len(items), 12):
                    rows = [["知识点", "名称", "起始页"]] + [[escape(k["knowledge_id"]), escape(k["title"]), str(starts[k["knowledge_id"]])] for k in items[offset:offset + 12]]
                    pages.append((Block("title", escape(title)), _para("学习层级", content["learner_level"]), Block("small", "来源与学科内容须分别审核；Word客户端另验。"), Block("table", [rows, [96, 300, 100]])))
                    mapping.append(None)
            for item in items:
                original = originals[item["knowledge_id"]]
                pages.extend(original.pages); mapping.extend([item["knowledge_id"]] * len(original.pages))
        document = ExportDocument(identifier, title, "knowledge_summary", tuple(pages), source)
        try: document_dict(document)
        except ExportError as exc: raise WorkflowError(exc.code, str(exc)) from exc
        result.append({"document": document, "delivery_stem": stem, "formats": list(formats), "knowledge_ids": [k["knowledge_id"] for k in items], "page_knowledge": mapping})
    add("inventory", "知识点完整清单", content["knowledge"], "inventory", "inventory")
    for item in content["knowledge"]:
        add("knowledge-" + item["knowledge_id"], item["title"], [item], "per_knowledge", "per-knowledge/" + item["lecture_id"] + "/" + item["knowledge_id"])
    for lecture in content["lectures"]:
        items = [k for k in content["knowledge"] if k["lecture_id"] == lecture["lecture_id"]]
        add("lecture-" + lecture["lecture_id"], lecture["title"], items, "per_lecture", "per-lecture/" + lecture["lecture_id"], cover=True)
    add("combined", content["title"], content["knowledge"], "combined", "combined", cover=True)
    return result


def asset_records(content, sources, source_root, asset_root):
    validate_content(content, sources); verify_sources(sources, source_root)
    by = {s["source_id"]: s for s in sources["sources"]}; records = {}
    for asset in content["assets"]:
        try: path = resolve_formula_image({"storage_key": asset["storage_key"], "sha256": asset["sha256"]}, asset_root)
        except ExportError as exc: raise WorkflowError(exc.code, str(exc)) from exc
        if asset["kind"] != "auxiliary":
            original = resolve_under(source_root, by[asset["source_id"]]["storage_key"])
            with Image.open(original) as image, Image.open(path) as derived:
                expected = image.crop(tuple(asset["region"])) if asset["region"] is not None else image
                expected = expected.convert("RGB")
                if derived.mode != "RGB" or derived.size != expected.size or derived.tobytes() != expected.tobytes():
                    fail("stale_asset", "Original diagram must match declared original RGB pixels")
        records[asset["storage_key"]] = {"sha256": digest(path.read_bytes()), "size": path.stat().st_size}
    return records


def code_records():
    root = Path(__file__).resolve().parent
    return {name: digest((root / name).read_bytes()) for name in
            ("knowledge_model.py", "contracts.py", "sources.py", "common.py")}


def _review_item(value, extra):
    _fields(value, {"status", "reviewer", "notes"} | set(extra), "review item")
    _enum(value["status"], {"pass", "fail", "not_tested"})
    _text(value["reviewer"], "reviewer", nullable=value["status"] != "pass")
    _text(value["notes"], "review notes", nullable=True)


def validate_review(review, content, recipe_sha256, document_records):
    validate_content(content)
    _fields(review, {"schema_version", "content_sha256", "recipe_sha256", "content", "subject", "pdf_visual", "word_client", "independent_reviews"}, "review")
    if review["schema_version"] != REVIEW_SCHEMA or review["content_sha256"] != content_digest(content) or review["recipe_sha256"] != recipe_sha256:
        fail("stale_review", "Review must bind current knowledge and rendering recipe")
    ids = {k["knowledge_id"] for k in content["knowledge"]}
    for key in ("content", "subject"):
        _review_item(review[key], {"knowledge_ids"}); _ids(review[key]["knowledge_ids"], ids, key, review[key]["status"] == "pass")
    _review_item(review["pdf_visual"], {"pages"})
    expected = {d["document_id"] + ":" + str(n) for d in document_records for n in range(1, d["page_count"] + 1)}
    values = review["pdf_visual"]["pages"]; _list(values, "review pages", maximum=10000)
    if any(type(n) is not str for n in values) or len(set(values)) != len(values) or not set(values) <= expected:
        fail("invalid_review", "Visual review names repeated or unknown pages")
    if review["pdf_visual"]["status"] == "pass" and set(values) != expected:
        fail("incomplete_review", "Visual pass requires every document page")
    _review_item(review["word_client"], {"platforms"}); platforms = review["word_client"]["platforms"]
    _fields(platforms, {"pc", "macos"}, "Word platforms")
    documents = {d["document_id"] for d in document_records if "docx" in d["formats"]}
    for platform in platforms.values():
        _fields(platform, {"status", "word_version", "os_version", "document_ids", "evidence_sha256"}, "Word platform")
        _enum(platform["status"], {"pass", "fail", "not_tested"})
        passed = platform["status"] == "pass"
        if passed and not documents:
            fail("incomplete_review", "Word pass requires selected DOCX documents")
        for key in ("word_version", "os_version"): _text(platform[key], key, nullable=not passed)
        _ids(platform["document_ids"], documents, "Word documents", passed)
        evidence = platform["evidence_sha256"]
        if type(evidence) is not dict or not set(evidence) <= set(platform["document_ids"]):
            fail("invalid_review", "Word evidence must name checked documents")
        for value in evidence.values(): _sha(value)
        if passed and set(evidence) != documents:
            fail("incomplete_review", "Every Word document needs client evidence")
    if review["word_client"]["status"] == "pass" and any(p["status"] != "pass" for p in platforms.values()):
        fail("incomplete_review", "Word pass requires both platforms")
    _list(review["independent_reviews"], "independent reviews")
    for item in review["independent_reviews"]:
        _review_item(item, {"knowledge_ids"}); _ids(item["knowledge_ids"], ids, "independent scope")
        if item["status"] == "pass" and not item["knowledge_ids"]:
            fail("incomplete_review", "Independent pass requires actual reviewed knowledge")
