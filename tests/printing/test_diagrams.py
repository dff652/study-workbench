import io
import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import TransactionTestCase
from PIL import Image

from app.exports.contracts import ExportError
from app.persistence import services as core
from app.printing import diagram_services as diagrams, packets, services
from app.printing.models import TeachingDiagramRevision
from app.web import services as materials
from tests.printing import test_services as fixtures
from tests.web.test_services import key


def diagram_uploads():
    stream = io.BytesIO()
    Image.new('RGB', (400, 250), 'white').save(stream, 'PNG')
    return {'png_upload': SimpleUploadedFile('figure.png', stream.getvalue(), content_type='image/png'),
        'vector_upload': SimpleUploadedFile('figure.svg', b'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="250"/>')}


class DiagramTests(TransactionTestCase):
    setUp = fixtures.PrintTests.setUp
    tearDown = fixtures.PrintTests.tearDown
    page = fixtures.PrintTests.page
    source = fixtures.PrintTests.source
    question = fixtures.PrintTests.question
    published = fixtures.PrintTests.published

    def inputs(self, q, **changes):
        return {**diagram_uploads(), 'placement': 'question',
            'source_region_id': q.payload['evidence_refs'][0]['region_revision_id'], 'alt': '合成三角形 ABC',
            'conditions': ['AB=AC'], 'width_points': 250, 'min_label_points': 12, 'independent_safe': True,
            'basis': '对照合成原图核对构造与标签', 'expected': diagrams.diagram_context(q), 'request_key': key(), **changes}

    def test_append_replay_stale_permissions_and_native_guards(self):
        q = self.published(); inputs = self.inputs(q)
        first = diagrams.save_diagram(self.owner, q.pk, **inputs)
        self.assertEqual(diagrams.save_diagram(self.owner, q.pk, **inputs), first)
        for actor in (self.viewer, self.other):
            with self.assertRaises(core.PersistenceError): diagrams.save_diagram(actor, q.pk, **self.inputs(q))
        row = TeachingDiagramRevision.objects.get(pk=first['diagram_id'])
        before = json.dumps(row.content, sort_keys=True)
        second = diagrams.save_diagram(self.owner, q.pk, **self.inputs(q, alt='新合成标签'))
        self.assertEqual(TeachingDiagramRevision.objects.get(pk=second['diagram_id']).previous_id, row.pk)
        with self.assertRaises(core.PersistenceError): diagrams.save_diagram(self.owner, q.pk, **{**inputs, 'request_key': key()})
        row.refresh_from_db(); self.assertEqual(json.dumps(row.content, sort_keys=True), before)
        for operation in ('update', 'delete'):
            with self.assertRaises(DatabaseError), transaction.atomic():
                if operation == 'update': TeachingDiagramRevision.objects.filter(pk=row.pk).update(basis='覆盖')
                else: TeachingDiagramRevision.objects.filter(pk=row.pk).delete()
        with self.assertRaises(DatabaseError), transaction.atomic():
            TeachingDiagramRevision.objects.create(household=self.house, question_revision=q, placement='question',
                revision_no=3, previous=row, content=row.content, basis='错误前序', created_by=self.owner)
        self.assertTrue(diagrams.diagram_file(self.viewer, row.pk, 'png').is_file())
        with self.assertRaises(core.PersistenceError): diagrams.diagram_file(self.other, row.pk, 'png')

    def test_validates_source_and_uploads_and_cleans_failed_install(self):
        q = self.published()
        for changes in (
            {'source_region_id': 'unknown'}, {'min_label_points': 8}, {'independent_safe': 'yes'},
            {'conditions': []}, {'png_upload': SimpleUploadedFile('bad.png', b'not-png')},
            {'vector_upload': SimpleUploadedFile('bad.svg', b'<!DOCTYPE svg><svg/>')},
            {'vector_upload': SimpleUploadedFile('utf16.svg', '<!DOCTYPE svg><svg/>'.encode('utf-16'))},
        ):
            with self.assertRaises((core.PersistenceError, ExportError)):
                diagrams.save_diagram(self.owner, q.pk, **self.inputs(q, **changes))
        from django.conf import settings
        from pathlib import Path
        root = Path(settings.SWB_DATA_ROOT)
        before = set(root.rglob('*.png')) | set(root.rglob('*.svg'))
        with patch('app.printing.diagram_services.core._receipt', side_effect=core.PersistenceError('probe', '合成失败')):
            with self.assertRaises(core.PersistenceError): diagrams.save_diagram(self.owner, q.pk, **self.inputs(q))
        self.assertEqual(TeachingDiagramRevision.objects.count(), 0)
        self.assertEqual(set(root.rglob('*.png')) | set(root.rglob('*.svg')), before)

    def test_five_books_preserve_diagrams_and_exclude_answer_diagram_from_practice(self):
        q = self.published()
        services.save_answer(self.owner, self.house.pk, q.pk, body='1/2', formulas=[], basis='通分',
            expected=services.answer_context(q), request_key=key(), confirm=True)
        first = diagrams.save_diagram(self.owner, q.pk, **self.inputs(q))
        diagrams.save_diagram(self.owner, q.pk, **self.inputs(q, placement='answer', alt='含合成答案', independent_safe=False))
        packet_id = packets.generate(self.owner, self.material.pk)
        _, manifest = packets.read(self.viewer, self.material.pk, packet_id)
        self.assertEqual(len(manifest['diagram_revisions']), 2)
        practice = next(book for book in manifest['books'] if book['purpose'] == 'independent_practice')
        answers = next(book for book in manifest['books'] if book['purpose'] == 'parent_answers')
        def blocks(book):
            doc = json.loads(services.snapshot_file(self.owner, book['snapshot_id'], 'content.json').read_bytes())
            return [b for page in doc['pages'] for b in page if b['kind'] == 'diagram']
        self.assertEqual([b['role'] for b in blocks(practice)], ['question'])
        self.assertEqual([b['role'] for b in blocks(answers)], ['question', 'answer'])
        diagrams.save_diagram(self.owner, q.pk, **self.inputs(q, independent_safe=False, alt='未核定标签'))
        self.assertFalse(packets.readiness(self.owner, self.material.pk)['ready'])
        with self.assertRaises(core.PersistenceError): packets.generate(self.owner, self.material.pk)
        self.assertEqual(packets.read(self.owner, self.material.pk, packet_id)[1], manifest)
        path = diagrams.diagram_file(self.owner, first['diagram_id'], 'vector'); path.write_bytes(b'changed')
        with self.assertRaises(core.PersistenceError): diagrams.diagram_file(self.owner, first['diagram_id'], 'vector')

    def test_new_question_version_does_not_inherit_previous_diagram(self):
        q = self.published(); diagrams.save_diagram(self.owner, q.pk, **self.inputs(q))
        edit = materials.question_detail(self.owner, q.entity.stable_id)
        saved = materials.save_question(self.owner, self.material.pk, printed_text='新的合成题干',
            original_number='1', sources=[self.source(self.page())], question_id=q.entity.stable_id,
            expected_context=edit['edit_context'], request_key=key(), reason='核对新版本', confirm=True)
        from app.persistence.models import RevisionRecord
        new = RevisionRecord.objects.get(pk=saved['revision_id'])
        self.assertEqual(diagrams.current_diagrams(new), [])
        self.assertEqual(len(TeachingDiagramRevision.objects.filter(question_revision=q)), 1)
        old = diagrams.details(self.owner, q.pk)
        self.assertFalse(old['can_write'])
        self.assertEqual(len(old['history']), 1)
        self.client.force_login(self.owner)
        response = self.client.get(f'/prints/diagrams/{q.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '保存并确认图示')
        self.assertContains(response, '合成三角形 ABC')

    def test_question_text_figure_and_writing_space_stay_on_one_page(self):
        questions = [self.published(text=f'合成题 {n}：求图中问号。') for n in (1, 2)]
        for question in questions:
            stream = io.BytesIO()
            Image.new('RGB', (600, 740), 'white').save(stream, 'PNG')
            diagrams.save_diagram(self.owner, question.pk, **self.inputs(question, width_points=300,
                png_upload=SimpleUploadedFile('tall.png', stream.getvalue())))
        snapshot = services.export_questions(self.owner, self.house.pk, [q.pk for q in questions],
            title='合成题图分页', purpose='independent_practice')
        content = json.loads(services.snapshot_file(self.owner, snapshot.pk, 'content.json').read_bytes())
        self.assertEqual(len(content['pages']), 2)
        for page in content['pages']:
            self.assertEqual(len([b for b in page if b['kind'] == 'p' and b['role'] == 'question']), 1)
            self.assertEqual(len([b for b in page if b['kind'] == 'diagram']), 1)
            self.assertEqual(len([b for b in page if b['kind'] == 'space']), 1)
