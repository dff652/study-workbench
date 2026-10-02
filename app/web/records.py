"""Shared household, revision and idempotency boundaries for business pages."""
from uuid import uuid4

from django.core import signing
from django.db import transaction

from app.domain.contracts import ContractError, EvidenceRef, EvidencePurpose, Granularity, RegionRevision, seal_revision
from app.persistence import services as core
from app.persistence.adapter import ObjectKey
from app.persistence.models import EntityRecord, Household, RevisionRecord
from . import services as materials
from .images import original_bbox
from .models import MaterialPage

CONTEXT_SALT = "study-workbench.business-context.v1"


def household(actor, household_id, *, write=False):
    value = Household.objects.select_for_update().get(pk=household_id)
    core.require_household_access(actor, value, write=write)
    return value


def header(actor, owner_id, reason, previous=None):
    return materials._header(actor, owner_id, materials._text(reason, 1000), previous)


def entity(household_id, kind, stable_id):
    return EntityRecord.objects.select_related("household", "head_revision").get(
        household_id=household_id, kind=kind, stable_id=stable_id)


def edit_context(row):
    return materials._edit_context(row)


def check_edit(row, expected_context):
    if expected_context != edit_context(row):
        raise core.PersistenceError("head_conflict", "内容或依赖已改变，请重新打开。")
    heads = {ObjectKey(row.entity.kind, row.entity.stable_id): row.pk}
    for dependency in expected_context["expected_dependencies"]:
        heads[ObjectKey(dependency["kind"], dependency["stable_id"])] = dependency["head_revision_id"]
    return heads


def sign_context(household_id, kind, stable_id, purpose, context):
    return signing.dumps({"household": str(household_id), "kind": kind, "id": stable_id,
        "purpose": purpose, "context": context}, salt=CONTEXT_SALT)


def read_context(token, household_id, kind, stable_id, purpose):
    try:
        value = signing.loads(token, salt=CONTEXT_SALT, max_age=3600)
    except signing.BadSignature as exc:
        raise core.PersistenceError("stale_context", "凭据已过期或无效。") from exc
    if (not isinstance(value, dict) or value.get("household") != str(household_id)
            or value.get("kind") != kind or value.get("id") != stable_id
            or value.get("purpose") != purpose or not isinstance(value.get("context"), dict)):
        raise core.PersistenceError("stale_context", "凭据与当前操作不符。")
    return value["context"]


@transaction.atomic
def command(actor, household_id, request_key, action, inputs, build):
    """Run a bounded builder under the household lock.

    build(bundle) returns (new_bundle, expected_heads, result). Its fresh UUIDs
    and timestamps are deliberately generated only after successful replay.
    """
    owner = household(actor, household_id, write=True)
    try:
        fingerprint = core._digest({"action": action, "inputs": inputs})
    except (TypeError, ValueError) as exc:
        raise core.PersistenceError("invalid_input", "请求内容无效。") from exc
    replay = core._replay(owner, actor, request_key, "web_record", fingerprint)
    if replay:
        return replay
    try:
        bundle, expected_heads, result = build(core.read_snapshot_bundle(actor, household_id))
        core.stage_bundle(actor, bundle, request_key=f"business-stage-{uuid4().hex}", expected_heads=expected_heads)
    except ContractError as exc:
        raise core.PersistenceError("invalid_input", "记录不符合来源或版本约束。") from exc
    return core._receipt(owner, actor, request_key, "web_record", fingerprint, result)


@transaction.atomic
def detail(actor, household_id, kind, stable_id):
    household(actor, household_id)
    item = entity(household_id, kind, stable_id)
    row = item.head_revision
    return {"entity": item, "current": row.payload if row else item.identity,
        "history": list(item.revisions.select_related("review_projection").order_by("-revision_no")),
        "edit_context": edit_context(row) if row else None,
        "review_context": core.review_context(actor, household_id, row.pk) if row else None}


@transaction.atomic
def review(actor, household_id, kind, stable_id, revision_id, *, action, reason, context, request_key):
    household(actor, household_id, write=True)
    item = entity(household_id, kind, stable_id)
    RevisionRecord.objects.get(pk=revision_id, entity=item)
    if not isinstance(context, dict) or set(context) != {
            "expected_head", "expected_dependencies", "expected_decision_id", "state"}:
        raise core.PersistenceError("invalid_input", "审核凭据不完整。")
    return core.review_revision(actor, household_id, revision_id, action=action, reason=reason,
        expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
        expected_decision_id=context["expected_decision_id"], request_key=request_key)


def source_refs(actor, household_id, sources, *, purpose=EvidencePurpose.HANDWRITING):
    """Validate B1 source JSON and return fresh regions plus exact evidence refs.

    Call only inside command's household transaction. Existing original bytes
    and old source regions are never changed. Empty sources are caller-specific.
    """
    if not isinstance(sources, list) or len(sources) > 30:
        raise core.PersistenceError("invalid_region", "来源区域列表无效。")
    refs, regions = [], []
    for sequence, source in enumerate(sources, 1):
        if not isinstance(source, dict) or not {"page_id", "rotation", "preview_sha256", "display_bbox"}.issubset(source):
            raise core.PersistenceError("invalid_region", "来源区域不完整。")
        page = MaterialPage.objects.select_related("image", "material").get(
            pk=source["page_id"], material__household_id=household_id)
        preview = materials.preview_file(actor, page.pk, source["rotation"])
        if preview.sha256 != source["preview_sha256"]:
            raise core.PersistenceError("preview_changed", "预览已改变。")
        materials.asset_path(preview.storage_key, preview.sha256)
        box = original_bbox(source["display_bbox"], page.image.payload["width"],
            page.image.payload["height"], source["rotation"])
        region_id = f"business-region-{uuid4().hex}"
        region = seal_revision(RegionRevision(region_id, household_id,
            header(actor, region_id, "记录人工选定来源区域"), page.image.stable_id,
            "original_pixels", box, purpose.value))
        regions.append(region)
        refs.append(EvidenceRef(household_id, page.image.stable_id, page.image.sha256,
            Granularity.REGION, region_id, region.header.revision_id, False, purpose, sequence))
    return tuple(regions), tuple(refs)
