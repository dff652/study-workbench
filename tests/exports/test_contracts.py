from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from app.exports.contracts import (Block, ExportDocument, ExportError, SourceRef, digest,
    plain_text, resolve_formula_image, snapshot_id, validate_document, validate_math)
from app.exports.fonts import document_characters


def synthetic_document(*blocks, purpose="knowledge_summary"):
    return ExportDocument("synthetic", "合成资料", purpose, (tuple(blocks),), SourceRef("synthetic-input", "a" * 64))


class ExportContractTests(unittest.TestCase):
    def test_independent_material_rejects_answer_method_classification_and_ambiguous_body(self):
        for role in ("answer", "method", "classification", "body", "assessment"):
            with self.assertRaises(ExportError) as caught:
                validate_document(synthetic_document(Block("p", "合成内容", role), purpose="independent_practice"))
            self.assertEqual(caught.exception.code, "independent_hint")
        document = synthetic_document(Block("math", ["f", ["t", "1"], ["t", "3"]], "question"),
            Block("space", 80, "answer_space"), purpose="independent_practice")
        validate_document(document)
        self.assertNotEqual(snapshot_id(document), snapshot_id(replace(document, purpose="parent_answers")))

    def test_unknown_formula_and_extra_children_fail_instead_of_becoming_subscript(self):
        for node in (["sqrt", ["t", "4"]], ["f", ["t", "1"]], ["t", "1", "discarded"], [[], ["t", "1"]]):
            with self.assertRaises(ExportError):
                validate_math(node)
        validate_math(["r", ["u", ["t", "n"], ["t", "2"]], ["t", "+"], ["d", ["t", "a"], ["t", "1"]]])

    def test_markup_preserves_text_and_rejects_external_loading_or_mismatched_tags(self):
        self.assertEqual(plain_text('<b>重点</b><br/><font color="#123456">文字 &amp; 文本</font>'), "重点\n文字 & 文本")
        for markup in ('<img src="/etc/passwd"/>', '<a href="https://example.org">资料</a>',
                       '<b>内容</font>', '<font color="red">内容</font>', '<b onclick="x">内容</b>', '<b>内容', '<?hidden?>内容', '<![CDATA[hidden]]>内容'):
            with self.assertRaises(ExportError):
                plain_text(markup)

    def test_source_state_requires_exact_revision_for_accepted_content(self):
        document = synthetic_document(Block("p", "合成资料"))
        with self.assertRaises(ExportError):
            validate_document(replace(document, source=SourceRef("source", "b" * 64, "accepted")))
        validate_document(replace(document, source=SourceRef("source", "b" * 64, "accepted", "question-r2")))
        self.assertNotEqual(snapshot_id(document), snapshot_id(replace(document, source=SourceRef("source", "b" * 64))))

    def test_character_collection_uses_visible_document_text_and_normalized_superscripts(self):
        chars = document_characters((synthetic_document(Block("p", '<font color="#000000">甲⁷</font>'),
            Block("math", ["t", "𝑛"])),))
        self.assertIn(ord("甲"), chars)
        self.assertIn(ord("7"), chars)
        self.assertNotIn(ord("⁷"), chars)
        self.assertNotIn(ord("𝑛"), chars)  # Math has its own glyph coverage.

    def test_formula_fallback_requires_local_verified_image_and_explicit_source(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            buffer = io.BytesIO()
            Image.new("RGB", (30, 10), "white").save(buffer, format="PNG")
            raw = buffer.getvalue()
            (root / "formula.png").write_bytes(raw)
            fallback = {"storage_key": "formula.png", "sha256": digest(raw), "source_ref": "synthetic-equation-v1",
                        "alt": "合成公式图片", "width_points": 90}
            validate_document(synthetic_document(Block("formula_image", fallback)))
            self.assertEqual(resolve_formula_image(fallback, root), root / "formula.png")
            for changed in ({**fallback, "storage_key": "../outside.png"}, {**fallback, "sha256": "f" * 64}):
                with self.assertRaises(ExportError):
                    resolve_formula_image(changed, root)

    def test_invalid_table_map_numbers_and_kind_return_explicit_errors(self):
        invalid = [Block("table", [[["甲", "乙"]], [300, 300]]), Block("space", float("nan")),
                   Block("map", {"root": ["资料"], "groups": None}), Block([], "x"), Block("unknown", "x")]
        for block in invalid:
            with self.assertRaises(ExportError):
                validate_document(synthetic_document(block))
