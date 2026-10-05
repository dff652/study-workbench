from concurrent.futures import ThreadPoolExecutor
import json
from uuid import uuid4

from django.db import close_old_connections
from django.test import Client, TransactionTestCase

from app.persistence.models import EntityRecord
from app.study import services as study
from app.web import services as materials
from app.web.models import MaterialSet
from app.workflows.models import WorkspaceDraft
from tests.study import test_services as fixtures


class IntegrationAPITests(TransactionTestCase):
    setUp = fixtures.StudyServiceTests.setUp
    create_observation = fixtures.StudyServiceTests.create_observation
    create_attempt = fixtures.StudyServiceTests.create_attempt

    def endpoints(self, key='question:editing'):
        suffix = key + '/?household=' + self.household.pk
        return '/api/v1/drafts/' + suffix, '/api/v1/draft-save/' + suffix

    def payload(self, version=0, value=None):
        return {'expected_version': version, 'base_stamp': 'version-one',
                'payload': value if value is not None else {'answer': '未核对的输入'}, 'request_key': uuid4().hex}

    def test_private_draft_replay_tombstone_and_scope_do_not_create_domain_records(self):
        client = Client()
        client.force_login(self.owner)
        get_url, save_url = self.endpoints()
        before = EntityRecord.objects.count()
        payload = self.payload()
        saved = client.post(save_url, payload, content_type='application/json')
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(client.post(save_url, payload, content_type='application/json').json(), saved.json())
        cleared = client.post(save_url, self.payload(1, {'cleared': True}), content_type='application/json')
        self.assertEqual(cleared.json()['draft']['version'], 2)
        stale = client.post(save_url, self.payload(1), content_type='application/json')
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['draft']['payload'], {'cleared': True})
        self.assertIn('no-store', client.get(get_url)['Cache-Control'])
        client.force_login(self.viewer)
        self.assertIsNone(client.get(get_url).json()['draft'])
        self.assertEqual(client.post(save_url, self.payload(), content_type='application/json').status_code, 404)
        client.force_login(self.other)
        self.assertEqual(client.get(get_url).status_code, 404)
        self.assertEqual((WorkspaceDraft.objects.count(), EntityRecord.objects.count()), (1, before))

    def test_simultaneous_first_saves_have_one_winner(self):
        _, url = self.endpoints()
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(self.owner)

        def send(client):
            close_old_connections()
            try:
                return client.post(url, self.payload(), content_type='application/json').status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(send, clients))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(WorkspaceDraft.objects.get().version, 1)

    def test_drafts_reject_sensitive_fields_bad_json_and_missing_csrf(self):
        _, url = self.endpoints()
        client = Client()
        client.force_login(self.owner)
        for value in ({'nested': {'password': 'synthetic'}}, [{'name': 'api_key', 'value': 'synthetic'}],
                      {'score': float('nan')}, {'score': float('inf')}, {'text': '\x00'}, {'\x00': 'invalid'}):
            payload = json.dumps(self.payload(value=value))
            self.assertEqual(client.post(url, payload, content_type='application/json').status_code, 400)
        for raw in ('[]', 'null', '[{}]', '{', '{"expected_version":null}', '{"payload":{},"payload":null}'):
            self.assertEqual(client.post(url, raw, content_type='application/json').status_code, 400)
        for field in ('base_stamp', 'request_key'):
            payload = {**self.payload(), field: '\x00'}
            self.assertEqual(client.post(url, payload, content_type='application/json').status_code, 400)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.owner)
        self.assertEqual(strict.post(url, self.payload(), content_type='application/json').status_code, 403)
        self.assertFalse(WorkspaceDraft.objects.exists())

    def test_form_scope_comes_from_the_authorized_material_not_a_stale_household_query(self):
        client = Client()
        client.force_login(self.owner)
        for path in (f'/material/{self.material.pk}/question/new/', f'/page/{self.page_id}/',
                     f'/question/{self.question_id}/edit/'):
            response = client.get('/api/v1/workspace/page/', {'url': path + '?household=another-household'})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()['page']['scope'], {'household_id': self.household.pk, 'learner_id': ''})
        client.force_login(self.other)
        response = client.get('/api/v1/workspace/page/', {'url': f'/material/{self.material.pk}/question/new/'})
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('page', response.json())

    def test_material_search_and_pages_cover_records_older_than_first_two_hundred(self):
        MaterialSet.objects.bulk_create([MaterialSet(household=self.household, created_by=self.owner,
            title='历史唯一搜索项' if index == 0 else f'资料 {index}') for index in range(205)])
        client = Client()
        client.force_login(self.owner)
        endpoint = '/api/v1/materials/'
        found = client.get(endpoint, {'household': self.household.pk, 'q': '历史唯一搜索项'}).json()
        self.assertEqual(found['total'], 1)
        self.assertEqual(found['items'][0]['title'], '历史唯一搜索项')
        first = client.get(endpoint, {'household': self.household.pk, 'page': 1, 'page_size': 20}).json()
        second = client.get(endpoint, {'household': self.household.pk, 'page': 2, 'page_size': 20}).json()
        self.assertEqual((first['total'], len(first['items']), first['has_next']), (206, 20, True))
        self.assertFalse({row['id'] for row in first['items']} & {row['id'] for row in second['items']})
        for bad in ({'page': 0}, {'page_size': 101}, {'page': 'bad'}):
            self.assertEqual(client.get(endpoint, bad).status_code, 400)
        self.assertEqual(client.get(endpoint, {'household': self.other_household.pk}).status_code, 404)

    def test_report_scope_filters_attempts_and_every_aggregate_and_keeps_navigation(self):
        self.create_attempt()
        empty = materials.create_material(self.owner, self.household.pk, '尚未练习的另一份资料', uuid4().hex)
        all_report = study.evidence_report(self.owner, self.learner_entity.pk)
        selected = study.evidence_report(self.owner, self.learner_entity.pk, material_id=self.material.pk)
        empty_report = study.evidence_report(self.owner, self.learner_entity.pk, material_id=empty.pk)
        self.assertEqual(len(all_report['attempts']), 1)
        self.assertEqual(selected['attempts'], all_report['attempts'])
        self.assertEqual(selected['evidence_scope'], 'material_questions')
        for field in ('attempts', 'observed_correct_methods', 'insufficient_evidence', 'repeated_errors', 'known_actual_date_intervals'):
            self.assertEqual(empty_report[field], [])
        client = Client()
        client.force_login(self.owner)
        response = client.get(f'/study/learner/{self.learner_entity.pk}/report/', {'material': str(empty.pk)})
        self.assertContains(response, '尚未练习的另一份资料')
        self.assertContains(response, '?material=' + str(empty.pk))
        self.assertNotContains(response, '4 × 2')
        self.assertEqual(client.get(f'/study/learner/{self.learner_entity.pk}/report/', {'material': 'invalid'}).status_code, 400)
        other = materials.create_material(self.other, self.other_household.pk, '别的家庭资料', uuid4().hex)
        self.assertEqual(client.get(f'/study/learner/{self.learner_entity.pk}/report/', {'material': str(other.pk)}).status_code, 404)
