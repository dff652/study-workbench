"""Prepare a manifest for explicitly selected, unchanged source images."""
from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import warnings

from PIL import Image, UnidentifiedImageError

from . import common


DEFAULT_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_PIXELS = 40_000_000
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SELECTION_KEYS = {"batch_id", "files", "expected_counts"}
_FILE_KEYS = {"path", "book", "token", "page_order"}
_COUNT_KEYS = {"sources", "parent_questions", "entries"}
_SOURCE_KEYS = {
    "source_id", "storage_key", "book", "token", "page_order", "sha256",
    "size", "width", "height", "format",
}


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        common.fail("invalid_arguments", "Command-line arguments do not match the tool contract")


def _invalid(code: str, message: str):
    common.fail(code, message)


def _nonempty_text(value, code: str, message: str) -> str:
    if type(value) is not str or not value or value != value.strip() or any(ord(c) < 32 for c in value):
        _invalid(code, message)
    return value


def _counts(value) -> dict:
    if type(value) is not dict or set(value) - _COUNT_KEYS:
        _invalid("invalid_expected_counts", "Expected counts must contain only supported non-negative counts")
    if any(type(count) is not int or count < 0 for count in value.values()):
        _invalid("invalid_expected_counts", "Expected counts must contain only supported non-negative counts")
    return dict(value)


def _storage_key(value) -> str:
    if type(value) is not str or not value or "\\" in value or any(ord(char) < 32 for char in value):
        _invalid("invalid_source_path", "Selected paths must be canonical relative POSIX paths")
    path = PurePosixPath(value)
    if (path.is_absolute() or re.match(r"[A-Za-z]:", value) or path.as_posix() != value or
            not path.parts or any(part in ("", ".", "..") for part in value.split("/"))):
        _invalid("path_escape", "Selected paths must stay inside the configured source root")
    return value


def _validate_selection(selection) -> tuple[str, dict, list[dict]]:
    if type(selection) is not dict or set(selection) - _SELECTION_KEYS or not {"batch_id", "files"} <= set(selection):
        _invalid("invalid_selection", "Selection must contain batch_id and an explicit files array")
    batch_id = _nonempty_text(selection["batch_id"], "invalid_selection", "batch_id must be non-empty text")
    expected_counts = _counts(selection.get("expected_counts", {}))
    files = selection["files"]
    if type(files) is not list or not files:
        _invalid("invalid_selection", "Selection must explicitly list at least one source file")

    result: list[dict] = []
    seen_paths: set[str] = set()
    seen_book_tokens: set[tuple[str, str]] = set()
    for item in files:
        if type(item) is not dict or set(item) != _FILE_KEYS:
            _invalid("invalid_selection_file", "Each selected file needs exactly path, book, token, and page_order")
        key = _storage_key(item["path"])
        book = _nonempty_text(item["book"], "invalid_selection_file", "book must be non-empty text")
        token = item["token"]
        if type(token) is not str or re.fullmatch(r"[0-9]{6}", token) is None:
            _invalid("invalid_selection_file", "token must be six decimal digits")
        page_order = item["page_order"]
        if page_order is not None and (type(page_order) is not int or page_order < 1):
            _invalid("invalid_selection_file", "page_order must be a positive integer or null")
        if key in seen_paths:
            _invalid("duplicate_source_path", "A source path may be selected only once")
        identity = (book, token)
        if identity in seen_book_tokens:
            _invalid("duplicate_book_token", "A book and photo token pair may be selected only once")
        seen_paths.add(key)
        seen_book_tokens.add(identity)
        result.append({"path": key, "book": book, "token": token, "page_order": page_order})

    if expected_counts and "sources" in expected_counts and expected_counts["sources"] != len(result):
        _invalid("source_count_mismatch", "Selected source count does not match expected_counts.sources")
    return batch_id, expected_counts, result


def _decode_image(raw: bytes, *, max_pixels: int) -> tuple[int, int, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=("JPEG", "PNG")) as image:
                if image.format not in {"JPEG", "PNG"} or getattr(image, "n_frames", 1) != 1:
                    _invalid("unsupported_image", "Only single-frame JPEG and PNG sources are supported")
                width, height = image.size
                if type(width) is not int or type(height) is not int or width < 1 or height < 1:
                    _invalid("invalid_image_dimensions", "Image dimensions must be positive")
                if width * height > max_pixels:
                    _invalid("image_too_large", "A selected source exceeds the configured pixel limit")
                image.load()
                return width, height, image.format
    except common.WorkflowError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise common.WorkflowError("invalid_image", "A selected file is not a decodable single-frame JPEG or PNG") from exc


def _read_image(path, *, max_bytes: int, max_pixels: int) -> tuple[bytes, int, int, str]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    except OSError as exc:
        raise common.WorkflowError("source_read_failed", "A selected source could not be read") from exc
    if len(raw) > max_bytes:
        _invalid("source_too_large", "A selected source exceeds the configured byte limit")
    width, height, image_format = _decode_image(raw, max_pixels=max_pixels)
    return raw, width, height, image_format


def _source_id(batch_id: str, storage_key: str) -> str:
    material = common.canonical({"batch_id": batch_id, "path": storage_key})
    return "src_" + common.digest(material)[:24]


def _ensure_output_nonoverlap(source_root, output) -> None:
    common.ensure_output_outside(source_root, output)
    root = Path(source_root).resolve()
    target = Path(output).resolve()
    output_root = target if target.exists() and target.is_dir() else target.parent
    if root.is_relative_to(output_root):
        _invalid("source_output_overlap", "Output root and original source tree must not overlap")


def collect_sources(source_root, selection, output=None, max_bytes=DEFAULT_MAX_BYTES,
                    max_pixels=DEFAULT_MAX_PIXELS) -> dict:
    """Build an idempotent manifest from only the paths in a selection object or file."""
    if type(max_bytes) is not int or max_bytes < 1 or type(max_pixels) is not int or max_pixels < 1:
        _invalid("invalid_limit", "Image byte and pixel limits must be positive integers")
    root = common.root_path(source_root)
    if isinstance(selection, str) or hasattr(selection, "__fspath__"):
        selection = common.read_json(selection)
    batch_id, expected_counts, selected = _validate_selection(selection)

    sources = []
    for item in selected:
        path = common.resolve_under(root, item["path"])
        raw, width, height, image_format = _read_image(path, max_bytes=max_bytes, max_pixels=max_pixels)
        sources.append({
            "source_id": _source_id(batch_id, item["path"]),
            "storage_key": item["path"],
            "book": item["book"],
            "token": item["token"],
            "page_order": item["page_order"],
            "sha256": common.digest(raw),
            "size": len(raw),
            "width": width,
            "height": height,
            "format": image_format,
        })
    manifest = {
        "schema_version": "swf.sources.v1",
        "batch_id": batch_id,
        "expected_counts": expected_counts,
        "sources": sources,
    }
    validate_manifest(manifest)
    if output is not None:
        _ensure_output_nonoverlap(root, output)
        common.write_json(output, manifest)
    return manifest


def validate_manifest(manifest) -> bool:
    if type(manifest) is not dict or set(manifest) != {"schema_version", "batch_id", "expected_counts", "sources"}:
        _invalid("invalid_manifest", "Manifest has an invalid top-level shape")
    if manifest["schema_version"] != "swf.sources.v1":
        _invalid("invalid_manifest", "Unsupported source manifest schema_version")
    batch_id = _nonempty_text(manifest["batch_id"], "invalid_manifest", "batch_id must be non-empty text")
    expected_counts = _counts(manifest["expected_counts"])
    sources = manifest["sources"]
    if type(sources) is not list or not sources:
        _invalid("invalid_manifest", "Manifest sources must be a non-empty array")
    ids: set[str] = set()
    keys: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for source in sources:
        if type(source) is not dict or set(source) != _SOURCE_KEYS:
            _invalid("invalid_manifest_source", "Manifest source has an invalid field set")
        key = _storage_key(source["storage_key"])
        book = _nonempty_text(source["book"], "invalid_manifest_source", "book must be non-empty text")
        token = source["token"]
        if type(token) is not str or re.fullmatch(r"[0-9]{6}", token) is None:
            _invalid("invalid_manifest_source", "token must be six decimal digits")
        page_order = source["page_order"]
        if page_order is not None and (type(page_order) is not int or page_order < 1):
            _invalid("invalid_manifest_source", "page_order must be positive or unknown")
        source_id = _nonempty_text(source["source_id"], "invalid_manifest_source", "source_id must be non-empty text")
        if source_id != _source_id(batch_id, key):
            _invalid("invalid_manifest_source", "source_id does not match its stable batch and path identity")
        if source_id in ids or key in keys or (book, token) in pairs:
            _invalid("duplicate_manifest_source", "Manifest source identities must be unique")
        if type(source["sha256"]) is not str or _SHA256_RE.fullmatch(source["sha256"]) is None:
            _invalid("invalid_manifest_source", "sha256 must be a lowercase SHA-256 digest")
        for field in ("size", "width", "height"):
            if type(source[field]) is not int or source[field] < 1:
                _invalid("invalid_manifest_source", f"{field} must be a positive integer")
        if type(source["format"]) is not str or source["format"] not in {"JPEG", "PNG"}:
            _invalid("invalid_manifest_source", "format must be JPEG or PNG")
        ids.add(source_id)
        keys.add(key)
        pairs.add((book, token))
    if expected_counts and "sources" in expected_counts and expected_counts["sources"] != len(sources):
        _invalid("source_count_mismatch", "Manifest source count does not match expected_counts.sources")
    return True


def verify_sources(manifest, source_root) -> bool:
    """Verify every manifest path, byte digest, size, and decoded image metadata."""
    validate_manifest(manifest)
    root = common.root_path(source_root)
    for source in manifest["sources"]:
        path = common.resolve_under(root, source["storage_key"])
        try:
            with path.open("rb") as stream:
                raw = stream.read(source["size"] + 1)
        except OSError as exc:
            raise common.WorkflowError("source_read_failed", "A manifest source could not be read") from exc
        if len(raw) != source["size"] or common.digest(raw) != source["sha256"]:
            _invalid("source_hash_mismatch", "A source no longer matches its recorded size and SHA-256")
        width, height, image_format = _decode_image(
            raw, max_pixels=max(source["width"] * source["height"], 1)
        )
        if (width, height, image_format) != (source["width"], source["height"], source["format"]):
            _invalid("source_metadata_mismatch", "A source no longer matches its recorded image metadata")
    return True


def _main(argv=None):
    def run():
        parser = _JsonArgumentParser(description=__doc__)
        parser.add_argument("--source-root", required=True)
        parser.add_argument("--selection", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
        parser.add_argument("--max-pixels", type=int, default=DEFAULT_MAX_PIXELS)
        args = parser.parse_args(argv)
        return collect_sources(
            args.source_root, args.selection, args.output,
            max_bytes=args.max_bytes, max_pixels=args.max_pixels,
        )

    return common.cli_result(run)


if __name__ == "__main__":
    raise SystemExit(_main())
