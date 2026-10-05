#!/usr/bin/env python3
"""Exercise authenticated business workflows in an owned synthetic browser run.

The persistence runner supplies an isolated PostgreSQL database and private
data root. This script writes only synthetic records through the local UI and
keeps browser artifacts private.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def require_owned_database(owner):
    host = Path(os.environ.get("SWB_DB_HOST", ""))
    data_root = Path(os.environ.get("SWB_DATA_ROOT", ""))
    marker = host.parent / "owner"
    if (not owner or os.environ.get("SWB_TEST_OWNER") != owner
            or os.environ.get("SWB_DB_NAME") != "swb_synthetic"
            or not host.is_absolute() or not host.parent.name.startswith("swb-synthetic-pg-")
            or not marker.is_file() or marker.read_text().strip() != owner
            or not data_root.is_absolute() or data_root.parent != host.parent):
        raise RuntimeError("Business browser acceptance requires its owned synthetic runner")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    require_owned_database(args.owner)

    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connections
    from django.utils.formats import date_format
    from PIL import Image, ImageDraw
    from playwright.sync_api import expect, sync_playwright
    from app.persistence import services as core
    from app.persistence.models import EntityRecord, Household, ReviewDecision, RevisionRecord
    from app.web.models import MaterialPage, MaterialSet, QuestionSource, ImageDerivative
    from app.ai.models import ModelConfig, ModelRun
    from app.catalogue.models import QuestionLineage
    from app.printing.models import AnswerDecision, ExportSnapshot, TeacherAnswerRevision, TeachingDiagramRevision
    from app.study.models import ScheduleRevision
    from app.operations.models import RetentionPolicyRevision, WorkTiming

    artifact_owner = re.sub(r"[^A-Za-z0-9_.-]", "_", args.owner)
    output = ROOT / "artifacts" / "business-verification" / artifact_owner
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    for parent in (output, output.parent, output.parent.parent):
        parent.chmod(0o700)
    log_path = output / "server.log"
    log_path.touch(mode=0o600, exist_ok=True)

    password = secrets.token_urlsafe(24)
    user = get_user_model().objects.create_user(
        username=f"synthetic-business-{uuid4().hex[:12]}", password=password)
    core.create_household(user, f"synthetic-business-{artifact_owner}")
    household_id = Household.objects.filter(memberships__user_id=user.pk).values_list("pk", flat=True).get()

    image = Image.new("RGB", (600, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 120, 120), fill="#b43525")
    draw.text((40, 160), "SYNTHETIC ONLY - 1/3 + 1/6 = ?", fill="black")
    draw.text((40, 180), "(-2)^2 / (x^2)^3 / sqrt(x)", fill="black")
    stream = BytesIO()
    image.save(stream, format="PNG")
    raw_image = stream.getvalue()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    checks = []
    errors = []
    blocked_requests = []
    office_documents=[]
    region_control_surfaces = set()
    server = None
    database_worker = ThreadPoolExecutor(max_workers=1)

    def db(operation):
        # Keep all ORM access off Playwright's event-loop thread.
        def query():
            try:
                return operation()
            finally:
                connections.close_all()
        return database_worker.submit(query).result()

    def selected_revision(entity_pk):
        return db(lambda: EntityRecord.objects.get(pk=entity_pk).head_revision_id)

    try:
        with log_path.open("w") as log:
            server = subprocess.Popen([sys.executable, "manage.py", "runserver",
                f"127.0.0.1:{port}", "--noreload", "--insecure"], cwd=ROOT,
                stdout=log, stderr=log)
            deadline = time.monotonic() + 20
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Local browser test server exited; inspect the private server.log")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Local browser test server did not start")
                    time.sleep(0.1)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 390, "height": 844},
                    is_mobile=True, has_touch=True, device_scale_factor=1)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route_guard(route):
                    if urlparse(route.request.url).netloc == f"127.0.0.1:{port}":
                        route.continue_()
                    else:
                        blocked_requests.append(route.request.url)
                        route.abort()

                context.route("**/*", route_guard)
                page.on("console", lambda message: errors.append(f"console.error: {message.text}")
                    if message.type == "error" else None)

                def fit(label):
                    scroll_width = page.evaluate("document.documentElement.scrollWidth")
                    viewport_width = page.viewport_size["width"]
                    if scroll_width > viewport_width + 1:
                        overflow = page.evaluate("""() => ({viewport: innerWidth, body: {
                            clientWidth: document.body.clientWidth, scrollWidth: document.body.scrollWidth},
                            elements: [...document.body.querySelectorAll('*')].map(element => {
                                const rect = element.getBoundingClientRect();
                                return {tag: element.tagName, id: element.id, className: String(element.className),
                                    left: Math.round(rect.left), right: Math.round(rect.right),
                                    width: Math.round(rect.width), scrollWidth: element.scrollWidth};
                            }).filter(item => item.left < -1 || item.right > innerWidth + 1).slice(0, 12)})""")
                        raise AssertionError({"page": label, "document_scroll_width": scroll_width,
                            "overflow": overflow})
                    checks.append(f"{'phone' if viewport_width == 390 else 'desktop'}-width:{label}")

                def screenshot(name):
                    page.evaluate("scrollTo(0, 0)")
                    path = output / name
                    page.screenshot(path=str(path))
                    path.chmod(0o600)

                def goto(path, label):
                    response = page.goto(origin + path)
                    assert response and response.status == 200, (label, response.status if response else None)
                    fit(label)

                def add_region(card=None):
                    card = card or page.locator(".region-card").first
                    assert page.locator(".region-card").count() > 0, "synthetic source page is missing"
                    tools = card.locator(".region-image-tools")
                    assert tools.count() == 1, "shared image tools are missing"
                    tools.locator(".region-zoom-in").click()
                    expect(tools.locator(".region-zoom-status")).to_have_text("图片 150%")
                    tools.locator(".region-pan-mode").click()
                    expect(tools.locator(".region-pan-mode")).to_have_attribute("aria-pressed", "true")
                    tools.locator(".region-select-mode").click()
                    expect(tools.locator(".region-select-mode")).to_have_attribute("aria-pressed", "true")
                    tools.locator(".region-zoom-out").click()
                    expect(tools.locator(".region-zoom-status")).to_have_text("图片 100%")
                    tools.locator(".region-reset-view").click()
                    path = urlparse(page.url).path
                    if "/question/" in path:
                        region_control_surfaces.add("question")
                    elif path.startswith("/knowledge/"):
                        region_control_surfaces.add("knowledge")
                    elif path.startswith("/learning/"):
                        region_control_surfaces.add("learning")
                    for selector, value in zip((".coord-x0", ".coord-y0", ".coord-x1", ".coord-y1"),
                            (10, 20, 400, 500)):
                        card.locator(selector).fill(str(value))
                    card.locator(".add-coordinates").click()
                    sources = json.loads(page.locator("input[name='sources']").input_value())
                    assert sources, "coordinate selection did not create an evidence region"
                    return sources

                def review_for_revision(revision_id):
                    expected_form = page.locator(
                        f"article[id='revision-{revision_id}'] form.review-form")
                    expect(expected_form).to_be_visible(timeout=15000)
                    forms = page.locator("form.review-form")
                    matches = [forms.nth(index) for index in range(forms.count())
                        if forms.nth(index).locator("input[name='revision_id']").input_value() == str(revision_id)]
                    if len(matches) != 1:
                        details = forms.evaluate_all("""forms => forms.map(form => ({
                            revisionId: form.querySelector("input[name='revision_id']")?.value,
                            actionOptions: [...form.querySelectorAll("select[name='action'] option")].map(option => option.value)
                        }))""")
                        revision = db(lambda: RevisionRecord.objects.select_related(
                            "entity", "review_projection").get(pk=revision_id))
                        page_forms = page.locator("form").evaluate_all("""forms => forms.map(form => ({
                            className: form.className,
                            action: form.getAttribute("action"),
                            fieldNames: [...form.querySelectorAll("input, select, textarea")].map(field => field.name)
                        }))""")
                        raise AssertionError({"expected_revision": revision_id, "page": page.url,
                            "review_forms": details, "revision_state": revision.review_projection.state,
                            "entity_head": revision.entity.head_revision_id,
                            "entity_published": revision.entity.published_revision_id,
                            "page_forms": page_forms})
                    return matches[0]

                def create_question(number, printed_text, markup=None):
                    goto(f"/material/{material.pk}/question/new/", "question-form")
                    page.locator("#id_original_number").fill(number)
                    page.locator("#id_printed_text").fill(printed_text)
                    if markup:
                        page.locator('#id_display_markup').fill(markup)
                        assert not page.locator('#id_image_print_confirmed').is_checked()
                        if '[[image:' in markup:page.locator('#id_image_print_confirmed').check()
                    page.locator("#id_reason").fill("录入合成印刷题目")
                    sources = add_region()
                    page.locator("#question-form > .form-actions button[value='draft']").click()
                    expect(page.locator(".printed-text")).to_have_text(printed_text,use_inner_text=True)
                    question_url = page.url
                    stable_id = question_url.rstrip("/").split("/")[-1]
                    question = db(lambda: EntityRecord.objects.get(kind="question", stable_id=stable_id))
                    entity_pk = question.pk
                    revision_id = question.head_revision_id
                    source_refs = db(lambda: QuestionSource.objects.get(revision_id=revision_id).sources)
                    assert len(source_refs) == len(sources) == 1
                    page.locator("#id_action").select_option("accept")
                    page.locator("#id_reason").fill("核对合成题干与原图区域")
                    page.get_by_role("button", name="记录审核决定", exact=True).click()
                    published = db(lambda: EntityRecord.objects.get(pk=entity_pk).published_revision_id)
                    assert published == revision_id, "question approval did not publish its exact revision"
                    checks.append(f"question-create-review:{number}")
                    return {"pk": entity_pk, "stable_id": question.stable_id,
                        "revision_id": revision_id, "url": urlparse(question_url).path, "number": number}

                page.goto(origin)
                expect(page).to_have_url(re.compile(re.escape(origin) + r"/accounts/login/"))
                page.locator("#id_username").fill(user.username)
                page.locator("#id_password").fill(password)
                page.get_by_role("button", name="登录", exact=True).click()
                expect(page.locator("#id_title")).to_be_visible()
                fit("materials-home")

                goto(f"/ai/?household={household_id}", "ai-default-off")
                expect(page.locator("body")).to_contain_text("尚未配置模型服务")
                assert page.locator("a[href^='/ai/new/']").count() == 0
                assert db(lambda: ModelConfig.objects.filter(household_id=household_id).count()) == 0
                checks.append("ai-default-off-before-configuration")

                goto(f"/ai/config/{household_id}/", "ai-owner-config-form")
                config_form = page.locator("form.stack-form")
                assert config_form.locator("input[name='csrfmiddlewaretoken']").input_value()
                field_names = config_form.locator("input, select").evaluate_all(
                    "elements => elements.map(element => element.name.toLowerCase())")
                assert not any("key" in name or "secret" in name for name in field_names), field_names
                assert config_form.locator("input[type='password']").count() == 0
                page.locator("#id_provider_label").fill("Synthetic placeholder")
                page.locator("#id_base_url").fill("https://example.invalid/v1")
                page.locator("#id_model").fill("synthetic-placeholder")
                page.get_by_text("上游与留存说明", exact=True).click()
                page.locator("#id_connection_route").select_option("unknown")
                page.locator("#id_upstream_state").select_option("unknown")
                page.locator("#id_retention_state").select_option("unknown")
                page.locator("#id_outbound_scope").select_option("reviewed_text")
                assert not page.locator("#id_cloud_enabled").is_checked()
                assert not page.locator("#id_confirm_external_processing").is_checked()
                page.get_by_role("button", name="保存新配置", exact=True).click()
                expect(page.locator("body")).to_contain_text("Synthetic placeholder")
                expect(page.locator("body")).to_contain_text("未启用")
                assert page.locator("a[href^='/ai/new/']").count() == 0
                config_row = db(lambda: ModelConfig.objects.get(household_id=household_id))
                assert (config_row.revision_no == 1 and config_row.created_by_id == user.pk
                    and not config_row.cloud_enabled and config_row.provider_label == "Synthetic placeholder"
                    and config_row.base_url == "https://example.invalid/v1"
                    and config_row.model == "synthetic-placeholder"
                    and config_row.connection_route == "unknown"
                    and config_row.upstream_state == "unknown"
                    and config_row.retention_state == "unknown"
                    and config_row.outbound_scope == "reviewed_text")
                assert db(lambda: ModelRun.objects.filter(household_id=household_id).count()) == 0
                screenshot("phone-ai-home.png")
                checks.append("ai-owner-disabled-https-config-no-secret-or-task")

                goto("/", "materials-home-after-ai-config")
                page.locator("#id_title").fill("合成业务验收资料")
                page.locator("form[action='/material/new/'] button").click()
                page.wait_for_url("**/material/*/")
                material = db(lambda: MaterialSet.objects.get(title="合成业务验收资料"))
                material_url = origin + f"/material/{material.pk}/"
                page.locator("#id_image").set_input_files([
                    {"name": "synthetic-business-1.png", "mimeType": "image/png", "buffer": raw_image},
                    {"name": "synthetic-business-2.png", "mimeType": "image/png", "buffer": raw_image},
                ])
                page.locator("#upload-form button").click()
                expect(page.locator("#upload-status")).to_contain_text("2", timeout=20000)
                expect(page.locator("#upload-form button")).to_be_enabled(timeout=20000)
                pages = db(lambda: list(MaterialPage.objects.filter(material=material).select_related("image").order_by("position")))
                assert len(pages) == 2 and pages[0].image_id == pages[1].image_id
                assert (Path(os.environ["SWB_DATA_ROOT"]) / pages[0].image.payload["storage_key"]).read_bytes() == raw_image
                checks.append("synthetic-upload-byte-reuse")

                # Exercise the actual manual entry, reviewed revision and print path.
                formula_text='合成公式题\n1/3 + 1/6\n(-2)^2\n(x^2)^3\nsqrt(x)'
                formula_markup='**合成公式题**\n[[math:1/3 + 1/6]]\n[[math:(-2)^2]]\n[[math:(x^2)^3]]\n[[image:1|sqrt(x)]]'
                question_one = create_question("合成题 A",formula_text,formula_markup)
                question_two = create_question("合成题 B", "2/5 + 1/10 = ?")
                # Local derivative controls use the same page selection and original pixels.
                material_page=db(lambda:MaterialPage.objects.select_related('image').filter(material=material).first())
                goto(f'/page/{material_page.pk}/','image-derivatives')
                card=page.locator('.region-card').first
                for selector,value in zip(('.coord-x0','.coord-y0','.coord-x1','.coord-y1'),(10,20,400,500)):
                    card.locator(selector).fill(str(value))
                card.locator('.add-coordinates').click()
                page.locator('#use-derivative-region').click()
                assert json.loads(page.locator('#derivative-form [name=display_bbox]').input_value())==[10,20,400,500]
                for operation in ('crop','erase','contrast'):
                    form=page.locator('#derivative-form')
                    form.locator('[name=operation]').select_option(operation)
                    form.locator('[name=display_bbox]').fill('[10,20,400,500]')
                    form.locator('[name=masks]').fill('[[20,30,40,50]]' if operation=='erase' else '[]')
                    form.get_by_role('button',name='生成新的派生记录',exact=True).click()
                    expect(page.locator('h2').filter(has_text='本机派生处理')).to_be_visible()
                derivatives=db(lambda:list(ImageDerivative.objects.filter(page=material_page)))
                assert {d.operation for d in derivatives}=={'crop','erase','contrast'}
                assert all(d.original_sha256==material_page.image.sha256 for d in derivatives)
                response=context.request.get(origin+f'/derivative/{derivatives[0].pk}/')
                assert response.status==200 and 'no-store' in response.headers['cache-control']
                checks.append('local-crop-erase-contrast-source-and-private-file')
                goto(question_one["url"], "question-history")
                screenshot("phone-question.png")

                # Create, accept, revise, and re-accept a sourced knowledge node.
                goto(f"/knowledge/?household_id={household_id}", "knowledge-index")
                page.locator("a[href*='/knowledge/create/knowledge/']").click()
                page.locator("#id_definition").fill("分数相加时，先通分再相加分子。")
                page.locator('#id_display_markup').fill('**分数相加时，先通分再相加分子。**')
                page.locator("#id_conditions").fill("分母不同的两个分数")
                page.locator("#id_common_errors").fill("遗漏通分")
                page.locator("#id_reason").fill("整理合成分数规则")
                add_region()
                page.locator("#knowledge-form .form-actions button[type='submit']").click()
                expect(page).to_have_url(re.compile(re.escape(origin) + r"/knowledge/entity/\d+/$"))
                node_url = page.url
                node_pk = int(node_url.rstrip("/").split("/")[-1])
                node = db(lambda: EntityRecord.objects.get(pk=node_pk))
                node_revision_one = selected_revision(node_pk)
                original_definition = db(lambda: RevisionRecord.objects.get(pk=node_revision_one).payload["definition"])
                review = review_for_revision(node_revision_one)
                review.locator("select[name='action']").select_option("accept")
                review.locator("textarea[name='reason'], input[name='reason']").fill("核对合成知识内容与来源")
                review.locator("button[type='submit']").click()
                assert db(lambda: EntityRecord.objects.get(pk=node_pk).published_revision_id) == node_revision_one
                page.goto(node_url + "edit/")
                page.locator("#id_definition").fill("分数相加先通分，再相加分子并保留公分母。")
                page.locator('#id_display_markup').fill('==分数相加先通分，再相加分子并保留公分母。==')
                page.locator("#id_conditions").fill("分母不同且需进行加减运算")
                page.locator("#id_common_errors").fill("忘记同步放大分子")
                page.locator("#id_reason").fill("补充分子同步放大的说明")
                page.locator("#knowledge-form .form-actions button[type='submit']").click()
                expect(page).to_have_url(re.compile(re.escape(node_url) + "$"))
                node_revision_two = selected_revision(node_pk)
                node_state = db(lambda: EntityRecord.objects.get(pk=node_pk))
                assert node_revision_two != node_revision_one and node_state.published_revision_id == node_revision_one
                assert db(lambda: RevisionRecord.objects.get(pk=node_revision_one).payload["definition"]) == original_definition
                review = review_for_revision(node_revision_two)
                review.locator("select[name='action']").select_option("accept")
                review.locator("textarea[name='reason'], input[name='reason']").fill("审核知识点新修订")
                review.locator("button[type='submit']").click()
                assert db(lambda: EntityRecord.objects.get(pk=node_pk).published_revision_id) == node_revision_two
                checks.append("knowledge-create-edit-review-immutable-history")

                page.goto(node_url)
                page.locator("#id_node_revision_id").select_option(str(node_revision_two))
                page.locator("#id_question_revision_id").select_option(str(question_one["revision_id"]))
                page.locator("#id_role").select_option("applies")
                page.locator(".link-editor #id_reason").fill("合成题适用此知识点")
                page.locator(".link-editor button[type='submit']").click()
                relation_review = page.locator("form.inline-review-form").last
                relation_review.locator("select[name='action']").select_option("accept")
                relation_review.locator("textarea[name='reason'], input[name='reason']").fill("核对已发布端点")
                relation_review.locator("button[type='submit']").click()
                goto(f"/knowledge/question/{question_one['pk']}/", "knowledge-question-backlink")
                reverse_link = page.locator(".association-list a[href^='/knowledge/entity/']").first
                expect(reverse_link).to_have_attribute("href", f"/knowledge/entity/{node_pk}/")
                screenshot("phone-knowledge.png")
                checks.append("knowledge-question-bidirectional-association")

                # Learning profile, deliberately unknown observation, and sourced confirmation.
                goto(f"/learning/?household={household_id}", "learning-home")
                page.locator("#id_display_name").fill("合成学习者")
                page.locator("#id_grade").fill("合成班级")
                page.locator("form[action='/learning/profile/new/'] button").click()
                learner_url = page.url
                learner_id = learner_url.rstrip("/").split("/")[-1]
                goto(f"/learning/observation/new/?household={household_id}", "unknown-observation-form")
                page.locator("#id_profile_context_id").select_option(learner_id)
                page.locator("#id_author_state").select_option("unknown")
                page.locator("#id_actual_date_state").select_option("unknown")
                page.locator("#id_legibility").select_option("unknown")
                page.locator("#id_notes").fill("合成记录：作者与实际日期均未知，先保留证据缺口。")
                page.locator("#id_reason").fill("记录未知来源")
                page.locator("#learning-observation-form button[type='submit']").click()
                expect(page.locator(".learning-facts")).to_contain_text("未知")
                expect(page.locator("main .notice")).to_contain_text("没有来源区域")
                checks.append("learning-unknown-observation-retained")

                goto(f"/learning/observation/new/?household={household_id}", "confirmed-observation-form")
                page.locator("#id_profile_context_id").select_option(learner_id)
                page.locator("#id_author_state").select_option("confirmed")
                page.locator("#id_author_learner_id").select_option(learner_id)
                page.locator("#id_confirmation_basis").fill("仅用于合成验收的人工身份确认")
                page.locator("#id_actual_date_state").select_option("known")
                page.locator("#id_actual_date").fill("2026-10-01")
                page.locator("#id_legibility").select_option("readable")
                page.locator("#id_notes").fill("合成清晰来源区域，实际日期已按合成记录填写。")
                page.locator("#id_reason").fill("确认合成来源观察")
                observation_sources = add_region()
                page.locator("#learning-observation-form button[type='submit']").click()
                observation_id = page.url.rstrip("/").split("/")[-1]
                assert len(observation_sources) == 1
                checks.append("learning-confirmed-observation-with-region")

                def create_attempt(kind, source, independence, prompt_status, previous=None,
                                   actual_date_state="unknown", answer_text=""):
                    goto(f"/learning/profile/{learner_id}/attempt/new/", f"attempt-{source}")
                    page.locator("#id_question_id").select_option(question_one["stable_id"])
                    page.locator("#id_attempt_kind").select_option(kind)
                    page.locator("#id_source_kind").select_option(source)
                    page.locator("#id_independence").select_option(independence)
                    page.locator("#id_prompt_status").select_option(prompt_status)
                    if source == "assisted_answer":
                        page.locator("#id_prompts").fill("指出先通分")
                    page.locator("#id_actual_date_state").select_option(actual_date_state)
                    if actual_date_state == "known":
                        page.locator("#id_actual_date").fill("2026-10-01")
                    page.locator("#id_legibility").select_option("readable" if source != "unknown" else "unknown")
                    page.locator("#id_answer_text").fill(answer_text)
                    page.locator("#id_authorship_basis").fill("合成演练：作者由人工明确确认")
                    page.locator("input[name='observation_values']").first.check()
                    if previous:
                        page.locator("#id_previous_attempt_id").select_option(previous)
                    page.get_by_role("button", name="保存作答记录", exact=True).click()
                    attempt_id = page.url.rstrip("/").split("/")[-1]
                    expect(page.locator(".history-list")).to_contain_text("修订 1")
                    attempt = db(lambda: EntityRecord.objects.get(kind="attempt", stable_id=attempt_id))
                    revision_id = attempt.head_revision_id
                    checks.append(f"attempt-evidence:{source}")
                    return attempt_id, revision_id

                attempt_one, attempt_one_revision = create_attempt("first", "unknown", "unknown", "unknown")
                attempt_two, _ = create_attempt("correction", "classroom_note", "not_independent", "unknown", attempt_one)
                attempt_three, _ = create_attempt("retry", "assisted_answer", "not_independent", "given", attempt_two)
                independent_attempt, independent_attempt_revision = create_attempt("retest", "independent_answer",
                    "confirmed_independent", "none_confirmed", attempt_three, "known", "1/2")
                goto(f"/learning/attempt/{independent_attempt}/", "independent-attempt")
                expect(page.locator("main .notice")).to_contain_text("证据不足")
                screenshot("phone-attempt.png")

                page.locator("a[href$='/assessment/new/']").first.click()
                assessment_form_url = page.url
                for dimension in ("answer", "method", "process", "calculation", "notation"):
                    page.locator(f"#id_{dimension}_judgment").select_option("correct")
                    page.locator(f"#id_{dimension}_basis").select_option("observed")
                    page.locator(f"input[name='{dimension}_evidence']").first.check()
                    page.locator(f"#id_{dimension}_rationale").fill("合成原图区域直接支持此判断")
                    page.locator(f"#id_{dimension}_unknown_reason").fill("")
                page.locator("#id_reason").fill("五维合成评价初版")
                page.get_by_role("button", name="保存为待审核评价", exact=True).click()
                assessment_url = page.url
                assessment_id = assessment_url.rstrip("/").split("/")[-1]
                page.goto(assessment_url + "edit/")
                page.locator("#id_reason").fill("追加五维评价历史修订")
                page.get_by_role("button", name="保存为待审核评价", exact=True).click()
                assessment = db(lambda: EntityRecord.objects.get(kind="assessment", stable_id=assessment_id))
                assessment_revision_two = assessment.head_revision_id
                assert db(lambda: RevisionRecord.objects.filter(entity=assessment).count()) == 2
                review = page.locator("form[action$='/review/']")
                expect(review).to_have_count(1)
                review.locator("select[name='action']").select_option("accept")
                review.locator("textarea[name='reason'], input[name='reason']").fill("接受当前五维评价修订")
                review.locator("button[type='submit']").click()
                assert db(lambda: EntityRecord.objects.get(kind="assessment", stable_id=assessment_id).published_revision_id) == assessment_revision_two
                assert db(lambda: ReviewDecision.objects.filter(revision_id=assessment_revision_two, action="accept").count()) == 1
                expect(page.locator(".history-list > li")).to_have_count(2)
                expect(page.locator(".history-list")).to_contain_text("已接受")
                for dimension_label in ("答案", "方法选择", "解题过程", "计算", "符号表达"):
                    expect(page.locator(".dimension-grid")).to_contain_text(dimension_label)
                checks.append("five-dimension-assessment-review-and-history")

                profile_path = f"/learning/profile/{learner_id}/"
                profile_url = origin + profile_path
                goto(profile_path, "learner-history")
                for value in ("来源未知", "课堂笔记", "提示后作答", "独立作答"):
                    expect(page.locator(".learning-attempt-list")).to_contain_text(value)
                expect(page.locator(".learning-attempt-list")).to_contain_text("已接受")
                expect(page.locator(".learning-attempt-list")).to_contain_text("有已审核的独立成功证据")
                expect(page.locator(".history-list")).to_contain_text("作者 未知")
                checks.append("learner-attempt-history-all-source-kinds")
                screenshot("phone-learning-history.png")
                goto(f"/learning/attempt/{independent_attempt}/", "accepted-independent-attempt")
                expect(page.locator(".notice.success")).to_contain_text("独立成功")
                for not_independent in (attempt_one, attempt_two, attempt_three):
                    goto(f"/learning/attempt/{not_independent}/", "non-independent-attempt")
                    assert page.locator(".notice.success").count() == 0
                checks.append("independent-success-gating")

                # The teacher answer and its decision are independent of learning assessment.
                goto(f"/prints/answers/{question_one['revision_id']}/", "teacher-answer")
                teacher_answer = "合成答案仅由家长单独录入"
                page.locator("#id_body").fill(teacher_answer)
                page.locator("#id_formulas").fill("1/3 + 1/6")
                page.locator("#id_basis").fill("按公分母 6 复算")
                page.get_by_role("button", name="保存答案草稿", exact=True).click()
                answer = db(lambda: TeacherAnswerRevision.objects.get(question_revision_id=question_one["revision_id"]))
                page.locator("input[name='reason']").fill("按合成原图复算答案")
                page.locator("button[name='action'][value='accepted']").click()
                assert db(lambda: AnswerDecision.objects.filter(answer=answer, action="accepted").count()) == 1
                assert db(lambda: EntityRecord.objects.get(kind="assessment", stable_id=assessment_id).head_revision_id) == assessment_revision_two
                checks.append("teacher-answer-separate-review")

                def create_export(purpose, title):
                    goto("/prints/", f"print-{purpose}")
                    page.locator("#id_household").select_option(str(household_id))
                    page.locator("#id_title").fill(title)
                    page.locator("#id_purpose").select_option(purpose)
                    page.locator(f"input[name='questions'][value='{question_one['revision_id']}']").check()
                    page.get_by_role("button", name=re.compile("生成 PDF／Word")).click()
                    expect(page.locator("h1")).to_have_text(title)
                    snapshot_id = int(page.url.rstrip("/").split("/")[-1])
                    row = db(lambda: ExportSnapshot.objects.get(pk=snapshot_id))
                    import shutil
                    from app.exports.snapshots import private_directory,verify_snapshot
                    parent=ROOT/'exports'/'gap-closure-business'
                    for directory in (ROOT/'exports',parent,parent/artifact_owner):private_directory(directory)
                    destination=parent/artifact_owner/row.export_id
                    shutil.copytree(Path(os.environ['SWB_DATA_ROOT'])/row.storage_key,destination)
                    verify_snapshot(destination)
                    office_documents.append({'directory':str(destination)})
                    return row

                answer_snapshot = create_export("parent_answers", "合成家长答案导出")
                assert answer_snapshot.provenance["answers"][0]["body"] == teacher_answer
                independent_snapshot = create_export("independent_practice", "合成独立练习导出")
                assert independent_snapshot.provenance["answers"] == []
                content = context.request.get(origin + f"/prints/snapshots/{independent_snapshot.pk}/content.json/")
                assert content.status == 200 and teacher_answer.encode() not in content.body()
                parsed=content.json()
                blocks=[block for p in parsed['pages'] for block in p]
                assert sum(b['kind']=='math' for b in blocks)==3
                assert sum(b['kind']=='formula_image' for b in blocks)==1
                assert any('<b>合成公式题</b>'==b.get('content') for b in blocks)
                docx=context.request.get(origin+f"/prints/snapshots/{independent_snapshot.pk}/document.docx/")
                assert docx.status==200
                import zipfile
                with zipfile.ZipFile(BytesIO(docx.body())) as archive:
                    xml=archive.read('word/document.xml').decode()
                assert 'm:f' in xml and 'm:sSup' in xml and 'w:b' in xml
                summary=create_export('knowledge_summary','合成知识重点导出')
                summary_content=context.request.get(origin+f"/prints/snapshots/{summary.pk}/content.json/").json()
                assert any('backcolor' in str(b['content']) for p in summary_content['pages'] for b in p)
                checks.append('manual-formula-emphasis-native-docx-and-source-image-print')
                checks.append("teacher-answer-export-and-independent-practice-exclusion")

                goto(f"/prints/answers/{question_two['revision_id']}/", "teacher-answer-confirm")
                page.locator('#id_body').fill('1/2')
                page.locator('#id_formulas').fill('2/5 + 1/10')
                page.locator('#id_basis').fill('按公分母 10 复算')
                page.get_by_role('button',name='保存并确认答案',exact=True).click()
                second_answer=db(lambda:TeacherAnswerRevision.objects.get(question_revision_id=question_two['revision_id']))
                assert db(lambda:second_answer.decisions.filter(action='accepted').count())==1
                diagram_source = db(lambda: RevisionRecord.objects.get(pk=question_two['revision_id']).payload['evidence_refs'][0]['region_revision_id'])
                diagram_url = f"/prints/diagrams/{question_two['revision_id']}/"
                for placement, alt in [('question','合成无提示图'),('question','合成无提示图第二版'),('answer','合成解析图含答案')]:
                    goto(diagram_url, 'teaching-diagram-upload')
                    page.locator('#id_placement').select_option(placement)
                    page.locator('#id_source_region_id').select_option(diagram_source)
                    figure = Image.new('RGB',(300,200),'white')
                    ImageDraw.Draw(figure).polygon([(40,160),(240,160),(240,30)],outline='black',width=3)
                    if placement == 'answer':
                        ImageDraw.Draw(figure).text((50,30),'SYNTHETIC ANSWER',fill='black')
                    drawing = BytesIO(); figure.save(drawing,format='PNG')
                    page.locator('#id_png_upload').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':drawing.getvalue()})
                    page.locator('#id_vector_upload').set_input_files({'name':'synthetic.svg','mimeType':'image/svg+xml',
                        'buffer':b'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><path d="M40 160 L240 160 L240 30 Z" fill="none" stroke="black"/></svg>'})
                    page.locator('#id_alt').fill(alt)
                    page.locator('#id_conditions').fill('合成直角三角形\n无真实题干或孩子信息')
                    page.locator('#id_width_points').fill('250')
                    page.locator('#id_min_label_points').fill('12')
                    if placement == 'question': page.locator('#id_independent_safe').check()
                    page.locator('#id_content_checked').check()
                    page.locator('#id_basis').fill('合成图核对；不证明真实几何内容')
                    page.get_by_role('button',name='保存并确认图示',exact=True).click()
                    expect(page.locator('main .notice').filter(has_text='教学图已保存并确认')).to_have_count(1)
                expect(page.locator('article')).to_have_count(3)
                assert db(lambda: TeachingDiagramRevision.objects.filter(question_revision_id=question_two['revision_id']).count()) == 3
                vector_url=page.get_by_role('link',name='下载配套矢量来源').first.get_attribute('href')
                vector_response=context.request.get(origin+vector_url)
                assert vector_response.status==200 and 'attachment' in vector_response.headers['content-disposition']
                assert vector_response.headers['content-type']=='application/octet-stream'
                checks.append('diagrams:private-upload-confirm-append-history-vector-attachment')
                screenshot('phone-diagrams.png')
                goto(f'/prints/materials/{material.pk}/five-books/', 'five-books-readiness')
                page.get_by_role('button',name='生成五册 PDF 与 Word',exact=True).click()
                page.wait_for_url('**/five-books/*/')
                packet_id=page.url.rstrip('/').split('/')[-1]
                zip_response=context.request.get(origin+f'/prints/materials/{material.pk}/five-books/{packet_id}/download/')
                assert zip_response.status==200
                with zipfile.ZipFile(BytesIO(zip_response.body())) as archive:
                    assert len(archive.namelist())==21
                    manifest=json.loads(archive.read('manifest.json'))
                    assert manifest['question_revisions']==[question_one['revision_id'],question_two['revision_id']]
                    assert manifest['evidence_scope']=='not_recorded'
                    assert len(manifest['books'])==5
                    assert len(manifest['diagram_revisions'])==2
                    practice_book=next(b for b in manifest['books'] if b['purpose']=='independent_practice')
                    practice_content=json.loads(archive.read(practice_book['label']+'/content.json'))
                    practice_diagrams=[b for p in practice_content['pages'] for b in p if b['kind']=='diagram']
                    assert len(practice_diagrams)==1 and practice_diagrams[0]['role']=='question'
                    assert '合成解析图含答案' not in json.dumps(practice_content,ensure_ascii=False)
                checks.append('five-books:single-batch-pdf-word-zip-fixed-revisions-unknown-learning')
                checks.append('diagrams:five-books-current-revisions-practice-no-answer-diagram')
                screenshot('phone-five-books.png')

                # Split preserves its source; merge starts from two selected exact current versions.
                original_question = db(lambda: EntityRecord.objects.get(pk=question_one["pk"]))
                original_revision = original_question.head_revision_id
                goto(f"/catalogue/question/{question_one['pk']}/split/", "catalogue-split")
                page.locator("#id_child_1_number").fill("合成题 A-1")
                page.locator("#id_child_1_text").fill("合成子题一：1/3 + 1/6 = ?")
                page.locator("#id_child_2_number").fill("合成题 A-2")
                page.locator("#id_child_2_text").fill("合成子题二：2/3 - 1/6 = ?")
                page.locator("#id_reason").fill("拆分为两个独立练习问题")
                page.get_by_role("button", name="建立待审核子题", exact=True).click()
                split_card = page.locator("article.revision-card").filter(has_text="拆题")
                expect(split_card).to_contain_text("拆题")
                assert db(lambda: EntityRecord.objects.get(pk=question_one["pk"]).head_revision_id) == original_revision
                split_lineage = db(lambda: QuestionLineage.objects.filter(household_id=household_id, action="split").latest("pk"))
                assert len(split_lineage.source_revision_ids) == 1 and len(split_lineage.target_revision_ids) == 2
                assert [str(value) for value in split_lineage.source_revision_ids] == [str(original_revision)]
                split_source_pks = db(lambda: list(RevisionRecord.objects.filter(
                    pk__in=split_lineage.source_revision_ids).values_list("entity_id", flat=True)))
                split_target_pks = db(lambda: list(RevisionRecord.objects.filter(
                    pk__in=split_lineage.target_revision_ids).values_list("entity_id", flat=True)))
                split_hrefs = split_card.locator("a[href^='/catalogue/question/']").evaluate_all(
                    "links => links.map(link => link.getAttribute('href'))")
                assert f"/catalogue/question/{question_one['pk']}/" in split_hrefs
                assert split_source_pks == [question_one["pk"]] and len(split_target_pks) == 2
                assert all(f"/catalogue/question/{pk}/" in split_hrefs for pk in split_target_pks)
                checks.append("catalogue-split-lineage-source-preserved")

                goto(f"/catalogue/merge/?household_id={household_id}", "catalogue-merge-select")
                question_two_revision = db(lambda: EntityRecord.objects.get(pk=question_two["pk"]).head_revision_id)
                for revision_id in (original_revision, question_two_revision):
                    page.locator(f"input[name='source_revision_ids'][value='{revision_id}']").check()
                page.get_by_role("button", name="继续填写合并内容", exact=True).click()
                page.locator("#id_original_number").fill("合成题 AB")
                page.locator("#id_printed_text").fill("合并后的合成题：1/3 + 1/6 + 2/5 + 1/10 = ?")
                page.locator("#id_reason").fill("合并两道相关分数练习")
                page.get_by_role("button", name="建立合并题草稿", exact=True).click()
                merge_card = page.locator("article.revision-card").filter(has_text="合题")
                expect(merge_card).to_contain_text("合题")
                merge_lineage = db(lambda: QuestionLineage.objects.filter(household_id=household_id, action="merge").latest("pk"))
                assert len(merge_lineage.source_revision_ids) == 2 and len(merge_lineage.target_revision_ids) == 1
                assert {str(value) for value in merge_lineage.source_revision_ids} == {
                    str(original_revision), str(question_two_revision)}
                merge_source_pks = db(lambda: list(RevisionRecord.objects.filter(
                    pk__in=merge_lineage.source_revision_ids).values_list("entity_id", flat=True)))
                merge_target_pks = db(lambda: list(RevisionRecord.objects.filter(
                    pk__in=merge_lineage.target_revision_ids).values_list("entity_id", flat=True)))
                merge_hrefs = merge_card.locator("a[href^='/catalogue/question/']").evaluate_all(
                    "links => links.map(link => link.getAttribute('href'))")
                assert {question_one["pk"], question_two["pk"]}.issubset(set(merge_source_pks))
                assert all(f"/catalogue/question/{pk}/" in merge_hrefs for pk in (*merge_source_pks, *merge_target_pks))
                checks.append("catalogue-merge-lineage-exact-versions")

                # Plans append a reschedule event, and the evidence report uses all real attempt/review history.
                goto(f"/study/?household={household_id}", "study-home")
                page.locator("a[href*='/schedule/new/']").first.click()
                page.locator("#id_question_revision_id").select_option(str(question_one["revision_id"]))
                first_due = (date.today() + timedelta(days=2)).isoformat()
                second_due = (date.today() + timedelta(days=5)).isoformat()
                page.locator("#id_due_date").fill(first_due)
                page.locator("#id_goal").fill("独立完成合成分数题")
                page.locator("#id_prompt_plan").fill("先不看提示")
                page.locator("#id_reason").fill("家长制定合成练习计划")
                page.get_by_role("button", name="保存计划", exact=True).click()
                schedule_pk = int(page.url.rstrip("/").split("/")[-1])
                page.locator("#id_action").select_option("rescheduled")
                page.locator("#id_due_date").fill(second_due)
                page.locator("#id_goal").fill("复测后总结通分步骤")
                page.locator("#id_reason").fill("调整合成练习日期")
                page.get_by_role("button", name="追加计划事件", exact=True).click()
                events = db(lambda: list(ScheduleRevision.objects.filter(schedule_id=schedule_pk).order_by("revision_no")))
                assert [item.action for item in events] == ["planned", "rescheduled"]
                assert [item.due_date.isoformat() for item in events] == [first_due, second_due]
                expect(page.locator(".study-events").first).to_contain_text(
                    date_format(date.fromisoformat(first_due)))
                expect(page.locator(".study-events").first).to_contain_text(
                    date_format(date.fromisoformat(second_due)))
                screenshot("phone-study-plan.png")
                report_url = origin + f"/study/learner/{db(lambda: EntityRecord.objects.get(kind='learner', stable_id=learner_id).pk)}/report/"
                goto(report_url.replace(origin, ""), "study-evidence-report")
                for value in ("来源未知", "课堂笔记", "提示后作答", "独立作答"):
                    expect(page.locator(".report-attempts")).to_contain_text(value)
                expect(page.locator(".report-assessments")).to_contain_text("已接受")
                expect(page.locator(".report-assessments")).to_contain_text("答案")
                screenshot("phone-study-report.png")
                checks.append("study-reschedule-history-and-evidence-report")

                goto("/operations/", "operations-home")
                policy_path = f"/operations/household/{household_id}/retention/"
                timing_path = f"/operations/household/{household_id}/timing/new/"
                expect(page.locator(f"a[href='{policy_path}']")).to_be_visible()
                goto(policy_path, "retention-policy")
                page.locator("#id_reason").fill("合成验收默认长期保留")
                page.get_by_role("button", name="追加策略", exact=True).click()
                expect(page.locator("main")).to_contain_text("策略版本")
                policy = db(lambda: RetentionPolicyRevision.objects.get(household_id=household_id))
                assert policy.archive_after_days is None and policy.delete_after_days is None
                checks.append("retention-default-append-without-deleting-assets")
                goto(timing_path, "manual-work-timing")
                page.locator("#id_question_revision_id").select_option(question_one["revision_id"])
                page.locator("#id_attempt_revision_id").select_option(independent_attempt_revision)
                page.locator("#id_seconds").fill("90")
                page.locator("#id_reason").fill("合成案例人工估计，不是精确测量")
                page.get_by_role("button", name="追加估计记录", exact=True).click()
                expect(page.locator("main")).to_contain_text("估计 90 秒")
                timing = db(lambda: WorkTiming.objects.get(household_id=household_id))
                assert timing.question_revision_id == question_one["revision_id"]
                assert timing.attempt_revision_id == independent_attempt_revision
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                screenshot("phone-operations.png")
                checks.append("manual-work-timing-exact-question-and-attempt")

                from verify_ai_continuity import exercise
                exercise(page=page, db=db, goto=goto, screenshot=screenshot, checks=checks,
                    actor=user, household_id=household_id, source_page=pages[0])

                goto(profile_path, "logout-private-page")
                page.locator("form[action='/accounts/logout/'] button").click()
                page.goto(profile_url)
                expect(page).to_have_url(re.compile(re.escape(origin) + r"/accounts/login/\?next="))
                assert not errors, errors
                assert {"question", "knowledge", "learning"}.issubset(region_control_surfaces), region_control_surfaces
                checks.append("shared-image-tools:question-knowledge-learning")
                assert not blocked_requests, blocked_requests
                checks.append("logout-revokes-authenticated-page")
                browser.close()

        report = {"synthetic_only": True, "viewport": [390, 844], "checks": checks,
            "screenshots": ["phone-question.png", "phone-knowledge.png", "phone-attempt.png",
                "phone-learning-history.png", "phone-study-plan.png", "phone-study-report.png",
                "phone-ai-home.png", "phone-operations.png", "phone-five-books.png", "phone-diagrams.png",
                "phone-page-reading.png", "phone-ai-confirmation.png",
                "desktop-page-reading.png", "desktop-ai-confirmation.png"],
            "additional_viewports": [[1280, 900]],
            "synthetic_ai_responses": 2, "real_model_calls": 0, "page_reading_versions": 2,
            "source_questions_uploaded": 2, "attempt_count": 4, "assessment_revisions": 2,
            "unknown_observation": True, "teacher_answer_separate": True,
            "catalogue_lineage": ["split", "merge"], "study_schedule_revisions": 2,
            "javascript_errors": errors, "blocked_external_requests": blocked_requests,
            "browser": "Playwright Chromium", "deployment": False}
        report_path = output / "verification.local.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        report_path.chmod(0o600)
        office_report=output/'office-sources.local.json'
        office_report.write_text(json.dumps({'documents':office_documents},ensure_ascii=False,indent=2))
        office_report.chmod(0o600)
        print(f"Business browser acceptance passed: {len(checks)} checks; report={report_path}", flush=True)
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
