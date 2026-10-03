import json
import unittest
from dataclasses import replace

from app.domain.contracts import KnowledgeRevision, RevisionHeader, ReviewState, Origin, revision_content_hash
from app.domain.serialization import _to_data, _decode
from app.domain.presentation import validate_display
from app.exports.body import body_blocks


class PresentationTests(unittest.TestCase):
    def revision(self):
        return KnowledgeRevision(RevisionHeader('k-r1','k',1,None,'tester','2026-10-03T00:00:00Z',
            Origin.HUMAN,'录入',''),ReviewState.DRAFT,'1/2',(),())

    def test_absent_field_preserves_legacy_shape_hash_and_strict_decoding(self):
        revision=self.revision()
        legacy=_to_data(revision)
        self.assertNotIn('display_markup',legacy)
        self.assertEqual(_decode(legacy,KnowledgeRevision,'$'),revision)
        encoded=json.loads(json.dumps(legacy))
        del encoded['header']['content_hash']
        import hashlib
        expected=hashlib.sha256(json.dumps(encoded,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(revision_content_hash(revision),expected)
        formatted=replace(revision,display_markup='[[math:1/2]]')
        self.assertNotEqual(revision_content_hash(formatted),expected)
        self.assertEqual(_decode(_to_data(formatted),KnowledgeRevision,'$'),formatted)
        del legacy['definition']
        with self.assertRaises(ValueError):_decode(legacy,KnowledgeRevision,'$')

    def test_native_math_emphasis_and_literal_legacy(self):
        text='重点\n1/2\n(-2)^2\n(x^2)^3'
        markup='**重点**\n[[math:1/2]]\n[[math:(-2)^2]]\n[[math:(x^2)^3]]'
        validate_display(markup,text,())
        validate_display(markup.replace('\n','\r\n'),text.replace('\n','\r\n'),())
        blocks=body_blocks(text,markup,role='question')
        self.assertEqual([b.kind for b in blocks],['p','math','math','math'])
        self.assertEqual(blocks[0].content,'<b>重点</b>')
        self.assertEqual(body_blocks('**old**')[0].content,'**old**')
        self.assertIn('&lt;script&gt;',body_blocks('<script>', '<script>')[0].content)
        self.assertIn('backcolor',body_blocks('强调','==强调==')[0].content)

    def test_reject_changes_unbound_images_and_unsupported_math(self):
        for markup,text in [('**答案**','题目'),('[[image:1|sqrt(x)]]','sqrt(x)'),
                ('[[math:sqrt(x)]]','sqrt(x)'),('[[math:__import__("os")]]','__import__("os")')]:
            with self.assertRaises(ValueError):validate_display(markup,text,())
