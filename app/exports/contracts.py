"""Bounded offline export input. Content review and database authorization stay separate."""
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re

from PIL import Image


SCHEMA_VERSION = "study-workbench.print.v0.1"
GENERATOR_VERSION = "study-workbench.renderer.a2.v3"
PURPOSES = {"knowledge_summary", "classification_index", "evidence_report", "independent_practice", "parent_answers"}
TEXT_KINDS = {"title", "sub", "h", "p", "small", "key", "warn", "bridge", "erratum"}
INDEPENDENT_ROLES = {"title", "instruction", "question", "answer_space"}
ROLES = INDEPENDENT_ROLES | {"body", "answer", "method", "classification", "assessment"}
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")


class ExportError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: str
    sha256: str
    state: str = "legacy_unreviewed"
    revision_id: str | None = None


@dataclass(frozen=True, slots=True)
class Block:
    kind: str
    content: object
    role: str = "body"


@dataclass(frozen=True, slots=True)
class ExportDocument:
    document_id: str
    title: str
    purpose: str
    pages: tuple[tuple[Block, ...], ...]
    source: SourceRef


@dataclass(frozen=True, slots=True)
class FontSet:
    regular: Path
    bold: Path
    math: Path
    word_family: str = "Noto Sans CJK SC"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Markup(HTMLParser):
    """Closed markup; tags cannot load files, links, images or PDF callbacks."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        allowed = {"b": set(), "br": set(), "super": set(), "font": {"color", "backcolor"}}
        if tag not in allowed or any(key not in allowed[tag] for key, _ in attrs):
            raise ExportError("unsupported_markup", "Only b, br, super and font colors are supported")
        if len({key for key, _ in attrs}) != len(attrs):
            raise ExportError("unsupported_markup", "Duplicate markup attribute")
        for _, value in attrs:
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                raise ExportError("unsupported_markup", "Colors require six hexadecimal digits")
        if tag == "br":
            self.parts.append("\n")
        else:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ExportError("unsupported_markup", "Unbalanced markup")

    def handle_startendtag(self, tag, attrs):
        if tag != "br":
            raise ExportError("unsupported_markup", "Only br may be self-closing")
        self.handle_starttag(tag, attrs)

    def handle_data(self, value):
        self.parts.append(value)

    def handle_comment(self, value):
        raise ExportError("unsupported_markup", "Markup comments are unsupported")

    def handle_decl(self, value):
        raise ExportError("unsupported_markup", "Markup declarations are unsupported")

    def handle_pi(self, value):
        raise ExportError("unsupported_markup", "Processing instructions are unsupported")

    def unknown_decl(self, value):
        raise ExportError("unsupported_markup", "Markup declarations are unsupported")


def plain_text(value):
    parser = Markup()
    parser.feed(value)
    parser.close()
    if parser.stack:
        raise ExportError("unsupported_markup", "Unclosed markup")
    return "".join(parser.parts)


def validate_math(node, depth=0):
    if depth > 32 or not isinstance(node, (list, tuple)) or not node:
        raise ExportError("invalid_formula", "Formula nesting or shape is invalid")
    kind = node[0]
    if not isinstance(kind, str):
        raise ExportError("invalid_formula", "Formula kind must be text")
    if kind == "t":
        if len(node) != 2 or not isinstance(node[1], str) or not node[1] or len(node[1]) > 2000 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", node[1]):
            raise ExportError("invalid_formula", "Formula text must be nonempty")
    elif kind in {"f", "u", "d"}:
        if len(node) != 3:
            raise ExportError("invalid_formula", "Binary formula nodes need exactly two children")
        for child in node[1:]:
            validate_math(child, depth + 1)
    elif kind == "r":
        if len(node) < 2 or len(node) > 256:
            raise ExportError("invalid_formula", "Formula rows need 1 to 255 children")
        for child in node[1:]:
            validate_math(child, depth + 1)
    else:
        raise ExportError("unsupported_formula", "Use a source-labelled formula_image for unsupported notation")


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 20_000 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
        raise ExportError("invalid_input", "Expected bounded nonempty text")


def validate_document(document):
    if not isinstance(document, ExportDocument) or not isinstance(document.purpose, str) or document.purpose not in PURPOSES:
        raise ExportError("invalid_document", "Expected a supported document purpose")
    if not isinstance(document.document_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", document.document_id):
        raise ExportError("invalid_document", "Document ID must be a local identifier")
    _text(document.title)
    # Titles are literal text, not markup.
    if plain_text(document.title) != document.title:
        raise ExportError("invalid_document", "Title must be literal text")
    source = document.source
    if (not isinstance(source, SourceRef) or not isinstance(source.sha256, str) or not SHA_RE.fullmatch(source.sha256) or
        not isinstance(source.state, str) or source.state not in {"legacy_unreviewed", "draft", "accepted"}):
        raise ExportError("invalid_source", "Explicit source hash and review state are required")
    _text(source.source_id)
    if source.revision_id is not None:
        _text(source.revision_id)
    if source.state == "accepted" and source.revision_id is None:
        raise ExportError("invalid_source", "Accepted content requires an exact revision reference")
    if not isinstance(document.pages, tuple) or not 1 <= len(document.pages) <= 100:
        raise ExportError("invalid_document", "Expected 1 to 100 explicit pages")
    for page in document.pages:
        if not isinstance(page, tuple) or not 1 <= len(page) <= 300:
            raise ExportError("invalid_document", "Expected bounded page blocks")
        for block in page:
            if not isinstance(block, Block) or not isinstance(block.role, str) or block.role not in ROLES or not isinstance(block.kind, str):
                raise ExportError("invalid_block", "Every block needs an explicit supported role")
            if document.purpose == "independent_practice" and block.role not in INDEPENDENT_ROLES:
                raise ExportError("independent_hint", "Independent practice cannot include answers, classifications or method hints")
            kind, content = block.kind, block.content
            if kind in TEXT_KINDS:
                _text(content)
                plain_text(content)
            elif kind == "math":
                validate_math(content)
            elif kind == "space":
                if type(content) not in (int, float) or not math.isfinite(content) or not 0 <= content <= 700:
                    raise ExportError("invalid_block", "Writing space must be a finite height in points")
            elif kind == "table":
                if not isinstance(content, (list, tuple)) or len(content) != 2:
                    raise ExportError("invalid_table", "Expected rows and column widths")
                rows, widths = content
                if (not isinstance(rows, (list, tuple)) or not rows or len(rows) > 200 or
                    not isinstance(widths, (list, tuple)) or not widths or len(widths) > 20 or
                    any(type(w) not in (int, float) or not math.isfinite(w) or w <= 0 for w in widths) or sum(widths) > 502):
                    raise ExportError("invalid_table", "Table size exceeds the printable width")
                for row in rows:
                    if not isinstance(row, (list, tuple)) or len(row) != len(widths):
                        raise ExportError("invalid_table", "Every row must have the same number of columns")
                    for value in row:
                        _text(value)
                        plain_text(value)
            elif kind == "map":
                if (not isinstance(content, dict) or set(content) != {"root", "groups"} or
                    not isinstance(content["groups"], (list, tuple)) or not 1 <= len(content["groups"]) <= 6):
                    raise ExportError("invalid_map", "Map requires explicit root and 1 to 6 groups")
                labels = [content["root"]]
                for group in content["groups"]:
                    if not isinstance(group, dict) or set(group) != {"label", "detail"}:
                        raise ExportError("invalid_map", "Map groups require label and detail")
                    labels.extend((group["label"], group["detail"]))
                for lines in labels:
                    if not isinstance(lines, (list, tuple)) or not 1 <= len(lines) <= 3:
                        raise ExportError("invalid_map", "Map labels require 1 to 3 lines")
                    for value in lines:
                        _text(value)
                        if plain_text(value) != value:
                            raise ExportError("invalid_map", "Map labels are literal text")
            elif kind in {"formula_image", "diagram"}:
                diagram_fields={"vector_storage_key", "vector_sha256", "conditions", "min_label_points", "independent_safe"} if kind=="diagram" else set()
                if not isinstance(content, dict) or set(content) != {"storage_key", "sha256", "source_ref", "alt", "width_points"} | diagram_fields:
                    raise ExportError("invalid_fallback", "Formula image needs local bytes, source and alternative text")
                for name in ("storage_key", "source_ref", "alt"):
                    _text(content[name])
                if not isinstance(content["sha256"], str) or not SHA_RE.fullmatch(content["sha256"]) or type(content["width_points"]) not in (int, float) or not 1 <= content["width_points"] <= 490:
                    raise ExportError("invalid_fallback", "Invalid formula image hash or printable size")
                if kind=="diagram":
                    _text(content['vector_storage_key'])
                    if (not isinstance(content['vector_sha256'],str) or not SHA_RE.fullmatch(content['vector_sha256']) or
                        type(content['min_label_points']) not in (int,float) or not 9<=content['min_label_points']<=40 or
                        type(content['independent_safe']) is not bool or
                        not isinstance(content['conditions'],(list,tuple)) or not 1<=len(content['conditions'])<=30):
                        raise ExportError('invalid_diagram','Teaching diagrams require vector provenance, conditions and readable labels')
                    for condition in content['conditions']:_text(condition)
                    if document.purpose=='independent_practice' and not content['independent_safe']:
                        raise ExportError('independent_hint','Practice diagrams require explicit confirmation that labels and conditions contain no hints')
            else:
                raise ExportError("unsupported_block", "Unknown blocks must not disappear silently")


def document_dict(document):
    validate_document(document)
    return {"schema_version": SCHEMA_VERSION, "document_id": document.document_id, "title": document.title,
        "purpose": document.purpose, "pages": [[{"kind": b.kind, "content": b.content, "role": b.role} for b in p] for p in document.pages],
        "source": {"source_id": document.source.source_id, "sha256": document.source.sha256,
                   "state": document.source.state, "revision_id": document.source.revision_id}}


def snapshot_id(document):
    return digest(canonical(document_dict(document)))


def document_from_dict(value):
    if not isinstance(value, dict) or set(value) != {"schema_version", "document_id", "title", "purpose", "pages", "source"} or value["schema_version"] != SCHEMA_VERSION:
        raise ExportError("invalid_document", "Unsupported or extended export schema")
    if not isinstance(value["source"], dict) or set(value["source"]) != {"source_id", "sha256", "state", "revision_id"}:
        raise ExportError("invalid_source", "Source fields must be explicit")
    pages = []
    if not isinstance(value["pages"], list):
        raise ExportError("invalid_document", "Pages must be a JSON list")
    for page in value["pages"]:
        if not isinstance(page, list):
            raise ExportError("invalid_document", "Page blocks must be a JSON list")
        blocks = []
        for block in page:
            if not isinstance(block, dict) or set(block) != {"kind", "content", "role"}:
                raise ExportError("invalid_block", "Block fields must be explicit")
            blocks.append(Block(**block))
        pages.append(tuple(blocks))
    document = ExportDocument(value["document_id"], value["title"], value["purpose"], tuple(pages), SourceRef(**value["source"]))
    validate_document(document)
    return document


def resolve_formula_image(content, asset_root):
    if asset_root is None:
        raise ExportError("missing_asset_root", "A local asset root is required")
    root = Path(asset_root).resolve()
    key = Path(content["storage_key"])
    path = (root / key).resolve()
    if key.is_absolute() or ".." in key.parts or not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ExportError("invalid_fallback", "Formula image must stay inside its asset root")
    if digest(path.read_bytes()) != content["sha256"]:
        raise ExportError("fallback_hash_mismatch", "Formula image differs from its source hash")
    with Image.open(path, formats=["PNG"]) as image:
        if image.width * image.height > 4_000_000:
            raise ExportError("invalid_fallback", "Formula image exceeds the pixel limit")
        image.load()
    return path


def resolve_diagram(content, asset_root):
    """Verify both printable PNG and its retained vector source; never execute SVG."""
    path=resolve_formula_image(content,asset_root)
    root=Path(asset_root).resolve();key=Path(content['vector_storage_key']);vector=(root/key).resolve()
    if (key.is_absolute() or '..' in key.parts or not vector.is_relative_to(root) or
        not vector.is_file() or vector.stat().st_size>8*1024*1024 or vector.suffix.lower() not in {'.pdf','.svg'}):
        raise ExportError('invalid_diagram','Vector source must stay inside the asset root')
    raw=vector.read_bytes()
    if digest(raw)!=content['vector_sha256']:
        raise ExportError('diagram_hash_mismatch','Vector source differs from its recorded hash')
    return path
