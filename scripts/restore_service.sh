#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE=""
if [[ "${1:-}" == "--env-file" ]]; then
    [[ $# -ge 3 ]] || { echo "Usage: $0 [--env-file FILE] PROJECT BACKUP_DIRECTORY" >&2; exit 2; }
    ENV_FILE="$(realpath -- "$2")"
    shift 2
fi
[[ $# == 2 ]] || { echo "Usage: $0 [--env-file FILE] PROJECT BACKUP_DIRECTORY" >&2; exit 2; }
PROJECT="$1"
BACKUP_INPUT="$2"
case "$PROJECT" in
    ''|[!a-z0-9]*|*[!a-z0-9_-]*) echo "Invalid Compose project name" >&2; exit 2 ;;
esac
RESOURCE_OWNER="${SWB_RESOURCE_OWNER:-manual}"

if [[ -n "$ENV_FILE" ]]; then
    compose() { docker compose --env-file "$ENV_FILE" --project-name "$PROJECT" --file "$ROOT/compose.yaml" "$@"; }
else
    compose() { docker compose --project-name "$PROJECT" --file "$ROOT/compose.yaml" "$@"; }
fi

RESOURCE_OWNER="$(compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["web"]["labels"]["com.study-workbench.resource-owner"])')"

BACKUP="$(cd -- "$(dirname -- "$BACKUP_INPUT")" && pwd -P)/$(basename -- "$BACKUP_INPUT")"
[[ -d "$BACKUP" && ! -L "$BACKUP" ]] || { echo "Backup directory is missing or is a symlink" >&2; exit 2; }

python3 - "$BACKUP" <<'PY'
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile

backup = Path(sys.argv[1])
if backup.stat().st_mode & 0o077:
    raise SystemExit("Refusing a backup directory accessible by group or other users")
for name in ("database.dump", "assets.tar.gz", "manifest.json"):
    path = backup / name
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise SystemExit(f"Refusing a missing, linked, or non-private backup file: {name}")

manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
if not isinstance(manifest, dict) or manifest.get("format") != "study-workbench-backup/v1":
    raise SystemExit("Unsupported backup manifest")

data_root_metadata = manifest.get("data_root")
if not isinstance(data_root_metadata, dict) or data_root_metadata != {"mode": 0o700, "uid": 10001, "gid": 10001}:
    raise SystemExit("Backup private data root has unsupported mode or ownership")

def file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"size": size, "sha256": digest.hexdigest()}

for name, field in (("database.dump", "database_dump"), ("assets.tar.gz", "assets_archive")):
    if manifest.get(field) != file_digest(backup / name):
        raise SystemExit(f"Backup checksum mismatch: {name}")

def safe_name(raw):
    if not isinstance(raw, str) or "\\" in raw or raw.startswith("/"):
        raise SystemExit("Unsafe path in backup")
    parsed = PurePosixPath(raw)
    if any(part == ".." for part in parsed.parts):
        raise SystemExit("Unsafe path in backup")
    parts = [part for part in parsed.parts if part not in ("", ".")]
    return "/".join(parts) if parts else "."

def metadata_map(items, *, directory):
    if not isinstance(items, list):
        raise SystemExit("Malformed private asset manifest")
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise SystemExit("Malformed private asset manifest entry")
        name = safe_name(item.get("path"))
        mode = item.get("mode")
        if name == "." or type(mode) is not int or not 0 <= mode <= 0o777:
            raise SystemExit("Unsafe path or mode in private asset manifest")
        if item.get("uid") != 10001 or item.get("gid") != 10001:
            raise SystemExit("Private asset manifest has unsupported ownership")
        if mode & (0o077 | 0o7000):
            raise SystemExit("Private asset manifest has unsafe permissions")
        if not directory and (type(item.get("size")) is not int or item["size"] < 0
                              or not isinstance(item.get("sha256"), str)):
            raise SystemExit("Malformed private file metadata")
        if name in result:
            raise SystemExit("Duplicate asset paths in backup manifest")
        result[name] = item
    return result

expected_files = metadata_map(manifest.get("files", []), directory=False)
expected_dirs = metadata_map(manifest.get("directories", []), directory=True)
if len(expected_files) != len(manifest.get("files", [])) or len(expected_dirs) != len(manifest.get("directories", [])):
    raise SystemExit("Duplicate asset paths in backup manifest")
if set(expected_files) & set(expected_dirs):
    raise SystemExit("Asset path has conflicting file and directory entries")
for name in (*expected_files, *expected_dirs):
    parts = name.split("/")
    for depth in range(1, len(parts)):
        parent = "/".join(parts[:depth])
        if parent not in expected_dirs:
            raise SystemExit(f"Private asset manifest omits a parent directory: {parent}")

archive = backup / "assets.tar.gz"
members = {}
with tarfile.open(archive, "r:gz") as tar:
    for member in tar.getmembers():
        name = safe_name(member.name)
        if name == "." and member.isdir():
            continue
        if name in members or member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise SystemExit("Unsafe or duplicate file entry in backup archive")
        if member.isfile():
            expected = expected_files.get(name)
            if (not expected or expected.get("size") != member.size
                    or expected.get("mode") != member.mode):
                raise SystemExit(f"Unlisted or mismatched asset in backup: {name}")
            source = tar.extractfile(member)
            if source is None:
                raise SystemExit(f"Unreadable asset in backup: {name}")
            digest = hashlib.sha256()
            size = 0
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
            if size != member.size or digest.hexdigest() != expected.get("sha256"):
                raise SystemExit(f"Asset checksum mismatch: {name}")
        elif member.isdir():
            expected = expected_dirs.get(name)
            if not expected or expected.get("mode") != member.mode:
                raise SystemExit(f"Unlisted directory in backup: {name}")
        else:
            raise SystemExit("Unsupported asset type in backup")
        members[name] = member
if {name for name, member in members.items() if member.isfile()} != set(expected_files):
    raise SystemExit("Backup archive and file manifest do not match")
if {name for name, member in members.items() if member.isdir()} != set(expected_dirs):
    raise SystemExit("Backup archive and directory manifest do not match")

print(f"Verified backup: {len(expected_files)} files, {len(expected_dirs)} directories")
PY

owned_service() {
    local service="$1" id details
    id="$(compose ps --all --quiet "$service")"
    [[ -n "$id" && "$id" != *$'\n'* ]] || { echo "Expected one $service container in project $PROJECT" >&2; return 1; }
    details="$(docker inspect --format '{{index .Config.Labels "com.study-workbench.resource-owner"}} {{index .Config.Labels "com.docker.compose.project"}}' "$id")"
    [[ "$details" == "$RESOURCE_OWNER $PROJECT" ]] || { echo "Refusing service $service with a mismatched owner or project label" >&2; return 1; }
    printf '%s\n' "$id"
}

DB_ID="$(owned_service db)"
compose ps --status running --quiet db | grep -Fxq "$DB_ID" || { echo "Start only the target database first with 'docker compose up -d db'" >&2; exit 1; }
if compose ps --status running --services | grep -Fxq web; then
    echo "Refusing restore while the target web writer is running; stop it first" >&2
    exit 1
fi
if compose config --services | grep -Fxq worker; then
    worker_ids="$(compose ps --all --quiet worker)"
    while IFS= read -r id; do
        [[ -n "$id" ]] || continue
        details="$(docker inspect --format '{{index .Config.Labels "com.study-workbench.resource-owner"}} {{index .Config.Labels "com.docker.compose.project"}}' "$id")"
        [[ "$details" == "$RESOURCE_OWNER $PROJECT" ]] || {
            echo "Refusing worker with a mismatched owner or project label" >&2
            exit 1
        }
    done <<< "$worker_ids"
    if [[ -n "$(compose ps --status running --quiet worker)" ]]; then
        echo "Refusing restore while the target worker writer is running; stop it first" >&2
        exit 1
    fi
fi

RELATIONS="$(compose exec --no-TTY db sh -eu -c 'exec psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align' <<'SQL'
SELECT CASE WHEN
    EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname !~ '^pg_' AND namespace.nspname <> 'information_schema'
    )
    OR EXISTS (
        SELECT 1 FROM pg_namespace
        WHERE nspname !~ '^pg_' AND nspname NOT IN ('information_schema', 'public')
    )
    OR EXISTS (SELECT 1 FROM pg_largeobject_metadata)
    OR EXISTS (SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql')
    THEN 1 ELSE 0 END;
SQL
)"
[[ "$RELATIONS" == "0" ]] || { echo "Refusing restore into a non-empty database" >&2; exit 1; }

if ! compose run --no-deps --rm --no-TTY --entrypoint python web - >/dev/null <<'PY'
import os
from pathlib import Path
import sys

root = Path(os.environ["SWB_DATA_ROOT"])
sys.exit(0 if root.is_dir() and not any(root.iterdir()) else 1)
PY
then
    echo "Refusing restore into a non-empty private data volume" >&2
    exit 1
fi

RESTORE_HELPER="$(cat <<'PY'
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tarfile
import uuid

if (os.getuid(), os.getgid()) != (10001, 10001):
    raise SystemExit("Restore helper is not running as the application uid/gid")
stream = sys.stdin.buffer
try:
    manifest_size = int(stream.readline())
except ValueError as error:
    raise SystemExit("Missing streamed backup manifest length") from error
if not 0 < manifest_size <= 64 * 1024 * 1024:
    raise SystemExit("Invalid streamed backup manifest length")
manifest_raw = stream.read(manifest_size)
if len(manifest_raw) != manifest_size:
    raise SystemExit("Incomplete streamed backup manifest")
manifest = json.loads(manifest_raw)
if not isinstance(manifest, dict) or manifest.get("format") != "study-workbench-backup/v1":
    raise SystemExit("Unsupported streamed backup manifest")
if manifest.get("data_root") != {"mode": 0o700, "uid": 10001, "gid": 10001}:
    raise SystemExit("Streamed backup root has unsupported mode or ownership")

def safe_name(raw):
    if not isinstance(raw, str) or "\\" in raw or raw.startswith("/"):
        raise SystemExit("Unsafe path in streamed backup")
    parsed = PurePosixPath(raw)
    if any(part == ".." for part in parsed.parts):
        raise SystemExit("Unsafe path in streamed backup")
    parts = [part for part in parsed.parts if part not in ("", ".")]
    return "/".join(parts) if parts else "."

def metadata_map(items, *, directory):
    if not isinstance(items, list):
        raise SystemExit("Malformed streamed asset manifest")
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise SystemExit("Malformed streamed asset entry")
        name = safe_name(item.get("path"))
        mode = item.get("mode")
        if name == "." or type(mode) is not int or not 0 <= mode <= 0o777:
            raise SystemExit("Unsafe path or mode in streamed asset manifest")
        if item.get("uid") != 10001 or item.get("gid") != 10001 or mode & (0o077 | 0o7000):
            raise SystemExit("Streamed asset manifest has unsupported mode or ownership")
        if not directory and (type(item.get("size")) is not int or item["size"] < 0
                              or not isinstance(item.get("sha256"), str)):
            raise SystemExit("Malformed streamed file metadata")
        if name in result:
            raise SystemExit("Duplicate path in streamed asset manifest")
        result[name] = item
    return result

expected_files = metadata_map(manifest.get("files", []), directory=False)
expected_dirs = metadata_map(manifest.get("directories", []), directory=True)
if set(expected_files) & set(expected_dirs):
    raise SystemExit("Streamed asset path has conflicting file and directory entries")
for name in (*expected_files, *expected_dirs):
    parts = name.split("/")
    for depth in range(1, len(parts)):
        parent = "/".join(parts[:depth])
        if parent not in expected_dirs:
            raise SystemExit(f"Streamed asset manifest omits a parent directory: {parent}")
target = Path(os.environ["SWB_DATA_ROOT"])
target_stat = target.lstat()
if not stat.S_ISDIR(target_stat.st_mode) or (target_stat.st_uid, target_stat.st_gid) != (10001, 10001):
    raise SystemExit("Private data root has unexpected type or owner")
if stat.S_IMODE(target_stat.st_mode) != manifest["data_root"]["mode"]:
    raise SystemExit("Private data root mode differs from the backup manifest")
if any(target.iterdir()):
    raise SystemExit("Private data volume is no longer empty")

stage = target / f".restore-{uuid.uuid4().hex}"
while stage.name in expected_files or stage.name in expected_dirs:
    stage = target / f".restore-{uuid.uuid4().hex}"
stage.mkdir(mode=0o700)
seen_files = set()
seen_dirs = set()
committed = False
try:
    for name in sorted(expected_dirs, key=lambda value: (value.count("/"), value)):
        (stage / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for member in archive:
            name = safe_name(member.name)
            if name == "." and member.isdir():
                continue
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise SystemExit("Refusing a link or special file in streamed archive")
            if member.isfile():
                expected = expected_files.get(name)
                if (not expected or name in seen_files or expected["size"] != member.size
                        or expected["mode"] != member.mode):
                    raise SystemExit(f"Unlisted or mismatched streamed asset: {name}")
                source = archive.extractfile(member)
                if source is None:
                    raise SystemExit(f"Unreadable streamed asset: {name}")
                destination = stage / name
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                                     | getattr(os, "O_NOFOLLOW", 0), expected["mode"])
                digest = hashlib.sha256()
                size = 0
                with os.fdopen(descriptor, "wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                if size != expected["size"] or digest.hexdigest() != expected["sha256"]:
                    raise SystemExit(f"Streamed asset checksum mismatch: {name}")
                destination.chmod(expected["mode"])
                seen_files.add(name)
            elif member.isdir():
                expected = expected_dirs.get(name)
                if (not expected or name in seen_dirs or expected["mode"] != member.mode):
                    raise SystemExit(f"Unlisted or mismatched streamed directory: {name}")
                (stage / name).mkdir(mode=0o700, parents=True, exist_ok=True)
                seen_dirs.add(name)
            else:
                raise SystemExit("Unsupported file type in streamed archive")
    if seen_files != set(expected_files) or seen_dirs != set(expected_dirs):
        raise SystemExit("Streamed archive paths do not match the manifest")
    for name, item in expected_dirs.items():
        (stage / name).chmod(item["mode"])
    top_level_names = sorted({name.split("/", 1)[0] for name in (*expected_files, *expected_dirs)})
    for name in top_level_names:
        os.rename(stage / name, target / name)
    stage.rmdir()
    committed = True

    actual_files = {}
    actual_dirs = {}
    for path in target.rglob("*"):
        relative = path.relative_to(target).as_posix()
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            actual_dirs[relative] = metadata
        elif stat.S_ISREG(metadata.st_mode):
            actual_files[relative] = metadata
        else:
            raise SystemExit(f"Unexpected path after streamed restore: {relative}")
    if set(actual_files) != set(expected_files) or set(actual_dirs) != set(expected_dirs):
        raise SystemExit("Restored volume paths do not match the manifest")
    for name, expected in expected_files.items():
        metadata = actual_files[name]
        if ((metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode))
                != (expected["uid"], expected["gid"], expected["mode"])):
            raise SystemExit(f"Restored file ownership or mode mismatch: {name}")
        digest = hashlib.sha256()
        with (target / name).open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected["sha256"]:
            raise SystemExit(f"Restored file checksum mismatch: {name}")
    for name, expected in expected_dirs.items():
        metadata = actual_dirs[name]
        if ((metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode))
                != (expected["uid"], expected["gid"], expected["mode"])):
            raise SystemExit(f"Restored directory ownership or mode mismatch: {name}")
    print(f"Restored {len(expected_files)} private files with verified path, SHA-256, mode and ownership")
except BaseException:
    if not committed and stage.exists():
        shutil.rmtree(stage)
    raise
PY
)"
MANIFEST_SIZE="$(python3 -c 'import os,sys; print(os.path.getsize(sys.argv[1]))' "$BACKUP/manifest.json")"
{
    printf '%s\n' "$MANIFEST_SIZE"
    cat -- "$BACKUP/manifest.json" "$BACKUP/assets.tar.gz"
} | compose run --no-deps --rm --no-TTY --entrypoint python web -c "$RESTORE_HELPER"
compose exec --no-TTY db sh -eu -c 'exec pg_restore --no-owner --no-acl --exit-on-error --single-transaction --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' < "$BACKUP/database.dump"

echo "Restore completed into the empty project $PROJECT; the web service remains stopped"
