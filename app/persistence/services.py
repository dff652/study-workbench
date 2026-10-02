"""Household-scoped persistence and append-only review transactions.

Every supported write locks the household first. This deliberately serializes
small household workloads and makes multi-object head checks atomic on PostgreSQL.
"""
from hashlib import sha256
import json

from django.contrib.auth import get_user_model
from django.db import transaction

from app.domain import Bundle, merge_bundles, serialize_bundle
from .adapter import ObjectKey, evidence_refs, load_bundle, revision_dependencies, split_bundle
from .models import (
    EntityRecord, EvidenceRecord, Household, HouseholdMember, ImageRecord,
    RequestReceipt, ReviewDecision, ReviewProjection, RevisionDependency, RevisionRecord,
)


class PersistenceError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _error(code, message):
    raise PersistenceError(code, message)


def _text(value, name, limit=160):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _error("invalid_input", f"Invalid {name}")


def require_household_access(actor, household, *, write=False):
    if not actor or not actor.pk or not get_user_model().objects.filter(pk=actor.pk, is_active=True).exists():
        _error("permission_denied", "An active household member is required")
    role = HouseholdMember.objects.filter(household=household, user=actor).values_list("role", flat=True).first()
    if not role or (write and role not in ("owner", "reviewer")):
        _error("permission_denied", "Household role does not permit this operation")


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _replay(household, actor, key, operation, fingerprint):
    _text(key, "request key")
    receipt = RequestReceipt.objects.filter(household=household, request_key=key).first()
    if receipt:
        if (receipt.operation, receipt.actor_id, receipt.request_hash) != (operation, actor.pk, fingerprint):
            _error("request_conflict", "Request key was already used for different content or actor")
        return receipt.result


def _receipt(household, actor, key, operation, fingerprint, result):
    RequestReceipt.objects.create(household=household, actor=actor, request_key=key,
                                  operation=operation, request_hash=fingerprint, result=result)
    return result


@transaction.atomic
def create_household(actor, household_id):
    _text(household_id, "household ID")
    if not actor or not actor.pk or not get_user_model().objects.filter(pk=actor.pk, is_active=True).exists():
        _error("permission_denied", "An active account is required")
    household = Household.objects.create(id=household_id)
    HouseholdMember.objects.create(household=household, user=actor, role="owner")
    return household


@transaction.atomic
def read_snapshot_bundle(actor, household_id):
    """Historical content only; embedded snapshot states do not grant publication."""
    household = Household.objects.select_for_update().get(pk=household_id)
    require_household_access(actor, household)
    return load_bundle(household)


def _vector(source_id, payloads, owners, heads):
    source_key = owners[source_id]
    visited = set()
    dependencies = set()

    def visit(revision_id):
        if revision_id in visited:
            return
        visited.add(revision_id)
        key = owners[revision_id]
        if key != source_key:
            dependencies.add(key)
        payload = payloads[revision_id]
        for _, _, target in revision_dependencies(payload):
            visit(target)
        for _, ref in evidence_refs(payload):
            if ref["region_revision_id"]:
                visit(ref["region_revision_id"])

    visit(source_id)
    return [{"kind": key.kind, "stable_id": key.stable_id, "head_revision_id": heads[key]}
            for key in sorted(dependencies)]


@transaction.atomic
def stage_bundle(actor, bundle: Bundle, *, request_key, expected_heads):
    """Persist an additive complete metadata bundle without publishing any snapshot."""
    household = Household.objects.select_for_update().get(pk=bundle.household_id)
    require_household_access(actor, household, write=True)
    if not isinstance(expected_heads, dict) or any(not isinstance(key, ObjectKey) for key in expected_heads):
        _error("invalid_input", "Expected heads must map ObjectKey to revision ID or None")
    for key, revision_id in expected_heads.items():
        _text(key.kind, "entity kind")
        _text(key.stable_id, "stable ID")
        if revision_id is not None:
            _text(revision_id, "expected head")
    fingerprint = _digest({"bundle": json.loads(serialize_bundle(bundle, check_snapshot_reviews=False)),
                           "heads": [[key.kind, key.stable_id, value] for key, value in sorted(expected_heads.items())]})
    replay = _replay(household, actor, request_key, "stage", fingerprint)
    if replay is not None:
        return replay
    entities = {ObjectKey(row.kind, row.stable_id): row for row in EntityRecord.objects.filter(household=household)}
    for key, expected in expected_heads.items():
        actual = entities[key].head_revision_id if key in entities else None
        if expected != actual:
            _error("head_conflict", "An entity head changed; reload before appending")
    existing_bundle = load_bundle(household)
    merged = merge_bundles(existing_bundle, bundle, check_snapshot_reviews=False)
    images, snapshots = split_bundle(merged)
    current_revisions = {row.pk: row for row in RevisionRecord.objects.filter(entity__household=household)}
    new_ids = {rev["header"]["revision_id"] for snap in snapshots.values() for rev in snap.revisions} - current_revisions.keys()
    for key, snap in snapshots.items():
        changed = any(rev["header"]["revision_id"] in new_ids for rev in snap.revisions)
        if key in entities and changed and key not in expected_heads:
            _error("expected_head_required", "Appending to an existing entity requires its expected head")
        if key in entities and entities[key].identity != snap.identity:
            _error("identity_conflict", "Stable identity cannot be overwritten")
    image_rows = {row.stable_id: row for row in ImageRecord.objects.filter(household=household)}
    image_count = 0
    for image in images:
        if image["image_id"] not in image_rows:
            if ImageRecord.objects.filter(household=household, sha256=image["sha256"]).exists():
                _error("duplicate_image", "Image hash already has a different stable identity")
            image_rows[image["image_id"]] = ImageRecord.objects.create(household=household,
                stable_id=image["image_id"], sha256=image["sha256"], payload=image)
            image_count += 1
    entity_count = 0
    for key, snap in snapshots.items():
        if key not in entities:
            _text(key.stable_id, "stable ID")
            entities[key] = EntityRecord.objects.create(household=household, kind=key.kind,
                                                       stable_id=key.stable_id, identity=snap.identity)
            entity_count += 1
    payloads, owners, heads = {}, {}, {}
    for key, snap in snapshots.items():
        for payload in snap.revisions:
            rid = payload["header"]["revision_id"]
            _text(rid, "revision ID")
            payloads[rid] = payload
            owners[rid] = key
        if snap.revisions:
            heads[key] = max(snap.revisions, key=lambda rev: rev["header"]["revision_no"])["header"]["revision_id"]
    if RevisionRecord.objects.filter(pk__in=new_ids).exists():
        _error("revision_conflict", "Revision ID already belongs to another household")
    for key, snap in snapshots.items():
        for payload in sorted(snap.revisions, key=lambda rev: rev["header"]["revision_no"]):
            h = payload["header"]
            if h["revision_id"] not in new_ids:
                continue
            row = RevisionRecord.objects.create(revision_id=h["revision_id"], entity=entities[key],
                revision_no=h["revision_no"], previous_id=h["previous_revision_id"], content_hash=h["content_hash"],
                payload=payload, dependency_heads=_vector(h["revision_id"], payloads, owners, heads),
                original_image=image_rows[payload["image_id"]] if key.kind == "region" else None)
            current_revisions[row.pk] = row
            ReviewProjection.objects.create(revision=row, state="draft")
    for rid in sorted(new_ids):
        payload = payloads[rid]
        for role, position, target_id in revision_dependencies(payload):
            RevisionDependency.objects.create(source_id=rid, target_id=target_id, role=role, position=position)
        for slot, ref in evidence_refs(payload):
            EvidenceRecord.objects.create(source_id=rid, image=image_rows[ref["image_id"]],
                region_id=ref["region_revision_id"], slot=slot, sequence=ref["sequence"], purpose=ref["purpose"],
                granularity=ref["granularity"], region_missing=ref["region_missing"], gaps=ref["gaps"])
    for key, head in heads.items():
        if entities[key].head_revision_id != head:
            entities[key].head_revision_id = head
            entities[key].save(update_fields=["head_revision"])
    return _receipt(household, actor, request_key, "stage", fingerprint,
                    {"images_added": image_count, "entities_added": entity_count, "revisions_added": len(new_ids)})


def _normalized_vector(vector):
    if not isinstance(vector, (list, tuple)):
        _error("dependency_conflict", "Expected dependency vector must be complete")
    normalized = []
    keys = set()
    for item in vector:
        if not isinstance(item, dict) or set(item) != {"kind", "stable_id", "head_revision_id"}:
            _error("dependency_conflict", "Invalid dependency vector entry")
        for value in item.values():
            _text(value, "dependency vector value")
        key = (item["kind"], item["stable_id"])
        if key in keys:
            _error("dependency_conflict", "Duplicate dependency vector entry")
        keys.add(key)
        normalized.append(item)
    return sorted(normalized, key=lambda item: (item["kind"], item["stable_id"]))


def _check_heads(household, vector):
    heads = {(row.kind, row.stable_id): row.head_revision_id for row in EntityRecord.objects.filter(household=household)}
    if any(heads.get((item["kind"], item["stable_id"])) != item["head_revision_id"] for item in vector):
        _error("stale_dependencies", "Dependencies changed since this revision was staged")


def _accepted(revision_id):
    return ReviewProjection.objects.filter(revision_id=revision_id, state="accepted").exists()


def _eligible(row):
    """Actual acceptance gates, independent of untrusted imported review snapshots."""
    # Revalidate stored typed content, including unknown reasons and hashes, and
    # derive the dependency closure again rather than trusting a stored subset.
    _, snapshots = split_bundle(load_bundle(row.entity.household))
    payloads, owners, heads = {}, {}, {}
    for key, snapshot in snapshots.items():
        for revision in snapshot.revisions:
            rid = revision["header"]["revision_id"]
            payloads[rid], owners[rid] = revision, key
        if snapshot.revisions:
            heads[key] = snapshot.revisions[-1]["header"]["revision_id"]
    if _vector(row.pk, payloads, owners, heads) != row.dependency_heads:
        _error("dependency_conflict", "Stored dependency vector is incomplete or no longer current")
    payload = row.payload
    kind = row.entity.kind
    if kind == "knowledge" and not payload["definition"].strip():
        _error("incomplete_content", "Accepted knowledge needs a definition")
    if kind == "question":
        if payload["missing_fields"] or not (payload["working_text"] or "").strip():
            _error("incomplete_content", "Accepted question needs complete working text")
        corrected = payload["printed_text"] is not None and payload["printed_text"] != payload["working_text"]
        if corrected and not payload["erratum_revision_ids"]:
            _error("missing_erratum", "Corrected source text needs an audited erratum")
        if any(not _accepted(rid) for rid in payload["erratum_revision_ids"]):
            _error("unaccepted_dependency", "Question errata must have actual accepted reviews")
    if kind == "assessment":
        if not {"answer", "process"}.issubset({d["dimension"] for d in payload["dimensions"]}):
            _error("incomplete_content", "Assessment must review answer and process separately")
        if any(not _accepted(rid) for rid in payload["context_erratum_revision_ids"]):
            _error("unaccepted_dependency", "Assessment context errata must have actual accepted reviews")
    if kind in ("knowledge_question", "method_question", "question_type_link"):
        for dep in row.outgoing_dependencies.select_related("target__entity"):
            if dep.target.entity.published_revision_id != dep.target_id or not _accepted(dep.target_id):
                _error("unaccepted_dependency", "Current links require actually published exact endpoints")
        if kind == "method_question" and payload["role"] == "primary":
            others = EntityRecord.objects.filter(household=row.entity.household, kind=kind,
                published_revision__isnull=False).exclude(pk=row.entity_id).select_related("published_revision")
            if any(other.published_revision.payload["role"] == "primary" and
                   other.published_revision.payload["question_revision_id"] == payload["question_revision_id"] for other in others):
                _error("multiple_primary_methods", "A question revision already has an accepted primary method")


@transaction.atomic
def review_revision(actor, household_id, revision_id, *, action, expected_head,
                    expected_dependencies, expected_decision_id, request_key, reason):
    household = Household.objects.select_for_update().get(pk=household_id)
    require_household_access(actor, household, write=True)
    _text(revision_id, "revision ID")
    _text(expected_head, "expected head")
    _text(reason, "review reason", limit=10000)
    if action not in ("accept", "reject", "withdraw"):
        _error("invalid_input", "Unknown review action")
    if expected_decision_id is not None:
        _text(expected_decision_id, "expected review decision")
    vector = _normalized_vector(expected_dependencies)
    fingerprint = _digest({"revision": revision_id, "action": action, "head": expected_head, "dependencies": vector, "previous_decision": expected_decision_id, "reason": reason})
    replay = _replay(household, actor, request_key, "review", fingerprint)
    if replay is not None:
        return replay
    row = RevisionRecord.objects.select_related("entity").filter(pk=revision_id, entity__household=household).first()
    if row is None:
        _error("missing_revision", "Revision does not exist in this household")
    current_decision = ReviewProjection.objects.get(revision=row).decision_id
    if (str(current_decision) if current_decision else None) != expected_decision_id:
        _error("review_conflict", "Review state changed before this decision")
    if row.entity.head_revision_id != expected_head:
        _error("head_conflict", "Entity head changed before review")
    if action != "withdraw" and row.pk != expected_head:
        _error("head_conflict", "Accept or reject only the current head")
    if vector != _normalized_vector(row.dependency_heads):
        _error("dependency_conflict", "The full stored dependency vector is required")
    if action == "accept":
        _check_heads(household, vector)
        _eligible(row)
        if row.entity.kind == 'question':
            from django.apps import apps
            if apps.is_installed('app.study'):
                from app.study.services import validate_variant_publication
                validate_variant_publication(actor, row.pk)
    if action == "withdraw" and row.entity.published_revision_id != row.pk:
        _error("review_conflict", "Withdraw only the currently published revision")
    decision = ReviewDecision.objects.create(household=household, revision=row, actor=actor,
        action=action, reason=reason, expected_head_id=expected_head, expected_dependencies=vector, expected_decision_id=expected_decision_id, request_key=request_key)
    # Remove publication before withdrawing/rejecting its projection so native
    # pointer guards never observe a published unaccepted row.
    if action != "accept" and row.entity.published_revision_id == row.pk:
        row.entity.published_revision_id = None
        row.entity.save(update_fields=["published_revision"])
    ReviewProjection.objects.filter(revision=row).update(state={"accept": "accepted", "reject": "rejected", "withdraw": "withdrawn"}[action], decision=decision)
    if action == "accept":
        row.entity.published_revision = row
        row.entity.save(update_fields=["published_revision"])
    return _receipt(household, actor, request_key, "review", fingerprint,
                    {"revision_id": row.pk, "state": {"accept": "accepted", "reject": "rejected", "withdraw": "withdrawn"}[action], "decision_id": str(decision.pk)})


@transaction.atomic
def review_context(actor, household_id, revision_id):
    household = Household.objects.select_for_update().get(pk=household_id)
    require_household_access(actor, household)
    row = RevisionRecord.objects.select_related("entity", "review_projection").get(pk=revision_id, entity__household=household)
    state = row.review_projection.state
    if state == "draft":
        try:
            _check_heads(household, row.dependency_heads)
        except PersistenceError:
            state = "stale"
    return {"expected_head": row.entity.head_revision_id, "expected_dependencies": row.dependency_heads,
            "expected_decision_id": str(row.review_projection.decision_id) if row.review_projection.decision_id else None, "state": state}


@transaction.atomic
def published_trace(actor, household_id, *, node=None, image_id=None, region_revision_id=None):
    """Bidirectional current node/question/image index using native publications."""
    household = Household.objects.select_for_update().get(pk=household_id)
    require_household_access(actor, household)
    if node is not None and (not isinstance(node, ObjectKey) or node.kind not in ("knowledge", "method", "question_type")):
        _error("invalid_input", "Expected a typed knowledge, method or question-type node")
    if region_revision_id is not None and image_id is None:
        _error("invalid_input", "Region query requires its image ID")
    published = {row.pk: row for row in RevisionRecord.objects.filter(
        entity__household=household, published_for_entities__isnull=False,
        review_projection__state="accepted").select_related("entity")}
    links = []
    for row in published.values():
        if row.entity.kind not in ("knowledge_question", "method_question", "question_type_link"):
            continue
        deps = list(row.outgoing_dependencies.all())
        if all(dep.target_id in published for dep in deps):
            links.append(row)
    questions = {rid for rid, row in published.items() if row.entity.kind == "question"}
    nodes = {rid for rid, row in published.items() if row.entity.kind in ("knowledge", "method", "question_type")}
    if node is not None:
        nodes = {rid for rid in nodes if (published[rid].entity.kind, published[rid].entity.stable_id) == (node.kind, node.stable_id)}
        questions = {dep.target_id for link in links if any(dep.target_id in nodes for dep in link.outgoing_dependencies.all())
                     for dep in link.outgoing_dependencies.filter(role="link_question")}
    if image_id is not None:
        refs = EvidenceRecord.objects.filter(source__entity__household=household, image__stable_id=image_id)
        if region_revision_id is not None:
            refs = refs.filter(region_id=region_revision_id)
        sourced = set(refs.values_list("source_id", flat=True))
        questions &= sourced
        nodes = (nodes & sourced) | {dep.target_id for link in links
                  if link.payload["question_revision_id"] in questions
                  for dep in link.outgoing_dependencies.exclude(role="link_question") if dep.target_id in nodes}
    if node is None and image_id is None:
        _error("invalid_input", "Supply a node or image query")
    return {"question_revision_ids": sorted(questions), "node_revision_ids": sorted(nodes),
            "evidence": [{"question_revision_id": rid, "refs": published[rid].payload["evidence_refs"]} for rid in sorted(questions)]}
