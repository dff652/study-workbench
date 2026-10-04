"""Pure conversion from the legacy question index to the offline domain model."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Callable

from app.domain import (
    ActualDateState,
    AuthorState,
    Bundle,
    ContractError,
    EvidencePurpose,
    EvidenceRef,
    Granularity,
    Legibility,
    Method,
    MethodQuestionLinkRevision,
    MethodRevision,
    ObservationRevision,
    Origin,
    Question,
    QuestionRevision,
    RevisionHeader,
    ReviewState,
    SourceImage,
    SourceObservation,
    seal_revision,
    validate_bundle,
)


_ROW_FIELDS = frozenset({"book", "num", "group", "photo", "feature", "method", "tag", "tip", "aux"})
_BOOKS = ("J1", "J2", "W1", "W2", "W3", "W4")
_NUM_RE = re.compile(r"([1-9][0-9]*)(?:\(([1-9][0-9]*)\)(?:-([1-9][0-9]*))?)?\Z")
_AUX_SEGMENT_RE = re.compile(r"([1-9][0-9]*)(?:\s+(.+))?\Z")


@dataclass(frozen=True, slots=True)
class CatalogConversion:
    bundle: Bundle
    index_rows: tuple[dict, ...]
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class CatalogProfile:
    """Explicit historical syntax; never infer a topic from free text."""
    format_id: str
    books: tuple[str, ...]
    photo_separator: str
    parse_number: Callable[[str, str], tuple[int, int | float | None, int | None]]
    parse_auxiliary: Callable[[str, dict[int, str], str], list[int]]


def _fail(code: str, path: str, message: str) -> None:
    raise ContractError(code, path, message)


def _stable_id(scope: str, kind: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"legacy-{scope}-{kind}-{digest}"


def _scope_prefix(household_id: str, dataset_key: str) -> str:
    material = f"{household_id}\0{dataset_key}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:20]


def _parse_num(value: str, path: str) -> tuple[int, int | None, int | None]:
    match = _NUM_RE.fullmatch(value)
    if match is None:
        _fail("invalid_question_number", path, "expected positive N, N(k), or N(k)-m")
    root, child, subquestion = match.groups()
    return int(root), int(child) if child is not None else None, int(subquestion) if subquestion is not None else None


def _parent_num(num: str, parse_number=_parse_num) -> str | None:
    root, child, subquestion = parse_number(num, "num")
    if child is None:
        return None
    if subquestion is None:
        return str(root)
    return f"{root}({child})"


def _sort_num(value: str, parse_number=_parse_num) -> tuple[int, int | float, int, int]:
    root, child, subquestion = parse_number(value, "num")
    return root, child or 0, subquestion or 0, 1 if subquestion is not None else 0


def _parse_aux_groups(aux: str, groups: dict[int, str], path: str) -> list[int]:
    if aux == "":
        return []
    if not aux.strip():
        _fail("malformed_aux_group", path, "auxiliary text must be empty or contain explicit group prefixes")
    result: list[int] = []
    seen: set[int] = set()
    for segment_no, raw_segment in enumerate(re.split(r"[;；]", aux)):
        segment = raw_segment.strip()
        match = _AUX_SEGMENT_RE.fullmatch(segment)
        segment_path = f"{path}.segment[{segment_no}]"
        if not segment or match is None:
            _fail("malformed_aux_group", segment_path, "expected an explicit numeric group prefix")
        group_id = int(match.group(1))
        if group_id not in groups:
            _fail("unknown_group", segment_path, "auxiliary prefix does not name a known group")
        if group_id not in seen:
            result.append(group_id)
            seen.add(group_id)
    return result


def _header(owner_id: str, revision_id: str, recorded_at: str, reason: str) -> RevisionHeader:
    return RevisionHeader(
        revision_id=revision_id,
        owner_id=owner_id,
        revision_no=1,
        previous_revision_id=None,
        created_by="legacy-importer",
        recorded_at=recorded_at,
        origin=Origin.IMPORT,
        change_reason=reason,
        content_hash="",
    )


LEGACY_PROFILE = CatalogProfile("calculation.v1", _BOOKS, "/", _parse_num, _parse_aux_groups)


def _question_evidence(
    household_id: str,
    tokens: list[str],
    images_by_token: dict[str, SourceImage],
) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(
            household_id=household_id,
            image_id=images_by_token[token].image_id,
            image_sha256=images_by_token[token].sha256,
            granularity=Granularity.WHOLE_IMAGE,
            region_id=None,
            region_revision_id=None,
            region_missing=True,
            purpose=EvidencePurpose.QUESTION,
            sequence=sequence,
            gaps=("region_missing",),
        )
        for sequence, token in enumerate(tokens, 1)
    )


def build_legacy_bundle(
    entries: list[dict],
    groups: dict[int, str],
    images: dict[str, SourceImage],
    *,
    household_id: str,
    dataset_key: str,
    recorded_at: str,
    profile: CatalogProfile = LEGACY_PROFILE,
) -> CatalogConversion:
    """Convert legacy index rows without inferring question text or learner work."""
    if not isinstance(entries, list):
        _fail("invalid_input", "entries", "expected a list of index rows")
    if not isinstance(groups, dict):
        _fail("invalid_input", "groups", "expected a group mapping")
    if set(groups) != set(range(1, 7)) or any(type(key) is not int for key in groups):
        _fail("invalid_group_map", "groups", "group keys must be exactly the integers 1 through 6")
    if any(type(name) is not str or not name.strip() for name in groups.values()):
        _fail("invalid_group_map", "groups", "every group needs a non-empty name")
    if not isinstance(images, dict):
        _fail("invalid_input", "images", "expected a mapping of six-digit photo tokens to SourceImage")
    if type(household_id) is not str or not household_id.strip():
        _fail("invalid_scope", "household_id", "expected a non-empty household ID")
    if type(dataset_key) is not str or not dataset_key.strip():
        _fail("invalid_scope", "dataset_key", "expected a non-empty dataset key")
    if (not isinstance(profile, CatalogProfile) or not profile.books or
        len(set(profile.books)) != len(profile.books) or
        profile.photo_separator not in ("/", "+") or
        not callable(profile.parse_number) or not callable(profile.parse_auxiliary)):
        _fail("invalid_catalog_profile", "profile", "expected an explicit supported catalog profile")
    book_order = {book: index for index, book in enumerate(profile.books)}
    photo_pattern = re.compile(r"[0-9]{6}(?:" + re.escape(profile.photo_separator) + r"[0-9]{6})*\Z")

    images_by_token: dict[str, SourceImage] = {}
    unique_images: dict[str, SourceImage] = {}
    for token, image in images.items():
        if type(token) is not str or re.fullmatch(r"[0-9]{6}", token) is None:
            _fail("invalid_photo_token", f"images.{token!r}", "image key must be a six-digit photo token")
        if not isinstance(image, SourceImage):
            _fail("invalid_image", f"images.{token}", "expected SourceImage metadata")
        if type(image.image_id) is not str or not image.image_id.strip() or image.image_id != image.image_id.strip():
            _fail("invalid_image", f"images.{token}.image_id", "expected a non-empty stable image ID")
        previous = unique_images.get(image.image_id)
        if previous is not None and previous != image:
            _fail("image_identity_conflict", f"images.{token}", "same stable image ID has conflicting metadata")
        unique_images.setdefault(image.image_id, image)
        images_by_token[token] = image

    parsed_rows: list[dict] = []
    indexed: set[tuple[str, str]] = set()
    for ordinal, row in enumerate(entries, 1):
        path = f"entries[{ordinal - 1}]"
        if type(row) is not dict:
            _fail("invalid_row", path, "expected a dictionary row")
        if any(type(key) is not str for key in row):
            _fail("invalid_row_field_name", path, "row field names must be strings")
        missing = _ROW_FIELDS - set(row)
        extra = set(row) - _ROW_FIELDS
        if missing:
            _fail("missing_row_fields", path, f"missing fields: {', '.join(sorted(missing))}")
        if extra:
            _fail("unexpected_row_fields", path, f"unexpected fields: {', '.join(sorted(extra))}")
        for field in ("book", "num", "photo", "feature", "method", "tag", "tip", "aux"):
            value = row[field]
            if type(value) is not str or (field != "aux" and not value.strip()):
                _fail("invalid_row_field", f"{path}.{field}", "expected source text" if field == "aux" else "expected non-empty source text")
        group_id = row["group"]
        if type(group_id) is not int:
            _fail("invalid_group", f"{path}.group", "expected an integer group ID")
        if group_id not in groups:
            _fail("unknown_group", f"{path}.group", "row references an unknown group")
        if row["book"] not in book_order:
            _fail("unknown_book", f"{path}.book", "book is not in the selected topic profile")
        profile.parse_number(row["num"], f"{path}.num")
        if photo_pattern.fullmatch(row["photo"]) is None:
            _fail("invalid_photo_list", f"{path}.photo", "expected photo tokens in the selected topic syntax")
        photo_tokens = row["photo"].split(profile.photo_separator)
        for token in photo_tokens:
            if token not in images_by_token:
                _fail("unknown_photo", f"{path}.photo", f"photo token {token} has no source image metadata")
        identity = (row["book"], row["num"])
        if identity in indexed:
            _fail("duplicate_index_row", f"{path}.num", "book and question number already have an index row")
        indexed.add(identity)
        aux_groups = profile.parse_auxiliary(row["aux"], groups, f"{path}.aux")
        parsed_rows.append({
            "ordinal": ordinal,
            "raw": row,
            "book": row["book"],
            "num": row["num"],
            "group": group_id,
            "photo_tokens": photo_tokens,
            "aux_group_ids": aux_groups,
        })

    scope = _scope_prefix(household_id, dataset_key)
    question_numbers: set[tuple[str, str]] = set(indexed)
    for row in parsed_rows:
        book, num = row["book"], row["num"]
        while True:
            parent = _parent_num(num, profile.parse_number)
            if parent is None:
                break
            question_numbers.add((book, parent))
            num = parent

    question_ids = {
        identity: _stable_id(scope, "q", f"{identity[0]}\0{identity[1]}")
        for identity in question_numbers
    }
    question_revision_ids = {identity: f"{question_id}-r1" for identity, question_id in question_ids.items()}
    question_photos: dict[tuple[str, str], list[str]] = {identity: [] for identity in question_numbers}
    for row in parsed_rows:
        current: str | None = row["num"]
        while current is not None:
            target = (row["book"], current)
            photo_list = question_photos[target]
            for token in row["photo_tokens"]:
                if token not in photo_list:
                    photo_list.append(token)
            current = _parent_num(current, profile.parse_number)

    questions: list[Question] = []
    for book, num in sorted(question_numbers, key=lambda identity: (book_order[identity[0]], *_sort_num(identity[1], profile.parse_number))):
        identity = (book, num)
        question_id = question_ids[identity]
        parent_num = _parent_num(num, profile.parse_number)
        parent_question_id = question_ids[(book, parent_num)] if parent_num is not None else None
        revision_id = question_revision_ids[identity]
        revision = seal_revision(QuestionRevision(
            header=_header(question_id, revision_id, recorded_at, "Legacy index import; question text and attempt source remain unknown"),
            review_state=ReviewState.DRAFT,
            parent_question_revision_id=question_revision_ids[(book, parent_num)] if parent_num is not None else None,
            printed_text=None,
            working_text=None,
            missing_fields=("printed_text", "working_text", "region_coordinates", "attempt_source"),
            evidence_refs=_question_evidence(household_id, question_photos[identity], images_by_token),
            erratum_revision_ids=(),
        ))
        questions.append(Question(question_id, household_id, parent_question_id, (revision,)))

    methods: list[Method] = []
    method_revision_ids: dict[int, str] = {}
    for group_id in range(1, 7):
        method_id = _stable_id(scope, "m", str(group_id))
        revision_id = f"{method_id}-r1"
        method_revision_ids[group_id] = revision_id
        revision = seal_revision(MethodRevision(
            header=_header(method_id, revision_id, recorded_at, "Import legacy method group label"),
            review_state=ReviewState.DRAFT,
            name=groups[group_id],
            conditions=(),
            steps=(),
            notes=(),
            parent_revision_id=None,
            source_refs=(),
        ))
        methods.append(Method(method_id, household_id, (revision,)))

    links: list[MethodQuestionLinkRevision] = []
    index_rows: list[dict] = []
    for row in parsed_rows:
        qid = question_ids[(row["book"], row["num"])]
        qrev_id = question_revision_ids[(row["book"], row["num"])]
        primary_method_revision_id = method_revision_ids[row["group"]]
        for role, method_revision_id in (
            [("primary", primary_method_revision_id)]
            + [("auxiliary", method_revision_ids[group_id]) for group_id in row["aux_group_ids"]]
        ):
            target_identity = f"{qrev_id}\0{role}\0{method_revision_id}"
            link_id = _stable_id(scope, "link", target_identity)
            revision_id = f"{link_id}-r1"
            links.append(seal_revision(MethodQuestionLinkRevision(
                link_id=link_id,
                household_id=household_id,
                header=_header(link_id, revision_id, recorded_at, "Import explicit legacy method group association"),
                question_revision_id=qrev_id,
                method_revision_id=method_revision_id,
                role=role,
                review_state=ReviewState.DRAFT,
            )))
        index_rows.append({
            "ordinal": row["ordinal"],
            "book": row["book"],
            "num": row["num"],
            "question_id": qid,
            "question_revision_id": qrev_id,
            "raw": row["raw"],
            "photo_tokens": list(row["photo_tokens"]),
            "primary_method_revision_id": primary_method_revision_id,
            "aux_method_revision_ids": [method_revision_ids[group_id] for group_id in row["aux_group_ids"]],
        })

    observations: list[SourceObservation] = []
    for image in unique_images.values():
        observation_id = _stable_id(scope, "observation", image.image_id)
        revision_id = f"{observation_id}-r1"
        evidence = EvidenceRef(
            household_id=household_id,
            image_id=image.image_id,
            image_sha256=image.sha256,
            granularity=Granularity.WHOLE_IMAGE,
            region_id=None,
            region_revision_id=None,
            region_missing=True,
            purpose=EvidencePurpose.OTHER,
            sequence=1,
            gaps=("region_missing",),
        )
        revision = seal_revision(ObservationRevision(
            header=_header(observation_id, revision_id, recorded_at, "Preserve unreviewed legacy source image"),
            evidence_refs=(evidence,),
            legibility=Legibility.UNKNOWN,
            author_state=AuthorState.UNKNOWN,
            author_learner_id=None,
            confirmed_by=None,
            confirmed_at=None,
            confirmation_basis=None,
            actual_date_state=ActualDateState.UNKNOWN,
            actual_date=None,
            notes="Handwriting and work source are unreviewed.",
        ))
        observations.append(SourceObservation(observation_id, household_id, None, (revision,)))

    bundle = Bundle(
        schema_version="study-workbench.core.v0.1",
        household_id=household_id,
        images=tuple(unique_images.values()),
        regions=(),
        knowledge_items=(),
        methods=tuple(methods),
        question_types=(),
        questions=tuple(questions),
        knowledge_question_links=(),
        method_question_links=tuple(links),
        question_type_links=(),
        learners=(),
        observations=tuple(observations),
        attempts=(),
        assessments=(),
        errata=(),
    )
    validate_bundle(bundle)
    counts = {
        "index_entries": len(parsed_rows),
        "root_questions": sum(question.parent_question_id is None for question in questions),
        "question_entities": len(questions),
        "images": len(unique_images),
        "methods": len(methods),
        "primary_links": len(parsed_rows),
        "auxiliary_links": sum(len(row["aux_group_ids"]) for row in parsed_rows),
        "observations": len(observations),
    }
    return CatalogConversion(bundle, tuple(index_rows), counts)
