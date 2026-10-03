"""Canonical JSON round-trip and idempotent merge for closed synthetic bundles.

This is a metadata interchange format, not a durable backup/restore service.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from enum import Enum
import json
import math
from typing import Union, get_args, get_origin, get_type_hints
import types

from . import contracts as c
from .contracts import Bundle, ContractError
from .validation import validate_bundle


_TYPES: dict[str, type] = {}
for _name, _value in vars(c).items():
    if not isinstance(_value, type):
        continue
    try:
        if is_dataclass(_value) or issubclass(_value, Enum):
            _TYPES[_name] = _value
    except TypeError:
        continue


def _to_data(value: object, path: str = "$") -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        if type(value).__name__ not in _TYPES:
            raise ContractError("unknown_contract_type", path, "dataclass is not part of the closed bundle format")
        return {"_type": type(value).__name__, **{item.name: _to_data(getattr(value, item.name), f"{path}.{item.name}")
            for item in fields(value) if not (item.metadata.get("legacy_omit_none") and getattr(value, item.name) is None)}}
    if isinstance(value, tuple):
        return [_to_data(item, f"{path}[]") for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ContractError("invalid_serializable_value", path, "value is not a finite JSON contract value")


def serialize_bundle(bundle: Bundle, *, check_snapshot_reviews: bool = True) -> str:
    """Validate and return deterministic UTF-8-compatible JSON text."""
    validate_bundle(bundle, check_snapshot_reviews=check_snapshot_reviews)
    try:
        return json.dumps(_to_data(bundle), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ContractError("serialization_failed", "bundle", "bundle cannot be represented as canonical JSON") from exc


def _reject_constant(value: str) -> None:
    raise ContractError("invalid_json_number", "$", f"non-finite JSON number {value} is forbidden")


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate_json_key", "$", f"duplicate JSON key {key}")
        result[key] = value
    return result


def _decode(value: object, expected: object, path: str) -> object:
    origin = get_origin(expected)
    args = get_args(expected)
    if origin is tuple:
        if not isinstance(value, list):
            raise ContractError("invalid_json_type", path, "expected JSON array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(item, args[0], f"{path}[{index}]") for index, item in enumerate(value))
        if len(value) != len(args):
            raise ContractError("invalid_json_length", path, "fixed tuple has the wrong number of values")
        return tuple(_decode(item, kind, f"{path}[{index}]") for index, (item, kind) in enumerate(zip(value, args)))
    if origin in (Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        choices = tuple(arg for arg in args if arg is not type(None))
        if len(choices) != 1:
            raise ContractError("unsupported_contract_type", path, "unsupported union in contract")
        return _decode(value, choices[0], path)
    if expected is type(None):
        if value is not None:
            raise ContractError("invalid_json_type", path, "expected null")
        return None
    if isinstance(expected, type) and issubclass(expected, Enum):
        if not isinstance(value, str):
            raise ContractError("invalid_json_type", path, f"expected {expected.__name__} string")
        try:
            return expected(value)
        except ValueError as exc:
            raise ContractError("invalid_enum", path, f"unknown {expected.__name__} value") from exc
    if isinstance(expected, type) and is_dataclass(expected):
        if not isinstance(value, dict):
            raise ContractError("invalid_json_type", path, f"expected {expected.__name__} object")
        type_name = value.get("_type")
        if type_name != expected.__name__ or type_name not in _TYPES:
            raise ContractError("contract_type_mismatch", f"{path}._type", f"expected {expected.__name__}")
        declared = {field.name for field in fields(expected)}
        extra = set(value) - declared - {"_type"}
        compatible = {item.name for item in fields(expected) if item.metadata.get("legacy_omit_none")}
        missing = declared - set(value) - compatible
        if extra:
            raise ContractError("unexpected_field", path, f"unexpected fields: {', '.join(sorted(extra))}")
        if missing:
            raise ContractError("missing_field", path, f"missing fields: {', '.join(sorted(missing))}")
        hints = get_type_hints(expected)
        kwargs = {field.name: _decode(value[field.name], hints[field.name], f"{path}.{field.name}")
                  for field in fields(expected) if field.name in value}
        try:
            return expected(**kwargs)
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid_contract_object", path, f"cannot construct {expected.__name__}") from exc
    if expected is str:
        if not isinstance(value, str):
            raise ContractError("invalid_json_type", path, "expected string")
        return value
    if expected is bool:
        if not isinstance(value, bool):
            raise ContractError("invalid_json_type", path, "expected boolean")
        return value
    if expected is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ContractError("invalid_json_type", path, "expected integer; boolean is not accepted")
        return value
    if expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractError("invalid_json_type", path, "expected finite number")
        if isinstance(value, int):
            try:
                math.isfinite(float(value))
            except OverflowError as exc:
                raise ContractError("invalid_json_type", path, "number is outside finite range") from exc
            if not math.isfinite(float(value)):
                raise ContractError("invalid_json_type", path, "expected finite number")
            return value
        try:
            numeric = float(value)
        except (OverflowError, ValueError) as exc:
            raise ContractError("invalid_json_type", path, "number is outside finite range") from exc
        if not math.isfinite(numeric):
            raise ContractError("invalid_json_type", path, "expected finite number")
        return numeric
    raise ContractError("unsupported_contract_type", path, f"unsupported field type {expected}")


def deserialize_bundle(source: str, *, check_snapshot_reviews: bool = True) -> Bundle:
    """Parse, type-check and validate one complete bundle."""
    if not isinstance(source, str):
        raise ContractError("invalid_json", "$", "bundle input must be JSON text")
    try:
        data = json.loads(source, parse_constant=_reject_constant, object_pairs_hook=_unique_pairs)
    except ContractError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractError("invalid_json", "$", "bundle is not valid JSON") from exc
    bundle = _decode(data, Bundle, "$")
    if not isinstance(bundle, Bundle):
        raise ContractError("invalid_bundle", "$", "root value must be Bundle")
    validate_bundle(bundle, check_snapshot_reviews=check_snapshot_reviews)
    return bundle


def _merge_versioned(left: tuple, right: tuple, id_field: str, path: str) -> tuple:
    result = {getattr(item, id_field): item for item in left}
    for incoming in right:
        key = getattr(incoming, id_field)
        current = result.get(key)
        if current is None:
            result[key] = incoming
            continue
        for field in fields(current):
            if field.name == "revisions":
                continue
            if getattr(current, field.name) != getattr(incoming, field.name):
                raise ContractError("immutable_identity_conflict", f"{path}.{key}.{field.name}", "same stable ID has conflicting identity content")
        by_id = {revision.header.revision_id: revision for revision in current.revisions}
        by_number = {revision.header.revision_no: revision.header.revision_id for revision in current.revisions}
        for revision in incoming.revisions:
            old = by_id.get(revision.header.revision_id)
            if old is not None:
                if old != revision:
                    raise ContractError("immutable_content_conflict", f"{path}.{key}.{revision.header.revision_id}", "same revision ID has different immutable content")
                continue
            old_id = by_number.get(revision.header.revision_no)
            if old_id is not None and old_id != revision.header.revision_id:
                raise ContractError("revision_number_conflict", f"{path}.{key}.revision_no", "same object revision number has different revision IDs")
            by_id[revision.header.revision_id] = revision
            by_number[revision.header.revision_no] = revision.header.revision_id
        result[key] = replace(current, revisions=tuple(sorted(by_id.values(), key=lambda rev: rev.header.revision_no)))
    return tuple(result[key] for key in sorted(result))


def _merge_immutable(left: tuple, right: tuple, id_field: str, path: str) -> tuple:
    result = {getattr(item, id_field): item for item in left}
    for item in right:
        key = getattr(item, id_field)
        old = result.get(key)
        if old is not None and old != item:
            raise ContractError("immutable_content_conflict", f"{path}.{key}", "same stable ID has different immutable content")
        result[key] = item
    return tuple(result[key] for key in sorted(result))


def _merge_flat_revisions(left: tuple, right: tuple, path: str) -> tuple:
    result = {item.header.revision_id: item for item in left}
    for item in right:
        old = result.get(item.header.revision_id)
        if old is not None and old != item:
            raise ContractError("immutable_content_conflict", f"{path}.{item.header.revision_id}", "same revision ID has different immutable content")
        result[item.header.revision_id] = item
    return tuple(sorted(result.values(), key=lambda item: (item.header.owner_id, item.header.revision_no)))


def merge_bundles(existing: Bundle, incoming: Bundle, *, check_snapshot_reviews: bool = True) -> Bundle:
    """Idempotently merge two complete bundles by stable IDs and revision IDs."""
    validate_bundle(existing, check_snapshot_reviews=check_snapshot_reviews)
    validate_bundle(incoming, check_snapshot_reviews=check_snapshot_reviews)
    if existing.schema_version != incoming.schema_version or existing.household_id != incoming.household_id:
        raise ContractError("bundle_scope_conflict", "bundle", "bundles must use the same schema and household")
    merged = Bundle(
        schema_version=existing.schema_version,
        household_id=existing.household_id,
        images=_merge_immutable(existing.images, incoming.images, "image_id", "images"),
        regions=_merge_flat_revisions(existing.regions, incoming.regions, "regions"),
        knowledge_items=_merge_versioned(existing.knowledge_items, incoming.knowledge_items, "knowledge_id", "knowledge_items"),
        methods=_merge_versioned(existing.methods, incoming.methods, "method_id", "methods"),
        question_types=_merge_versioned(existing.question_types, incoming.question_types, "question_type_id", "question_types"),
        questions=_merge_versioned(existing.questions, incoming.questions, "question_id", "questions"),
        knowledge_question_links=_merge_flat_revisions(existing.knowledge_question_links, incoming.knowledge_question_links, "knowledge_question_links"),
        method_question_links=_merge_flat_revisions(existing.method_question_links, incoming.method_question_links, "method_question_links"),
        question_type_links=_merge_flat_revisions(existing.question_type_links, incoming.question_type_links, "question_type_links"),
        learners=_merge_immutable(existing.learners, incoming.learners, "learner_id", "learners"),
        observations=_merge_versioned(existing.observations, incoming.observations, "observation_id", "observations"),
        attempts=_merge_versioned(existing.attempts, incoming.attempts, "attempt_id", "attempts"),
        assessments=_merge_versioned(existing.assessments, incoming.assessments, "assessment_id", "assessments"),
        errata=_merge_versioned(existing.errata, incoming.errata, "erratum_id", "errata"),
    )
    validate_bundle(merged, check_snapshot_reviews=check_snapshot_reviews)
    return merged
