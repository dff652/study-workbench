#!/usr/bin/env python3
"""Exercise the built UI with owned synthetic data, never a running family service."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_business import require_owned_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    require_owned_database(args.owner)
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise RuntimeError("Build the actual frontend first")
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db import connections
    from app.persistence import services as core
    from app.persistence.models import EntityRecord
    from app.web import learning_services as learning, services as materials
    from app.workflows import services as workflows
    from app.workflows.models import WorkflowJob
    from app.printing import packets, services as printing
    from app.exports.snapshots import verify_snapshot
    from PIL import Image
    from playwright.sync_api import sync_playwright, expect
    from verify_exports import pdf_checks, run as pdf_run

    token = uuid4().hex
    output = ROOT / "artifacts/fusion-verification" / token
    output.mkdir(parents=True, mode=0o700)
    for parent in (output, output.parent, output.parent.parent): parent.chmod(0o700)
    password = secrets.token_urlsafe(24)
    user = get_user_model().objects.create_user(username="fusion-" + token[:8], password=password)
    house = core.create_household(user, "synthetic-fusion-" + token)
    profile = learning.create_profile(user, house.pk, display_name="小禾", grade="三年级", request_key=uuid4().hex)
    learning.create_profile(user, house.pk, display_name="小明", grade="四年级", request_key=uuid4().hex)
    pool = ThreadPoolExecutor(max_workers=1)
    def db(call):
        def run():
            try: return call()
            finally: connections.close_all()
        return pool.submit(run).result(timeout=150)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    checks, errors, external = [], [], []
    stream = BytesIO()
    Image.new("RGB", (160, 120), "white").save(stream, format="PNG")
    image_path = output / "synthetic.png"; image_path.write_bytes(stream.getvalue())
    server = None
    try:
        with (output / "server.log").open("w") as log:
            server = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"], cwd=ROOT, stdout=log, stderr=log)
            deadline = time.monotonic() + 20
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.3): break
                except OSError:
                    if time.monotonic() > deadline or server.poll() is not None: raise RuntimeError("Owned browser server failed")
                    time.sleep(0.1)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                def route(request_route):
                    if request_route.request.url.startswith(origin + "/"):
                        request_route.continue_()
                    else:
                        external.append(request_route.request.url); request_route.abort()
                context.route("**/*", route)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(origin + "/app/")
                expect(page.get_by_role("link", name="前往登录", exact=True)).to_be_visible()
                page.get_by_role("link", name="前往登录", exact=True).click()
                page.locator("#id_username").fill(user.username)
                page.locator("#id_password").fill(password)
                page.get_by_role("button", name="登录", exact=True).click()
                page.goto(origin + "/app/")
                expect(page.get_by_role("heading", name="资料整理", exact=True)).to_be_visible()
                expect(page.get_by_text("我的家庭", exact=True).first).to_be_visible()
                expect(page.get_by_text("当前版本 v0.2.0-dev", exact=True).first).to_be_visible()
                updates = page.get_by_text("查看更新记录", exact=True).first
                updates.click()
                expect(page.get_by_text("v0.2.0-dev · 2026-10-04", exact=True).first).to_be_visible()
                expect(page.get_by_text("源码版本：未记录提交身份", exact=False).first).to_be_visible()
                expect(page.get_by_text("新增同源工作台、学习证据总览及历次作答记录。", exact=True).first).to_be_visible()
                page.screenshot(path=str(output / "version-and-changelog.png"), full_page=True)
                updates.click()
                checks.append("development-version-changelog")
                page.get_by_role("button", name="新建资料", exact=True).click()
                page.get_by_label("资料名称", exact=True).fill("合成融合验收资料")
                page.get_by_role("button", name="创建资料", exact=True).click()
                page.get_by_label("选择原图", exact=True).set_input_files(str(image_path))
                page.get_by_role("button", name="上传原图", exact=True).click()
                expect(page.get_by_text("资料页 1", exact=True)).to_be_visible()
                data = page.request.get(origin + "/api/v1/materials/?household=" + house.pk).json()
                material_id = data["items"][0]["id"]
                detail = page.request.get(origin + f"/api/v1/materials/{material_id}/").json()
                source = detail["pages"][0]
                assert source["sha256"] == hashlib.sha256(image_path.read_bytes()).hexdigest()
                refs = [{"source_id": "photo", "bbox": [2, 2, 155, 115]}]
                proposal = {"schema_version": "swb.skill-import.v1",
                    "sources": [{"id": "photo", "page_id": source["id"], "sha256": source["sha256"]}],
                    "records": [
                        {"id": "q", "kind": "question", "data": {"printed_text": "4 × 2 = ?", "original_number": "S1", "sources": refs}},
                        {"id": "k", "kind": "knowledge", "data": {"definition": "乘法表示相同加数的和。", "sources": refs}},
                        {"id": "a", "kind": "answer", "data": {"question": "q", "body": "8", "basis": "4 + 4 = 8，复算"}},
                        {"id": "l", "kind": "link", "data": {"question": "q", "node": "k", "role": "applies"}},
                    ]}
                proposal_path = output / "proposal.local.json"
                from tests.workflows.test_assets import with_diagram
                proposal = with_diagram(proposal)
                proposal["records"][-1]["data"]["source"] = refs[0]
                proposal_path.write_text(json.dumps(proposal, ensure_ascii=False))
                page.get_by_label("选择结构化交换 JSON", exact=True).set_input_files(str(proposal_path))
                expect(page.get_by_text("无提示题面图 · 题目 S1", exact=True).first).to_be_visible()
                page.get_by_role("button", name="新建整理任务", exact=True).click()
                page.get_by_role("combobox", name="学习者（可选）", exact=True).select_option("")
                with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(f"/api/v1/materials/{material_id}/workflows/")) as created:
                    page.get_by_role("button", name="创建并查看任务", exact=True).click()
                assert created.value.status == 200
                created_job = created.value.json()["job"]
                expect(page.get_by_text("4 × 2 = ?", exact=True)).to_be_visible()
                expect(page.get_by_text("教学图示", exact=True).first).to_be_visible()
                job_id = db(lambda: WorkflowJob.objects.get(material_id=material_id).pk)
                assert str(job_id) == created_job["id"]
                page.get_by_role("button", name="合成融合验收资料 当前资料 1 张原图页", exact=True).click()
                expect(page.get_by_role("button", name="确认整包内容", exact=True)).to_be_visible()
                page.get_by_label("我已查看并核对上方列出的全部记录类型。", exact=True).check()
                page.get_by_label("确认原因", exact=True).fill("逐项对照合成原图确认题干、知识、答案与关联")
                with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(f"/api/v1/workflows/{job_id}/actions/") and response.request.post_data_json.get("action") == "confirm") as confirmed:
                    page.get_by_role("button", name="确认整包内容", exact=True).click()
                assert confirmed.value.status == 200 and confirmed.value.json()["job"]["state"] == "ready"
                readiness = page.get_by_text("五册生成前检查", exact=True).locator("xpath=ancestor::*[@data-slot='card']")
                expect(readiness.get_by_text("题面已确认", exact=True)).to_be_visible()
                expect(readiness.get_by_text("答案已准备", exact=True)).to_be_visible()
                expect(page.get_by_text("尚未为此资料创建任务。", exact=True)).to_have_count(0)
                with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(f"/api/v1/workflows/{job_id}/actions/") and response.request.post_data_json.get("action") == "queue") as queued:
                    page.get_by_role("button", name="加入处理队列", exact=True).click()
                assert queued.value.status == 200 and queued.value.json()["job"]["state"] == "queued", (queued.value.status, queued.value.json(), queued.value.request.post_data_json)
                assert db(lambda: workflows.detail(user, job_id).state) == "queued"
                assert db(lambda: workflows.execute_next().state) == "output_check"
                page.get_by_role("button", name="刷新任务", exact=True).click()
                expect(page.get_by_role("link", name="打开五册检查版", exact=True)).to_be_visible()
                job = db(lambda: workflows.detail(user, job_id))
                _, manifest = db(lambda: packets.read(user, material_id, job.result["packet_id"]))
                assert len(manifest["diagram_revisions"]) == 1
                office = []
                for book in manifest["books"]:
                    directory = db(lambda: printing.snapshot_file(user, book["snapshot_id"], "snapshot.json").parent)
                    snapshot = verify_snapshot(directory)
                    copy = ROOT / "exports/fusion-verification" / token / book["purpose"]
                    copy.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    shutil.copytree(directory, copy)
                    pdf_checks(copy / "document.pdf", len(snapshot["inputs"]["document"]["pages"]))
                    text = pdf_run("pdftotext", directory / "document.pdf", "-")
                    if book["purpose"] == "independent_practice": assert "乘法表示" not in text and "复算" not in text
                    if book["purpose"] == "evidence_report": assert "未知" in text
                    office.append({"directory": str(copy), "purpose": book["purpose"]})
                page.evaluate("scrollTo(0, 0)")
                page.screenshot(path=str(output / "pc-output-check.png"), full_page=True)
                for label in ("PDF 可以阅读", "Word 文档可以阅读", "五册用途均正确"):
                    page.get_by_label(label, exact=True).check()
                page.get_by_label("输出检查原因", exact=True).fill("匿名 PDF、Word 结构与五册用途逐项核对")
                page.get_by_role("button", name="确认输出检查", exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role("link", name="下载完整五册 ZIP", exact=True).first.click()
                archive_path = output / "five-books.zip"; download.value.save_as(str(archive_path))
                assert len(zipfile.ZipFile(archive_path).namelist()) == 21
                checks += ["session-login", "one-household-friendly-name", "original-upload-sha", "all-records-one-confirm", "worker-explicit-queue", "five-purpose-pdf-docx-snapshots", "unknown-learning-report", "checked-zip-21-members"]
                def seed_attempts():
                    current = workflows.detail(user, job_id)
                    qid = current.result["mapping"]["q"]["question_id"]
                    preview = materials.preview_file(user, source["id"], 0)
                    ref = {"page_id": source["id"], "rotation": 0, "preview_sha256": preview.sha256, "display_bbox": [2, 2, 155, 115]}
                    observation = learning.save_observation(user, house.pk, legibility="readable", author_state="confirmed",
                        author_learner_id=profile["learner_id"], confirmation_basis="匿名当面确认", actual_date_state="known", actual_date=date(2026, 10, 1),
                        notes="合成观察", sources=[ref], reason="合成观察", request_key=uuid4().hex)
                    for source_kind, independence, prompt in (("classroom_note", "not_independent", "unknown"), ("assisted_answer", "not_independent", "given"), ("independent_answer", "confirmed_independent", "none_confirmed")):
                        choices = learning.learner_create_choices(user, profile["learner_id"])
                        selected = next(value for value, _ in choices["observation_choices"] if value.startswith(observation["observation_id"] + "|"))
                        attempt = learning.create_attempt(user, profile["learner_id"], question_id=qid, attempt_kind="first", source_kind=source_kind,
                            independence=independence, prompt_status=prompt, prompts=("匿名提示",) if prompt == "given" else (), actual_date_state="known",
                            actual_date=date(2026, 10, 1), legibility="readable", answer_text="8", authorship_basis="当面确认", observation_values=[selected],
                            previous_attempt_id=None, context=choices["context"], request_key=uuid4().hex)
                    context_data = learning.assessment_context(user, attempt["attempt_id"])
                    evidence = context_data["evidence_choices"][0][0][0]
                    values = {"context_errata": []}
                    for name in ("answer", "method", "process", "calculation", "notation"):
                        known = name in ("answer", "process")
                        values[name] = {"judgment": "correct" if known else "unknown", "basis": "observed" if known else "undetermined",
                            "evidence": [evidence] if known else [], "rationale": "按合成原图核对" if known else "", "unknown_reason": "" if known else "未测试"}
                    assessment = learning.save_assessment(user, attempt["attempt_id"], values=values, context=context_data["context"], request_key=uuid4().hex, reason="合成评价")
                    review = learning.review_form_context(user, assessment["assessment_id"])
                    learning.review_assessment(user, assessment["assessment_id"], assessment["revision_id"], action="accept", reason="合成来源核对", context=review["review_context"], request_key=uuid4().hex)
                db(seed_attempts)
                page.get_by_role("button", name="学习总览", exact=True).click()
                page.get_by_role("combobox", name="学习者", exact=True).select_option(profile["learner_id"])
                expect(page.get_by_text("独立成功证据", exact=True)).to_be_visible()
                response = page.request.get(origin + f"/api/v1/learners/{profile['learner_id']}/overview/?household={house.pk}").json()
                assert response["metrics"]["attempt_count"] == 3 and response["metrics"]["independent_success_count"] == 1
                assert response["metrics"]["source_counts"]["classroom_note"] == 1 and response["metrics"]["source_counts"]["assisted_answer"] == 1
                assert response["metrics"]["independent_success_rate"] is None
                page.screenshot(path=str(output / "pc-overview.png"), full_page=True)
                page.get_by_role("button", name="作答记录", exact=True).click()
                expect(page.get_by_text("4 × 2 = ?", exact=True).first).to_be_visible()
                for label in ("课堂笔记", "提示后作答", "独立作答"):
                    expect(page.get_by_role("table").get_by_text(label, exact=True)).to_be_visible()
                for width, height in ((1440, 1000), (390, 844)):
                    page.set_viewport_size({"width": width, "height": height})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    page.screenshot(path=str(output / f"attempts-{width}.png"), full_page=True)
                checks += ["three-source-types-separate", "same-question-three-events", "no-invented-mastery-rate", "pc-and-phone-no-overflow"]
                from verify_fusion_completion import exercise
                try:
                    checks += exercise(page, origin, db, user, house, profile, material_id, source, output)
                except Exception:
                    page.screenshot(path=str(output / "completion-failure.png"), full_page=True)
                    raise
                from verify_fusion_completion import exercise_preparation
                try:
                    preparation_checks, preparation_office = exercise_preparation(page, origin, db, user, house, output)
                    checks += preparation_checks
                    office += preparation_office
                except Exception:
                    page.screenshot(path=str(output / "preparation-failure.png"), full_page=True)
                    raise
                page.get_by_role("button", name="退出", exact=True).click()
                assert page.request.get(origin + "/api/v1/session/").status == 401
                page.goto(origin + "/app/")
                expect(page.get_by_role("link", name="前往登录", exact=True)).to_be_visible()
                checks.append("csrf-post-logout-private-api-rejected")
                assert not external and not errors, {"external": external, "page_errors": errors}
                browser.close()
                (output / "office-sources.local.json").write_text(json.dumps({"documents": office}))
        (output / "verification.local.json").write_text(json.dumps({"synthetic_only": True, "checks": checks, "external_requests": external, "page_errors": errors}, ensure_ascii=False, indent=2))
        print(f"Fusion browser acceptance passed: {len(checks)} checks; report={output / 'verification.local.json'}")
    finally:
        if server:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait()
        pool.shutdown(wait=True)
        for path in output.rglob("*"):
            if path.is_file(): path.chmod(0o600)


if __name__ == "__main__":
    main()
