"""Append-only provenance for the bounded legacy catalog import."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from app.persistence.models import Household, RequestReceipt, RevisionRecord


class LegacyImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.PROTECT)
    dataset_key = models.CharField(max_length=160)
    source_digest = models.CharField(max_length=64)
    prepared_at = models.DateTimeField()
    imported_at = models.DateTimeField(default=timezone.now)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    receipt = models.OneToOneField(RequestReceipt, on_delete=models.PROTECT)
    manifest = models.JSONField()
    counts = models.JSONField()

    class Meta:
        db_table = "swb_legacyimportbatch"
        constraints = [
            models.UniqueConstraint(fields=("household", "dataset_key"), name="swb_import_house_dataset_uniq"),
            models.CheckConstraint(condition=models.Q(source_digest__regex=r"^[0-9a-f]{64}$"), name="swb_import_digest_valid"),
        ]


class LegacyIndexEntry(models.Model):
    batch = models.ForeignKey(LegacyImportBatch, on_delete=models.PROTECT, related_name="entries")
    ordinal = models.PositiveIntegerField()
    book = models.CharField(max_length=8)
    number = models.CharField(max_length=40)
    question_revision = models.ForeignKey(RevisionRecord, on_delete=models.PROTECT, related_name="legacy_entries")
    primary_method_revision = models.ForeignKey(RevisionRecord, on_delete=models.PROTECT, related_name="legacy_classifications")
    raw = models.JSONField()
    photo_tokens = models.JSONField()
    auxiliary_method_revision_ids = models.JSONField()

    class Meta:
        db_table = "swb_legacyindexentry"
        constraints = [
            models.UniqueConstraint(fields=("batch", "book", "number"), name="swb_import_entry_number_uniq"),
            models.UniqueConstraint(fields=("batch", "ordinal"), name="swb_import_entry_order_uniq"),
            models.CheckConstraint(condition=models.Q(ordinal__gt=0), name="swb_import_entry_order_positive"),
        ]
