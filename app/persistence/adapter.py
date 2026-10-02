"""Closed A1a snapshot mapping; native review state never rewrites these payloads."""
from dataclasses import dataclass
import json

from app.domain import Bundle, deserialize_bundle, serialize_bundle
from .models import EntityRecord, Household, ImageRecord, RevisionRecord


# kind -> (bundle field, stable ID field, identity type, flat revision collection)
LAYOUT = {
    "knowledge": ("knowledge_items", "knowledge_id", "KnowledgeItem", False),
    "method": ("methods", "method_id", "Method", False),
    "question_type": ("question_types", "question_type_id", "QuestionType", False),
    "question": ("questions", "question_id", "Question", False),
    "observation": ("observations", "observation_id", "SourceObservation", False),
    "attempt": ("attempts", "attempt_id", "Attempt", False),
    "assessment": ("assessments", "assessment_id", "Assessment", False),
    "erratum": ("errata", "erratum_id", "Erratum", False),
    "region": ("regions", "region_id", "RegionRevision", True),
    "knowledge_question": ("knowledge_question_links", "link_id", "KnowledgeQuestionLinkRevision", True),
    "method_question": ("method_question_links", "link_id", "MethodQuestionLinkRevision", True),
    "question_type_link": ("question_type_links", "link_id", "QuestionTypeLinkRevision", True),
    "learner": ("learners", "learner_id", "LearnerProfile", False),
}


@dataclass(frozen=True, order=True)
class ObjectKey:
    kind: str
    stable_id: str


@dataclass(frozen=True)
class Snapshot:
    key: ObjectKey
    identity: dict
    revisions: tuple[dict, ...]


def split_bundle(bundle: Bundle):
    data = json.loads(serialize_bundle(bundle, check_snapshot_reviews=False))
    result = {}
    for kind, (field, id_field, _, flat) in LAYOUT.items():
        for item in data[field]:
            key = ObjectKey(kind, item[id_field])
            if flat:
                identity = {id_field: item[id_field], "household_id": item["household_id"]}
                if kind == "region":
                    identity["image_id"] = item["image_id"]
                old = result.get(key)
                revisions = old.revisions + (item,) if old else (item,)
            else:
                identity = {k: v for k, v in item.items() if k != "revisions"}
                revisions = tuple(item.get("revisions", ()))
            result[key] = Snapshot(key, identity, revisions)
    return data["images"], result


def load_bundle(household: Household) -> Bundle:
    """Internal history reader. Callers must authenticate household access first."""
    data = {"_type": "Bundle", "schema_version": household.schema_version, "household_id": household.pk}
    data["images"] = list(ImageRecord.objects.filter(household=household).order_by("stable_id").values_list("payload", flat=True))
    for field, *_ in LAYOUT.values():
        data[field] = []
    revisions = {}
    for row in RevisionRecord.objects.filter(entity__household=household).order_by("revision_no", "revision_id"):
        revisions.setdefault(row.entity_id, []).append(row.payload)
    for entity in EntityRecord.objects.filter(household=household).order_by("kind", "stable_id"):
        field, _, _, flat = LAYOUT[entity.kind]
        revs = revisions.get(entity.pk, [])
        if flat:
            data[field].extend(revs)
        elif entity.kind == "learner":
            data[field].append(entity.identity)
        else:
            data[field].append({**entity.identity, "revisions": revs})
    return deserialize_bundle(json.dumps(data), check_snapshot_reviews=False)


def revision_dependencies(payload: dict):
    """Yield (role, position, exact target revision ID) for the closed kinds."""
    kind = payload["_type"]
    singles = {
        "QuestionRevision": (("parent_question", "parent_question_revision_id"),),
        "MethodRevision": (("parent_method", "parent_revision_id"),),
        "AttemptRevision": (("attempt_question", "question_revision_id"),),
        "AssessmentRevision": (("assessment_attempt", "attempt_revision_id"), ("assessment_question", "question_revision_id")),
        "ErratumRevision": (("erratum_target", "target_revision_id"),),
        "KnowledgeQuestionLinkRevision": (("link_question", "question_revision_id"), ("link_knowledge", "knowledge_revision_id")),
        "MethodQuestionLinkRevision": (("link_question", "question_revision_id"), ("link_method", "method_revision_id")),
        "QuestionTypeLinkRevision": (("link_question", "question_revision_id"), ("link_question_type", "question_type_revision_id")),
    }
    for role, field in singles.get(kind, ()):
        if payload[field] is not None:
            yield role, 0, payload[field]
    for role, field in (("question_erratum", "erratum_revision_ids"), ("assessment_erratum", "context_erratum_revision_ids")):
        for pos, revision_id in enumerate(payload.get(field, ())):
            yield role, pos, revision_id
    for pos, ref in enumerate(payload.get("observation_refs", ())):
        yield "attempt_observation", pos, ref["observation_revision_id"]


def evidence_refs(payload: dict):
    for ref in payload.get("source_refs", payload.get("evidence_refs", ())):
        yield "source", ref
    for dimension in payload.get("dimensions", ()):
        for ref in dimension["evidence_refs"]:
            yield dimension["dimension"], ref
