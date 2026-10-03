"""Append-only lineage between exact question revisions."""
from django.conf import settings
from django.db import models

from app.persistence.models import Household, RevisionRecord


class QuestionLabel(models.Model):
    """An entered derived question number independent of a single material set."""
    revision = models.OneToOneField(RevisionRecord, primary_key=True, on_delete=models.PROTECT)
    original_number = models.CharField(max_length=80)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=~models.Q(original_number=""),
            name="swb_question_label_number_required")]


class QuestionLineage(models.Model):
    class Action(models.TextChoices):
        SPLIT = "split", "Split"
        MERGE = "merge", "Merge"

    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="question_lineage")
    action = models.CharField(max_length=8, choices=Action.choices)
    source_revision_ids = models.JSONField()
    target_revision_ids = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = "catalogue_questionlineage"
        constraints = [
            models.CheckConstraint(condition=models.Q(action__in=("split", "merge")),
                name="swb_lineage_action_valid"),
            models.CheckConstraint(condition=~models.Q(reason=""), name="swb_lineage_reason_required"),
        ]
