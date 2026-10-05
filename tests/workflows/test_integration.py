from uuid import uuid4

from django.test import Client, TransactionTestCase

from app.exports.contracts import canonical, digest
from app.persistence import services as core
from app.persistence.models import RevisionRecord
from app.printing import packets, services as printing
from app.workflows import services, exchange
from app.workflows.models import WorkflowJob
from tests.study import test_services as fixtures


class ScopedWorkflowTests(TransactionTestCase):
    setUp = fixtures.StudyServiceTests.setUp
    create_observation = fixtures.StudyServiceTests.create_observation
    create_attempt = fixtures.StudyServiceTests.create_attempt

    def test_pre_integration_job_receipt_replays_and_different_scope_does_not(self):
        key = uuid4().hex
        value = {'schema_version': exchange.SCHEMA, 'sources': [], 'records': []}
        # Exact persisted shape of the deployed v1 workflow, without a scope field.
        old = WorkflowJob.objects.create(material=self.material, created_by=self.owner, request_key=key,
            fingerprint=digest(canonical({'input': value, 'learner_id': self.learner_id, 'actor': self.owner.pk})),
            input=value, source_stamp=services.stamp(self.material), state='ready', result={'learner_id': self.learner_id})
        self.assertEqual(services.create(self.owner, self.material.pk, request_key=key, learner_id=self.learner_id).pk, old.pk)
        self.assertEqual(services.create(self.owner, self.material.pk, request_key=key, learner_id=self.learner_id,
            evidence_scope='selected_learner_history').pk, old.pk)
        with self.assertRaises(core.PersistenceError) as failure:
            services.create(self.owner, self.material.pk, request_key=key, learner_id=self.learner_id,
                evidence_scope='material_questions')
        self.assertEqual(failure.exception.code, 'request_conflict')
        old.refresh_from_db()
        self.assertEqual(old.result, {'learner_id': self.learner_id})

    def test_api_scope_reaches_real_worker_and_frozen_packet(self):
        self.create_attempt()
        revision = RevisionRecord.objects.get(pk=self.question_revision_id)
        printing.save_answer(self.owner, self.household.pk, revision.pk, body='8', formulas=[],
            basis='两段各 4 厘米相加', expected=printing.answer_context(revision), request_key=uuid4().hex, confirm=True)
        client = Client()
        client.force_login(self.owner)
        endpoint = f'/api/v1/materials/{self.material.pk}/workflows/'
        for scope in ('material_questions', 'selected_learner_history'):
            response = client.post(endpoint, {'request_key': uuid4().hex, 'learner_id': self.learner_id,
                'evidence_scope': scope}, content_type='application/json')
            self.assertEqual(response.status_code, 200, response.content)
            job = WorkflowJob.objects.get(pk=response.json()['job']['id'])
            self.assertEqual(job.result['evidence_scope'], scope)
            services.action(self.owner, job.pk, action='queue', expected=services.context(job), request_key=uuid4().hex)
            result = services.execute_next()
            self.assertEqual(result.state, 'output_check', result.error_code)
            _, manifest = packets.read(self.owner, self.material.pk, result.result['packet_id'])
            self.assertEqual(manifest['evidence_scope'], scope)
            report_book = next(book for book in manifest['books'] if book['purpose'] == 'evidence_report')
            from app.printing.models import ExportSnapshot
            report = ExportSnapshot.objects.get(pk=report_book['snapshot_id']).provenance['report']
            self.assertEqual(report['evidence_scope'], scope)
            self.assertEqual(len(report['attempts']), 1)
        count = WorkflowJob.objects.count()
        rejected = client.post(endpoint, {'request_key': uuid4().hex, 'evidence_scope': 'guess'}, content_type='application/json')
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(WorkflowJob.objects.count(), count)
