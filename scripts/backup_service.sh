#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE=""
if [[ "${1:-}" == "--env-file" ]]; then
    [[ $# -ge 4 ]] || { echo "Usage: $0 [--env-file FILE] PROJECT DESTINATION" >&2; exit 2; }
    ENV_FILE="$(realpath -- "$2")"
    shift 2
fi
[[ $# == 2 ]] || { echo "Usage: $0 [--env-file FILE] PROJECT DESTINATION" >&2; exit 2; }
PROJECT="$1"
DEST_INPUT="$2"
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

DEST_PARENT_INPUT="$(dirname -- "$DEST_INPUT")"
DEST_NAME="$(basename -- "$DEST_INPUT")"
[[ "$DEST_NAME" != "." && "$DEST_NAME" != "/" ]] || { echo "Destination must name a new directory" >&2; exit 2; }
[[ -d "$DEST_PARENT_INPUT" ]] || { echo "Destination parent must already exist" >&2; exit 2; }
DEST_PARENT="$(cd -- "$DEST_PARENT_INPUT" && pwd -P)"
DEST="$DEST_PARENT/$DEST_NAME"
[[ ! -e "$DEST" && ! -L "$DEST" ]] || { echo "Refusing to overwrite an existing backup" >&2; exit 2; }

service_id() {
    local service="$1" ids id details count=0
    ids="$(compose ps --all --quiet "$service")"
    [[ -n "$ids" ]] || { echo "Compose service $service has no container in project $PROJECT" >&2; return 1; }
    while IFS= read -r id; do
        [[ -n "$id" ]] || continue
        ((count += 1))
        details="$(docker inspect --format '{{index .Config.Labels "com.study-workbench.resource-owner"}} {{index .Config.Labels "com.docker.compose.project"}}' "$id")"
        [[ "$details" == "$RESOURCE_OWNER $PROJECT" ]] || {
            echo "Refusing service $service with a mismatched owner or project label" >&2
            return 1
        }
    done <<< "$ids"
    [[ $count == 1 ]] || { echo "Expected one $service container in project $PROJECT" >&2; return 1; }
    printf '%s\n' "$ids"
}

WEB_ID="$(service_id web)"
DB_ID="$(service_id db)"
compose ps --status running --quiet db | grep -Fxq "$DB_ID" || { echo "Database service must be running" >&2; exit 1; }
WEB_RUNNING=0
if compose ps --status running --quiet web | grep -Fxq "$WEB_ID"; then
    WEB_RUNNING=1
fi
WORKER_RUNNING=0
WORKER_IDS=""
if compose config --services | grep -Fxq worker; then
    WORKER_IDS="$(compose ps --all --quiet worker)"
    while IFS= read -r id; do
        [[ -n "$id" ]] || continue
        details="$(docker inspect --format '{{index .Config.Labels "com.study-workbench.resource-owner"}} {{index .Config.Labels "com.docker.compose.project"}}' "$id")"
        [[ "$details" == "$RESOURCE_OWNER $PROJECT" ]] || {
            echo "Refusing worker with a mismatched owner or project label" >&2
            exit 1
        }
    done <<< "$WORKER_IDS"
    if [[ -n "$(compose ps --status running --quiet worker)" ]]; then
        WORKER_RUNNING=1
    fi
fi

WORK=""
STOPPED=0
finish() {
    local result=$?
    trap - EXIT
    set +e
    if [[ -n "$WORK" && -d "$WORK" ]]; then
        if [[ $result == 0 && -d "$WORK/ready" ]]; then
            mv -- "$WORK/ready" "$DEST" || result=1
        fi
        rm -rf -- "$WORK"
    fi
    if [[ $STOPPED == 1 ]]; then
        local restart_services=()
        [[ $WEB_RUNNING == 1 ]] && restart_services+=(web)
        [[ $WORKER_RUNNING == 1 ]] && restart_services+=(worker)
        compose start "${restart_services[@]}" >/dev/null || {
            echo "Backup is saved, but a previously running writer could not be restarted" >&2
            [[ $result != 0 ]] || result=1
        }
    fi
    exit "$result"
}
trap finish EXIT

WORK="$(mktemp -d "$DEST_PARENT/.${DEST_NAME}.tmp.XXXXXX")"
chmod 0700 "$WORK"
mkdir -m 0700 "$WORK/data" "$WORK/ready"

writers_to_stop=()
[[ $WEB_RUNNING == 1 ]] && writers_to_stop+=(web)
[[ $WORKER_RUNNING == 1 ]] && writers_to_stop+=(worker)
if ((${#writers_to_stop[@]})); then
    STOPPED=1
    compose stop --timeout 30 "${writers_to_stop[@]}" >/dev/null
fi

compose exec --no-TTY db sh -eu -c 'exec pg_dump --format=custom --no-owner --no-acl --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' > "$WORK/ready/database.dump"
compose run --no-deps --rm --no-TTY --entrypoint python web - > "$WORK/source-manifest.json" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import stat

root = Path(os.environ["SWB_DATA_ROOT"])
root_metadata = root.lstat()
if not stat.S_ISDIR(root_metadata.st_mode):
    raise SystemExit("Private data root is not a directory")
if (root_metadata.st_uid, root_metadata.st_gid) != (os.getuid(), os.getgid()):
    raise SystemExit("Private data root has an unexpected owner")
if stat.S_IMODE(root_metadata.st_mode) & 0o077:
    raise SystemExit("Private data root permissions are too broad")

files = []
directories = []
for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
    relative = path.relative_to(root).as_posix()
    metadata = path.lstat()
    if (metadata.st_uid, metadata.st_gid) != (os.getuid(), os.getgid()):
        raise SystemExit(f"Private storage has an unexpected owner: {relative}")
    if stat.S_ISLNK(metadata.st_mode):
        raise SystemExit(f"Refusing a symlink in private storage: {relative}")
    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISDIR(metadata.st_mode):
        if mode & (0o077 | 0o7000):
            raise SystemExit(f"Private directory permissions are too broad: {relative}")
        directories.append({"path": relative, "mode": mode,
                            "uid": metadata.st_uid, "gid": metadata.st_gid})
        continue
    if not stat.S_ISREG(metadata.st_mode) or mode & (0o077 | 0o7000):
        raise SystemExit(f"Refusing a non-regular or non-private asset: {relative}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    files.append({"path": relative, "size": size, "sha256": digest.hexdigest(),
                  "mode": mode, "uid": metadata.st_uid, "gid": metadata.st_gid})

print(json.dumps({"root": {"mode": stat.S_IMODE(root_metadata.st_mode),
                            "uid": root_metadata.st_uid, "gid": root_metadata.st_gid},
                  "directories": directories, "files": files}, sort_keys=True))
PY
docker cp "$WEB_ID:/var/lib/study-workbench/private/." "$WORK/data"
tar -czf "$WORK/ready/assets.tar.gz" -C "$WORK/data" .

python3 - "$WORK" <<'PY'
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

work = Path(sys.argv[1])
data = work / "data"
ready = work / "ready"
source_manifest = json.loads((work / "source-manifest.json").read_text(encoding="utf-8"))
source_files = {item["path"]: item for item in source_manifest["files"]}
source_directories = {item["path"]: item for item in source_manifest["directories"]}
host_files = {}
host_directories = {}
for path in sorted(data.rglob("*"), key=lambda item: item.relative_to(data).as_posix()):
    relative = path.relative_to(data).as_posix()
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise SystemExit(f"Refusing a symlink in private storage: {relative}")
    if stat.S_ISDIR(metadata.st_mode):
        if metadata.st_mode & (0o077 | 0o7000):
            raise SystemExit(f"Private directory permissions are too broad: {relative}")
        host_directories[relative] = {"path": relative, "mode": stat.S_IMODE(metadata.st_mode)}
        continue
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & (0o077 | 0o7000):
        raise SystemExit(f"Refusing a non-regular or non-private asset: {relative}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    host_files[relative] = {"path": relative, "size": size, "sha256": digest.hexdigest(),
                            "mode": stat.S_IMODE(metadata.st_mode)}

if set(host_files) != set(source_files) or set(host_directories) != set(source_directories):
    raise SystemExit("Private data copy paths do not match the stopped application volume")
for path, actual in host_files.items():
    expected = source_files[path]
    if any(actual[field] != expected[field] for field in ("size", "sha256", "mode")):
        raise SystemExit(f"Private data copy differs from the stopped application volume: {path}")
    if (expected.get("uid"), expected.get("gid")) != (10001, 10001):
        raise SystemExit(f"Private file has an unexpected application owner: {path}")
for path, actual in host_directories.items():
    expected = source_directories[path]
    if actual["mode"] != expected["mode"]:
        raise SystemExit(f"Private directory mode differs from the stopped application volume: {path}")
    if (expected.get("uid"), expected.get("gid")) != (10001, 10001):
        raise SystemExit(f"Private directory has an unexpected application owner: {path}")
root = source_manifest["root"]
if (root.get("uid"), root.get("gid")) != (10001, 10001) or root.get("mode") != 0o700:
    raise SystemExit("Private data root has unexpected mode or ownership")

files = [source_files[path] for path in sorted(source_files)]
directories = [source_directories[path] for path in sorted(source_directories)]

def checksum(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"size": size, "sha256": digest.hexdigest()}

manifest = {
    "format": "study-workbench-backup/v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "database_dump": checksum(ready / "database.dump"),
    "assets_archive": checksum(ready / "assets.tar.gz"),
    "data_root": root,
    "directories": directories,
    "files": files,
}
manifest_path = ready / "manifest.json"
with manifest_path.open("x", encoding="utf-8") as output:
    json.dump(manifest, output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    output.write("\n")
manifest_path.chmod(0o600)
for path in ready.iterdir():
    if path.is_file():
        path.chmod(0o600)
ready.chmod(0o700)
print(f"Backup manifest: {len(files)} files, {len(directories)} directories")
PY

echo "Private backup prepared at $DEST"
