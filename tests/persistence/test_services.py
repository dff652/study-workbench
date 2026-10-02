"""Independent service acceptance on real PostgreSQL, with synthetic metadata only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase

from app.domain import (
    ActualDateState, Assessment, Attempt, AttemptKind, AuthorState, ContractError,
    Erratum, ErratumRevision, ErratumTargetKind, Independence, Judgment, Legibility,
    PromptStatus, ReviewState, SourceKind, deserialize_bundle, serialize_bundle, validate_bundle,
)
from app.persistence.adapter import ObjectKey, split_bundle
from app.persistence.models import (
    EntityRecord, HouseholdMember, RequestReceipt, ReviewDecision, ReviewProjection, RevisionRecord,
)
from app.persistence.services import (
    PersistenceError, create_household, published_trace, read_snapshot_bundle,
    review_context, review_revision, stage_bundle,
)
from tests.domain.test_contract_scenarios import (
    HOUSEHOLD, make_base_bundle, make_revision, reseal, tracking_bundle,
)


class PersistenceAcceptance(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql", "Concurrency acceptance requires real PostgreSQL")
        self.actor = get_user_model().objects.create_user(username="parent-synthetic")
        self.household = create_household(self.actor, HOUSEHOLD)
        self.base = make_base_bundle()

    def stage(self, bundle=None, key="stage-initial", heads=None):
        return stage_bundle(self.actor, bundle or self.base, request_key=key, expected_heads=heads or {})

    def review(self, rid, action="accept", key=None, context=None):
        context = context or review_context(self.actor, HOUSEHOLD, rid)
        return review_revision(self.actor, HOUSEHOLD, rid, action=action,
            expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
            expected_decision_id=context["expected_decision_id"],
            request_key=key or f"{action}:{rid}", reason="Synthetic independent acceptance")

    def next_question(self, bundle, rid="question-1-r2"):
        q = bundle.questions[0]
        rev = q.revisions[-1]
        next_rev = reseal(rev, review_state=ReviewState.DRAFT,
            header=replace(rev.header, revision_id=rid, revision_no=rev.header.revision_no + 1,
                           previous_revision_id=rev.header.revision_id, content_hash="", change_reason="Synthetic append"))
        return replace(bundle, questions=(replace(q, revisions=(*q.revisions, next_rev)), *bundle.questions[1:]))

    def test_snapshot_roundtrip_does_not_auto_publish_or_rewrite_hash(self):
        self.stage()
        restored = read_snapshot_bundle(self.actor, HOUSEHOLD)
        self.assertEqual(split_bundle(restored), split_bundle(self.base))
        self.assertFalse(EntityRecord.objects.exclude(published_revision=None).exists())
        self.assertEqual(published_trace(self.actor, HOUSEHOLD, image_id="image-page-2")["question_revision_ids"], [])
        before = RevisionRecord.objects.get(pk="question-1-r1").payload
        self.review("question-1-r1")
        self.assertEqual(RevisionRecord.objects.get(pk="question-1-r1").payload, before)
        self.assertEqual(ReviewDecision.objects.count(), 1)

    def test_audited_bidirectional_trace_keeps_cross_page_region_versions(self):
        self.stage()
        self.review("knowledge-fractions-r1")
        self.review("question-1-r1")
        self.review("knowledge-fractions-to-question-1-r1-r1")
        forward = published_trace(self.actor, HOUSEHOLD, node=ObjectKey("knowledge", "knowledge-fractions"))
        reverse = published_trace(self.actor, HOUSEHOLD, image_id="image-page-2", region_revision_id="region-q1-page-2-r1")
        self.assertEqual(forward["question_revision_ids"], ["question-1-r1"])
        self.assertEqual(reverse["node_revision_ids"], ["knowledge-fractions-r1"])
        self.assertEqual([ref["sequence"] for ref in forward["evidence"][0]["refs"]], [1, 2])

    def test_stage_and_review_request_replays_are_idempotent_after_head_changes(self):
        initial = self.stage()
        review = self.review("question-1-r1")
        old_context = {"expected_head": "question-1-r1", "expected_dependencies": RevisionRecord.objects.get(pk="question-1-r1").dependency_heads, "expected_decision_id": None}
        self.stage(self.next_question(self.base), key="append", heads={ObjectKey("question", "question-1"): "question-1-r1"})
        self.assertEqual(self.stage(), initial)
        self.assertEqual(self.review("question-1-r1", context=old_context), review)
        self.assertEqual(ReviewDecision.objects.count(), 1)
        with self.assertRaises(PersistenceError) as caught:
            self.stage(self.next_question(self.base), key="stage-initial")
        self.assertEqual(caught.exception.code, "request_conflict")

    def test_draft_and_rejection_preserve_previous_publication(self):
        self.stage()
        self.review("question-1-r1")
        self.stage(self.next_question(self.base), key="append", heads={ObjectKey("question", "question-1"): "question-1-r1"})
        entity = EntityRecord.objects.get(kind="question", stable_id="question-1")
        self.assertEqual(entity.head_revision_id, "question-1-r2")
        self.assertEqual(entity.published_revision_id, "question-1-r1")
        self.review("question-1-r2", "reject")
        entity.refresh_from_db()
        self.assertEqual(entity.published_revision_id, "question-1-r1")
        self.review("question-1-r1", "withdraw")
        entity.refresh_from_db()
        self.assertIsNone(entity.published_revision_id)
        self.assertEqual(ReviewProjection.objects.get(pk="question-1-r1").state, "withdrawn")

    def test_complete_transitive_dependency_vector_and_changed_heads_block_acceptance(self):
        self.stage(tracking_bundle())
        context = review_context(self.actor, HOUSEHOLD, "assessment-1-r1")
        kinds = {item["kind"] for item in context["expected_dependencies"]}
        self.assertTrue({"attempt", "observation", "question", "region"}.issubset(kinds))
        with self.assertRaises(PersistenceError) as caught:
            self.review("assessment-1-r1", context={**context, "expected_dependencies": []})
        self.assertEqual(caught.exception.code, "dependency_conflict")
        old_region = self.base.regions[0]
        new_region = reseal(old_region, header=replace(old_region.header, revision_id="region-q1-page-1-r2", revision_no=2,
            previous_revision_id=old_region.header.revision_id, content_hash=""), geometry=(50.0, 110.0, 650.0, 550.0))
        changed = replace(tracking_bundle(), regions=(*self.base.regions, new_region))
        self.stage(changed, key="change-region", heads={ObjectKey("region", old_region.region_id): old_region.header.revision_id})
        self.assertEqual(review_context(self.actor, HOUSEHOLD, "assessment-1-r1")["state"], "stale")
        with self.assertRaises(PersistenceError) as caught:
            self.review("assessment-1-r1", context=context)
        self.assertEqual(caught.exception.code, "stale_dependencies")
        self.assertFalse(ReviewDecision.objects.exists())
        self.assertEqual(ReviewProjection.objects.get(pk="assessment-1-r1").state, "draft")

    def test_unknown_blank_and_classroom_or_prompted_work_are_preserved(self):
        unknown = tracking_bundle(source=SourceKind.CLASSROOM_NOTE, independence=Independence.UNKNOWN,
            prompt_status=PromptStatus.UNKNOWN, actual_date_state=ActualDateState.UNKNOWN, actual_date=None,
            attempt_legibility=Legibility.UNKNOWN, observation_legibility=Legibility.UNKNOWN,
            answer_text=None, author_state=AuthorState.UNKNOWN, author_learner_id=None,
            answer=Judgment.UNKNOWN, process=Judgment.UNKNOWN, review_state=ReviewState.DRAFT)
        self.stage(unknown)
        self.review("assessment-1-r1")
        restored = read_snapshot_bundle(self.actor, HOUSEHOLD)
        self.assertEqual(restored.attempts[0], unknown.attempts[0])
        self.assertEqual(restored.observations[0], unknown.observations[0])
        self.assertTrue(all(d.judgment is Judgment.UNKNOWN for d in restored.assessments[0].revisions[0].dimensions))
        self.assertEqual(restored.assessments[0].revisions[0].review_state, ReviewState.DRAFT)

    def test_two_attempts_and_assessment_revisions_never_overwrite_each_other(self):
        bundle = tracking_bundle()
        first = bundle.attempts[0]
        second_rev = reseal(first.revisions[0], header=replace(first.revisions[0].header, owner_id="attempt-2", revision_id="attempt-2-r1", content_hash=""),
            attempt_kind=AttemptKind.RETEST, source_kind=SourceKind.ASSISTED_ANSWER,
            independence=Independence.NOT_INDEPENDENT, prompt_status=PromptStatus.GIVEN, prompts=("Synthetic hint",))
        second = replace(first, attempt_id="attempt-2", previous_attempt_id=first.attempt_id, revisions=(second_rev,))
        a1 = bundle.assessments[0]
        a2rev = reseal(a1.revisions[0], header=replace(a1.revisions[0].header, owner_id="assessment-2", revision_id="assessment-2-r1", content_hash=""), attempt_revision_id=second_rev.header.revision_id)
        a2 = Assessment("assessment-2", HOUSEHOLD, second.attempt_id, (a2rev,))
        bundle = replace(bundle, attempts=(first, second), assessments=(a1, a2))
        self.stage(bundle)
        changed_revision = reseal(a1.revisions[0], header=replace(a1.revisions[0].header, revision_id="assessment-1-r2", revision_no=2,
            previous_revision_id="assessment-1-r1", content_hash=""), dimensions=tuple(replace(d, judgment=Judgment.PARTIAL) for d in a1.revisions[0].dimensions))
        changed = replace(bundle, assessments=(replace(a1, revisions=(*a1.revisions, changed_revision)), a2))
        self.stage(changed, key="append-assessment", heads={ObjectKey("assessment", "assessment-1"): "assessment-1-r1"})
        restored = read_snapshot_bundle(self.actor, HOUSEHOLD)
        self.assertEqual(restored.attempts, bundle.attempts)
        self.assertEqual(restored.assessments[0].revisions[0], a1.revisions[0])
        self.assertEqual(len(restored.assessments[0].revisions), 2)
        self.assertEqual(restored.assessments[1], a2)

    def test_audited_draft_erratum_can_correct_new_question_without_changing_old_attempt(self):
        base = tracking_bundle()
        self.stage(base)
        q = base.questions[0]
        old = q.revisions[0]
        fix = make_revision(ErratumRevision, "fix-1", "fix-1-r1", target_kind=ErratumTargetKind.QUESTION,
            target_revision_id=old.header.revision_id, printed_text=old.printed_text,
            corrected_text="Compute 1/3 + 1/3.", basis="Synthetic source correction",
            evidence_refs=old.evidence_refs, review_state=ReviewState.DRAFT, reviewed_by=None)
        with_fix = replace(base, errata=(Erratum("fix-1", HOUSEHOLD, (fix,)),))
        self.stage(with_fix, key="add-fix")
        self.review("fix-1-r1")
        newer = reseal(old, header=replace(old.header, revision_id="question-1-r2", revision_no=2,
            previous_revision_id=old.header.revision_id, content_hash=""), review_state=ReviewState.DRAFT,
            working_text=fix.corrected_text, erratum_revision_ids=(fix.header.revision_id,))
        corrected = replace(with_fix, questions=(replace(q, revisions=(old, newer)), *base.questions[1:]))
        self.stage(corrected, key="correct-question", heads={ObjectKey("question", q.question_id): old.header.revision_id})
        self.review("question-1-r2")
        restored = read_snapshot_bundle(self.actor, HOUSEHOLD)
        self.assertEqual(restored.attempts[0].revisions[0].question_revision_id, old.header.revision_id)
        self.assertEqual(restored.questions[0].revisions[0], old)
        self.assertEqual(restored.errata[0].revisions[0], fix)
        encoded = serialize_bundle(restored, check_snapshot_reviews=False)
        self.assertEqual(deserialize_bundle(encoded, check_snapshot_reviews=False), restored)
        with self.assertRaises(ContractError):
            validate_bundle(restored)  # Offline snapshots still require offline acceptance.

    def test_incomplete_snapshots_and_unaudited_link_endpoints_cannot_publish(self):
        self.stage()
        with self.assertRaises(PersistenceError) as caught:
            self.review("knowledge-fractions-to-question-1-r1-r1")
        self.assertEqual(caught.exception.code, "unaccepted_dependency")
        changed = self.next_question(self.base)
        q = changed.questions[0]
        incomplete = reseal(q.revisions[-1], working_text=None, missing_fields=("working_text",))
        changed = replace(changed, questions=(replace(q, revisions=(q.revisions[0], incomplete)), *changed.questions[1:]))
        self.stage(changed, key="append-incomplete", heads={ObjectKey("question", q.question_id): "question-1-r1"})
        with self.assertRaises(PersistenceError) as caught:
            self.review("question-1-r2")
        self.assertEqual(caught.exception.code, "incomplete_content")
        self.assertFalse(ReviewDecision.objects.exists())

    def test_household_roles_and_inactive_accounts_guard_history_and_writes(self):
        self.stage()
        viewer = get_user_model().objects.create_user(username="viewer-synthetic")
        HouseholdMember.objects.create(household=self.household, user=viewer, role="viewer")
        self.assertEqual(len(read_snapshot_bundle(viewer, HOUSEHOLD).questions), 2)
        with self.assertRaises(PersistenceError):
            stage_bundle(viewer, self.base, request_key="viewer-write", expected_heads={})
        outsider = get_user_model().objects.create_user(username="outsider-synthetic")
        create_household(outsider, "other-household")
        with self.assertRaises(PersistenceError):
            read_snapshot_bundle(outsider, HOUSEHOLD)
        with self.assertRaises(PersistenceError):
            review_revision(viewer, HOUSEHOLD, "question-1-r1", action="accept", expected_head="question-1-r1",
                expected_dependencies=RevisionRecord.objects.get(pk="question-1-r1").dependency_heads, expected_decision_id=None, request_key="viewer-review", reason="Synthetic")
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
        with self.assertRaises(PersistenceError):
            self.stage(key="inactive-write")

    def test_outer_transaction_and_late_receipt_failure_roll_back_every_review_effect(self):
        self.stage()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.review("question-1-r1")
                raise RuntimeError("Synthetic caller failure")
        self.assertFalse(ReviewDecision.objects.exists())
        self.assertEqual(ReviewProjection.objects.get(pk="question-1-r1").state, "draft")
        self.assertIsNone(EntityRecord.objects.get(kind="question", stable_id="question-1").published_revision_id)
        with patch("app.persistence.services._receipt", side_effect=RuntimeError("Synthetic late failure")):
            with self.assertRaises(RuntimeError):
                self.review("question-1-r1")
        self.assertFalse(ReviewDecision.objects.exists())
        self.assertEqual(RequestReceipt.objects.count(), 1)
        self.assertIsNone(EntityRecord.objects.get(kind="question", stable_id="question-1").published_revision_id)

    def test_missing_or_old_expected_head_blocks_append_without_partial_records(self):
        self.stage()
        updated = self.next_question(self.base)
        for heads, code in (({}, "expected_head_required"), ({ObjectKey("question", "question-1"): None}, "head_conflict")):
            with self.assertRaises(PersistenceError) as caught:
                self.stage(updated, key=f"bad:{code}", heads=heads)
            self.assertEqual(caught.exception.code, code)
        self.assertFalse(RevisionRecord.objects.filter(pk="question-1-r2").exists())
        self.assertEqual(RequestReceipt.objects.count(), 1)

    def test_structural_validation_mode_still_rejects_modified_hashes_and_wrong_refs(self):
        q = self.base.questions[0]
        bad = replace(q.revisions[0], working_text="Tampered without resealing")
        with self.assertRaises(ContractError):
            self.stage(replace(self.base, questions=(replace(q, revisions=(bad,)), *self.base.questions[1:])))
        self.assertFalse(RevisionRecord.objects.exists())

    def test_postgresql_competing_appends_allow_one_writer_and_reject_one_stale_head(self):
        self.stage()
        barrier = threading.Barrier(2)
        def append(rid):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                barrier.wait(timeout=10)
                stage_bundle(actor, self.next_question(self.base, rid), request_key=f"append:{rid}",
                             expected_heads={ObjectKey("question", "question-1"): "question-1-r1"})
                return "ok"
            except PersistenceError as exc:
                return exc.code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(append, ("question-1-r2-a", "question-1-r2-b")))
        self.assertCountEqual(results, ["ok", "head_conflict"])
        self.assertEqual(RevisionRecord.objects.filter(entity__kind="question", entity__stable_id="question-1").count(), 2)

    def test_postgresql_competing_reviews_require_current_audit_cursor(self):
        self.stage()
        context = review_context(self.actor, HOUSEHOLD, "question-1-r1")
        barrier = threading.Barrier(2)
        def review(action):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                barrier.wait(timeout=10)
                review_revision(actor, HOUSEHOLD, "question-1-r1", action=action,
                    expected_head=context["expected_head"], expected_dependencies=context["expected_dependencies"],
                    expected_decision_id=context["expected_decision_id"], request_key=f"race:{action}", reason="Synthetic race")
                return "ok"
            except PersistenceError as exc:
                return exc.code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(review, ("accept", "reject")))
        self.assertCountEqual(results, ["ok", "review_conflict"])
        self.assertEqual(ReviewDecision.objects.count(), 1)

    def test_late_accept_cannot_undo_a_withdrawal_without_current_audit_cursor(self):
        self.stage()
        self.review("question-1-r1")
        context = review_context(self.actor, HOUSEHOLD, "question-1-r1")
        self.review("question-1-r1", "withdraw")
        with self.assertRaises(PersistenceError) as caught:
            self.review("question-1-r1", key="late-accept", context=context)
        self.assertEqual(caught.exception.code, "review_conflict")
        self.assertEqual(ReviewDecision.objects.count(), 2)
        self.assertIsNone(EntityRecord.objects.get(kind="question", stable_id="question-1").published_revision_id)
