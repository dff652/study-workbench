from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
from unittest.mock import patch
from uuid import uuid4
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import Client, TransactionTestCase
from PIL import Image

from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.solutions import bridge, jobs, queries, rendering, services
from app.solutions.models import SolutionAsset, SolutionConfirmation, SolutionOutput, SolutionRevision
from app.web import services as materials
from tests.study import test_services as fixtures


def key():
    return uuid4().hex


def png(size=(120, 80), color=(230, 234, 239)):
    stream = BytesIO()
    Image.new('RGB', size, color).save(stream, format='PNG')
    return stream.getvalue()


class SolutionTests(TransactionTestCase):
    setUp = fixtures.StudyServiceTests.setUp
    create_observation = fixtures.StudyServiceTests.create_observation

    def content(self):
        return {'schema_version': 'swb.solution.v1', 'title': '匿名解析样本',
            'lectures': [{'id': 'lecture-1', 'title': '乘法与单位'}],
            'questions': [{
                'id': 'question-1', 'question_revision_id': self.question_revision_id,
                'lecture_id': 'lecture-1', 'number': '1', 'title': '第 1 题：乘法核对',
                'statement': {'text': '每段长 4 厘米，共有 2 段。', 'status': 'complete'},
                'sources': [{'page_id': self.page_id, 'region': [8, 8, 100, 70]}],
                'parts': [{'id': 'part-1', 'parent_id': None, 'label': '（1）',
                           'statement': '求总长度。', 'answer': '8', 'unit': '厘米'}],
                'thinking': '先找每段长度和段数。', 'lecture_method': '用相同加数的和表示乘法。',
                'alternative_method': '', 'steps': ['把两段相加：4 + 4。'],
                'pitfalls': ['答案应注明长度单位。'], 'formulas': ['4*2', '1/2+1/2'],
                'figures': [], 'links': [], 'corrections': [], 'unknowns': [],
            }], 'outputs': {'per_question': ['pdf', 'docx'], 'per_lecture': ['pdf', 'docx'], 'combined': ['pdf', 'docx']}}

    def save(self, content=None, version=0, request_key=None):
        return services.save(self.owner, self.material.pk, content=content or self.content(),
            expected_version=version, request_key=request_key or key(), reason='合成内容保存')

    def queue(self, revision):
        result = services.action(self.owner, self.material.pk, action='generate', expected_version=revision.version,
                                 request_key=key(), reason='合成生成')
        return SolutionOutput.objects.get(pk=result['output_id'])

    def test_append_only_drafts_replay_conflict_and_confirmation_do_not_create_attempts(self):
        before = EntityRecord.objects.count()
        request = key()
        first = self.save(request_key=request)
        self.assertEqual(self.save(request_key=request).pk, first.pk)
        edited = self.content(); edited['questions'][0]['thinking'] = '补充第一步。'
        second = self.save(edited, 1)
        self.assertEqual(second.version, 2)
        self.assertEqual(self.save(request_key=request).pk, first.pk)
        with self.assertRaises(core.PersistenceError) as stale:
            self.save(edited, 1)
        self.assertEqual(stale.exception.code, 'stale_solution')
        with self.assertRaises(core.PersistenceError) as conflict:
            self.save(edited, 0, request)
        self.assertEqual(conflict.exception.code, 'request_conflict')
        confirm_key = key()
        for _ in range(2):
            services.action(self.owner, self.material.pk, action='confirm', expected_version=2,
                            request_key=confirm_key, reason='合成原图核对')
        self.assertEqual(SolutionConfirmation.objects.count(), 1)
        self.assertEqual(EntityRecord.objects.count(), before)
        self.assertFalse(first.confirmations.exists())
        self.assertTrue(second.confirmations.exists())
        with self.assertRaises(DatabaseError), transaction.atomic():
            SolutionRevision.objects.filter(pk=first.pk).update(reason='改写历史')
        first.refresh_from_db()
        self.assertEqual(first.content['questions'][0]['thinking'], '先找每段长度和段数。')

    def test_source_order_hierarchy_unknowns_and_correction_types_survive_bridge(self):
        upload = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile('second.png', png(color=(200, 225, 220)), content_type='image/png'), key())
        content = self.content(); question = content['questions'][0]
        question['sources'].append({'page_id': upload['page_id'], 'region': None})
        question['parts'].insert(0, {'id': 'container', 'parent_id': None, 'label': '大问', 'statement': '先读图。', 'answer': None, 'unit': None})
        question['parts'][1]['parent_id'] = 'container'
        question['parts'][1]['unit'] = None
        question['corrections'] = [{'kind': kind, 'original': '旧文字', 'replacement': '新文字', 'basis': '合成原图依据'}
                                   for kind in ('printing_error', 'naming', 'draft_correction')]
        saved = self.save(content)
        result = bridge.companion_content(saved, {})
        target = result['questions'][0]
        self.assertEqual([item['sequence'] for item in target['source_refs']], [1, 2])
        self.assertIsNone(target['source_refs'][1]['region'])
        self.assertEqual(target['parts'][1]['parent_id'], 'container')
        self.assertIsNone(target['parts'][1]['unit'])
        self.assertTrue(any('单位待确认' in value for value in target['unknowns']))
        self.assertEqual([item['kind'] for item in target['corrections']], ['printing_error', 'naming', 'draft_correction'])
        self.assertTrue(all(plan['document'].purpose == 'parent_answers' for plan in bridge.model.compile_documents(result)))

    def test_validation_rejects_cycles_wrong_scope_and_unchecked_asset_claim(self):
        for mutate in (
            lambda q: q['parts'][0].update(parent_id='part-1'),
            lambda q: q['sources'][0].update(page_id=str(uuid4())),
            lambda q: q['sources'][0].update(region=[0, 0, 121, 80]),
            lambda q: q['links'].append({'revision_id': self.question_revision_id, 'relation': 'primary_method'}),
            lambda q: q['figures'].append({'asset_id': str(uuid4()), 'role': 'question', 'caption': '来源不明图', 'width_mm': 50}),
        ):
            content = self.content(); mutate(content['questions'][0])
            with self.assertRaises(core.PersistenceError): self.save(content)
        self.assertFalse(SolutionRevision.objects.exists())
        with self.assertRaises(core.PersistenceError):
            services.save(self.viewer, self.material.pk, content=self.content(), expected_version=0, request_key=key(), reason='只读不能写')
        with self.assertRaises(core.PersistenceError):
            services.material(self.other, self.material.pk)

    def test_png_upload_pixel_binding_replay_and_immutability(self):
        source = {'page_id': self.page_id, 'region': [8, 8, 100, 70]}
        request = key()
        def upload(raw, request_key=request, kind='source_crop', ref=source):
            return services.upload_asset(self.owner, self.material.pk,
                SimpleUploadedFile('figure.png', raw, content_type='image/png'), kind=kind,
                label='题面图', basis='从合成原图取出', source=ref, request_key=request_key)
        first = upload(png(size=(92, 62)))
        self.assertEqual(upload(png(size=(92, 62))).pk, first.pk)
        with self.assertRaises(core.PersistenceError): upload(png(size=(92, 62), color=(255, 0, 0)), key())
        auxiliary = upload(png(size=(80, 60), color=(255, 0, 0)), key(), 'auxiliary', None)
        self.assertIsNone(auxiliary.source)
        self.assertEqual(SolutionAsset.objects.count(), 2)
        with self.assertRaises(DatabaseError), transaction.atomic():
            SolutionAsset.objects.filter(pk=first.pk).update(basis='换依据')

    def test_cancelled_claim_stays_cancelled_and_failed_job_can_retry(self):
        saved = self.save(); output = self.queue(saved)
        def cancelled(claimed, assets):
            jobs.action(self.owner, claimed.pk, action='cancel', expected_version=claimed.version,
                        request_key=key(), reason='合成取消')
            return {'documents': [], 'recipe_sha256': 'a' * 64}
        with patch('app.solutions.rendering.render', side_effect=cancelled):
            result = jobs.execute_next()
        self.assertEqual(result.state, 'cancelled')
        self.assertEqual(result.result, {})
        second = self.queue(saved)
        with patch('app.solutions.rendering.render', side_effect=RuntimeError('synthetic')):
            failed = jobs.execute_next()
        self.assertEqual(failed.pk, second.pk)
        self.assertEqual(failed.state, 'failed')
        request = key()
        retried = jobs.action(self.owner, failed.pk, action='retry', expected_version=failed.version,
                             request_key=request, reason='合成重试')
        replay = jobs.action(self.owner, failed.pk, action='retry', expected_version=failed.version,
                             request_key=request, reason='合成重试')
        self.assertEqual(retried.version, replay.version)
        self.assertEqual(replay.state, 'queued')

    def test_source_derivation_preserves_transparency_pixels_replay_and_original(self):
        raw = BytesIO()
        original = Image.new('RGBA', (12, 12), (30, 60, 120, 128))
        original.putpixel((0, 0), (12, 24, 36, 0))
        original.save(raw, format='PNG')
        original_bytes = raw.getvalue()
        page = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile('transparent.png', original_bytes, content_type='image/png'), key())
        client = Client(enforce_csrf_checks=True)
        url = f'/api/v1/materials/{self.material.pk}/solutions/source-assets/'
        payload = {'kind': 'source_image', 'label': '透明来源', 'basis': '按原图取出',
                   'source': {'page_id': page['page_id'], 'region': None}, 'request_key': key()}
        self.assertEqual(client.get(url).status_code, 401)
        client.force_login(self.owner)
        self.assertEqual(client.post(url, payload, content_type='application/json').status_code, 403)
        csrf = client.get('/api/v1/session/').json()['csrf_token']
        for region in (None, [0, 0, 6, 7]):
            payload['kind'] = 'source_image' if region is None else 'source_crop'
            payload['source']['region'] = region
            payload['request_key'] = key()
            saved = client.post(url, payload, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
            self.assertEqual(saved.status_code, 200, saved.content)
            count = SolutionAsset.objects.count()
            replay = client.post(url, payload, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(SolutionAsset.objects.count(), count)
            asset = SolutionAsset.objects.get(request_key=payload['request_key'])
            with Image.open(materials.asset_path(asset.storage_key, asset.sha256)) as generated:
                expected = original if region is None else original.crop(region)
                self.assertEqual(generated.convert('RGBA').tobytes(), expected.tobytes())
                self.assertEqual(generated.size, expected.size)
        stored_original = services.inputs(self.material)[0][page['page_id']].image
        self.assertEqual(materials.asset_path(stored_original.payload['storage_key'], stored_original.sha256).read_bytes(), original_bytes)
        for actor in (self.viewer, self.other):
            client.force_login(actor)
            csrf = client.get('/api/v1/session/').json()['csrf_token']
            self.assertEqual(client.post(url, payload, content_type='application/json', HTTP_X_CSRFTOKEN=csrf).status_code, 404)
        client.force_login(self.owner)
        csrf = client.get('/api/v1/session/').json()['csrf_token']
        payload['kind'] = 'auxiliary'
        self.assertEqual(client.post(url, payload, content_type='application/json', HTTP_X_CSRFTOKEN=csrf).status_code, 400)
        self.assertEqual(SolutionAsset.objects.count(), 2)
        self.assertFalse(SolutionRevision.objects.exists())

    def test_material_changes_block_old_snapshot_generation(self):
        first = self.save()
        materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile('new.png', png(color=(20, 30, 40)), content_type='image/png'), key())
        with self.assertRaises(core.PersistenceError) as changed: self.queue(first)
        self.assertEqual(changed.exception.code, 'source_changed')
        self.assertFalse(SolutionOutput.objects.exists())

    def test_old_linked_knowledge_keeps_name_version_and_source_navigation(self):
        from app.web import knowledge_services as knowledge
        created = knowledge.save_node(self.owner, self.household.pk, 'knowledge',
            data={'definition': '原版本定义', 'sources': []}, reason='合成原版本', request_key=key())
        node = EntityRecord.objects.get(kind='knowledge', stable_id=created['stable_id'])
        content = self.content()
        content['questions'][0]['links'] = [{'relation':'knowledge', 'revision_id':created['revision_id']}]
        self.save(content)
        knowledge.save_node(self.owner, self.household.pk, 'knowledge', stable_id=node.stable_id,
            expected_context=knowledge.node_detail(self.owner, node.pk)['edit_context'],
            data={'definition': '更新后的定义', 'sources': []}, reason='合成追加修订', request_key=key())
        data = queries.workspace(self.owner, self.material.pk)
        old = next(item for item in data['nodes'] if item['revision_id'] == created['revision_id'])
        self.assertIn('原版本定义', old['label'])
        self.assertIn('第 1 版', old['label'])
        self.assertIn('历史版本', old['label'])
        self.assertIn('#revision-', old['detail_url'])
        self.assertNotIn('更新后的定义', old['label'])
        self.assertEqual(data['revision']['content']['questions'][0]['links'], content['questions'][0]['links'])

    def test_api_csrf_scope_historical_content_and_no_store(self):
        client = Client(enforce_csrf_checks=True)
        url = f'/api/v1/materials/{self.material.pk}/solutions/'
        self.assertEqual(client.get(url).status_code, 401)
        client.force_login(self.owner)
        csrf = client.get('/api/v1/session/').json()['csrf_token']
        self.assertEqual(client.post(url+'draft/', {}, content_type='application/json').status_code, 403)
        value = {'content': self.content(), 'expected_version': 0, 'request_key': key(), 'reason': '合成API保存'}
        saved = client.post(url+'draft/', json.dumps(value), content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertIn('no-store', saved['Cache-Control'])
        revision = saved.json()['revision']
        historic = client.get(f"/api/v1/solutions/revisions/{revision['id']}/")
        self.assertEqual(historic.json()['revision']['content'], value['content'])
        client.force_login(self.other)
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(client.get(f"/api/v1/solutions/revisions/{revision['id']}/").status_code, 404)

    def test_history_and_output_pagination_reach_every_old_record_without_duplicates(self):
        first = self.save()
        # Pagination is a read projection. Seed valid immutable copies without
        # performing 102 unrelated saves; the write guards are tested above.
        SolutionRevision.objects.bulk_create([SolutionRevision(material=self.material, version=version,
            content=first.content, content_hash=first.content_hash, sources=first.sources,
            source_stamp=first.source_stamp, request_key=key(), fingerprint=first.fingerprint,
            author=self.owner, reason='合成历史页') for version in range(2, 104)])
        newest = services.latest(self.material)
        for _ in range(51):
            self.queue(newest)
        current = queries.workspace(self.owner, self.material.pk)
        self.assertEqual(len(current['history']), 100)
        older = queries.history_page(self.viewer, self.material.pk, current['history_next_before'])
        versions = [item['version'] for item in current['history'] + older['history']]
        self.assertEqual(versions, list(range(103, 0, -1)))
        self.assertIsNone(older['history_next_before'])
        previous_outputs = queries.outputs_page(self.viewer, self.material.pk, current['output_next_before'])
        ids = [item['id'] for item in current['outputs'] + previous_outputs['outputs']]
        self.assertEqual(len(ids), 51)
        self.assertEqual(len(set(ids)), 51)
        self.assertIsNone(previous_outputs['output_next_before'])
        client = Client(); client.force_login(self.owner)
        prefix = f'/api/v1/materials/{self.material.pk}/solutions/'
        self.assertEqual(client.get(prefix + 'history/?before=invalid').status_code, 400)
        self.assertEqual(client.get(prefix + f'outputs/?before={uuid4()}').status_code, 404)
        old_output = previous_outputs['outputs'][0]
        detail_url = f'/api/v1/solutions/outputs/{old_output["id"]}/'
        cancelled = client.post(detail_url + 'actions/', {
            'action': 'cancel', 'expected_version': old_output['version'],
            'request_key': key(), 'reason': '取消更早页的合成任务'}, content_type='application/json')
        self.assertEqual(cancelled.status_code, 200, cancelled.content)
        updated = next(item for item in cancelled.json()['outputs'] if item['id'] == old_output['id'])
        self.assertEqual(updated['state'], 'cancelled')
        client.force_login(self.viewer)
        old_detail = client.get(detail_url)
        self.assertEqual(old_detail.status_code, 200)
        self.assertEqual(old_detail.json()['output']['state'], 'cancelled')
        self.assertIn('no-store', old_detail['Cache-Control'])
        client.force_login(self.other)
        self.assertEqual(client.get(prefix + 'history/?before=4').status_code, 404)
        self.assertEqual(client.get(prefix + 'outputs/').status_code, 404)
        self.assertEqual(client.get(detail_url).status_code, 404)
        client.logout()
        self.assertEqual(client.get(detail_url).status_code, 401)

    def test_formula_preview_is_authenticated_csrf_checked_and_does_not_write_evidence(self):
        client = Client(enforce_csrf_checks=True)
        url = '/api/v1/solutions/formula-preview/'
        self.assertEqual(client.get(url).status_code, 401)
        client.force_login(self.viewer)
        self.assertEqual(client.post(url, {'expression':'1/2'}, content_type='application/json').status_code, 403)
        csrf = client.get('/api/v1/session/').json()['csrf_token']
        before = EntityRecord.objects.count()
        valid = client.post(url, {'expression':'1/2'}, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.json()['formula'], ['f', ['t','1'], ['t','2']])
        self.assertIn('no-store', valid['Cache-Control'])
        invalid = client.post(url, {'expression':'open("file")'}, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()['error']['code'], 'invalid_solution')
        for payload in ({}, {'expression': None}, {'expression': 12}):
            with self.subTest(payload=payload):
                missing = client.post(url, payload, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
                self.assertEqual(missing.status_code, 400)
                self.assertEqual(missing.json()['error']['code'], 'invalid_solution')
        self.assertEqual(EntityRecord.objects.count(), before)
        self.assertFalse(SolutionRevision.objects.exists())

    def test_real_pdf_word_organizations_previews_and_independent_checks(self):
        second_page = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile('page-two.png', png(color=(250, 238, 221)), content_type='image/png'), key())
        crop = services.upload_asset(self.owner, self.material.pk,
            SimpleUploadedFile('crop.png', png(size=(92, 62)), content_type='image/png'), kind='source_crop',
            label='题面区域', basis='合成原图裁切', source={'page_id': self.page_id, 'region': [8, 8, 100, 70]}, request_key=key())
        content = self.content(); content['lectures'].append({'id': 'lecture-2', 'title': '待补图形题'})
        question = content['questions'][0]
        question['sources'].append({'page_id': second_page['page_id'], 'region': None})
        question['figures'] = [{'asset_id': str(crop.pk), 'role': 'question', 'caption': '已选题面区域', 'width_mm': 50}]
        question['corrections'] = [{'kind': 'printing_error', 'original': '厘来', 'replacement': '厘米', 'basis': '合成题目原图文字'}]
        other = deepcopy(question)
        other.update(id='question-2', lecture_id='lecture-2', number='2', title='第 2 题：保留未知', question_revision_id=None)
        other['parts'] = [{'id': 'part-2', 'parent_id': None, 'label': '（1）', 'statement': '补充单位后求解。', 'answer': None, 'unit': None}]
        other['unknowns'] = ['原图此处单位不清楚']
        other['figures'] = []
        content['questions'].append(other)
        saved = self.save(content); output = self.queue(saved)
        row = jobs.execute_next()
        self.assertEqual(row.pk, output.pk)
        self.assertEqual(row.state, 'output_check', row.error_code)
        generated = row.result
        self.assertEqual(len(generated['documents']), 5)
        question_docs = {item['question_ids'][0]: item for item in generated['documents'] if item['organization']=='per_question'}
        self.assertEqual(sum(item['page_count'] for item in question_docs.values()),
            len([qid for item in generated['documents'] if item['organization']=='combined' for qid in item['page_questions'] if qid]))
        for document in generated['documents']:
            self.assertEqual(len(document['previews']), document['page_count'])
            for name in ('document.pdf', 'document.docx', *document['previews']):
                self.assertTrue(rendering.output_file(row, document['id'], name).is_file())
        self.client.force_login(self.viewer)
        file_url = f"/api/v1/solutions/outputs/{row.pk}/files/{generated['documents'][0]['id']}/document.pdf/"
        response = self.client.get(file_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Frame-Options'], 'SAMEORIGIN')
        response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(file_url).status_code, 404)
        with zipfile.ZipFile(rendering.archive(row)) as archive:
            self.assertEqual(len([name for name in archive.namelist() if name.endswith('.docx')]), 5)
            self.assertFalse(any('original' in name or name.endswith('.png') for name in archive.namelist()))
            checks = json.loads(archive.read('checks.json'))['checks']
            self.assertEqual(checks['word_pc']['status'], 'not_tested')
        if os.environ.get('SWB_SOLUTION_TEST_EVIDENCE'):
            from django.conf import settings
            target = Path(os.environ['SWB_SOLUTION_TEST_EVIDENCE']) / output.pk.hex
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = Path(settings.SWB_DATA_ROOT) / 'solutions' / 'outputs' / output.pk.hex
            shutil.copytree(source, target)
        checks = queries.default_checks()
        for name in ('content', 'math', 'pdf_visual'):
            checks[name] = {'status': 'pass', 'notes': '合成状态机测试，非真实人工签收'}
        checked = jobs.action(self.owner, row.pk, action='check', expected_version=row.version,
            request_key=key(), reason='合成检查独立状态', checks=checks)
        self.assertEqual(checked.state, 'complete')
        self.assertEqual(checked.result['checks']['word_pc']['status'], 'not_tested')
        checks['pdf_visual'] = {'status': 'fail', 'notes': '合成退回'}
        failed = jobs.action(self.owner, row.pk, action='check', expected_version=checked.version,
            request_key=key(), reason='合成退回', checks=checks)
        with self.assertRaises(Exception): rendering.archive(failed)
