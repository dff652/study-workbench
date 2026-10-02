"""Immutable local-retention policy, export lifecycle, and manual timing rows."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from app.persistence.models import Household, RevisionRecord
from app.printing.models import ExportSnapshot


class RetentionPolicyRevision(models.Model):
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="retention_policies")
    revision_no = models.PositiveIntegerField()
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="next_revisions")
    archive_after_days = models.PositiveIntegerField(null=True, blank=True)
    delete_after_days = models.PositiveIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=1000)
    request_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("household", "revision_no"), name="ops_policy_version"),
            models.UniqueConstraint(fields=("household", "request_key"), name="ops_policy_request"),
            models.CheckConstraint(condition=models.Q(revision_no__gt=0), name="ops_policy_positive"),
            models.CheckConstraint(condition=(
                models.Q(delete_after_days__isnull=True) |
                (models.Q(archive_after_days__isnull=False) &
                 models.Q(delete_after_days__gte=models.F("archive_after_days")))),
                name="ops_policy_archive_before_delete"),
        ]
        ordering = ("household_id", "revision_no")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Retention policy revisions are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Retention policy revisions are retained.")


class ExportArchiveRecord(models.Model):
    snapshot = models.OneToOneField(ExportSnapshot, on_delete=models.PROTECT, related_name="local_archive")
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="export_archives")
    source_storage_key = models.CharField(max_length=300)
    archive_storage_key = models.CharField(max_length=360, unique=True)
    manifest_sha256 = models.CharField(max_length=64)
    archive_sha256 = models.CharField(max_length=64)
    file_hashes = models.JSONField()
    reason = models.CharField(max_length=1000)
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    archived_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Export archive records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Export archive records are retained.")


class ExportRetirementRecord(models.Model):
    snapshot = models.OneToOneField(ExportSnapshot, on_delete=models.PROTECT, related_name="local_retirement")
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="export_retirements")
    storage_key = models.CharField(max_length=300)
    archive_storage_key = models.CharField(max_length=360)
    manifest_sha256 = models.CharField(max_length=64)
    archive_sha256 = models.CharField(max_length=64)
    file_hashes = models.JSONField()
    reason = models.CharField(max_length=1000)
    retired_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    retired_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Export retirement records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Export retirement records are retained.")


class WorkTiming(models.Model):
    class Kind(models.TextChoices):
        MANUAL_ENTRY = "manual_entry", "手工录入"
        MODEL_CORRECTION = "model_correction", "模型结果人工修订"

    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="work_timings")
    question_revision = models.ForeignKey(RevisionRecord, on_delete=models.PROTECT,
        related_name="work_timings")
    attempt_revision = models.ForeignKey(RevisionRecord, null=True, blank=True,
        on_delete=models.PROTECT, related_name="timing_records")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    seconds = models.PositiveIntegerField()
    reason = models.CharField(max_length=1000)
    request_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("household", "request_key"), name="ops_timing_request"),
            models.CheckConstraint(condition=models.Q(kind__in=("manual_entry", "model_correction")),
                name="ops_timing_kind_valid"),
            models.CheckConstraint(condition=models.Q(seconds__gt=0) & models.Q(seconds__lte=604800),
                name="ops_timing_seconds_valid"),
        ]
        ordering = ("-recorded_at", "-pk")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Work timing records are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Work timing records are retained.")
