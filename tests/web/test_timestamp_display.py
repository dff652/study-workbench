from django.test import SimpleTestCase
from app.web.templatetags.product import local_timestamp

class TimestampDisplayTests(SimpleTestCase):
    def test_converts_record_timestamp_with_explicit_timezone_without_changing_date_value(self):
        self.assertEqual(local_timestamp('2026-10-06T20:01:02Z'), '2026-10-07 04:01:02 UTC+0800')
        self.assertEqual(local_timestamp('2026-10-06'), '2026-10-06 00:00:00（时区未记录）')
        self.assertEqual(local_timestamp('未知'), '未知')
