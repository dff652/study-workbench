"""Synthetic HTTP coverage for the private knowledge editor boundary."""
import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase
from django.urls import reverse

from app.persistence import services as core
from app.persistence.models import HouseholdMember


class KnowledgeHTTPTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.owner = get_user_model().objects.create_user(username=f"knowledge-http-owner-{suffix}")
        self.viewer = get_user_model().objects.create_user(username=f"knowledge-http-viewer-{suffix}")
        self.household = core.create_household(self.owner, f"knowledge-http-house-{suffix}")
        HouseholdMember.objects.create(household=self.household, user=self.viewer, role=HouseholdMember.Role.VIEWER)
        self.create_url = f"{reverse('knowledge:node_new', kwargs={'kind': 'knowledge'})}?household_id={self.household.pk}"
        self.client = Client()
        self.client.force_login(self.owner)

    def payload(self):
        return {"request_key": uuid.uuid4().hex, "household_id": self.household.pk,
            "reason": "人工合成录入", "sources": "[]", "definition": "乘法分配律：a(b+c)=ab+ac",
            "conditions": "适用整数与实数", "common_errors": "漏乘后一项"}

    def test_editor_requires_csrf_and_viewer_cannot_create(self):
        anonymous = Client()
        self.assertEqual(anonymous.get(reverse("knowledge:index")).status_code, 302)

        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.owner)
        self.assertEqual(protected.get(self.create_url).status_code, 200)
        self.assertEqual(protected.post(self.create_url, self.payload()).status_code, 403)

        viewer_client = Client()
        viewer_client.force_login(self.viewer)
        self.assertEqual(viewer_client.get(self.create_url).status_code, 200)
        self.assertEqual(viewer_client.post(self.create_url, self.payload()).status_code, 404)

    def test_owner_can_create_manual_draft_and_open_its_detail(self):
        response = self.client.post(self.create_url, self.payload())
        self.assertEqual(response.status_code, 302, response.content.decode("utf-8"))
        detail = self.client.get(response.headers["Location"])
        self.assertEqual(detail.status_code, 200)
        content = detail.content.decode("utf-8")
        self.assertIn("乘法分配律", content)
        self.assertIn("人工依据尚未关联", content)
        self.assertIn("待审核", content)
