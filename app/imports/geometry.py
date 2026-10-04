"""Geometry catalog syntax layered over the shared catalog converter."""
from __future__ import annotations

from collections.abc import Mapping
import re

from app.domain import SourceImage

from .catalog import CatalogConversion, CatalogProfile, _fail, build_legacy_bundle


_GEOMETRY_NUM_RE = re.compile(
    r"([1-9][0-9]*)(?:\(([1-9][0-9]*)\)(?:-([1-9][0-9]*))?|\((左|右)\))?\Z"
)
_AUXILIARY_SEPARATOR_RE = re.compile(r"[;；]")
_GEOMETRY_BOOKS = ("J3", "J4", "W5", "W6", "W7", "W8", "W9")


def _parse_geometry_number(value: str, path: str) -> tuple[int, int | float | None, int | None]:
    match = _GEOMETRY_NUM_RE.fullmatch(value)
    if match is None:
        _fail(
            "invalid_question_number",
            path,
            "expected positive N, N(k), N(k)-m, N(左), or N(右)",
        )
    root_text, child_text, subquestion_text, side = match.groups()
    root = int(root_text)
    if side is not None:
        # These sort after N and before numeric children, with left before right.
        # A missing subquestion keeps both side nodes directly under their N parent.
        return root, 0.5 if side == "左" else 0.75, None
    return (
        root,
        int(child_text) if child_text is not None else None,
        int(subquestion_text) if subquestion_text is not None else None,
    )


def geometry_profile(auxiliary_mapping: Mapping[str, int]) -> CatalogProfile:
    """Build a geometry syntax profile from exact auxiliary-name mappings."""
    if not isinstance(auxiliary_mapping, Mapping):
        _fail("invalid_geometry_auxiliary_map", "auxiliary_mapping", "expected a mapping of exact names to group IDs")

    mapping: dict[str, int] = {}
    for name, group_id in auxiliary_mapping.items():
        if type(name) is not str or not name.strip() or name != name.strip():
            _fail(
                "invalid_geometry_auxiliary_map",
                "auxiliary_mapping",
                "names must be non-empty source labels without surrounding whitespace",
            )
        if type(group_id) is not int or not 1 <= group_id <= 6:
            _fail(
                "invalid_geometry_auxiliary_map",
                f"auxiliary_mapping[{name!r}]",
                "group IDs must be integers from 1 through 6",
            )
        mapping[name] = group_id

    # Keep a private snapshot so later caller mutations cannot change this profile.
    exact_mapping = dict(mapping)

    def parse_auxiliary(aux: str, groups: dict[int, str], path: str) -> list[int]:
        if aux == "":
            return []
        if not aux.strip():
            _fail("malformed_auxiliary_name", path, "auxiliary text must be empty or contain mapped names")

        result: list[int] = []
        seen: set[int] = set()
        for segment_no, raw_segment in enumerate(_AUXILIARY_SEPARATOR_RE.split(aux)):
            name = raw_segment.strip()
            segment_path = f"{path}.segment[{segment_no}]"
            if not name:
                _fail("malformed_auxiliary_name", segment_path, "expected a non-empty mapped auxiliary name")
            if name not in exact_mapping:
                _fail("unknown_auxiliary_name", segment_path, f"auxiliary name {name!r} has no exact mapping")
            group_id = exact_mapping[name]
            if group_id not in groups:
                _fail("unknown_group", segment_path, "mapped auxiliary group is not present in the catalog")
            if group_id not in seen:
                result.append(group_id)
                seen.add(group_id)
        return result

    return CatalogProfile(
        format_id="geometry.v1",
        books=_GEOMETRY_BOOKS,
        photo_separator="+",
        parse_number=_parse_geometry_number,
        parse_auxiliary=parse_auxiliary,
    )


def build_geometry_bundle(
    entries: list[dict],
    groups: dict[int, str],
    images: dict[str, SourceImage],
    *,
    household_id: str,
    dataset_key: str,
    recorded_at: str,
    auxiliary_mapping: Mapping[str, int],
) -> CatalogConversion:
    """Convert a geometry index through the shared catalog bundle builder."""
    return build_legacy_bundle(
        entries,
        groups,
        images,
        household_id=household_id,
        dataset_key=dataset_key,
        recorded_at=recorded_at,
        profile=geometry_profile(auxiliary_mapping),
    )
