"""Explicit school subjects, independently versioned from explanation profiles."""
from django.db import transaction
from django.db.models import CharField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from app.persistence import services as core
from . import services
from .models import MaterialClassificationRevision, MaterialSet

CHOICES = (("unknown", "未分类"), ("mathematics", "数学"), ("chinese", "语文"), ("english", "英语"),
    ("physics", "物理"), ("chemistry", "化学"), ("biology", "生物"), ("history", "历史"),
    ("geography", "地理"), ("politics", "道德与法治"), ("science", "科学"), ("other", "其他"))
LABELS = dict(CHOICES)


def validate(value):
    if type(value) is not str or value not in LABELS:
        raise core.PersistenceError("invalid_subject", "请选择有效的学校学科；尚未确认时保留未分类。")
    return value


def latest(material):
    return material.classifications.order_by("-version").first()


def current(material):
    row = latest(material)
    return {"subject": row.subject if row else "unknown", "version": row.version if row else 0}


def classified(rows):
    latest_subject = MaterialClassificationRevision.objects.filter(material_id=OuterRef("pk")).order_by(
        "-version").values("subject")[:1]
    return rows.annotate(school_subject=Coalesce(Subquery(latest_subject), Value("unknown"), output_field=CharField()))


@transaction.atomic
def save(actor, material_id, *, subject, expected_version, request_key, reason):
    material = services._material(actor, material_id, write=True)
    material = MaterialSet.objects.select_for_update().get(pk=material.pk)
    subject = validate(subject)
    request_key, reason = services._text(request_key, 160), services._text(reason, 1000)
    fingerprint = core._digest({"subject": subject, "expected": expected_version, "reason": reason, "actor": actor.pk})
    replay = material.classifications.filter(request_key=request_key).first()
    if replay:
        if replay.fingerprint != fingerprint:
            raise core.PersistenceError("request_conflict", "本次分类请求已对应其他内容。")
        return replay
    old = latest(material)
    if type(expected_version) is not int or expected_version != (old.version if old else 0):
        raise core.PersistenceError("stale_subject", "学科已在另一窗口更新，请比较后再保存。")
    return MaterialClassificationRevision.objects.create(material=material, version=expected_version + 1,
        previous=old, subject=subject, reason=reason, created_by=actor, request_key=request_key, fingerprint=fingerprint)
