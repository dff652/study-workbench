from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from importlib import import_module
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
from threading import Barrier
from unittest.mock import patch
import zipfile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase
from lxml import etree
from PIL import Image

from app.exports.contracts import canonical, digest
from app.exports.fonts import prepare_fonts
from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.printing.services import _font_inputs
from app.solutions import jobs, knowledge_bridge, queries, rendering, services
from app.solutions.models import SolutionConfirmation, SolutionOutput, SolutionRevision
from app.web import knowledge_services, services as materials, subjects
from app.web.models import MaterialClassificationRevision
from tests.solutions import test_workflow as fixtures
from tests.solutions.knowledge_fixtures import knowledge_content, SAMPLES

key = fixtures.key


class KnowledgeCompanionTests(TransactionTestCase):
    setUp = fixtures.SolutionTests.setUp
    create_observation = fixtures.SolutionTests.create_observation

    def save(self, content=None, version=0, request_key=None):
        return services.save(self.owner, self.material.pk, content=content or knowledge_content(self.page_id),
            expected_version=version, request_key=request_key or key(), reason='匿名知识整理', mode='knowledge')

    def action(self, revision, action='generate', request_key=None):
        return services.action(self.owner, self.material.pk, action=action, expected_version=revision.version,
            request_key=request_key or key(), reason='匿名知识核对', mode='knowledge')

    def queue(self, revision):
        return SolutionOutput.objects.get(pk=self.action(revision)['output_id'])

    def test_separate_mode_versions_and_replays_preserve_legacy_content(self):
        before = EntityRecord.objects.count(); request = key()
        old_content = fixtures.SolutionTests.content(self)
        old = services.save(self.owner, self.material.pk, content=old_content,
            expected_version=0, request_key=request, reason='匿名旧解析')
        original = (deepcopy(old.content), old.content_hash, old.source_stamp, old.created_at)
        first = self.save(request_key=request)
        second = self.save(version=1)
        self.assertEqual((old.version, first.version, second.version), (1, 1, 2))
        self.assertEqual(self.save(request_key=request).pk, first.pk)
        with self.assertRaises(core.PersistenceError) as failure:
            self.save(version=0, request_key=key())
        self.assertEqual(failure.exception.code, 'stale_solution')
        self.assertEqual(queries.workspace(self.owner, self.material.pk)['revision']['id'], old.pk)
        self.assertEqual([r['id'] for r in queries.workspace(self.owner, self.material.pk, 'knowledge')['history']], [second.pk, first.pk])
        old.refresh_from_db()
        self.assertEqual((old.content, old.content_hash, old.source_stamp, old.created_at), original)
        self.assertEqual(EntityRecord.objects.count(), before)
        with self.assertRaises(DatabaseError), transaction.atomic():
            SolutionRevision.objects.filter(pk=first.pk).update(content=old_content)

    def test_closed_schema_rejects_cycles_bad_sources_profiles_and_unknown_fields(self):
        def mutate_dependency(content):
            content['knowledge'][0]['dependencies'] = [content['knowledge'][0]['id']]
        mutations = (
            mutate_dependency,
            lambda c: c['knowledge'][0].update(dependencies=['missing']),
            lambda c: c['knowledge'][0].update(knowledge_revision_id=self.question_revision_id),
            lambda c: c['knowledge'][0]['sources'][0].update(region=[0.5, 0, 50, 40]),
            lambda c: c['knowledge'][0]['sources'][0].update(page_id='foreign-page'),
            lambda c: c['lectures'][0].update(rule_profile='language'),
            lambda c: c['knowledge'][0]['steps'][0].update(new_page=1),
            lambda c: c['knowledge'][0]['steps'][0].update(formula='open("secret")'),
            lambda c: c['knowledge'][0]['steps'][1].update(id=c['knowledge'][0]['steps'][0]['id']),
            lambda c: c.update(unexpected='must not discard'),
        )
        for mutation in mutations:
            content = knowledge_content(self.page_id); mutation(content)
            with self.subTest(mutation=mutation), self.assertRaises(core.PersistenceError):
                self.save(content)
        self.assertFalse(SolutionRevision.objects.exists())

    def test_partial_drafts_remain_readable_but_five_sections_and_full_conclusion_gate_actions(self):
        mutations = (
            lambda c: c['knowledge'][0]['steps'][2].update(text='', formula='4*2'),
            lambda c: c['knowledge'][0]['steps'][3].update(text='结果是偶数。'),
            lambda c: c['knowledge'][0].update(conditions=[]),
            lambda c: c['knowledge'][0].update(sources=[]),
            lambda c: c.update(learner_level=''),
            lambda c: c.update(outputs={name: [] for name in c['outputs']}),
        )
        for version, mutation in enumerate(mutations):
            content = knowledge_content(self.page_id); mutation(content); revision = self.save(content, version)
            for action in ('confirm', 'generate'):
                with self.subTest(version=version, action=action), self.assertRaises(core.PersistenceError) as failure:
                    self.action(revision, action)
                self.assertEqual(failure.exception.code, 'knowledge_incomplete')
            self.assertEqual(queries.revision_row(revision)['content'], content)
        self.assertFalse(SolutionConfirmation.objects.exists()); self.assertFalse(SolutionOutput.objects.exists())
        complete = self.save(version=len(mutations)); confirmation_key = key()
        self.action(complete, 'confirm', confirmation_key); self.action(complete, 'confirm', confirmation_key)
        self.assertEqual(SolutionConfirmation.objects.count(), 1)

    def test_classification_is_manual_append_only_and_native_guards_reject_bypass(self):
        self.assertEqual(subjects.current(self.material), {'subject': 'unknown', 'version': 0})
        request = key()
        first = subjects.save(self.owner, self.material.pk, subject='english', expected_version=0,
            request_key=request, reason='按匿名封面分类')
        self.assertEqual(subjects.save(self.owner, self.material.pk, subject='english', expected_version=0,
            request_key=request, reason='按匿名封面分类').pk, first.pk)
        second = subjects.save(self.owner, self.material.pk, subject='physics', expected_version=1,
            request_key=key(), reason='人工重新核对课程')
        self.assertEqual(second.previous_id, first.pk)
        for actor in (self.viewer, self.other):
            with self.assertRaises(core.PersistenceError):
                subjects.save(actor, self.material.pk, subject='history', expected_version=2, request_key=key(), reason='无权作者')
        for values in ({'version': 4, 'previous': second}, {'version': 3, 'previous': first},
                       {'version': 3, 'previous': second, 'created_by': self.viewer},
                       {'version': 3, 'previous': second, 'subject': 'made-up'},
                       {'version': 3, 'previous': second, 'reason': ' '}):
            fields = {'material': self.material, 'created_by': self.owner, 'subject': 'mathematics',
                'reason': '原生防线反例', 'request_key': key(), 'fingerprint': '0' * 64, **values}
            with self.subTest(values=values), self.assertRaises(DatabaseError), transaction.atomic():
                MaterialClassificationRevision.objects.create(**fields)
        for operation in (lambda: MaterialClassificationRevision.objects.filter(pk=first.pk).update(reason='覆盖'),
                          lambda: MaterialClassificationRevision.objects.filter(pk=first.pk).delete()):
            with self.assertRaises(DatabaseError), transaction.atomic(): operation()
        reverse = import_module('app.web.migrations.0005_materialclassificationrevision').REVERSE
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(reverse)
        self.assertEqual(MaterialClassificationRevision.objects.count(), 2)

    def test_two_database_connections_cannot_append_the_same_version(self):
        for mode in ('classification', 'knowledge'):
            barrier = Barrier(2)
            def append(_):
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    if mode == 'classification':
                        subjects.save(self.owner, self.material.pk, subject='science', expected_version=0, request_key=key(), reason='并发分类')
                    else:
                        self.save()
                    return 'saved'
                except core.PersistenceError as exc:
                    return exc.code
                finally: close_old_connections()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(append, range(2)))
            self.assertCountEqual(results, ['saved', 'stale_subject' if mode == 'classification' else 'stale_solution'])

    def test_subject_filter_uses_actual_material_sources_and_old_content_stays_unclassified(self):
        client = Client(); client.force_login(self.owner)
        url = f'/api/v1/materials/?household_id={self.household.pk}'
        self.assertEqual(client.get(url + '&subject=unknown').json()['items'][0]['id'], str(self.material.pk))
        revision = self.save(); before = deepcopy(revision.content)
        subjects.save(self.owner, self.material.pk, subject='physics', expected_version=0, request_key=key(), reason='匿名物理课程')
        self.assertEqual(client.get(url + '&subject=physics').json()['total'], 1)
        self.assertEqual(client.get(url + '&subject=unknown').json()['total'], 0)
        self.assertEqual(client.get(url + '&subject=made-up').status_code, 400)
        physics = knowledge_services.index_data(self.owner, self.household.pk, {'subject': 'physics'})
        unknown = knowledge_services.index_data(self.owner, self.household.pk, {'subject': 'unknown'})
        self.assertEqual(len(physics['questions']), 1); self.assertEqual(len(unknown['questions']), 0)
        revision.refresh_from_db(); self.assertEqual(revision.content, before)
        self.assertEqual(queries.workspace(self.owner, self.material.pk, 'knowledge')['initial_content']['school_subject'], 'physics')
        with self.assertRaises(core.PersistenceError) as failure: self.action(revision)
        self.assertEqual(failure.exception.code, 'source_changed')

    def test_classification_change_before_or_during_render_cannot_publish(self):
        first = self.queue(self.save())
        subjects.save(self.owner, self.material.pk, subject='physics', expected_version=0, request_key=key(), reason='来源分类变化')
        with patch('app.solutions.rendering.render') as render: failed = jobs.execute_next()
        render.assert_not_called(); self.assertEqual((failed.pk, failed.state, failed.error_code), (first.pk, 'failed', 'source_changed'))
        with self.assertRaises(core.PersistenceError):
            jobs.action(self.owner, first.pk, action='retry', expected_version=failed.version, request_key=key(), reason='旧来源重试')
        second = self.queue(self.save(version=1))
        def change_during_render(*_):
            subjects.save(self.owner, self.material.pk, subject='chemistry', expected_version=1, request_key=key(), reason='生成期间来源变化')
            return {'recipe_sha256': 'synthetic', 'documents': []}
        with patch('app.solutions.rendering.render', side_effect=change_during_render): failed = jobs.execute_next()
        self.assertEqual((failed.pk, failed.state, failed.error_code), (second.pk, 'failed', 'source_changed')); self.assertEqual(failed.result, {})

    def test_current_knowledge_links_are_required_for_confirmation_and_worker_publication(self):
        node = knowledge_services.save_node(self.owner, self.household.pk, 'knowledge',
            data={'definition': '偶整数能够写成二乘整数。', 'conditions': '', 'common_errors': '', 'sources': []},
            request_key=key(), reason='匿名基础知识')
        context = core.review_context(self.owner, self.household.pk, node['revision_id'])
        core.review_revision(self.owner, self.household.pk, node['revision_id'], action='accept',
            expected_head=context['expected_head'], expected_dependencies=context['expected_dependencies'],
            expected_decision_id=context['expected_decision_id'], request_key=key(), reason='人工核对定义')
        content = knowledge_content(self.page_id); content['knowledge'][0]['knowledge_revision_id'] = node['revision_id']
        saved = self.save(content); self.action(saved, 'confirm'); output = self.queue(saved)
        EntityRecord.objects.filter(head_revision_id=node['revision_id']).update(published_revision=None)
        with self.assertRaises(core.PersistenceError): self.action(saved, 'confirm')
        with patch('app.solutions.rendering.render') as render: failed = jobs.execute_next()
        render.assert_not_called(); self.assertEqual((failed.pk, failed.state), (output.pk, 'failed'))
        self.assertEqual(queries.revision_row(saved)['content'], content)

    def test_pinned_vendor_rejects_drift_and_nonempty_mode_reverse_is_blocked(self):
        original = knowledge_bridge.verify_vendor()
        for mutation in (lambda value: value.update(commit='0' * 40),
                         lambda value: value['files'].pop('sources.py'),
                         lambda value: value['files']['knowledge_model.py'].update(adapted_sha256='0' * 64)):
            changed = deepcopy(original); mutation(changed)
            with patch('app.solutions.knowledge_bridge.json.loads', return_value=changed), self.assertRaises(core.PersistenceError) as failure:
                knowledge_bridge.verify_vendor()
            self.assertEqual(failure.exception.code, 'knowledge_tool_changed')
        saved = self.save(); reverse = import_module('app.solutions.migrations.0003_companion_modes').REVERSE
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor: cursor.execute(reverse)
        saved.refresh_from_db(); self.assertEqual(saved.mode, 'knowledge')
        fields = {'material': self.material, 'version': 1, 'mode': 'solution', 'content': saved.content,
            'content_hash': saved.content_hash, 'sources': saved.sources, 'source_stamp': saved.source_stamp,
            'request_key': key(), 'fingerprint': '0' * 64, 'author': self.owner, 'reason': '模式不符'}
        with self.assertRaises(DatabaseError), transaction.atomic(): SolutionRevision.objects.create(**fields)

    def test_api_permissions_csrf_classification_cursor_and_mode_binding(self):
        url = f'/api/v1/materials/{self.material.pk}/knowledge-explanations/'
        anonymous = Client(); self.assertEqual(anonymous.get(url).status_code, 401)
        viewer = Client(); viewer.force_login(self.viewer)
        self.assertFalse(viewer.get(url).json()['writable'])
        payload = {'content': knowledge_content(self.page_id), 'expected_version': 0, 'request_key': key(), 'reason': '匿名接口'}
        self.assertEqual(viewer.post(url + 'draft/', data=json.dumps(payload), content_type='application/json').status_code, 404)
        self.assertFalse(SolutionRevision.objects.exists())
        outsider = Client(); outsider.force_login(self.other); self.assertEqual(outsider.get(url).status_code, 404)
        owner = Client(enforce_csrf_checks=True); owner.force_login(self.owner)
        self.assertEqual(owner.post(url + 'draft/', data=json.dumps(payload), content_type='application/json').status_code, 403)
        token = owner.get('/api/v1/session/').json()['csrf_token']
        saved = owner.post(url + 'draft/', data=json.dumps(payload), content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(saved.status_code, 200); self.assertEqual(saved.json()['revision']['mode'], 'knowledge')
        self.assertEqual(saved.json()['saved_revision']['id'], saved.json()['revision']['id'])
        self.assertEqual(saved.json()['saved_source_stamp'], saved.json()['source_stamp'])
        self.assertEqual(saved.json()['material']['household_id'], str(self.household.pk))
        self.assertEqual(saved.json()['pages'][0]['position'], 1)
        self.assertEqual(len(saved.json()['pages'][0]['sha256']), 64)
        wrong = owner.post(url.replace('knowledge-explanations/', 'solutions/') + 'draft/', data=json.dumps(payload), content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(wrong.status_code, 400)
        first_classification = None
        for version in range(53):
            values = {'subject': 'history' if version % 2 else 'science', 'expected_version': version, 'request_key': key(), 'reason': '匿名分类分页'}
            if version < 2:
                posted = owner.post(f'/api/v1/materials/{self.material.pk}/classification/save/', data=json.dumps(values), content_type='application/json', HTTP_X_CSRFTOKEN=token)
                self.assertEqual(posted.status_code, 200)
                self.assertEqual(posted.json()['saved_classification']['version'], version + 1)
                if version == 0:
                    first_classification = values
            else:
                subjects.save(self.owner, self.material.pk, **values)
        replay = owner.post(f'/api/v1/materials/{self.material.pk}/classification/save/', data=json.dumps(first_classification), content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()['saved_classification'], {'subject': 'science', 'version': 1})
        self.assertEqual(replay.json()['material']['classification']['version'], 53)
        class_url = f'/api/v1/materials/{self.material.pk}/classification/'
        first = owner.get(class_url).json(); self.assertEqual(len(first['history']), 50); self.assertEqual(first['history_next_before'], 4)
        later = owner.get(class_url + '?before=4').json(); self.assertEqual([r['version'] for r in later['history']], [3, 2, 1])
        self.assertIsNone(later['history_next_before']); self.assertEqual(owner.get(class_url + '?before=bad').status_code, 400)

    def test_save_receipt_names_the_saved_revision_even_when_workspace_has_advanced(self):
        client = Client(); client.force_login(self.owner)
        content = knowledge_content(self.page_id)
        payload = {'content': content, 'expected_version': 0, 'request_key': key(), 'reason': '本窗口内容'}
        project = queries.workspace
        def newer_workspace(actor, material_id, mode='solution'):
            version = services.latest(self.material, mode).version
            newer = deepcopy(content); newer['title'] = f'另一窗口版本 {version + 1}'
            services.save(self.owner, self.material.pk, content=newer, expected_version=version,
                request_key=key(), reason='另一窗口输入', mode=mode)
            return project(actor, material_id, mode)
        url = f'/api/v1/materials/{self.material.pk}/knowledge-explanations/draft/'
        with patch('app.api.knowledge_views.queries.workspace', side_effect=newer_workspace):
            for current_version in (2, 3):
                response = client.post(url, data=json.dumps(payload), content_type='application/json')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['saved_revision']['version'], 1)
                self.assertEqual(response.json()['saved_revision']['content'], content)
                self.assertEqual(response.json()['revision']['version'], current_version)
        self.assertEqual(SolutionRevision.objects.count(), 3)

    def test_late_knowledge_worker_cannot_publish_cancelled_or_unauthorized_output(self):
        first = self.queue(self.save())
        def cancel_during_render(claimed, _assets):
            jobs.action(self.owner, claimed.pk, action='cancel', expected_version=claimed.version, request_key=key(), reason='取消匿名生成')
            return {'recipe_sha256': 'synthetic', 'documents': []}
        with patch('app.solutions.rendering.render', side_effect=cancel_during_render): cancelled = jobs.execute_next()
        self.assertEqual((cancelled.pk, cancelled.state, cancelled.result), (first.pk, 'cancelled', {}))
        second = self.queue(self.save(version=1)); self.owner.is_active = False; self.owner.save(update_fields=['is_active'])
        with patch('app.solutions.rendering.render') as render: self.assertIsNone(jobs.execute_next())
        render.assert_not_called(); second.refresh_from_db(); self.assertEqual((second.state, second.error_code), ('failed', 'permission_changed'))

    def test_upgrade_adds_mode_without_rewriting_old_revision_or_creating_classification_history(self):
        executor = MigrationExecutor(connection); targets = executor.loader.graph.leaf_nodes()
        content = fixtures.SolutionTests.content(self)
        manifest, mapping = services.bridge.source_manifest(self.material, content, services.inputs(self.material)[0])
        stamp = services.stamp(self.material, content)
        try:
            executor.migrate([('solutions', '0002_history_guards'), ('workbench_web', '0004_page_reading_revision')])
            old_model = executor.loader.project_state([('solutions', '0002_history_guards')]).apps.get_model('solutions', 'SolutionRevision')
            old = old_model.objects.create(material_id=self.material.pk, version=1, content=content,
                content_hash=digest(canonical(content)), sources={'manifest': manifest, 'page_mapping': mapping},
                source_stamp=stamp, request_key=key(), fingerprint='0' * 64, author_id=self.owner.pk, reason='迁移前匿名记录')
            original = old_model.objects.filter(pk=old.pk).values().get()
        finally:
            MigrationExecutor(connection).migrate(targets)
        upgraded = SolutionRevision.objects.filter(pk=old.pk).values().get()
        self.assertEqual(upgraded.pop('mode'), 'solution'); self.assertEqual(upgraded, original)
        self.assertEqual(subjects.current(self.material), {'subject': 'unknown', 'version': 0})

    def test_single_long_title_keeps_full_heading_and_fits_pdf_and_word_footer(self):
        content = knowledge_content(self.page_id)
        title = ('完整知识名称：' + '依据定义核对条件并说明完整结论的范围' * 10)[:160]
        content['knowledge'][0]['title'] = title
        content['outputs'] = {'inventory': [], 'per_knowledge': ['pdf', 'docx'], 'per_lecture': [], 'combined': []}
        saved = self.save(content)
        self.queue(saved)
        result = jobs.execute_next()
        self.assertEqual(result.state, 'output_check', result.error_code)
        document, = result.result['documents']
        self.assertEqual(document['organization'], 'per_knowledge')
        self.assertTrue(document['title'].endswith('...'))
        self.assertTrue(title.startswith(document['title'][:-3]))
        self.assertEqual(len(document['previews']), document['page_count'])
        with zipfile.ZipFile(rendering.output_file(result, document['id'], 'document.docx')) as archive:
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            body = etree.fromstring(archive.read('word/document.xml'))
            self.assertIn(title, ''.join(body.xpath('//w:t/text()', namespaces=ns)))
            footer = etree.fromstring(archive.read('word/footer1.xml'))
            self.assertIn(document['title'], ''.join(footer.xpath('//w:t/text()', namespaces=ns)))
        evidence = os.environ.get('SWB_SOLUTION_TEST_EVIDENCE')
        if evidence:
            target = Path(evidence) / ('knowledge-long-footer-' + result.pk.hex)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copytree(Path(settings.SWB_DATA_ROOT) / 'solutions' / 'outputs' / result.pk.hex, target)
            (target / 'result.json').write_text(json.dumps(result.result, ensure_ascii=False, indent=2))
            for path in target.rglob('*'): path.chmod(0o700 if path.is_dir() else 0o600)

    def test_long_title_directory_splits_and_uses_actual_body_start_pages(self):
        content = knowledge_content(self.page_id)
        template = content['knowledge'][0]
        content['knowledge'] = []
        content['outputs'] = {'inventory': [], 'per_knowledge': [],
            'per_lecture': ['pdf', 'docx'], 'combined': ['pdf', 'docx']}
        for index in range(1, 13):
            item = deepcopy(template)
            item.update(id=f'knowledge-{index}', order=index,
                title=(f'知识 {index:02}：' + '依据定义核对条件并说明完整结论的范围' * 10)[:160],
                dependencies=['knowledge-1'] if index > 1 else [])
            for step_index, step in enumerate(item['steps']):
                step['id'] = f'knowledge-{index}-step-{step_index}'
            content['knowledge'].append(item)
        saved = self.save(content)
        compiled = knowledge_bridge.companion_content(saved, services.inputs(self.material)[2])
        root = Path(settings.SWB_DATA_ROOT)
        fonts, _ = prepare_fonts([p['document'] for p in knowledge_bridge.plans(compiled, saved)],
            root / 'long-title-fonts', **_font_inputs())
        originals = [knowledge_bridge._native(knowledge_bridge.model._knowledge_document(compiled, item), compiled, saved)
            for item in compiled['knowledge']]
        with patch('app.solutions.knowledge_bridge.paginate', wraps=knowledge_bridge.paginate) as measured:
            plans = knowledge_bridge.plans(compiled, saved, fonts, root)
        for original in originals:
            for page in original.pages:
                self.assertEqual(sum(call.args[0] == list(page) for call in measured.call_args_list), 1)
        bodies, directories = {}, {}
        for plan in plans:
            covers = plan['page_knowledge'].count(None)
            self.assertGreater(covers, 1)
            self.assertEqual(len(plan['page_knowledge']), len(plan['document'].pages))
            rows = [row for page in plan['document'].pages[:covers] for block in page
                if block.kind == 'table' for row in block.content[0][1:]]
            self.assertEqual(len(rows), 12)
            self.assertEqual({row[1]: int(row[2]) for row in rows},
                {item['title']: plan['page_knowledge'].index(item['id']) + 1 for item in content['knowledge']})
            directories[plan['organization']] = rows
            for identifier in plan['knowledge_ids']:
                body = tuple(page for page, mapped in zip(plan['document'].pages, plan['page_knowledge'], strict=True)
                    if mapped == identifier)
                self.assertEqual(body, bodies.setdefault(identifier, body))
        output = self.queue(saved)
        result = jobs.execute_next()
        self.assertEqual(result.state, 'output_check', result.error_code)
        self.assertEqual(len(result.result['documents']), 2)
        for document, plan in zip(result.result['documents'], plans, strict=True):
            self.assertEqual(document['page_count'], len(plan['document'].pages))
            self.assertEqual(len(document['previews']), document['page_count'])
            with zipfile.ZipFile(rendering.output_file(result, document['id'], 'document.docx')) as archive:
                xml = etree.fromstring(archive.read('word/document.xml'))
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                tables = xml.xpath('//w:tbl', namespaces=ns)
                self.assertEqual(len(tables), plan['page_knowledge'].count(None))
                data = [[''.join(cell.xpath('.//w:t/text()', namespaces=ns))
                    for cell in row.xpath('./w:tc', namespaces=ns)]
                    for table in tables for row in table.xpath('./w:tr', namespaces=ns)[1:]]
                self.assertEqual(data, directories[document['organization']])
        evidence = os.environ.get('SWB_SOLUTION_TEST_EVIDENCE')
        if evidence:
            target = Path(evidence) / ('knowledge-long-titles-' + output.pk.hex)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copytree(root / 'solutions' / 'outputs' / output.pk.hex, target)
            (target / 'result.json').write_text(json.dumps(result.result, ensure_ascii=False, indent=2))
            for path in target.rglob('*'): path.chmod(0o700 if path.is_dir() else 0o600)

    def test_real_four_profile_documents_share_measured_bodies_and_preserve_rgba_sources(self):
        before = EntityRecord.objects.count()
        image = Image.new('RGBA', (80, 60), (70, 130, 190, 80)); image.putpixel((12, 12), (255, 70, 0, 0))
        stream = BytesIO(); image.save(stream, format='PNG'); raw = stream.getvalue()
        page = materials.upload_page(self.owner, self.material.pk, SimpleUploadedFile('anonymous-rgba.png', raw, content_type='image/png'), key())['page_id']
        source = {'page_id': page, 'region': [5, 5, 65, 45]}
        asset = services.derive_asset(self.owner, self.material.pk, kind='source_crop', label='匿名来源裁切', basis='保留原图透明像素', source=source, request_key=key())
        content = knowledge_content(page, tuple(SAMPLES)); first = content['knowledge'][0]
        first['id'] = 'knowledge-2444c947956c4d54aa5d93ca02c9028b'
        first['sources'][0]['region'] = source['region']
        first['steps'][2]['formula'] = '2*4+2*6'
        first['steps'][2]['figure'] = {'asset_id': str(asset.pk), 'role': 'method', 'caption': '匿名原图裁切', 'width_mm': 45}
        first['steps'][2]['text'] += '\n' + '分页推导段落。' * 200
        first['definitions'] += '\n单次元数据标记。' + '用于验证元数据与正文共同测量。' * 90
        saved = self.save(content); compiled = knowledge_bridge.companion_content(saved, services.inputs(self.material)[2])
        font_root = Path(settings.SWB_DATA_ROOT) / 'knowledge-test-fonts'
        fonts, _ = prepare_fonts([plan['document'] for plan in knowledge_bridge.plans(compiled, saved)], font_root, **_font_inputs())
        plans = knowledge_bridge.plans(compiled, saved, fonts, Path(settings.SWB_DATA_ROOT))
        individual = {p['knowledge_ids'][0]: p['document'].pages for p in plans if p['organization'] == 'per_knowledge'}
        self.assertGreater(len(individual[first['id']]), 1)
        for plan in plans:
            self.assertEqual(len(plan['page_knowledge']), len(plan['document'].pages))
            if plan['organization'] in ('combined', 'per_lecture'):
                cover_count = plan['page_knowledge'].count(None); position = cover_count + 1
                table_rows = [row for page_blocks in plan['document'].pages[:cover_count] for block in page_blocks if block.kind == 'table' for row in block.content[0][1:]]
                titles = {item['id']: item['title'] for item in content['knowledge']}
                self.assertEqual({row[1]: int(row[2]) for row in table_rows}, {titles[identifier]: 1 + plan['page_knowledge'].index(identifier) for identifier in plan['knowledge_ids']})
                self.assertTrue(all(row[0].isdigit() for row in table_rows))
                for identifier in plan['knowledge_ids']:
                    pages = tuple(page_blocks for page_blocks, mapped in zip(plan['document'].pages, plan['page_knowledge'], strict=True) if mapped == identifier)
                    self.assertEqual(pages, individual[identifier]); position += len(pages)
                self.assertEqual(position, len(plan['document'].pages) + 1)
        output = self.queue(saved); result = jobs.execute_next(); self.assertEqual(result.state, 'output_check', result.error_code)
        self.assertEqual(len(result.result['documents']), 10)
        self.assertEqual(set(result.result['checks']), {'content', 'subject', 'pdf_visual', 'word_pc', 'word_macos'})
        self.assertTrue(all(check['status'] == 'not_tested' for check in result.result['checks'].values()))
        for document in result.result['documents']:
            self.assertEqual(document['question_ids'], []); self.assertEqual(len(document['previews']), document['page_count'])
            path = rendering.output_file(result, document['id'], 'document.docx')
            with zipfile.ZipFile(path) as archive:
                root = etree.fromstring(archive.read('word/document.xml'))
                plain = ''.join(root.xpath('//w:t/text()', namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}))
                self.assertNotIn(first['id'], plain)
                math_count = len(root.xpath("//*[local-name()='oMath']"))
                self.assertEqual(math_count, int(first['id'] in document['knowledge_ids'] and document['organization'] != 'inventory'))
                if math_count:
                    pictures = [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
                    self.assertIn(materials.asset_path(asset.storage_key, asset.sha256).read_bytes(), pictures)
        with zipfile.ZipFile(rendering.archive(result)) as archive:
            self.assertIsNone(archive.testzip()); self.assertTrue(any(name.endswith('.docx') for name in archive.namelist()))
            self.assertFalse(any('originals/' in name for name in archive.namelist()))
        original_page = services.inputs(self.material)[0][page]
        self.assertEqual(materials.asset_path(original_page.image.payload['storage_key'], original_page.image.sha256).read_bytes(), raw)
        with Image.open(materials.asset_path(asset.storage_key, asset.sha256)) as derived:
            self.assertEqual(derived.convert('RGBA').tobytes(), image.crop(source['region']).tobytes())
        self.assertEqual(EntityRecord.objects.count(), before)
        checks = queries.default_checks('knowledge')
        for name in ('content', 'subject', 'pdf_visual'): checks[name] = {'status': 'pass', 'notes': '自动化检查限定于此匿名用例'}
        checked = jobs.action(self.owner, result.pk, action='check', expected_version=result.version, request_key=key(), reason='匿名结构检查', checks=checks)
        self.assertEqual(checked.state, 'complete'); self.assertEqual(checked.result['checks']['word_pc']['status'], 'not_tested')
        evidence = os.environ.get('SWB_SOLUTION_TEST_EVIDENCE')
        if evidence:
            target = Path(evidence) / ('knowledge-' + output.pk.hex)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copytree(Path(settings.SWB_DATA_ROOT) / 'solutions' / 'outputs' / output.pk.hex, target)
            (target / 'result.json').write_text(json.dumps(result.result, ensure_ascii=False, indent=2))
            for path in target.rglob('*'): path.chmod(0o700 if path.is_dir() else 0o600)
