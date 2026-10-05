from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import os
import shutil
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase
from PIL import Image

from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.solutions import bridge, jobs, queries, rendering, services
from app.solutions.models import SolutionOutput, SolutionRevision
from app.web import services as materials
from tests.solutions import test_workflow as fixtures

key = fixtures.key


class StructuredSolutionTests(TransactionTestCase):
    setUp = fixtures.SolutionTests.setUp
    create_observation = fixtures.SolutionTests.create_observation
    content = fixtures.SolutionTests.content
    save = fixtures.SolutionTests.save
    queue = fixtures.SolutionTests.queue

    def structured(self):
        content = self.content()
        content['schema_version'] = 'swb.solution.v2'
        question = content['questions'][0]
        question['steps'] = [
            {'id': 'step-one', 'text': '先通分，再把分子相加。', 'formula': '1/3+1/6', 'figure': None, 'new_page': False},
            {'id': 'step-two', 'text': '分页后的核对步骤。', 'formula': '4*2', 'figure': None, 'new_page': True},
        ]
        question['alternative_steps'] = [
            {'id': 'alternative-one', 'text': '也可以先用相同加数求和。', 'formula': '4+4', 'figure': None, 'new_page': False}]
        return content

    def test_structured_order_page_break_and_legacy_history(self):
        old = self.save()
        old_bytes, old_hash = deepcopy(old.content), old.content_hash
        current = self.save(self.structured(), version=1)
        compiled = bridge.companion_content(current, {})['questions'][0]['pages']
        self.assertEqual(len(compiled), 2)
        self.assertTrue(any('先通分' in str(block['content']) for block in compiled[0]))
        self.assertIn('分页后的核对步骤', compiled[1][0]['content'])
        self.assertEqual(compiled[1][1]['kind'], 'math')
        self.assertTrue(any('其他解法' in str(block['content']) for block in compiled[1]))
        old.refresh_from_db()
        self.assertEqual((old.content, old.content_hash), (old_bytes, old_hash))
        self.assertEqual(bridge.companion_content(old, {})['questions'][0]['pages'][0][0]['kind'], 'title')
        self.assertEqual(queries.revision_row(old)['content']['schema_version'], 'swb.solution.v1')

    def test_closed_steps_reject_duplicates_wrong_types_and_foreign_assets(self):
        for mutation in (
            lambda q: q['alternative_steps'][0].update(id='step-one'),
            lambda q: q['steps'][0].update(new_page=1),
            lambda q: q['steps'][0].update(formula='open("secret")'),
            lambda q: q['steps'][0].update(figure={'asset_id': 'foreign', 'role': 'method', 'caption': '', 'width_mm': 60}),
            lambda q: q['steps'][0].update(unknown_field='discarding this is forbidden'),
        ):
            content = self.structured()
            mutation(content['questions'][0])
            with self.subTest(content=content), self.assertRaises(core.PersistenceError):
                self.save(content)
        self.assertFalse(SolutionRevision.objects.exists())

    def test_historical_links_remain_readable_but_cannot_confirm_or_generate(self):
        saved = self.save(self.structured())
        before = EntityRecord.objects.count()
        entity = EntityRecord.objects.get(stable_id=self.question_id, kind='question')
        entity.published_revision = None
        entity.save(update_fields=['published_revision'])
        self.assertFalse(queries.workspace(self.owner, self.material.pk)['questions'])
        self.assertEqual(queries.revision_row(saved)['content'], saved.content)
        # Saving a comparison is allowed, but obtaining a fresh stamp must not bypass publication checks.
        copied = self.save(self.structured(), version=1)
        for action in ('confirm', 'generate'):
            with self.subTest(action=action), self.assertRaises(core.PersistenceError) as failure:
                services.action(self.owner, self.material.pk, action=action, expected_version=copied.version,
                                request_key=key(), reason='不能把历史当作当前依据')
            self.assertEqual(failure.exception.code, 'source_changed')
        self.assertFalse(SolutionOutput.objects.exists())
        self.assertEqual(EntityRecord.objects.count(), before)

    def test_withdrawal_after_queue_is_checked_before_render(self):
        saved = self.save(self.structured())
        output = self.queue(saved)
        EntityRecord.objects.filter(stable_id=self.question_id, kind='question').update(published_revision=None)
        with patch('app.solutions.rendering.render') as render:
            result = jobs.execute_next()
        render.assert_not_called()
        self.assertEqual((result.pk, result.state, result.error_code), (output.pk, 'failed', 'source_changed'))

    def test_withdrawal_during_render_cannot_publish_a_successful_result(self):
        output = self.queue(self.save(self.structured()))

        def withdraw(*_args):
            EntityRecord.objects.filter(stable_id=self.question_id, kind='question').update(published_revision=None)
            return {'recipe_sha256': 'synthetic-recipe', 'documents': []}

        with patch('app.solutions.rendering.render', side_effect=withdraw):
            result = jobs.execute_next()
        self.assertEqual((result.pk, result.state, result.error_code), (output.pk, 'failed', 'source_changed'))
        self.assertEqual(result.result, {})

    def test_real_structured_render_keeps_transparent_source_and_breaks(self):
        image = Image.new('RGBA', (80, 60), (70, 130, 190, 80))
        image.putpixel((12, 12), (255, 70, 0, 0))
        stream = BytesIO()
        image.save(stream, format='PNG')
        raw = stream.getvalue()
        uploaded = materials.upload_page(self.owner, self.material.pk,
            SimpleUploadedFile('transparent.png', raw, content_type='image/png'), key())
        source = {'page_id': uploaded['page_id'], 'region': [5, 5, 65, 45]}
        asset = services.derive_asset(self.owner, self.material.pk, kind='source_crop', label='透明原图区域',
            basis='只裁切，不改变透明像素', source=source, request_key=key())
        content = self.structured()
        question = content['questions'][0]
        content['title'] = '匿名分数加法解析'
        content['lectures'][0]['title'] = '分数加法'
        question.update(question_revision_id=None, title='两段彩带一共多长？',
            statement={'text': '一段彩带长 1/3 米，另一段长 1/6 米，一共多长？', 'status': 'complete'},
            thinking='先统一每份的大小，再把份数相加。', lecture_method='通分后相加，最后约分。',
            formulas=[], pitfalls=['不能把分母直接相加。'])
        question['parts'][0].update(statement='求总长度。', answer='1/2', unit='米')
        question['steps'][0].update(text='把三分之一米改写成六分之二米，再加上六分之一米。', formula='2/6+1/6')
        question['steps'][1].update(text='得到六分之三米，约分后是二分之一米。', formula='3/6')
        question['alternative_steps'][0].update(text='也可以通分成十二分之四与十二分之二，相加后约分。', formula='4/12+2/12')
        question['sources'].append(source)
        question['steps'][0]['figure'] = {'asset_id': str(asset.pk), 'role': 'method', 'caption': '原图裁切', 'width_mm': 45}
        saved = self.save(content)
        without_step_asset = deepcopy(content)
        without_step_asset['questions'][0]['steps'][0]['figure'] = None
        self.assertNotEqual(saved.source_stamp, services.stamp(self.material, without_step_asset))
        output = self.queue(saved)
        result = jobs.execute_next()
        self.assertEqual(result.state, 'output_check', result.error_code)
        for document in result.result['documents']:
            self.assertGreaterEqual(document['page_count'], 2)
            self.assertEqual(len(document['previews']), document['page_count'])
            for suffix in ('pdf', 'docx'):
                self.assertTrue(rendering.output_file(result, document['id'], f'document.{suffix}').is_file())
        page = services.inputs(self.material)[0][uploaded['page_id']]
        self.assertEqual(materials.asset_path(page.image.payload['storage_key'], page.image.sha256).read_bytes(), raw)
        with Image.open(materials.asset_path(asset.storage_key, asset.sha256)) as cropped:
            self.assertEqual(cropped.convert('RGBA').tobytes(), image.crop(source['region']).tobytes())
        evidence = os.environ.get('SWB_SOLUTION_TEST_EVIDENCE')
        if evidence:
            destination = Path(evidence) / ('structured-' + output.pk.hex)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copytree(Path(settings.SWB_DATA_ROOT) / 'solutions' / 'outputs' / output.pk.hex, destination)
            (destination / 'result.json').write_text(json.dumps(result.result, ensure_ascii=False, indent=2))
            for path in destination.rglob('*'):
                path.chmod(0o700 if path.is_dir() else 0o600)
