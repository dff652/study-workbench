"""Household retention and manual timing services with explicit file scope."""
from datetime import timedelta
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath
import re
import stat
import shutil
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from app.exports.contracts import ExportError, canonical, digest
from app.exports.snapshots import verify_snapshot, write_private
from app.persistence import services as core
from app.persistence.models import EntityRecord, HouseholdMember, RevisionRecord
from app.printing.models import ExportSnapshot
from app.web import records
from .models import ExportArchiveRecord, ExportRetirementRecord, RetentionPolicyRevision, WorkTiming


logger = logging.getLogger(__name__)
TIMING_CONTEXT_SALT = "study-workbench.work-timing.v1"
MAX_TIMING_SECONDS = 604800
LEDGER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
DATA_LIFECYCLE_POLICY = (
    {"kind": "原始照片", "default": "私有资料卷内原样保存；无自动归档或退役。",
        "archive_retire": "配套备份会包含原图；应用不自动删除，也不随导出退役。"},
    {"kind": "派生文件与预览", "default": "旋转预览、裁切、手动遮白和增强结果与原图分开保存，记录来源及处理信息。",
        "archive_retire": "随私有资料卷备份；当前不自动归档或退役派生文件，不能覆盖原图。"},
    {"kind": "领域历史", "default": "题目、知识、作答和评价修订历史追加保留。",
        "archive_retire": "随数据库配套备份；应用不自动归档或退役领域历史。"},
    {"kind": "AI 响应", "default": "任务响应、工具结果、用量和状态保存在本机数据库。",
        "archive_retire": "随数据库配套备份；应用不自动归档或退役响应历史。供应商副本另按配置说明或标记未知。"},
    {"kind": "运行日志", "default": "worker 输出任务编号、状态和错误码，不写响应正文或密钥。",
        "archive_retire": "项目未配置日志轮转期限；由主机或容器运行环境管理，当前保留期限未知。"},
    {"kind": "备份", "default": "每份数据库与私有资料卷配套备份写入独立新目录，不覆盖已有目录。",
        "archive_retire": "本应用不自动归档或删除旧备份；备份位置、保留期限和退役由运维者单独管理。"},
    {"kind": "导出", "default": "导出快照文件和历史元数据默认保留，不自动归档或退役。",
        "archive_retire": "所有者可追加策略；执行须显式操作。退役前校验并保留归档副本及账本，只移除指定导出目录。"},
    {"kind": "供应商侧副本", "default": "供应商留存按每版配置记录；没有说明时明确为未知。",
        "archive_retire": "本应用没有供应商删除接口；外部删除状态未知，不把本机退役记作供应商删除成功。"},
)


def _is_digest(value):
    return isinstance(value, str) and bool(LEDGER_ID_RE.fullmatch(value))


def _error(code, message):
    raise core.PersistenceError(code, message)


def _member_role(actor, household, *, owner_only):
    core.require_household_access(actor, household, write=True)
    role = HouseholdMember.objects.filter(household=household, user=actor).values_list("role", flat=True).first()
    if role not in (("owner",) if owner_only else ("owner", "reviewer")):
        _error("permission_denied", "该家庭成员不能执行此操作。")


def _household(actor, household_id, *, owner_only):
    household = records.household(actor, household_id, write=True)
    _member_role(actor, household, owner_only=owner_only)
    return household


@transaction.atomic
def operations_index(actor):
    """Return only households in which this active account is a member."""
    if not actor or not actor.pk or not actor.is_active:
        _error("permission_denied", "需要有效的家庭成员账号。")
    memberships = HouseholdMember.objects.filter(user=actor, household__isnull=False,
        user__is_active=True).select_related("household").order_by("household_id")
    return {"households": [{"household": row.household, "role": row.role}
        for row in memberships]}


def _clean_reason(reason):
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 1000 or "\x00" in reason:
        _error("invalid_input", "请填写有效的说明（最多 1000 字）。")
    return reason.strip()


@transaction.atomic
def retention_policy_detail(actor, household_id):
    household = _household(actor, household_id, owner_only=True)
    history = list(RetentionPolicyRevision.objects.filter(household=household).order_by("revision_no"))
    current = history[-1] if history else None
    return {"household": household, "current": current,
        "archive_after_days": current.archive_after_days if current else None,
        "delete_after_days": current.delete_after_days if current else None,
        "history": history, "default_policy": current is None,
        "data_lifecycle_policy": DATA_LIFECYCLE_POLICY}


@transaction.atomic
def append_retention_policy(actor, household_id, *, archive_after_days, delete_after_days, reason, request_key):
    household = _household(actor, household_id, owner_only=True)
    reason = _clean_reason(reason)
    for value in (archive_after_days, delete_after_days):
        if value is not None and (type(value) is not int or not 0 <= value <= 36500):
            _error("invalid_input", "保留天数须为空或介于 0 到 36500。")
    if delete_after_days is not None and (archive_after_days is None or delete_after_days < archive_after_days):
        _error("invalid_input", "到期删除前必须启用更早或同日的归档。")
    try:
        request_key = UUID(str(request_key))
    except (TypeError, ValueError, AttributeError) as exc:
        raise core.PersistenceError("invalid_input", "请求键无效。") from exc
    fingerprint = core._digest({"archive_after_days": archive_after_days,
        "delete_after_days": delete_after_days, "reason": reason})
    previous_request = RetentionPolicyRevision.objects.filter(
        household=household, request_key=request_key).first()
    if previous_request:
        if previous_request.created_by_id != actor.pk or previous_request.request_hash != fingerprint:
            _error("request_conflict", "该请求键已用于不同内容或账号。")
        return previous_request
    latest = RetentionPolicyRevision.objects.filter(household=household).order_by("-revision_no").first()
    row = RetentionPolicyRevision.objects.create(household=household,
        revision_no=(latest.revision_no + 1 if latest else 1), previous=latest,
        archive_after_days=archive_after_days, delete_after_days=delete_after_days,
        reason=reason, request_key=request_key, request_hash=fingerprint, created_by=actor)
    logger.info("local retention policy saved household=%s revision=%s archive_after_days=%s delete_after_days=%s originals=retain domain_history=retain model_proposals=retain provider_retention=unknown",
        household.pk, row.revision_no, archive_after_days, delete_after_days)
    return row


@transaction.atomic
def work_timing_context(actor, household_id):
    household = _household(actor, household_id, owner_only=False)
    questions = list(EntityRecord.objects.filter(household=household, kind="question",
        published_revision__isnull=False, published_revision__review_projection__state="accepted")
        .select_related("head_revision", "published_revision").order_by("stable_id"))
    question_choices, question_heads = [], {}
    for row in questions:
        revision = row.published_revision
        question_heads[revision.pk] = {"entity_id": row.pk, "head_revision_id": row.head_revision_id}
        title = revision.payload.get("working_text") or revision.payload.get("printed_text") or "题干待补"
        question_choices.append((revision.pk, f"{title[:100]} · 题目版本 {revision.revision_no}"))

    attempts = list(EntityRecord.objects.filter(household=household, kind="attempt",
        head_revision__isnull=False).select_related("head_revision").order_by("stable_id"))
    attempt_choices, attempt_heads = [], {}
    for row in attempts:
        revision = row.head_revision
        question_revision_id = revision.payload.get("question_revision_id")
        if revision.payload.get("state") != "active" or question_revision_id not in question_heads:
            continue
        attempt_heads[revision.pk] = {"entity_id": row.pk, "head_revision_id": row.head_revision_id,
            "question_revision_id": question_revision_id}
        source_label = {"independent_answer": "独立作答", "assisted_answer": "提示后作答",
            "classroom_note": "课堂笔记", "copied_work": "抄录", "unknown": "来源未知"}.get(
                revision.payload.get("source_kind"), "来源未知")
        actual_date = revision.payload.get("actual_date") or "日期未知"
        attempt_choices.append((revision.pk,
            f"{source_label} · {actual_date} · 作答版本 {revision.revision_no} · {row.stable_id[-8:]}"))
    signed_context = records.sign_context(household.pk, "operations", "work-timing", "create",
        {"question_heads": question_heads, "attempt_heads": attempt_heads})
    history = list(WorkTiming.objects.filter(household=household)
        .select_related("question_revision", "attempt_revision", "recorded_by")[:100])
    return {"household": household, "question_choices": question_choices,
        "attempt_choices": attempt_choices, "attempt_question_map": attempt_heads,
        "context_token": signed_context, "history": history}


@transaction.atomic
def record_work_timing(actor, household_id, *, question_revision_id, attempt_revision_id=None,
                       kind, seconds, reason, context_token, request_key):
    household = _household(actor, household_id, owner_only=False)
    reason = _clean_reason(reason)
    if kind not in WorkTiming.Kind.values:
        _error("invalid_input", "耗时类型无效。")
    if type(seconds) is not int or not 1 <= seconds <= MAX_TIMING_SECONDS:
        _error("invalid_input", "人工估计秒数须介于 1 秒和 7 天。")
    try:
        question_revision_id = str(question_revision_id)
        attempt_revision_id = str(attempt_revision_id) if attempt_revision_id else None
        request_key = UUID(str(request_key))
    except (TypeError, ValueError, AttributeError) as exc:
        raise core.PersistenceError("invalid_input", "题目版本、作答版本或请求键无效。") from exc
    fingerprint = core._digest({"question_revision_id": question_revision_id,
        "attempt_revision_id": attempt_revision_id, "kind": kind, "seconds": seconds, "reason": reason})
    previous_request = WorkTiming.objects.filter(household=household, request_key=request_key).first()
    if previous_request:
        if previous_request.recorded_by_id != actor.pk or previous_request.request_hash != fingerprint:
            _error("request_conflict", "该请求键已用于不同内容或账号。")
        return previous_request
    try:
        context = records.read_context(context_token, household.pk, "operations", "work-timing", "create")
    except core.PersistenceError:
        raise
    expected_question = context.get("question_heads", {}).get(question_revision_id)
    question = RevisionRecord.objects.select_related("entity").filter(
        pk=question_revision_id, entity__household=household, entity__kind="question").first()
    if (not isinstance(expected_question, dict) or question is None
            or question.entity.published_revision_id != question.pk
            or question.entity.head_revision_id != expected_question.get("head_revision_id")
            or question.entity.pk != expected_question.get("entity_id")):
        _error("stale_context", "题目版本已改变或不再是当前发布版本，请刷新后重试。")
    attempt = None
    if attempt_revision_id:
        expected_attempt = context.get("attempt_heads", {}).get(attempt_revision_id)
        attempt = RevisionRecord.objects.select_related("entity").filter(
            pk=attempt_revision_id, entity__household=household, entity__kind="attempt").first()
        if (not isinstance(expected_attempt, dict) or attempt is None
                or attempt.entity.head_revision_id != attempt.pk
                or attempt.entity.head_revision_id != expected_attempt.get("head_revision_id")
                or attempt.entity.pk != expected_attempt.get("entity_id")
                or attempt.payload.get("question_revision_id") != question.pk
                or expected_attempt.get("question_revision_id") != question.pk
                or attempt.payload.get("state") != "active"):
            _error("stale_context", "作答版本已改变，或与所选精确题目版本不符。")
    return WorkTiming.objects.create(household=household, question_revision=question,
        attempt_revision=attempt, kind=kind, seconds=seconds, reason=reason,
        request_key=request_key, request_hash=fingerprint, recorded_by=actor)


def _data_root():
    if not settings.SWB_DATA_ROOT:
        _error("unsafe_storage", "请先显式配置私有资料目录。")
    configured = Path(settings.SWB_DATA_ROOT)
    if configured.is_symlink():
        _error("unsafe_storage", "资料目录不能是符号链接。")
    root = configured.resolve()
    if not root.is_dir() or root.stat().st_mode & 0o077:
        _error("unsafe_storage", "资料目录必须为权限 0700 的私有目录。")
    return root


def _household_key(household_id):
    return hashlib.sha256(str(household_id).encode("utf-8")).hexdigest()[:24]


def _checked_directory(root, key, prefix):
    relative = PurePosixPath(key)
    if (relative.is_absolute() or not relative.parts or ".." in relative.parts
            or "\\" in key or not key.startswith(prefix)):
        _error("unsafe_storage", "导出路径不符合受控存储前缀。")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _error("unsafe_storage", "导出路径不能包含符号链接。")
    resolved = cursor.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        _error("missing_asset", "导出快照目录不存在或路径无效。")
    return resolved


def _snapshot_directory(snapshot):
    root = _data_root()
    prefix = f"prints/{_household_key(snapshot.household_id)}/"
    return root, _checked_directory(root, snapshot.storage_key, prefix)


def _private_subdirectory(root, key, prefix):
    relative = PurePosixPath(key)
    if (relative.is_absolute() or not relative.parts or ".." in relative.parts
            or "\\" in key or not (key == prefix.rstrip("/") or key.startswith(prefix))):
        _error("unsafe_storage", "目标路径不符合受控私有目录前缀。")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _error("unsafe_storage", "受控目录不能包含符号链接。")
        if not cursor.exists():
            cursor.mkdir(mode=0o700)
        if not cursor.is_dir() or cursor.stat().st_mode & 0o077:
            _error("unsafe_storage", "受控目录必须为权限 0700 的私有目录。")
    return cursor


def _snapshot_hashes(directory, expected_manifest_sha):
    if directory.is_symlink():
        _error("unsafe_storage", "快照目录不能为符号链接。")
    try:
        raw_manifest = (directory / "snapshot.json").read_bytes()
        if digest(raw_manifest) != expected_manifest_sha:
            _error("asset_changed", "导出清单哈希与数据库不符。")
        manifest = verify_snapshot(directory)
        expected = set(manifest["files"]) | {"snapshot.json"}
        actual = set()
        for path in directory.rglob("*"):
            if path.is_symlink():
                _error("unsafe_storage", "快照文件不能包含符号链接。")
            if path.is_file():
                if not stat.S_ISREG(path.stat().st_mode):
                    _error("unsafe_storage", "快照仅允许普通文件。")
                actual.add(path.relative_to(directory).as_posix())
        if actual != expected:
            _error("invalid_snapshot", "快照存在清单以外或缺失的文件。")
        hashes = {name: digest((directory / name).read_bytes()) for name in sorted(actual)}
        for name, record in manifest["files"].items():
            if hashes[name] != record["sha256"]:
                _error("asset_changed", "导出文件校验失败。")
        return hashes
    except (OSError, KeyError, TypeError, ValueError, ExportError) as exc:
        if isinstance(exc, core.PersistenceError):
            raise
        raise core.PersistenceError("invalid_snapshot", "导出快照缺失或无法通过完整性验证。") from exc


def _archive_key(snapshot):
    return (f"retention-archive/{_household_key(snapshot.household_id)}/"
        f"{snapshot.pk}-{snapshot.export_id}")


def _archive_directory(root, key, snapshot):
    return _checked_directory(root, key,
        f"retention-archive/{_household_key(snapshot.household_id)}/")


def _copy_archive(snapshot, reason, actor):
    root, source = _snapshot_directory(snapshot)
    source_hashes = _snapshot_hashes(source, snapshot.manifest_sha256)
    key = _archive_key(snapshot)
    destination_path = root / key
    _private_subdirectory(root, str(PurePosixPath(key).parent),
        f"retention-archive/{_household_key(snapshot.household_id)}/")
    if destination_path.exists() or destination_path.is_symlink():
        destination = _archive_directory(root, key, snapshot)
    else:
        shutil.copytree(source, destination_path)
        for directory in sorted((path for path in destination_path.rglob("*") if path.is_dir()),
                                key=lambda path: len(path.parts), reverse=True):
            directory.chmod(0o700)
        destination_path.chmod(0o700)
        for path in destination_path.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
        destination = _archive_directory(root, key, snapshot)
    archive_hashes = _snapshot_hashes(destination, snapshot.manifest_sha256)
    archive_sha256 = digest(canonical(archive_hashes))
    if source_hashes != archive_hashes:
        _error("asset_changed", "归档副本与原快照校验不一致。")
    archive, created = ExportArchiveRecord.objects.get_or_create(snapshot=snapshot,
        defaults={"household_id": snapshot.household_id, "source_storage_key": snapshot.storage_key,
            "archive_storage_key": key, "manifest_sha256": snapshot.manifest_sha256,
            "archive_sha256": archive_sha256, "file_hashes": archive_hashes,
            "reason": reason, "archived_by": actor})
    if (not created and (archive.source_storage_key != snapshot.storage_key
            or archive.archive_storage_key != key or archive.manifest_sha256 != snapshot.manifest_sha256
            or archive.archive_sha256 != archive_sha256 or archive.file_hashes != archive_hashes)):
        _error("retention_conflict", "已有归档记录与本地文件不一致，停止处理。")
    return archive


def _verify_archive(snapshot, archive):
    root = _data_root()
    if (archive.household_id != snapshot.household_id
            or archive.source_storage_key != snapshot.storage_key
            or archive.manifest_sha256 != snapshot.manifest_sha256):
        _error("retention_conflict", "归档记录与导出快照不一致。")
    directory = _archive_directory(root, archive.archive_storage_key, snapshot)
    hashes = _snapshot_hashes(directory, archive.manifest_sha256)
    if hashes != archive.file_hashes or digest(canonical(hashes)) != archive.archive_sha256:
        _error("asset_changed", "受控归档副本哈希与不可变归档记录不符。")
    return directory


@transaction.atomic
def retirement_candidates(actor, household_id, *, now=None):
    household = _household(actor, household_id, owner_only=True)
    now = now or timezone.now()
    latest = RetentionPolicyRevision.objects.filter(household=household).order_by("-revision_no").first()
    archive_days = latest.archive_after_days if latest else None
    delete_days = latest.delete_after_days if latest else None
    rows = ExportSnapshot.objects.filter(household=household).order_by("created_at", "pk")
    result = []
    for snapshot in rows:
        age = max(0, (now - snapshot.created_at).days)
        retired = ExportRetirementRecord.objects.filter(snapshot=snapshot).first()
        archived = ExportArchiveRecord.objects.filter(snapshot=snapshot).first()
        if retired is not None:
            result.append({"snapshot": snapshot, "age_days": age, "action": "already_retired",
                "archive_storage_key": retired.archive_storage_key})
        elif delete_days is not None and age >= delete_days:
            result.append({"snapshot": snapshot, "age_days": age, "action": "retire_after_archive",
                "archive_storage_key": archived.archive_storage_key if archived else _archive_key(snapshot)})
        elif archive_days is not None and age >= archive_days and archived is None:
            result.append({"snapshot": snapshot, "age_days": age, "action": "archive",
                "archive_storage_key": _archive_key(snapshot)})
    return {"household_id": household.pk, "policy_revision": latest,
        "archive_after_days": archive_days, "delete_after_days": delete_days,
        "default_policy": latest is None, "candidates": result,
        "retained_categories": ["原始照片", "领域修订历史", "模型提案"],
        "provider_retention": "unknown; this local operation does not request or prove provider-side deletion"}


@transaction.atomic
def archive_export_snapshot(actor, household_id, snapshot_id, *, reason):
    household = _household(actor, household_id, owner_only=True)
    reason = _clean_reason(reason)
    snapshot = ExportSnapshot.objects.select_for_update().filter(pk=snapshot_id, household=household).first()
    if snapshot is None:
        _error("not_found", "导出快照不存在。")
    archive = _copy_archive(snapshot, reason, actor)
    logger.info("export snapshot archived household=%s snapshot=%s storage_key=%s archive_key=%s manifest_sha256=%s originals=retain domain_history=retain model_proposals=retain provider_retention=unknown",
        household.pk, snapshot.pk, snapshot.storage_key, archive.archive_storage_key, archive.manifest_sha256)
    return archive


@transaction.atomic
def retire_export_snapshot(actor, household_id, snapshot_id, *, reason):
    household = _household(actor, household_id, owner_only=True)
    reason = _clean_reason(reason)
    snapshot = ExportSnapshot.objects.select_for_update().filter(pk=snapshot_id, household=household).first()
    if snapshot is None:
        _error("not_found", "导出快照不存在。")
    archive = ExportArchiveRecord.objects.filter(snapshot=snapshot).first()
    if archive is None:
        archive = _copy_archive(snapshot, reason, actor)
    _verify_archive(snapshot, archive)
    retired, created = ExportRetirementRecord.objects.get_or_create(snapshot=snapshot,
        defaults={"household": household, "storage_key": snapshot.storage_key,
            "archive_storage_key": archive.archive_storage_key,
            "manifest_sha256": archive.manifest_sha256, "archive_sha256": archive.archive_sha256,
            "file_hashes": archive.file_hashes, "reason": reason, "retired_by": actor})
    if (not created and (retired.storage_key != snapshot.storage_key
            or retired.archive_storage_key != archive.archive_storage_key
            or retired.manifest_sha256 != archive.manifest_sha256
            or retired.archive_sha256 != archive.archive_sha256
            or retired.file_hashes != archive.file_hashes)):
        _error("retention_conflict", "已有退役账本与当前归档不一致。")
    transaction.on_commit(lambda: _delete_original_if_present(snapshot))
    logger.info("export snapshot retired household=%s snapshot=%s storage_key=%s archive_key=%s archive_sha256=%s actor=%s originals=retain domain_history=retain model_proposals=retain provider_retention=unknown",
        household.pk, snapshot.pk, retired.storage_key, retired.archive_storage_key,
        retired.archive_sha256, actor.pk)
    return retired


def _delete_original_if_present(snapshot):
    root = _data_root()
    prefix = f"prints/{_household_key(snapshot.household_id)}/"
    relative = PurePosixPath(snapshot.storage_key)
    path = root.joinpath(*relative.parts)
    if not path.exists() and not path.is_symlink():
        return
    source = _checked_directory(root, snapshot.storage_key, prefix)
    _snapshot_hashes(source, snapshot.manifest_sha256)
    shutil.rmtree(source)


@transaction.atomic
def retire_expired_exports(actor, household_id, *, reason, now=None):
    preview = retirement_candidates(actor, household_id, now=now)
    _clean_reason(reason)
    results = []
    for item in preview["candidates"]:
        snapshot = item["snapshot"]
        if item["action"] == "archive":
            results.append(archive_export_snapshot(actor, household_id, snapshot.pk, reason=reason))
        elif item["action"] == "retire_after_archive":
            results.append(retire_export_snapshot(actor, household_id, snapshot.pk, reason=reason))
        elif item["action"] == "already_retired":
            _delete_original_if_present(snapshot)
            results.append(ExportRetirementRecord.objects.get(snapshot=snapshot))
    return results


@transaction.atomic
def snapshot_availability(actor, snapshot_id):
    snapshot = ExportSnapshot.objects.filter(pk=snapshot_id).first()
    if snapshot is None:
        _error("not_found", "导出快照不存在。")
    records.household(actor, snapshot.household_id)
    retirement = ExportRetirementRecord.objects.filter(snapshot=snapshot).first()
    if retirement:
        return {"status": "retired", "retirement": retirement}
    archive = ExportArchiveRecord.objects.filter(snapshot=snapshot).first()
    return {"status": "archived" if archive else "active", "archive": archive}


@transaction.atomic
def export_retirement_ledger(actor, household_id):
    household = _household(actor, household_id, owner_only=True)
    entries = list(ExportRetirementRecord.objects.filter(household=household)
        .select_related("snapshot", "retired_by").order_by("retired_at", "pk"))
    payload = {"schema_version": "study-workbench.retirement-ledger.v1",
        "household_id": str(household.pk), "generated_at": timezone.now().isoformat(),
        "entries": [{"retirement_id": row.pk, "snapshot_export_id": row.snapshot.export_id,
            "snapshot_id": row.snapshot_id, "storage_key": row.storage_key,
            "archive_storage_key": row.archive_storage_key,
            "manifest_sha256": row.manifest_sha256, "archive_sha256": row.archive_sha256,
            "file_hashes": row.file_hashes, "reason": row.reason,
            "retired_by_id": row.retired_by_id, "retired_at": row.retired_at.isoformat()}
            for row in entries]}
    raw = canonical(payload)
    ledger_id = digest(raw)
    root = _data_root()
    key = f"retention-ledgers/{_household_key(household.pk)}/ledger-{ledger_id}.json"
    directory = _private_subdirectory(root, f"retention-ledgers/{_household_key(household.pk)}",
        f"retention-ledgers/{_household_key(household.pk)}/")
    path = directory / f"ledger-{ledger_id}.json"
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            _error("retention_conflict", "现有退役账本内容不一致。")
    else:
        write_private(path, raw)
    return {"ledger_id": ledger_id, "storage_key": key, "sha256": ledger_id,
        "entries": len(entries), "household_id": str(household.pk)}


@transaction.atomic
def verify_retirement_ledger(actor, household_id, *, ledger_id):
    household = _household(actor, household_id, owner_only=True)
    if not isinstance(ledger_id, str) or not LEDGER_ID_RE.fullmatch(ledger_id):
        _error("invalid_input", "账本 ID 无效。")
    root = _data_root()
    key = f"retention-ledgers/{_household_key(household.pk)}/ledger-{ledger_id}.json"
    path = root / key
    cursor = root
    for part in PurePosixPath(key).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _error("unsafe_storage", "退役账本路径不能包含符号链接。")
    try:
        if not path.is_file() or path.stat().st_mode & 0o077:
            _error("unsafe_storage", "退役账本须为权限 0600 的普通私有文件。")
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise core.PersistenceError("missing_ledger", "指定的本机退役账本缺失或无效。") from exc
    if (not isinstance(payload, dict) or digest(raw) != ledger_id or canonical(payload) != raw
            or payload.get("household_id") != str(household.pk)):
        _error("invalid_ledger", "退役账本校验值或家庭范围不匹配。")
    if payload.get("schema_version") != "study-workbench.retirement-ledger.v1" or not isinstance(payload.get("entries"), list):
        _error("invalid_ledger", "不支持的退役账本结构。")
    expected_keys = {"retirement_id", "snapshot_export_id", "snapshot_id", "storage_key",
        "archive_storage_key", "manifest_sha256", "archive_sha256", "file_hashes", "reason",
        "retired_by_id", "retired_at"}
    household_key = _household_key(household.pk)
    ledger_by_export = {}
    for item in payload["entries"]:
        if not isinstance(item, dict) or set(item) != expected_keys:
            _error("invalid_ledger", "退役账本条目字段缺失、多余或类型无效。")
        export_id = item["snapshot_export_id"]
        hashes = item["file_hashes"]
        if (type(item["retirement_id"]) is not int or item["retirement_id"] < 1
                or type(item["snapshot_id"]) is not int or item["snapshot_id"] < 1
                or not _is_digest(export_id)
                or not isinstance(item["reason"], str) or not item["reason"].strip()
                or type(item["retired_by_id"]) is not int or item["retired_by_id"] < 1
                or not isinstance(item["retired_at"], str) or not item["retired_at"]
                or not isinstance(hashes, dict) or set(hashes) != {
                    "document.pdf", "document.docx", "content.json", "snapshot.json"}
                or any(not isinstance(name, str) or not name or not _is_digest(sha)
                    for name, sha in hashes.items())):
            _error("invalid_ledger", "退役账本条目类型或哈希无效。")
        storage_key = item["storage_key"]
        archive_key = item["archive_storage_key"]
        for key, prefix in ((storage_key, f"prints/{household_key}/"),
                            (archive_key, f"retention-archive/{household_key}/")):
            relative = PurePosixPath(key) if isinstance(key, str) else None
            if (relative is None or relative.is_absolute() or ".." in relative.parts
                    or "\\" in key or not key.startswith(prefix)):
                _error("invalid_ledger", "退役账本包含非受控存储位置。")
        if any(not _is_digest(item[field]) for field in
                ("manifest_sha256", "archive_sha256")):
            _error("invalid_ledger", "退役账本条目摘要格式无效。")
        if export_id in ledger_by_export:
            _error("invalid_ledger", "退役账本包含重复快照身份。")
        ledger_by_export[export_id] = item
    database = list(ExportRetirementRecord.objects.filter(household=household)
        .select_related("snapshot").order_by("pk"))
    database_by_export = {row.snapshot.export_id: row for row in database}
    missing = sorted(set(ledger_by_export) - set(database_by_export))
    extra = sorted(set(database_by_export) - set(ledger_by_export))
    mismatched = []
    for export_id in sorted(set(ledger_by_export) & set(database_by_export)):
        item, row = ledger_by_export[export_id], database_by_export[export_id]
        expected = {"retirement_id": row.pk, "snapshot_id": row.snapshot_id,
            "storage_key": row.storage_key, "archive_storage_key": row.archive_storage_key,
            "manifest_sha256": row.manifest_sha256, "archive_sha256": row.archive_sha256,
            "file_hashes": row.file_hashes, "reason": row.reason, "retired_by_id": row.retired_by_id,
            "retired_at": row.retired_at.isoformat()}
        if any(item.get(key) != value for key, value in expected.items()):
            mismatched.append(export_id)
    return {"ledger_id": ledger_id, "matches": not (missing or extra or mismatched),
        "missing_from_restored_database": missing, "not_in_selected_ledger": extra,
        "mismatched": mismatched}
