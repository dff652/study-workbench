"""Synthetic HTTP coverage for confirmed, private teaching diagrams."""
from io import BytesIO
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase
from django.urls import reverse
from PIL import Image

from app.printing.models import TeachingDiagramRevision
from app.persistence.models import RevisionRecord
from app.web import services as materials
from tests.printing import test_services as fixtures
from tests.web.test_http import hidden_fields


def synthetic_png():
    output = BytesIO()
    Image.new("RGB", (32, 24), (230, 240, 250)).save(output, format="PNG")
    return output.getvalue()


class DiagramHTTPTests(TransactionTestCase):
    def setUp(self):
        fixtures.PrintTests.setUp(self)
        self.client.force_login(self.owner)

    tearDown = fixtures.PrintTests.tearDown
    page = fixtures.PrintTests.page
    source = fixtures.PrintTests.source
    question = fixtures.PrintTests.question
    published = fixtures.PrintTests.published

    def url(self, question):
        return reverse("printing:diagrams", kwargs={"pk": question.pk})

    def form_data(self, question, context, **overrides):
        data = {
            "context": context,
            "request_key": uuid4().hex,
            "placement": "question",
            "source_region_id": question.payload["evidence_refs"][0]["region_revision_id"],
            "png_upload": SimpleUploadedFile("teaching.png", synthetic_png(), content_type="image/png"),
            "vector_upload": SimpleUploadedFile("teaching.pdf", b"%PDF-1.4\nsynthetic vector", content_type="application/pdf"),
            "alt": "合成几何示意图",
            "conditions": "AB = CD\n角 A = 30 度",
            "width_points": "320",
            "min_label_points": "12",
            "independent_safe": "on",
            "content_checked": "on",
            "basis": "合成题干与原图区域逐项核对",
        }
        data.update(overrides)
        return data

    def test_save_confirms_history_and_private_file_responses(self):
        question = self.published()
        url = self.url(question)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertIn("no-store", page["Cache-Control"])
        hidden = hidden_fields(page)
        response = self.client.post(url, self.form_data(question, hidden["context"]))
        self.assertEqual(response.status_code, 302, response.content.decode())

        saved = TeachingDiagramRevision.objects.get(question_revision=question)
        detail = self.client.get(response["Location"])
        self.assertContains(detail, "合成几何示意图")
        self.assertContains(detail, "已保存")
        self.assertEqual(saved.revision_no, 1)
        png_url = reverse("printing:diagram_file", kwargs={"pk": saved.pk, "name": "png"})
        png = self.client.get(png_url)
        self.assertEqual(png["Content-Type"], "image/png")
        self.assertIn("inline", png["Content-Disposition"])
        self.assertEqual(b"".join(png.streaming_content), synthetic_png())

        vector_url = reverse("printing:diagram_file", kwargs={"pk": saved.pk, "name": "vector"})
        vector = self.client.get(vector_url)
        self.assertEqual(vector["Content-Type"], "application/octet-stream")
        self.assertIn("attachment", vector["Content-Disposition"])
        self.assertEqual(vector["X-Content-Type-Options"], "nosniff")
        self.assertEqual(b"".join(vector.streaming_content), b"%PDF-1.4\nsynthetic vector")

    def test_login_viewer_cross_household_and_csrf_boundaries(self):
        question = self.published()
        url = self.url(question)
        anonymous = Client().get(url)
        self.assertEqual(anonymous.status_code, 302)

        page = self.client.get(url)
        context = hidden_fields(page)["context"]
        viewer = Client()
        viewer.force_login(self.viewer)
        viewer_page = viewer.get(url)
        self.assertEqual(viewer_page.status_code, 200)
        self.assertNotContains(viewer_page, "保存并确认")
        denied = viewer.post(url, self.form_data(question, context))
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(Client().get(url).status_code, 302)

        other = Client()
        other.force_login(self.other)
        self.assertEqual(other.get(url).status_code, 404)

        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.owner)
        denied = protected.post(url, self.form_data(question, context))
        self.assertEqual(denied.status_code, 403)

    def test_stale_confirmation_and_invalid_or_injected_fields_do_not_save(self):
        question = self.published()
        url = self.url(question)
        context = hidden_fields(self.client.get(url))["context"]
        stale = self.client.post(url, self.form_data(question, "expired-or-forged"))
        self.assertEqual(stale.status_code, 409)

        missing_check = self.client.post(url, self.form_data(question, context, content_checked=""))
        self.assertEqual(missing_check.status_code, 400)
        invalid_width = self.client.post(url, self.form_data(question, context, width_points="49"))
        self.assertEqual(invalid_width.status_code, 400)
        injected_path = self.client.post(url, self.form_data(question, context, storage_path="/tmp/private.png"))
        self.assertEqual(injected_path.status_code, 400)
        self.assertFalse(TeachingDiagramRevision.objects.filter(question_revision=question).exists())

    def test_signed_context_preserves_many_source_regions(self):
        page = self.page()
        result = materials.save_question(self.owner, self.material.pk,
            printed_text='合成跨区域题目', original_number='multi-region',
            sources=[self.source(page) for _ in range(12)], request_key=uuid4().hex,
            reason='验证合法多区域上下文不会被表单截断', confirm=True)
        question = RevisionRecord.objects.get(pk=result['revision_id'])
        url = self.url(question)
        context = hidden_fields(self.client.get(url))['context']
        self.assertGreater(len(context), 2048)
        response = self.client.post(url, self.form_data(question, context))
        self.assertEqual(response.status_code, 302, response.content.decode())
        self.assertEqual(TeachingDiagramRevision.objects.filter(question_revision=question).count(), 1)
