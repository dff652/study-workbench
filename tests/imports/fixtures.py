"""Tiny generated JPEGs and source catalogs; no personal material in tests."""
import io
from pathlib import Path

from PIL import Image

from app.imports.package import canonical, digest
from .test_catalog import GROUPS, row


def source_fixture(base):
    base = Path(base)
    source, data = base / "source", base / "private"
    source.mkdir()
    entries = [row("J1", "1", 1, "000001/000002", aux="5 比较"),
               row("W1", "2(1)-1", 3, "000002")]
    files = []
    def save(relative, raw, kind):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        files.append({"kind": kind, "path": relative, "size_bytes": len(raw), "sha256": digest(raw)})
    save("documents/v3/question_catalog.json", canonical(entries), "source_index")
    # Evaluating or running this file would fail. Only the GROUPS literal is read.
    save("documents/v3/question_catalog.py", (f"GROUPS = {GROUPS!r}\nraise RuntimeError('must never execute')\n").encode(), "source_script")
    for number in range(1, 4):
        output = io.BytesIO()
        Image.new("RGB", (4 + number, 3), (number * 60, 10, 20)).save(output, format="JPEG")
        save(f"photos/IMG_20261001_{number:06d}.jpg", output.getvalue(), "source_photo")
    inventory = {"schema_version": 1, "source_root": str(source), "created_at": "2026-10-01T10:00:00+00:00",
        "files": files, "counts": {"question_entries": 2, "parent_questions": 2, "photos": 3,
            "by_book": {"J1": 1, "W1": 1}, "by_group": {str(g): int(g in (1, 3)) for g in range(1, 7)}}}
    path = base / "inventory.local.json"
    path.write_bytes(canonical(inventory))
    return path, source, data, inventory
