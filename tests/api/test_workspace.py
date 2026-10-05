from urllib.parse import urlencode
from uuid import uuid4

from django.test import Client, SimpleTestCase, TransactionTestCase
from lxml import html

from app.api.workspace import fragment, local_url
from app.web.models import MaterialSet as Material
from tests.study import test_services as fixtures


class FragmentTests(SimpleTestCase):
    def test_fragment_removes_active_content_and_preserves_form_and_geometry(self):
        raw = '''<html><head><script src="/static/web/regions.a123456789ab.js"></script></head>
        <body><nav>old navigation</nav><main>&lt;script&gt;literal&lt;/script&gt;<h1>核对</h1>
        <script><b>bad</b></script><iframe src="/bad"><i>bad</i></iframe>
        <form method="post"><input name="csrfmiddlewaretoken" value="token">
        <img src="/private/source/" onerror="alert(1)">
        <a href="javascript:alert(1)" onclick="alert(1)">bad link</a>
        <a href="https://example.org/">external</a>
        <div data-region-picker="" style="left:12%;top:20px;background:url(x)"></div>
        <noscript><button type="submit">保存</button></noscript></form></main></body></html>'''
        page = fragment(raw, "/question/example/?version=1")
        root = html.fragment_fromstring(page["html"], create_parent=True)
        self.assertEqual(page["widgets"], ["regions"])
        self.assertFalse(root.xpath(".//script|.//iframe|.//*[@onclick]|.//*[@onerror]"))
        self.assertFalse(root.xpath(".//a/@href"))
        self.assertEqual(root.xpath(".//form/@action"), ["/question/example/?version=1"])
        self.assertEqual(root.xpath(".//*[@data-region-picker]/@style"), ["left:12%;top:20px"])
        self.assertEqual(root.xpath(".//input/@name"), ["csrfmiddlewaretoken"])
        self.assertNotIn("old navigation", page["html"])
        self.assertIn("<script>literal</script>", root.text_content())

    def test_addresses_are_local(self):
        for value in ("https://example.org/", "//example.org/", "javascript:alert(1)", "/\\example.org/", "/x\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                local_url(value)

    def test_native_tabs_survive_sanitizing_with_panel_relationships(self):
        raw = """<main><div role="tablist" data-workspace-tabs aria-label="相关记录">
          <button type="button" id="record-tab" role="tab" aria-controls="record-panel"
            aria-selected="true" data-workspace-tab="records">记录</button></div>
          <section id="record-panel" role="tabpanel" aria-labelledby="record-tab"
            data-workspace-panel><form method="post"><input name="reason"></form></section></main>"""
        root = html.fragment_fromstring(fragment(raw, "/members/")["html"], create_parent=True)
        button = root.xpath('.//button[@role="tab"]')[0]
        panel = root.xpath('.//section[@role="tabpanel"]')[0]
        self.assertEqual(button.get("aria-selected"), "true")
        self.assertEqual(button.get("aria-controls"), panel.get("id"))
        self.assertEqual(panel.get("aria-labelledby"), button.get("id"))
        self.assertIsNone(panel.get("hidden"))
        self.assertEqual(root.xpath(".//form/@action"), ["/members/"])


class WorkspaceAPITests(TransactionTestCase):
    setUp = fixtures.StudyServiceTests.setUp
    create_observation = fixtures.StudyServiceTests.create_observation
    schedule_context = fixtures.StudyServiceTests.schedule_context
    create_schedule = fixtures.StudyServiceTests.create_schedule
    create_attempt = fixtures.StudyServiceTests.create_attempt
    save_and_review = fixtures.StudyServiceTests.save_and_review

    def endpoint(self, url, command=False):
        return "/api/v1/workspace/" + ("submit/" if command else "page/") + "?" + urlencode({"url": url})

    def test_auth_whitelist_and_household_permissions(self):
        url = f"/material/{self.material.pk}/"
        client = Client()
        self.assertEqual(client.get(self.endpoint(url)).status_code, 401)
        client.force_login(self.owner)
        for target in ("/admin/", "/accounts/logout/", "/api/v1/session/", f"/page/{self.page_id}/preview/0/"):
            self.assertEqual(client.get(self.endpoint(target)).status_code, 404, target)
        self.assertEqual(client.get(self.endpoint("https://example.org/")).status_code, 400)
        result = client.get(self.endpoint(url))
        self.assertEqual(result.status_code, 200)
        self.assertIn("no-store", result["Cache-Control"])
        self.assertIn("合成题目", result.json()["page"]["html"])
        self.assertNotIn("site-header", result.json()["page"]["html"])
        client.force_login(self.other)
        self.assertEqual(client.get(self.endpoint(url)).status_code, 404)
        client.force_login(self.viewer)
        knowledge = client.get(self.endpoint(f"/knowledge/?household_id={self.household.pk}"))
        self.assertEqual(knowledge.status_code, 200)
        self.assertNotIn('href="/knowledge/create/', knowledge.json()["page"]["html"])
        self.assertIn("有编辑权限的成员", knowledge.json()["page"]["html"])
        before = Material.objects.count()
        result = client.post(self.endpoint("/material/new/", True), {
            "household_id": self.household.pk, "title": "不可写入", "request_key": uuid4()})
        self.assertNotEqual(result.status_code, 200)
        self.assertEqual(Material.objects.count(), before)

    def test_commands_csrf_validation_redirect_and_idempotence(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        url = self.endpoint("/material/new/", True)
        self.assertEqual(client.post(url, {}).status_code, 403)
        csrf = client.get("/api/v1/session/").json()["csrf_token"]
        invalid = client.post(url, {"request_key": uuid4(), "household_id": self.household.pk}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('name="title"', invalid.json()["page"]["html"])
        body = {"request_key": uuid4(), "household_id": self.household.pk, "title": "通过主框架创建"}
        before = Material.objects.count()
        first = client.post(url, body, HTTP_X_CSRFTOKEN=csrf)
        second = client.post(url, body, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["redirect"], second.json()["redirect"])
        self.assertEqual(Material.objects.count(), before + 1)
        self.assertEqual(client.get(self.endpoint(first.json()["redirect"])).status_code, 200)
        self.assertEqual(client.get(url).status_code, 405)

    def test_query_redirect_and_region_widgets(self):
        client = Client()
        client.force_login(self.owner)
        redirect = client.get(self.endpoint("/knowledge/")).json()["redirect"]
        self.assertIn("household_id=", redirect)
        self.assertEqual(client.get(self.endpoint(redirect)).status_code, 200)
        response = client.get(self.endpoint(f"/material/{self.material.pk}/question/new/"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("regions", response.json()["page"]["widgets"])
        self.assertIn('name="sources"', response.json()["page"]["html"])

    def test_encoded_household_path_uses_django_decoding(self):
        from urllib.parse import quote
        from app.api.workspace import allowed_target
        _, _, match = allowed_target('/ai/config/' + quote('家庭 A', safe='') + '/')
        self.assertEqual(match.kwargs['household_id'], '家庭 A')

    def test_schedule_page_scope_uses_authorized_owner_not_query_context(self):
        schedule, _ = self.create_schedule()
        target = f'/study/schedule/{schedule["schedule_pk"]}/?household=other&learner=other'
        client = Client()
        client.force_login(self.owner)
        expected = {"household_id": str(self.household.pk), "learner_id": self.learner_id}
        result = client.get(self.endpoint(target))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["page"]["scope"], expected)
        invalid = client.post(self.endpoint(target, True), {})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()["page"]["scope"], expected)
        client.force_login(self.viewer)
        self.assertEqual(client.get(self.endpoint(target)).json()["page"]["scope"], expected)
        client.force_login(self.other)
        denied = client.get(self.endpoint(target))
        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("page", denied.json())
        client.force_login(self.owner)
        attempt = self.create_attempt()
        assessment = self.save_and_review(attempt["attempt_id"])
        for path in (f'/learning/attempt/{attempt["attempt_id"]}/',
                     f'/learning/attempt/{attempt["attempt_id"]}/edit/',
                     f'/learning/assessment/{assessment["assessment_id"]}/',
                     f'/learning/observation/{self.observation["observation_id"]}/',
                     f'/study/learner/{self.learner_entity.pk}/report/'):
            with self.subTest(path=path):
                scoped = client.get(self.endpoint(path + '?learner=other'))
                self.assertEqual(scoped.status_code, 200)
                self.assertEqual(scoped.json()["page"]["scope"], expected)
