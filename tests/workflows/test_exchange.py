import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from django.test import SimpleTestCase
from app.exports.contracts import canonical, digest, ExportError, PURPOSES
from scripts.prepare_skill_exchange import prepare
from scripts.produce_skill_records import produce


class SkillExchangeTests(SimpleTestCase):
    def test_malformed_packet_blocks_reject_without_attribute_errors(self):
        from copy import deepcopy
        for pages in (None, {}, [None], [{}], [['not-a-block']], [[None]], [[[]]]):
            sources, catalog, packet, records, mapping = self.inputs()
            packet = deepcopy(packet)
            packet['documents'][0]['pages'] = pages
            with self.subTest(pages=pages), self.assertRaises(ExportError):
                prepare(sources, catalog, packet, records, mapping)

    def test_legacy_diagram_requires_exact_portable_mapping_and_retains_packet(self):
        from copy import deepcopy
        from tests.workflows.test_assets import with_diagram
        sources, catalog, packet, _, mapping = self.inputs()
        proposal = with_diagram({'sources': [], 'records': [{'id': 'q', 'kind': 'question', 'data': {
            'printed_text': '合成题', 'sources': [{'source_id': 's', 'bbox': [1, 1, 8, 8]}]}}]})
        records = {'schema_version': 'swb.skill-records.v2', 'records': proposal['records'], 'assets': proposal['assets']}
        block = {'kind': 'diagram', 'role': 'question', 'content': {'storage_key': 'figure.png',
            'sha256': records['assets']['figure.png']['sha256'], 'source_ref': 'explicit-original',
            'alt': '合成三角形 ABC', 'width_mm': 250 * 25.4 / 72, 'no_hint_confirmed': True}}
        for doc in packet['documents']:
            if doc['purpose'] in ('parent_answers', 'independent_practice'):
                doc['pages'][0].append(deepcopy(block))
        result = prepare(sources, catalog, packet, records, mapping)
        self.assertEqual(result['schema_version'], 'swb.skill-import.v2')
        self.assertEqual(result['packet'], packet)
        self.assertEqual(result['assets'], records['assets'])
        changed = deepcopy(packet)
        next(d for d in changed['documents'] if d['purpose'] == 'independent_practice')['pages'][0][-1]['content']['no_hint_confirmed'] = False
        with self.assertRaises(ExportError): prepare(sources, catalog, changed, records, mapping)
        records['records'] = records['records'][:-1]
        records['assets'] = {}
        with self.assertRaises(ExportError): prepare(sources, catalog, packet, records, mapping)

    def test_complete_companion_uses_typed_content_and_rejects_inferred_sources(self):
        sources = {"schema_version": "swf.sources.v1", "sources": [{"source_id": "photo", "width": 120, "height": 80}]}
        draft = {"schema_version": "swb.material-draft.v1", "original_number": "C1",
            "sources": [{"source_id": "photo", "bbox": [8, 8, 100, 70]}],
            "proposal": {"printed_text": "3 × 3 = ?", "missing_fields": [],
                "nodes": [{"kind": "method", "data": {"name": "重复相加", "steps": "3 + 3 + 3"}}],
                "answer": {"body": "9", "basis": "复算", "formulas": [["t", "9"]]}}}
        result = produce(draft, sources)
        self.assertEqual([row["kind"] for row in result["records"]], ["question", "method", "link", "answer"])
        self.assertEqual(result["records"][0]["data"]["sources"], draft["sources"])
        draft["sources"][0]["bbox"] = [0, 0, 999, 80]
        with self.assertRaises(ValueError): produce(draft, sources)
        with self.assertRaises(ValueError): produce({"index": "不是完整题干"}, sources)

    def test_companion_cli_is_private_offline_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            draft = {"schema_version": "swb.material-draft.v1", "original_number": "D1",
                "sources": [{"source_id": "photo", "bbox": [8, 8, 100, 70]}],
                "proposal": {"printed_text": None, "missing_fields": ["printed_text"], "nodes": [], "answer": None}}
            sources = {"schema_version": "swf.sources.v1", "sources": [{"source_id": "photo", "width": 120, "height": 80}]}
            for name, value in (("draft", draft), ("sources", sources)):
                (root / (name + ".json")).write_bytes(canonical(value))
            target = root / "records.json"
            args = [sys.executable, "scripts/produce_skill_records.py", "--draft", str(root / "draft.json"),
                "--sources", str(root / "sources.json"), "--output", str(target)]
            env = {key: value for key, value in os.environ.items() if not key.startswith("SWB_") and key != "DJANGO_SETTINGS_MODULE"}
            first = subprocess.run(args, capture_output=True, text=True, env=env, check=True)
            self.assertFalse(json.loads(first.stdout)["database_opened"])
            before = target.read_bytes()
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertIsNone(json.loads(before)["records"][0]["data"]["printed_text"])
            self.assertNotEqual(subprocess.run(args, capture_output=True, env=env).returncode, 0)
            self.assertEqual(target.read_bytes(), before)

    def inputs(self):
        sources = {"schema_version": "swf.sources.v1", "batch_id": "synthetic",
                   "sources": [{"source_id": "s", "sha256": "a" * 64, "token": "photo-01"}]}
        catalog = {"schema_version": "swf.catalog.v1", "batch_id": "synthetic", "entries": [{"raw": "unknown"}]}
        docs = [{"schema_version": "swf.print.v1", "document_id": f"doc-{i}", "title": "匿名册",
            "purpose": purpose, "pages": [[{"kind": "p", "content": "未知保留。", "role": "instruction"}]],
            "source": {"source_id": "synthetic", "sha256": digest(canonical(catalog)), "state": "draft", "revision_id": None}}
            for i, purpose in enumerate(sorted(PURPOSES))]
        packet = {"schema_version": "swf.packet.v1", "batch_id": "synthetic",
                  "sources_sha256": digest(canonical(sources)), "catalog_sha256": digest(canonical(catalog)),
                  "documents": docs, "omitted_purposes": []}
        records = {"schema_version": "swb.skill-records.v1", "records": []}
        mapping = {"schema_version": "swb.skill-page-map.v1", "pages": [{"source_id": "s", "page_id": "explicit-page", "sha256": "a" * 64}]}
        return sources, catalog, packet, records, mapping

    def test_pure_merge_preserves_all_inputs_and_rejects_stale_or_omitted_source(self):
        inputs = self.inputs()
        output = prepare(*inputs, ledger={"unknown": "authorship"})
        self.assertEqual(output["tool_inputs"]["sources"], inputs[0])
        self.assertEqual(output["packet"], inputs[2])
        self.assertEqual(output["catalog"], inputs[1])
        self.assertEqual(output["ledger"], {"unknown": "authorship"})
        inputs[4]["pages"] = []
        with self.assertRaises(ValueError): prepare(*inputs)
        inputs = self.inputs()
        inputs[1]["entries"].append({"raw": "changed"})
        with self.assertRaises(ExportError): prepare(*inputs)

    def test_cli_has_no_database_configuration_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            args = [sys.executable, "scripts/prepare_skill_exchange.py"]
            for name, value in zip(("sources", "catalog", "packet", "records", "mapping"), self.inputs()):
                path = root / (name + ".json")
                path.write_bytes(canonical(value))
                args += ["--" + name, str(path)]
            target = root / "exchange.json"
            args += ["--output", str(target)]
            env = {key: value for key, value in os.environ.items() if not key.startswith("SWB_") and key != "DJANGO_SETTINGS_MODULE"}
            result = subprocess.run(args, capture_output=True, text=True, env=env, check=True)
            self.assertFalse(json.loads(result.stdout)["database_opened"])
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            before = target.read_bytes()
            repeated = subprocess.run(args, capture_output=True, text=True, env=env)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(target.read_bytes(), before)
