"""Manual page inventory is independent of OCR, answers and learner progress."""
import json

from django.db import DatabaseError, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse

from app.persistence import services as core
from app.persistence.models import EntityRecord, RevisionRecord
from app.web import page_reading as reading, services
from app.web.models import MaterialPage, PageReadingRevision
from tests.web import test_services as fixtures

key = fixtures.key
from tests.web.test_http import hidden_fields


class PageReadingTests(TransactionTestCase):
    setUp = fixtures.ManualServicesTests.setUp
    tearDown = fixtures.ManualServicesTests.tearDown
    page = fixtures.ManualServicesTests.page
    source = fixtures.ManualServicesTests.source

    def save(self, page_id, **overrides):
        values = dict(reading='read', coverage='partial', sources=[{'kind': 'unknown', **self.source(page_id)}],
            pending_items='右下角看不清，待重拍', basis='人工逐页查看合成图片',
            expected=reading.detail(self.owner, page_id)['context'], request_key=key())
        values.update(overrides)
        return reading.save(self.owner, page_id, **values)

    def test_initial_unknown_and_append_history_do_not_create_learning_records(self):
        page_id = self.page()
        first = reading.detail(self.owner, page_id)
        self.assertEqual(first['history'], [])
        before = RevisionRecord.objects.count()
        saved = self.save(page_id)
        expected = reading.detail(self.owner, page_id)['context']
        second = self.save(page_id, reading='needs_retake', expected=expected)
        history = reading.detail(self.owner, page_id)['history']
        self.assertEqual([row.revision_no for row in history], [2, 1])
        self.assertEqual(history[0].previous_id, saved['reading_revision_id'])
        self.assertEqual(history[0].pk, second['reading_revision_id'])
        self.assertEqual(history[1].reading, 'read')
        self.assertEqual(history[1].partitions[0]['kind'], 'unknown')
        self.assertEqual(before, RevisionRecord.objects.count())
        self.assertFalse(EntityRecord.objects.filter(kind__in=('attempt', 'assessment')).exists())

    def test_rotations_map_to_original_pixels_and_keep_original_hash(self):
        page_id = self.page()
        source_page = MaterialPage.objects.select_related('image').get(pk=page_id)
        expected_boxes = {0: [5, 10, 30, 40], 90: [10, 30, 40, 55],
            180: [50, 20, 75, 50], 270: [40, 5, 70, 30]}
        for angle, box in expected_boxes.items():
            saved = self.save(page_id, sources=[{'kind': 'theory', **self.source(page_id, angle)}],
                coverage='complete', pending_items='')
            row = PageReadingRevision.objects.get(pk=saved['reading_revision_id'])
            self.assertEqual(row.partitions[0]['original_bbox'], box)
            self.assertEqual(row.original_sha256, source_page.image.sha256)
            self.assertEqual(row.partitions[0]['image_id'], source_page.image.stable_id)

    def test_complete_requires_explicit_read_and_no_unknown_or_pending(self):
        page_id = self.page()
        for changes in ({'coverage': 'complete'}, {'coverage': 'complete', 'pending_items': ''},
                {'coverage': 'complete', 'sources': [], 'pending_items': ''},
                {'coverage': 'complete', 'sources': [{'kind': 'theory', **self.source(page_id)}],
                 'reading': 'unread', 'pending_items': ''}, {'reading': 'needs_retake', 'pending_items': ''}):
            with self.assertRaises(core.PersistenceError):
                self.save(page_id, **changes)
        self.assertEqual(PageReadingRevision.objects.count(), 0)

    def test_exact_replay_conflict_and_stale_form(self):
        page_id = self.page()
        expected = reading.detail(self.owner, page_id)['context']
        request_key = key()
        saved = self.save(page_id, expected=expected, request_key=request_key)
        self.assertEqual(self.save(page_id, expected=expected, request_key=request_key), saved)
        with self.assertRaises(core.PersistenceError):
            self.save(page_id, expected=expected)
        with self.assertRaises(core.PersistenceError):
            self.save(page_id, expected=expected, request_key=request_key, pending_items='改变已提交内容')
        self.assertEqual(PageReadingRevision.objects.count(), 1)

    def test_invalid_coordinates_cross_page_and_tampered_preview_fail_closed(self):
        page_id = self.page()
        foreign_page = self.page('other.png')
        for source in ({'kind': 'theory', **self.source(foreign_page)},
                {'kind': 'unknown', **self.source(page_id), 'preview_sha256': 'f' * 64},
                {'kind': 'unknown', **self.source(page_id), 'display_bbox': [0, 0, 81, 60]},
                {'kind': 'unknown', **self.source(page_id, 270), 'display_bbox': [5, 70.1, 30, 79]},
                {'kind': 'unknown', **self.source(page_id), 'display_bbox': [0, 0, 10**500, 50]},
                {'kind': [], **self.source(page_id)},
                {'kind': 'unknown', **self.source(page_id), 'display_bbox': [0, 0, float('nan'), 50]}):
            with self.assertRaises(core.PersistenceError):
                self.save(page_id, sources=[source])
        self.assertEqual(PageReadingRevision.objects.count(), 0)

    def test_native_database_guards_enforce_immutable_contiguous_same_source_and_coordinates(self):
        page_id = self.page()
        saved = self.save(page_id)
        row = PageReadingRevision.objects.get(pk=saved['reading_revision_id'])
        with self.assertRaises(DatabaseError), transaction.atomic():
            PageReadingRevision.objects.filter(pk=row.pk).update(reading='unread')
        with self.assertRaises(DatabaseError), transaction.atomic():
            PageReadingRevision.objects.filter(pk=row.pk).delete()
        original = dict(page=row.page, household=row.household, created_by=self.owner,
            previous=row, revision_no=2, original_sha256=row.original_sha256, reading='read', coverage='partial',
            partitions=row.partitions, pending_items='', basis='合成直接写入测试')
        for override in ({'previous': None}, {'household': self.other_house}, {'created_by': self.viewer},
                {'original_sha256': 'f' * 64}, {'partitions': [{**row.partitions[0], 'original_bbox': [0, 0, 1, 1]}]},
                {'partitions': None}, {'partitions': [{**row.partitions[0], 'display_bbox': [0, 0, 81, 60]}]}):
            with self.assertRaises(DatabaseError), transaction.atomic():
                PageReadingRevision.objects.create(**{**original, **override})
        for angle, box in {0: [5, 10, 30.25, 40], 90: [10, 29.75, 40, 55],
                180: [49.75, 20, 75, 50], 270: [40, 5, 70, 30.25]}.items():
            source = self.source(page_id, angle)
            part = {**row.partitions[0], **source, 'display_bbox': [5, 10, 30.25, 40],
                'original_bbox': box}
            with self.assertRaises(DatabaseError), transaction.atomic():
                PageReadingRevision.objects.create(**{**original, 'partitions': [part]})

    def test_http_private_csrf_explicit_save_and_old_token_rejection(self):
        page_id = self.page()
        url = reverse('web:page_reading', kwargs={'page_id': page_id})
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(url).status_code, 302)
        client.force_login(self.owner)
        response = client.get(url)
        self.assertContains(response, '尚未记录：未阅读')
        self.assertIn('no-store', response['Cache-Control'])
        values = {**hidden_fields(response), 'sources': json.dumps([{'kind': 'handwriting', **self.source(page_id)}]),
            'reading': 'read', 'coverage': 'partial', 'pending_items': '未知作者', 'basis': '人工看图'}
        no_csrf = {k: v for k, v in values.items() if k != 'csrfmiddlewaretoken'}
        self.assertEqual(client.post(url, no_csrf).status_code, 403)
        self.assertEqual(PageReadingRevision.objects.count(), 0)
        fraction = {'kind': 'handwriting', **self.source(page_id, 270),
            'display_bbox': [5, 70.1, 30, 79]}
        rejected = client.post(url, {**values, 'sources': json.dumps([fraction])})
        self.assertContains(rejected, '原图区域无效', status_code=400)
        self.assertEqual(PageReadingRevision.objects.count(), 0)
        self.assertEqual(client.post(url, values).status_code, 302)
        self.assertEqual(client.post(url, values).status_code, 302)
        self.assertEqual(PageReadingRevision.objects.count(), 1)
        self.assertEqual(client.post(url, {**values, 'request_key': key()}).status_code, 409)
        client.force_login(self.viewer)
        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.post(url, values).status_code, 404)
        client.force_login(self.other)
        self.assertEqual(client.get(url).status_code, 404)

    def test_http_can_record_unread_or_retake_without_inventing_partitions(self):
        page_id = self.page()
        url = reverse('web:page_reading', kwargs={'page_id': page_id})
        client = Client()
        client.force_login(self.owner)
        response = client.get(url)
        values = {**hidden_fields(response), 'sources': '[]', 'reading': 'needs_retake',
            'coverage': 'partial', 'pending_items': '照片模糊，尚未阅读', 'basis': '人工发现照片模糊'}
        self.assertEqual(client.post(url, values).status_code, 302)
        row = PageReadingRevision.objects.get(page_id=page_id)
        self.assertEqual(row.partitions, [])
        self.assertEqual(row.reading, 'needs_retake')
