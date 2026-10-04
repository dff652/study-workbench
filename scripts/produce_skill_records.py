#!/usr/bin/env python3
"""Produce complete companion records from explicit typed material content."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.exports.contracts import canonical, digest
from app.workflows.content_schema import records
from scripts.prepare_skill_exchange import read


def produce(draft, sources):
    if (not isinstance(draft, dict) or set(draft) != {"schema_version", "proposal", "sources", "original_number"}
            or draft["schema_version"] != "swb.material-draft.v1" or not isinstance(draft["original_number"], str)
            or len(draft["original_number"]) > 80 or not isinstance(sources, dict)
            or sources.get("schema_version") != "swf.sources.v1"
            or not isinstance(sources.get("sources"), list)):
        raise ValueError("请提供明确的内容草稿、来源及原题号。")
    original = {row["source_id"]: row for row in sources["sources"]}
    if len(original) != len(sources["sources"]):
        raise ValueError("来源身份重复。")
    refs = draft["sources"]
    if not isinstance(refs, list) or not 1 <= len(refs) <= 30:
        raise ValueError("请提供明确来源区域。")
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"source_id", "bbox"}:
            raise ValueError("来源区域字段无效。")
        source = original.get(ref["source_id"])
        box = ref["bbox"]
        if (source is None or not isinstance(box, list) or len(box) != 4 or any(type(n) is not int for n in box)
                or not 0 <= box[0] < box[2] <= source["width"] or not 0 <= box[1] < box[3] <= source["height"]):
            raise ValueError("坐标须为明确原图整数区域。")
    return records(draft["proposal"], refs, draft["original_number"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("draft", "sources", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        value = produce(read(args.draft), read(args.sources))
        raw = canonical(value)
        if len(raw) > 1024 * 1024 or not args.output.parent.is_dir() or args.output.parent.stat().st_mode & 0o077:
            raise ValueError("输出目录须为 0700，记录最多 1 MiB。")
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        import json
        print(json.dumps({"sha256": digest(raw), "record_count": len(value["records"]),
                          "database_opened": False, "review_state": "draft"}))
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        print('{"error":"records_rejected"}', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
