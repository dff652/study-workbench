# Single-host container service

## 当前双入口（2026-10-06）

新增内网 HTTP `http://192.168.2.36:18080/app/`，原 HTTPS `https://192.168.2.36:18443/app/` 保持。HTTP 源码 `02ce455`／`test-20261006-http-02ce455`，原 HTTPS Web／worker 仍 `4ab5a22`；共享原数据库／资料卷，各自会话名字。当前使用 `compose.yaml`＋`compose.mobile.yaml`＋`compose.http.yaml` 三文件，启动／回退和验收状态见 [HTTP 支持](reviews/http-support-deployment-20261006.md)。下方两个配置文件的叙述为相应历史阶段或未启用 HTTP 伴随服务的配置，不能作为本次整项目操作文件列表。

## 前轮 UI UX 整改部署（2026-10-06）

36 当前运行 `4ab5a22`／`test-20261006-ux-4ab5a22`，仍为 `0.2.0-dev`。主代理 38 项运维及 15 组实际 HTTPS 检查通过；52 张表旧业务记录与 24 文件保持，没有新增迁移。PRE／POST 配套备份分别实际空恢复，并在 PRE 恢复实例启动新镜像验证兼容；原数据库／卷、代理及 CA 保持，旧镜像与恢复点保留。独立运行 review、文档交付与人工未验范围见 [本轮部署验收](reviews/ux-remediation-deployment-20261006.md)。后续仍使用两个 Compose 文件，不能把文档提交当作新镜像。

以下记录保留为前轮历史，镜像／表数量均只适用于对应阶段；当前身份以上节为准。

## 前轮 Web 整合交付（2026-10-05）

36 已升级到 `66e7fb2`／`test-20261005-integration-66e7fb2`，32 项运维、18 组实际 HTTPS 浏览器及前后配套空恢复通过。旧版恢复后已演练候选迁移；新增 `workflows.0003_workspacedraft`，50 张旧表记录和 24 私有文件、原 DB／卷、代理及 CA 保持，当前 51 张表。详见 [部署验收](reviews/web-deployment-20261005.md)；真实家庭 Web、Word 和模型仍待实际结果。

仍使用两个 Compose 文件，旧镜像和配套恢复点保留；源交付、运行镜像和后续文档回执分开记录。下方旧 PC／融合记录按历史保留，不是当前镜像身份。

## 前轮 PC 交付（2026-10-05）

36 已完成源码 `136c251`／镜像 `test-20261005-pc-136c251` 的 PC 升级，仍为 `0.2.0-dev`。主代理 35 项运维与 18 组实际 HTTPS 浏览器检查通过；前后数据库／私有文件配套备份均实际恢复到空实例，旧版恢复后也演练了候选迁移。45 张旧表既有记录与 24 文件、原 DB 容器／卷、代理及 CA 保持；新增两份 solutions 迁移后共 50 张表。CA 全状态备份、解包逐文件和根密钥配对通过，旧镜像与旧配套备份保留。详细证据、恢复点与人工未验项见 [36 PC 部署验收](reviews/pc-deployment-20261005.md)。

运行继续使用 compose.yaml＋compose.mobile.yaml，Web／数据库均无直接主机端口。运行身份固定为 `136c251`，后续文档回执不重建镜像；回退须用旧配套备份恢复空实例，不能让旧镜像直接连接已迁移数据库。

## 前轮融合交付（2026-10-04～05）

36 已完成融合版升级，运行源码 `c4aa96f`／镜像标签 `test-20261004-fusion-c4aa96f`，版本 `0.2.0-dev`。26 项运维和 14 组严格 HTTPS 浏览器通过。前后停两写入服务获取配套备份，并分别实际空实例恢复；41 张旧表原记录、24 文件及原数据库容器／卷保持，私有 CA 全状态备份／解包／密钥配对通过且当前 CA 不变。后续运行命令仍须使用 compose.yaml＋compose.mobile.yaml；旧版本回退仅以旧配套备份恢复空项目，不能连接升级后数据库。

根地址登录后进入 `/app/`，旧资料库保留在 `/materials/`；原业务入口继续可访问。运行身份固定为源码提交，之后文档提交不等于重建镜像。精确门槛及人工未验项见 [本轮 review](reviews/skill-delivery-20261004.md)和 [DEV_STATE](../DEV_STATE.md)。


This document covers the local Docker Compose service and its private backup and restore workflow. The Compose file binds the Web service to `127.0.0.1:8000` by default; PostgreSQL has no published host port. It is not a public deployment recipe. For the current authorized LAN HTTP listener, use the dedicated companion configuration above; HTTPS/PWA keeps its managed TLS proxy.

The optional [MOB-01 HTTPS/PWA overlay](mobile-deployment.md) adds an owned non-root Caddy proxy, removes the direct Web host port, and uses a private CA. Its isolated acceptance and authorized host-36 upgrade/recovery are recorded in DEV_STATE; Android physical-device acceptance is still pending. Keep the HTTPS overlay and handle private CA state separately from database/file backup. With the current HTTP companion enabled, retain all three Compose files as documented above.

## Pinned runtime

The frontend builder uses Node 24.19.0 Bookworm slim pinned by digest, installs the locked frontend dependencies with lifecycle scripts disabled, and builds the real React/TypeScript bundle. Node and npm are absent from the final image. The selected shadcn-admin MIT notice is retained in `/app/licenses/shadcn-admin-MIT.txt`, and bundled dependency notices in `/app/licenses/frontend-dependency-notices.txt`; exact copied files and source hashes are in [frontend notices](../frontend/THIRD_PARTY.md).

The runtime image uses the Python 3.12.14 slim Bookworm base by digest, Django and application dependencies from `requirements.txt`, and the pinned runtime-only packages in `requirements-container.txt`. Gunicorn 26.2.0 and WhiteNoise 6.12.0 were checked against their [PyPI release metadata](https://pypi.org/project/gunicorn/26.2.0/) and [PyPI release metadata](https://pypi.org/project/whitenoise/6.12.0/) on 2026-10-03. WhiteNoise follows its [Django integration guidance](https://whitenoise.readthedocs.io/en/stable/django.html): middleware runs after Django's security middleware and serves the collected, manifest-hashed static files.

The image also installs the Bookworm packages `fonts-noto-cjk=1:20220127+repack1-1` and `fonts-dejavu-core=2.37-6` from Debian's [Bookworm package metadata for Noto](https://packages.debian.org/bookworm/fonts-noto-cjk) and [DejaVu](https://packages.debian.org/bookworm/fonts-dejavu-core). These provide the original TTC/TTF inputs at the paths used by the printing service. The two license notices are copied into `/app/licenses/`. The container font package revisions differ from the host revisions recorded in [third-party notices](third-party-notices.md), so generated print snapshots record their actual font hashes; container output is not claimed to be byte-for-byte or pixel-identical to prior host output.

The PC companion implementation adds Debian `poppler-utils` for PDF page-count verification and page previews. Its Debian package revision is not pinned; the executed `pdftoppm` version is recorded in each immutable output recipe. Rendering also preserves the actual native generator, font, adapter and fixed companion source hashes. The deterministic solution queue shares the existing background worker and runs with the model disabled. `solutions.0001` and `0002` add draft, confirmation, PNG and output/event history; upgrade and recovery require the paired database and complete private directory. The historical integration deployment ran source `66e7fb2`, with `pdftoppm` 22.12.0 verified in the running image. See the [PC contract](pc-companion-contract.md) and current DEV_STATE for actual acceptance.

The Web process runs as uid/gid `10001`, has no Linux capabilities, uses a read-only root filesystem, and writes uploads and generated materials only under the private named volume mounted at `/var/lib/study-workbench/private`. PostgreSQL uses a separate named volume. Compose labels both projects' owned containers, volumes, networks, and the built application image; the acceptance script refuses existing resource names and removes only resources whose labels match its generated project and owner IDs.

## First local start

Requirements: Docker Engine with the Compose v2 plugin, Python 3 for the verifier, and enough disk space for the pinned base image, PostgreSQL image, and CJK fonts. Run these commands from the project root:

```sh
umask 077
python3 - <<'PY'
from pathlib import Path
import secrets

path = Path(".env.container.local")
lines = Path("container.env.example").read_text(encoding="utf-8").splitlines()
for name, length in (("SWB_DB_PASSWORD", 36), ("SWB_SECRET_KEY", 48)):
    prefix = f"{name}="
    indices = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(indices) != 1:
        raise SystemExit(f"Expected one {name} in the environment template")
    lines[indices[0]] = prefix + secrets.token_urlsafe(length)
with path.open("x", encoding="utf-8") as target:
    target.write("\n".join(lines) + "\n")
path.chmod(0o600)
print("Local secrets generated without displaying their values.")
PY

docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml config --quiet
docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml build web
docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml up --detach --wait
curl --fail http://127.0.0.1:8000/healthz
```

The configuration command creates a new file exclusively. If `.env.container.local` already exists, including a symbolic link, it refuses to replace it. Keep the existing protected configuration for subsequent starts; do not rerun initialization to rotate credentials.

The settings reject missing secrets, database values, or allowed hosts. There is no default password and no public account registration. Create the first account with an interactive password prompt; do not put a password in a command argument:

```sh
docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml exec web python manage.py createsuperuser
```

An account also needs a household membership. After creating the account, run this interactive command and enter its username and a new household ID locally:

```sh
docker compose --env-file .env.container.local --project-name study-workbench -f compose.yaml exec web python manage.py shell -c 'from django.contrib.auth import get_user_model; from app.persistence.services import create_household; actor=get_user_model().objects.get(username=input("Username: ")); create_household(actor,input("New household ID: "))'
```

After login, the production root opens `/app/`; `/materials/` retains source-region editing and prior business pages. `/api/v1/about/` exposes the real development version and changelog. Set `SWB_SOURCE_REVISION` only to a reviewed commit whose bytes match the build, and optionally set `SWB_BUILD_DATE` through build arguments. An uncommitted local build keeps source revision unknown.

Compose starts a separate sequential SOP/model worker using `scripts/run_model_tasks.py --watch`. It advances explicitly queued local five-book jobs and existing separately authorized AI tasks, with cancellation, interrupted recovery and audit history. Both processes share the private volume and the same protected environment; no model is enabled by default. A local SOP job does not request or repeat a model call. See [model configuration](model-configuration.md) before adding a server-side key or permitted HTTPS host. The build records `SWB_SOURCE_REVISION` in its image label.

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

The full verifier builds a uniquely tagged image, generates random Compose project/owner names and loopback ports, uses only the synthetic domain fixture plus a generated PNG, and cleans up only resources whose ownership labels match that run. The fusion fixture also retains a ready SOP job with immutable input and an append-only created event, checks the built `/app/` entry and development metadata, and compares workflow rows after restore. The fixture includes three separately retained attempts, an accepted assessment, teacher answer, three exports, a study plan, split provenance, disabled model configuration, local retention policy and manual timing. One synthetic export is explicitly archived and retired, and its ledger is saved. The verifier checks the non-root process and loopback binding, database readiness, login, private upload and preview, static CSS, web-container recreation, `pg_dump` plus file hashes, empty-instance restoration, and refusal to restore twice into a non-empty instance. It compares all serialized application rows and verifies DB-referenced originals, previews, active exports and retired archives against the manifest's path, SHA-256, mode, UID, and GID before and after restore. Retired original files remain absent after restore.

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

The authorized test runs on host 36 as Compose project `study-workbench-36`, with dedicated database/private volumes. Its exact LAN listener is recorded only in the ignored `data/runtime-36/deployment.local.json`. This initially used LAN HTTP; the authorized MOB-01 upgrade now uses LAN HTTPS with a separate private CA. It is not a public deployment; both Compose files are required for subsequent service updates. Its protected configuration and generated account are under `data/runtime-36/` (directory 0700, files 0600); account details stay in `credentials.local.json`. Only clearly labeled synthetic sample data was seeded. Do not copy private configuration into Git or paste the password into chat.

Use the existing configuration without displaying its contents:

```sh
docker compose --env-file data/runtime-36/compose.env --project-name study-workbench-36 -f compose.yaml -f compose.mobile.yaml ps
```

The initial backup at `backups/runtime-36/20261003-initial/` was made with both Web and worker stopped and then resumed. Follow [local data policy](local-data-policy.md) when exporting a later retirement ledger or restoring an older backup; a backup cannot contain deletions recorded after its creation.

Before the gap-closure upgrade, Web and worker use `test-20261003-reviewed-4f145ef`, built from source `4f145ef38bb6683333b76b7cea0f726a8876e7a4`. The actual `a59e8d7` upgrade added only `catalogue.0003_questionlabel`; all original rows in 39 tables and 19 private files were preserved. Thirteen mobile-browser checks passed, including existing attempt/assessment history and six unchanged PDF/DOCX downloads. AI remains disabled. The original database container and named volumes remain in use; the older image and protected configuration are retained.

The paired backups are `backups/runtime-36/20261003-pre-reviewed-20261003T070755Z-b2bd29/` and `backups/runtime-36/20261003-post-reviewed-20261003T070755Z-b2bd29/`, with verified dump/file checksums and protected deployment configuration. The pre-upgrade backup was restored with the old image into a separate empty project and compared against the original rows, files and authenticated preview; that recovery project was then removed. The actual upgrade report is `artifacts/runtime-36/upgrade-20261003T070755Z-b2bd29/verification.local.json`. Documentation-only commits after this build do not change its source label. For rollback, restore the matching old backup with the old image into an empty project; never attach that image to the migrated database.

Run the independent cross-version drill with `python3 scripts/verify_upgrade.py`. It builds a fixed `1c0c386` B1 source archive with minimal container/health shims, records old database rows and uploaded files, backs up, migrates the same volumes with the new image, and verifies old rows/files plus a new learning-plan record. Rollback uses the B1 image and pre-upgrade backup in a separate empty project. It never starts the older image on the upgraded database. Actual results are recorded in DEV_STATE and private `artifacts/upgrade-verification/` reports.

The gap-closure changes add nullable `ai.0005_external_processing_consent` and the append-only `workbench_web.0003_imagederivative` schema. Existing AI configurations keep unknown declarations until an explicit new confirmed version is saved; AI remains disabled by default. Derivative PNGs are included in the same private-file backup and empty-instance restore. Stop both old Web and worker before migrating to avoid mixed send-gate versions. The pre-upgrade snapshot must be restored with its matching old image in a fresh project before updating the live service. Actual source, image, restore and post-upgrade checks are recorded in DEV_STATE; plans do not establish deployment.

The actual gap-closure source `ce698f9891d9c8bb609cde82c282a177074b31b0` was manually pushed and then deployed to host 36 as `test-20261003-gaps-ce698f9`. An old-image restore in a fresh project verified the pre-upgrade backup before both writers were migrated and replaced. Original rows across 40 old tables and 19 private files were preserved; the database container and volumes stayed in place. Both new migrations, 182 application source hashes, a rollback-only native derivative guard probe, 16 runtime checks, unchanged historical downloads and the post-upgrade backup passed. AI remains off, no private trial photos were copied into this service, and no real model requests were sent. The exact runtime report is `artifacts/runtime-36/upgrade-gaps-20261003T131631Z-2f2b5f/verification.local.json`; the paired pre/post backups are `backups/runtime-36/20261003-pre-gaps-20261003T131631Z-2f2b5f/` and `backups/runtime-36/20261003-post-gaps-20261003T131631Z-2f2b5f/`. Keep the matching old image and backup for a fresh-project recovery; do not attach the old image to the migrated database.

## Fusion migration and deployment boundary (2026-10-04)

The local fusion changes include `printing.0003_teachingdiagramrevision`, `workbench_web.0004_page_reading_revision`, and `workflows.0001`/`0002`. The new schemas are included in isolated down/up migration checks and the full database/file backup comparison. Existing history is preserved; schema reversal is a synthetic test, not a production rollback plan. Before a later authorized host-36 upgrade, retain its matching image, Compose files and private CA state; stop both writers, make and verify a fresh pre-upgrade backup, restore it into a new empty project, then build/migrate and rerun authenticated business checks. This implementation session has not upgraded host 36, pushed source, or published to NAS. Exact current local acceptance is recorded in [DEV_STATE](../DEV_STATE.md) and the [fusion execution record](fusion-execution-20261004.md).
