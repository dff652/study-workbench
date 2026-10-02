#!/usr/bin/env python3
"""Inspect or explicitly apply household-scoped local export retention.

Dry-run is the default. This command accepts a household ID and snapshot or
ledger ID, never a filesystem path; all storage paths come from database rows
and the configured private data root.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--household", required=True, help="Exact household ID")
    parser.add_argument("--owner-id", required=True, help="Active owner account ID")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--execute", action="store_true",
        help="Apply due archive and retirement actions; requires --reason")
    action.add_argument("--archive-snapshot", type=int,
        help="Archive one snapshot by database ID; requires --reason")
    action.add_argument("--retire-snapshot", type=int,
        help="Archive and retire one snapshot by database ID; requires --reason")
    action.add_argument("--export-ledger", action="store_true",
        help="Write a controlled local retirement ledger")
    action.add_argument("--verify-ledger", metavar="LEDGER_ID",
        help="Compare the selected hash-verified local ledger with this database")
    action.add_argument("--dry-run", action="store_true",
        help="Show due actions without changing files or database (default)")
    parser.add_argument("--reason", help="Required explanation for an archive or retirement")
    return parser.parse_args()


def _json_value(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main():
    args = _arguments()
    mutating = args.execute or args.archive_snapshot is not None or args.retire_snapshot is not None
    if mutating and not args.reason:
        raise SystemExit("--reason is required for archive or retirement")
    if args.reason is not None and not args.reason.strip():
        raise SystemExit("--reason must contain non-whitespace text")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from app.persistence import services as core
    from app.operations import services

    try:
        actor = get_user_model().objects.get(pk=args.owner_id, is_active=True)
    except (get_user_model().DoesNotExist, ValueError) as exc:
        raise SystemExit("--owner-id must identify an active account") from exc

    reason = args.reason.strip() if args.reason else None
    try:
        if args.verify_ledger:
            result = services.verify_retirement_ledger(actor, args.household, ledger_id=args.verify_ledger)
        elif args.export_ledger:
            result = services.export_retirement_ledger(actor, args.household)
        elif args.archive_snapshot is not None:
            row = services.archive_export_snapshot(actor, args.household, args.archive_snapshot,
                reason=reason)
            result = {"status": "archived", "snapshot_id": row.snapshot_id,
                "archive_storage_key": row.archive_storage_key, "archive_sha256": row.archive_sha256}
        elif args.retire_snapshot is not None:
            row = services.retire_export_snapshot(actor, args.household, args.retire_snapshot,
                reason=reason)
            result = {"status": "retired", "snapshot_id": row.snapshot_id,
                "archive_storage_key": row.archive_storage_key, "archive_sha256": row.archive_sha256}
        elif args.execute:
            rows = services.retire_expired_exports(actor, args.household, reason=reason)
            result = {"status": "executed", "processed": [
                {"snapshot_id": row.snapshot_id,
                 "status": "retired" if hasattr(row, "retired_by_id") else "archived",
                 "archive_storage_key": row.archive_storage_key,
                 "archive_sha256": row.archive_sha256}
                for row in rows]}
        else:
            preview = services.retirement_candidates(actor, args.household)
            result = {"status": "dry_run", "household_id": preview["household_id"],
                "default_policy": preview["default_policy"],
                "archive_after_days": preview["archive_after_days"],
                "delete_after_days": preview["delete_after_days"],
                "candidates": [{"snapshot_id": item["snapshot"].pk,
                    "age_days": item["age_days"], "action": item["action"],
                    "archive_storage_key": item["archive_storage_key"]}
                    for item in preview["candidates"]],
                "retained_categories": preview["retained_categories"],
                "provider_retention": preview["provider_retention"]}
    except core.PersistenceError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=_json_value, indent=2))
    return 2 if args.verify_ledger and not result["matches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
