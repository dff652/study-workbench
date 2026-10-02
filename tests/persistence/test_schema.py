import hashlib
import uuid

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from app.domain import contracts
from app.persistence.models import (
    EntityRecord,
    EvidenceRecord,
    Household,
    HouseholdMember,
    ImageRecord,
    RequestReceipt,
    ReviewDecision,
    ReviewProjection,
    RevisionDependency,
    RevisionRecord,
)


class PersistenceSchemaTests(TestCase):
    def setUp(self):
        self.household = Household.objects.create(id="synthetic-home")
        self.user = get_user_model().objects.create_user(username="reviewer", password="unused")
        HouseholdMember.objects.create(
            household=self.household, user=self.user, role=HouseholdMember.Role.OWNER
        )
        self.image = self.make_image(self.household, "image-1")

    def make_image(self, household, stable_id):
        return ImageRecord.objects.create(
            household=household,
            stable_id=stable_id,
            sha256=hashlib.sha256(stable_id.encode()).hexdigest(),
            payload={"width": 100, "height": 80, "storage_key": f"synthetic/{stable_id}.jpg"},
        )

    def make_entity(self, kind, stable_id, household=None):
        return EntityRecord.objects.create(
            household=household or self.household,
            kind=kind,
            stable_id=stable_id,
            identity={"stable_id": stable_id},
        )

    def make_revision(
        self,
        entity,
        revision=None,
        revision_id=None,
        number=1,
        previous=None,
        image=None,
        dependency_heads=None,
    ):
        revision_id = revision_id or f"rev-{uuid.uuid4()}"
        header = contracts.RevisionHeader(
            revision_id=revision_id,
            owner_id=entity.stable_id,
            revision_no=number,
            previous_revision_id=previous.revision_id if previous else None,
            created_by="synthetic-user",
            recorded_at="2026-10-02T00:00:00+00:00",
            origin=contracts.Origin.HUMAN,
            change_reason="synthetic schema fixture",
            content_hash="",
        )
        if revision is None:
            revision = contracts.QuestionRevision(
                header=header,
                review_state=contracts.ReviewState.DRAFT,
                parent_question_revision_id=None,
                printed_text="Synthetic question",
                working_text="Synthetic question",
                missing_fields=(),
                evidence_refs=(),
            )
        else:
            revision = revision(header)
        sealed = contracts.seal_revision(revision)
        row = RevisionRecord.objects.create(
            revision_id=revision_id,
            entity=entity,
            revision_no=number,
            previous=previous,
            content_hash=sealed.header.content_hash,
            payload=contracts._plain(sealed),
            dependency_heads=dependency_heads or [],
            original_image=image,
        )
        ReviewProjection.objects.create(revision=row)
        EntityRecord.objects.filter(pk=entity.pk).update(head_revision=row)
        return row

    def make_question_revision(self, entity, **kwargs):
        def build(header):
            return contracts.QuestionRevision(
                header=header,
                review_state=contracts.ReviewState.DRAFT,
                parent_question_revision_id=None,
                printed_text="Synthetic question",
                working_text="Synthetic question",
                missing_fields=(),
                evidence_refs=(),
            )

        return self.make_revision(entity, revision=build, **kwargs)

    def make_method_revision(self, entity, **kwargs):
        def build(header):
            return contracts.MethodRevision(
                header=header,
                review_state=contracts.ReviewState.DRAFT,
                name="Synthetic method",
                conditions=(),
                steps=("Synthetic step",),
                notes=(),
            )

        return self.make_revision(entity, revision=build, **kwargs)

    def make_region_revision(self, entity, image=None, **kwargs):
        image = image or self.image

        def build(header):
            return contracts.RegionRevision(
                region_id=entity.stable_id,
                household_id=self.household.id,
                header=header,
                image_id=image.stable_id,
                coordinate_space="original_pixels",
                geometry=(1, 2, 20, 30),
                purpose="question",
            )

        return self.make_revision(entity, revision=build, image=image, **kwargs)

    def make_decision(
        self,
        revision,
        actor=None,
        action=ReviewDecision.Action.ACCEPT,
        request_key=None,
        expected_head=None,
        expected_decision=None,
        expected_dependencies=None,
    ):
        return ReviewDecision.objects.create(
            household=self.household,
            revision=revision,
            actor=actor or self.user,
            action=action,
            reason="Synthetic review",
            expected_head=expected_head or revision,
            expected_decision=expected_decision,
            expected_dependencies=revision.dependency_heads if expected_dependencies is None else expected_dependencies,
            request_key=request_key or f"request-{uuid.uuid4()}",
        )

    def assert_database_rejects(self, operation):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                operation()
                connection.check_constraints()

    @staticmethod
    def raw_delete(model, pk):
        table = connection.ops.quote_name(model._meta.db_table)
        column = connection.ops.quote_name(model._meta.pk.column)
        with connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table} WHERE {column} = %s", [pk])

    def test_migrations_create_postgresql_tables_and_guards(self):
        self.assertEqual(EntityRecord._meta.db_table, "swb_entityrecord")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tgname FROM pg_trigger "
                "WHERE NOT tgisinternal AND tgname IN ('swb_immutable_revision', 'swb_revision_typed', 'swb_decision_actor')"
            )
            names = {row[0] for row in cursor.fetchall()}
        self.assertEqual(names, {"swb_immutable_revision", "swb_revision_typed", "swb_decision_actor"})

    def test_missing_foreign_key_and_duplicate_revision_number_are_rejected(self):
        entity = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-1")
        revision = self.make_question_revision(entity)

        self.assert_database_rejects(
            lambda: HouseholdMember.objects.create(
                household=self.household, user_id=987654321, role=HouseholdMember.Role.OWNER
            )
        )
        self.assert_database_rejects(
            lambda: RevisionDependency.objects.create(
                source=revision, target_id="missing-revision", role=RevisionDependency.Role.PARENT_QUESTION, position=0
            )
        )
        self.assert_database_rejects(lambda: self.make_question_revision(entity, revision_id="duplicate-no-1"))

    def test_invalid_entity_kind_and_dependency_role_are_rejected(self):
        self.assert_database_rejects(
            lambda: EntityRecord.objects.create(
                household=self.household, kind="arbitrary", stable_id="bad-kind", identity={}
            )
        )
        question = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-2")
        question_revision = self.make_question_revision(question)
        method = self.make_entity(EntityRecord.EntityKind.METHOD, "method-1")
        method_revision = self.make_method_revision(method)
        self.assert_database_rejects(
            lambda: RevisionDependency.objects.create(
                source=question_revision,
                target=method_revision,
                role=RevisionDependency.Role.PARENT_QUESTION,
                position=0,
            )
        )
        self.assert_database_rejects(
            lambda: RevisionDependency.objects.create(
                source=question_revision, target=question_revision, role="arbitrary", position=0
            )
        )

    def test_dependency_guards_require_same_household_and_permitted_typed_edge(self):
        first = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-a")
        second = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-b")
        first_revision = self.make_question_revision(first)
        second_revision = self.make_question_revision(second)
        dependency = RevisionDependency.objects.create(
            source=first_revision,
            target=second_revision,
            role=RevisionDependency.Role.PARENT_QUESTION,
            position=0,
        )
        self.assertIsNotNone(dependency.pk)

        other_household = Household.objects.create(id="other-home")
        foreign_question = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-foreign", household=other_household)
        foreign_revision = self.make_question_revision(foreign_question)
        self.assert_database_rejects(
            lambda: RevisionDependency.objects.create(
                source=first_revision,
                target=foreign_revision,
                role=RevisionDependency.Role.PARENT_QUESTION,
                position=1,
            )
        )

    def test_evidence_guards_enforce_household_kind_slot_and_region_geometry(self):
        question = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-evidence")
        source = self.make_question_revision(question)
        whole = EvidenceRecord.objects.create(
            source=source,
            image=self.image,
            slot=EvidenceRecord.Slot.SOURCE,
            sequence=1,
            purpose=EvidenceRecord.Purpose.QUESTION,
            granularity=EvidenceRecord.Granularity.WHOLE_IMAGE,
            region_missing=True,
            gaps=["region_missing"],
        )
        self.assertEqual(whole.source_id, source.revision_id)

        region = self.make_entity(EntityRecord.EntityKind.REGION, "region-1")
        region_revision = self.make_region_revision(region)
        EvidenceRecord.objects.create(
            source=source,
            image=self.image,
            region=region_revision,
            slot=EvidenceRecord.Slot.SOURCE,
            sequence=2,
            purpose=EvidenceRecord.Purpose.QUESTION,
            granularity=EvidenceRecord.Granularity.REGION,
            region_missing=False,
            gaps=[],
        )

        other_household = Household.objects.create(id="evidence-other-home")
        foreign_image = self.make_image(other_household, "foreign-image")
        self.assert_database_rejects(
            lambda: EvidenceRecord.objects.create(
                source=source,
                image=foreign_image,
                slot=EvidenceRecord.Slot.SOURCE,
                sequence=3,
                purpose=EvidenceRecord.Purpose.QUESTION,
                granularity=EvidenceRecord.Granularity.WHOLE_IMAGE,
                region_missing=True,
                gaps=["region_missing"],
            )
        )
        self.assert_database_rejects(
            lambda: EvidenceRecord.objects.create(
                source=source,
                image=self.image,
                slot=EvidenceRecord.Slot.ANSWER,
                sequence=4,
                purpose=EvidenceRecord.Purpose.HANDWRITING,
                granularity=EvidenceRecord.Granularity.WHOLE_IMAGE,
                region_missing=True,
                gaps=["region_missing"],
            )
        )
        self.assert_database_rejects(
            lambda: EvidenceRecord.objects.create(
                source=source,
                image=self.image,
                region=source,
                slot=EvidenceRecord.Slot.SOURCE,
                sequence=5,
                purpose=EvidenceRecord.Purpose.QUESTION,
                granularity=EvidenceRecord.Granularity.REGION,
                region_missing=False,
                gaps=[],
            )
        )

    def test_revision_guard_checks_snapshot_kind_and_predecessor_owner(self):
        first_entity = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-first")
        first_revision = self.make_question_revision(first_entity)
        second_entity = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-second")
        self.assert_database_rejects(
            lambda: self.make_question_revision(
                second_entity, revision_id="cross-owner-rev-2", number=2, previous=first_revision
            )
        )

        wrong_kind = self.make_entity(EntityRecord.EntityKind.METHOD, "method-wrong-snapshot")
        self.assert_database_rejects(lambda: self.make_question_revision(wrong_kind, revision_id="wrong-snapshot"))

    def test_head_must_be_latest_and_entity_identity_cannot_be_deleted(self):
        question = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-head-chain")
        first = self.make_question_revision(question, revision_id="question-head-1")
        second = self.make_question_revision(
            question, revision_id="question-head-2", number=2, previous=first
        )
        self.assert_database_rejects(
            lambda: EntityRecord.objects.filter(pk=question.pk).update(head_revision=first)
        )
        self.assert_database_rejects(
            lambda: EntityRecord.objects.filter(pk=question.pk).update(head_revision=None)
        )
        self.assertEqual(EntityRecord.objects.get(pk=question.pk).head_revision_id, second.revision_id)
        self.assert_database_rejects(lambda: EntityRecord.objects.filter(pk=question.pk).delete())
        self.assert_database_rejects(
            lambda: EntityRecord.objects.filter(pk=question.pk).update(stable_id="rewritten-identity")
        )

        learner = self.make_entity(EntityRecord.EntityKind.LEARNER, "learner-no-revision")
        self.assert_database_rejects(lambda: self.make_question_revision(learner))
        self.assert_database_rejects(lambda: self.raw_delete(EntityRecord, learner.pk))

    def test_entity_pointer_guards_require_same_owner_and_accepted_projection(self):
        question = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-pointer")
        revision = self.make_question_revision(question)
        question.head_revision = revision
        question.save(update_fields=("head_revision",))

        other = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-pointer-other")
        other_revision = self.make_question_revision(other)
        self.assert_database_rejects(
            lambda: EntityRecord.objects.filter(pk=question.pk).update(head_revision=other_revision)
        )
        self.assert_database_rejects(
            lambda: EntityRecord.objects.filter(pk=question.pk).update(published_revision=revision)
        )

        decision = self.make_decision(revision)
        ReviewProjection.objects.filter(revision=revision).update(state=ReviewProjection.State.ACCEPTED, decision=decision)
        EntityRecord.objects.filter(pk=question.pk).update(published_revision=revision)
        self.assertEqual(EntityRecord.objects.get(pk=question.pk).published_revision_id, revision.revision_id)

    def test_review_actor_and_projection_action_are_guarded(self):
        question = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-review")
        revision = self.make_question_revision(question)
        viewer = get_user_model().objects.create_user(username="viewer", password="unused")
        HouseholdMember.objects.create(household=self.household, user=viewer, role=HouseholdMember.Role.VIEWER)
        self.assert_database_rejects(lambda: self.make_decision(revision, actor=viewer))

        accepted_by_rejection = self.make_decision(
            revision, action=ReviewDecision.Action.REJECT, request_key="reject-question"
        )
        self.assert_database_rejects(
            lambda: ReviewProjection.objects.filter(revision=revision).update(
                state=ReviewProjection.State.ACCEPTED, decision=accepted_by_rejection
            )
        )

        self.assert_database_rejects(
            lambda: ReviewProjection.objects.filter(revision=revision).update(
                state=ReviewProjection.State.ACCEPTED, decision=None
            )
        )

        inactive_owner = get_user_model().objects.create_user(
            username="inactive-owner", password="unused", is_active=False
        )
        HouseholdMember.objects.create(household=self.household, user=inactive_owner, role=HouseholdMember.Role.OWNER)
        self.assert_database_rejects(lambda: self.make_decision(revision, actor=inactive_owner))
        self.assert_database_rejects(
            lambda: RequestReceipt.objects.create(
                household=self.household,
                request_key="viewer-receipt",
                operation=RequestReceipt.Operation.STAGE,
                actor=viewer,
                request_hash=hashlib.sha256(b"viewer").hexdigest(),
                result={},
            )
        )

    def test_projection_cannot_invalidate_a_published_revision(self):
        question = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-published")
        revision = self.make_question_revision(question)
        decision = self.make_decision(revision)
        ReviewProjection.objects.filter(revision=revision).update(state=ReviewProjection.State.ACCEPTED, decision=decision)
        EntityRecord.objects.filter(pk=question.pk).update(published_revision=revision)
        self.assert_database_rejects(
            lambda: ReviewProjection.objects.filter(revision=revision).update(state=ReviewProjection.State.STALE)
        )

    def test_review_requires_current_head_projection_decision_and_dependency_vector(self):
        dependency = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-dependency")
        dependency_revision = self.make_question_revision(dependency, revision_id="dependency-rev-1")
        source_entity = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-with-vector")
        vector = [{
            "kind": EntityRecord.EntityKind.QUESTION,
            "stable_id": dependency.stable_id,
            "head_revision_id": dependency_revision.revision_id,
        }]
        source = self.make_question_revision(
            source_entity, revision_id="question-vector-rev-1", dependency_heads=vector
        )

        self.assert_database_rejects(lambda: self.make_decision(source, expected_dependencies=[]))
        self.make_question_revision(
            dependency, revision_id="dependency-rev-2", number=2, previous=dependency_revision
        )
        self.assert_database_rejects(lambda: self.make_decision(source))

        first = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-stale-head")
        first_revision = self.make_question_revision(first, revision_id="stale-head-1")
        second_revision = self.make_question_revision(
            first, revision_id="stale-head-2", number=2, previous=first_revision
        )
        self.assert_database_rejects(
            lambda: self.make_decision(first_revision, expected_head=first_revision)
        )
        self.assert_database_rejects(
            lambda: self.make_decision(second_revision, expected_head=first_revision)
        )

    def test_review_decision_chain_rejects_stale_successor_and_withdraws_published_revision(self):
        question = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-decision-chain")
        revision = self.make_question_revision(question)
        first = self.make_decision(revision)
        ReviewProjection.objects.filter(revision=revision).update(
            state=ReviewProjection.State.ACCEPTED, decision=first
        )
        EntityRecord.objects.filter(pk=question.pk).update(published_revision=revision)

        self.assert_database_rejects(lambda: self.make_decision(revision, expected_decision=None))
        withdrawal = self.make_decision(
            revision,
            action=ReviewDecision.Action.WITHDRAW,
            expected_decision=first,
            request_key="withdraw-published",
        )
        EntityRecord.objects.filter(pk=question.pk).update(published_revision=None)
        ReviewProjection.objects.filter(revision=revision).update(
            state=ReviewProjection.State.WITHDRAWN, decision=withdrawal
        )

        self.assert_database_rejects(
            lambda: self.make_decision(
                revision,
                expected_decision=first,
                request_key="late-accept-after-withdraw",
            )
        )
        self.assert_database_rejects(
            lambda: ReviewProjection.objects.filter(revision=revision).update(
                state=ReviewProjection.State.ACCEPTED, decision=first
            )
        )
        self.assert_database_rejects(lambda: self.raw_delete(ReviewProjection, revision.revision_id))

    def test_append_only_tables_reject_orm_update_and_delete(self):
        question = self.make_entity(EntityRecord.EntityKind.QUESTION, "question-immutable")
        revision = self.make_question_revision(question)
        dependency = RevisionDependency.objects.create(
            source=revision,
            target=revision,
            role=RevisionDependency.Role.PARENT_QUESTION,
            position=0,
        )
        EvidenceRecord.objects.create(
            source=revision,
            image=self.image,
            slot=EvidenceRecord.Slot.SOURCE,
            sequence=1,
            purpose=EvidenceRecord.Purpose.QUESTION,
            granularity=EvidenceRecord.Granularity.WHOLE_IMAGE,
            region_missing=True,
            gaps=["region_missing"],
        )
        decision = self.make_decision(revision)
        receipt = RequestReceipt.objects.create(
            household=self.household,
            request_key="receipt-1",
            operation=RequestReceipt.Operation.STAGE,
            actor=self.user,
            request_hash=hashlib.sha256(b"stage").hexdigest(),
            result={"revision_id": revision.revision_id},
        )
        immutable_rows = (
            (ImageRecord, self.image.pk, {"stable_id": "mutated-image"}),
            (RevisionRecord, revision.revision_id, {"payload": {"changed": True}}),
            (RevisionDependency, dependency.pk, {"position": 1}),
            (EvidenceRecord, revision.evidence.get().pk, {"purpose": EvidenceRecord.Purpose.OTHER}),
            (ReviewDecision, decision.pk, {"reason": "changed"}),
            (RequestReceipt, receipt.pk, {"result": {"changed": True}}),
        )
        for model, pk, values in immutable_rows:
            with self.subTest(model=model.__name__, operation="update"):
                self.assert_database_rejects(lambda model=model, pk=pk, values=values: model.objects.filter(pk=pk).update(**values))
            with self.subTest(model=model.__name__, operation="delete"):
                self.assert_database_rejects(lambda model=model, pk=pk: self.raw_delete(model, pk))
