#!/usr/bin/env python3
"""Merge explicit skill records and selected page mappings, without opening a DB."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.exports.contracts import canonical, digest, ExportError
from app.workflows.skill_packet import validate_packet
from app.workflows.assets import validate_records


def read(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("单个输入超过 1 MiB。")
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value: raise ValueError("输入包含重复键。")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非有限数")))


def prepare(sources, catalog, packet, records, mapping, ledger=None):
    if not isinstance(records, dict): raise ValueError("伴随记录须为对象。")
    is_v2 = records.get("schema_version") == "swb.skill-records.v2"
    allowed = {"schema_version", "records", "assets"} if is_v2 else {"schema_version", "records"}
    if set(records) != allowed: raise ValueError("伴随记录字段不符。")
    validate_records(records["records"], records.get("assets", {}))
    validate_packet(packet, sources, catalog, records["records"], records.get("assets", {}))
    if (sources.get("schema_version") != "swf.sources.v1" or catalog.get("schema_version") != "swf.catalog.v1"
            or records.get("schema_version") not in {"swb.skill-records.v1", "swb.skill-records.v2"}
            or mapping.get("schema_version") != "swb.skill-page-map.v1" or set(mapping) != {"schema_version", "pages"}):
        raise ValueError("输入格式不符。")
    index = {row["source_id"]: row for row in sources["sources"]}
    if len(index) != len(sources["sources"]): raise ValueError("来源身份重复。")
    rows, seen = [], set()
    for row in mapping["pages"]:
        if set(row) != {"source_id", "page_id", "sha256"} or row["source_id"] in seen:
            raise ValueError("映射字段或身份无效。")
        original = index.get(row["source_id"])
        if not original or original["sha256"] != row["sha256"]:
            raise ValueError("页映射哈希与 skill 原图清单不符。")
        seen.add(row["source_id"])
        rows.append({"id": row["source_id"], "page_id": row["page_id"], "sha256": row["sha256"]})
    if seen != set(index):
        raise ValueError("每个来源都需要明确映射；不能丢弃未知辅助图。")
    value = {"schema_version": "swb.skill-import.v2" if is_v2 else "swb.skill-import.v1", "sources": rows, "records": records["records"],
             "packet": packet, "catalog": catalog, "ledger": ledger,
             "tool_inputs": {"sources": sources, "mapping": mapping, "record_sha256": digest(canonical(records))}}
    if is_v2: value["assets"] = records["assets"]
    if len(canonical(value)) > 1024 * 1024: raise ValueError("完整交换包超过 1 MiB，请拆分批次。")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "catalog", "packet", "records", "mapping", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()
    try:
        value = prepare(*(read(getattr(args, name)) for name in ("sources", "catalog", "packet", "records", "mapping")),
                        ledger=read(args.ledger) if args.ledger else None)
        target = args.output.absolute()
        if not target.parent.is_dir() or target.parent.stat().st_mode & 0o077:
            raise ValueError("输出父目录必须预先建为私有目录（0700）。")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(value)); handle.flush(); os.fsync(handle.fileno())
        print(json.dumps({"output": str(target), "sha256": digest(canonical(value)),
            "record_count": len(value["records"]), "database_opened": False, "review_state": "draft"}))
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as exc:
        print(json.dumps({"error": "exchange_rejected", "message": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
