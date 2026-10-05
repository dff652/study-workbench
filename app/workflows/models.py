"""Persistent SOP state; input and audit events remain immutable."""
import uuid
from django.conf import settings
from django.db import models


STATES = ("needs_review", "ready", "queued", "running", "output_check", "complete", "failed", "cancelled")


class WorkflowJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material = models.ForeignKey("workbench_web.MaterialSet", on_delete=models.PROTECT, related_name="workflow_jobs")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=160)
    fingerprint = models.CharField(max_length=64)
    input = models.JSONField(default=dict)
    state = models.CharField(max_length=20, default="needs_review")
    version = models.PositiveIntegerField(default=1)
    source_stamp = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    error_code = models.CharField(max_length=80, blank=True)
    started_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("material", "request_key"), name="swb_workflow_request_unique"),
            models.CheckConstraint(condition=models.Q(state__in=STATES), name="swb_workflow_state"),
            models.CheckConstraint(condition=models.Q(version__gt=0), name="swb_workflow_version"),
        ]


class WorkflowEvent(models.Model):
    job = models.ForeignKey(WorkflowJob, on_delete=models.PROTECT, related_name="events")
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=40)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("version",)
        constraints = [models.UniqueConstraint(fields=("job", "version"), name="swb_workflow_event_version")]


class WorkspaceDraft(models.Model):
    """Private, recoverable input; never a confirmed domain revision."""
    household = models.ForeignKey("persistence.Household", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    key = models.CharField(max_length=160)
    version = models.PositiveIntegerField(default=1)
    base_stamp = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("household", "actor", "key"), name="swb_workspace_draft_unique")]
