"""Explicit companion content, provenance, organization and review contracts."""
from __future__ import annotations

from html import escape
from pathlib import Path, PurePosixPath
import re

from PIL import Image

from .sources import validate_manifest, verify_sources
from .contracts import (
    Block, ExportDocument, ExportError, SourceRef, TEXT_KINDS,
    document_from_dict, plain_text, resolve_formula_image,
)
from .common import canonical, digest, fail, resolve_under, WorkflowError


SCHEMA_VERSION = "swf.solution-companion.v1"
REVIEW_SCHEMA = "swf.solution-review.v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ROOT = Path(__file__).resolve().parent.parent
_CONTENT_KEYS = {
    "schema_version", "batch_id", "revision_id", "title", "sources_sha256",
    "lectures", "questions", "assets", "outputs", "unknowns",
}
_QUESTION_KEYS = {
    "question_id", "lecture_id", "display_number", "title", "statement",
    "source_refs", "parts", "pages", "unknowns", "corrections",
}


def _fields(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        fail("invalid_companion", f"{name} fields must be explicit")


def _text(value, name, nullable=False):
    if nullable and value is None:
        return
    if (type(value) is not str or not value.strip() or len(value) > 20_000 or
            re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value)):
        fail("invalid_companion", f"{name} needs bounded nonempty text")


def _identifier(value, name):
    if type(value) is not str or not _ID.fullmatch(value):
        fail("invalid_companion", f"{name} needs a local identifier")


def _sha(value, name):
    if type(value) is not str or not _SHA.fullmatch(value):
        fail("invalid_companion", f"{name} needs SHA-256")


def _enum(value, allowed, name):
    if type(value) is not str or value not in allowed:
        fail("invalid_companion", f"{name} needs an explicit supported value")


def _list(value, name, maximum=100, nonempty=False):
    if type(value) is not list or len(value) > maximum or (nonempty and not value):
        fail("invalid_companion", f"{name} needs a bounded array")


def _notes(value, name):
    _list(value, name)
    for item in value:
        _text(item, name)


def _key(value):
    if (type(value) is not str or not value or "\\" in value or
            any(ord(c) < 32 for c in value) or re.match(r"[A-Za-z]:", value)):
        fail("path_escape", "Resource needs a canonical relative POSIX key")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(p in {"", ".", ".."} for p in value.split("/")):
        fail("path_escape", "Resource must stay under its asset root")
    if path.suffix.lower() != ".png":
        fail("invalid_companion", "Companion resources must be PNG")


def _region(value, source=None):
    if value is None:
        return
    if (type(value) is not list or len(value) != 4 or any(type(n) is not int for n in value) or
            not 0 <= value[0] < value[2] or not 0 <= value[1] < value[3]):
        fail("invalid_region", "Region needs four valid original-pixel coordinates")
    if source and (value[2] > source["width"] or value[3] > source["height"]):
        fail("invalid_region", "Region exceeds the original source")


def content_digest(content):
    return digest(canonical(content))


def _question_document(content, question):
    value = {
        "schema_version": "swf.print.v1", "document_id": "question-" + question["question_id"],
        "title": question["title"], "purpose": "parent_answers", "pages": question["pages"],
        "source": {"source_id": content["batch_id"], "sha256": content_digest(content),
                   "state": "draft", "revision_id": content["revision_id"]},
    }
    try:
        return document_from_dict(value)
    except ExportError as exc:
        raise WorkflowError(exc.code, str(exc)) from exc


def _page_text(document, role=None):
    parts = []
    for page in document.pages:
        for block in page:
            if role is not None and block.role != role:
                continue
            if block.kind in TEXT_KINDS:
                parts.append(plain_text(block.content))
            elif block.kind == "table":
                parts.extend(plain_text(cell) for row in block.content[0] for cell in row)
    return "".join("".join(parts).split())


def leaf_parts(question):
    parents = {p["parent_id"] for p in question["parts"] if p["parent_id"] is not None}
    return [p for p in question["parts"] if p["part_id"] not in parents]


def validate_content(content, sources=None):
    _fields(content, _CONTENT_KEYS, "content")
    if content["schema_version"] != SCHEMA_VERSION:
        fail("invalid_companion", "Unsupported companion schema")
    for key in ("batch_id", "revision_id"):
        _identifier(content[key], key)
    _text(content["title"], "title")
    _sha(content["sources_sha256"], "sources_sha256")
    _notes(content["unknowns"], "unknowns")
    source_by_id = None
    if sources is not None:
        validate_manifest(sources)
        if sources["batch_id"] != content["batch_id"] or digest(canonical(sources)) != content["sources_sha256"]:
            fail("stale_input", "Content does not match the selected sources")
        source_by_id = {s["source_id"]: s for s in sources["sources"]}
    _fields(content["outputs"], {"per_question", "per_lecture", "combined"}, "outputs")
    for formats in content["outputs"].values():
        _list(formats, "formats", maximum=2)
        if any(type(f) is not str or f not in {"pdf", "docx"} for f in formats) or len(set(formats)) != len(formats):
            fail("invalid_companion", "Select pdf/docx once per organization")
    if not any(content["outputs"].values()):
        fail("invalid_companion", "At least one organization must be selected")
    _list(content["lectures"], "lectures", nonempty=True)
    lecture_ids = set()
    for lecture in content["lectures"]:
        _fields(lecture, {"lecture_id", "title"}, "lecture")
        _identifier(lecture["lecture_id"], "lecture_id")
        _text(lecture["title"], "lecture title")
        if lecture["lecture_id"] in lecture_ids:
            fail("duplicate_identity", "Lecture IDs must be unique")
        lecture_ids.add(lecture["lecture_id"])
    _list(content["assets"], "assets", maximum=1000)
    assets = {}
    for asset in content["assets"]:
        _fields(asset, {"storage_key", "sha256", "kind", "source_id", "region", "basis"}, "asset")
        _key(asset["storage_key"])
        _sha(asset["sha256"], "asset sha256")
        _text(asset["basis"], "asset basis")
        if asset["storage_key"] in assets:
            fail("duplicate_identity", "Resource keys must be unique")
        _enum(asset["kind"], {"source_crop", "source_image", "auxiliary"}, "asset kind")
        if asset["kind"] == "auxiliary":
            if asset["source_id"] is not None or asset["region"] is not None:
                fail("invalid_companion", "Auxiliary construction must not masquerade as an original crop")
        else:
            _text(asset["source_id"], "asset source_id")
            if source_by_id is not None and asset["source_id"] not in source_by_id:
                fail("missing_source", "Resource source is not selected")
            _region(asset["region"], source_by_id.get(asset["source_id"]) if source_by_id else None)
            if (asset["kind"] == "source_crop") != (asset["region"] is not None):
                fail("invalid_region", "Source crop needs its real region; whole image has no region")
        assets[asset["storage_key"]] = asset
    _list(content["questions"], "questions", nonempty=True)
    question_ids, part_ids, numbers, used_assets, used_lectures = set(), set(), set(), set(), set()
    for question in content["questions"]:
        _fields(question, _QUESTION_KEYS, "question")
        _identifier(question["question_id"], "question_id")
        _identifier(question["lecture_id"], "lecture_id")
        for key in ("display_number", "title"):
            _text(question[key], key)
        if question["lecture_id"] not in lecture_ids:
            fail("missing_lecture", "Question names an undeclared lecture")
        number = (question["lecture_id"], question["display_number"])
        if question["question_id"] in question_ids or number in numbers:
            fail("duplicate_identity", "Question IDs and lecture-local numbers must be unique")
        question_ids.add(question["question_id"]); numbers.add(number); used_lectures.add(question["lecture_id"])
        _notes(question["unknowns"], "question unknowns")
        statement = question["statement"]
        _fields(statement, {"text", "status"}, "statement")
        _text(statement["text"], "statement text", nullable=True)
        _enum(statement["status"], {"complete", "partial", "unknown"}, "statement status")
        if statement["status"] != "complete" and not question["unknowns"]:
            fail("missing_unknown", "Incomplete statement needs an explicit gap")
        _list(question["source_refs"], "source_refs", nonempty=True)
        for sequence, ref in enumerate(question["source_refs"], 1):
            _fields(ref, {"source_id", "sequence", "region"}, "source reference")
            _text(ref["source_id"], "source_id")
            if type(ref["sequence"]) is not int or ref["sequence"] != sequence:
                fail("invalid_sequence", "Cross-page sources must keep their explicit order")
            if source_by_id is not None and ref["source_id"] not in source_by_id:
                fail("missing_source", "Question source is not selected")
            _region(ref["region"], source_by_id.get(ref["source_id"]) if source_by_id else None)
        _list(question["parts"], "parts", nonempty=True)
        local_parts = {}
        for part in question["parts"]:
            _fields(part, {"part_id", "parent_id", "label", "statement", "answer", "unit"}, "part")
            _identifier(part["part_id"], "part_id")
            if part["part_id"] in part_ids:
                fail("duplicate_identity", "Part IDs must be unique across this batch")
            part_ids.add(part["part_id"]); local_parts[part["part_id"]] = part
            if part["parent_id"] is not None:
                _identifier(part["parent_id"], "parent_id")
            _text(part["label"], "part label")
            for key in ("statement", "answer", "unit"):
                _text(part[key], "part " + key, nullable=True)
        for part in question["parts"]:
            seen = {part["part_id"]}; parent = part["parent_id"]
            while parent is not None:
                if parent not in local_parts or parent in seen:
                    fail("invalid_parent", "Part parent must belong to this question without cycles")
                seen.add(parent); parent = local_parts[parent]["parent_id"]
        leaves = leaf_parts(question)
        for part in question["parts"]:
            if part not in leaves and part["answer"] is not None:
                fail("invalid_parent", "Parent containers must not duplicate leaf answers")
        if any(p["answer"] is None for p in leaves) and not question["unknowns"]:
            fail("missing_unknown", "Unknown answer needs a recorded gap")
        _list(question["corrections"], "corrections")
        for correction in question["corrections"]:
            _fields(correction, {"kind", "original", "replacement", "basis"}, "correction")
            _enum(correction["kind"], {"printing_error", "naming", "draft_correction"}, "correction kind")
            for key in ("original", "replacement", "basis"):
                _text(correction[key], "correction " + key)
        document = _question_document(content, question)
        roles = {b.role for page in document.pages for b in page}
        if not {"question", "method"} <= roles or (any(p["answer"] is not None for p in leaves) and "answer" not in roles):
            fail("missing_question_content", "Question pages need question, method and applicable answer roles")
        corpus = _page_text(document)
        expected = [statement["text"], *(p["statement"] for p in question["parts"])]
        if any(value is not None and "".join(value.split()) not in corpus for value in expected):
            fail("missing_question_content", "Complete transcriptions must be present in question pages")
        for part in leaves:
            if part["answer"] is None:
                continue
            required = [part["label"], part["answer"]]
            if part["unit"] is not None:
                required.append(part["unit"])
            answer_blocks = ["".join(plain_text(b.content).split()) for page in document.pages
                             for b in page if b.role == "answer" and b.kind in TEXT_KINDS]
            if not any(all("".join(value.split()) in text for value in required) for text in answer_blocks):
                fail("missing_answer", "Each known leaf needs its label, answer and known unit in an answer text block")
        original_picture = False
        for page in document.pages:
            for block in page:
                if block.kind not in {"diagram", "formula_image"}:
                    continue
                key = block.content["storage_key"]
                if key not in assets or block.content["sha256"] != assets[key]["sha256"]:
                    fail("stale_asset", "Block must name its declared resource bytes")
                asset = assets[key]; used_assets.add(key)
                if asset["kind"] != "auxiliary":
                    if not any(ref["source_id"] == asset["source_id"] and ref["region"] == asset["region"] for ref in question["source_refs"]):
                        fail("stale_asset", "Source image/crop must match this question's source reference")
                    original_picture |= block.role == "question"
        if statement["status"] == "complete" and statement["text"] is None and not original_picture:
            fail("missing_question_content", "Complete image-only statement needs a source-labelled question image")
    if used_assets != set(assets) or used_lectures != lecture_ids:
        fail("unused_input", "Declare only lectures and resources actually used by selected questions")
    if sources is not None:
        counts = sources["expected_counts"]
        observed = {"parent_questions": len(content["questions"]),
                    "entries": sum(len(leaf_parts(q)) for q in content["questions"])}
        for key, count in observed.items():
            if counts.get(key) is not None and counts[key] != count:
                fail("coverage_mismatch", "Content differs from explicitly selected " + key)


def compile_documents(content):
    validate_content(content)
    source = SourceRef(content["batch_id"], content_digest(content), "draft", content["revision_id"])
    question_documents = {q["question_id"]: _question_document(content, q) for q in content["questions"]}
    result = []

    def add(identifier, title, questions, organization, stem, cover=False):
        formats = content["outputs"][organization]
        if not formats:
            return
        pages, mapping = [], []
        if cover:
            for offset in range(0, len(questions), 12):
                combined = organization == "combined"
                rows = [["讲次／题号" if combined else "原题号", "解题主线", "答案"]]
                for q in questions[offset:offset + 12]:
                    answer = "; ".join(p["label"] + ": " + (p["answer"] or "待核实") + (" " + p["unit"] if p["unit"] else "") for p in leaf_parts(q))
                    number = q["lecture_id"] + "/" + q["display_number"] if combined else q["display_number"]
                    rows.append([escape(number), escape(q["title"]), escape(answer)])
                widths = [80, 210, 206] if combined else [48, 230, 218]
                pages.append((Block("title", escape(title)), Block("small", "逐题解析含答案；不同组织版本正文重复。"), Block("table", [rows, widths])))
                mapping.append(None)
        for q in questions:
            original = question_documents[q["question_id"]]
            pages.extend(original.pages); mapping.extend([q["question_id"]] * len(original.pages))
        document = ExportDocument(identifier, title, "parent_answers", tuple(pages), source)
        # Validate aggregate limits and title markup before any output is created.
        from .contracts import document_dict
        try:
            document_dict(document)
        except ExportError as exc:
            raise WorkflowError(exc.code, str(exc)) from exc
        result.append({"document": document, "delivery_stem": stem, "formats": list(formats),
                       "question_ids": [q["question_id"] for q in questions], "page_questions": mapping})

    for q in content["questions"]:
        add("question-" + q["question_id"], q["title"], [q], "per_question",
            "per-question/" + q["lecture_id"] + "/" + q["question_id"])
    for lecture in content["lectures"]:
        subset = [q for q in content["questions"] if q["lecture_id"] == lecture["lecture_id"]]
        add("lecture-" + lecture["lecture_id"], lecture["title"], subset, "per_lecture",
            "per-lecture/" + lecture["lecture_id"], cover=True)
    add("combined", content["title"], content["questions"], "combined", "combined", cover=True)
    return result


def asset_records(content, sources, source_root, asset_root):
    validate_content(content, sources)
    verify_sources(sources, source_root)
    source_by_id = {s["source_id"]: s for s in sources["sources"]}
    records = {}
    for asset in content["assets"]:
        try:
            path = resolve_formula_image({"storage_key": asset["storage_key"], "sha256": asset["sha256"]}, asset_root)
        except ExportError as exc:
            raise WorkflowError(exc.code, str(exc)) from exc
        if asset["kind"] != "auxiliary":
            original = resolve_under(source_root, source_by_id[asset["source_id"]]["storage_key"])
            with Image.open(original) as image, Image.open(path) as derived:
                expected = image.crop(tuple(asset["region"])) if asset["region"] is not None else image
                expected = expected.convert("RGB")
                if derived.mode != "RGB" or derived.size != expected.size or derived.tobytes() != expected.tobytes():
                    fail("stale_asset", "Source resource differs from original RGB pixels; v1 has no implicit transforms")
        records[asset["storage_key"]] = {"sha256": digest(path.read_bytes()), "size": path.stat().st_size}
    return records


def code_records():
    # Workbench keeps the upstream contract/compiler; rendering is native.
    root = Path(__file__).resolve().parent
    return {name: digest((root / name).read_bytes())
            for name in ("model.py", "contracts.py", "sources.py", "common.py")}


def _review_item(item, keys):
    _fields(item, keys | {"status", "reviewer", "notes"}, "review item")
    _enum(item["status"], {"pass", "fail", "not_tested"}, "review status")
    _text(item["notes"], "review notes")
    _text(item["reviewer"], "reviewer", nullable=True)
    if item["status"] == "pass" and item["reviewer"] is None:
        fail("invalid_review", "Pass requires an actual reviewer")


def _scope(item, question_ids, part_ids, complete=False):
    for key, allowed in (("question_ids", question_ids), ("part_ids", part_ids)):
        _list(item[key], key, maximum=10_000)
        if any(type(v) is not str for v in item[key]) or len(set(item[key])) != len(item[key]) or not set(item[key]) <= allowed:
            fail("invalid_review", "Review scope must name existing questions and leaf answers once")
        if complete and set(item[key]) != allowed:
            fail("incomplete_review", "Pass must cover every selected question and leaf answer")


def validate_review(review, content, recipe_sha256, document_records):
    validate_content(content)
    _fields(review, {"schema_version", "content_sha256", "recipe_sha256", "content", "math", "pdf_visual", "word_client", "independent_reviews"}, "review")
    if review["schema_version"] != REVIEW_SCHEMA or review["content_sha256"] != content_digest(content) or review["recipe_sha256"] != recipe_sha256:
        fail("stale_review", "Review must match current content and render recipe")
    questions = {q["question_id"] for q in content["questions"]}
    parts = {p["part_id"] for q in content["questions"] for p in leaf_parts(q)}
    part_questions = {p["part_id"]: q["question_id"] for q in content["questions"] for p in leaf_parts(q)}
    for key in ("content", "math"):
        _review_item(review[key], {"question_ids", "part_ids"})
        _scope(review[key], questions, parts, complete=review[key]["status"] == "pass")
    visual = review["pdf_visual"]
    _review_item(visual, {"pages"})
    pages = {f"{d['document_id']}:{n}" for d in document_records for n in range(1, d["page_count"] + 1)}
    _list(visual["pages"], "visual pages", maximum=30_000)
    if any(type(p) is not str for p in visual["pages"]) or len(set(visual["pages"])) != len(visual["pages"]) or not set(visual["pages"]) <= pages:
        fail("invalid_review", "Visual evidence must name actual pages")
    if visual["status"] == "pass" and set(visual["pages"]) != pages:
        fail("incomplete_review", "Visual pass must cover all rendered pages")
    word = review["word_client"]
    _review_item(word, {"platforms"})
    _fields(word["platforms"], {"PC", "macOS"}, "Word platforms")
    documents = {d["document_id"] for d in document_records}
    for platform in word["platforms"].values():
        _fields(platform, {"status", "word_version", "os_version", "document_ids", "evidence_sha256"}, "Word platform")
        _enum(platform["status"], {"pass", "fail", "not_tested"}, "Word platform status")
        for key in ("word_version", "os_version"):
            _text(platform[key], key, nullable=True)
        _list(platform["document_ids"], "Word document IDs", maximum=1000)
        ids = platform["document_ids"]
        if any(type(v) is not str for v in ids) or len(set(ids)) != len(ids) or not set(ids) <= documents:
            fail("invalid_review", "Word scope must name existing documents")
        evidence = platform["evidence_sha256"]
        if type(evidence) is not dict or not set(evidence) <= set(ids):
            fail("invalid_review", "Word evidence must correspond to checked documents")
        for value in evidence.values():
            _sha(value, "Word evidence")
        if platform["status"] == "pass" and (set(ids) != documents or set(evidence) != documents or platform["word_version"] is None or platform["os_version"] is None):
            fail("incomplete_review", "Word pass needs both versions and every document's evidence")
    statuses = {p["status"] for p in word["platforms"].values()}
    expected = "fail" if "fail" in statuses else ("pass" if statuses == {"pass"} else "not_tested")
    if word["status"] != expected:
        fail("invalid_review", "Word aggregate must preserve both actual platform states")
    _list(review["independent_reviews"], "independent reviews")
    for item in review["independent_reviews"]:
        _review_item(item, {"question_ids", "part_ids"})
        _scope(item, questions, parts)
        if item["status"] == "pass" and not item["question_ids"]:
            fail("incomplete_review", "Independent pass must name at least one reviewed question")
        if any(part_questions[pid] not in item["question_ids"] for pid in item["part_ids"]):
            fail("invalid_review", "Independent leaf scope must belong to its named questions")
