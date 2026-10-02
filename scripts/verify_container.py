#!/usr/bin/env python3
"""Build and exercise an isolated synthetic Compose deployment end to end."""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "compose.yaml"
POSTGRES_IMAGE = "postgres@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229"
FIXTURE = ROOT / "tests/fixtures/domain/synthetic-v0.1.json"


def command(args, *, env=None, input_text=None, check=True):
    result = subprocess.run(args, cwd=ROOT, env=env, input=input_text, text=True, capture_output=True)
    if check and result.returncode:
        details = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(args)}\n{details}")
    return result


def free_loopback_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def project_command(project, *args):
    return ["docker", "compose", "--file", str(COMPOSE_FILE), "--project-name", project, *args]


def compose(project, env, *args, check=True, input_text=None):
    return command(project_command(project, *args), env=env, check=check, input_text=input_text)


def assert_project_absent(project):
    for kind, args in (
        ("container", ["docker", "ps", "--all", "--quiet", "--filter", f"label=com.docker.compose.project={project}"]),
        ("volume", ["docker", "volume", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project}"]),
        ("network", ["docker", "network", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project}"]),
    ):
        result = command(args)
        if result.stdout.strip():
            raise RuntimeError(f"Refusing to reuse existing {kind} resources with project label {project}")


def assert_image_absent(image_ref):
    result = command(["docker", "image", "inspect", image_ref], check=False)
    if result.returncode == 0:
        raise RuntimeError(f"Refusing to overwrite an existing image tag: {image_ref}")


def compose_env(owner, tag, port, secret_key, db_password):
    env = {key: value for key, value in os.environ.items() if not key.startswith("SWB_")}
    env.pop("COMPOSE_FILE", None)
    env.update({
        "SWB_IMAGE_TAG": tag,
        "SWB_RESOURCE_OWNER": owner,
        "SWB_BIND_ADDRESS": "127.0.0.1",
        "SWB_HOST_PORT": str(port),
        "SWB_DB_NAME": "swb_container_synthetic",
        "SWB_DB_USER": "swb_container_synthetic",
        "SWB_DB_PASSWORD": db_password,
        "SWB_SECRET_KEY": secret_key,
        "SWB_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "SWB_CSRF_TRUSTED_ORIGINS": f"http://127.0.0.1:{port},http://localhost:{port}",
        "SWB_SECURE_SSL_REDIRECT": "false",
        "SWB_SECURE_COOKIES": "false",
        "SWB_TRUST_PROXY_HEADERS": "false",
    })
    return env


def wait_http(url, *, timeout=180):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with build_opener().open(url, timeout=3) as response:
                return response.status, response.read()
        except (OSError, HTTPError, URLError) as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError(f"Service did not respond at {url}: {last_error}")


def wait_compose_health(project, env, *, timeout=180):
    deadline = time.monotonic() + timeout
    last = "unknown"
    while time.monotonic() < deadline:
        result = compose(project, env, "ps", "--all", "--format", "json")
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        statuses = {row.get("Service"): row.get("Health", "") for row in rows}
        states = {row.get("Service"): row.get("State", "") for row in rows}
        if statuses.get("db") == "healthy" and statuses.get("web") == "healthy":
            return
        last = f"state={states}, health={statuses}"
        if any(state in {"exited", "dead"} for state in states.values()):
            break
        time.sleep(2)
    logs = compose(project, env, "logs", "--no-color", "--tail", "80", check=False).stdout
    raise RuntimeError(f"Compose services did not become healthy ({last})\n{logs}")


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = {}
        self.household_id = None
        self.in_household_select = False
        self.images = []
        self.stylesheets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("type") == "hidden" and attrs.get("name"):
            self.hidden[attrs["name"]] = attrs.get("value", "")
        if tag == "select" and attrs.get("name") == "household_id":
            self.in_household_select = True
        elif tag == "option" and self.in_household_select and self.household_id is None:
            self.household_id = attrs.get("value")
        elif tag == "img" and attrs.get("src"):
            self.images.append(attrs["src"])
        elif tag == "link" and "stylesheet" in attrs.get("rel", "") and attrs.get("href"):
            self.stylesheets.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "select":
            self.in_household_select = False


class Browser:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.opener = build_opener(HTTPCookieProcessor())

    def request(self, path, *, data=None, headers=None):
        url = path if path.startswith("http://") else urljoin(self.base_url + "/", path.lstrip("/"))
        request = Request(url, data=data, headers=headers or {})
        try:
            with self.opener.open(request, timeout=15) as response:
                return response.status, response.headers, response.read(), response.geturl()
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {error.code} for {url}: {body[:400]}") from error

    def html(self, path):
        status, headers, body, url = self.request(path)
        if status != 200:
            raise RuntimeError(f"Expected HTTP 200 for {path}, got {status}")
        parser = PageParser()
        parser.feed(body.decode("utf-8"))
        return parser, body, url


def exec_python(project, env, code, *, input_text=None):
    result = compose(project, env, "exec", "--no-TTY", "web", "python", "-c", code, input_text=input_text)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Container verification code did not return JSON: {result.stdout[:500]}") from error


SEED_CODE = r'''import django, json, sys, uuid
django.setup()
from django.contrib.auth import get_user_model
from app.domain import deserialize_bundle
from app.persistence import services
from app.persistence.services import review_context, review_revision

payload = json.load(sys.stdin)
User = get_user_model()
if User.objects.exists():
    raise SystemExit("New synthetic database already contains an account")
actor = User.objects.create_user(username=payload["username"], password=payload["password"])
household_id = payload["bundle"]["household_id"]
services.create_household(actor, household_id)
bundle = deserialize_bundle(json.dumps(payload["bundle"], ensure_ascii=False), check_snapshot_reviews=False)
services.stage_bundle(actor, bundle, request_key="synthetic-container-stage", expected_heads={})
review_ids = [
    "knowledge-fractions-r1", "method-common-denominator-r1", "type-fraction-sum-r1",
    "question-1-r1", "question-2-r1",
    "knowledge-fractions-to-question-1-r1-r1", "knowledge-fractions-to-question-2-r1-r1",
    "method-common-denominator-to-question-1-r1-r1", "method-common-denominator-to-question-2-r1-r1",
    "type-fraction-sum-to-question-1-r1-r1", "type-fraction-sum-to-question-2-r1-r1",
]
for revision_id in review_ids:
    context = review_context(actor, household_id, revision_id)
    review_revision(actor, household_id, revision_id, action="accept",
        expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
        expected_decision_id=context["expected_decision_id"], request_key=f"synthetic-review-{revision_id}",
        reason="Synthetic container restore verification")
print(json.dumps({"created": True, "review_count": len(review_ids)}))
'''


SNAPSHOT_CODE = r'''import django, hashlib, json
django.setup()
import stat
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.apps import apps
from app.persistence.models import (EvidenceRecord, EntityRecord, Household, HouseholdMember,
    ImageRecord, RequestReceipt, RevisionDependency, RevisionRecord, ReviewDecision, ReviewProjection)
from app.web.services import asset_path
from app.web.models import MaterialPage, MaterialSet, PagePreview, QuestionSource

models = [get_user_model(), Session, *[model for model in apps.get_models()
    if model.__module__.startswith('app.')]]
records = {model._meta.label: list(model.objects.order_by("pk").values()) for model in models}
encoded = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()
image_hashes = sorted(ImageRecord.objects.values_list("sha256", flat=True))
counts = {name: len(rows) for name, rows in records.items()}
preview_files = []
for preview in PagePreview.objects.select_related("image").order_by("image_id", "rotation"):
    path = asset_path(preview.storage_key, preview.sha256)
    metadata = path.stat()
    preview_files.append({"image_sha256": preview.image.sha256, "rotation": preview.rotation,
        "storage_key": preview.storage_key, "sha256": preview.sha256,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mode": stat.S_IMODE(metadata.st_mode), "uid": metadata.st_uid, "gid": metadata.st_gid})
asset_refs = {}
for image in ImageRecord.objects.order_by("pk"):
    storage_key = image.payload.get("storage_key")
    if isinstance(storage_key, str) and storage_key.startswith("web/"):
        asset_refs[storage_key] = image.sha256
for preview in PagePreview.objects.order_by("pk"):
    existing = asset_refs.setdefault(preview.storage_key, preview.sha256)
    if existing != preview.sha256:
        raise SystemExit(f"Conflicting database hashes for storage key {preview.storage_key}")
from app.printing.models import ExportSnapshot
from app.operations.models import ExportArchiveRecord, ExportRetirementRecord
for export in ExportSnapshot.objects.order_by('pk'):
    retired = ExportRetirementRecord.objects.filter(snapshot=export).first()
    storage_key = retired.archive_storage_key if retired else export.storage_key
    if retired:
        assert not (Path(settings.SWB_DATA_ROOT) / export.storage_key).exists()
    manifest_path = asset_path(storage_key + '/snapshot.json', export.manifest_sha256)
    asset_refs[storage_key + '/snapshot.json'] = export.manifest_sha256
    manifest = json.loads(manifest_path.read_text())
    for filename, item in manifest['files'].items():
        asset_refs[storage_key + '/' + filename] = item['sha256']
for archive in ExportArchiveRecord.objects.order_by('pk'):
    for filename, sha256 in archive.file_hashes.items():
        asset_refs[archive.archive_storage_key + '/' + filename] = sha256
asset_files = []
for storage_key, expected_hash in sorted(asset_refs.items()):
    path = asset_path(storage_key, expected_hash)
    metadata = path.stat()
    asset_files.append({"storage_key": storage_key, "sha256": expected_hash,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": metadata.st_size,
        "mode": stat.S_IMODE(metadata.st_mode), "uid": metadata.st_uid, "gid": metadata.st_gid})
print(json.dumps({"sha256": hashlib.sha256(encoded).hexdigest(), "counts": counts,
    "image_hashes": image_hashes, "review_decisions": counts[ReviewDecision._meta.label],
    "revisions": counts[RevisionRecord._meta.label], "dependencies": counts[RevisionDependency._meta.label],
    "preview_hashes": sorted(PagePreview.objects.values_list("sha256", flat=True)),
    "previews": list(PagePreview.objects.order_by("image_id", "rotation").values(
        "image__sha256", "rotation", "storage_key", "sha256")), "preview_files": preview_files,
    "asset_files": asset_files},
    sort_keys=True))
'''


def login(base_url, username, password):
    browser = Browser(base_url)
    status, _headers, _body, final_url = browser.request("/")
    if status != 200 or not urlsplit(final_url).path.startswith("/accounts/login/"):
        raise RuntimeError("Anonymous home request did not redirect to the login form")
    login_form, _body, _url = browser.html("/accounts/login/")
    login_values = dict(login_form.hidden)
    login_values.update({"username": username, "password": password, "next": "/"})
    status, _headers, _body, final_url = browser.request(
        "/accounts/login/", data=urlencode(login_values).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200 or urlsplit(final_url).path != "/":
        raise RuntimeError("Synthetic user could not log in through the rendered form")
    return browser


def upload_from_browser(browser):
    base_url = browser.base_url
    index, _body, _url = browser.html("/")
    if not index.household_id:
        raise RuntimeError("Synthetic user has no visible household membership")
    material_values = dict(index.hidden)
    material_values.update({"household_id": index.household_id, "title": "合成容器验收资料"})
    _status, _headers, _body, material_url = browser.request(
        "/material/new/", data=urlencode(material_values).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    material_path = urlsplit(material_url).path
    if not material_path.startswith("/material/") or not material_path.endswith("/"):
        raise RuntimeError("Synthetic user could not create a material set through the page")

    material, _body, _url = browser.html(material_path)
    token = material.hidden.get("csrfmiddlewaretoken")
    request_key = material.hidden.get("request_key")
    if not token or not request_key:
        raise RuntimeError("Upload form did not expose its normal CSRF and request-key fields")
    png_bytes = synthetic_png()
    boundary = f"----swb-{secrets.token_hex(12)}"
    body = bytearray()
    for key, value in (("csrfmiddlewaretoken", token), ("request_key", request_key)):
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
    body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"synthetic.png\"\r\nContent-Type: image/png\r\n\r\n".encode())
    body.extend(png_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    status, _headers, response_body, _url = browser.request(
        material_path, data=bytes(body), headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        })
    result = json.loads(response_body)
    if status != 200 or not result.get("ok"):
        raise RuntimeError("Synthetic image upload did not complete")
    page_path = f"/page/{result['page_id']}/"
    page, _body, _url = browser.html(page_path)
    preview_path = next((urlsplit(urljoin(base_url + "/", source)).path for source in page.images), None)
    if not preview_path or "/preview/0/" not in preview_path:
        raise RuntimeError("Uploaded page does not show its private image preview")
    status, headers, preview, _url = browser.request(preview_path)
    if status != 200 or headers.get_content_type() != "image/png":
        raise RuntimeError("Authenticated image preview was not returned as PNG")
    png_hash = hashlib.sha256(png_bytes).hexdigest()
    if hashlib.sha256(preview).hexdigest() == png_hash:
        raise RuntimeError("The preview unexpectedly has the original file bytes")

    if not index.stylesheets:
        raise RuntimeError("Production HTML omitted its static stylesheet")
    static_url = urljoin(base_url + "/", index.stylesheets[0])
    status, _headers, static, _url = browser.request(static_url)
    if status != 200 or b"page-shell" not in static:
        raise RuntimeError("WhiteNoise did not serve the collected CSS asset")
    return page_path, preview_path, hashlib.sha256(preview).hexdigest(), png_hash


def synthetic_png():
    import struct
    import zlib

    def chunk(kind, payload):
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    width, height = 32, 24
    row = b"\0" + bytes((90, 145, 210)) * width
    pixels = row * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def verify_preview(browser, path, expected_hash):
    status, headers, preview, final_url = browser.request(path)
    actual = hashlib.sha256(preview).hexdigest()
    if status != 200 or actual != expected_hash:
        raise RuntimeError(
            "Authenticated private preview mismatch: "
            f"status={status}, content_type={headers.get_content_type()}, "
            f"path={urlsplit(final_url).path}, actual_sha256={actual}, expected_sha256={expected_hash}"
        )


def stored_preview(snapshot, original_hash):
    matches = [row for row in snapshot.get("previews", [])
               if row.get("image__sha256") == original_hash and row.get("rotation") == 0]
    if len(matches) != 1:
        raise RuntimeError("Expected one stored rotation-0 preview for the uploaded synthetic image")
    return matches[0]


def checked_labels(project, owner, env):
    result = compose(project, env, "ps", "--all", "--quiet")
    containers = [item for item in result.stdout.splitlines() if item]
    for container in containers:
        details = command(["docker", "inspect", "--format", '{{index .Config.Labels "com.study-workbench.resource-owner"}} {{index .Config.Labels "com.docker.compose.project"}}', container])
        if details.stdout.strip() != f"{owner} {project}":
            raise RuntimeError(f"Resource ownership check failed for container {container}")
    return containers


def cleanup_project(project, owner, env):
    containers = checked_labels(project, owner, env)
    if containers:
        compose(project, env, "down", "--remove-orphans")
    for volume_name, args in (
        ("db_data", ["docker", "volume", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project}", "--filter", "label=com.docker.compose.volume=db_data"]),
        ("private_data", ["docker", "volume", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project}", "--filter", "label=com.docker.compose.volume=private_data"]),
    ):
        result = command(args)
        for volume in [item for item in result.stdout.splitlines() if item]:
            labels = command(["docker", "volume", "inspect", "--format", '{{index .Labels "com.study-workbench.resource-owner"}} {{index .Labels "com.docker.compose.project"}} {{index .Labels "com.docker.compose.volume"}}', volume]).stdout.strip()
            if labels != f"{owner} {project} {volume_name}":
                raise RuntimeError(f"Preserving volume with an unexpected owner label: {volume}")
            command(["docker", "volume", "rm", volume])
    for network in command(["docker", "network", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project}"]).stdout.splitlines():
        if not network:
            continue
        labels = command(["docker", "network", "inspect", "--format", '{{index .Labels "com.study-workbench.resource-owner"}} {{index .Labels "com.docker.compose.project"}}', network]).stdout.strip()
        if labels != f"{owner} {project}":
            raise RuntimeError(f"Preserving network with an unexpected owner label: {network}")
        command(["docker", "network", "rm", network])


def verify_container():
    command(["docker", "compose", "version"])
    command(["docker", "image", "inspect", POSTGRES_IMAGE])
    token = uuid.uuid4().hex[:16]
    main_project = f"swbd1-{token}"
    restore_project = f"swbd1-restore-{token}"
    main_owner = f"swb-d1-{token}"
    restore_owner = f"swb-d1-restore-{token}"
    image_tag = f"d1-verify-{token}"
    image_ref = f"study-workbench:{image_tag}"
    port = free_loopback_port()
    restore_port = free_loopback_port()
    while restore_port == port:
        restore_port = free_loopback_port()
    secret_key = secrets.token_urlsafe(48)
    db_password = secrets.token_urlsafe(36)
    primary_env = compose_env(main_owner, image_tag, port, secret_key, db_password)
    restore_env = compose_env(restore_owner, image_tag, restore_port, secret_key, db_password)
    for project in (main_project, restore_project):
        assert_project_absent(project)
    assert_image_absent(image_ref)

    temp_root = Path(tempfile.mkdtemp(prefix=f"swb-{token}-"))
    temp_root.chmod(0o700)
    image_built = False
    try:
        print(f"Isolation: projects={main_project},{restore_project}; owners={main_owner},{restore_owner}; bind=127.0.0.1:{port}; image={image_ref}", flush=True)
        compose(main_project, primary_env, "config", "--quiet")
        print("Building the pinned application image", flush=True)
        compose(main_project, primary_env, "build", "web")
        image_built = True
        compose(main_project, primary_env, "up", "--detach", "--wait", "--wait-timeout", "180")
        wait_compose_health(main_project, primary_env)
        container_id = compose(main_project, primary_env, "ps", "--quiet", "web").stdout.strip()
        uid = command(["docker", "exec", container_id, "id", "-u"]).stdout.strip()
        if uid != "10001":
            raise RuntimeError(f"Web process is running as uid {uid}, expected 10001")
        published = command(["docker", "port", container_id, "8000/tcp"]).stdout.strip()
        if published != f"127.0.0.1:{port}":
            raise RuntimeError(f"Web port is not bound only to loopback: {published}")
        print(f"Container process uid={uid}; host listener={published}; DB has no published port", flush=True)

        health, _ = wait_http(f"http://127.0.0.1:{port}/healthz", timeout=30)
        if health != 200:
            raise RuntimeError("Database-backed health endpoint is not ready")
        username = f"synthetic-{token}"
        password = secrets.token_urlsafe(24)
        bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
        seed_input = json.dumps({"username": username, "password": password, "bundle": bundle}, ensure_ascii=False)
        seed_result = exec_python(main_project, primary_env, SEED_CODE, input_text=seed_input)
        if not seed_result.get("created") or seed_result.get("review_count", 0) < 1:
            raise RuntimeError("Synthetic user and reviewed relationship data were not created")

        base_url = f"http://127.0.0.1:{port}"
        browser = login(base_url, username, password)
        page_path, preview_path, preview_hash, original_hash = upload_from_browser(browser)
        business = exec_python(main_project, primary_env,
            (ROOT / 'scripts/container_business_fixture.py').read_text(),
            input_text=json.dumps({'username': username, 'page_id': page_path.split('/')[2]}))
        if business['attempts'] != 3 or len(business['exports']) != 3 or not business['model_disabled']:
            raise RuntimeError('Synthetic business fixture was incomplete')
        for route in ('/knowledge/', '/learning/', '/catalogue/', '/study/', '/ai/', '/prints/', '/operations/'):
            browser.html(route)
        before = exec_python(main_project, primary_env, SNAPSHOT_CODE)
        if before.get("review_decisions", 0) < 1 or before.get("revisions", 0) < 1 or before.get("dependencies", 0) < 1:
            raise RuntimeError("Synthetic snapshot lacks reviewed revisions and relationships")
        if original_hash not in before.get("image_hashes", []):
            raise RuntimeError("Uploaded synthetic original image hash is missing from the database")
        source_preview = stored_preview(before, original_hash)
        if source_preview["sha256"] != preview_hash:
            raise RuntimeError("Served preview body does not match its database preview hash before backup")
        source_originals = [item for item in before["asset_files"] if item["sha256"] == original_hash]
        if len(source_originals) != 1:
            raise RuntimeError("Uploaded original storage key is missing or ambiguous in the database snapshot")
        print(f"Business path: login, private material upload, image preview, CSS; rows={before['counts']}", flush=True)

        backup_dir = temp_root / "backup"
        command(["bash", "scripts/backup_service.sh", main_project, str(backup_dir)], env=primary_env)
        manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest_files = {item.get("path"): item for item in manifest.get("files", [])}
        for asset in before["asset_files"]:
            entry = manifest_files.get(asset["storage_key"])
            if not entry:
                raise RuntimeError(f"Backup manifest is missing DB storage key: {asset['storage_key']}")
            for field in ("size", "sha256", "mode", "uid", "gid"):
                expected = asset["file_sha256"] if field == "sha256" else asset[field]
                if entry.get(field) != expected:
                    raise RuntimeError(
                        f"Backup manifest {field} differs from DB storage key {asset['storage_key']}"
                    )
        if not any(item.get("sha256") == original_hash for item in manifest.get("files", [])):
            raise RuntimeError("Backup file manifest does not contain the uploaded original image")
        if not any(item.get("sha256") == source_preview["sha256"] for item in manifest.get("files", [])):
            raise RuntimeError("Backup file manifest does not contain the database preview file")
        preview_paths = [item.get("path") for item in manifest.get("files", [])
                         if item.get("sha256") == source_preview["sha256"]]
        if source_preview["storage_key"] not in preview_paths:
            raise RuntimeError(
                "Backup contains preview bytes at a path different from the database storage key: "
                f"storage_key={source_preview['storage_key']}, archived_paths={preview_paths}"
            )
        if manifest["database_dump"]["size"] <= 0 or manifest["assets_archive"]["size"] <= 0:
            raise RuntimeError("Backup is missing its database dump or private file archive")
        print(f"Backup: pg_dump plus {len(manifest['files'])} hashed private files", flush=True)

        compose(main_project, primary_env, "up", "--detach", "--wait", "--wait-timeout", "180", "--force-recreate", "--no-deps", "web")
        wait_compose_health(main_project, primary_env)
        verify_preview(browser, preview_path, preview_hash)
        print("Persistence: uploaded file and authenticated session survived web container recreation", flush=True)

        compose(main_project, primary_env, "stop", "--timeout", "30", "web", "worker", "db")
        compose(restore_project, restore_env, "config", "--quiet")
        compose(restore_project, restore_env, "up", "--detach", "--wait", "--wait-timeout", "120", "db")
        command(["bash", "scripts/restore_service.sh", restore_project, str(backup_dir)], env=restore_env)
        refused = command(["bash", "scripts/restore_service.sh", restore_project, str(backup_dir)], env=restore_env, check=False)
        if refused.returncode == 0 or "non-empty database" not in refused.stderr:
            raise RuntimeError("Restore did not explicitly refuse a repeated restore into a non-empty database")
        compose(restore_project, restore_env, "up", "--detach", "--wait", "--wait-timeout", "180", "web", "worker")
        wait_compose_health(restore_project, restore_env)
        restored_container_id = compose(restore_project, restore_env, "ps", "--quiet", "web").stdout.strip()
        restored_uid = command(["docker", "exec", restored_container_id, "id", "-u"]).stdout.strip()
        if restored_uid != "10001":
            raise RuntimeError("Restored web service is not running as its non-root application uid")
        restored_base = f"http://127.0.0.1:{restore_port}"
        restored_browser = Browser(restored_base)
        # A fresh cookie jar proves the restored account still works, rather than
        # relying only on the original session cookie.
        restored = exec_python(restore_project, restore_env, SNAPSHOT_CODE)
        if restored.get("sha256") != before.get("sha256"):
            raise RuntimeError("Restored relations, revisions, review audit, or application rows differ from the backup point")
        if restored.get("image_hashes") != before.get("image_hashes"):
            raise RuntimeError("Restored original image hashes differ from the backup point")
        if restored.get("asset_files") != before.get("asset_files"):
            raise RuntimeError("Restored DB-keyed file path, hash, size, mode, or ownership differs from backup point")
        if restored.get("preview_files") != before.get("preview_files"):
            raise RuntimeError(
                f"Restored preview file metadata differs from backup point: "
                f"before={before.get('preview_files')}, after={restored.get('preview_files')}"
            )
        if preview_hash not in restored.get("preview_hashes", []):
            raise RuntimeError("Restored database does not include the preview hash served before backup")
        restored_preview = stored_preview(restored, original_hash)
        if restored_preview != source_preview:
            raise RuntimeError(
                f"Restored preview metadata differs from backup point: before={source_preview}, after={restored_preview}"
            )
        restored_browser = login(restored_base, username, password)
        verify_preview(restored_browser, preview_path, source_preview["sha256"])
        print(f"Empty-instance restore: rows and image hashes match; non-empty restore refused; uid={restored_uid}", flush=True)

        print(f"Verified projects: {main_project} (127.0.0.1:{port}), {restore_project} (127.0.0.1:{restore_port}); host data contained synthetic fixtures only", flush=True)
        return image_ref, main_project, restore_project, main_owner, restore_owner
    finally:
        for project, owner, env in ((restore_project, restore_owner, restore_env), (main_project, main_owner, primary_env)):
            try:
                cleanup_project(project, owner, env)
            except Exception as error:
                print(f"Cleanup stopped safely for project {project}: {error}", file=sys.stderr, flush=True)
        if image_built:
            details = command(["docker", "image", "inspect", "--format", '{{index .Config.Labels "com.study-workbench.resource-owner"}} {{json .RepoTags}}', image_ref], check=False)
            if details.returncode == 0:
                parts = details.stdout.strip().split(" ", 1)
                if len(parts) == 2 and parts[0] == main_owner and image_ref in json.loads(parts[1]):
                    command(["docker", "image", "rm", image_ref], check=False)
                else:
                    print("Preserving image because its owner label or tag does not match this run", file=sys.stderr, flush=True)
        shutil.rmtree(temp_root, ignore_errors=True)


def main():
    verify_container()


if __name__ == "__main__":
    main()
