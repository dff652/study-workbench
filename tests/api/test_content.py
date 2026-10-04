import json
from django.test import Client, TransactionTestCase
from app.persistence.models import EntityRecord
from app.web.models import MaterialPage, PageReadingRevision
from app.printing.models import TeacherAnswerRevision
from tests.study import test_services as fixtures

key = fixtures.key


class ContentAPITests(TransactionTestCase):
    setUp = fixtures.StudyServiceTests.setUp
    create_observation = fixtures.StudyServiceTests.create_observation

    def setUpClient(self):
        client = Client()
        client.force_login(self.owner)
        return client

    def url(self, part="content"):
        return f"/api/v1/materials/{self.material.pk}/{part}/"

    def value(self, client):
        return {"expected": client.get(self.url()).json()["context"], "request_key": key(),
            "reason": "逐项核对合成来源", "checked": True, "printed_text": "3 × 3 = ?",
            "original_number": "C1", "sources": [{"page_id": self.page_id, "bbox": [8, 8, 100, 70]}],
            "answer": {"body": "9", "formulas": [], "basis": "3 + 3 + 3"},
            "nodes": [{"kind": "knowledge", "data": {"definition": "乘法"}}]}

    def post(self, client, url, value):
        return client.post(url, json.dumps(value), content_type="application/json")

    def test_atomic_confirmation_sources_links_and_replay(self):
        client = self.setUpClient()
        value = self.value(client)
        response = self.post(client, self.url(), value)
        self.assertEqual(response.status_code, 200, response.content)
        before = EntityRecord.objects.count()
        self.assertEqual(self.post(client, self.url(), value).json(), response.json())
        self.assertEqual(before, EntityRecord.objects.count())
        row = next(row for row in client.get(self.url()).json()["questions"] if row["id"] == response.json()["question_id"])
        self.assertTrue(row["confirmed"] and row["answer"]["confirmed"])
        self.assertEqual(row["sources"], value["sources"])
        self.assertEqual(EntityRecord.objects.filter(kind="attempt").count(), 0)
        self.assertEqual(EntityRecord.objects.filter(kind="knowledge_question", published_revision__isnull=False).count(), 1)
        self.assertEqual(self.post(client, self.url(), {**value, "request_key": key()}).status_code, 409)

    def test_invalid_answer_or_unknown_fields_roll_back_question(self):
        client = self.setUpClient()
        value = self.value(client)
        value["answer"]["formulas"] = [["unsupported", "x"]]
        before = EntityRecord.objects.count()
        self.assertEqual(self.post(client, self.url(), value).status_code, 400)
        self.assertEqual(before, EntityRecord.objects.count())
        self.assertEqual(TeacherAnswerRevision.objects.count(), 0)
        self.assertEqual(self.post(client, self.url(), {**value, "guess_mastery": True}).status_code, 400)

    def test_answer_only_update_keeps_exact_question_version_and_relations(self):
        client = self.setUpClient()
        value = self.value(client)
        value.update(question_id=self.question_id, printed_text="4 × 2 = ?", original_number="K1")
        response = self.post(client, self.url(), value)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["revision_id"], self.question_revision_id)
        entity = EntityRecord.objects.get(kind="question", stable_id=self.question_id)
        self.assertEqual(entity.revisions.count(), 1)
        value.update(expected=client.get(self.url()).json()["context"], request_key=key(), nodes=[])
        value["answer"]["body"] = "8，订正答案"
        self.assertEqual(self.post(client, self.url(), value).status_code, 200)
        self.assertEqual(TeacherAnswerRevision.objects.count(), 2)
        self.assertEqual(EntityRecord.objects.filter(kind="knowledge_question", published_revision__isnull=False).count(), 1)

    def test_empty_manual_draft_preserves_unknown_and_cannot_publish(self):
        client = self.setUpClient()
        value = {"expected": client.get(self.url()).json()["context"], "request_key": key(),
            "reason": "题面看不清，保留待重拍", "printed_text": "", "original_number": "U1",
            "sources": [{"page_id": self.page_id, "bbox": [8, 8, 100, 70]}]}
        response = self.post(client, f"/api/v1/materials/{self.material.pk}/content/draft/", value)
        self.assertEqual(response.status_code, 200, response.content)
        entity = EntityRecord.objects.get(kind="question", stable_id=response.json()["question_id"])
        self.assertIsNone(entity.published_revision_id)
        self.assertIsNone(entity.head_revision.payload["printed_text"])
        self.assertIn("printed_text", entity.head_revision.payload["missing_fields"])
        self.assertEqual(EntityRecord.objects.filter(kind="attempt").count(), 0)

    def test_erratum_preserves_printed_text_and_history_without_child_error(self):
        client = self.setUpClient()
        value = {"expected": client.get(self.url()).json()["context"], "request_key": key(),
            "question_id": self.question_id, "corrected_text": "4 × 3 = ?",
            "basis": "合成印刷错误核对", "reason": "讲义勘误", "checked": True}
        response = self.post(client, self.url("erratum"), value)
        self.assertEqual(response.status_code, 200, response.content)
        question = EntityRecord.objects.get(kind="question", stable_id=self.question_id)
        self.assertEqual(question.head_revision.payload["printed_text"], "4 × 2 = ?")
        self.assertEqual(question.head_revision.payload["working_text"], "4 × 3 = ?")
        self.assertEqual(question.revisions.count(), 2)
        self.assertEqual(EntityRecord.objects.filter(kind="assessment").count(), 0)
        self.assertEqual(self.post(client, self.url("erratum"), value).status_code, 200)

    def test_reading_unknowns_permissions_and_original_unchanged(self):
        client = self.setUpClient()
        page = MaterialPage.objects.get(pk=self.page_id)
        original = page.image.sha256
        url = f"/api/v1/pages/{self.page_id}/reading/"
        value = {"expected": client.get(url).json()["context"], "request_key": key(),
            "reading": "read", "coverage": "complete", "partitions": [{"kind": "unknown", "bbox": [8, 8, 100, 70]}],
            "pending_items": [], "basis": "合成阅读"}
        self.assertEqual(self.post(client, url, value).status_code, 400)
        value.update(coverage="partial", pending_items=["字迹看不清"], request_key=key())
        self.assertEqual(self.post(client, url, value).status_code, 200)
        self.assertEqual(client.get(url).json()["current"]["coverage"], "partial")
        self.assertEqual(client.get(url).json()["current"]["pending_items"], ["字迹看不清"])
        page.image.refresh_from_db()
        self.assertEqual(page.image.sha256, original)
        self.assertEqual(PageReadingRevision.objects.count(), 1)
        viewer = Client()
        viewer.force_login(self.viewer)
        self.assertEqual(viewer.get(self.url()).status_code, 200)
        self.assertEqual(self.post(viewer, self.url(), self.value(client)).status_code, 404)
        stranger = Client()
        stranger.force_login(self.other)
        self.assertEqual(stranger.get(url).status_code, 404)
