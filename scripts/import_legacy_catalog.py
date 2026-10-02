#!/usr/bin/env python3
"""Prepare/validate private sources; DB import requires explicit target and actor."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.imports.package import load_prepared_import, prepare_legacy_import


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--inventory", type=Path, default=ROOT / "docs/source-inventory.local.json")
    prepare.add_argument("--household", required=True)
    prepare.add_argument("--dataset", required=True)
    for operation in (prepare, commands.add_parser("validate"), commands.add_parser("import")):
        operation.add_argument("--data-root", type=Path, default=ROOT / "data")
        if operation is not prepare:
            operation.add_argument("--package", type=Path, required=True)
        if operation.prog.endswith(" import"):
            operation.add_argument("--actor-id", type=int, required=True)
    args = parser.parse_args()
    if args.operation == "prepare":
        directory, prepared = prepare_legacy_import(args.inventory, args.data_root,
            household_id=args.household, dataset_key=args.dataset)
        result = {"package": str(directory), "counts": prepared.conversion.counts,
                  "source_digest": prepared.manifest["source_digest"]}
    else:
        prepared = load_prepared_import(args.package, args.data_root)
        result = {"counts": prepared.conversion.counts, "source_digest": prepared.manifest["source_digest"]}
        if args.operation == "import":
            import os
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
            import django
            django.setup()
            from django.contrib.auth import get_user_model
            from app.imports.services import import_prepared
            result = import_prepared(get_user_model().objects.get(pk=args.actor_id), prepared)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
