"""Pure validation and trace queries for the offline core contract."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import math
import re
from typing import Iterable
from .presentation import validate_display

from .contracts import (
    ActualDateState, Assessment, AssessmentDimension, AssessmentRevision, Attempt,
    AttemptKind, AttemptRevision, AttemptState, AuthorState, BasisKind, Bundle,
    ContractError, DimensionKind, Erratum, ErratumRevision, ErratumTargetKind,
    EvidencePurpose, EvidenceRef, Granularity, Independence, Judgment,
    KnowledgeItem, KnowledgeQuestionLinkRevision, KnowledgeRevision,
    LearnerProfile, Legibility, Method, MethodQuestionLinkRevision,
    MethodRevision, NodeKind, NodeRef, ObservationRef, ObservationRevision,
    PromptStatus, Question, QuestionRevision, QuestionType,
    QuestionTypeLinkRevision, QuestionTypeRevision, RegionRevision,
    ReviewState, SCHEMA_VERSION, SourceImage, SourceKind, SourceObservation, VersionCheckResult,
    VersionCheckState, VersionRef, revision_content_hash,
)

_HEX_256 = re.compile(r"^[0-9a-f]{64}$")


def _fail(code: str, path: str, message: str) -> None:
    raise ContractError(code, path, message)


def _id(value: object, path: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail("invalid_id", path, "expected non-empty ID without surrounding whitespace")


def _text(value: object, path: str, nonempty: bool = True) -> None:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        _fail("invalid_text", path, "expected text" if not nonempty else "expected non-empty text")


def _tuple(value: object, path: str) -> tuple:
    if not isinstance(value, tuple):
        _fail("invalid_collection", path, "expected an immutable tuple")
    return value


def _strings(value: object, path: str, nonempty: bool = True) -> tuple[str, ...]:
    result = _tuple(value, path)
    for i, item in enumerate(result):
        _text(item, f"{path}[{i}]", nonempty)
    return result


def _enum(value: object, kind: type, path: str) -> None:
    if not isinstance(value, kind):
        _fail("invalid_enum", path, f"expected {kind.__name__}")


def _integer(value: object, path: str, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("invalid_integer", path, f"expected integer >= {minimum}; booleans are not integers here")


def _datetime(value: object, path: str) -> None:
    _text(value, path)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        _fail("invalid_timestamp", path, "expected ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("timezone_required", path, "timestamp must include a timezone offset")


def _date(value: object, path: str) -> None:
    _text(value, path)
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        _fail("invalid_date", path, "expected ISO calendar date YYYY-MM-DD")
    if parsed.isoformat() != value:
        _fail("invalid_date", path, "date must use canonical YYYY-MM-DD form")


def _unique(items: Iterable[object], field: str, path: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for i, item in enumerate(items):
        value = getattr(item, field, None)
        _id(value, f"{path}[{i}].{field}")
        if value in result:
            _fail("duplicate_id", f"{path}[{i}].{field}", "stable ID is duplicated")
        result[value] = item
    return result


def _typed_tuple(bundle: Bundle, field: str, cls: type) -> tuple:
    result = _tuple(getattr(bundle, field, None), f"bundle.{field}")
    for i, item in enumerate(result):
        if not isinstance(item, cls):
            _fail("invalid_entity", f"bundle.{field}[{i}]", f"expected {cls.__name__}")
    return result


def _add_revision(revision: object, owner: str, path: str, ids: dict[str, object]) -> None:
    from .contracts import Origin, RevisionHeader

    header = getattr(revision, "header", None)
    if not isinstance(header, RevisionHeader):
        _fail("invalid_revision_header", f"{path}.header", "expected RevisionHeader")
    _id(header.revision_id, f"{path}.header.revision_id")
    _id(header.owner_id, f"{path}.header.owner_id")
    if header.owner_id != owner:
        _fail("revision_owner_mismatch", f"{path}.header.owner_id", "revision belongs to another stable object")
    _integer(header.revision_no, f"{path}.header.revision_no")
    if header.previous_revision_id is not None:
        _id(header.previous_revision_id, f"{path}.header.previous_revision_id")
    _id(header.created_by, f"{path}.header.created_by")
    _datetime(header.recorded_at, f"{path}.header.recorded_at")
    _enum(header.origin, Origin, f"{path}.header.origin")
    _text(header.change_reason, f"{path}.header.change_reason")
    if not isinstance(header.content_hash, str) or not _HEX_256.fullmatch(header.content_hash):
        _fail("invalid_content_hash", f"{path}.header.content_hash", "expected lowercase SHA-256 hex digest")
    if header.revision_id in ids:
        _fail("duplicate_revision_id", f"{path}.header.revision_id", "revision ID must be unique")
    if revision_content_hash(revision) != header.content_hash:
        _fail("content_hash_mismatch", f"{path}.header.content_hash", "revision content does not match its declared hash")
    ids[header.revision_id] = revision


def _chain(owner: str, revisions: object, cls: type, path: str, ids: dict[str, object]) -> tuple:
    revisions = _tuple(revisions, f"{path}.revisions")
    if not revisions:
        _fail("empty_revision_history", f"{path}.revisions", "versioned object needs at least one revision")
    previous = None
    for i, revision in enumerate(revisions):
        item_path = f"{path}.revisions[{i}]"
        if not isinstance(revision, cls):
            _fail("invalid_revision", item_path, f"expected {cls.__name__}")
        header = getattr(revision, "header", None)
        _add_revision(revision, owner, item_path, ids)
        if header.revision_no != i + 1 or header.previous_revision_id != previous:
            _fail("revision_chain_mismatch", f"{item_path}.header", "revisions must be contiguous and point to the prior revision")
        previous = header.revision_id
    return revisions


def _flat_chains(items: tuple, owner_field: str, cls: type, path: str, ids: dict[str, object]) -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = defaultdict(list)
    for i, item in enumerate(items):
        owner = getattr(item, owner_field, None)
        _id(owner, f"{path}[{i}].{owner_field}")
        if not isinstance(item, cls):
            _fail("invalid_revision", f"{path}[{i}]", f"expected {cls.__name__}")
        _add_revision(item, owner, f"{path}[{i}]", ids)
        grouped[owner].append(item)
    for owner, rows in grouped.items():
        rows.sort(key=lambda row: row.header.revision_no)
        previous = None
        for i, row in enumerate(rows):
            if row.header.revision_no != i + 1 or row.header.previous_revision_id != previous:
                _fail("revision_chain_mismatch", path, f"revision chain for {owner} is not contiguous")
            previous = row.header.revision_id
    return grouped


def _entity_revisions(entities: tuple, id_field: str, cls: type, path: str, ids: dict[str, object]) -> dict[str, tuple[object, object]]:
    result: dict[str, tuple[object, object]] = {}
    for i, entity in enumerate(entities):
        owner = getattr(entity, id_field)
        for revision in _chain(owner, entity.revisions, cls, f"{path}[{i}]", ids):
            result[revision.header.revision_id] = (entity, revision)
    return result


def _household(entity: object, household_id: str, path: str) -> None:
    if getattr(entity, "household_id", None) != household_id:
        _fail("household_mismatch", f"{path}.household_id", "entity belongs to another household")


def _evidence(refs: object, household_id: str, images: dict, regions: dict, path: str) -> tuple[EvidenceRef, ...]:
    refs = _tuple(refs, path)
    sequences: set[int] = set()
    for i, ref in enumerate(refs):
        p = f"{path}[{i}]"
        if not isinstance(ref, EvidenceRef):
            _fail("invalid_evidence_ref", p, "expected EvidenceRef")
        _id(ref.household_id, f"{p}.household_id")
        _id(ref.image_id, f"{p}.image_id")
        if ref.household_id != household_id:
            _fail("household_mismatch", f"{p}.household_id", "evidence belongs to another household")
        image = images.get(ref.image_id)
        if image is None:
            _fail("missing_image", f"{p}.image_id", "source image does not exist")
        if not isinstance(ref.image_sha256, str) or not _HEX_256.fullmatch(ref.image_sha256):
            _fail("invalid_image_hash", f"{p}.image_sha256", "expected lowercase SHA-256 digest")
        if ref.image_sha256 != image.sha256:
            _fail("image_hash_mismatch", f"{p}.image_sha256", "evidence SHA-256 differs from source image metadata")
        _enum(ref.granularity, Granularity, f"{p}.granularity")
        _enum(ref.purpose, EvidencePurpose, f"{p}.purpose")
        if not isinstance(ref.region_missing, bool):
            _fail("invalid_boolean", f"{p}.region_missing", "expected boolean")
        _integer(ref.sequence, f"{p}.sequence")
        _strings(ref.gaps, f"{p}.gaps")
        if ref.sequence in sequences:
            _fail("duplicate_evidence_sequence", f"{p}.sequence", "sequence must be unique within this evidence list")
        sequences.add(ref.sequence)
        if ref.granularity is Granularity.WHOLE_IMAGE:
            if ref.region_id is not None or ref.region_revision_id is not None or not ref.region_missing or "region_missing" not in ref.gaps:
                _fail("whole_image_region_conflict", p, "whole-image reference must omit region IDs and explicitly retain region_missing")
        else:
            _id(ref.region_id, f"{p}.region_id")
            _id(ref.region_revision_id, f"{p}.region_revision_id")
            region = regions.get(ref.region_revision_id)
            if ref.region_missing or region is None:
                _fail("missing_region_revision", f"{p}.region_revision_id", "region reference must resolve to a known region revision")
            if region.region_id != ref.region_id or region.image_id != ref.image_id or region.geometry is None:
                _fail("region_reference_mismatch", p, "region identity, image, or geometry does not match the evidence reference")
    return refs


def validate_bundle(bundle: Bundle, *, check_snapshot_reviews: bool = True) -> None:
    """Validate immutable content and optionally its offline review snapshots.

    Persistence disables snapshot review gates and enforces actual review eligibility
    in its authenticated transaction. Types, hashes and reference integrity always apply.
    This mode does not confer acceptance or permission.
    """
    if not isinstance(bundle, Bundle):
        _fail("invalid_bundle", "bundle", "expected Bundle")
    _text(bundle.schema_version, "bundle.schema_version")
    if bundle.schema_version != SCHEMA_VERSION:
        _fail("unsupported_schema_version", "bundle.schema_version", "unsupported core-contract schema")
    _id(bundle.household_id, "bundle.household_id")
    fields = (
        ("images", SourceImage), ("regions", RegionRevision), ("knowledge_items", KnowledgeItem),
        ("methods", Method), ("question_types", QuestionType), ("questions", Question),
        ("knowledge_question_links", KnowledgeQuestionLinkRevision),
        ("method_question_links", MethodQuestionLinkRevision), ("question_type_links", QuestionTypeLinkRevision),
        ("learners", LearnerProfile), ("observations", SourceObservation), ("attempts", Attempt),
        ("assessments", Assessment), ("errata", Erratum),
    )
    values = {name: _typed_tuple(bundle, name, cls) for name, cls in fields}
    images = _unique(values["images"], "image_id", "bundle.images")
    knowledge = _unique(values["knowledge_items"], "knowledge_id", "bundle.knowledge_items")
    methods = _unique(values["methods"], "method_id", "bundle.methods")
    types = _unique(values["question_types"], "question_type_id", "bundle.question_types")
    questions = _unique(values["questions"], "question_id", "bundle.questions")
    learners = _unique(values["learners"], "learner_id", "bundle.learners")
    observations = _unique(values["observations"], "observation_id", "bundle.observations")
    attempts = _unique(values["attempts"], "attempt_id", "bundle.attempts")
    assessments = _unique(values["assessments"], "assessment_id", "bundle.assessments")
    errata = _unique(values["errata"], "erratum_id", "bundle.errata")
    ids: dict[str, object] = {}

    for i, image in enumerate(values["images"]):
        p = f"bundle.images[{i}]"
        _household(image, bundle.household_id, p)
        if not isinstance(image.sha256, str) or not _HEX_256.fullmatch(image.sha256):
            _fail("invalid_image_hash", f"{p}.sha256", "expected lowercase SHA-256 metadata")
        _text(image.storage_key, f"{p}.storage_key")
        _text(image.media_type, f"{p}.media_type")
        if not image.media_type.startswith("image/"):
            _fail("invalid_media_type", f"{p}.media_type", "expected image/* media type")
        _integer(image.width, f"{p}.width")
        _integer(image.height, f"{p}.height")
        _datetime(image.recorded_at, f"{p}.recorded_at")

    region_by_rev: dict[str, RegionRevision] = {}
    grouped_regions = _flat_chains(values["regions"], "region_id", RegionRevision, "bundle.regions", ids)
    for i, region in enumerate(values["regions"]):
        p = f"bundle.regions[{i}]"
        _household(region, bundle.household_id, p)
        _id(region.image_id, f"{p}.image_id")
        image = images.get(region.image_id)
        if image is None:
            _fail("missing_image", f"{p}.image_id", "region image does not exist")
        if region.coordinate_space != "original_pixels":
            _fail("invalid_coordinate_space", f"{p}.coordinate_space", "coordinates must use original_pixels")
        _text(region.purpose, f"{p}.purpose")
        if region.geometry is not None:
            box = region.geometry
            if not isinstance(box, tuple) or len(box) != 4:
                _fail("invalid_geometry", f"{p}.geometry", "expected four bbox coordinates")
            coords: list[float] = []
            for j, coord in enumerate(box):
                if isinstance(coord, bool) or not isinstance(coord, (int, float)):
                    _fail("invalid_coordinate", f"{p}.geometry[{j}]", "coordinate must be finite numeric data; bool is invalid")
                try:
                    numeric = float(coord)
                except (OverflowError, ValueError):
                    _fail("invalid_coordinate", f"{p}.geometry[{j}]", "coordinate is outside finite numeric range")
                if not math.isfinite(numeric):
                    _fail("invalid_coordinate", f"{p}.geometry[{j}]", "coordinate must be finite")
                coords.append(numeric)
            x0, y0, x1, y1 = coords
            if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
                _fail("geometry_out_of_bounds", f"{p}.geometry", "bbox must be non-degenerate and inside original pixels")
        region_by_rev[region.header.revision_id] = region

    k_revs = _entity_revisions(values["knowledge_items"], "knowledge_id", KnowledgeRevision, "bundle.knowledge_items", ids)
    m_revs = _entity_revisions(values["methods"], "method_id", MethodRevision, "bundle.methods", ids)
    t_revs = _entity_revisions(values["question_types"], "question_type_id", QuestionTypeRevision, "bundle.question_types", ids)
    q_revs = _entity_revisions(values["questions"], "question_id", QuestionRevision, "bundle.questions", ids)
    o_revs = _entity_revisions(values["observations"], "observation_id", ObservationRevision, "bundle.observations", ids)
    a_revs = _entity_revisions(values["attempts"], "attempt_id", AttemptRevision, "bundle.attempts", ids)
    e_revs = _entity_revisions(values["assessments"], "assessment_id", AssessmentRevision, "bundle.assessments", ids)
    err_revs = _entity_revisions(values["errata"], "erratum_id", ErratumRevision, "bundle.errata", ids)

    for group, label in ((k_revs, "knowledge"), (m_revs, "method"), (t_revs, "question type")):
        for revision_id, (entity, revision) in group.items():
            p = f"{label}.{revision_id}"
            _household(entity, bundle.household_id, p)
            _enum(revision.review_state, ReviewState, f"{p}.review_state")
            if isinstance(revision, KnowledgeRevision):
                try:
                    validate_display(revision.display_markup, revision.definition, revision.source_refs)
                except ValueError as exc:
                    _fail("invalid_display", p, str(exc))
                _text(revision.definition, f"{p}.definition", (check_snapshot_reviews and revision.review_state is ReviewState.ACCEPTED))
                _strings(revision.conditions, f"{p}.conditions")
                _strings(revision.common_errors, f"{p}.common_errors")
            elif isinstance(revision, MethodRevision):
                _text(revision.name, f"{p}.name")
                _strings(revision.conditions, f"{p}.conditions")
                _strings(revision.steps, f"{p}.steps")
                _strings(revision.notes, f"{p}.notes")
            else:
                _text(revision.name, f"{p}.name")
                _strings(revision.structural_features, f"{p}.structural_features")
                _strings(revision.conditions, f"{p}.conditions")
            _evidence(revision.source_refs, bundle.household_id, images, region_by_rev, f"{p}.source_refs")

    parent_questions: dict[str, str | None] = {}
    for i, question in enumerate(values["questions"]):
        p = f"bundle.questions[{i}]"
        _household(question, bundle.household_id, p)
        parent_questions[question.question_id] = question.parent_question_id
        if question.parent_question_id is not None:
            _id(question.parent_question_id, f"{p}.parent_question_id")
            if question.parent_question_id not in questions:
                _fail("missing_parent_question", f"{p}.parent_question_id", "parent question does not exist")
        for revision in question.revisions:
            rp = f"question_revision.{revision.header.revision_id}"
            if revision.image_print_confirmed is not None and type(revision.image_print_confirmed) is not bool:
                _fail("invalid_boolean", rp, "image print confirmation must be explicit boolean or unknown")
            try:
                validate_display(revision.display_markup, revision.working_text, revision.evidence_refs)
            except ValueError as exc:
                _fail("invalid_display", rp, str(exc))
            _enum(revision.review_state, ReviewState, f"{rp}.review_state")
            if revision.printed_text is not None:
                _text(revision.printed_text, f"{rp}.printed_text", False)
            if revision.working_text is not None:
                _text(revision.working_text, f"{rp}.working_text", False)
            missing = _strings(revision.missing_fields, f"{rp}.missing_fields")
            if (check_snapshot_reviews and revision.review_state is ReviewState.ACCEPTED) and (missing or not revision.working_text or not revision.working_text.strip()):
                _fail("incomplete_question_accepted", rp, "accepted question needs working text and no missing fields")
            parent_id = question.parent_question_id
            if (parent_id is None) != (revision.parent_question_revision_id is None):
                _fail("parent_revision_mismatch", rp, "child and parent revision references must agree")
            if parent_id is not None:
                _id(revision.parent_question_revision_id, f"{rp}.parent_question_revision_id")
                parent = q_revs.get(revision.parent_question_revision_id)
                if parent is None or parent[0].question_id != parent_id:
                    _fail("parent_revision_mismatch", rp, "pinned parent revision does not belong to the stable parent question")
            _strings(revision.erratum_revision_ids, f"{rp}.erratum_revision_ids")
            _evidence(revision.evidence_refs, bundle.household_id, images, region_by_rev, f"{rp}.evidence_refs")
    _parent_cycles(parent_questions, "bundle.questions")

    for i, learner in enumerate(values["learners"]):
        p = f"bundle.learners[{i}]"
        _household(learner, bundle.household_id, p)
        _text(learner.display_name, f"{p}.display_name")
        if learner.grade is not None:
            _text(learner.grade, f"{p}.grade")

    for i, observation in enumerate(values["observations"]):
        p = f"bundle.observations[{i}]"
        _household(observation, bundle.household_id, p)
        if observation.profile_context_id is not None:
            _id(observation.profile_context_id, f"{p}.profile_context_id")
            if observation.profile_context_id not in learners:
                _fail("missing_profile_context", f"{p}.profile_context_id", "learner profile context does not exist")
        for revision in observation.revisions:
            rp = f"observation_revision.{revision.header.revision_id}"
            _enum(revision.legibility, Legibility, f"{rp}.legibility")
            _enum(revision.author_state, AuthorState, f"{rp}.author_state")
            if revision.author_learner_id is not None:
                _id(revision.author_learner_id, f"{rp}.author_learner_id")
            if revision.author_state is AuthorState.UNKNOWN:
                if any(x is not None for x in (revision.author_learner_id, revision.confirmed_by, revision.confirmed_at, revision.confirmation_basis)):
                    _fail("unknown_author_has_confirmation", rp, "unknown author cannot contain confirmation fields")
            else:
                _id(revision.author_learner_id, f"{rp}.author_learner_id")
                if revision.author_learner_id not in learners:
                    _fail("missing_author_learner", f"{rp}.author_learner_id", "confirmed author must reference a learner")
                _id(revision.confirmed_by, f"{rp}.confirmed_by")
                _datetime(revision.confirmed_at, f"{rp}.confirmed_at")
                _text(revision.confirmation_basis, f"{rp}.confirmation_basis")
            _enum(revision.actual_date_state, ActualDateState, f"{rp}.actual_date_state")
            if revision.actual_date_state is ActualDateState.KNOWN:
                _date(revision.actual_date, f"{rp}.actual_date")
            elif revision.actual_date is not None:
                _fail("unknown_date_has_value", f"{rp}.actual_date", "unknown actual date must not be guessed")
            _text(revision.notes, f"{rp}.notes", False)
            _evidence(revision.evidence_refs, bundle.household_id, images, region_by_rev, f"{rp}.evidence_refs")

    attempt_by_id = attempts
    for i, attempt in enumerate(values["attempts"]):
        p = f"bundle.attempts[{i}]"
        _household(attempt, bundle.household_id, p)
        _id(attempt.learner_id, f"{p}.learner_id")
        _id(attempt.question_id, f"{p}.question_id")
        if attempt.learner_id not in learners or attempt.question_id not in questions:
            _fail("missing_attempt_identity", p, "attempt must reference an existing learner and question")
        pinned_question_revision: str | None = None
        for revision in attempt.revisions:
            rp = f"attempt_revision.{revision.header.revision_id}"
            _id(revision.question_revision_id, f"{rp}.question_revision_id")
            qrow = q_revs.get(revision.question_revision_id)
            if qrow is None or qrow[0].question_id != attempt.question_id:
                _fail("attempt_question_identity_mismatch", f"{rp}.question_revision_id", "question revision does not belong to immutable attempt question")
            if pinned_question_revision is None:
                pinned_question_revision = revision.question_revision_id
            elif revision.question_revision_id != pinned_question_revision:
                _fail("attempt_question_revision_rewritten", f"{rp}.question_revision_id", "an attempt keeps its original question revision; create a replacement for wrong identity")
            _enum(revision.attempt_kind, AttemptKind, f"{rp}.attempt_kind")
            _enum(revision.source_kind, SourceKind, f"{rp}.source_kind")
            _enum(revision.independence, Independence, f"{rp}.independence")
            _enum(revision.prompt_status, PromptStatus, f"{rp}.prompt_status")
            _strings(revision.prompts, f"{rp}.prompts")
            if revision.prompt_status is PromptStatus.NONE_CONFIRMED and revision.prompts:
                _fail("prompt_status_conflict", f"{rp}.prompts", "confirmed no-prompt status cannot contain prompt records")
            _enum(revision.actual_date_state, ActualDateState, f"{rp}.actual_date_state")
            if revision.actual_date_state is ActualDateState.KNOWN:
                _date(revision.actual_date, f"{rp}.actual_date")
            elif revision.actual_date is not None:
                _fail("unknown_date_has_value", f"{rp}.actual_date", "unknown actual date must not be guessed")
            _enum(revision.legibility, Legibility, f"{rp}.legibility")
            if revision.answer_text is not None:
                _text(revision.answer_text, f"{rp}.answer_text", False)
            _text(revision.authorship_basis, f"{rp}.authorship_basis")
            _enum(revision.state, AttemptState, f"{rp}.state")
            if revision.source_kind in (SourceKind.CLASSROOM_NOTE, SourceKind.COPIED_WORK) and revision.independence is Independence.CONFIRMED_INDEPENDENT:
                _fail("independence_conflict", rp, "classroom notes and copied work cannot be confirmed independent")
            if revision.source_kind is SourceKind.INDEPENDENT_ANSWER and revision.independence is Independence.NOT_INDEPENDENT:
                _fail("independence_conflict", rp, "independent-answer source cannot be labeled not independent")
            if revision.independence is Independence.CONFIRMED_INDEPENDENT and (revision.source_kind is not SourceKind.INDEPENDENT_ANSWER or revision.prompt_status is not PromptStatus.NONE_CONFIRMED):
                _fail("independence_evidence_conflict", rp, "confirmed independence requires independent source and no confirmed prompts")
            if revision.prompt_status is PromptStatus.GIVEN and revision.independence is Independence.CONFIRMED_INDEPENDENT:
                _fail("prompt_independence_conflict", rp, "prompted answer cannot be confirmed independent")
            if revision.replacement_attempt_id is not None:
                _id(revision.replacement_attempt_id, f"{rp}.replacement_attempt_id")
            if revision.state is AttemptState.WITHDRAWN:
                _text(revision.withdrawal_reason, f"{rp}.withdrawal_reason")
                if revision.withdrawal_reason == "identity_error":
                    _id(revision.replacement_attempt_id, f"{rp}.replacement_attempt_id")
            elif revision.withdrawal_reason is not None or revision.replacement_attempt_id is not None:
                _fail("active_attempt_has_withdrawal", rp, "active attempt cannot declare withdrawal metadata")
            seen: set[tuple[str, str]] = set()
            for j, obs_ref in enumerate(_tuple(revision.observation_refs, f"{rp}.observation_refs")):
                op = f"{rp}.observation_refs[{j}]"
                if not isinstance(obs_ref, ObservationRef):
                    _fail("invalid_observation_ref", op, "expected ObservationRef")
                _id(obs_ref.observation_id, f"{op}.observation_id")
                _id(obs_ref.observation_revision_id, f"{op}.observation_revision_id")
                obs = o_revs.get(obs_ref.observation_revision_id)
                if obs is None or obs[0].observation_id != obs_ref.observation_id or obs[0].household_id != attempt.household_id:
                    _fail("observation_reference_mismatch", op, "observation reference is missing or belongs to another object/household")
                pair = (obs_ref.observation_id, obs_ref.observation_revision_id)
                if pair in seen:
                    _fail("duplicate_observation_ref", op, "observation reference is duplicated")
                seen.add(pair)
        if attempt.previous_attempt_id is not None:
            _id(attempt.previous_attempt_id, f"{p}.previous_attempt_id")
            previous = attempt_by_id.get(attempt.previous_attempt_id)
            if previous is None or previous.learner_id != attempt.learner_id or previous.question_id != attempt.question_id:
                _fail("previous_attempt_identity_mismatch", f"{p}.previous_attempt_id", "previous attempt must share learner and stable question")
        if attempt.supersedes_attempt_id is not None:
            _id(attempt.supersedes_attempt_id, f"{p}.supersedes_attempt_id")
            old = attempt_by_id.get(attempt.supersedes_attempt_id)
            if old is None or old.revisions[-1].state is not AttemptState.WITHDRAWN or old.revisions[-1].withdrawal_reason != "identity_error" or old.revisions[-1].replacement_attempt_id != attempt.attempt_id:
                _fail("replacement_not_withdrawn", f"{p}.supersedes_attempt_id", "identity correction must pair a withdrawn original with its replacement")
    _parent_cycles({a.attempt_id: a.previous_attempt_id for a in values["attempts"]}, "bundle.attempts.previous_attempt_id")
    _parent_cycles({a.attempt_id: a.supersedes_attempt_id for a in values["attempts"]}, "bundle.attempts.supersedes_attempt_id")
    for attempt in values["attempts"]:
        latest = attempt.revisions[-1]
        if latest.replacement_attempt_id is not None:
            replacement = attempt_by_id.get(latest.replacement_attempt_id)
            if replacement is None or replacement.supersedes_attempt_id != attempt.attempt_id:
                _fail("replacement_link_mismatch", f"attempt.{attempt.attempt_id}", "replacement must point back to withdrawn attempt")

    # Relation edges are typed; no unchecked generic graph target is accepted.
    links_by_kind = (
        (values["knowledge_question_links"], KnowledgeQuestionLinkRevision, k_revs, "knowledge_revision_id"),
        (values["method_question_links"], MethodQuestionLinkRevision, m_revs, "method_revision_id"),
        (values["question_type_links"], QuestionTypeLinkRevision, t_revs, "question_type_revision_id"),
    )
    accepted_primary: dict[str, int] = defaultdict(int)
    for links, cls, target_revs, target_field in links_by_kind:
        groups = _flat_chains(links, "link_id", cls, f"bundle.{cls.__name__}", ids)
        for link_id, revisions in groups.items():
            for link in revisions:
                _household(link, bundle.household_id, f"link.{link_id}")
                _id(link.question_revision_id, f"link.{link_id}.question_revision_id")
                _id(getattr(link, target_field), f"link.{link_id}.{target_field}")
                qrow = q_revs.get(link.question_revision_id)
                target = target_revs.get(getattr(link, target_field))
                if qrow is None or target is None:
                    _fail("missing_link_reference", f"link.{link_id}", "typed link question or node revision does not exist")
                _text(link.role, f"link.{link_id}.role")
                _enum(link.review_state, ReviewState, f"link.{link_id}.review_state")
                if qrow[0].household_id != link.household_id or target[0].household_id != link.household_id:
                    _fail("household_mismatch", f"link.{link_id}", "link endpoints must share one household")
                if check_snapshot_reviews and link.review_state is ReviewState.ACCEPTED and (qrow[1].review_state is not ReviewState.ACCEPTED or target[1].review_state is not ReviewState.ACCEPTED):
                    _fail("accepted_link_to_unaccepted_target", f"link.{link_id}", "accepted link endpoints must also be accepted")
            latest = revisions[-1]
            if check_snapshot_reviews and isinstance(latest, MethodQuestionLinkRevision) and latest.review_state is ReviewState.ACCEPTED and latest.role == "primary":
                accepted_primary[latest.question_revision_id] += 1
    if any(count > 1 for count in accepted_primary.values()):
        _fail("multiple_primary_methods", "bundle.method_question_links", "question revision has multiple accepted primary methods")

    # Method parent graph uses exact version IDs and must be acyclic.
    method_parent = {}
    for revision_id, (method, revision) in m_revs.items():
        if revision.parent_revision_id is not None:
            _id(revision.parent_revision_id, f"method_revision.{revision_id}.parent_revision_id")
            parent = m_revs.get(revision.parent_revision_id)
            if parent is None or parent[0].household_id != method.household_id:
                _fail("missing_parent_method_revision", f"method_revision.{revision_id}.parent_revision_id", "parent revision is missing or cross-household")
            method_parent[revision_id] = revision.parent_revision_id
    _parent_cycles(method_parent, "bundle.methods")

    # Erratum versions support corrected question content; source text and old revisions stay intact.
    target_revs = {**q_revs, **k_revs, **m_revs}
    for revision_id, (erratum, revision) in err_revs.items():
        _household(erratum, bundle.household_id, f"erratum.{erratum.erratum_id}")
        _enum(revision.target_kind, ErratumTargetKind, f"erratum_revision.{revision_id}.target_kind")
        _id(revision.target_revision_id, f"erratum_revision.{revision_id}.target_revision_id")
        target = target_revs.get(revision.target_revision_id)
        if target is None:
            _fail("missing_erratum_target", f"erratum_revision.{revision_id}.target_revision_id", "target revision does not exist")
        expected = {ErratumTargetKind.QUESTION: QuestionRevision, ErratumTargetKind.KNOWLEDGE: KnowledgeRevision, ErratumTargetKind.METHOD: MethodRevision}[revision.target_kind]
        if not isinstance(target[1], expected) or target[0].household_id != erratum.household_id:
            _fail("erratum_target_mismatch", f"erratum_revision.{revision_id}.target_revision_id", "target type or household does not match")
        _text(revision.printed_text, f"erratum_revision.{revision_id}.printed_text")
        _text(revision.corrected_text, f"erratum_revision.{revision_id}.corrected_text")
        _text(revision.basis, f"erratum_revision.{revision_id}.basis")
        _enum(revision.review_state, ReviewState, f"erratum_revision.{revision_id}.review_state")
        if revision.reviewed_by is not None:
            _id(revision.reviewed_by, f"erratum_revision.{revision_id}.reviewed_by")
        if (check_snapshot_reviews and revision.review_state is ReviewState.ACCEPTED):
            _id(revision.reviewed_by, f"erratum_revision.{revision_id}.reviewed_by")
        _evidence(revision.evidence_refs, bundle.household_id, images, region_by_rev, f"erratum_revision.{revision_id}.evidence_refs")
    for qrev_id, (question, revision) in q_revs.items():
        if ((check_snapshot_reviews and revision.review_state is ReviewState.ACCEPTED) and revision.printed_text is not None
                and revision.working_text is not None and revision.printed_text != revision.working_text
                and not revision.erratum_revision_ids):
            _fail("accepted_question_missing_erratum", f"question_revision.{qrev_id}.erratum_revision_ids", "accepted corrected content must cite an accepted erratum")
        for erratum_id in revision.erratum_revision_ids:
            erratum_row = err_revs.get(erratum_id)
            if erratum_row is None:
                _fail("missing_question_erratum", f"question_revision.{qrev_id}.erratum_revision_ids", "referenced erratum revision does not exist")
            erratum, fix = erratum_row
            old_target = q_revs.get(fix.target_revision_id)
            if ((check_snapshot_reviews and fix.review_state is not ReviewState.ACCEPTED) or fix.target_kind is not ErratumTargetKind.QUESTION
                    or old_target is None or old_target[0].question_id != question.question_id
                    or old_target[1].header.revision_no >= revision.header.revision_no
                    or fix.corrected_text != revision.working_text or fix.printed_text != revision.printed_text):
                _fail("question_erratum_mismatch", f"question_revision.{qrev_id}.erratum_revision_ids", "accepted erratum must target this question and preserve printed text while supporting working text")

    for assessment in values["assessments"]:
        assessment_id = assessment.assessment_id
        _household(assessment, bundle.household_id, f"assessment.{assessment_id}")
        _id(assessment.attempt_id, f"assessment.{assessment_id}.attempt_id")
        attempt = attempts.get(assessment.attempt_id)
        if attempt is None or attempt.household_id != assessment.household_id:
            _fail("missing_assessment_attempt", f"assessment.{assessment_id}.attempt_id", "assessment attempt is missing or cross-household")
        for revision in assessment.revisions:
            rp = f"assessment_revision.{revision.header.revision_id}"
            _id(revision.attempt_revision_id, f"{rp}.attempt_revision_id")
            _id(revision.question_revision_id, f"{rp}.question_revision_id")
            attempt_row = a_revs.get(revision.attempt_revision_id)
            if attempt_row is None or attempt_row[0].attempt_id != attempt.attempt_id:
                _fail("assessment_attempt_revision_mismatch", f"{rp}.attempt_revision_id", "assessment must pin its own attempt revision")
            if attempt_row[1].question_revision_id != revision.question_revision_id:
                _fail("assessment_question_revision_mismatch", f"{rp}.question_revision_id", "assessment and attempt must pin the same question revision")
            qrow = q_revs.get(revision.question_revision_id)
            if qrow is None or qrow[0].question_id != attempt.question_id:
                _fail("assessment_question_identity_mismatch", f"{rp}.question_revision_id", "question revision does not match attempt identity")
            _enum(revision.review_state, ReviewState, f"{rp}.review_state")
            if revision.reviewed_by is not None:
                _id(revision.reviewed_by, f"{rp}.reviewed_by")
            if (check_snapshot_reviews and revision.review_state is ReviewState.ACCEPTED):
                _id(revision.reviewed_by, f"{rp}.reviewed_by")
            seen: set[DimensionKind] = set()
            for dimension in _tuple(revision.dimensions, f"{rp}.dimensions"):
                if not isinstance(dimension, AssessmentDimension):
                    _fail("invalid_assessment_dimension", f"{rp}.dimensions", "expected AssessmentDimension")
                _enum(dimension.dimension, DimensionKind, f"{rp}.dimensions")
                if dimension.dimension in seen:
                    _fail("duplicate_assessment_dimension", f"{rp}.dimensions", "dimension is duplicated")
                seen.add(dimension.dimension)
                _enum(dimension.judgment, Judgment, f"{rp}.{dimension.dimension.value}.judgment")
                _enum(dimension.basis, BasisKind, f"{rp}.{dimension.dimension.value}.basis")
                _text(dimension.rationale, f"{rp}.{dimension.dimension.value}.rationale", False)
                if dimension.unknown_reason is not None:
                    _text(dimension.unknown_reason, f"{rp}.{dimension.dimension.value}.unknown_reason")
                if dimension.judgment is Judgment.UNKNOWN:
                    _text(dimension.unknown_reason, f"{rp}.{dimension.dimension.value}.unknown_reason")
                refs = _evidence(dimension.evidence_refs, bundle.household_id, images, region_by_rev, f"{rp}.{dimension.dimension.value}.evidence_refs")
            if (check_snapshot_reviews and revision.review_state is ReviewState.ACCEPTED) and not {DimensionKind.ANSWER, DimensionKind.PROCESS}.issubset(seen):
                _fail("accepted_assessment_dimensions_missing", f"{rp}.dimensions", "accepted assessment must separately review answer and process")
            for erratum_id in _strings(revision.context_erratum_revision_ids, f"{rp}.context_erratum_revision_ids"):
                if erratum_id not in err_revs:
                    _fail("missing_assessment_erratum", f"{rp}.context_erratum_revision_ids", "assessment erratum reference does not exist")


def _parent_cycles(parents: dict[str, str | None], path: str) -> None:
    complete: set[str] = set()
    for start in parents:
        visited: set[str] = set()
        node: str | None = start
        while node is not None:
            if node in visited:
                _fail("parent_cycle", path, f"parent cycle includes {node}")
            if node in complete:
                break
            visited.add(node)
            node = parents.get(node)
        complete.update(visited)


def _latest(links: tuple) -> tuple:
    newest: dict[str, object] = {}
    for link in links:
        old = newest.get(link.link_id)
        if old is None or link.header.revision_no > old.header.revision_no:
            newest[link.link_id] = link
    return tuple(newest.values())


def _revision_index(entities: tuple, id_field: str) -> dict[str, tuple[str, object]]:
    return {revision.header.revision_id: (getattr(entity, id_field), revision)
            for entity in entities for revision in entity.revisions}


def questions_for_node(bundle: Bundle, node: NodeRef) -> tuple[QuestionRevision, ...]:
    """Return accepted question revisions attached to one exact node revision."""
    validate_bundle(bundle)
    if not isinstance(node, NodeRef):
        _fail("invalid_node_ref", "node", "expected NodeRef")
    _enum(node.kind, NodeKind, "node.kind")
    _id(node.node_id, "node.node_id")
    _id(node.revision_id, "node.revision_id")
    config = {
        NodeKind.KNOWLEDGE: (bundle.knowledge_question_links, "knowledge_revision_id", bundle.knowledge_items, "knowledge_id"),
        NodeKind.METHOD: (bundle.method_question_links, "method_revision_id", bundle.methods, "method_id"),
        NodeKind.QUESTION_TYPE: (bundle.question_type_links, "question_type_revision_id", bundle.question_types, "question_type_id"),
    }[node.kind]
    links, target_field, target_entities, target_id = config
    target_index = _revision_index(target_entities, target_id)
    target = target_index.get(node.revision_id)
    if target is None or target[0] != node.node_id:
        _fail("missing_node_revision", "node.revision_id", "typed node revision does not exist")
    q_index = _revision_index(bundle.questions, "question_id")
    found = {
        link.question_revision_id: q_index[link.question_revision_id][1]
        for link in _latest(links)
        if link.review_state is ReviewState.ACCEPTED
        and getattr(link, target_field) == node.revision_id
        and link.question_revision_id in q_index
        and q_index[link.question_revision_id][1].review_state is ReviewState.ACCEPTED
    }
    return tuple(found[key] for key in sorted(found, key=lambda key: (q_index[key][0], key)))


def questions_for_evidence(bundle: Bundle, image_id: str, region_revision_id: str | None = None) -> tuple[QuestionRevision, ...]:
    """Reverse-trace one source image or region to its accepted question revisions."""
    validate_bundle(bundle)
    _id(image_id, "image_id")
    if region_revision_id is not None:
        _id(region_revision_id, "region_revision_id")
    if image_id not in {image.image_id for image in bundle.images}:
        _fail("missing_image", "image_id", "source image does not exist")
    if region_revision_id is not None:
        region = next((row for row in bundle.regions if row.header.revision_id == region_revision_id), None)
        if region is None:
            _fail("missing_region_revision", "region_revision_id", "source region revision does not exist")
        if region.image_id != image_id:
            _fail("region_image_mismatch", "region_revision_id", "region revision belongs to a different image")
    found: dict[str, QuestionRevision] = {}
    q_index = _revision_index(bundle.questions, "question_id")
    for revision_id, (_question_id, revision) in q_index.items():
        if revision.review_state is not ReviewState.ACCEPTED:
            continue
        if any(ref.image_id == image_id and (region_revision_id is None or ref.region_revision_id == region_revision_id)
               for ref in revision.evidence_refs):
            found[revision_id] = revision
    return tuple(found[key] for key in sorted(found, key=lambda key: (q_index[key][0], key)))


def nodes_for_evidence(bundle: Bundle, image_id: str, region_revision_id: str | None = None) -> tuple[NodeRef, ...]:
    """Reverse-trace an image or region through accepted questions to typed nodes."""
    validate_bundle(bundle)
    _id(image_id, "image_id")
    if region_revision_id is not None:
        _id(region_revision_id, "region_revision_id")
    if image_id not in {image.image_id for image in bundle.images}:
        _fail("missing_image", "image_id", "source image does not exist")
    if region_revision_id is not None:
        region = next((row for row in bundle.regions if row.header.revision_id == region_revision_id), None)
        if region is None:
            _fail("missing_region_revision", "region_revision_id", "source region revision does not exist")
        if region.image_id != image_id:
            _fail("region_image_mismatch", "region_revision_id", "region revision belongs to a different image")
    q_index = _revision_index(bundle.questions, "question_id")
    image_qs = {
        qid for qid, (_owner, revision) in q_index.items()
        if revision.review_state is ReviewState.ACCEPTED
        and any(ref.image_id == image_id and (region_revision_id is None or ref.region_revision_id == region_revision_id) for ref in revision.evidence_refs)
    }
    found: set[NodeRef] = set()
    for kind, links, target_field, entities, id_field in (
        (NodeKind.KNOWLEDGE, bundle.knowledge_question_links, "knowledge_revision_id", bundle.knowledge_items, "knowledge_id"),
        (NodeKind.METHOD, bundle.method_question_links, "method_revision_id", bundle.methods, "method_id"),
        (NodeKind.QUESTION_TYPE, bundle.question_type_links, "question_type_revision_id", bundle.question_types, "question_type_id"),
    ):
        targets = _revision_index(entities, id_field)
        for link in _latest(links):
            target = targets.get(getattr(link, target_field))
            if link.review_state is ReviewState.ACCEPTED and link.question_revision_id in image_qs and target is not None:
                found.add(NodeRef(kind, target[0], getattr(link, target_field)))
    return tuple(sorted(found, key=lambda node: (node.kind.value, node.node_id, node.revision_id)))


def independent_successes(bundle: Bundle) -> tuple[Attempt, ...]:
    """Return evidence-backed attempt events; this function never infers mastery."""
    validate_bundle(bundle)
    obs_index = {rev.header.revision_id: (obs, rev) for obs in bundle.observations for rev in obs.revisions}
    assessments: dict[str, list[AssessmentRevision]] = defaultdict(list)
    for assessment in bundle.assessments:
        assessments[assessment.attempt_id].append(assessment.revisions[-1])
    successes: list[Attempt] = []
    for attempt in bundle.attempts:
        current = attempt.revisions[-1]
        if (current.state is not AttemptState.ACTIVE or current.source_kind is not SourceKind.INDEPENDENT_ANSWER
                or current.independence is not Independence.CONFIRMED_INDEPENDENT
                or current.prompt_status is not PromptStatus.NONE_CONFIRMED
                or current.actual_date_state is not ActualDateState.KNOWN or current.legibility is not Legibility.READABLE):
            continue
        verified: set[EvidenceRef] = set()
        for ref in current.observation_refs:
            _observation, observation_revision = obs_index[ref.observation_revision_id]
            if (observation_revision.author_state is AuthorState.CONFIRMED
                    and observation_revision.author_learner_id == attempt.learner_id
                    and observation_revision.legibility is Legibility.READABLE):
                verified.update(observation_revision.evidence_refs)
        if not verified:
            continue
        current_assessments = [
            assessment for assessment in assessments.get(attempt.attempt_id, ())
            if assessment.review_state is ReviewState.ACCEPTED and assessment.reviewed_by
            and assessment.attempt_revision_id == current.header.revision_id
        ]
        # Conflicting accepted review evidence stays unresolved in this contract slice.
        if any(d.judgment in (Judgment.INCORRECT, Judgment.PARTIAL)
               for assessment in current_assessments for d in assessment.dimensions):
            continue
        success = False
        for assessment in current_assessments:
            dimensions = {dimension.dimension: dimension for dimension in assessment.dimensions}
            required = (dimensions.get(DimensionKind.ANSWER), dimensions.get(DimensionKind.PROCESS))
            if any(d is None for d in required):
                continue
            if all(d.judgment is Judgment.CORRECT and d.basis is BasisKind.OBSERVED and d.evidence_refs
                   and set(d.evidence_refs).issubset(verified) for d in required):
                success = True
                break
        if success:
            successes.append(attempt)
    return tuple(sorted(successes, key=lambda attempt: attempt.attempt_id))


def compare_expected_version(expected: tuple[VersionRef, ...], current: tuple[VersionRef, ...]) -> VersionCheckResult:
    """Compare complete dependency vectors; stale/conflicting checks never publish."""
    def as_map(refs: object, path: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for i, ref in enumerate(_tuple(refs, path)):
            p = f"{path}[{i}]"
            if not isinstance(ref, VersionRef):
                _fail("invalid_version_ref", p, "expected VersionRef")
            _id(ref.dependency_id, f"{p}.dependency_id")
            _id(ref.revision_id, f"{p}.revision_id")
            if ref.dependency_id in result:
                _fail("duplicate_version_dependency", f"{p}.dependency_id", "dependency vector repeats an object")
            result[ref.dependency_id] = ref.revision_id
        return result
    expected_map, current_map = as_map(expected, "expected"), as_map(current, "current")
    if expected_map.keys() != current_map.keys():
        state = VersionCheckState.VERSION_CONFLICT
    elif expected_map == current_map:
        state = VersionCheckState.CURRENT
    else:
        state = VersionCheckState.STALE
    return VersionCheckResult(state, tuple(sorted(expected, key=lambda r: r.dependency_id)),
                              tuple(sorted(current, key=lambda r: r.dependency_id)),
                              state is VersionCheckState.CURRENT, None)
