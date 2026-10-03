# Single-host container service

This document covers the local Docker Compose service and its private backup and restore workflow. The Compose file binds the Web service to `127.0.0.1:8000` by default; PostgreSQL has no published host port. It is not a public deployment recipe. Put a separately managed TLS reverse proxy in front of the loopback listener before exposing access beyond the machine.

## Pinned runtime

The image uses the Python 3.12.14 slim Bookworm base by digest, Django and application dependencies from `requirements.txt`, and the pinned runtime-only packages in `requirements-container.txt`. Gunicorn 26.2.0 and WhiteNoise 6.12.0 were checked against their [PyPI release metadata](https://pypi.org/project/gunicorn/26.2.0/) and [PyPI release metadata](https://pypi.org/project/whitenoise/6.12.0/) on 2026-10-03. WhiteNoise follows its [Django integration guidance](https://whitenoise.readthedocs.io/en/stable/django.html): middleware runs after Django's security middleware and serves the collected, manifest-hashed static files.

The image also installs the Bookworm packages `fonts-noto-cjk=1:20220127+repack1-1` and `fonts-dejavu-core=2.37-6` from Debian's [Bookworm package metadata for Noto](https://packages.debian.org/bookworm/fonts-noto-cjk) and [DejaVu](https://packages.debian.org/bookworm/fonts-dejavu-core). These provide the original TTC/TTF inputs at the paths used by the printing service. The two license notices are copied into `/app/licenses/`. The container font package revisions differ from the host revisions recorded in [third-party notices](third-party-notices.md), so generated print snapshots record their actual font hashes; container output is not claimed to be byte-for-byte or pixel-identical to prior host output.

The Web process runs as uid/gid `10001`, has no Linux capabilities, uses a read-only root filesystem, and writes uploads and generated materials only under the private named volume mounted at `/var/lib/study-workbench/private`. PostgreSQL uses a separate named volume. Compose labels both projects' owned containers, volumes, networks, and the built application image; the acceptance script refuses existing resource names and removes only resources whose labels match its generated project and owner IDs.

## First local start

Requirements: Docker Engine with the Compose v2 plugin, Python 3 for the verifier, and enough disk space for the pinned base image, PostgreSQL image, and CJK fonts. Run these commands from the project root:

```sh
umask 077
install -m 0600 container.env.example .env.container.local
python3 - <<'PY'
from pathlib import Path
import secrets

path = Path(".env.container.local")
lines = path.read_text(encoding="utf-8").splitlines()
for name, length in (("SWB_DB_PASSWORD", 36), ("SWB_SECRET_KEY", 48)):
    prefix = f"{name}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            if not line[len(prefix):]:
                lines[index] = prefix + secrets.token_urlsafe(length)
            break
    else:
        raise SystemExit(f"Missing {name} in the local environment template")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
print("Local secrets generated without displaying their values.")
PY

docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml config --quiet
docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml build web
docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml up --detach --wait
curl --fail http://127.0.0.1:8000/healthz
```

The settings reject missing secrets, database values, or allowed hosts. There is no default password and no public account registration. Create the first account with an interactive password prompt; do not put a password in a command argument:

```sh
docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml exec web python manage.py createsuperuser
```

An account also needs a household membership. After creating the account, run this interactive command and enter its username and a new household ID locally:

```sh
docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml exec web python manage.py shell -c 'from django.contrib.auth import get_user_model; from app.persistence.services import create_household; actor=get_user_model().objects.get(username=input("Username: ")); create_household(actor,input("New household ID: "))'
```

Compose starts a separate sequential model worker using `scripts/run_model_tasks.py --watch`. Both processes share the private volume and the same protected environment; no model is enabled by default. See [model configuration](model-configuration.md) before adding a server-side key or permitted HTTPS host. The build records `SWB_SOURCE_REVISION` in its image label.

The production health endpoint checks PostgreSQL as well as the Django process. A healthy endpoint does not verify login, uploads, printing, or restore; use the acceptance command below for those paths. Static files are collected into the container's writable `/tmp` area at each start.

## HTTPS proxy settings

The template deliberately keeps secure-cookie and HTTPS redirect switches off for the loopback-only HTTP path. For a trusted reverse proxy which terminates HTTPS, overwrite `X-Forwarded-Proto` with `https` and set all three values in the private environment file:

```text
SWB_SECURE_SSL_REDIRECT=true
SWB_SECURE_COOKIES=true
SWB_TRUST_PROXY_HEADERS=true
```

Also set `SWB_ALLOWED_HOSTS` and `SWB_CSRF_TRUSTED_ORIGINS` to the exact external host and HTTPS origin. The app accepts the proxy header only when explicitly configured; do not enable that setting if untrusted clients can reach the application port directly.

## Isolated synthetic acceptance

The full verifier builds a uniquely tagged image, generates random Compose project/owner names and loopback ports, uses only the synthetic domain fixture plus a generated PNG, and cleans up only resources whose ownership labels match that run. The fixture includes three separately retained attempts, an accepted assessment, teacher answer, three exports, a study plan, split provenance, disabled model configuration, local retention policy and manual timing. One synthetic export is explicitly archived and retired, and its ledger is saved. The verifier checks the non-root process and loopback binding, database readiness, login, private upload and preview, static CSS, web-container recreation, `pg_dump` plus file hashes, empty-instance restoration, and refusal to restore twice into a non-empty instance. It compares all serialized application rows and verifies DB-referenced originals, previews, active exports and retired archives against the manifest's path, SHA-256, mode, UID, and GID before and after restore. Retired original files remain absent after restore.

The 2026-10-03 pre-push fixes add `catalogue.0003_questionlabel` for immutable derived question numbers. The main agent reran the isolated container restore and the fixed B1 upgrade/old-backup rollback with this migration; the restore includes the new labels. Host 36 stayed on `a59e8d7` during that review. After the source push, a separate backup, recovery drill, migration and service upgrade moved it to reviewed source `4f145ef`. The historical review and actual deployment evidence are recorded separately in the [pre-push review](reviews/pre-push-20261003.md) and [development state](../DEV_STATE.md).

```sh
.venv/bin/python -m py_compile app/production.py app/health.py app/wsgi.py scripts/verify_container.py
bash -n scripts/backup_service.sh scripts/restore_service.sh
sh -n scripts/container_entrypoint.sh
.venv/bin/python -m unittest discover -s tests/container -p 'test_*.py' -v
python3 scripts/verify_container.py
```

The verifier needs permission to build and run Docker containers. It does not touch a real deployment or read personal photos. If Docker cannot start or a run fails before cleanup, inspect only the exact project and owner IDs printed by that run, and remove resources only after confirming every resource label matches those IDs.

## Backup

Backups contain a custom-format PostgreSQL dump, an archive of private files, and a JSON manifest of relative paths, SHA-256/size, mode, and UID/GID, plus archive checksums. The script stops the Web service and, when present, the background worker before taking both snapshots, then restarts only the writers that were running before the operation. This keeps current app writes quiescent while the database and file snapshots are made. Direct database writers or any other background writer must also be stopped before backup. Restore validates the archive on the host, then streams it to a non-root helper that rechecks every path, hash, mode, and owner while writing directly to the isolated private volume. The manifest detects accidental corruption; it is not a signature or proof against deliberate modification. The archive contains personal records and images, so store it in a private, access-controlled location and protect the storage media separately.

Create the destination parent once with private permissions. Each backup destination must be a new path; the script refuses to overwrite an existing one:

```sh
backup_root="$HOME/study-workbench-backups"
install -d -m 0700 "$backup_root"
backup_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
bash scripts/backup_service.sh --env-file .env.container.local study-workbench "$backup_root/$backup_stamp"
```

The output directory and its files are created with mode `0700` and `0600`. Keep the original archive unchanged and copy it only to a protected backup location.

## Restore to a new empty project

Restore is intentionally limited to an empty PostgreSQL database and an empty private-data volume. It refuses a running Web or background-worker service, any user relation in the target database, or any file already in the target volume. There is no force-overwrite option. Always choose a fresh project name and, if the original service is still running, a different loopback port. A failed restore may have partially populated its target; discard only that new, confirmed restore project and its volumes, then retry from a fresh project.

Start only the new project's database. Keep the env file private; override the host port in the command environment so the restore project does not claim the original listener:

```sh
restore_project=study-workbench-restore
restore_port=18000
SWB_HOST_PORT="$restore_port" docker compose --env-file .env.container.local --project-name "$restore_project" -f compose.yaml up --detach --wait db
bash scripts/restore_service.sh --env-file .env.container.local "$restore_project" "$HOME/study-workbench-backups/REPLACE_WITH_BACKUP_DIRECTORY"
SWB_HOST_PORT="$restore_port" docker compose --env-file .env.container.local --project-name "$restore_project" -f compose.yaml up --detach --wait web worker
curl --fail "http://127.0.0.1:$restore_port/healthz"
```

The Web service remains stopped until the last `up` command, which applies any pending migrations and collects static files. Verify an account login and the original private previews in the restored project before switching any proxy or user traffic. When deliberately deleting a failed or retired restore project, first inspect Compose project labels and volume owner labels; `down --volumes` permanently removes that project's database and private files.

## Image upgrades and rollback boundary

Use a new `SWB_IMAGE_TAG` for each application build and retain the previous image until the new service passes its business checks. Make a fresh backup before applying schema migrations. The startup entrypoint runs migrations before serving requests; restoring an older application image alone does not reverse a migration. Only start an older image against the migrated database when that migration is known to remain backward-compatible. Otherwise, restore the pre-upgrade backup into a separate empty project and verify it there before changing any traffic routing. This repo does not provide automated migration rollback, online cutover, or production deployment automation.

To stop the local service without deleting either data volume:

```sh
docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml stop
```

Do not use `down --volumes` unless permanent deletion of both PostgreSQL records and private files is intended.

## 36 LAN test instance

The authorized test runs on host 36 as Compose project `study-workbench-36`, with dedicated database/private volumes. Its exact LAN listener is recorded only in the ignored `data/runtime-36/deployment.local.json`. This is LAN HTTP testing, not a public HTTPS deployment. Its protected configuration and generated account are under `data/runtime-36/` (directory 0700, files 0600); account details stay in `credentials.local.json`. Only clearly labeled synthetic sample data was seeded. Do not copy private configuration into Git or paste the password into chat.

Use the existing configuration without displaying its contents:

```sh
docker compose --env-file data/runtime-36/compose.env --project-name study-workbench-36 -f compose.yaml ps
```

The initial backup at `backups/runtime-36/20261003-initial/` was made with both Web and worker stopped and then resumed. Follow [local data policy](local-data-policy.md) when exporting a later retirement ledger or restoring an older backup; a backup cannot contain deletions recorded after its creation.

The current Web and worker use `test-20261003-reviewed-4f145ef`, built from source `4f145ef38bb6683333b76b7cea0f726a8876e7a4`. The actual `a59e8d7` upgrade added only `catalogue.0003_questionlabel`; all original rows in 39 tables and 19 private files were preserved. Thirteen mobile-browser checks passed, including existing attempt/assessment history and six unchanged PDF/DOCX downloads. AI remains disabled. The original database container and named volumes remain in use; the older image and protected configuration are retained.

The paired backups are `backups/runtime-36/20261003-pre-reviewed-20261003T070755Z-b2bd29/` and `backups/runtime-36/20261003-post-reviewed-20261003T070755Z-b2bd29/`, with verified dump/file checksums and protected deployment configuration. The pre-upgrade backup was restored with the old image into a separate empty project and compared against the original rows, files and authenticated preview; that recovery project was then removed. The actual upgrade report is `artifacts/runtime-36/upgrade-20261003T070755Z-b2bd29/verification.local.json`. Documentation-only commits after this build do not change its source label. For rollback, restore the matching old backup with the old image into an empty project; never attach that image to the migrated database.

Run the independent cross-version drill with `python3 scripts/verify_upgrade.py`. It builds a fixed `1c0c386` B1 source archive with minimal container/health shims, records old database rows and uploaded files, backs up, migrates the same volumes with the new image, and verifies old rows/files plus a new learning-plan record. Rollback uses the B1 image and pre-upgrade backup in a separate empty project. It never starts the older image on the upgraded database. Actual results are recorded in DEV_STATE and private `artifacts/upgrade-verification/` reports.
