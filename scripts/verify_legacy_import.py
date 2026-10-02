#!/usr/bin/env python3
"""Real-catalog acceptance, callable only inside the owned temporary PG runner."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    # Refuse caller databases. The parent runner also creates and verifies this
    # marker on its private socket directory and strips all inherited SWB vars.
    socket = Path(os.environ["SWB_DB_HOST"])
    owner = os.environ.get("SWB_TEST_OWNER", "")
    if not owner or (socket.parent / "owner").read_text() != owner:
        raise RuntimeError("Real import acceptance requires an owned disposable database")
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from app.imports.models import LegacyImportBatch, LegacyIndexEntry
    from app.imports.package import canonical, checked_bytes, load_prepared_import
    from app.persistence.adapter import split_bundle
    from app.imports.services import import_prepared, legacy_trace
    from app.persistence.models import EntityRecord, ImageRecord, RequestReceipt, RevisionRecord
    from app.persistence.services import create_household, read_snapshot_bundle

    prepared = load_prepared_import(args.package, args.data_root)
    manifest, conversion = prepared.manifest, prepared.conversion
    actor = get_user_model().objects.create_user(username="temporary-real-index-verifier")
    create_household(actor, manifest["household_id"])
    first, second = import_prepared(actor, prepared), import_prepared(actor, prepared)
    assert not first["already_imported"] and second["already_imported"]
    assert sum(second["added"].values()) == 0 and first["batch_id"] == second["batch_id"]
    assert LegacyImportBatch.objects.count() == RequestReceipt.objects.count() == 1
    assert LegacyIndexEntry.objects.count() == 81
    assert ImageRecord.objects.count() == 23
    assert EntityRecord.objects.filter(kind="question").count() == 91
    assert RevisionRecord.objects.count() == EntityRecord.objects.count() == 219
    assert not EntityRecord.objects.exclude(published_revision=None).exists()
    restored = read_snapshot_bundle(actor, manifest["household_id"])
    restored_images, restored_entities = split_bundle(restored)
    source_images, source_entities = split_bundle(conversion.bundle)
    assert {image["image_id"]: image for image in restored_images} == {image["image_id"]: image for image in source_images}
    assert restored_entities == source_entities
    assert len(restored.regions) == len(restored.attempts) == len(restored.assessments) == len(restored.learners) == len(restored.errata) == 0
    for question in restored.questions:
        assert question.revisions[0].printed_text is None and question.revisions[0].working_text is None
    for observation in restored.observations:
        revision = observation.revisions[0]
        assert revision.author_state.value == revision.legibility.value == revision.actual_date_state.value == "unknown"
    all_rows = legacy_trace(actor, manifest["household_id"], manifest["dataset_key"])["entries"]
    assert [r["raw"] for r in all_rows] == [r["raw"] for r in conversion.index_rows]
    for entry in all_rows:
        for photo in entry["photos"]:
            reverse = legacy_trace(actor, manifest["household_id"], manifest["dataset_key"], photo_token=photo["token"])
            assert entry["ordinal"] in [r["ordinal"] for r in reverse["entries"]]
    all_questions = legacy_trace(actor, manifest["household_id"], manifest["dataset_key"])["questions"]
    assert len(all_questions) == 91 and sum(q["implicit_parent"] for q in all_questions) == 10
    for question in all_questions:
        forward = legacy_trace(actor, manifest["household_id"], manifest["dataset_key"],
            book=question["book"], number=question["number"])["questions"]
        assert [q["question_revision_id"] for q in forward] == [question["question_revision_id"]]
        for photo in question["photos"]:
            reverse = legacy_trace(actor, manifest["household_id"], manifest["dataset_key"], photo_token=photo["token"])["questions"]
            assert question["question_revision_id"] in [q["question_revision_id"] for q in reverse]
    cross_page = legacy_trace(actor, manifest["household_id"], manifest["dataset_key"], book="W1", number="8")["entries"]
    assert [p["token"] for p in cross_page[0]["photos"]] == ["193414", "193423"]
    referenced = {token for row in conversion.index_rows for token in row["photo_tokens"]}
    assert len(referenced) == 22
    for photo in manifest["sources"]["photos"]:
        # Compare original inventoried bytes and the private copies after DB work.
        assert checked_bytes(Path(manifest["sources"]["source_root"]), photo) == checked_bytes(args.data_root.resolve(), {**photo, "path": photo["storage_key"]})
        if photo["token"] not in referenced:
            trace = legacy_trace(actor, manifest["household_id"], manifest["dataset_key"], photo_token=photo["token"])
            assert trace["entries"] == [] and trace["source_photo"] is not None
    for group in range(1, 7):
        trace = legacy_trace(actor, manifest["household_id"], manifest["dataset_key"], group=group)
        assert sum(row["raw"]["group"] == group for row in trace["entries"]) == manifest["sources"]["expected_counts"]["by_group"][str(group)]
    # Exercise CLI import against the owned target and reload a newly verified package.
    import subprocess
    replay = subprocess.run([sys.executable, "scripts/import_legacy_catalog.py", "import", "--package", str(args.package),
        "--data-root", str(args.data_root), "--actor-id", str(actor.pk)], check=True, capture_output=True, text=True)
    assert json.loads(replay.stdout)["already_imported"]
    report = {"verified_at": datetime.now(timezone.utc).isoformat(), "source_digest": manifest["source_digest"],
        "counts": conversion.counts, "total_entities": 219, "referenced_photos": 22, "unindexed_photos": 1,
        "checks": ["source-copy-sha256", "snapshot-roundtrip", "81-raw-rows", "repeat-no-additions", "bidirectional-trace",
                   "cross-page-order", "six-method-groups", "unknown-provenance", "no-publication", "cli-replay"],
        "database_retention": "disposable-runner-cleans-after-exit"}
    report_path = args.package / "verification.local.json"
    descriptor = os.open(report_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical(report))
    print(json.dumps({"real_import_verified": True, "counts": conversion.counts, "entities": 219}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
