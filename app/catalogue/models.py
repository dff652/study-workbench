"""Append-only lineage between exact question revisions."""
from django.conf import settings
from django.db import models

from app.persistence.models import Household


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
