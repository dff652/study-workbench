"""Authenticated, CSRF-protected HTTP confirmation over fabricated proposals."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase
from django.urls import reverse

from app.ai import review_services
from app.ai.models import ModelRun
from app.persistence.models import RevisionRecord
from app.web import services as materials
from tests.ai import test_services as fixtures


class ReviewHTTPTests(TransactionTestCase):
    reset_sequences = True

    setUp = fixtures.AIWorkflowTests.setUp
    config_data = fixtures.AIWorkflowTests.config_data
    make_config = fixtures.AIWorkflowTests.make_config
    make_question = fixtures.AIWorkflowTests.make_question
    make_blank_question = fixtures.AIWorkflowTests.make_blank_question
    region_for = fixtures.AIWorkflowTests.region_for
    queue_question = fixtures.AIWorkflowTests.queue_question
    proposal_response = fixtures.AIWorkflowTests.proposal_response
    run_with_response = fixtures.AIWorkflowTests.run_with_response

    def ready_run(self, *, blank=True):
        question = self.make_blank_question() if blank else self.published
        run = self.queue_question(question, image=blank)
        response = self.proposal_response(run, printed_text="合成识别：3 + 4 = ?")
        self.run_with_response(run, response)
        return run

    def form_data(self, page):
        form = page.context["form"]
        return {"context": form["context"].value(), "request_key": form["request_key"].value(),
            "checked": "on", "reason": "人工核对合成题目并保留未知"}

    def test_review_is_authenticated_readable_and_write_form_is_hidden_from_viewers(self):
        run = self.ready_run()
        url = reverse("ai:review", kwargs={"run_id": run.pk})
        anonymous = Client()
        self.assertEqual(anonymous.get(url).status_code, 302)

        owner = Client()
        owner.force_login(self.owner)
        page = owner.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertIn("no-store", page["Cache-Control"])
        self.assertContains(page, "任务固定的模型配置与外发确认")
        self.assertContains(page, "合成识别：3 + 4 = ?")
        self.assertContains(page, "原印刷题干为空")
        self.assertContains(page, "确认并保存")

        viewer = Client()
        viewer.force_login(self.viewer)
        read_only = viewer.get(url)
        self.assertEqual(read_only.status_code, 200)
        self.assertContains(read_only, "合成识别：3 + 4 = ?")
        self.assertNotContains(read_only, "name=\"checked\"")
        self.assertNotContains(read_only, "确认并保存")

        outsider = Client()
        outsider.force_login(self.other)
        self.assertEqual(outsider.get(url).status_code, 404)

    def test_shared_original_image_pages_are_not_misattributed_as_exact_question_sources(self):
        run = self.ready_run(blank=True)
        reused_material = materials.create_material(self.owner, self.household.pk,
            "合成的原图复用资料", fixtures.key())
        reused_page = materials.upload_page(self.owner, reused_material.pk,
            SimpleUploadedFile("reused-original.png", self.original_bytes, content_type="image/png"),
            fixtures.key())
        second_same_material_page = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile("second-page-same-original.png", self.original_bytes,
                content_type="image/png"), fixtures.key())
        self.assertTrue(reused_page["duplicate_image"])
        self.assertTrue(second_same_material_page["duplicate_image"])

        client = Client()
        client.force_login(self.owner)
        page = client.get(reverse("ai:review", kwargs={"run_id": run.pk}))
        self.assertEqual(page.status_code, 200)
        source_pages = page.context["source_pages"]
        self.assertEqual([item["page_id"] for item in source_pages], [self.page["page_id"]])
        self.assertEqual([item["label"] for item in source_pages], ["原图来源 · 第 1 页"])

    def test_confirmation_requires_csrf_then_saves_and_labels_confirmed_output(self):
        run = self.ready_run()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        url = reverse("ai:review", kwargs={"run_id": run.pk})
        page = client.get(url)
        self.assertEqual(page.status_code, 200)
        values = self.form_data(page)
        confirm_url = reverse("ai:confirm", kwargs={"run_id": run.pk})

        rejected = client.post(confirm_url, values)
        self.assertEqual(rejected.status_code, 403)
        run.refresh_from_db()
        self.assertEqual(run.status, ModelRun.Status.AWAITING_REVIEW)

        values["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        saved = client.post(confirm_url, values)
        self.assertEqual(saved.status_code, 302)
        run.refresh_from_db()
        self.assertEqual(run.status, ModelRun.Status.APPLIED)
        self.assertEqual(len(run.output_revision_ids), 1)
        output = RevisionRecord.objects.get(pk=run.output_revision_ids[0])
        self.assertEqual(output.entity.kind, "question")
        self.assertEqual(output.review_projection.state, "accepted")

        completed = client.get(url)
        self.assertEqual(completed.status_code, 200)
        self.assertContains(completed, "已确认并保存的内容")
        self.assertNotContains(completed, "已生成的待确认内容")
        self.assertContains(completed, "已完成逐项核对并保存确认")
        self.assertNotContains(completed, "name=\"checked\"")

    def test_stale_source_keeps_proposal_visible_but_removes_confirmation_form(self):
        run = self.ready_run()
        client = Client()
        client.force_login(self.owner)
        url = reverse("ai:review", kwargs={"run_id": run.pk})
        page = client.get(url)
        values = self.form_data(page)
        original = RevisionRecord.objects.get(pk=run.question_revision_ids[0])
        detail = materials.question_detail(self.owner, original.entity.stable_id)
        materials.save_question(self.owner, self.material.pk, printed_text="人工新增版本",
            original_number="AI-OCR", sources=[self.source], question_id=original.entity.stable_id,
            expected_context=detail["edit_context"], request_key=fixtures.key(), reason="合成来源更新")

        response = client.post(reverse("ai:confirm", kwargs={"run_id": run.pk}), values)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "合成识别：3 + 4 = ?", status_code=409)
        self.assertContains(response, "来源或依赖已改变", status_code=409)
        self.assertNotContains(response, "name=\"checked\"", status_code=409)
        run.refresh_from_db()
        self.assertEqual(run.status, ModelRun.Status.AWAITING_REVIEW)
