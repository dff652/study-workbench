"""Append-only schedules and immutable provenance for generated questions."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from app.persistence.models import EntityRecord, Household, RevisionRecord


class StudySchedule(models.Model):
    """Stable plan identity pinned to one learner and one question revision."""

    schedule_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="study_schedules")
    learner = models.ForeignKey(EntityRecord, on_delete=models.PROTECT, related_name="study_schedules")
    target_question_revision = models.ForeignKey(
        RevisionRecord, on_delete=models.PROTECT, related_name="study_schedules")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("household", "schedule_id"), name="study_schedule_identity")]
        indexes = [models.Index(fields=("household", "created_at"), name="study_schedule_recent")]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("A study schedule identity cannot be changed.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Study schedule history is retained.")


class ScheduleRevision(models.Model):
    class Action(models.TextChoices):
        PLANNED = "planned", "Planned"
        RESCHEDULED = "rescheduled", "Rescheduled"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    schedule = models.ForeignKey(StudySchedule, on_delete=models.PROTECT, related_name="revisions")
    revision_no = models.PositiveIntegerField()
    action = models.CharField(max_length=16, choices=Action.choices)
    due_date = models.DateField()
    goal = models.CharField(max_length=1200)
    prompt_plan = models.TextField(blank=True)
    completed_attempt_revision = models.ForeignKey(
        RevisionRecord, null=True, blank=True, on_delete=models.PROTECT,
        related_name="completed_study_schedules")
    reason = models.CharField(max_length=1000)
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="next_revisions")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("schedule", "revision_no"), name="study_schedule_version"),
            models.CheckConstraint(condition=models.Q(revision_no__gt=0), name="study_schedule_positive"),
            models.CheckConstraint(condition=models.Q(action__in=("planned", "rescheduled", "cancelled", "completed")),
                name="study_schedule_action_valid"),
        ]
        ordering = ("schedule_id", "revision_no")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Schedule revisions are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Schedule revisions are retained.")


class VariantProvenance(models.Model):
    """Immutable link between an AI-run output and its shared draft question."""

    question = models.OneToOneField(EntityRecord, on_delete=models.PROTECT, related_name="variant_provenance")
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="variant_provenance")
    run_id = models.CharField(max_length=160)
    parent_question_revision = models.ForeignKey(
        RevisionRecord, on_delete=models.PROTECT, related_name="generated_variants")
    target_method_revision = models.ForeignKey(
        RevisionRecord, on_delete=models.PROTECT, related_name="generated_method_variants")
    generated_text = models.TextField()
    answer_expression = models.CharField(max_length=512)
    check_expression = models.CharField(max_length=512)
    source_revision_ids = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=("household", "created_at"), name="study_variant_recent")]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Variant provenance is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Variant provenance is retained.")
