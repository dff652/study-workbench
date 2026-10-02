#!/usr/bin/env python3
"""Phone browser acceptance using synthetic files in the owned test database.

Invoke through run_persistence_tests.py --browser, never against a user database.
The local development server and its files are temporary; screenshots contain
only synthetic material. Chromium must already be installed in a private cache.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def require_owned_database(owner):
    host = Path(os.environ.get("SWB_DB_HOST", ""))
    if (not owner or os.environ.get("SWB_TEST_OWNER") != owner
            or os.environ.get("SWB_DB_NAME") != "swb_synthetic"
            or not host.is_absolute()
            or not host.parent.name.startswith("swb-synthetic-pg-")
            or (host.parent / "owner").read_text() != owner
            or Path(os.environ["SWB_DATA_ROOT"]).parent != host.parent):
        raise RuntimeError("Browser acceptance requires the owned synthetic runner")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    require_owned_database(args.owner)
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connections
    from PIL import Image, ImageDraw
    from playwright.sync_api import sync_playwright, expect
    from app.persistence import services as core
    from app.persistence.models import EntityRecord, RevisionRecord, ReviewDecision
    from app.web.models import MaterialPage, MaterialSet, QuestionSource

    password = secrets.token_urlsafe(24)
    user = get_user_model().objects.create_user(username="synthetic-browser-parent", password=password)
    core.create_household(user, f"synthetic-browser-{args.owner}")
    image = Image.new("RGB", (600, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 120, 120), fill="#b43525")
    draw.text((40, 160), "SYNTHETIC ONLY - 1/3 + 1/6 = ?", fill="black")
    stream = BytesIO()
    image.save(stream, format="PNG")
    raw = stream.getvalue()

    output = ROOT / "artifacts" / "b1-verification" / args.owner
    output.mkdir(parents=True, mode=0o700)
    for parent in (output, output.parent, output.parent.parent):
        parent.chmod(0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    log_path = output / "server.log"
    log_path.touch(mode=0o600)
    checks = []
    server = None
    database_worker = ThreadPoolExecutor(max_workers=1)

    def db(operation):
        # Playwright's sync facade runs an event loop on this thread. Keep ORM
        # queries in a dedicated synchronous thread; retain Django's async guard.
        def query():
            try:
                return operation()
            finally:
                connections.close_all()
        return database_worker.submit(query).result()

    try:
        with log_path.open("w") as log:
            server = subprocess.Popen([sys.executable, "manage.py", "runserver",
                f"127.0.0.1:{port}", "--noreload", "--insecure"], cwd=ROOT, stdout=log, stderr=log)
            deadline = time.monotonic() + 15
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Local test server exited; see synthetic server.log")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Local test server did not start")
                    time.sleep(0.1)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 390, "height": 844},
                    is_mobile=True, has_touch=True, device_scale_factor=1)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                context.route("**/*", lambda route: route.continue_()
                    if urlparse(route.request.url).netloc == f"127.0.0.1:{port}" else route.abort())

                def fits(screen):
                    # Mobile browsers can widen innerWidth to fit overflowing
                    # content. Compare with the configured device width itself.
                    assert page.evaluate("document.documentElement.scrollWidth <= 391"), screen
                    checks.append(f"phone-width:{screen}")

                page.goto(origin)
                expect(page).to_have_url(origin + "/accounts/login/?next=/")
                page.locator("#id_username").fill(user.username)
                page.locator("#id_password").fill(password)
                page.get_by_role("button", name="登录", exact=True).click()
                expect(page.locator("#id_title")).to_be_visible()
                fits("materials")
                page.locator("#id_title").fill("合成浏览器资料")
                page.locator("form[action='/material/new/'] button").click()
                page.wait_for_url("**/material/*/")
                material = db(lambda: MaterialSet.objects.get(title="合成浏览器资料"))
                material_url = origin + f"/material/{material.pk}/"
                expect(page).to_have_url(material_url)
                files = [
                    {"name": "synthetic-first.png", "mimeType": "image/png", "buffer": raw},
                    {"name": "synthetic-copy.png", "mimeType": "image/png", "buffer": raw},
                    {"name": "invalid.png", "mimeType": "image/png", "buffer": b"synthetic invalid file"},
                ]
                page.locator("#id_image").set_input_files(files)
                page.locator("#upload-form button").click()
                expect(page.locator("#upload-status")).to_contain_text("2", timeout=20000)
                expect(page.locator("#upload-form button")).to_be_enabled()
                expect(page.locator("#upload-results")).to_contain_text("invalid.png")
                pages = db(lambda: list(MaterialPage.objects.filter(material=material).select_related("image").order_by("position")))
                assert len(pages) == 2 and pages[0].image_id == pages[1].image_id
                assert (Path(os.environ["SWB_DATA_ROOT"]) / pages[0].image.payload["storage_key"]).read_bytes() == raw
                checks.append("mixed-upload:per-file-result-and-byte-reuse")

                page.goto(material_url)
                page.locator(".move-down").first.click()
                page.get_by_role("button", name="保存顺序", exact=True).click()
                assert db(lambda: list(MaterialPage.objects.filter(material=material).order_by("position").values_list("pk", flat=True))) == [pages[1].pk, pages[0].pk]
                fits("page-order")
                page.goto(origin + f"/material/{material.pk}/question/new/")
                page.locator("#id_original_number").fill("合成题 1")
                page.locator("#id_printed_text").fill("1/3 + 1/6 = ?")
                page.locator("#id_reason").fill("人工录入合成印刷题干")
                first = page.locator(".region-card").first
                first.locator(".rotation-select").select_option("90")
                canvas = first.locator("canvas")
                canvas.scroll_into_view_if_needed()
                bounds = canvas.bounding_box()
                page.mouse.move(bounds["x"] + bounds["width"] * 0.1, bounds["y"] + bounds["height"] * 0.2)
                page.mouse.down()
                page.mouse.move(bounds["x"] + bounds["width"] * 0.7, bounds["y"] + bounds["height"] * 0.6, steps=5)
                page.mouse.up()
                first.locator(".add-region").click()
                sources = json.loads(page.locator("#id_sources").input_value())
                assert len(sources) == 1 and sources[0]["rotation"] == 90
                second = page.locator(".region-card").nth(1)
                for selector, value in zip((".coord-x0", ".coord-y0", ".coord-x1", ".coord-y1"), (10, 20, 200, 300)):
                    second.locator(selector).fill(str(value))
                second.locator(".add-coordinates").click()
                assert len(json.loads(page.locator("#id_sources").input_value())) == 2
                fits("region-editor")
                page.locator("#question-form > .form-actions button").click()
                expect(page.locator(".printed-text")).to_have_text("1/3 + 1/6 = ?")
                question_url = page.url
                question_id = question_url.rstrip("/").split("/")[-1]
                entity = db(lambda: EntityRecord.objects.get(kind="question", stable_id=question_id))
                old_id = entity.head_revision_id
                old_sources = db(lambda: QuestionSource.objects.get(revision_id=old_id).sources)
                assert len(old_sources) == 2 and old_sources[0]["rotation"] == 90
                expect(page.locator(".source-list li")).to_have_count(2)
                source_url = page.locator(".source-list a").first.get_attribute("href")
                checks.append("multi-page-source:drag-and-keyboard-and-original-coordinates")
                page.locator("#id_action").select_option("accept")
                page.locator("#id_reason").fill("核对合成题干与来源")
                page.get_by_role("button", name="记录审核决定", exact=True).click()
                assert db(lambda: ReviewDecision.objects.filter(revision_id=old_id, action="accept").count()) == 1

                stale = context.new_page()
                stale.goto(question_url + "edit/")
                page.goto(question_url + "edit/")
                assert len(json.loads(page.locator("#id_sources").input_value())) == 2
                page.locator("#id_printed_text").fill("1/3 + 1/6 = ? 请写出过程。")
                page.locator("#id_reason").fill("补充印刷指令；保留首次版本")
                page.locator("#question-form > .form-actions button").click()
                db(entity.refresh_from_db)
                assert entity.head_revision_id != old_id and entity.published_revision_id == old_id
                assert db(lambda: RevisionRecord.objects.get(pk=old_id).payload["printed_text"]) == "1/3 + 1/6 = ?"
                assert db(lambda: QuestionSource.objects.get(revision_id=old_id).sources) == old_sources
                expect(page.locator(".history-list")).to_contain_text("1/3 + 1/6 = ?")
                expect(page.locator(".history-list .history-source")).to_have_count(4)
                stale.locator("#id_reason").fill("过期标签页不应覆盖")
                with stale.expect_response(lambda response: response.request.method == "POST") as result:
                    stale.locator("#question-form > .form-actions button").click()
                assert result.value.status == 409
                checks.append("revision-history:old-text-region-review-retained-and-stale-edit-rejected")

                page.goto(origin + source_url)
                expect(page.locator(".linked-questions")).to_contain_text("合成题 1")
                fits("source-backlink")
                page.goto(question_url)
                fits("question-history")
                for preview in page.locator(".history-source img").all():
                    preview.scroll_into_view_if_needed()
                    page.wait_for_function("image => image.complete && image.naturalWidth > 0",
                        arg=preview.element_handle())
                page.evaluate("scrollTo(0, 0)")
                screenshot = output / "phone-question-history.png"
                page.screenshot(path=str(screenshot), full_page=True)
                screenshot.chmod(0o600)
                preview_url = origin + f"/page/{pages[0].pk}/preview/0/"
                response = context.request.get(preview_url)
                assert response.status == 200 and "no-store" in response.headers["cache-control"]
                assert "no-store" in context.request.get(question_url).headers["cache-control"]
                page.locator("form[action='/accounts/logout/'] button").click()
                response = context.request.get(preview_url, max_redirects=0)
                assert response.status == 302
                checks.append("privacy:authenticated-images-no-store-and-logout-revocation")
                assert not errors, errors
                browser.close()
        report = {"synthetic_only": True, "viewport": [390, 844], "checks": checks,
            "question_revisions": 2, "source_regions_per_revision": 2, "javascript_errors": errors,
            "browser": "Playwright Chromium", "deployment": False}
        report_path = output / "verification.local.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        report_path.chmod(0o600)
        print(f"Phone browser acceptance passed: {len(checks)} checks; report={report_path}", flush=True)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        connections.close_all()
        database_worker.shutdown()


if __name__ == "__main__":
    main()
