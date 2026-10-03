"""Closed response validation for study-workbench.ai.v1."""
import json

from app.domain import BasisKind, DimensionKind, Judgment
from app.domain.arithmetic import check_arithmetic

MAX_RESPONSE = 1_048_576
TASKS = {"question", "knowledge", "assessment", "variant"}
DIMENSIONS = {item.value for item in DimensionKind}


class InvalidProposal(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidProposal("duplicate_json_key")
        result[key] = value
    return result


def _bad_constant(_):
    raise InvalidProposal("invalid_json_number")


def parse_response(raw, *, task, allowed_sources, max_tool_calls=4,
        allowed_regions=(), allowed_methods=(), attempt_legibility=None):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_RESPONSE:
        raise InvalidProposal("response_too_large")
    try:
        data = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_bad_constant)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidProposal("response_invalid_json") from None
    if not isinstance(data, dict) or set(data) != {"schema_version", "task", "source_revision_ids", "proposal", "tool_calls"}:
        raise InvalidProposal("response_schema_invalid")
    if data["schema_version"] != "study-workbench.ai.v1" or data["task"] != task:
        raise InvalidProposal("response_schema_invalid")
    refs = data["source_revision_ids"]
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise InvalidProposal("response_schema_invalid")
    if len(set(refs)) != len(refs) or set(refs) != set(allowed_sources):
        raise InvalidProposal("response_unknown_source")
    proposal = data["proposal"]
    if not isinstance(proposal, dict):
        raise InvalidProposal("response_schema_invalid")
    if task == "question":
        if set(proposal) != {"printed_text", "missing_fields", "classification_suggestion", "analysis_suggestion"}:
            raise InvalidProposal("response_schema_invalid")
        _string(proposal["printed_text"], 20000, allow_none=True)
        _string_list(proposal["missing_fields"], 80, 200)
        for key in ("classification_suggestion", "analysis_suggestion"):
            _string(proposal[key], 6000, allow_none=True)
    elif task == "knowledge":
        if set(proposal) != {"definition", "conditions", "common_errors"}:
            raise InvalidProposal("response_schema_invalid")
        _string(proposal["definition"], 20000)
        _string_list(proposal["conditions"], 80, 1000)
        _string_list(proposal["common_errors"], 80, 1000)
    elif task == "assessment":
        if set(proposal) != {"dimensions"} or not isinstance(proposal["dimensions"], list) or len(proposal["dimensions"]) != 5:
            raise InvalidProposal("response_schema_invalid")
        seen = set()
        for dim in proposal["dimensions"]:
            if not isinstance(dim, dict) or set(dim) != {"dimension", "judgment", "basis", "source_region_revision_ids", "rationale", "unknown_reason"}:
                raise InvalidProposal("response_schema_invalid")
            if (not isinstance(dim["dimension"], str) or dim["dimension"] not in DIMENSIONS
                    or dim["dimension"] in seen):
                raise InvalidProposal("response_schema_invalid")
            seen.add(dim["dimension"])
            if (not isinstance(dim["judgment"], str) or not isinstance(dim["basis"], str)
                    or dim["judgment"] not in {x.value for x in Judgment}
                    or dim["basis"] not in {x.value for x in BasisKind}):
                raise InvalidProposal("response_schema_invalid")
            _string(dim["rationale"], 2000)
            _string(dim["unknown_reason"], 1000, allow_none=True)
            regions = dim["source_region_revision_ids"]
            if not isinstance(regions, list) or any(not isinstance(x, str) for x in regions):
                raise InvalidProposal("response_unknown_source")
            if (len(regions) != len(set(regions)) or any(x not in allowed_regions for x in regions)):
                raise InvalidProposal("response_unknown_source")
            judgment = Judgment(dim["judgment"])
            basis = BasisKind(dim["basis"])
            rationale = dim["rationale"]
            unknown_reason = dim["unknown_reason"]
            if not rationale.strip():
                raise InvalidProposal("response_schema_invalid")
            if dim["judgment"] == "unknown" and not dim["unknown_reason"]:
                raise InvalidProposal("response_schema_invalid")
            if basis is BasisKind.UNDETERMINED and not unknown_reason:
                raise InvalidProposal("response_schema_invalid")
            if judgment is not Judgment.UNKNOWN and basis is BasisKind.OBSERVED and not regions:
                raise InvalidProposal("response_schema_invalid")
            if judgment is Judgment.CORRECT and (basis is not BasisKind.OBSERVED or not regions
                    or attempt_legibility != "readable"):
                raise InvalidProposal("response_schema_invalid")
    else:
        if set(proposal) != {"text", "answer_expression", "check_expression", "target_method_revision_id"}:
            raise InvalidProposal("response_schema_invalid")
        _string(proposal["text"], 12000)
        _string(proposal["answer_expression"], 512)
        _string(proposal["check_expression"], 512)
        if proposal["target_method_revision_id"] not in allowed_methods:
            raise InvalidProposal("response_unknown_source")
        try:
            if check_arithmetic(proposal["answer_expression"], proposal["check_expression"])["matches"] is not True:
                raise InvalidProposal("variant_math_check_failed")
        except Exception:
            raise InvalidProposal("variant_math_check_failed") from None
    calls = data["tool_calls"]
    if not isinstance(calls, list) or len(calls) > max_tool_calls:
        raise InvalidProposal("tool_call_limit")
    return data


def _string(value, limit, allow_none=False):
    if allow_none and value is None:
        return
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise InvalidProposal("response_schema_invalid")


def _string_list(value, count, limit):
    if not isinstance(value, list) or len(value) > count:
        raise InvalidProposal("response_schema_invalid")
    for item in value:
        _string(item, limit)
