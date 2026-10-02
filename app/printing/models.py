"""Append-only teacher answers and authorized print snapshots.

Question identities and their content remain in the shared persistence model.
An answer is a separate teacher assertion, never inferred from a child's work.
"""
from django.conf import settings
from django.db import models
from app.persistence.models import Household, RevisionRecord


class TeacherAnswerRevision(models.Model):
    household = models.ForeignKey(Household, on_delete=models.PROTECT)
    question_revision = models.ForeignKey(RevisionRecord, on_delete=models.PROTECT)
    revision_no = models.PositiveIntegerField()
    previous = models.ForeignKey('self', null=True, on_delete=models.PROTECT)
    body = models.TextField()
    formulas = models.JSONField(default=list)
    basis = models.TextField()
    source_refs = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('question_revision', 'revision_no'), name='swb_answer_version'),
            models.CheckConstraint(condition=models.Q(revision_no__gt=0), name='swb_answer_positive')]


class AnswerDecision(models.Model):
    answer = models.ForeignKey(TeacherAnswerRevision, on_delete=models.PROTECT, related_name='decisions')
    action = models.CharField(max_length=16, choices=[(v, v) for v in ('accepted', 'rejected', 'withdrawn')])
    reason = models.TextField()
    previous = models.ForeignKey('self', null=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(action__in=('accepted','rejected','withdrawn')),
            name='swb_answer_decision_valid')]


class ExportSnapshot(models.Model):
    household = models.ForeignKey(Household, on_delete=models.PROTECT)
    export_id = models.CharField(max_length=64)
    purpose = models.CharField(max_length=32)
    title = models.CharField(max_length=160)
    storage_key = models.CharField(max_length=300)
    manifest_sha256 = models.CharField(max_length=64)
    provenance = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('household', 'export_id'), name='swb_print_identity')]
