"""Authorized, optimistic and replay-safe companion writes."""
import fcntl
from io import BytesIO
import os
from pathlib import Path

from django.conf import settings
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from app.exports.contracts import canonical, digest
from app.persistence import services as core
from app.persistence.models import RevisionRecord
from app.web import services as materials
from app.web.models import MaterialSet
from . import bridge, schema
from .models import SolutionAsset, SolutionConfirmation, SolutionOutput, SolutionOutputEvent, SolutionRevision


@transaction.atomic
def material(actor, material_id, write=False):
    row = materials._material(actor, material_id, write=write)
    if write:
        row = MaterialSet.objects.select_for_update().select_related("household").get(pk=row.pk)
    return row


def inputs(row):
    pages = {str(page.pk): page for page in row.pages.select_related("image").order_by("position")}
    revisions = {item.pk: item for item in RevisionRecord.objects.filter(entity__household=row.household,
        entity__kind__in=("question", "knowledge", "method", "question_type")).select_related("entity")}
    assets = {str(item.pk): item for item in row.solution_assets.all()}
    return pages, revisions, assets


def latest(row):
    return row.solution_revisions.order_by("-version").first()


def version_check(row, expected):
    current = latest(row)
    if type(expected) is not int or expected != (current.version if current else 0):
        raise core.PersistenceError("stale_solution", "解析已在其他页面更新。请保留当前输入，刷新后比较再保存。")
    return current


def stamp(row, content):
    pages, revisions, assets = inputs(row)
    ids = {question["question_revision_id"] for question in content["questions"] if question["question_revision_id"]}
    ids.update(link["revision_id"] for question in content["questions"] for link in question["links"])
    return digest(canonical({"pages": [[str(page.pk), page.position, page.image.sha256] for page in pages.values()],
        "records": [[rid, revisions[rid].content_hash, revisions[rid].entity.head_revision_id,
                     revisions[rid].entity.published_revision_id] for rid in sorted(ids) if rid in revisions],
        "assets": [[str(asset.pk), asset.sha256] for asset in sorted(assets.values(), key=lambda item: str(item.pk)) if any(
            figure["asset_id"] == str(asset.pk) for question in content["questions"] for figure in schema.figures(question))]}))


def require_current_links(row, content):
    """Old revisions remain readable; new confirmation/output requires current evidence."""
    from app.web.models import QuestionSource
    _, revisions, _ = inputs(row)
    related = set(QuestionSource.objects.filter(material=row).values_list("revision_id", flat=True))
    for question in content["questions"]:
        rid = question["question_revision_id"]
        if rid is not None and rid not in related:
            raise core.PersistenceError("source_changed", "关联题目不属于这份资料，请重新选择。")
        linked = ([rid] if rid is not None else []) + [link["revision_id"] for link in question["links"]]
        for revision_id in linked:
            revision = revisions.get(revision_id)
            if revision is None or not (revision.pk == revision.entity.head_revision_id == revision.entity.published_revision_id):
                raise core.PersistenceError("source_changed", "关联题目或知识已更新、撤回或尚未确认，请核对并重新选择当前版本。")


@transaction.atomic
def save(actor, material_id, *, content, expected_version, request_key, reason):
    row = material(actor, material_id, write=True)
    request_key = materials._text(request_key, 160)
    reason = materials._text(reason, 1000)
    fingerprint = digest(canonical({"content": content, "expected": expected_version, "reason": reason, "actor": actor.pk}))
    previous = row.solution_revisions.filter(request_key=request_key).first()
    if previous:
        if previous.fingerprint != fingerprint:
            raise core.PersistenceError("request_conflict", "本次保存已对应其他内容，请重试。")
        return previous
    current = version_check(row, expected_version)
    pages, revisions, assets = inputs(row)
    schema.validate(content, pages, revisions, assets)
    manifest, mapping = bridge.source_manifest(row, content, pages)
    return SolutionRevision.objects.create(material=row, version=(current.version if current else 0) + 1,
        content=content, content_hash=digest(canonical(content)), sources={"manifest": manifest, "page_mapping": mapping},
        source_stamp=stamp(row, content), request_key=request_key, fingerprint=fingerprint,
        author=actor, reason=reason)


@transaction.atomic
def action(actor, material_id, *, action, expected_version, request_key, reason):
    row = material(actor, material_id, write=True)
    request_key = materials._text(request_key, 160)
    reason = materials._text(reason, 1000)
    fingerprint = digest(canonical({"material": str(row.pk), "action": action,
                                    "version": expected_version, "reason": reason}))
    replay = core._replay(row.household, actor, request_key, "web_record", fingerprint)
    if replay:
        return replay
    revision = version_check(row, expected_version)
    if not revision or not revision.content["questions"]:
        raise core.PersistenceError("solution_incomplete", "请先保存至少一道题目的解析草稿。")
    if revision.source_stamp != stamp(row, revision.content):
        raise core.PersistenceError("source_changed", "来源或知识版本已更新，请比较后保存新解析版本。")
    pages, revisions, assets = inputs(row)
    schema.validate(revision.content, pages, revisions, assets)
    require_current_links(row, revision.content)
    if action == "confirm":
        confirmation = SolutionConfirmation.objects.create(revision=revision, author=actor, reason=reason)
        result = {"revision_id": revision.pk, "confirmation_id": confirmation.pk}
    elif action == "generate":
        if (not any(revision.content["outputs"].values()) or any(not question["sources"] or not question["parts"]
                for question in revision.content["questions"])):
            raise core.PersistenceError("solution_incomplete", "生成前请为每题选择原图、填写小问并选择输出格式；未知答案和区域可以保留。")
        bridge.companion_content(revision, assets)
        output = SolutionOutput.objects.create(revision=revision, requested_by=actor,
            request_key=request_key, fingerprint=fingerprint)
        SolutionOutputEvent.objects.create(output=output, version=1, action="queued", author=actor,
            details={"reason": reason, "confirmed": revision.confirmations.exists()})
        result = {"revision_id": revision.pk, "output_id": str(output.pk)}
    else:
        raise core.PersistenceError("invalid_state", "此操作不受支持。")
    return core._receipt(row.household, actor, request_key, "web_record", fingerprint, result)


def _source_pixels(row, kind, source):
    pages = {str(page.pk): page for page in row.pages.select_related("image")}
    schema.source(source, pages)
    if (kind == "source_crop") != (source["region"] is not None):
        schema.fail("裁切图须有真实区域，整张原图不填写裁切区域。")
    page = pages[source["page_id"]]
    original = materials.asset_path(page.image.payload["storage_key"], page.image.sha256)
    with Image.open(original) as image:
        pixels = image.convert("RGBA")
        if source["region"] is not None:
            pixels = pixels.crop(source["region"])
    return pixels


def derive_asset(actor, material_id, *, kind, label, basis, source, request_key):
    if kind not in ("source_crop", "source_image"):
        schema.fail("只能从原图生成来源图片或来源裁切。")
    row = material(actor, material_id, write=True)
    pixels = _source_pixels(row, kind, source)
    if pixels.width * pixels.height > 4_000_000:
        schema.fail("图示最多 400 万像素，请选择较小的原图区域。")
    stream = BytesIO()
    pixels.save(stream, format="PNG")
    # Never derive source pixels from the white-background display preview or
    # a browser canvas. Reuse upload validation, authorization and replay guards.
    return upload_asset(actor, material_id, stream, kind=kind, label=label,
                        basis=basis, source=source, request_key=request_key)


def upload_asset(actor, material_id, upload, *, kind, label, basis, source, request_key):
    if upload is None or not hasattr(upload, "read"):
        schema.fail("请选择 PNG 图示。")
    upload.seek(0)
    raw = upload.read(8 * 1024 * 1024 + 1)
    if not raw or len(raw) > 8 * 1024 * 1024:
        schema.fail("图示最多 8 MiB。")
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format != "PNG" or image.width * image.height > 4_000_000:
                raise ValueError
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            pixels = image.convert("RGBA")
            pixels.load()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise core.PersistenceError("invalid_solution", "图示须为可读取的 PNG，最多 400 万像素。") from exc
    label, basis, request_key = (materials._text(value, maximum) for value, maximum in
                                  ((label, 160), (basis, 1000), (request_key, 160)))
    if kind not in ("source_crop", "source_image", "auxiliary"):
        schema.fail("请选择原图、来源裁切或辅助图。")
    root = materials._root()
    from .vendor.common import assert_no_symlinks
    assert_no_symlinks(root)
    created = []
    fd = os.open(root / ".solution-files.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with transaction.atomic(durable=True):
                row = material(actor, material_id, write=True)
                if kind == "auxiliary":
                    if source is not None:
                        schema.fail("辅助构图须独立标注，不能冒充原图区域。")
                else:
                    expected = _source_pixels(row, kind, source)
                    if expected.size != pixels.size or expected.tobytes() != pixels.tobytes():
                        schema.fail("所上传图片与原图区域不一致。修改后的图示请标为辅助图，并填写依据。")
                sha = digest(raw)
                fingerprint = digest(canonical({"sha": sha, "kind": kind, "source": source,
                                               "label": label, "basis": basis, "actor": actor.pk}))
                previous = row.solution_assets.filter(request_key=request_key).first()
                if previous:
                    if previous.fingerprint != fingerprint:
                        raise core.PersistenceError("request_conflict", "本次上传已对应其他图片。")
                    materials.asset_path(previous.storage_key, previous.sha256)
                    return previous
                storage_key = f"solutions/assets/{row.pk.hex}/{sha}.png"
                assert_no_symlinks(root / storage_key)
                materials._install(root, storage_key, raw, created)
                return SolutionAsset.objects.create(material=row, kind=kind, label=label, basis=basis,
                    source=source, storage_key=storage_key, sha256=sha, width=pixels.width, height=pixels.height,
                    request_key=request_key, fingerprint=fingerprint, author=actor)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
