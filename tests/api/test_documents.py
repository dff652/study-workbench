"""Catalogue regressions use owned synthetic metadata, never real exports."""
from unittest.mock import patch
from datetime import datetime, timezone
from django.test import Client, TransactionTestCase
from django.urls import reverse
from app.printing.models import ExportSnapshot
from app.solutions.models import SolutionRevision, SolutionOutput
from app.operations.models import ExportRetirementRecord
from tests.study import test_services as fixtures


class DocumentCatalogueTests(TransactionTestCase):
    create_observation = fixtures.StudyServiceTests.create_observation
    setUp = fixtures.StudyServiceTests.setUp

    def snapshot(self, title='刚生成的练习', purpose='independent_practice'):
        return ExportSnapshot.objects.create(household=self.household, export_id=fixtures.key(), purpose=purpose,
            title=title, storage_key='synthetic/metadata-only', manifest_sha256='0' * 64,
            provenance={}, created_by=self.owner)

    def output(self, mode='knowledge', state='output_check'):
        revision = SolutionRevision.objects.create(material=self.material, mode=mode,
            version=1, content={'schema_version': 'swb.knowledge.v1' if mode == 'knowledge' else 'swb.solution.v3'}, content_hash='0'*64, sources={}, source_stamp='0'*64,
            request_key=fixtures.key(), fingerprint='0'*64, author=self.owner, reason='合成成果检索')
        return SolutionOutput.objects.create(revision=revision, requested_by=self.owner,
            request_key=fixtures.key(), fingerprint='0'*64, state=state, result={'documents': [{
                'id': 'one', 'title': '分数知识讲解', 'organization': 'combined', 'page_count': 1,
                'formats': ['pdf', 'docx'], 'previews': ['page-1.png']}]})

    def get(self, client, **params):
        return client.get('/api/v1/documents/', {'household': self.household.pk, **params})

    def test_default_merges_all_types_before_paging_and_uses_typed_ids(self):
        with patch('django.utils.timezone.now', return_value=datetime(2026,10,1,tzinfo=timezone.utc)):
            self.output()
        with patch('django.utils.timezone.now', return_value=datetime(2026,10,2,tzinfo=timezone.utc)):
            first = self.snapshot()
        with patch('django.utils.timezone.now', return_value=datetime(2026,10,3,tzinfo=timezone.utc)):
            newest = self.output('solution')
        client = Client(); client.force_login(self.viewer)
        pages = [self.get(client, page=i, page_size=1).json() for i in (1,2,3)]
        self.assertEqual([p['items'][0]['category'] for p in pages], ['solution','practice','knowledge'])
        self.assertEqual(pages[0]['items'][0]['id'], 'output:'+str(newest.pk))
        self.assertEqual(pages[1]['items'][0]['id'], 'snapshot:'+str(first.pk))
        self.assertEqual(len({p['items'][0]['id'] for p in pages}), 3)
        self.assertEqual((pages[0]['total'], pages[2]['has_next']), (3,False))
        self.assertIn('no-store', self.get(client)['Cache-Control'])

    def test_search_includes_snapshot_and_output_titles_with_explicit_categories(self):
        self.snapshot('分数练习'); self.output()
        client = Client(); client.force_login(self.owner)
        self.assertEqual(self.get(client,q='分数').json()['total'],2)
        self.assertEqual(self.get(client,q='分数',category='practice').json()['items'][0]['category'],'practice')
        self.assertEqual(self.get(client,category='knowledge').json()['total'],1)
        self.assertEqual(self.get(client,q='完全不存在').json()['total'],0)
        for params in ({'page':0},{'page_size':101},{'category':'invalid'}):
            self.assertEqual(self.get(client,**params).status_code,400)

    def test_roles_and_direct_household_access_are_enforced_without_writes(self):
        self.snapshot(); self.output()
        client=Client()
        self.assertEqual(self.get(client).status_code,401)
        client.force_login(self.other)
        self.assertEqual(self.get(client).status_code,404)
        for actor in (self.viewer,self.owner):
            client.force_login(actor)
            self.assertEqual(self.get(client).json()['total'],2)
            self.assertEqual(client.post('/api/v1/documents/',{}).status_code,405)
        self.assertEqual((ExportSnapshot.objects.count(), SolutionOutput.objects.count()),(1,1))

    def test_failed_outputs_have_status_and_no_download_links(self):
        self.output(state='failed')
        client=Client();client.force_login(self.owner)
        row=self.get(client).json()['items'][0]
        self.assertEqual(row['documents'],[])
        self.assertIsNone(row['zip_url'])
        self.assertEqual(row['state_label'],'生成未完成')

    def test_retirement_is_not_hidden_or_offered_as_download(self):
        row=self.snapshot()
        # The read adapter only consumes the existing ledger, never changes it.
        with patch('app.api.documents.ExportRetirementRecord.objects.filter') as retired:
            retired.return_value.values_list.return_value=[row.pk]
            client=Client();client.force_login(self.owner)
            value=self.get(client).json()['items'][0]
        self.assertEqual(value['state_label'],'已退役，保留历史')
        self.assertEqual(value['documents'],[])
        self.assertEqual(value['detail_url'],reverse('printing:snapshot',args=[row.pk]))
