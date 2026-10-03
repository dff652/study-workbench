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


class ImageDerivative(models.Model):
    """Immutable local processing record; never substitutes for original evidence."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(MaterialPage, on_delete=models.PROTECT, related_name='derivatives')
    original_image = models.ForeignKey(ImageRecord, on_delete=models.PROTECT, related_name='derivatives')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operation = models.CharField(max_length=16, choices=(('crop','裁切'),('erase','手动遮白'),('contrast','对比度增强')))
    parameters = models.JSONField()
    original_sha256 = models.CharField(max_length=64)
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=240)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    lossy_description = models.CharField(max_length=1000)
    request_key = models.CharField(max_length=160)
    fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('page','created_by','request_key'),name='swb_derivative_request'),
            models.CheckConstraint(condition=models.Q(operation__in=('crop','erase','contrast')),name='swb_derivative_operation'),
            models.CheckConstraint(condition=models.Q(width__gt=0,height__gt=0),name='swb_derivative_size')]

    def save(self,*args,**kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            from django.core.exceptions import ValidationError
            raise ValidationError('派生记录只能追加。')
        return super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError('派生来源记录默认保留。')
