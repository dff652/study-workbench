"""HTTP boundaries checked independently of the UI implementation."""
import os
import tempfile
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from app.persistence import services as core
from app.persistence.models import ImageRecord, ReviewDecision
from app.web import services
from app.web.images import MAX_UPLOAD_BYTES
from tests.web.test_services import image_bytes


class HTTPBoundaryTests(TransactionTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="swb-boundary-")
        self.addCleanup(directory.cleanup)
        self.root = directory.name
        os.chmod(self.root, 0o700)
        config = override_settings(SWB_DATA_ROOT=self.root)
        config.enable()
        self.addCleanup(config.disable)
        self.user = get_user_model().objects.create_user(username="boundary-owner")
        self.family = core.create_household(self.user, "boundary-family")
        self.material = services.create_material(self.user, self.family.pk, "合成边界", str(uuid4()))
        self.client = Client()
        self.client.force_login(self.user)

    def test_request_upload_cap_precedes_decode_and_storage(self):
        response = self.client.post(reverse("web:material_detail", args=[self.material.pk]), {
            "request_key": str(uuid4()),
            "image": SimpleUploadedFile("synthetic-large.png", b"x" * (MAX_UPLOAD_BYTES + 1)),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ImageRecord.objects.count(), 0)
        self.assertEqual(self.material.pages.count(), 0)
        self.assertEqual(os.listdir(self.root), [])

    def test_signed_review_tamper_and_foreign_private_image(self):
        result = services.upload_page(self.user, self.material.pk,
            SimpleUploadedFile("synthetic.png", image_bytes()), str(uuid4()))
        preview = services.preview_file(self.user, result["page_id"], 0)
        question = services.save_question(self.user, self.material.pk,
            printed_text="2 + 2 = ?", original_number="S1", reason="合成印刷",
            sources=[{"page_id": result["page_id"], "rotation": 0,
                "preview_sha256": preview.sha256, "display_bbox": [1, 1, 20, 20]}],
            request_key=str(uuid4()))
        detail_url = reverse("web:question_detail", args=[question["question_id"]])
        detail = self.client.get(detail_url)
        token = detail.context["review_form"].initial["context_token"]
        denied = self.client.post(reverse("web:question_review", args=[question["question_id"]]), {
            "request_key": str(uuid4()), "revision_id": question["revision_id"],
            "context_token": token + "tampered", "action": "accept", "reason": "修改签名应拒绝",
        })
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(ReviewDecision.objects.count(), 0)
        outsider = get_user_model().objects.create_user(username="boundary-outsider")
        core.create_household(outsider, "other-boundary-family")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.assertEqual(self.client.get(reverse("web:page_preview", args=[result["page_id"], 0])).status_code, 404)

    def test_private_html_cannot_be_cached_and_logout_requires_post(self):
        detail = self.client.get(reverse("web:material_detail", args=[self.material.pk]))
        self.assertIn("private", detail["Cache-Control"])
        self.assertIn("no-store", detail["Cache-Control"])
        self.assertEqual(self.client.get("/accounts/logout/").status_code, 405)
