"""Additional real-UI acceptance; called only by the owned fusion fixture."""
from datetime import date, timedelta
import hashlib
import json
import re


def exercise(page, origin, db, actor, household, learner, material_id, source, output):
    from playwright.sync_api import expect
    checks = []
    api = origin + "/api/v1/"
    def submit(button, suffix):
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(suffix)) as response:
            button.click()
        assert response.value.status == 200, response.value.text()
        return response.value.json()
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="进度与复测", exact=True).click()
    page.get_by_role("combobox", name="学习者", exact=True).select_option(learner["learner_id"])
    expect(page.get_by_role("button", name="新增复测计划", exact=True)).to_be_visible()
    groups = page.request.get(api + f"learners/{learner['learner_id']}/progress/?household={household.pk}").json()["groups"]
    assert any(row["attempt_count"] == 3 and row["independent_success_count"] == 1 for row in groups)
    page.get_by_role("button", name="新增复测计划", exact=True).click()
    question = page.get_by_label("题目", exact=True)
    question.select_option(index=1)
    page.get_by_label("复测日期", exact=False).fill((date.today() + timedelta(days=1)).isoformat())
    page.get_by_label("复测目标", exact=False).fill("匿名独立复测")
    page.get_by_label("创建原因", exact=False).fill("合成记录计划")
    # Empty prompt plan is intentional: an independent attempt needs no hints.
    page.get_by_role("button", name="创建复测计划", exact=True).click()
    expect(page.get_by_role("button", name="改期", exact=True)).to_be_visible()
    page.get_by_role("button", name="改期", exact=True).click()
    page.get_by_label("新的复测日期", exact=False).fill((date.today() + timedelta(days=2)).isoformat())
    page.get_by_label("本次操作原因", exact=False).fill("保留改期历史")
    page.get_by_role("button", name="保存改期", exact=True).click()
    page.get_by_role("button", name="记录复测完成", exact=True).click()
    attempt = page.get_by_label("选择这次复测对应的真实作答", exact=True)
    choice = attempt.locator("option").filter(has_text="独立作答").last.get_attribute("value")
    attempt.select_option(choice)
    page.get_by_label("本次操作原因", exact=False).fill("绑定真实合成独立作答")
    submit(page.get_by_role("button", name="确认关联作答并完成", exact=True), "/actions/")
    schedule = page.request.get(api + f"learners/{learner['learner_id']}/schedules/?household={household.pk}").json()["items"][0]
    assert schedule["state"] == "completed" and len(schedule["history"]) == 3
    assert schedule["history"][-1]["actual_date"] == "2026-10-01"
    assert schedule["history"][-1]["attempt_revision_id"] == choice
    expect(page.get_by_text("绑定真实合成独立作答", exact=False)).to_be_visible()
    page.evaluate("scrollTo(0, 0)")
    page.screenshot(path=str(output / "completion-progress.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    page.screenshot(path=str(output / "completion-progress-phone.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    checks += ["node-progress-exact-revision-real-sources", "review-plan-empty-hints-real-attempt-three-events", "progress-phone-no-overflow"]

    page.get_by_role("button", name="资料整理", exact=True).click()
    page.get_by_role("button", name="合成融合验收资料 当前资料 1 张原图页", exact=True).click()
    page.get_by_role("button", name="打开内容核对", exact=True).click()
    expect(page.get_by_label("正在核对的题目", exact=False)).to_be_visible()
    editor = page.locator("form").filter(has=page.get_by_label("图中印刷题面转写", exact=False))

    def draw(scope, *, x1=10, y1=10, x2=110, y2=80):
        svg = scope.get_by_role("img", name="资料页 1 区域选框", exact=True)
        expect(svg).to_be_visible()
        svg.scroll_into_view_if_needed()
        svg.evaluate("node => window.scrollBy(0, node.getBoundingClientRect().top - 96)")
        box = svg.bounding_box()
        assert box and abs(box["width"] / box["height"] - 160 / 120) < .02
        start = [box["x"] + box["width"] * x1 / 160, box["y"] + box["height"] * y1 / 120]
        assert page.evaluate("([x, y]) => document.elementFromPoint(x, y)?.closest('svg')?.getAttribute('aria-label')", start) == "资料页 1 区域选框"
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * x2 / 160, box["y"] + box["height"] * y2 / 120, steps=5)
        page.mouse.up()

    draw(editor)
    editor.get_by_role("button", name="确认添加这个题目来源", exact=True).click()
    editor.get_by_label("题号（可留空）", exact=True).fill("C2")
    editor.get_by_label("图中印刷题面转写", exact=False).fill("3 × 3 = ?")
    editor.get_by_label("可选家长答案", exact=False).check()
    editor.get_by_label("家长核对的答案或解答", exact=False).fill("9")
    editor.get_by_label("答案依据", exact=False).fill("3 + 3 + 3")
    editor.locator("summary").filter(has_text="知识").click()
    editor.get_by_label(re.compile(r"^(知识)?定义$")).fill("三个相同加数的和")
    editor.get_by_label("我已对照原图核对题面", exact=False).check()
    editor.get_by_label("本次核对原因", exact=False).fill("合成图像逐项核对")
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(f"materials/{material_id}/content/")) as saved:
        editor.get_by_role("button", name="确认并保存题目", exact=True).click()
    assert saved.value.status == 200, saved.value.text()
    qid = saved.value.json()["question_id"]
    content_url = api + f"materials/{material_id}/content/"
    row = next(row for row in page.request.get(content_url).json()["questions"] if row["id"] == qid)
    assert row["confirmed"] and row["answer"]["confirmed"] and row["sources"]
    assert all(abs(a-b) <= 1 for a,b in zip(row["sources"][0]["bbox"], [10, 10, 110, 80]))
    page.screenshot(path=str(output / "completion-content.png"), full_page=True)
    checks += ["original-pixel-box-manual-question-answer-node-one-confirm"]

    page.get_by_label("正在核对的题目", exact=False).select_option("")
    draw(editor, x1=115, y1=85, x2=155, y2=115)
    editor.get_by_role("button", name="确认添加这个题目来源", exact=True).click()
    editor.get_by_label("本次核对原因", exact=False).fill("空白看不清，保留未知")
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("content/draft/")) as draft:
        editor.get_by_role("button", name="保存待补草稿", exact=True).click()
    assert draft.value.status == 200, draft.value.text()
    unknown = next(row for row in page.request.get(content_url).json()["questions"] if row["id"] == draft.value.json()["question_id"])
    assert not unknown["confirmed"] and not unknown["printed_text"]
    checks.append("blank-unconfirmed-draft-keeps-unknown")

    page.get_by_label("正在核对的题目", exact=False).select_option(qid)
    page.get_by_role("button", name="记录讲义勘误", exact=True).click()
    page.get_by_label("订正后的讲义题干", exact=False).fill("3 × 4 = ?")
    page.get_by_label("订正依据", exact=False).fill("合成印刷错误核对")
    page.get_by_label("勘误原因", exact=False).fill("讲义错误，非孩子错误")
    page.get_by_label("我已核对", exact=False).last.check()
    submit(page.get_by_role("button", name="确认并应用勘误", exact=True), "/erratum/")
    expect(page.get_by_text("3 × 4 = ?", exact=True).first).to_be_visible()
    row = next(row for row in page.request.get(content_url).json()["questions"] if row["id"] == qid)
    assert row["printed_text"] == "3 × 3 = ?" and row["working_text"] == "3 × 4 = ?"
    checks.append("printed-erratum-preserves-original-separate-from-learner-errors")

    reading = page.locator("form").filter(has=page.get_by_label("阅读状态", exact=False))
    reading.get_by_label("新分区类型", exact=False).select_option("unknown")
    draw(reading)
    reading.get_by_role("button", name="确认添加未知区域分区", exact=True).click()
    reading.get_by_label("待补事项（每行一项）", exact=False).fill("原图下半区待核对")
    reading.get_by_label("阅读依据（必填）", exact=False).fill("只阅读已知区，保留未知")
    submit(reading.get_by_role("button", name="保存本页阅读记录", exact=True), "/reading/")
    reading.get_by_label("阅读状态", exact=False).select_option("read")
    reading.get_by_label("阅读覆盖", exact=False).select_option("complete")
    expect(reading.get_by_role("button", name="保存本页阅读记录", exact=True)).to_be_disabled()
    reading.get_by_label("阅读覆盖", exact=False).select_option("partial")
    reading.get_by_label("阅读依据（必填）", exact=False).fill("已读但未知区待补")
    submit(reading.get_by_role("button", name="保存本页阅读记录", exact=True), "/reading/")
    history = page.request.get(api + f"pages/{source['id']}/reading/").json()["history"]
    assert len(history) == 2 and all(row["coverage"] == "partial" for row in history)
    checks.append("reading-unknown-blocks-complete-and-preserves-history")
    reading.get_by_role("button", name="移除分区", exact=True).click()
    reading.get_by_label("待补事项（每行一项）", exact=False).fill("")
    reading.get_by_label("阅读覆盖", exact=False).select_option("complete")
    expect(reading.get_by_role("button", name="保存本页阅读记录", exact=True)).to_be_disabled()
    expect(reading.get_by_role("alert")).to_contain_text("尚未标记分区")
    reading.get_by_label("新分区类型", exact=False).select_option("question")
    draw(reading)
    reading.get_by_role("button", name="确认添加题目分区", exact=True).click()
    reading.get_by_label("阅读依据（必填）", exact=False).fill("对照原图确认已知分区和完整阅读")
    submit(reading.get_by_role("button", name="保存本页阅读记录", exact=True), "/reading/")
    history = page.request.get(api + f"pages/{source['id']}/reading/").json()["history"]
    assert len(history) == 3 and history[0]["coverage"] == "complete" and len(history[0]["partitions"]) == 1
    assert all(row["coverage"] == "partial" for row in history[1:])
    checks.append("reading-empty-partitions-blocked-then-known-region-saves-complete-with-history")
    for width, height in ((1440, 1000), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.screenshot(path=str(output / f"completion-content-{width}.png"), full_page=True)
    assert hashlib.sha256((output / "synthetic.png").read_bytes()).hexdigest() == source["sha256"]
    checks += ["completion-pc-phone-no-overflow-original-unchanged"]
    return checks


def exercise_preparation(page, origin, db, actor, household, output):
    """Only a patched synthetic provider executes; browser traffic stays local."""
    import os
    import shutil
    from pathlib import Path
    from uuid import uuid4
    from unittest.mock import patch
    from django.test import override_settings
    from playwright.sync_api import expect
    from app.ai import services as ai
    from app.ai.models import ModelRun
    from app.persistence.models import EntityRecord
    from app.workflows import services as workflows
    from app.printing import packets, services as printing
    from app.exports.snapshots import verify_snapshot
    from verify_exports import pdf_checks, run as pdf_run
    api = origin + "/api/v1/"
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.get_by_role("button", name="收起内容核对", exact=True).click()
    page.get_by_role("button", name="新建资料", exact=True).click()
    page.get_by_label("资料名称", exact=True).fill("合成准备阶段资料")
    page.get_by_role("button", name="创建资料", exact=True).click()
    expect(page.get_by_role("button", name="合成准备阶段资料 当前资料 0 张原图页", exact=True)).to_be_visible()
    expect(page.get_by_label("选择原图", exact=True)).to_be_enabled()
    page.get_by_label("选择原图", exact=True).set_input_files(str(output / "synthetic.png"))
    page.get_by_role("button", name="上传原图", exact=True).click()
    expect(page.get_by_text("资料页 1", exact=True)).to_be_visible()
    material = next(row for row in page.request.get(api + f"materials/?household={household.pk}").json()["items"] if row["title"] == "合成准备阶段资料")
    material_id = material["id"]
    page.get_by_role("button", name="新建整理任务", exact=True).click()
    page.get_by_role("combobox", name="学习者（可选）", exact=True).select_option("")
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(f"materials/{material_id}/workflows/")) as created:
        page.get_by_role("button", name="创建并查看任务", exact=True).click()
    assert created.value.status == 200, created.value.text()
    job_id = created.value.json()["job"]["id"]
    panel = page.get_by_text("按原图准备题目草稿", exact=True).locator("xpath=ancestor::*[@data-slot='card']").first
    expect(panel.get_by_role("button", name="打开同页人工核对", exact=True)).to_be_visible()
    def configure():
        with override_settings(SWB_AI_ALLOW_TEST_HTTP=False):
            ai.create_model_config(actor, household.pk, data={
                "provider_label": "合成供应商，非真实模型", "base_url": "https://model.example.test/v1", "model": "synthetic-material",
                "connection_route": "gateway", "upstream_state": "unknown", "known_upstream_providers": "",
                "retention_state": "unknown", "retention_description": "", "confirm_external_processing": True,
                "cloud_enabled": True, "outbound_scope": "selected_regions", "timeout_seconds": 2,
                "max_output_tokens": 1000, "max_input_chars": 16000, "max_calls": 4,
                "batch_budget": "10", "input_price_per_million": "1", "output_price_per_million": "1",
                "reserved_per_call": "0.1", "non_billable_gateway": False})
    db(configure)
    panel.get_by_role("button", name="刷新准备阶段", exact=True).click()
    expect(panel.get_by_role("button", name="明确发送准备请求", exact=True)).to_be_visible()
    form = panel.locator("form").filter(has=page.get_by_label("准备原因（必填）", exact=True))
    svg = form.get_by_role("img", name="资料页 1 区域选框", exact=True)
    expect(svg).to_be_visible()
    svg.scroll_into_view_if_needed()
    box = svg.bounding_box()
    page.mouse.move(box["x"] + box["width"] * .05, box["y"] + box["height"] * .05)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * .8, box["y"] + box["height"] * .8, steps=5)
    page.mouse.up()
    form.get_by_role("button", name="确认添加准备来源", exact=True).click()
    def send(reason):
        form.get_by_label("准备原因（必填）", exact=True).fill(reason)
        form.get_by_label("我已对照原图并明确选定这些区域", exact=False).check()
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(f"workflows/{job_id}/preparation/")) as response:
            form.get_by_role("button", name="明确发送准备请求", exact=True).click()
        assert response.value.status == 200, response.value.text()
        return response.value.json()["stage_id"]
    first = send("匿名区域准备请求")
    panel.get_by_role("button", name="刷新准备阶段", exact=True).click()
    panel.get_by_label("取消阶段原因", exact=True).fill("明确取消，保留历史后重做")
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(f"preparation/{first}/cancel/")) as cancelled:
        panel.get_by_role("button", name="取消本模型阶段", exact=True).click()
    assert cancelled.value.status == 200, cancelled.value.text()
    panel.get_by_role("button", name="按原来源重做阶段", exact=True).click()
    second = send("沿用固定区域重做")
    assert second != first
    def execute():
        run = ModelRun.objects.get(pk=second)
        proposal = {"printed_text": "5 × 2 = ?", "missing_fields": [],
            "nodes": [{"kind": "method", "data": {"name": "重复加法", "steps": "5 + 5"}}],
            "answer": {"body": "10", "formulas": [], "basis": "5 + 5 = 10"}}
        response = json.dumps({"schema_version": "study-workbench.ai.v1", "task": "material",
            "source_revision_ids": list(dict.fromkeys(run.source_revision_ids + run.question_revision_ids + run.selected_region_revision_ids)),
            "proposal": proposal, "tool_calls": []})
        with patch.dict(os.environ, {"SWB_MODEL_API_KEY": "synthetic-only", "SWB_MODEL_ALLOWED_HOSTS": "model.example.test"}), \
                patch("app.ai.provider.urllib.request.OpenerDirector.open", side_effect=AssertionError("Real external requests are forbidden in this fixture")), \
                patch("app.ai.services.chat_completion", return_value=(response, {"prompt_tokens": 50, "completion_tokens": 100})) as provider:
            result = ai.execute_run(second)
        assert result.status == "awaiting_review", result.error_code
        assert provider.call_count == 1
        assert all(EntityRecord.objects.get(head_revision_id=rid).published_revision_id is None for rid in result.question_revision_ids)
    db(execute)
    panel.get_by_role("button", name="刷新准备阶段", exact=True).click()
    expect(panel.get_by_label("模型草稿题干", exact=False)).to_have_value("5 × 2 = ?")
    panel.get_by_label("原题号（可留空）", exact=True).fill("P1")
    panel.get_by_label("本阶段确认原因（必填）", exact=True).fill("核对匿名题干、来源、方法和答案")
    panel.get_by_label("我已对照本阶段原图区域核对题干", exact=False).check()
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(f"preparation/{second}/confirm/")) as confirmed:
        panel.get_by_role("button", name="确认本阶段内容", exact=True).click()
    assert confirmed.value.status == 200, confirmed.value.text()
    data = page.request.get(api + f"workflows/{job_id}/preparation/").json()
    assert data["limits"]["used_requests"] == 2
    assert [row["state"] for row in data["stages"]] == ["cancelled", "applied"]
    expect(panel.get_by_text("本阶段内容已人工确认并保存；其他阶段历史仍保留。", exact=True)).to_be_visible()
    expect(page.get_by_text("题面已确认", exact=True)).to_be_visible()
    page.evaluate("scrollTo(0, 0)")
    page.screenshot(path=str(output / "completion-preparation.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    page.screenshot(path=str(output / "completion-preparation-phone.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1000})
    # Generate from the content confirmed above, not the old import fixture.
    with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith(f"workflows/{job_id}/actions/") and response.request.post_data_json.get("action") == "queue") as queued:
        page.get_by_role("button", name="加入处理队列", exact=True).click()
    assert queued.value.status == 200, queued.value.text()
    assert db(lambda: workflows.execute_next().state) == "output_check"
    page.get_by_role("button", name="刷新任务", exact=True).click()
    expect(page.get_by_role("link", name="打开五册检查版", exact=True)).to_be_visible()
    job = db(lambda: workflows.detail(actor, job_id))
    _, manifest = db(lambda: packets.read(actor, material_id, job.result["packet_id"]))
    office = []
    for book in manifest["books"]:
        directory = db(lambda: printing.snapshot_file(actor, book["snapshot_id"], "snapshot.json").parent)
        snapshot = verify_snapshot(directory)
        copy = Path(__file__).resolve().parents[1] / "exports/fusion-completion" / output.name / book["purpose"]
        copy.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copytree(directory, copy)
        pdf_checks(copy / "document.pdf", len(snapshot["inputs"]["document"]["pages"]))
        text = pdf_run("pdftotext", directory / "document.pdf", "-")
        if book["purpose"] == "independent_practice": assert "重复加法" not in text and "5 + 5" not in text
        if book["purpose"] == "evidence_report": assert "未知" in text
        office.append({"directory": str(copy), "purpose": book["purpose"]})
    for label in ("PDF 可以阅读", "Word 文档可以阅读", "五册用途均正确"):
        page.get_by_label(label, exact=True).check()
    page.get_by_label("输出检查原因", exact=True).fill("合成内容五册检查，真实客户端仍待验")
    page.get_by_role("button", name="确认输出检查", exact=True).click()
    expect(page.get_by_role("link", name="下载完整五册 ZIP", exact=True).first).to_be_visible()
    return ["model-off-manual-entry", "explicit-region-preparation-cancel-redo-two-events",
        "synthetic-provider-no-auto-publication-one-human-confirm", "prepared-content-five-purpose-snapshots", "preparation-phone-no-overflow"], office
