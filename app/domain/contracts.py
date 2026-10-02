"""Typed, offline domain records for the Study Workbench core contract.

These records describe metadata only. They do not read image bytes, execute image
transforms, persist data, or provide export/backup services.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
import hashlib
import json
import math
from typing import TypeVar


SCHEMA_VERSION = "study-workbench.core.v0.1"


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    path: str
    message: str


class ContractError(ValueError):
    """An explicit domain-contract failure, optionally with several issues."""

    def __init__(self, code: str, path: str, message: str):
        self.issues = (Issue(code, path, message),)
        super().__init__(f"{code} at {path}: {message}")


class Origin(str, Enum):
    HUMAN = "human"
    OCR = "ocr"
    AI = "ai"
    IMPORT = "import"


class ReviewState(str, Enum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STALE = "stale"
    WITHDRAWN = "withdrawn"


class NodeKind(str, Enum):
    KNOWLEDGE = "knowledge"
    METHOD = "method"
    QUESTION_TYPE = "question_type"


class Granularity(str, Enum):
    WHOLE_IMAGE = "whole_image"
    REGION = "region"


class EvidencePurpose(str, Enum):
    QUESTION = "question"
    HANDWRITING = "handwriting"
    FORMULA = "formula"
    DIAGRAM = "diagram"
    DEFINITION = "definition"
    OTHER = "other"


class AuthorState(str, Enum):
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


class Legibility(str, Enum):
    READABLE = "readable"
    PARTIAL = "partial"
    ILLEGIBLE = "illegible"
    BLANK = "blank"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ActualDateState(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class AttemptKind(str, Enum):
    FIRST = "first"
    CORRECTION = "correction"
    RETRY = "retry"
    RETEST = "retest"


class SourceKind(str, Enum):
    INDEPENDENT_ANSWER = "independent_answer"
    ASSISTED_ANSWER = "assisted_answer"
    CLASSROOM_NOTE = "classroom_note"
    COPIED_WORK = "copied_work"
    UNKNOWN = "unknown"


class Independence(str, Enum):
    CONFIRMED_INDEPENDENT = "confirmed_independent"
    NOT_INDEPENDENT = "not_independent"
    UNKNOWN = "unknown"


class PromptStatus(str, Enum):
    NONE_CONFIRMED = "none_confirmed"
    GIVEN = "given"
    UNKNOWN = "unknown"


class AttemptState(str, Enum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class DimensionKind(str, Enum):
    ANSWER = "answer"
    METHOD = "method"
    PROCESS = "process"
    CALCULATION = "calculation"
    NOTATION = "notation"


class Judgment(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class BasisKind(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNDETERMINED = "undetermined"


class ErratumTargetKind(str, Enum):
    QUESTION = "question"
    KNOWLEDGE = "knowledge"
    METHOD = "method"


@dataclass(frozen=True, slots=True)
class RevisionHeader:
    revision_id: str
    owner_id: str
    revision_no: int
    previous_revision_id: str | None
    created_by: str
    recorded_at: str
    origin: Origin
    change_reason: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    household_id: str
    image_id: str
    image_sha256: str
    granularity: Granularity
    region_id: str | None
    region_revision_id: str | None
    region_missing: bool
    purpose: EvidencePurpose
    sequence: int
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceImage:
    image_id: str
    household_id: str
    sha256: str
    storage_key: str
    media_type: str
    width: int
    height: int
    recorded_at: str


@dataclass(frozen=True, slots=True)
class RegionRevision:
    region_id: str
    household_id: str
    header: RevisionHeader
    image_id: str
    coordinate_space: str
    geometry: tuple[float, float, float, float] | None
    purpose: str


@dataclass(frozen=True, slots=True)
class KnowledgeRevision:
    header: RevisionHeader
    review_state: ReviewState
    definition: str
    conditions: tuple[str, ...]
    common_errors: tuple[str, ...]
    source_refs: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    knowledge_id: str
    household_id: str
    revisions: tuple[KnowledgeRevision, ...]


@dataclass(frozen=True, slots=True)
class MethodRevision:
    header: RevisionHeader
    review_state: ReviewState
    name: str
    conditions: tuple[str, ...]
    steps: tuple[str, ...]
    notes: tuple[str, ...]
    parent_revision_id: str | None = None
    source_refs: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class Method:
    method_id: str
    household_id: str
    revisions: tuple[MethodRevision, ...]


@dataclass(frozen=True, slots=True)
class QuestionTypeRevision:
    header: RevisionHeader
    review_state: ReviewState
    name: str
    structural_features: tuple[str, ...]
    conditions: tuple[str, ...]
    source_refs: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class QuestionType:
    question_type_id: str
    household_id: str
    revisions: tuple[QuestionTypeRevision, ...]


@dataclass(frozen=True, slots=True)
class QuestionRevision:
    header: RevisionHeader
    review_state: ReviewState
    parent_question_revision_id: str | None
    printed_text: str | None
    working_text: str | None
    missing_fields: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    erratum_revision_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Question:
    question_id: str
    household_id: str
    parent_question_id: str | None
    revisions: tuple[QuestionRevision, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeQuestionLinkRevision:
    link_id: str
    household_id: str
    header: RevisionHeader
    question_revision_id: str
    knowledge_revision_id: str
    role: str
    review_state: ReviewState


@dataclass(frozen=True, slots=True)
class MethodQuestionLinkRevision:
    link_id: str
    household_id: str
    header: RevisionHeader
    question_revision_id: str
    method_revision_id: str
    role: str
    review_state: ReviewState


@dataclass(frozen=True, slots=True)
class QuestionTypeLinkRevision:
    link_id: str
    household_id: str
    header: RevisionHeader
    question_revision_id: str
    question_type_revision_id: str
    role: str
    review_state: ReviewState


@dataclass(frozen=True, slots=True)
class LearnerProfile:
    learner_id: str
    household_id: str
    display_name: str
    grade: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationRevision:
    header: RevisionHeader
    evidence_refs: tuple[EvidenceRef, ...]
    legibility: Legibility
    author_state: AuthorState
    author_learner_id: str | None
    confirmed_by: str | None
    confirmed_at: str | None
    confirmation_basis: str | None
    actual_date_state: ActualDateState
    actual_date: str | None
    notes: str


@dataclass(frozen=True, slots=True)
class SourceObservation:
    observation_id: str
    household_id: str
    profile_context_id: str | None
    revisions: tuple[ObservationRevision, ...]


@dataclass(frozen=True, slots=True)
class ObservationRef:
    observation_id: str
    observation_revision_id: str


@dataclass(frozen=True, slots=True)
class AttemptRevision:
    header: RevisionHeader
    question_revision_id: str
    attempt_kind: AttemptKind
    source_kind: SourceKind
    independence: Independence
    prompt_status: PromptStatus
    prompts: tuple[str, ...]
    actual_date_state: ActualDateState
    actual_date: str | None
    legibility: Legibility
    answer_text: str | None
    authorship_basis: str
    observation_refs: tuple[ObservationRef, ...]
    state: AttemptState
    withdrawal_reason: str | None = None
    replacement_attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class Attempt:
    attempt_id: str
    household_id: str
    learner_id: str
    question_id: str
    previous_attempt_id: str | None
    supersedes_attempt_id: str | None
    revisions: tuple[AttemptRevision, ...]


@dataclass(frozen=True, slots=True)
class AssessmentDimension:
    dimension: DimensionKind
    judgment: Judgment
    basis: BasisKind
    evidence_refs: tuple[EvidenceRef, ...]
    rationale: str
    unknown_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AssessmentRevision:
    header: RevisionHeader
    attempt_revision_id: str
    question_revision_id: str
    review_state: ReviewState
    reviewed_by: str | None
    dimensions: tuple[AssessmentDimension, ...]
    context_erratum_revision_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Assessment:
    assessment_id: str
    household_id: str
    attempt_id: str
    revisions: tuple[AssessmentRevision, ...]


@dataclass(frozen=True, slots=True)
class ErratumRevision:
    header: RevisionHeader
    target_kind: ErratumTargetKind
    target_revision_id: str
    printed_text: str
    corrected_text: str
    basis: str
    evidence_refs: tuple[EvidenceRef, ...]
    review_state: ReviewState
    reviewed_by: str | None


@dataclass(frozen=True, slots=True)
class Erratum:
    erratum_id: str
    household_id: str
    revisions: tuple[ErratumRevision, ...]


@dataclass(frozen=True, slots=True)
class VersionRef:
    dependency_id: str
    revision_id: str


@dataclass(frozen=True, slots=True)
class NodeRef:
    kind: NodeKind
    node_id: str
    revision_id: str


class VersionCheckState(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    VERSION_CONFLICT = "version_conflict"


@dataclass(frozen=True, slots=True)
class VersionCheckResult:
    state: VersionCheckState
    expected: tuple[VersionRef, ...]
    current: tuple[VersionRef, ...]
    publishable: bool
    published_result: None = None


@dataclass(frozen=True, slots=True)
class Bundle:
    schema_version: str
    household_id: str
    images: tuple[SourceImage, ...]
    regions: tuple[RegionRevision, ...]
    knowledge_items: tuple[KnowledgeItem, ...]
    methods: tuple[Method, ...]
    question_types: tuple[QuestionType, ...]
    questions: tuple[Question, ...]
    knowledge_question_links: tuple[KnowledgeQuestionLinkRevision, ...]
    method_question_links: tuple[MethodQuestionLinkRevision, ...]
    question_type_links: tuple[QuestionTypeLinkRevision, ...]
    learners: tuple[LearnerProfile, ...]
    observations: tuple[SourceObservation, ...]
    attempts: tuple[Attempt, ...]
    assessments: tuple[Assessment, ...]
    errata: tuple[Erratum, ...]


T = TypeVar("T")


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            "_type": type(value).__name__,
            **{field.name: _plain(getattr(value, field.name)) for field in fields(value)},
        }
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ContractError("invalid_serializable_value", "value", f"unsupported or non-finite value: {type(value).__name__}")


def revision_content_hash(revision: object) -> str:
    """Return the canonical SHA-256 for a typed revision, excluding its own hash."""
    if not is_dataclass(revision) or not hasattr(revision, "header"):
        raise ContractError("invalid_revision", "revision", "expected a typed revision with a header")
    payload = _plain(revision)
    if not isinstance(payload, dict) or not isinstance(payload.get("header"), dict):
        raise ContractError("invalid_revision", "revision.header", "revision header is malformed")
    payload["header"].pop("content_hash", None)
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ContractError("invalid_revision", "revision", "revision content cannot be hashed") from exc
    return hashlib.sha256(encoded).hexdigest()


def seal_revision(revision: T) -> T:
    """Copy a revision with its canonical content hash filled in."""
    if not is_dataclass(revision) or not hasattr(revision, "header"):
        raise ContractError("invalid_revision", "revision", "expected a typed revision with a header")
    header = getattr(revision, "header")
    if not isinstance(header, RevisionHeader):
        raise ContractError("invalid_revision", "revision.header", "expected RevisionHeader")
    sealed_header = replace(header, content_hash="")
    unsealed = replace(revision, header=sealed_header)
    digest = revision_content_hash(unsealed)
    return replace(unsealed, header=replace(sealed_header, content_hash=digest))


__all__ = [
    name for name, value in globals().items()
    if isinstance(value, type) and getattr(value, "__module__", None) == __name__
]
__all__ += ["SCHEMA_VERSION", "revision_content_hash", "seal_revision"]
