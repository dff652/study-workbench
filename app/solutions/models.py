"""Append-only companion content and resumable, version-bound output jobs."""
import uuid

from django.conf import settings
from django.db import models


class SolutionRevision(models.Model):
    material = models.ForeignKey("workbench_web.MaterialSet", on_delete=models.PROTECT, related_name="solution_revisions")
    mode = models.CharField(max_length=16, default="solution")
    version = models.PositiveIntegerField()
    content = models.JSONField()
    content_hash = models.CharField(max_length=64)
    sources = models.JSONField()
    source_stamp = models.CharField(max_length=64)
    request_key = models.CharField(max_length=160)
    fingerprint = models.CharField(max_length=64)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("version",)
        constraints = [
            models.UniqueConstraint(fields=("material", "mode", "version"), name="swb_solution_revision_mode_version"),
            models.UniqueConstraint(fields=("material", "mode", "request_key"), name="swb_solution_revision_mode_request"),
            models.CheckConstraint(condition=models.Q(mode__in=("solution", "knowledge")), name="swb_companion_mode"),
        ]


class SolutionConfirmation(models.Model):
    revision = models.ForeignKey(SolutionRevision, on_delete=models.PROTECT, related_name="confirmations")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)


class SolutionAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material = models.ForeignKey("workbench_web.MaterialSet", on_delete=models.PROTECT, related_name="solution_assets")
    kind = models.CharField(max_length=20)
    label = models.CharField(max_length=160)
    basis = models.CharField(max_length=1000)
    source = models.JSONField(null=True)
    storage_key = models.CharField(max_length=240)
    sha256 = models.CharField(max_length=64)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    request_key = models.CharField(max_length=160)
    fingerprint = models.CharField(max_length=64)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("material", "request_key"), name="swb_solution_asset_request")]


class SolutionOutput(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(SolutionRevision, on_delete=models.PROTECT, related_name="outputs")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=160)
    fingerprint = models.CharField(max_length=64)
    state = models.CharField(max_length=20, default="queued")
    version = models.PositiveIntegerField(default=1)
    result = models.JSONField(default=dict)
    error_code = models.CharField(max_length=80, blank=True)
    started_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("revision", "request_key"), name="swb_solution_output_request"),
            models.CheckConstraint(condition=models.Q(state__in=("queued", "running", "output_check", "complete", "failed", "cancelled")), name="swb_solution_output_state"),
        ]


class SolutionOutputEvent(models.Model):
    output = models.ForeignKey(SolutionOutput, on_delete=models.PROTECT, related_name="events")
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=32)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("version",)
        constraints = [models.UniqueConstraint(fields=("output", "version"), name="swb_solution_output_event")]
