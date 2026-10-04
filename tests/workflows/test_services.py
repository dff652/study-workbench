from datetime import timedelta
import json
from unittest.mock import patch

from django.db import DatabaseError, transaction
from django.test import Client, TransactionTestCase
from django.utils import timezone
from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.web import services as materials
from app.printing import packets, services as printing
from app.workflows import services as workflows, exchange
from app.workflows.models import WorkflowJob, WorkflowEvent
from tests.study import test_services as fixtures
from tests.study.test_services import key


class WorkflowTests(TransactionTestCase):
    setUp = fixtures.StudyServiceTests.setUp
    create_observation = fixtures.StudyServiceTests.create_observation

    def proposal(self):
        page = self.material.pages.select_related("image").get()
        refs = [{"source_id": "original", "bbox": [8, 8, 100, 70]}]
        return {"schema_version": exchange.SCHEMA,
            "sources": [{"id": "original", "page_id": str(page.pk), "sha256": page.image.sha256}],
            "records": [
                {"id": "q", "kind": "question", "data": {"printed_text": "3 × 3 = ?", "original_number": "S1", "sources": refs}},
                {"id": "k", "kind": "knowledge", "data": {"definition": "乘法表示相同加数的和。", "sources": refs}},
                {"id": "a", "kind": "answer", "data": {"question": "q", "body": "9", "basis": "3 + 3 + 3 复算"}},
                {"id": "l", "kind": "link", "data": {"question": "q", "node": "k", "role": "applies"}},
                {"id": "o", "kind": "observation", "data": {"notes": "有笔迹，来源不明。", "sources": refs}},
            ], "ledger": {"unknowns": ["独立性未测试"]}, "catalog": {"raw": ["保留原始条目"]}}

    def create(self, proposal=None):
        return workflows.create(self.owner, self.material.pk, request_key=key(), proposal=proposal)

    def do(self, job, action, **kwargs):
        return workflows.action(self.owner, job.pk, action=action, expected=workflows.context(job), request_key=key(), **kwargs)

    def test_full_proposal_native_traceability_unknowns_atomic_confirmation(self):
        proposal = self.proposal()
        job = self.create(proposal)
        self.assertEqual(job.input, proposal)
        self.assertEqual(job.state, "needs_review")
        job = self.do(job, "confirm", reason="逐项对照合成原图核对")
        mapping = job.result["mapping"]
        question = EntityRecord.objects.get(kind="question", stable_id=mapping["q"]["question_id"])
        node = EntityRecord.objects.get(kind="knowledge", stable_id=mapping["k"]["stable_id"])
        self.assertEqual(question.published_revision_id, mapping["q"]["revision_id"])
        self.assertEqual(node.published_revision_id, mapping["k"]["revision_id"])
        link = EntityRecord.objects.get(kind="knowledge_question", stable_id=mapping["l"]["stable_id"])
        self.assertEqual(link.published_revision.payload["question_revision_id"], question.published_revision_id)
        observation = EntityRecord.objects.get(kind="observation", stable_id=mapping["o"]["observation_id"])
        self.assertEqual(observation.head_revision.payload["author_state"], "unknown")
        self.assertEqual(observation.head_revision.payload["actual_date_state"], "unknown")
        self.assertEqual(EntityRecord.objects.filter(kind="attempt").count(), 0)
        self.assertTrue(question.published_revision.evidence.exists())
        self.assertEqual(list(job.events.values_list("action", flat=True)), ["created", "confirm"])

    def test_replay_stale_and_atomic_rollback(self):
        request = key()
        job = workflows.create(self.owner, self.material.pk, request_key=request, proposal=self.proposal())
        self.assertEqual(workflows.create(self.owner, self.material.pk, request_key=request, proposal=self.proposal()).pk, job.pk)
        with self.assertRaises(core.PersistenceError):
            workflows.create(self.owner, self.material.pk, request_key=request)
        bad = self.proposal()
        bad["records"][2]["data"]["question"] = "missing"
        broken = self.create(bad)
        before = EntityRecord.objects.count()
        with self.assertRaises(core.PersistenceError):
            self.do(broken, "confirm", reason="合成核对")
        self.assertEqual(EntityRecord.objects.count(), before)
        self.assertEqual(workflows.detail(self.owner, broken.pk).state, "needs_review")
        expected = workflows.context(job)
        job = self.do(job, "cancel")
        with self.assertRaises(core.PersistenceError):
            workflows.action(self.owner, job.pk, action="confirm", expected=expected, request_key=key(), reason="旧页面")

    def test_source_changes_reject_and_permissions(self):
        job = self.create(self.proposal())
        materials.create_material(self.owner, self.household.pk, "无关资料", key())
        # New knowledge revisions affect an export's fixed knowledge scope.
        from app.web import knowledge_services
        knowledge_services.save_node(self.owner, self.household.pk, "knowledge",
            data={"definition": "新知识"}, reason="合成", request_key=key())
        with self.assertRaises(core.PersistenceError) as caught:
            self.do(job, "confirm", reason="旧输入")
        self.assertEqual(caught.exception.code, "source_changed")
        with self.assertRaises(core.PersistenceError):
            workflows.action(self.viewer, job.pk, action="cancel", expected=workflows.context(job), request_key=key())
        with self.assertRaises(core.PersistenceError):
            workflows.detail(self.other, job.pk)

    def test_no_delete_or_modify_input_and_events_in_database(self):
        job = self.create()
        for mutate in (lambda: WorkflowJob.objects.filter(pk=job.pk).update(input={}),
                       lambda: WorkflowEvent.objects.filter(job=job).update(action="edited")):
            with self.assertRaises(DatabaseError), transaction.atomic():
                mutate()

    def test_closed_exchange_rejects_unknowns_wrong_sha_and_coords(self):
        pages = {str(p.pk): p for p in self.material.pages.select_related("image")}
        for change in ("sha", "coords", "field"):
            proposal = self.proposal()
            if change == "sha": proposal["sources"][0]["sha256"] = "0" * 64
            elif change == "coords": proposal["records"][0]["data"]["sources"][0]["bbox"][2] = 1000
            else: proposal["unexpected"] = True
            with self.assertRaises(core.PersistenceError):
                exchange.validate(proposal, pages)
        with self.assertRaises(core.PersistenceError):
            exchange.decode(b'{"a":1,"a":2}')
        with self.assertRaises(core.PersistenceError):
            exchange.decode(b'{"a":NaN}')
        with self.assertRaises(core.PersistenceError):
            exchange.decode(b'[' * 110 + b'0' + b']' * 110)
        with self.assertRaises(core.PersistenceError):
            exchange.decode(b'[' * 2000 + b'0' + b']' * 2000)

    def test_post_csrf_scope_and_get_never_runs(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.post(f"/api/v1/materials/{self.material.pk}/workflows/",
            data=json.dumps({"request_key": key()}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        csrf = client.get("/api/v1/session/").json()["csrf_token"]
        response = client.post(f"/api/v1/materials/{self.material.pk}/workflows/",
            data=json.dumps({"request_key": key()}), content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200, response.content)
        job_id = response.json()["job"]["id"]
        with patch("app.workflows.services.execute_next", side_effect=AssertionError("GET executed")):
            self.assertEqual(client.get(f"/api/v1/workflows/{job_id}/").status_code, 200)
        client.force_login(self.other)
        self.assertEqual(client.get(f"/api/v1/workflows/{job_id}/").status_code, 404)
        self.assertEqual(client.get(f"/api/v1/materials/{self.material.pk}/").status_code, 404)

    def test_interrupted_resume_and_late_cancellation(self):
        job = self.create()
        with patch("app.workflows.services.packets.readiness", return_value={"ready": True}):
            job = self.do(job, "queue")
        claimed = workflows._claim(job.pk)
        claimed.started_at = timezone.now() - timedelta(minutes=31)
        workflows._event(claimed, None, "test_interruption")
        workflows.recover_interrupted()
        job = workflows.detail(self.owner, job.pk)
        self.assertEqual((job.state, job.error_code), ("failed", "interrupted"))
        with patch("app.workflows.services.packets.readiness", return_value={"ready": True}):
            job = self.do(job, "resume")
        def cancelled(*args, **kwargs):
            current = workflows.detail(self.owner, job.pk)
            self.do(current, "cancel")
            return "f" * 64
        with patch("app.workflows.services.packets.generate", side_effect=cancelled):
            self.assertEqual(workflows.execute_next().state, "cancelled")
        self.assertEqual(workflows.detail(self.owner, job.pk).state, "cancelled")

    def test_revoked_author_does_not_block_other_queued_jobs(self):
        from app.persistence.models import HouseholdMember
        from django.contrib.auth import get_user_model
        from app.web.member_services import change_role
        actor = get_user_model().objects.create_user(username="sop-reviewer")
        membership = HouseholdMember.objects.create(household=self.household, user=actor, role="reviewer")
        revoked = workflows.create(actor, self.material.pk, request_key=key())
        permitted = self.create()
        with patch("app.workflows.services.packets.readiness", return_value={"ready": True}):
            workflows.action(actor, revoked.pk, action="queue", expected=workflows.context(revoked), request_key=key())
            self.do(permitted, "queue")
        change_role(self.owner, self.household.pk, membership.pk, "viewer")
        with patch("app.workflows.services.packets.generate", return_value="f" * 64):
            result = workflows.execute_next()
        self.assertEqual(result.pk, permitted.pk)
        self.assertEqual(result.state, "output_check")
        revoked.refresh_from_db()
        self.assertEqual((revoked.state, revoked.error_code), ("failed", "permission_changed"))
        self.assertEqual(list(revoked.events.values_list("action", flat=True)), ["created", "queue", "failed"])

    def test_real_five_books_output_check_and_verified_download(self):
        question = EntityRecord.objects.get(kind="question", stable_id=self.question_id).published_revision
        printing.save_answer(self.owner, self.household.pk, question.pk, body="8", formulas=[],
            basis="4 + 4 复算", expected=printing.answer_context(question), request_key=key(), confirm=True)
        job = self.create(self.proposal())
        expected, request = workflows.context(job), key()
        job = workflows.action(self.owner, job.pk, action="confirm", expected=expected,
            request_key=request, reason="逐项核对合成题干、节点、答案及原图")
        mapping = job.result["mapping"]
        replay = workflows.action(self.owner, job.pk, action="confirm", expected=expected,
            request_key=request, reason="逐项核对合成题干、节点、答案及原图")
        self.assertEqual(replay.result["mapping"], mapping)
        self.assertEqual(job.events.count(), 2)
        job = self.do(job, "queue")
        job = workflows.execute_next()
        self.assertEqual(job.state, "output_check", job.error_code)
        client = Client()
        client.force_login(self.owner)
        self.assertNotIn("download_url", client.get(f"/api/v1/workflows/{job.pk}/").json()["links"])
        with self.assertRaises(core.PersistenceError):
            self.do(job, "check_output", checks={"pdf": True}, reason="尚未检查 Word")
        packet_id = job.result["packet_id"]
        _, manifest = packets.read(self.owner, self.material.pk, packet_id)
        self.assertEqual(manifest["evidence_scope"], "not_recorded")
        self.assertEqual(len(manifest["books"]), 5)
        job = self.do(job, "check_output", checks={"pdf": True, "docx": True, "purposes": True}, reason="合成五册核对")
        self.assertEqual(job.state, "complete")
        response = client.get(f"/api/v1/workflows/{job.pk}/download/")
        self.assertEqual(response.status_code, 200)
        import io, zipfile
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        self.assertEqual(len(archive.namelist()), 21)
