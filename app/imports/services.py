"""Atomic legacy imports and household-scoped provenance queries."""
from datetime import datetime

from django.db import transaction

from app.persistence.models import Household, RequestReceipt, RevisionRecord
from app.persistence.services import PersistenceError, require_household_access, stage_bundle
from .models import LegacyImportBatch, LegacyIndexEntry
from .package import verify_prepared


def _result(batch, repeated):
    return {"batch_id": str(batch.pk), "source_digest": batch.source_digest,
            "counts": batch.counts, "already_imported": repeated,
            "added": {"entities_added": 0, "revisions_added": 0, "images_added": 0} if repeated else batch.receipt.result}


@transaction.atomic
def import_prepared(actor, prepared):
    """Import once per household/dataset; a changed source requires a new dataset."""
    verify_prepared(prepared)
    manifest = prepared.manifest
    dataset = manifest["dataset_key"]
    if not isinstance(dataset, str) or not dataset.strip() or len(dataset) > 160:
        raise PersistenceError("invalid_input", "Invalid dataset key")
    household = Household.objects.select_for_update().get(pk=manifest["household_id"])
    require_household_access(actor, household, write=True)
    batch = LegacyImportBatch.objects.select_related("receipt").filter(household=household, dataset_key=dataset).first()
    if batch:
        if batch.source_digest != manifest["source_digest"]:
            raise PersistenceError("import_source_conflict", "Dataset already refers to different source bytes")
        return _result(batch, True)
    request_key = f"legacy-import:{manifest['source_digest']}"
    stage_bundle(actor, prepared.conversion.bundle, request_key=request_key, expected_heads={})
    receipt = RequestReceipt.objects.get(household=household, request_key=request_key)
    batch = LegacyImportBatch.objects.create(household=household, dataset_key=dataset,
        source_digest=manifest["source_digest"], prepared_at=datetime.fromisoformat(manifest["prepared_at"]),
        imported_by=actor, receipt=receipt, manifest=manifest, counts=prepared.conversion.counts)
    LegacyIndexEntry.objects.bulk_create([LegacyIndexEntry(batch=batch, ordinal=row["ordinal"],
        book=row["book"], number=row["num"], question_revision_id=row["question_revision_id"],
        primary_method_revision_id=row["primary_method_revision_id"], raw=row["raw"],
        photo_tokens=row["photo_tokens"], auxiliary_method_revision_ids=row["aux_method_revision_ids"])
        for row in prepared.conversion.index_rows])
    return _result(batch, False)


def _question_trace(batch, household, photos, *, book, number, photo_token, group_question_ids):
    """Include implied parent containers, using original revision pins only."""
    revisions = {r.pk: r.payload for r in RevisionRecord.objects.filter(entity__household=household, entity__kind="question")}
    indexed = {row["question_revision_id"] for row in batch.manifest["index_rows"]}
    identities = {}
    for row in batch.manifest["index_rows"]:
        rid, num = row["question_revision_id"], row["num"]
        while rid:
            identities[rid] = (row["book"], num)
            rid = revisions[rid]["parent_question_revision_id"]
            num = num.rsplit("-", 1)[0] if "-" in num else num.split("(", 1)[0]
    image_tokens = {photo["image_id"]: token for token, photo in photos.items()}
    result = []
    for rid, (source_book, num) in identities.items():
        payload = revisions[rid]
        if book is not None and source_book != book or number is not None and num != number:
            continue
        if group_question_ids is not None and rid not in group_question_ids:
            continue
        refs = payload["evidence_refs"]
        if photo_token is not None and not any(image_tokens[ref["image_id"]] == photo_token for ref in refs):
            continue
        result.append({"book": source_book, "number": num, "question_revision_id": rid,
            "implicit_parent": rid not in indexed, "parent_question_revision_id": payload["parent_question_revision_id"],
            "missing_fields": payload["missing_fields"],
            "photos": [{**ref, "token": image_tokens[ref["image_id"]],
                        "storage_key": photos[image_tokens[ref["image_id"]]]["storage_key"]} for ref in refs]})
    return result


@transaction.atomic
def legacy_trace(actor, household_id, dataset_key, *, book=None, number=None, photo_token=None, group=None):
    """Trace the draft legacy index. This query never reports mastery or publication."""
    household = Household.objects.select_for_update().get(pk=household_id)
    require_household_access(actor, household)
    batch = LegacyImportBatch.objects.get(household=household, dataset_key=dataset_key)
    rows = batch.entries.select_related("question_revision", "primary_method_revision").order_by("ordinal")
    if book is not None:
        rows = rows.filter(book=book)
    if number is not None:
        rows = rows.filter(number=number)
    if photo_token is not None:
        rows = rows.filter(photo_tokens__contains=[photo_token])
    methods = {row["primary_method_revision_id"]: row["raw"]["group"] for row in batch.manifest["index_rows"]}
    # Empty groups may still be referenced as auxiliary methods.
    missing = {rid for row in batch.manifest["index_rows"] for rid in row["aux_method_revision_ids"]} - methods.keys()
    groups = {name: int(key) for key, name in batch.manifest["sources"]["groups"].items()}
    for revision in RevisionRecord.objects.filter(pk__in=missing, entity__household=household):
        methods[revision.pk] = groups[revision.payload["name"]]
    photos = {p["token"]: p for p in batch.manifest["sources"]["photos"]}
    entries = []
    for row in rows:
        if group is not None and group not in {row.raw["group"], *(methods[rid] for rid in row.auxiliary_method_revision_ids)}:
            continue
        entries.append({"ordinal": row.ordinal, "book": row.book, "number": row.number,
            "question_revision_id": row.question_revision_id, "raw": row.raw,
            "primary_method_revision_id": row.primary_method_revision_id,
            "auxiliary_method_revision_ids": row.auxiliary_method_revision_ids,
            "missing_fields": row.question_revision.payload["missing_fields"],
            "photos": [{"token": token, "image_id": photos[token]["image_id"],
                        "sha256": photos[token]["sha256"], "storage_key": photos[token]["storage_key"],
                        "sequence": index + 1, "region_missing": True}
                       for index, token in enumerate(row.photo_tokens)]})
    return {"batch_id": str(batch.pk), "index_state": "draft", "entries": entries,
            "source_photo": photos.get(photo_token) if photo_token is not None else None,
            "questions": _question_trace(batch, household, photos, book=book, number=number,
                photo_token=photo_token, group_question_ids={row["question_revision_id"] for row in entries} if group is not None else None)}
