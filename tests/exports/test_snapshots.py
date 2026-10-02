from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.exports.contracts import Block, ExportError, FontSet, SourceRef, canonical, digest
from app.exports.fonts import prepare_fonts
from app.exports.snapshots import export_document, verify_snapshot
from tests.exports.test_contracts import synthetic_document

ROOT = Path(__file__).resolve().parents[2]
SOURCE_FONTS = {
    'regular_source': Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    'bold_source': Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'),
    'math_source': Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf'),
    'cjk_notice': ROOT / 'licenses/Noto-OFL.txt',
    'math_notice': ROOT / 'licenses/DejaVu-fonts.txt',
}


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='study-a2-snapshot-tests-')
        cls.document = synthetic_document(Block('p', '合成资料'), Block('math', ['f', ['t', '1'], ['t', '2']]))
        cls.fonts, cls.profile = prepare_fonts([cls.document], Path(cls.temporary.name) / 'fonts', **SOURCE_FONTS)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_replay_reuses_bytes_and_new_source_or_purpose_preserves_previous_files(self):
        with tempfile.TemporaryDirectory() as root:
            first, result = export_document(self.document, root, self.fonts, self.profile)
            hashes = {p.name: digest(p.read_bytes()) for p in first.iterdir()}
            repeated, replay = export_document(self.document, root, self.fonts, self.profile)
            self.assertEqual(first, repeated)
            self.assertTrue(replay['already_exported'])
            for changed in (replace(self.document, purpose='parent_answers'),
                            replace(self.document, source=SourceRef('synthetic-input', 'b' * 64))):
                other, _ = export_document(changed, root, self.fonts, self.profile)
                self.assertNotEqual(first, other)
            self.assertEqual(hashes, {p.name: digest(p.read_bytes()) for p in first.iterdir()})
            self.assertFalse(result['archive_complete'])
            self.assertEqual(verify_snapshot(first)['word_equations'], 1)
            self.assertEqual(first.stat().st_mode & 0o777, 0o700)
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in first.iterdir()))

    def test_modified_artifact_and_omitted_file_record_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as root:
            directory, _ = export_document(self.document, root, self.fonts, self.profile)
            pdf = directory / 'document.pdf'
            raw = pdf.read_bytes()
            pdf.write_bytes(raw + b'changed')
            with self.assertRaises(ExportError) as caught:
                export_document(self.document, root, self.fonts, self.profile)
            self.assertEqual(caught.exception.code, 'snapshot_hash_mismatch')
            self.assertEqual(pdf.read_bytes(), raw + b'changed')
            pdf.write_bytes(raw)
            manifest = json.loads((directory / 'snapshot.json').read_bytes())
            del manifest['files']['document.pdf']
            (directory / 'snapshot.json').write_bytes(canonical(manifest))
            with self.assertRaises(ExportError) as caught:
                verify_snapshot(directory)
            self.assertEqual(caught.exception.code, 'invalid_snapshot')

    def test_late_word_failure_discards_only_new_staging_output(self):
        with tempfile.TemporaryDirectory() as root:
            def failure(doc, output, fonts, **kwargs):
                (output / 'document.pdf').write_bytes(b'partial')
                raise ExportError('synthetic_word_failure', 'late failure')
            with patch('app.exports.renderer.render_document', side_effect=failure):
                with self.assertRaises(ExportError):
                    export_document(self.document, root, self.fonts, self.profile)
            self.assertEqual([p.name for p in Path(root).iterdir()], ['.export.lock'])

    def test_font_profile_is_bound_to_actual_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            changed = replace(self.fonts, regular=self.fonts.math)
            with self.assertRaises(ExportError) as caught:
                export_document(self.document, root, changed, self.profile)
            self.assertEqual(caught.exception.code, 'font_hash_mismatch')
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_mutable_payload_change_during_render_cannot_publish_snapshot(self):
        doc = synthetic_document(Block('math', ['t', '1']))
        with tempfile.TemporaryDirectory() as root:
            def mutate(document, output, fonts, **kwargs):
                document.pages[0][0].content[1] = '2'
                return {'page_count': 1, 'word_equations': 1}
            with patch('app.exports.renderer.render_document', side_effect=mutate):
                with self.assertRaises(ExportError) as caught:
                    export_document(doc, root, self.fonts, self.profile)
            self.assertEqual(caught.exception.code, 'input_changed')
            self.assertFalse(any(p.is_dir() for p in Path(root).iterdir()))


class FontPreparationTests(unittest.TestCase):
    def test_subsets_are_deterministic_renamed_and_keep_notices_without_changing_sources(self):
        doc = synthetic_document(Block('p', '合成资料'))
        before = {k: digest(p.read_bytes()) for k, p in SOURCE_FONTS.items()}
        with tempfile.TemporaryDirectory() as root:
            fonts, first = prepare_fonts([doc], Path(root) / 'one', **SOURCE_FONTS)
            _, second = prepare_fonts([doc], Path(root) / 'two', **SOURCE_FONTS)
            self.assertEqual(first, second)
            self.assertEqual(first['renamed_family'], 'Study Workbench Sans SC')
            self.assertEqual(first['files']['cjk-LICENSE.txt'], before['cjk_notice'])
            self.assertEqual(first['files']['math-LICENSE.txt'], before['math_notice'])
            self.assertEqual(fonts.regular.stat().st_mode & 0o777, 0o600)
        self.assertEqual(before, {k: digest(p.read_bytes()) for k, p in SOURCE_FONTS.items()})

    def test_missing_glyph_removes_new_stage_and_preserves_existing_directory(self):
        doc = synthetic_document(Block('p', '合成资料\U0010ffff'))
        with tempfile.TemporaryDirectory() as root:
            new = Path(root) / 'new'
            with self.assertRaises(ExportError) as caught:
                prepare_fonts([doc], new, **SOURCE_FONTS)
            self.assertEqual(caught.exception.code, 'missing_glyph')
            self.assertFalse(new.exists())
            existing = Path(root) / 'existing'
            existing.mkdir()
            (existing / 'sentinel').write_text('keep')
            with self.assertRaises(FileExistsError):
                prepare_fonts([doc], existing, **SOURCE_FONTS)
            self.assertEqual((existing / 'sentinel').read_text(), 'keep')
