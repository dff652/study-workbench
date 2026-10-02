#!/usr/bin/env python3
"""Prepare verified private v3 inputs and append PDF/Word file snapshots."""
import argparse
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.exports.contracts import (ExportError, FontSet, canonical, digest, document_from_dict, snapshot_id)
from app.exports.fonts import prepare_fonts
from app.exports.legacy import load_legacy_documents, save_legacy_inputs
from app.exports.snapshots import export_document, private_directory, write_private
from app.imports.package import checked_bytes, read_json


def load_packet(directory):
    directory = Path(directory).resolve()
    manifest = read_json((directory / "packet.json").read_bytes())
    if digest(canonical(manifest["recipe"])) != manifest["packet_id"]:
        raise ExportError("invalid_packet", "Private input recipe differs from its ID")
    for name, record in manifest["files"].items():
        checked_bytes(directory, {"path": name, **record})
    documents = tuple(document_from_dict(read_json((directory / f"legacy-{i:02d}.spec.json").read_bytes())) for i in range(1, 6))
    if [snapshot_id(doc) for doc in documents] != manifest["recipe"]["document_sha256"]:
        raise ExportError("invalid_packet", "Document specs differ from their recipe")
    fonts = FontSet(directory / "fonts/CJK-Regular.ttf", directory / "fonts/CJK-Bold.ttf", directory / "fonts/Math.ttf")
    return documents, fonts, manifest


def prepare_packet(args):
    documents, sources, provenance = load_legacy_documents(args.inventory)
    source_root = Path(provenance["source_root"]).resolve()
    for path in (args.packet_root, args.output_root):
        if path.resolve().is_relative_to(source_root):
            raise ExportError("source_output_overlap", "Outputs must stay outside the original source tree")
    cjk_notice, math_notice = ROOT / "licenses/Noto-OFL.txt", ROOT / "licenses/DejaVu-fonts.txt"
    font_sources = {"regular": args.cjk_regular, "bold": args.cjk_bold, "math": args.math_font}
    recipe = {"provenance": provenance, "document_sha256": [snapshot_id(d) for d in documents],
        "font_sources": {name: digest(path.read_bytes()) for name, path in font_sources.items()},
        "face_index": args.cjk_face_index, "fonttools_version": importlib.metadata.version("fonttools"),
        "font_preparer_sha256": digest((ROOT / "app/exports/fonts.py").read_bytes()),
        "licenses": {"cjk": digest(cjk_notice.read_bytes()), "math": digest(math_notice.read_bytes())}}
    packet_id = digest(canonical(recipe))
    root = private_directory(args.packet_root)
    destination = root / packet_id[:24]
    descriptor = os.open(root / ".prepare.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if destination.exists():
            if destination.is_symlink():
                raise ExportError("invalid_packet", "Private packet cannot be a symlink")
            loaded, fonts, manifest = load_packet(destination)
            if manifest["recipe"] != recipe:
                raise ExportError("invalid_packet", "Private packet refers to a different recipe")
            return destination, loaded, fonts, manifest
        temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=root))
        try:
            save_legacy_inputs(temporary, documents, sources, provenance)
            _, profile = prepare_fonts(documents, temporary / "fonts", regular_source=args.cjk_regular,
                bold_source=args.cjk_bold, math_source=args.math_font, cjk_notice=cjk_notice,
                math_notice=math_notice, face_index=args.cjk_face_index)
            files = {str(p.relative_to(temporary)): {"sha256": digest(p.read_bytes()), "size_bytes": p.stat().st_size}
                     for p in temporary.rglob("*") if p.is_file()}
            manifest = {"packet_id": packet_id, "recipe": recipe, "font_profile": profile, "files": files}
            write_private(temporary / "packet.json", manifest)
            load_packet(temporary)
            temporary.rename(destination)
            loaded, fonts, manifest = load_packet(destination)
            return destination, loaded, fonts, manifest
        except BaseException:
            shutil.rmtree(temporary)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=ROOT / "docs/source-inventory.local.json")
    parser.add_argument("--packet-root", type=Path, default=ROOT / "data/export-inputs/v3")
    parser.add_argument("--output-root", type=Path, default=ROOT / "exports/a2-v3")
    parser.add_argument("--cjk-regular", type=Path, required=True)
    parser.add_argument("--cjk-bold", type=Path, required=True)
    parser.add_argument("--math-font", type=Path, required=True)
    parser.add_argument("--cjk-face-index", type=int, default=2)
    args = parser.parse_args()
    packet, documents, fonts, manifest = prepare_packet(args)
    exported = []
    for document in documents:
        directory, result = export_document(document, args.output_root, fonts, manifest["font_profile"], asset_root=packet)
        exported.append({"document_id": document.document_id, "directory": str(directory), "export_id": result["export_id"],
            "pages": result["page_count"], "word_equations": result["word_equations"], "already_exported": result["already_exported"]})
    print(json.dumps({"packet": str(packet), "outputs": exported}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
