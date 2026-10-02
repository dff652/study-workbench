"""Private append-only file snapshots; no database publication or archive claims."""
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import tempfile

from .contracts import (ExportError, GENERATOR_VERSION, SCHEMA_VERSION, canonical, digest,
    document_dict, snapshot_id, validate_document)


DEPENDENCIES = ("reportlab", "python-docx", "fonttools", "lxml", "Pillow", "charset-normalizer")


def private_directory(path):
    path = Path(path).resolve()
    missing, cursor = [], path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
    if not path.is_dir() or path.stat().st_mode & 0o077:
        raise ExportError("unsafe_output_root", "Output directories must have mode 0700")
    return path


def write_private(path, value):
    raw = value if isinstance(value, bytes) else canonical(value)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def runtime_fingerprint():
    module_dir = Path(__file__).parent
    return {"generator_version": GENERATOR_VERSION,
        "dependencies": {name: importlib.metadata.version(name) for name in DEPENDENCIES},
        "code_sha256": {path.name: digest(path.read_bytes()) for path in sorted(module_dir.glob("*.py"))}}


def verify_snapshot(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "snapshot.json").read_text())
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ExportError("invalid_snapshot", "Unknown print snapshot schema")
    if digest(canonical(manifest["inputs"])) != manifest["export_id"]:
        raise ExportError("invalid_snapshot", "Snapshot identity does not match its inputs")
    document = manifest["inputs"]["document"]
    if (manifest["snapshot_id"] != digest(canonical(document)) or
        manifest["page_count"] != len(document["pages"]) or
        manifest["word_equations"] != sum(b["kind"] == "math" for p in document["pages"] for b in p) or
        set(manifest["files"]) != {"document.pdf", "document.docx", "content.json"}):
        raise ExportError("invalid_snapshot", "Snapshot artifacts or metadata are incomplete")
    for name, record in manifest["files"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ExportError("invalid_snapshot", "Snapshot file is missing or leaves its directory")
        raw = path.read_bytes()
        if digest(raw) != record["sha256"] or len(raw) != record["size_bytes"]:
            raise ExportError("snapshot_hash_mismatch", "Snapshot files were modified")
    if (directory / "content.json").read_bytes() != canonical(document):
        raise ExportError("invalid_snapshot", "Saved content differs from its declared snapshot")
    return manifest


def export_document(document, output_root, fonts, font_manifest, *, asset_root=None, forbidden_export_ids=()):
    """An unchanged input reuses verified artifacts; corrupted outputs never overwrite."""
    from .renderer import render_document
    validate_document(document)
    for path, name in ((fonts.regular, "CJK-Regular.ttf"), (fonts.bold, "CJK-Bold.ttf"), (fonts.math, "Math.ttf")):
        if digest(Path(path).read_bytes()) != font_manifest["files"].get(name):
            raise ExportError("font_hash_mismatch", "Configured fonts differ from their recorded profile")
    if fonts.word_family != font_manifest["word_family"]:
        raise ExportError("font_hash_mismatch", "Word font family differs from the font profile")
    runtime = runtime_fingerprint()
    # Blocks may contain lists/dicts despite the frozen outer records. Detach the
    # snapshot before rendering so a changed payload cannot mutate our evidence.
    source = json.loads(canonical(document_dict(document)))
    inputs = {"document": source, "runtime": runtime, "font_profile": font_manifest}
    export_id = digest(canonical(inputs))
    if export_id in forbidden_export_ids:
        raise ExportError("snapshot_retired", "此导出已退役，不能重新创建原快照；请调整内容或标题后另行导出。")
    root = private_directory(output_root)
    destination = root / f"{document.document_id}-{export_id[:24]}"
    lock_fd = os.open(root / ".export.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if destination.exists():
            if destination.is_symlink():
                raise ExportError("snapshot_conflict", "Snapshot directory cannot be a symlink")
            previous = verify_snapshot(destination)
            if previous["export_id"] != export_id or previous["inputs"] != inputs:
                raise ExportError("snapshot_conflict", "Existing export uses different inputs")
            return destination, {**previous, "already_exported": True}
        temporary = Path(tempfile.mkdtemp(prefix=".exporting-", dir=root))
        try:
            result = render_document(document, temporary, fonts, asset_root=asset_root)
            if snapshot_id(document) != digest(canonical(source)):
                raise ExportError("input_changed", "Input document changed while rendering")
            write_private(temporary / "content.json", source)
            files = {}
            for path in sorted(temporary.rglob("*")):
                if path.is_dir():
                    path.chmod(0o700)
                    continue
                path.chmod(0o600)
                files[str(path.relative_to(temporary))] = {"sha256": digest(path.read_bytes()), "size_bytes": path.stat().st_size}
            manifest = {"schema_version": SCHEMA_VERSION, "export_id": export_id, "snapshot_id": snapshot_id(document),
                "inputs": inputs, "page_count": result["page_count"], "word_equations": result["word_equations"],
                "files": files, "archive_complete": False}
            write_private(temporary / "snapshot.json", manifest)
            verify_snapshot(temporary)
            temporary.rename(destination)
            return destination, {**manifest, "already_exported": False}
        except BaseException:
            shutil.rmtree(temporary)
            raise
