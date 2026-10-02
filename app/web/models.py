import uuid
from django.db import models
from django.conf import settings
from app.persistence.models import Household, ImageRecord, RevisionRecord


class MaterialSet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.PROTECT)
    title = models.CharField(max_length=160)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class MaterialPage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material = models.ForeignKey(MaterialSet, on_delete=models.PROTECT, related_name='pages')
    image = models.ForeignKey(ImageRecord, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()
    original_name = models.CharField(max_length=255)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('material', 'position'), name='swb_web_page_position',
                                               deferrable=models.Deferrable.DEFERRED),
                       models.CheckConstraint(condition=models.Q(position__gt=0), name='swb_web_position_positive')]


class PagePreview(models.Model):
    image = models.ForeignKey(ImageRecord, on_delete=models.PROTECT, related_name='web_previews')
    rotation = models.PositiveSmallIntegerField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=240)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('image', 'rotation'), name='swb_web_preview_rotation'),
                       models.CheckConstraint(condition=models.Q(rotation__in=(0,90,180,270)), name='swb_web_rotation_valid'),
                       models.CheckConstraint(condition=models.Q(sha256__regex=r'^[0-9a-f]{64}$'), name='swb_web_preview_hash')]


class QuestionSource(models.Model):
    revision = models.OneToOneField(RevisionRecord, on_delete=models.PROTECT, primary_key=True)
    material = models.ForeignKey(MaterialSet, on_delete=models.PROTECT)
    original_number = models.CharField(max_length=80, blank=True)
    sources = models.JSONField()
