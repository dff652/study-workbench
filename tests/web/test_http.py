"""Synthetic HTTP coverage for the private manual review path."""
from html.parser import HTMLParser
import json
import os
import tempfile
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image

from app.persistence import services as core_services
from app.persistence.models import HouseholdMember, ReviewDecision
from app.web import services as web_services


class HiddenFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "input" and values.get("type") == "hidden" and "name" in values:
            self.values[values["name"]] = values.get("value", "")


def hidden_fields(response):
    parser = HiddenFields()
    parser.feed(response.content.decode("utf-8"))
    return parser.values


def synthetic_png(color=(235, 238, 242)):
    from io import BytesIO

    output = BytesIO()
    Image.new("RGB", (120, 80), color=color).save(output, format="PNG")
    return output.getvalue()


class WebHTTPTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="swb-web-test-")
        self.addCleanup(directory.cleanup)
        os.chmod(directory.name, 0o700)
        settings = override_settings(SWB_DATA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)

        self.owner = get_user_model().objects.create_user(username=f"owner-{uuid4().hex[:8]}", password="synthetic-only")
        self.household = core_services.create_household(self.owner, f"http-test-{uuid4().hex}")
        self.material = web_services.create_material(
            self.owner, self.household.pk, "合成 HTTP 样例", str(uuid4())
        )
        self.client = Client()
        self.client.force_login(self.owner)
        self.material_url = reverse("web:material_detail", kwargs={"material_id": self.material.pk})
        self.png = synthetic_png()

    def upload(self, name="synthetic.png", raw=None):
        response = self.client.post(
            self.material_url,
            {"image": SimpleUploadedFile(name, raw or self.png, content_type="image/png"),
             "request_key": str(uuid4())},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200, response.content.decode("utf-8"))
        return response.json()

    def test_login_private_preview_upload_reuse_and_order(self):
        anonymous = Client()
        response = anonymous.get(reverse("web:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.headers["Location"])

        first = self.upload("first.png")
        second = self.upload("same-bytes.png")
        self.assertFalse(first["duplicate_image"])
        self.assertTrue(second["duplicate_image"])
        self.assertEqual(second["position"], 2)

        page_id = first["page_id"]
        page_url = reverse("web:page_detail", kwargs={"page_id": page_id})
        self.assertEqual(self.client.get(page_url).status_code, 200)
        preview_url = reverse("web:page_preview", kwargs={"page_id": page_id, "rotation": 0})
        self.assertEqual(anonymous.get(preview_url).status_code, 302)
        preview = self.client.get(preview_url)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview["Content-Type"], "image/png")
        self.assertIn("no-store", preview["Cache-Control"])
        self.assertTrue(b"".join(preview.streaming_content).startswith(b"\x89PNG"))

        ordered = self.client.post(reverse("web:reorder_pages", kwargs={"material_id": self.material.pk}), {
            "ids": json.dumps([second["page_id"], first["page_id"]]), "request_key": str(uuid4()),
        })
        self.assertEqual(ordered.status_code, 302)

    def test_upload_requires_csrf_and_viewer_cannot_write(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        denied = csrf_client.post(self.material_url, {
            "image": SimpleUploadedFile("csrf.png", self.png, content_type="image/png"),
            "request_key": str(uuid4()),
        })
        self.assertEqual(denied.status_code, 403)

        page = self.upload()["page_id"]
        invalid = self.client.post(self.material_url, {
            "image": SimpleUploadedFile("not-an-image.txt", b"synthetic text", content_type="text/plain"),
            "request_key": str(uuid4()),
        }, HTTP_ACCEPT="application/json", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("JPEG/PNG", invalid.json()["message"])
        viewer = get_user_model().objects.create_user(username=f"viewer-{uuid4().hex[:8]}")
        HouseholdMember.objects.create(household=self.household, user=viewer, role=HouseholdMember.Role.VIEWER)
        viewer_client = Client()
        viewer_client.force_login(viewer)
        self.assertEqual(viewer_client.get(self.material_url).status_code, 200)
        preview_url = reverse("web:page_preview", kwargs={"page_id": page, "rotation": 0})
        self.assertEqual(viewer_client.get(preview_url).status_code, 200)
        denied = viewer_client.post(self.material_url, {
            "image": SimpleUploadedFile("viewer.png", self.png, content_type="image/png"),
            "request_key": str(uuid4()),
        })
        self.assertEqual(denied.status_code, 404)

    def test_question_sources_edit_conflict_and_review_history(self):
        page = self.upload("first.png")["page_id"]
        preview = web_services.preview_file(self.owner, page, 0)
        next_page = self.upload("second.png", synthetic_png(color=(220, 225, 232)))["page_id"]
        next_preview = web_services.preview_file(self.owner, next_page, 0)
        sources = [{
            "page_id": page,
            "rotation": 0,
            "preview_sha256": preview.sha256,
            "display_bbox": [8, 10, 100, 65],
        }]
        response = self.client.post(reverse("web:question_new", kwargs={"material_id": self.material.pk}), {
            "request_key": str(uuid4()),
            "original_number": "1(a)",
            "printed_text": "2 + 3 = ?",
            "sources": json.dumps(sources),
            "reason": "从合成原图人工录入",
        })
        self.assertEqual(response.status_code, 302, response.content.decode("utf-8"))
        question_path = response.headers["Location"]
        question_id = question_path.rstrip("/").rsplit("/", 1)[-1]
        detail_url = reverse("web:question_detail", kwargs={"question_id": question_id})

        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("2 + 3 = ?", detail.content.decode("utf-8"))
        self.assertIn(reverse("web:page_detail", kwargs={"page_id": page}).encode(), detail.content)
        page_detail = self.client.get(reverse("web:page_detail", kwargs={"page_id": page}))
        self.assertIn("1(a)".encode(), page_detail.content)
        legacy_page_url = reverse("web:page_detail", kwargs={"page_id": page})
        with patch.object(web_services, "question_detail", side_effect=ObjectDoesNotExist):
            legacy_page_detail = self.client.get(legacy_page_url)
        self.assertEqual(legacy_page_detail.status_code, 200)
        self.assertIn("旧索引题目，题干与区域待补".encode(), legacy_page_detail.content)
        self.assertIn(f'id="question-{question_id}"'.encode(), legacy_page_detail.content)
        self.assertNotIn(f'href="{detail_url}"'.encode(), legacy_page_detail.content)
        old_review = hidden_fields(detail)

        edit_url = reverse("web:question_edit", kwargs={"question_id": question_id})
        edit = self.client.get(edit_url)
        self.assertEqual(edit.status_code, 200)
        edit_fields = hidden_fields(edit)
        self.assertEqual(json.loads(edit_fields["sources"])[0]["page_id"], page)
        edit_payload = {
            "request_key": str(uuid4()),
            "original_number": "1(a)",
            "printed_text": "2 + 4 = ?",
            "sources": json.dumps([{
                "page_id": next_page,
                "rotation": 0,
                "preview_sha256": next_preview.sha256,
                "display_bbox": [20, 15, 90, 70],
            }]),
            "reason": "修正合成题干",
            "context_token": edit_fields["context_token"],
        }
        edited = self.client.post(edit_url, edit_payload)
        self.assertEqual(edited.status_code, 302, edited.content.decode("utf-8"))
        edit_replay = self.client.post(edit_url, edit_payload)
        self.assertEqual(edit_replay.status_code, 302, edit_replay.content.decode("utf-8"))
        self.assertEqual(len(web_services.question_detail(self.owner, question_id)["history"]), 2)
        edited_detail = self.client.get(detail_url)
        self.assertIn("2 + 3 = ?".encode(), edited_detail.content)
        self.assertIn("2 + 4 = ?".encode(), edited_detail.content)
        self.assertIn("first.png".encode(), edited_detail.content)
        self.assertIn("second.png".encode(), edited_detail.content)
        self.assertEqual(edited_detail.content.count(b"history-region-box"), 2)

        stale = self.client.post(reverse("web:question_review", kwargs={"question_id": question_id}), {
            "request_key": str(uuid4()), "revision_id": old_review["revision_id"],
            "context_token": old_review["context_token"], "action": "accept", "reason": "旧页面审核",
        })
        self.assertEqual(stale.status_code, 409)

        current = self.client.get(detail_url)
        current_fields = hidden_fields(current)
        review_url = reverse("web:question_review", kwargs={"question_id": question_id})
        review_payload = {
            "request_key": str(uuid4()), "revision_id": current_fields["revision_id"],
            "context_token": current_fields["context_token"], "action": "accept", "reason": "核对合成题干与来源",
        }
        accepted = self.client.post(review_url, review_payload)
        self.assertEqual(accepted.status_code, 302, accepted.content.decode("utf-8"))
        review_replay = self.client.post(review_url, review_payload)
        self.assertEqual(review_replay.status_code, 302, review_replay.content.decode("utf-8"))
        self.assertEqual(ReviewDecision.objects.filter(revision_id=current_fields["revision_id"]).count(), 1)
        reviewed = self.client.get(detail_url)
        self.assertIn("已审核".encode(), reviewed.content)
        self.assertIn("核对合成题干与来源".encode(), reviewed.content)
