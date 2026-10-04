import json
from django.test import Client, TransactionTestCase
from django.test import override_settings
from tests.study import test_services as fixtures


class EvidenceAPITests(TransactionTestCase):
    setUp = fixtures.StudyServiceTests.setUp
    create_observation = fixtures.StudyServiceTests.create_observation
    create_attempt = fixtures.StudyServiceTests.create_attempt
    save_and_review = fixtures.StudyServiceTests.save_and_review

    def url(self, part):
        return f"/api/v1/learners/{self.learner_id}/{part}/?household={self.household.pk}"

    def test_session_about_auth_scope_and_no_store(self):
        client = Client()
        response = client.get("/api/v1/session/")
        self.assertEqual(response.status_code, 401)
        client.force_login(self.viewer)
        response = client.get("/api/v1/session/")
        self.assertEqual(response.json()["households"][0]["name"], "我的家庭")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(response.json()["csrf_token"])
        about = client.get("/api/v1/about/").json()
        self.assertEqual(about["release_state"], "development")
        self.assertTrue(about["changelog"])
        self.assertEqual(client.get("/api/v1/learners/?household=" + self.other_household.pk).status_code, 404)
        client.force_login(self.other)
        self.assertEqual(client.get(self.url("overview")).status_code, 404)

    def test_counts_keep_distinct_attempts_and_assessment_history(self):
        first, second = self.create_attempt(), self.create_attempt()
        self.save_and_review(first["attempt_id"])
        self.save_and_review(first["attempt_id"])
        client = Client()
        client.force_login(self.owner)
        overview = client.get(self.url("overview"))
        self.assertEqual(overview.status_code, 200, overview.content)
        metrics = overview.json()["metrics"]
        self.assertEqual(metrics["attempt_count"], 2)
        self.assertEqual(metrics["question_count"], 1)
        self.assertEqual(metrics["independent_success_count"], 1)
        self.assertIsNone(metrics["independent_success_rate"])
        rows = client.get(self.url("attempts") + "&page_size=1").json()
        self.assertEqual((rows["total"], len(rows["items"])), (2, 1))
        self.assertTrue(rows["items"][0]["attempt_url"])
        dated = client.get(self.url("overview") + "&date_from=2026-10-01&date_to=2026-10-01")
        self.assertEqual(dated.json()["metrics"]["attempt_count"], 2)
        empty = client.get(self.url("overview") + "&source_kind=classroom_note")
        self.assertEqual(empty.json()["metrics"]["attempt_count"], 0)

    def test_invalid_filters_and_paging(self):
        client = Client()
        client.force_login(self.owner)
        for query in ("date_from=2026-99-01", "date_from=2026-10-02&date_to=2026-10-01", "source_kind=made_up"):
            self.assertEqual(client.get(self.url("overview") + "&" + query).status_code, 400)
        for query in ("page=0", "page_size=101", "page_size=abc"):
            self.assertEqual(client.get(self.url("attempts") + "&" + query).status_code, 400)

    def test_frontend_asset_traversal_and_product_landing(self):
        import tempfile
        from pathlib import Path
        client = Client()
        client.force_login(self.owner)
        with tempfile.TemporaryDirectory() as directory, override_settings(SWB_FRONTEND_ROOT=directory, SWB_FRONTEND_DEFAULT=True):
            root = Path(directory)
            (root / "assets").mkdir()
            (root / "index.html").write_text("<h1>Workbench</h1>")
            (root / "private.txt").write_text("synthetic-private")
            (root / "assets" / "escape.js").symlink_to(root / "private.txt")
            self.assertEqual(client.get("/").url, "/app/")
            self.assertEqual(client.get("/app/").status_code, 200)
            self.assertEqual(client.get("/app/assets/escape.js").status_code, 404)
            self.assertEqual(client.get("/app/assets/../private.txt").status_code, 404)
            self.assertEqual(client.get("/materials/").status_code, 200)
