import json
import unittest

from app.ai.schema import InvalidProposal, parse_response


def response(task="question", **overrides):
    proposal = {"printed_text": "虚构题目", "missing_fields": [],
        "classification_suggestion": None, "analysis_suggestion": None}
    values = {"schema_version": "study-workbench.ai.v1", "task": task,
        "source_revision_ids": ["question-r1"], "proposal": proposal, "tool_calls": []}
    values.update(overrides)
    return json.dumps(values, ensure_ascii=False)


class ClosedResponseTests(unittest.TestCase):
    def test_accepts_exact_synthetic_question_shape(self):
        result = parse_response(response(), task="question", allowed_sources=["question-r1"])
        self.assertEqual(result["proposal"]["printed_text"], "虚构题目")

    def test_rejects_duplicate_keys_and_unknown_fields(self):
        with self.assertRaises(InvalidProposal):
            parse_response('{"schema_version":"study-workbench.ai.v1","schema_version":"x"}',
                task="question", allowed_sources=["question-r1"])
        with self.assertRaises(InvalidProposal):
            parse_response(response(extra="closed"), task="question", allowed_sources=["question-r1"])

    def test_rejects_unknown_or_missing_sources_and_tool_overflow(self):
        with self.assertRaises(InvalidProposal):
            parse_response(response(source_revision_ids=["other"]), task="question",
                allowed_sources=["question-r1"])
        with self.assertRaises(InvalidProposal):
            parse_response(response(tool_calls=[{}] * 5), task="question",
                allowed_sources=["question-r1"], max_tool_calls=4)

    def test_rejects_oversized_and_non_json_responses(self):
        with self.assertRaises(InvalidProposal):
            parse_response(" " * 1_048_577, task="question", allowed_sources=["question-r1"])
        with self.assertRaises(InvalidProposal):
            parse_response("not json", task="question", allowed_sources=["question-r1"])

    def test_assessment_references_must_be_selected_regions_and_match_evidence_rules(self):
        dimensions = [{"dimension": name, "judgment": "unknown", "basis": "undetermined",
            "source_region_revision_ids": [], "rationale": "选择保留未知",
            "unknown_reason": "所选证据不足"}
            for name in ("answer", "method", "process", "calculation", "notation")]
        proposal = {"dimensions": dimensions}
        data = {"schema_version": "study-workbench.ai.v1", "task": "assessment",
            "source_revision_ids": ["question-r1", "region-r1"], "proposal": proposal,
            "tool_calls": []}
        accepted = parse_response(json.dumps(data, ensure_ascii=False), task="assessment",
            allowed_sources=data["source_revision_ids"], allowed_regions=["region-r1"])
        self.assertEqual(len(accepted["proposal"]["dimensions"]), 5)

        dimensions[0] = {**dimensions[0], "source_region_revision_ids": ["question-r1"]}
        with self.assertRaises(InvalidProposal):
            parse_response(json.dumps(data, ensure_ascii=False), task="assessment",
                allowed_sources=data["source_revision_ids"], allowed_regions=["region-r1"])

        dimensions[0] = {**dimensions[0], "judgment": "correct", "basis": "observed",
            "source_region_revision_ids": ["region-r1"], "unknown_reason": None}
        with self.assertRaises(InvalidProposal):
            parse_response(json.dumps(data, ensure_ascii=False), task="assessment",
                allowed_sources=data["source_revision_ids"], allowed_regions=["region-r1"],
                attempt_legibility="unreadable")
        parse_response(json.dumps(data, ensure_ascii=False), task="assessment",
            allowed_sources=data["source_revision_ids"], allowed_regions=["region-r1"],
            attempt_legibility="readable")

    def test_assessment_unknowns_need_reasons_and_region_ids_must_be_strings(self):
        dimensions = [{"dimension": name, "judgment": "unknown", "basis": "undetermined",
            "source_region_revision_ids": [], "rationale": "证据不足", "unknown_reason": "无法确定"}
            for name in ("answer", "method", "process", "calculation", "notation")]
        dimensions[0] = {**dimensions[0], "unknown_reason": None}
        data = {"schema_version": "study-workbench.ai.v1", "task": "assessment",
            "source_revision_ids": ["question-r1"], "proposal": {"dimensions": dimensions}, "tool_calls": []}
        with self.assertRaises(InvalidProposal):
            parse_response(json.dumps(data), task="assessment", allowed_sources=["question-r1"])
        dimensions[0] = {**dimensions[0], "unknown_reason": "无法确定",
            "source_region_revision_ids": [[]]}
        with self.assertRaises(InvalidProposal):
            parse_response(json.dumps(data), task="assessment", allowed_sources=["question-r1"])
