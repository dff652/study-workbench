#!/usr/bin/env python3
"""Exercise a B1-to-current upgrade and a real pre-upgrade restore rollback.

All records and files are generated inside uniquely labeled synthetic Compose
projects. This script never connects an older image to a migrated database.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import uuid

import verify_container as vc


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "1c0c386"
RUN_MODEL_COPY = "COPY --chown=10001:10001 scripts/run_model_tasks.py ./scripts/run_model_tasks.py"
RETENTION_COPY = "COPY --chown=10001:10001 scripts/manage_private_retention.py ./scripts/manage_private_retention.py"


SNAPSHOT_CODE = r'''import datetime, decimal, django, hashlib, json, math, os, stat, uuid
django.setup()
from django.conf import settings
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from pathlib import Path

def normalize(value):
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        import base64
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return {"$datetime": value.isoformat()}
    if isinstance(value, decimal.Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, uuid.UUID):
        return {"$uuid": str(value)}
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"$float": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"$value": str(value)}

def encoded(value):
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False)

tables = {}
with connection.cursor() as cursor:
    table_names = sorted(connection.introspection.table_names(cursor))
    for table in table_names:
        columns = [column.name for column in connection.introspection.get_table_description(cursor, table)]
        constraints = connection.introspection.get_constraints(cursor, table)
        pk_columns = next((item["columns"] for item in constraints.values()
                           if item.get("primary_key")), None)
        if not pk_columns or not set(pk_columns).issubset(columns):
            raise SystemExit("Cannot snapshot old table without an introspected primary key: " + table)
        projection = ", ".join(connection.ops.quote_name(name) for name in columns)
        ordering = ", ".join(connection.ops.quote_name(name) for name in pk_columns)
        cursor.execute("SELECT " + projection + " FROM " + connection.ops.quote_name(table)
            + " ORDER BY " + ordering)
        row_hashes = {}
        for values in cursor.fetchall():
            row = dict(zip(columns, values))
            key = encoded([row[name] for name in pk_columns])
            row_hash = hashlib.sha256(encoded(row).encode("utf-8")).hexdigest()
            if key in row_hashes:
                raise SystemExit("Duplicate primary key while snapshotting " + table)
            row_hashes[key] = row_hash
        row_list = sorted(row_hashes.items())
        tables[table] = {
            "columns": columns,
            "primary_key_columns": list(pk_columns),
            "row_count": len(row_list),
            "table_sha256": hashlib.sha256(encoded(row_list).encode("utf-8")).hexdigest(),
            "row_sha256_by_primary_key": row_hashes,
        }

root = Path(settings.SWB_DATA_ROOT)
root_stat = root.lstat()
if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
    raise SystemExit("Private data root is not a real directory")
if (root_stat.st_uid, root_stat.st_gid, stat.S_IMODE(root_stat.st_mode)) != (10001, 10001, 0o700):
    raise SystemExit("Private data root ownership or mode changed")
files = []
for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise SystemExit("Refusing symlink in synthetic private data: " + path.relative_to(root).as_posix())
    if stat.S_ISDIR(info.st_mode):
        continue
    if not stat.S_ISREG(info.st_mode):
        raise SystemExit("Refusing non-regular synthetic private data")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    files.append({"path": path.relative_to(root).as_posix(), "size": size,
        "sha256": digest.hexdigest(), "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid, "gid": info.st_gid})

migrations = sorted([[row.app, row.name] for row in MigrationRecorder.Migration.objects.order_by("app", "name")])
state = {"tables": tables, "files": files}
print(json.dumps({"state_sha256": hashlib.sha256(encoded(state).encode("utf-8")).hexdigest(),
    "tables": tables, "files": files, "migrations": migrations}, sort_keys=True))
'''


COMPARE_OLD_ROWS_CODE = r'''import django, hashlib, json, sys
django.setup()
from django.db import connection

def normalize(value):
    import datetime, decimal, math, uuid
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        import base64
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return {"$datetime": value.isoformat()}
    if isinstance(value, decimal.Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, uuid.UUID):
        return {"$uuid": str(value)}
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"$float": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"$value": str(value)}

def encoded(value):
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False)

old = json.load(sys.stdin)
missing = []
matched = {}
with connection.cursor() as cursor:
    current_tables = set(connection.introspection.table_names(cursor))
    for table, before in old["tables"].items():
        if table not in current_tables:
            missing.append({"table": table, "reason": "table_missing"})
            continue
        columns = [column.name for column in connection.introspection.get_table_description(cursor, table)]
        old_columns = before["columns"]
        old_pk = before["primary_key_columns"]
        if not set(old_columns).issubset(columns):
            missing.append({"table": table, "reason": "old_column_missing"})
            continue
        constraints = connection.introspection.get_constraints(cursor, table)
        current_pk = next((item["columns"] for item in constraints.values()
                           if item.get("primary_key")), None)
        if current_pk != old_pk:
            missing.append({"table": table, "reason": "primary_key_changed"})
            continue
        projection = ", ".join(connection.ops.quote_name(name) for name in old_columns)
        ordering = ", ".join(connection.ops.quote_name(name) for name in old_pk)
        cursor.execute("SELECT " + projection + " FROM " + connection.ops.quote_name(table)
            + " ORDER BY " + ordering)
        rows = {}
        for values in cursor.fetchall():
            row = dict(zip(old_columns, values))
            key = encoded([row[name] for name in old_pk])
            rows[key] = hashlib.sha256(encoded(row).encode("utf-8")).hexdigest()
        expected = before["row_sha256_by_primary_key"]
        changed = [key for key, digest in expected.items() if rows.get(key) != digest]
        if changed:
            missing.append({"table": table, "reason": "old_rows_missing_or_changed", "count": len(changed)})
            continue
        matched_rows = sorted(expected.items())
        matched[table] = {"row_count": len(matched_rows),
            "table_sha256": hashlib.sha256(encoded(matched_rows).encode("utf-8")).hexdigest()}

print(json.dumps({"preserved": not missing, "tables": matched, "problems": missing}, sort_keys=True))
'''


OLD_QUESTION_CODE = r'''import django, json, sys
django.setup()
from django.contrib.auth import get_user_model
from app.persistence.models import EntityRecord, ReviewDecision, ReviewProjection
from app.web.models import MaterialPage, QuestionSource
from app.web import services as materials

payload = json.load(sys.stdin)
actor = get_user_model().objects.get(username=payload["username"])
page = MaterialPage.objects.get(pk=payload["page_id"], material__household_id=payload["household_id"])
preview = materials.preview_file(actor, page.pk, 0)
source = {"page_id": str(page.pk), "rotation": 0, "preview_sha256": preview.sha256,
    "display_bbox": [2, 2, 28, 20]}
created = materials.save_question(actor, page.material_id, printed_text="4 × 2 = ?",
    original_number="合成升级验收题", sources=[source], request_key=payload["request_key"],
    reason="B1 到当前版本的合成升级验收")
detail = materials.question_detail(actor, created["question_id"])
materials.review_question(actor, created["question_id"], created["revision_id"],
    action="accept", reason="核对合成题干与原图区域", context=detail["review_context"],
    request_key=payload["review_request_key"])
entity = EntityRecord.objects.get(kind="question", stable_id=created["question_id"])
source_row = QuestionSource.objects.get(revision_id=created["revision_id"])
state = ReviewProjection.objects.get(revision_id=created["revision_id"]).state
decision = ReviewDecision.objects.get(revision_id=created["revision_id"], action="accept")
if entity.published_revision_id != created["revision_id"] or state != "accepted":
    raise SystemExit("Synthetic B1 question was not actually accepted and published")
if not source_row.sources or not decision.reason:
    raise SystemExit("Synthetic B1 question source or review audit is incomplete")
print(json.dumps({"question_id": created["question_id"], "revision_id": created["revision_id"],
    "published_revision_id": entity.published_revision_id, "review_state": state,
    "source_count": len(source_row.sources), "review_decision_id": str(decision.pk)}, sort_keys=True))
'''


NEW_BUSINESS_RECORD_CODE = r'''import django, json, sys
django.setup()
from datetime import date, timedelta
from uuid import uuid4
from django.contrib.auth import get_user_model
from app.persistence.models import EntityRecord
from app.web import learning_services as learning
from app.study import services as study
from app.study.models import ScheduleRevision
from app.ai.models import ModelRun

payload = json.load(sys.stdin)
actor = get_user_model().objects.get(username=payload["username"])
profile = learning.create_profile(actor, payload["household_id"],
    display_name="合成升级学习者", grade="四年级", request_key=uuid4().hex)
learner = EntityRecord.objects.get(household_id=payload["household_id"],
    kind="learner", stable_id=profile["learner_id"])
context = study.new_schedule_context(actor, learner.pk)
due_date = date.today() + timedelta(days=7)
plan = study.create_schedule(actor, learner.pk, question_revision_id=payload["question_revision_id"],
    due_date=due_date, goal="验证升级后新学习计划", prompt_plan="先独立完成合成题",
    reason="新版本 schema 写入验收", context=context["context"], request_key=uuid4().hex)
schedule_events = ScheduleRevision.objects.filter(schedule_id=plan["schedule_pk"]).count()
if schedule_events != 1 or not EntityRecord.objects.filter(pk=learner.pk, kind="learner").exists():
    raise SystemExit("Current-version business record did not persist")
if ModelRun.objects.filter(household_id=payload["household_id"]).exists():
    raise SystemExit("Upgrade acceptance unexpectedly queued an AI model task")
print(json.dumps({"kind": "learner_and_study_schedule", "learner_id": learner.stable_id,
    "schedule_id": str(plan["schedule_id"]), "schedule_event_count": schedule_events,
    "due_date": due_date.isoformat(), "ai_model_runs": 0}, sort_keys=True))
'''


def compose(project, env, overlays, *args, check=True, input_text=None):
    command = ["docker", "compose", "--file", str(vc.COMPOSE_FILE)]
    for overlay in overlays:
        command.extend(("--file", str(overlay)))
    command.extend(("--project-name", project, *args))
    return vc.command(command, env=env, check=check, input_text=input_text)


def baseline_commit():
    return vc.command(["git", "rev-parse", "--verify", f"{BASELINE}^{{commit}}"]
        ).stdout.strip()


def make_old_context(temp_root, baseline_sha):
    archive = temp_root / "b1-source.tar"
    old_context = temp_root / "b1-context"
    old_context.mkdir(mode=0o700)
    vc.command(["git", "archive", "--format=tar", "--output", str(archive), baseline_sha,
        "app", "requirements.txt", "licenses", "manage.py"])
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    with tarfile.open(archive, "r:") as source:
        source.extractall(old_context, filter="data")
    archive.unlink()

    for relative in ("app/production.py", "app/health.py", "app/wsgi.py", "requirements-container.txt"):
        destination = old_context / relative
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(ROOT / relative, destination)
    entrypoint = old_context / "scripts" / "container_entrypoint.sh"
    entrypoint.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(ROOT / "scripts/container_entrypoint.sh", entrypoint)

    urls = old_context / "app/urls.py"
    url_source = urls.read_text(encoding="utf-8")
    if "from django.urls import include, path" not in url_source or "urlpatterns = [" not in url_source:
        raise RuntimeError("The extracted B1 URL configuration does not match the expected container shim")
    if "path('healthz'" not in url_source and 'path("healthz"' not in url_source:
        url_source += "\n\nfrom app.health import healthz\nurlpatterns.insert(0, path('healthz', healthz, name='healthz'))\n"
        urls.write_text(url_source, encoding="utf-8")

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    if dockerfile.count(RUN_MODEL_COPY) != 1:
        raise RuntimeError("Current Dockerfile did not have one explicit model-worker copy to remove")
    (old_context / "Dockerfile").write_text(dockerfile.replace(RUN_MODEL_COPY + "\n", "").replace(
        RETENTION_COPY + "\n", ""), encoding="utf-8")
    shutil.copy2(ROOT / "Dockerfile", temp_root / "current-Dockerfile-reference")
    overlay = temp_root / "compose-b1-overlay.json"
    overlay.write_text(json.dumps({"services": {"web": {"build": {
        "context": str(old_context), "dockerfile": "Dockerfile"}}}}, sort_keys=True) + "\n", encoding="utf-8")
    if (old_context / "scripts/run_model_tasks.py").exists():
        raise RuntimeError("B1 build context unexpectedly contains the current AI worker")
    return old_context, overlay, archive_hash


def image_metadata(image_ref):
    template = '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}} {{index .Config.Labels "com.study-workbench.resource-owner"}}'
    values = vc.command(["docker", "image", "inspect", "--format", template, image_ref]).stdout.strip().split()
    if len(values) != 3:
        raise RuntimeError("Could not read built image identity labels")
    return {"image_id": values[0], "source_revision": values[1], "resource_owner": values[2]}


def migration_names(snapshot):
    return {f"{app}.{name}" for app, name in snapshot["migrations"]}


def verify_file_snapshot(before, after, expected_hashes):
    if before["files"] != after["files"]:
        raise RuntimeError("Private uploaded file paths, SHA-256, size, mode, or ownership changed")
    hashes = {item["sha256"] for item in before["files"]}
    if not set(expected_hashes).issubset(hashes):
        raise RuntimeError("The uploaded original or rendered preview hash is missing from private storage")


def compare_upgrade_rows(project, env, before):
    result = vc.exec_python(project, env, COMPARE_OLD_ROWS_CODE, input_text=json.dumps(before, sort_keys=True))
    if not result.get("preserved"):
        raise RuntimeError("One or more pre-upgrade rows changed during migration: "
            + json.dumps(result.get("problems", []), sort_keys=True))
    expected = {name: info["table_sha256"] for name, info in before["tables"].items()}
    actual = {name: row["table_sha256"] for name, row in result["tables"].items()}
    if actual != expected:
        raise RuntimeError("Old row hashes after migration do not match the B1 snapshot")
    return result


def private_report(path, result):
    path.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def verify_upgrade():
    vc.command(["docker", "compose", "version"])
    vc.command(["docker", "image", "inspect", vc.POSTGRES_IMAGE])
    baseline_sha = baseline_commit()
    token = uuid.uuid4().hex[:16]
    main_project = f"swbup-{token}"
    rollback_project = f"swbup-restore-{token}"
    main_owner = f"swb-upgrade-{token}"
    rollback_owner = f"swb-upgrade-restore-{token}"
    old_tag = f"d1-b1-{token}"
    current_tag = f"d1-current-{token}"
    old_image = f"study-workbench:{old_tag}"
    current_image = f"study-workbench:{current_tag}"
    ports = set()
    while len(ports) < 3:
        ports.add(vc.free_loopback_port())
    main_port, _reserved, rollback_port = sorted(ports)
    secret_key = __import__("secrets").token_urlsafe(48)
    db_password = __import__("secrets").token_urlsafe(36)
    old_env = vc.compose_env(main_owner, old_tag, main_port, secret_key, db_password)
    old_env["SWB_SOURCE_REVISION"] = baseline_sha
    current_env = vc.compose_env(main_owner, current_tag, main_port, secret_key, db_password)
    current_env["SWB_SOURCE_REVISION"] = "working-tree"
    rollback_env = vc.compose_env(rollback_owner, old_tag, rollback_port, secret_key, db_password)
    rollback_env["SWB_SOURCE_REVISION"] = baseline_sha

    output = ROOT / "artifacts" / "upgrade-verification" / token
    report_path = output / "verification.local.json"
    report = {
        "status": "running", "synthetic_only": True,
        "source": {"baseline_commit": baseline_sha, "current_git_head": vc.command(
            ["git", "rev-parse", "HEAD"]).stdout.strip(), "current_source_revision": "working-tree"},
        "versions": {"b1_image": old_image, "current_image": current_image},
        "projects": {"upgrade": main_project, "rollback_restore": rollback_project},
        "rollback_boundary": {"strategy": "restore the pre-upgrade backup into a fresh isolated project",
            "older_image_on_migrated_database": False, "migrated_database_reused": False},
    }
    temp_root = Path(tempfile.mkdtemp(prefix=f"swb-upgrade-{token}-"))
    temp_root.chmod(0o700)
    preflight_complete = False
    stage = "preflight"
    cleanup_errors = []
    try:
        for project in (main_project, rollback_project):
            vc.assert_project_absent(project)
        for image_ref in (old_image, current_image):
            vc.assert_image_absent(image_ref)
        preflight_complete = True
        _, old_overlay, archive_hash = make_old_context(temp_root, baseline_sha)
        report["source"]["b1_git_archive_sha256"] = archive_hash

        stage = "b1_build"
        compose(main_project, old_env, [old_overlay], "config", "--quiet")
        compose(main_project, old_env, [old_overlay], "build", "web")
        old_image_info = image_metadata(old_image)
        if old_image_info["source_revision"] != baseline_sha or old_image_info["resource_owner"] != main_owner:
            raise RuntimeError("B1 image does not identify the fixed baseline commit and owned label")
        report["versions"]["b1_image_id"] = old_image_info["image_id"]

        stage = "b1_start"
        compose(main_project, old_env, [old_overlay], "up", "--detach", "--wait",
            "--wait-timeout", "180", "db", "web")
        vc.wait_compose_health(main_project, old_env, timeout=180)
        old_web = compose(main_project, old_env, [old_overlay], "ps", "--quiet", "web").stdout.strip()
        old_uid = vc.command(["docker", "exec", old_web, "id", "-u"]).stdout.strip()
        old_listener = vc.command(["docker", "port", old_web, "8000/tcp"]).stdout.strip()
        if old_uid != "10001" or old_listener != f"127.0.0.1:{main_port}":
            raise RuntimeError("B1 Web did not start non-root and loopback-only")
        base_url = f"http://127.0.0.1:{main_port}"
        username = f"synthetic-upgrade-{token}"
        password = __import__("secrets").token_urlsafe(24)
        bundle = json.loads(vc.FIXTURE.read_text(encoding="utf-8"))
        household_id = bundle["household_id"]
        seed_input = json.dumps({"username": username, "password": password, "bundle": bundle}, ensure_ascii=False)
        seeded = vc.exec_python(main_project, old_env, vc.SEED_CODE, input_text=seed_input)
        if not seeded.get("created") or seeded.get("review_count", 0) < 1:
            raise RuntimeError("B1 synthetic user, household, and reviewed source fixture were not created")

        stage = "b1_upload_and_review"
        browser = vc.login(base_url, username, password)
        page_path, preview_path, preview_hash, original_hash = vc.upload_from_browser(browser)
        page_id = page_path.strip("/").split("/")[1]
        question = vc.exec_python(main_project, old_env, OLD_QUESTION_CODE, input_text=json.dumps({
            "username": username, "household_id": household_id, "page_id": page_id,
            "request_key": f"upgrade-question-{token}", "review_request_key": f"upgrade-review-{token}"}, ensure_ascii=False))
        if (question.get("review_state") != "accepted" or
                question.get("published_revision_id") != question.get("revision_id") or
                question.get("source_count") != 1):
            raise RuntimeError("B1 synthetic question lacks its exact reviewed revision and original-image source")
        vc.verify_preview(browser, preview_path, preview_hash)
        before = vc.exec_python(main_project, old_env, SNAPSHOT_CODE)
        verify_file_snapshot(before, before, [original_hash, preview_hash])
        report["b1_snapshot"] = {
            "state_sha256": before["state_sha256"],
            "table_row_counts": {name: item["row_count"] for name, item in before["tables"].items()},
            "table_sha256": {name: item["table_sha256"] for name, item in before["tables"].items()},
            "migrations": before["migrations"],
            "files": before["files"], "question": question,
            "synthetic_original_sha256": original_hash, "synthetic_preview_sha256": preview_hash,
        }

        stage = "pre_upgrade_backup"
        backup_dir = temp_root / "pre-upgrade-backup"
        vc.command(["bash", "scripts/backup_service.sh", main_project, str(backup_dir)], env=old_env)
        manifest_path = backup_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backup_files = {item["path"]: item for item in manifest.get("files", [])}
        if set(backup_files) != {item["path"] for item in before["files"]}:
            raise RuntimeError("Pre-upgrade backup manifest has extra or missing private files")
        for file_record in before["files"]:
            if backup_files.get(file_record["path"]) != file_record:
                raise RuntimeError("Pre-upgrade backup manifest differs from the B1 private-file hash snapshot")
        report["pre_upgrade_backup"] = {
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "database_dump": manifest["database_dump"], "assets_archive": manifest["assets_archive"],
            "file_count": len(manifest["files"]), "directory_count": len(manifest["directories"]),
        }

        stage = "current_build"
        compose(main_project, current_env, [], "config", "--quiet")
        compose(main_project, current_env, [], "build", "web")
        current_image_info = image_metadata(current_image)
        if current_image_info["source_revision"] != "working-tree" or current_image_info["resource_owner"] != main_owner:
            raise RuntimeError("Current image does not identify the working tree and owned label")
        report["versions"]["current_image_id"] = current_image_info["image_id"]

        stage = "schema_upgrade"
        compose(main_project, old_env, [old_overlay], "stop", "--timeout", "30", "web")
        compose(main_project, current_env, [], "up", "--detach", "--wait", "--wait-timeout", "180", "web")
        vc.wait_compose_health(main_project, current_env, timeout=180)
        migrated_web = compose(main_project, current_env, [], "ps", "--quiet", "web").stdout.strip()
        current_uid = vc.command(["docker", "exec", migrated_web, "id", "-u"]).stdout.strip()
        current_listener = vc.command(["docker", "port", migrated_web, "8000/tcp"]).stdout.strip()
        if current_uid != "10001" or current_listener != f"127.0.0.1:{main_port}":
            raise RuntimeError("Current Web did not upgrade on the same private volumes with safe runtime binding")

        post_upgrade = vc.exec_python(main_project, current_env, SNAPSHOT_CODE)
        row_check = compare_upgrade_rows(main_project, current_env, before)
        verify_file_snapshot(before, post_upgrade, [original_hash, preview_hash])
        old_migrations, current_migrations = migration_names(before), migration_names(post_upgrade)
        if not old_migrations.issubset(current_migrations):
            raise RuntimeError("Current migration recorder lost pre-upgrade migration rows")
        added_migrations = sorted(current_migrations - old_migrations)
        if not added_migrations:
            raise RuntimeError("Current image did not apply any new migrations to the B1 database")
        report["upgrade"] = {
            "old_rows_preserved_before_new_login_or_writes": True,
            "old_row_state_sha256_before": before["state_sha256"],
            "old_row_state_sha256_verified_after": before["state_sha256"],
            "matched_old_table_hashes": row_check["tables"],
            "old_migrations": sorted(old_migrations), "current_migrations": sorted(current_migrations),
            "added_migrations": added_migrations,
            "private_files_unchanged": True, "private_files_after": post_upgrade["files"],
        }

        stage = "current_login_and_new_record"
        current_browser = vc.login(f"http://127.0.0.1:{main_port}", username, password)
        vc.verify_preview(current_browser, preview_path, preview_hash)
        new_record = vc.exec_python(main_project, current_env, NEW_BUSINESS_RECORD_CODE,
            input_text=json.dumps({"username": username, "household_id": household_id,
                "question_revision_id": question["revision_id"]}, ensure_ascii=False))
        if new_record.get("kind") != "learner_and_study_schedule" or new_record.get("schedule_event_count") != 1:
            raise RuntimeError("New-version learning/schedule business record did not persist")
        # The current worker must start idle: no queued ModelRun or provider/key is created by this drill.
        compose(main_project, current_env, [], "up", "--detach", "--wait", "--wait-timeout", "120", "worker")
        statuses = [json.loads(line) for line in compose(main_project, current_env, [],
            "ps", "--all", "--format", "json").stdout.splitlines() if line.strip()]
        worker_states = [item.get("State") for item in statuses if item.get("Service") == "worker"]
        if worker_states != ["running"]:
            raise RuntimeError("Current model worker did not remain idle and running")
        worker_snapshot = vc.exec_python(main_project, current_env,
            "import django,json; django.setup(); from app.ai.models import ModelRun; print(json.dumps({'model_runs':ModelRun.objects.count()}))")
        if worker_snapshot.get("model_runs") != 0:
            raise RuntimeError("No AI task should be queued or executed during the migration drill")
        report["upgrade"]["new_business_record"] = new_record
        report["upgrade"]["current_worker_state"] = worker_states[0]
        report["upgrade"]["model_runs"] = 0

        stage = "fresh_project_old_backup_restore"
        compose(main_project, current_env, [], "stop", "--timeout", "30", "web", "worker", "db")
        compose(rollback_project, rollback_env, [old_overlay], "config", "--quiet")
        compose(rollback_project, rollback_env, [old_overlay], "up", "--detach", "--wait",
            "--wait-timeout", "120", "db")
        vc.command(["bash", "scripts/restore_service.sh", rollback_project, str(backup_dir)], env=rollback_env)
        compose(rollback_project, rollback_env, [old_overlay], "up", "--detach", "--wait",
            "--wait-timeout", "180", "web")
        vc.wait_compose_health(rollback_project, rollback_env, timeout=180)
        rollback_web = compose(rollback_project, rollback_env, [old_overlay], "ps", "--quiet", "web").stdout.strip()
        restored_uid = vc.command(["docker", "exec", rollback_web, "id", "-u"]).stdout.strip()
        restored_image = vc.command(["docker", "inspect", "--format", "{{.Config.Image}}", rollback_web]).stdout.strip()
        if restored_uid != "10001" or restored_image != old_image:
            raise RuntimeError("Rollback restore did not start the recorded B1 image in a fresh project")
        restored = vc.exec_python(rollback_project, rollback_env, SNAPSHOT_CODE)
        if restored["state_sha256"] != before["state_sha256"]:
            raise RuntimeError("Fresh B1 restore does not reproduce the complete pre-upgrade database row/file hash")
        if restored["migrations"] != before["migrations"] or restored["files"] != before["files"]:
            raise RuntimeError("Fresh B1 restore changed the old migration set or private file hashes")
        restored_tables = set(restored["tables"])
        if "ai_modelconfig" in restored_tables or "study_studyschedule" in restored_tables:
            raise RuntimeError("The rollback project unexpectedly contains post-upgrade schema")
        restored_browser = vc.login(f"http://127.0.0.1:{rollback_port}", username, password)
        vc.verify_preview(restored_browser, preview_path, preview_hash)
        report["rollback_boundary"].update({
            "fresh_project": rollback_project, "restored_image": restored_image,
            "restored_image_source_revision": baseline_sha,
            "old_migration_set_restored": True, "pre_upgrade_row_state_sha256_restored": restored["state_sha256"],
            "private_file_hashes_restored": True, "restored_user_login": True,
            "restored_private_preview": True, "post_upgrade_schema_present": False,
        })
        report["status"] = "passed"
        report["checks"] = ["b1-old-image-build-and-start", "synthetic-user-household-upload-question-review",
            "pre-upgrade-backup-manifest-matches-private-files", "current-image-migrates-same-database",
            "all-pre-upgrade-row-hashes-unchanged", "login-and-original-preview-after-upgrade",
            "new-learner-schedule-record-on-new-schema", "current-idle-worker-with-no-ai-runs",
            "fresh-project-old-image-plus-old-backup-rollback", "old-login-and-preview-after-restore"]
        report["private_artifacts"] = str(report_path)
    except Exception as error:
        report["status"] = "failed"
        report["failure_stage"] = stage
        report["failure_type"] = type(error).__name__
        raise
    finally:
        if preflight_complete:
            for project, owner, env in ((rollback_project, rollback_owner, rollback_env),
                                        (main_project, main_owner, current_env)):
                try:
                    vc.cleanup_project(project, owner, env)
                except Exception as error:
                    cleanup_errors.append({"project": project, "type": type(error).__name__})
            for image_ref in (current_image, old_image):
                details = vc.command(["docker", "image", "inspect", "--format",
                    '{{index .Config.Labels "com.study-workbench.resource-owner"}} {{json .RepoTags}}',
                    image_ref], check=False)
                if details.returncode == 0:
                    parts = details.stdout.strip().split(" ", 1)
                    if len(parts) == 2 and parts[0] == main_owner and image_ref in json.loads(parts[1]):
                        removed = vc.command(["docker", "image", "rm", image_ref], check=False)
                        if removed.returncode:
                            cleanup_errors.append({"image": image_ref, "type": "image_remove_failed"})
                    else:
                        cleanup_errors.append({"image": image_ref, "type": "ownership_label_mismatch"})
        shutil.rmtree(temp_root, ignore_errors=True)
        report["cleanup_errors"] = cleanup_errors
        report["resources_removed_only_by_matching_labels"] = preflight_complete and not cleanup_errors
        try:
            private_report(report_path, report)
        except Exception as report_error:
            print(f"Could not write the private upgrade report ({type(report_error).__name__})", file=os.sys.stderr)


if __name__ == "__main__":
    verify_upgrade()
