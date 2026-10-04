import base64
import os
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TransactionTestCase

from app.exports.contracts import digest, ExportError
from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.printing.models import TeachingDiagramRevision
from app.workflows import services as workflows
from app.workflows.assets import validate_records
from tests.printing.test_diagrams import diagram_uploads
from tests.study.test_services import key
from tests.workflows import test_services as workflow_fixtures


def with_diagram(proposal):
    result = deepcopy(proposal)
    result['schema_version'] = 'swb.skill-import.v2'
    uploads = diagram_uploads()
    result['assets'] = {name: {'sha256': digest(raw), 'base64': base64.b64encode(raw).decode(), 'media_type': media}
        for name, raw, media in [('figure.png', uploads['png_upload'].read(), 'image/png'),
                                 ('figure.svg', uploads['vector_upload'].read(), 'image/svg+xml')]}
    result['records'].append({'id': 'diagram', 'kind': 'diagram', 'data': {
        'question': 'q', 'placement': 'question', 'png_asset': 'figure.png', 'vector_asset': 'figure.svg',
        'source': result['records'][0]['data']['sources'][0], 'alt': '合成三角形 ABC', 'conditions': ['AB=AC'],
        'width_points': 250, 'min_label_points': 12, 'independent_safe': True, 'basis': '合成构造逐项核对'}})
    return result


class AssetExchangeTests(TransactionTestCase):
    setUp = workflow_fixtures.WorkflowTests.setUp
    create_observation = workflow_fixtures.WorkflowTests.create_observation
    proposal = workflow_fixtures.WorkflowTests.proposal
    do = workflow_fixtures.WorkflowTests.do

    def test_pending_png_preview_has_exact_bytes_and_household_scope(self):
        value = with_diagram(self.proposal())
        job = workflows.create(self.owner, self.material.pk, request_key=key(), proposal=value)
        client = Client()
        detail_url = f'/api/v1/workflows/{job.pk}/'
        self.assertEqual(client.get(detail_url).status_code, 401)
        client.force_login(self.owner)
        detail = client.get(detail_url).json()
        self.assertEqual(set(detail['assets']), {'figure.png'})
        url = detail['assets']['figure.png']['preview_url']
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response.content, base64.b64decode(value['assets']['figure.png']['base64']))
        self.assertEqual(client.get(url.replace('figure.png', 'figure.svg')).status_code, 404)
        client.force_login(self.viewer)
        self.assertEqual(client.get(url).status_code, 200)
        client.force_login(self.other)
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(EntityRecord.objects.filter(kind='attempt').count(), 0)

    def test_confirm_replay_exact_native_diagram_source_and_private_bytes(self):
        value = with_diagram(self.proposal())
        job = workflows.create(self.owner, self.material.pk, request_key=key(), proposal=value)
        original = workflows.context(job)
        request = key()
        job = workflows.action(self.owner, job.pk, action='confirm', expected=original, request_key=request, reason='合成逐项核对')
        row = TeachingDiagramRevision.objects.get(pk=job.result['mapping']['diagram']['diagram_id'])
        question = EntityRecord.objects.get(kind='question', stable_id=job.result['mapping']['q']['question_id'])
        self.assertEqual(row.question_revision_id, question.published_revision_id)
        self.assertEqual(row.content['source_ref'], question.published_revision.payload['evidence_refs'][0]['region_revision_id'] + '|' + value['sources'][0]['sha256'])
        self.assertEqual(Path(settings.SWB_DATA_ROOT, row.content['storage_key']).stat().st_mode & 0o777, 0o600)
        replay = workflows.action(self.owner, job.pk, action='confirm', expected=original, request_key=request, reason='合成逐项核对')
        self.assertEqual(replay.pk, job.pk)
        self.assertEqual(TeachingDiagramRevision.objects.count(), 1)
        self.assertFalse(EntityRecord.objects.filter(kind='attempt').exists())

    def test_late_failure_rolls_back_diagram_files_and_all_content(self):
        value = with_diagram(self.proposal())
        value['records'][3]['data']['node'] = 'missing'
        job = workflows.create(self.owner, self.material.pk, request_key=key(), proposal=value)
        before = EntityRecord.objects.count()
        with self.assertRaises(core.PersistenceError):
            self.do(job, 'confirm', reason='失败输入')
        self.assertEqual(EntityRecord.objects.count(), before)
        self.assertFalse(TeachingDiagramRevision.objects.exists())
        self.assertEqual(list(Path(settings.SWB_DATA_ROOT).glob('prints/diagrams/**/*.*')), [])
        self.assertEqual(workflows.detail(self.owner, job.pk).state, 'needs_review')

    def test_commit_failure_also_removes_new_files(self):
        value = with_diagram(self.proposal())
        job = workflows.create(self.owner, self.material.pk, request_key=key(), proposal=value)
        before = EntityRecord.objects.count()
        from django.db import connection, DatabaseError
        with patch.object(connection, 'commit', side_effect=DatabaseError('synthetic commit failure')):
            with self.assertRaises(DatabaseError):
                self.do(job, 'confirm', reason='合成提交失败')
        self.assertEqual(EntityRecord.objects.count(), before)
        self.assertFalse(TeachingDiagramRevision.objects.exists())
        self.assertEqual(list(Path(settings.SWB_DATA_ROOT).glob('prints/diagrams/**/*.*')), [])

    def test_disk_fsync_failure_removes_owned_partial_file(self):
        value = with_diagram(self.proposal())
        job = workflows.create(self.owner, self.material.pk, request_key=key(), proposal=value)
        before = EntityRecord.objects.count()
        actual_fsync, failures = os.fsync, []
        def disk_failure(fd):
            path = Path('/proc/self/fd', str(fd)).readlink()
            if path.is_relative_to(Path(settings.SWB_DATA_ROOT) / 'prints/diagrams'):
                failures.append(path)
                raise OSError('synthetic disk failure')
            return actual_fsync(fd)
        with patch('app.printing.diagram_services.os.fsync', side_effect=disk_failure):
            with self.assertRaises(OSError): self.do(job, 'confirm', reason='磁盘失败')
        self.assertEqual(len(failures), 1)
        self.assertEqual(EntityRecord.objects.count(), before)
        self.assertFalse(TeachingDiagramRevision.objects.exists())
        self.assertEqual(list(Path(settings.SWB_DATA_ROOT).glob('prints/diagrams/**/*.*')), [])

    def test_hash_source_unknown_unused_and_active_svg_rejected_before_creation(self):
        for mutation in ('sha', 'source', 'unused', 'svg', 'hint'):
            value = with_diagram(self.proposal())
            if mutation == 'sha': value['assets']['figure.png']['sha256'] = '0' * 64
            elif mutation == 'source': value['records'][-1]['data']['source'] = {'source_id': 'original', 'bbox': [9, 8, 100, 70]}
            elif mutation == 'unused': value['assets']['unused.png'] = value['assets']['figure.png']
            elif mutation == 'hint': value['records'][-1]['data']['independent_safe'] = False
            else:
                raw = b'<svg xmlns="http://www.w3.org/2000/svg"><script>bad</script></svg>'
                value['assets']['figure.svg'].update(sha256=digest(raw), base64=base64.b64encode(raw).decode())
            with self.subTest(mutation=mutation), self.assertRaises(core.PersistenceError):
                workflows.create(self.owner, self.material.pk, request_key=key(), proposal=value)
        self.assertFalse(TeachingDiagramRevision.objects.exists())

    def test_existing_assets_retained_after_failed_new_batch(self):
        value = with_diagram(self.proposal())
        first = workflows.create(self.owner, self.material.pk, request_key=key(), proposal=value)
        self.do(first, 'confirm', reason='首次核对')
        row = TeachingDiagramRevision.objects.get()
        path = Path(settings.SWB_DATA_ROOT, row.content['storage_key'])
        before = path.read_bytes()
        value['records'][3]['data']['node'] = 'missing'
        second = workflows.create(self.owner, self.material.pk, request_key=key(), proposal=value)
        with self.assertRaises(core.PersistenceError): self.do(second, 'confirm', reason='失败新任务')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(TeachingDiagramRevision.objects.count(), 1)
