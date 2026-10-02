from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from app.domain import (
    ActualDateState, Assessment, AssessmentDimension, AssessmentRevision, Attempt,
    AttemptKind, AttemptRevision, AttemptState, AuthorState, BasisKind, Bundle,
    ContractError, DimensionKind, Erratum, ErratumRevision, ErratumTargetKind,
    EvidencePurpose, EvidenceRef, Granularity, Independence, Judgment,
    KnowledgeItem, KnowledgeQuestionLinkRevision, KnowledgeRevision, Origin,
    LearnerProfile, Legibility, Method, MethodQuestionLinkRevision,
    MethodRevision, NodeKind, NodeRef, ObservationRef, ObservationRevision,
    PromptStatus, Question, QuestionRevision, QuestionType,
    QuestionTypeLinkRevision, QuestionTypeRevision, RegionRevision, ReviewState,
    RevisionHeader, SourceImage, SourceKind, SourceObservation, VersionCheckState,
    VersionRef, compare_expected_version, deserialize_bundle, independent_successes,
    merge_bundles, nodes_for_evidence, questions_for_evidence, questions_for_node,
    seal_revision, serialize_bundle, validate_bundle,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "domain" / "synthetic-v0.1.json"
HOUSEHOLD = "household-demo"
RECORDED = "2026-09-30T12:30:00+08:00"


def header(owner: str, revision_id: str, revision_no: int = 1, previous: str | None = None, reason: str = "synthetic fixture") -> RevisionHeader:
    return RevisionHeader(revision_id, owner, revision_no, previous, "parent-demo", RECORDED, Origin.HUMAN, reason, "")


def make_revision(cls, owner: str, revision_id: str, **kwargs):
    return seal_revision(cls(header=header(owner, revision_id, **kwargs.pop("header_args", {})), **kwargs))


def make_base_bundle() -> Bundle:
    image1 = SourceImage("image-page-1", HOUSEHOLD, "a" * 64, "fixture://synthetic/page-1", "image/jpeg", 1000, 1400, RECORDED)
    image2 = SourceImage("image-page-2", HOUSEHOLD, "b" * 64, "fixture://synthetic/page-2", "image/jpeg", 1000, 1400, RECORDED)
    region1 = make_revision(RegionRevision, "region-q1-page-1", "region-q1-page-1-r1", region_id="region-q1-page-1", household_id=HOUSEHOLD, image_id=image1.image_id, coordinate_space="original_pixels", geometry=(40.0, 100.0, 600.0, 500.0), purpose="question")
    region2 = make_revision(RegionRevision, "region-q1-page-2", "region-q1-page-2-r1", region_id="region-q1-page-2", household_id=HOUSEHOLD, image_id=image2.image_id, coordinate_space="original_pixels", geometry=(30.0, 70.0, 580.0, 410.0), purpose="question continuation")
    region3 = make_revision(RegionRevision, "region-q2-page-1", "region-q2-page-1-r1", region_id="region-q2-page-1", household_id=HOUSEHOLD, image_id=image1.image_id, coordinate_space="original_pixels", geometry=(50.0, 700.0, 620.0, 1000.0), purpose="question")
    ev_q1_p1 = EvidenceRef(HOUSEHOLD, image1.image_id, image1.sha256, Granularity.REGION, region1.region_id, region1.header.revision_id, False, EvidencePurpose.QUESTION, 1, ())
    ev_q1_p2 = EvidenceRef(HOUSEHOLD, image2.image_id, image2.sha256, Granularity.REGION, region2.region_id, region2.header.revision_id, False, EvidencePurpose.QUESTION, 2, ())
    ev_q2 = EvidenceRef(HOUSEHOLD, image1.image_id, image1.sha256, Granularity.REGION, region3.region_id, region3.header.revision_id, False, EvidencePurpose.QUESTION, 1, ())

    k_rev = make_revision(KnowledgeRevision, "knowledge-fractions", "knowledge-fractions-r1", review_state=ReviewState.ACCEPTED, definition="Equivalent fractions preserve value.", conditions=("denominator is nonzero",), common_errors=("changing only one term",), source_refs=())
    m_rev = make_revision(MethodRevision, "method-common-denominator", "method-common-denominator-r1", review_state=ReviewState.ACCEPTED, name="Use a common denominator", conditions=("fraction addition",), steps=("Find a shared denominator", "Convert each fraction", "Add numerators"), notes=(), parent_revision_id=None, source_refs=())
    t_rev = make_revision(QuestionTypeRevision, "type-fraction-sum", "type-fraction-sum-r1", review_state=ReviewState.ACCEPTED, name="Fraction sum", structural_features=("sum of rational terms",), conditions=(), source_refs=())
    q1_rev = make_revision(QuestionRevision, "question-1", "question-1-r1", review_state=ReviewState.ACCEPTED, parent_question_revision_id=None, printed_text="Compute 1/3 + 1/6.", working_text="Compute 1/3 + 1/6.", missing_fields=(), evidence_refs=(ev_q1_p1, ev_q1_p2))
    q2_rev = make_revision(QuestionRevision, "question-2", "question-2-r1", review_state=ReviewState.ACCEPTED, parent_question_revision_id=None, printed_text="Compute 2/5 + 1/5.", working_text="Compute 2/5 + 1/5.", missing_fields=(), evidence_refs=(ev_q2,))

    def link(cls, kind_id: str, qrev: str, target_rev: str, role: str):
        lid = f"{kind_id}-to-{qrev}"
        kw = dict(link_id=lid, household_id=HOUSEHOLD, question_revision_id=qrev, role=role, review_state=ReviewState.ACCEPTED)
        if cls is KnowledgeQuestionLinkRevision:
            kw["knowledge_revision_id"] = target_rev
        elif cls is MethodQuestionLinkRevision:
            kw["method_revision_id"] = target_rev
        else:
            kw["question_type_revision_id"] = target_rev
        return make_revision(cls, lid, f"{lid}-r1", **kw)

    return Bundle(
        schema_version="study-workbench.core.v0.1", household_id=HOUSEHOLD,
        images=(image1, image2), regions=(region1, region2, region3),
        knowledge_items=(KnowledgeItem("knowledge-fractions", HOUSEHOLD, (k_rev,)),),
        methods=(Method("method-common-denominator", HOUSEHOLD, (m_rev,)),),
        question_types=(QuestionType("type-fraction-sum", HOUSEHOLD, (t_rev,)),),
        questions=(Question("question-1", HOUSEHOLD, None, (q1_rev,)), Question("question-2", HOUSEHOLD, None, (q2_rev,))),
        knowledge_question_links=tuple(link(KnowledgeQuestionLinkRevision, "knowledge-fractions", q.header.revision_id, "knowledge-fractions-r1", "examines") for q in (q1_rev, q2_rev)),
        method_question_links=tuple(link(MethodQuestionLinkRevision, "method-common-denominator", q.header.revision_id, "method-common-denominator-r1", "primary") for q in (q1_rev, q2_rev)),
        question_type_links=tuple(link(QuestionTypeLinkRevision, "type-fraction-sum", q.header.revision_id, "type-fraction-sum-r1", "main") for q in (q1_rev, q2_rev)),
        learners=(), observations=(), attempts=(), assessments=(), errata=(),
    )


def tracking_bundle(
    *, source: SourceKind = SourceKind.INDEPENDENT_ANSWER,
    independence: Independence = Independence.CONFIRMED_INDEPENDENT,
    prompt_status: PromptStatus = PromptStatus.NONE_CONFIRMED,
    prompts: tuple[str, ...] = (),
    actual_date_state: ActualDateState = ActualDateState.KNOWN,
    actual_date: str | None = "2026-09-29",
    attempt_legibility: Legibility = Legibility.READABLE,
    observation_legibility: Legibility = Legibility.READABLE,
    answer_text: str | None = "1/2",
    author_state: AuthorState = AuthorState.CONFIRMED,
    author_learner_id: str | None = "learner-1",
    answer: Judgment = Judgment.CORRECT,
    process: Judgment = Judgment.CORRECT,
    extra_dimensions: tuple[AssessmentDimension, ...] = (),
    review_state: ReviewState = ReviewState.ACCEPTED,
    assessment_attempt_revision_id: str | None = None,
) -> Bundle:
    base = make_base_bundle()
    learner = LearnerProfile("learner-1", HOUSEHOLD, "小禾", "Grade 5")
    qrev = base.questions[0].revisions[0]
    evidence = (replace(qrev.evidence_refs[0], purpose=EvidencePurpose.HANDWRITING),)
    obs_kwargs = dict(
        evidence_refs=evidence, legibility=observation_legibility, author_state=author_state,
        author_learner_id=author_learner_id,
        confirmed_by="parent-demo" if author_state is AuthorState.CONFIRMED else None,
        confirmed_at=RECORDED if author_state is AuthorState.CONFIRMED else None,
        confirmation_basis="confirmed from the source note" if author_state is AuthorState.CONFIRMED else None,
        actual_date_state=ActualDateState.UNKNOWN, actual_date=None, notes="synthetic observation",
    )
    observation_revision = make_revision(ObservationRevision, "observation-1", "observation-1-r1", **obs_kwargs)
    observation = SourceObservation("observation-1", HOUSEHOLD, "learner-1", (observation_revision,))
    attempt_kwargs = dict(
        question_revision_id=qrev.header.revision_id, attempt_kind=AttemptKind.FIRST,
        source_kind=source, independence=independence, prompt_status=prompt_status,
        prompts=prompts, actual_date_state=actual_date_state, actual_date=actual_date,
        legibility=attempt_legibility, answer_text=answer_text, authorship_basis="parent confirmed who completed this event",
        observation_refs=(ObservationRef(observation.observation_id, observation_revision.header.revision_id),),
        state=AttemptState.ACTIVE, withdrawal_reason=None, replacement_attempt_id=None,
    )
    attempt_revision = make_revision(AttemptRevision, "attempt-1", "attempt-1-r1", **attempt_kwargs)
    attempt = Attempt("attempt-1", HOUSEHOLD, learner.learner_id, "question-1", None, None, (attempt_revision,))
    dimensions = (
        AssessmentDimension(DimensionKind.ANSWER, answer, BasisKind.OBSERVED, evidence, "answer read from linked work", "answer unreadable" if answer is Judgment.UNKNOWN else None),
        AssessmentDimension(DimensionKind.PROCESS, process, BasisKind.OBSERVED, evidence, "visible steps reviewed", "steps unreadable" if process is Judgment.UNKNOWN else None),
        *extra_dimensions,
    )
    arid = assessment_attempt_revision_id or attempt_revision.header.revision_id
    assessment_revision = make_revision(AssessmentRevision, "assessment-1", "assessment-1-r1", attempt_revision_id=arid, question_revision_id=qrev.header.revision_id, review_state=review_state, reviewed_by="parent-demo" if review_state is ReviewState.ACCEPTED else None, dimensions=dimensions, context_erratum_revision_ids=())
    assessment = Assessment("assessment-1", HOUSEHOLD, attempt.attempt_id, (assessment_revision,))
    return replace(base, learners=(learner,), observations=(observation,), attempts=(attempt,), assessments=(assessment,))


def reseal(revision, **changes):
    changed = replace(revision, **changes)
    changed = replace(changed, header=replace(changed.header, content_hash=""))
    return seal_revision(changed)


def replace_question_revision(bundle: Bundle, question_id: str, revision) -> Bundle:
    questions = []
    for question in bundle.questions:
        if question.question_id == question_id:
            replaced = False
            revisions_list = []
            for old in question.revisions:
                if old.header.revision_id == revision.header.revision_id:
                    revisions_list.append(revision)
                    replaced = True
                else:
                    revisions_list.append(old)
            if not replaced:
                revisions_list.append(revision)
            revisions = tuple(revisions_list)
            questions.append(replace(question, revisions=revisions))
        else:
            questions.append(question)
    return replace(bundle, questions=tuple(questions))


class CoreContractScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = deserialize_bundle(FIXTURE.read_text(encoding="utf-8"))

    def test_ct01_bidirectional_nodes_questions_and_ordered_cross_page_evidence(self):
        node = NodeRef(NodeKind.KNOWLEDGE, "knowledge-fractions", "knowledge-fractions-r1")
        question_revisions = questions_for_node(self.bundle, node)
        self.assertEqual({revision.header.owner_id for revision in question_revisions}, {"question-1", "question-2"})
        q1 = next(item for item in question_revisions if item.header.owner_id == "question-1")
        self.assertEqual([ref.sequence for ref in q1.evidence_refs], [1, 2])
        self.assertEqual([ref.image_id for ref in q1.evidence_refs], ["image-page-1", "image-page-2"])
        reverse_questions = questions_for_evidence(self.bundle, "image-page-2")
        self.assertEqual([revision.header.owner_id for revision in reverse_questions], ["question-1"])
        self.assertEqual(reverse_questions[0].header.revision_id, q1.header.revision_id)
        with self.assertRaisesRegex(ContractError, "missing_region_revision"):
            questions_for_evidence(self.bundle, "image-page-2", "unknown-region-r1")
        reverse = nodes_for_evidence(self.bundle, "image-page-2")
        self.assertEqual({item.kind for item in reverse}, {NodeKind.KNOWLEDGE, NodeKind.METHOD, NodeKind.QUESTION_TYPE})
        self.assertEqual(nodes_for_evidence(self.bundle, "image-page-2", "region-q1-page-2-r1"), reverse)

    def test_ct02_two_attempts_and_independent_assessment_revisions_round_trip(self):
        bundle = tracking_bundle(source=SourceKind.ASSISTED_ANSWER, independence=Independence.NOT_INDEPENDENT, prompt_status=PromptStatus.GIVEN, prompts=("Use a common denominator",), answer=Judgment.INCORRECT, process=Judgment.PARTIAL, answer_text="2/9")
        first = bundle.attempts[0]
        first_revision = first.revisions[0]
        first_assessment = bundle.assessments[0]
        first_assessment_revision = first_assessment.revisions[0]
        first_observation = bundle.observations[0]
        second_evidence = (replace(bundle.questions[0].revisions[0].evidence_refs[1], purpose=EvidencePurpose.HANDWRITING, sequence=1),)
        second_observation_revision = make_revision(ObservationRevision, "observation-2", "observation-2-r1", evidence_refs=second_evidence, legibility=Legibility.READABLE, author_state=AuthorState.CONFIRMED, author_learner_id="learner-1", confirmed_by="parent-demo", confirmed_at=RECORDED, confirmation_basis="parent reviewed the later retest source", actual_date_state=ActualDateState.UNKNOWN, actual_date=None, notes="separate synthetic retest evidence from the second page")
        second_observation = SourceObservation("observation-2", HOUSEHOLD, "learner-1", (second_observation_revision,))
        second_attempt_revision = reseal(first_revision, header=replace(first_revision.header, revision_id="attempt-2-r1", owner_id="attempt-2", revision_no=1, previous_revision_id=None), attempt_kind=AttemptKind.RETEST, source_kind=SourceKind.INDEPENDENT_ANSWER, independence=Independence.CONFIRMED_INDEPENDENT, prompt_status=PromptStatus.NONE_CONFIRMED, prompts=(), actual_date="2026-09-30", answer_text="1/2", observation_refs=(ObservationRef("observation-2", "observation-2-r1"),))
        second_attempt = Attempt("attempt-2", HOUSEHOLD, "learner-1", "question-1", "attempt-1", None, (second_attempt_revision,))
        # The observation explicitly confirms the learner and the assessment is independently addressed.
        second_assessment_revision = make_revision(AssessmentRevision, "assessment-2", "assessment-2-r1", attempt_revision_id=second_attempt_revision.header.revision_id, question_revision_id="question-1-r1", review_state=ReviewState.ACCEPTED, reviewed_by="parent-demo", dimensions=(AssessmentDimension(DimensionKind.ANSWER, Judgment.CORRECT, BasisKind.OBSERVED, (second_observation_revision.evidence_refs[0],), "answer observed on the independent retest"), AssessmentDimension(DimensionKind.PROCESS, Judgment.CORRECT, BasisKind.OBSERVED, (second_observation_revision.evidence_refs[0],), "process observed on the independent retest")), context_erratum_revision_ids=())
        bundle = replace(bundle, observations=(first_observation, second_observation), attempts=(first, second_attempt), assessments=(first_assessment, Assessment("assessment-2", HOUSEHOLD, "attempt-2", (second_assessment_revision,))))
        validate_bundle(bundle)
        self.assertEqual({a.attempt_id for a in independent_successes(bundle)}, {"attempt-2"})
        revised_dimensions = (replace(first_assessment_revision.dimensions[0], judgment=Judgment.PARTIAL, rationale="rechecked: the learner combined denominators"), first_assessment_revision.dimensions[1])
        edited_assessment_revision = reseal(first_assessment_revision, header=replace(first_assessment_revision.header, revision_id="assessment-1-r2", revision_no=2, previous_revision_id="assessment-1-r1"), review_state=ReviewState.ACCEPTED, reviewed_by="parent-demo", dimensions=revised_dimensions)
        edited = replace(first_assessment, revisions=(first_assessment_revision, edited_assessment_revision))
        bundle = replace(bundle, assessments=(edited, bundle.assessments[1]))
        loaded = deserialize_bundle(serialize_bundle(bundle))
        self.assertEqual([a.attempt_id for a in loaded.attempts], ["attempt-1", "attempt-2"])
        self.assertEqual(len(loaded.assessments[0].revisions), 2)
        self.assertEqual(loaded.assessments[0].revisions[0].header.revision_id, "assessment-1-r1")
        self.assertEqual(loaded.assessments[0].revisions[1].header.previous_revision_id, "assessment-1-r1")

    def test_ct03_unknown_profile_context_is_not_authorship_and_observation_can_stand_alone(self):
        bundle = tracking_bundle(author_state=AuthorState.UNKNOWN, author_learner_id=None)
        self.assertEqual(independent_successes(bundle), ())
        observation_only = replace(bundle, attempts=(), assessments=())
        validate_bundle(observation_only)
        self.assertEqual(len(observation_only.observations), 1)
        bad_revision = reseal(bundle.observations[0].revisions[0], author_state=AuthorState.UNKNOWN, author_learner_id="learner-1", confirmed_by="parent-demo", confirmed_at=RECORDED, confirmation_basis="profile context only")
        broken = replace(bundle, observations=(replace(bundle.observations[0], revisions=(bad_revision,)),))
        with self.assertRaisesRegex(ContractError, "unknown_author_has_confirmation"):
            validate_bundle(broken)

    def test_ct03_non_independent_sources_prompts_unknown_dates_and_unreadable_evidence_do_not_count(self):
        cases = (
            tracking_bundle(source=SourceKind.CLASSROOM_NOTE, independence=Independence.NOT_INDEPENDENT),
            tracking_bundle(source=SourceKind.COPIED_WORK, independence=Independence.NOT_INDEPENDENT),
            tracking_bundle(source=SourceKind.UNKNOWN, independence=Independence.UNKNOWN),
            tracking_bundle(source=SourceKind.ASSISTED_ANSWER, independence=Independence.NOT_INDEPENDENT, prompt_status=PromptStatus.GIVEN, prompts=("hint",)),
            tracking_bundle(actual_date_state=ActualDateState.UNKNOWN, actual_date=None),
            tracking_bundle(attempt_legibility=Legibility.BLANK),
            tracking_bundle(observation_legibility=Legibility.ILLEGIBLE),
            tracking_bundle(observation_legibility=Legibility.MISSING),
        )
        for bundle in cases:
            with self.subTest(source=bundle.attempts[0].revisions[0].source_kind, date=bundle.attempts[0].revisions[0].actual_date_state):
                self.assertEqual(independent_successes(bundle), ())

    def test_prompt_records_cannot_contradict_confirmed_no_prompt(self):
        bundle = tracking_bundle(prompts=("one hint",))
        with self.assertRaisesRegex(ContractError, "prompt_status_conflict"):
            validate_bundle(bundle)

    def test_draft_relationship_is_not_returned_as_current_map_content(self):
        old = next(link for link in self.bundle.knowledge_question_links if link.question_revision_id == "question-2-r1")
        draft = reseal(old, header=replace(old.header, revision_id="knowledge-fractions-to-question-2-r1-r2", revision_no=2, previous_revision_id=old.header.revision_id), review_state=ReviewState.DRAFT)
        bundle = replace(self.bundle, knowledge_question_links=self.bundle.knowledge_question_links + (draft,))
        qids = {revision.header.owner_id for revision in questions_for_node(bundle, NodeRef(NodeKind.KNOWLEDGE, "knowledge-fractions", "knowledge-fractions-r1"))}
        self.assertEqual(qids, {"question-1"})

    def test_independent_success_requires_evidence_linked_to_attempt_observations(self):
        bundle = tracking_bundle()
        assessment = bundle.assessments[0]
        distant_evidence = bundle.questions[1].revisions[0].evidence_refs
        dimensions = tuple(replace(dimension, evidence_refs=distant_evidence) for dimension in assessment.revisions[0].dimensions)
        detached = reseal(assessment.revisions[0], dimensions=dimensions)
        bundle = replace(bundle, assessments=(replace(assessment, revisions=(detached,)),))
        validate_bundle(bundle)
        self.assertEqual(independent_successes(bundle), ())

    def test_ct04_answer_and_process_are_independent_review_dimensions(self):
        right_answer_wrong_process = tracking_bundle(answer=Judgment.CORRECT, process=Judgment.INCORRECT)
        self.assertEqual(independent_successes(right_answer_wrong_process), ())
        no_process = tracking_bundle(review_state=ReviewState.DRAFT)
        draft_revision = reseal(no_process.assessments[0].revisions[0], dimensions=(no_process.assessments[0].revisions[0].dimensions[0],))
        no_process = replace(no_process, assessments=(replace(no_process.assessments[0], revisions=(draft_revision,)),))
        self.assertEqual(independent_successes(no_process), ())

    def test_ct04_any_explicit_incorrect_dimension_or_conflicting_accepted_assessment_blocks_success(self):
        extra = AssessmentDimension(DimensionKind.CALCULATION, Judgment.INCORRECT, BasisKind.OBSERVED, (), "visible arithmetic error")
        self.assertEqual(independent_successes(tracking_bundle(extra_dimensions=(extra,))), ())
        base = tracking_bundle()
        attempt_rev = base.attempts[0].revisions[0]
        evidence = base.observations[0].revisions[0].evidence_refs[0]
        conflicting = make_revision(AssessmentRevision, "assessment-2", "assessment-2-r1", attempt_revision_id=attempt_rev.header.revision_id, question_revision_id="question-1-r1", review_state=ReviewState.ACCEPTED, reviewed_by="second-reviewer", dimensions=(AssessmentDimension(DimensionKind.ANSWER, Judgment.CORRECT, BasisKind.OBSERVED, (evidence,), "answer"), AssessmentDimension(DimensionKind.PROCESS, Judgment.PARTIAL, BasisKind.OBSERVED, (evidence,), "steps incomplete")), context_erratum_revision_ids=())
        conflict_bundle = replace(base, assessments=base.assessments + (Assessment("assessment-2", HOUSEHOLD, "attempt-1", (conflicting,)),))
        self.assertEqual(independent_successes(conflict_bundle), ())

    def test_ct05_erratum_and_child_error_are_separate_and_old_content_is_preserved(self):
        base = tracking_bundle(answer=Judgment.INCORRECT, process=Judgment.PARTIAL, answer_text="2/9", extra_dimensions=(AssessmentDimension(DimensionKind.CALCULATION, Judgment.INCORRECT, BasisKind.OBSERVED, (make_base_bundle().questions[0].revisions[0].evidence_refs[0],), "learner added denominators 3 and 6"),))
        question = base.questions[0]
        original_revision = question.revisions[0]
        old = reseal(original_revision, printed_text="Compute 1/3 + 1/6 = 2/9.", working_text="Compute 1/3 + 1/6 = 2/9.")
        question = replace(question, revisions=(old,))
        fixed_text = "Compute 1/3 + 1/6 = 1/2."
        erratum_revision = make_revision(ErratumRevision, "erratum-1", "erratum-1-r1", target_kind=ErratumTargetKind.QUESTION, target_revision_id=old.header.revision_id, printed_text=old.printed_text, corrected_text=fixed_text, basis="2/6 + 1/6 = 3/6 = 1/2; the printed answer 2/9 adds the denominators", evidence_refs=(old.evidence_refs[0],), review_state=ReviewState.ACCEPTED, reviewed_by="parent-demo")
        fixed_question_revision = make_revision(QuestionRevision, "question-1", "question-1-r2", header_args={"revision_no": 2, "previous": old.header.revision_id}, review_state=ReviewState.ACCEPTED, parent_question_revision_id=None, printed_text=old.printed_text, working_text=fixed_text, missing_fields=(), evidence_refs=old.evidence_refs, erratum_revision_ids=(erratum_revision.header.revision_id,))
        changed_question = replace(question, revisions=(old, fixed_question_revision))
        bundle = replace(base, questions=(changed_question, *base.questions[1:]), errata=(Erratum("erratum-1", HOUSEHOLD, (erratum_revision,)),))
        validate_bundle(bundle)
        self.assertEqual(bundle.attempts[0].revisions[0].question_revision_id, old.header.revision_id)
        self.assertEqual(bundle.assessments[0].revisions[0].question_revision_id, old.header.revision_id)
        self.assertNotEqual(fixed_question_revision.working_text, fixed_question_revision.printed_text)
        self.assertEqual(bundle.assessments[0].revisions[0].dimensions[2].judgment, Judgment.INCORRECT)

    def test_accepted_changed_question_requires_matching_accepted_erratum(self):
        base = make_base_bundle()
        old = base.questions[0].revisions[0]
        fixed = make_revision(QuestionRevision, "question-1", "question-1-r2", header_args={"revision_no": 2, "previous": old.header.revision_id}, review_state=ReviewState.ACCEPTED, parent_question_revision_id=None, printed_text=old.printed_text, working_text="corrected text", missing_fields=(), evidence_refs=old.evidence_refs)
        bad = replace_question_revision(base, "question-1", fixed)
        with self.assertRaisesRegex(ContractError, "accepted_question_missing_erratum"):
            validate_bundle(bad)

    def test_ct06_full_dependency_vector_detects_stale_and_missing_dependency_conflicts(self):
        expected = (VersionRef("question", "q-r1"), VersionRef("region", "r-r1"), VersionRef("method", "m-r1"))
        self.assertEqual(compare_expected_version(expected, expected).state, VersionCheckState.CURRENT)
        stale = compare_expected_version(expected, (VersionRef("question", "q-r1"), VersionRef("region", "r-r2"), VersionRef("method", "m-r1")))
        self.assertEqual(stale.state, VersionCheckState.STALE)
        self.assertFalse(stale.publishable)
        self.assertIsNone(stale.published_result)
        conflict = compare_expected_version(expected, expected[:-1])
        self.assertEqual(conflict.state, VersionCheckState.VERSION_CONFLICT)
        self.assertFalse(conflict.publishable)
        self.assertIsNone(conflict.published_result)
        with self.assertRaisesRegex(ContractError, "duplicate_version_dependency"):
            compare_expected_version((VersionRef("question", "q-r1"), VersionRef("question", "q-r2")), ())

    def test_ct07_hash_household_coordinate_region_version_and_parent_cycles_are_rejected(self):
        qrev = self.bundle.questions[0].revisions[0]
        ref = replace(qrev.evidence_refs[0], image_sha256="f" * 64)
        bad_hash_revision = reseal(qrev, evidence_refs=(ref, *qrev.evidence_refs[1:]))
        with self.assertRaisesRegex(ContractError, "image_hash_mismatch"):
            validate_bundle(replace_question_revision(self.bundle, "question-1", bad_hash_revision))
        wrong_region = replace(qrev.evidence_refs[0], region_revision_id="missing-region-r1")
        with self.assertRaisesRegex(ContractError, "missing_region_revision"):
            validate_bundle(replace_question_revision(self.bundle, "question-1", reseal(qrev, evidence_refs=(wrong_region, *qrev.evidence_refs[1:]))))
        region = self.bundle.regions[0]
        bool_region = reseal(region, geometry=(True, 2.0, 30.0, 40.0))
        with self.assertRaisesRegex(ContractError, "invalid_coordinate"):
            validate_bundle(replace(self.bundle, regions=(bool_region, *self.bundle.regions[1:])))
        huge_region = reseal(region, geometry=(0, 0, 10**400, 40))
        with self.assertRaisesRegex(ContractError, "invalid_coordinate"):
            validate_bundle(replace(self.bundle, regions=(huge_region, *self.bundle.regions[1:])))
        outside_region = reseal(region, geometry=(0.0, 0.0, 1001.0, 20.0))
        with self.assertRaisesRegex(ContractError, "geometry_out_of_bounds"):
            validate_bundle(replace(self.bundle, regions=(outside_region, *self.bundle.regions[1:])))
        other_household_ref = replace(qrev.evidence_refs[0], household_id="another-home")
        with self.assertRaisesRegex(ContractError, "household_mismatch"):
            validate_bundle(replace_question_revision(self.bundle, "question-1", reseal(qrev, evidence_refs=(other_household_ref, *qrev.evidence_refs[1:]))))
        q1, q2 = self.bundle.questions
        q1r, q2r = q1.revisions[0], q2.revisions[0]
        q1cyc = reseal(q1r, parent_question_revision_id=q2r.header.revision_id)
        q2cyc = reseal(q2r, parent_question_revision_id=q1r.header.revision_id)
        cycle_bundle = replace(self.bundle, questions=(replace(q1, parent_question_id=q2.question_id, revisions=(q1cyc,)), replace(q2, parent_question_id=q1.question_id, revisions=(q2cyc,))))
        with self.assertRaisesRegex(ContractError, "parent_cycle"):
            validate_bundle(cycle_bundle)

    def test_ct08_roundtrip_repeated_merge_and_immutable_conflicts(self):
        bundle = self.bundle
        self.assertEqual(bundle, make_base_bundle())
        encoded = serialize_bundle(bundle)
        loaded = deserialize_bundle(encoded)
        self.assertEqual(loaded, bundle)
        self.assertEqual(serialize_bundle(loaded), encoded)
        merged = merge_bundles(bundle, loaded)
        self.assertEqual(merged, bundle)
        self.assertEqual(len(merge_bundles(merged, bundle).questions), len(bundle.questions))
        changed_knowledge_revision = reseal(bundle.knowledge_items[0].revisions[0], definition="different immutable definition")
        incoming = replace(bundle, knowledge_items=(replace(bundle.knowledge_items[0], revisions=(changed_knowledge_revision,)),))
        with self.assertRaisesRegex(ContractError, "immutable_content_conflict"):
            merge_bundles(bundle, incoming)
        incomplete = replace(bundle, images=())
        with self.assertRaisesRegex(ContractError, "missing_image"):
            merge_bundles(bundle, incomplete)

    def test_ct09_draft_index_can_retain_missing_text_and_whole_image_gap(self):
        base = make_base_bundle()
        image = base.images[0]
        whole = EvidenceRef(HOUSEHOLD, image.image_id, image.sha256, Granularity.WHOLE_IMAGE, None, None, True, EvidencePurpose.QUESTION, 1, ("region_missing", "question_text_missing"))
        draft = make_revision(QuestionRevision, "question-draft", "question-draft-r1", review_state=ReviewState.DRAFT, parent_question_revision_id=None, printed_text=None, working_text=None, missing_fields=("question_text", "region"), evidence_refs=(whole,))
        bundle = replace(base, questions=base.questions + (Question("question-draft", HOUSEHOLD, None, (draft,)),))
        validate_bundle(bundle)
        self.assertEqual(draft.missing_fields, ("question_text", "region"))
        accepted = reseal(draft, review_state=ReviewState.ACCEPTED)
        invalid = replace(bundle, questions=base.questions + (Question("question-draft", HOUSEHOLD, None, (accepted,)),))
        with self.assertRaisesRegex(ContractError, "incomplete_question_accepted"):
            validate_bundle(invalid)

    def test_ct10_wrong_attempt_identity_uses_withdrawal_and_replacement(self):
        base = tracking_bundle()
        old = base.attempts[0]
        original_revision = old.revisions[0]
        withdrawn_revision = reseal(original_revision, header=replace(original_revision.header, revision_id="attempt-1-r2", revision_no=2, previous_revision_id=original_revision.header.revision_id), state=AttemptState.WITHDRAWN, withdrawal_reason="identity_error", replacement_attempt_id="attempt-replacement")
        withdrawn = replace(old, revisions=(original_revision, withdrawn_revision))
        replacement_revision = make_revision(AttemptRevision, "attempt-replacement", "attempt-replacement-r1", question_revision_id="question-2-r1", attempt_kind=AttemptKind.FIRST, source_kind=SourceKind.UNKNOWN, independence=Independence.UNKNOWN, prompt_status=PromptStatus.UNKNOWN, prompts=(), actual_date_state=ActualDateState.UNKNOWN, actual_date=None, legibility=Legibility.UNKNOWN, answer_text=None, authorship_basis="corrected learner/question identity from parent review", observation_refs=(), state=AttemptState.ACTIVE)
        replacement = Attempt("attempt-replacement", HOUSEHOLD, "learner-1", "question-2", None, "attempt-1", (replacement_revision,))
        bundle = replace(base, attempts=(withdrawn, replacement))
        validate_bundle(bundle)
        self.assertEqual(bundle.attempts[0].question_id, "question-1")
        self.assertEqual(bundle.attempts[0].revisions[0].state, AttemptState.ACTIVE)
        self.assertEqual(bundle.attempts[0].revisions[1].state, AttemptState.WITHDRAWN)
        self.assertEqual(bundle.assessments[0].revisions[0].attempt_revision_id, original_revision.header.revision_id)
        self.assertEqual(independent_successes(bundle), ())

    def test_ct10_unknown_observation_revision_is_retained_after_confirmation(self):
        bundle = tracking_bundle(author_state=AuthorState.UNKNOWN, author_learner_id=None)
        original = bundle.observations[0].revisions[0]
        confirmed = reseal(original, header=replace(original.header, revision_id="observation-1-r2", revision_no=2, previous_revision_id=original.header.revision_id), author_state=AuthorState.CONFIRMED, author_learner_id="learner-1", confirmed_by="parent-demo", confirmed_at=RECORDED, confirmation_basis="parent matched this page to the learner")
        observation = replace(bundle.observations[0], revisions=(original, confirmed))
        bundle = replace(bundle, observations=(observation,))
        validate_bundle(bundle)
        self.assertEqual(bundle.observations[0].revisions[0].author_state, AuthorState.UNKNOWN)
        self.assertEqual(bundle.observations[0].revisions[1].author_state, AuthorState.CONFIRMED)
        # Attempt keeps its original unknown-evidence observation reference unless explicitly revised.
        self.assertEqual(bundle.attempts[0].revisions[0].observation_refs[0].observation_revision_id, original.header.revision_id)

    def test_assessment_must_match_the_attempts_exact_question_revision(self):
        bundle = tracking_bundle()
        assessment = bundle.assessments[0]
        broken_revision = reseal(assessment.revisions[0], question_revision_id="question-2-r1")
        bundle = replace(bundle, assessments=(replace(assessment, revisions=(broken_revision,)),))
        with self.assertRaisesRegex(ContractError, "assessment_question_revision_mismatch"):
            validate_bundle(bundle)

    def test_attempt_revision_cannot_rewrite_actual_question_version(self):
        bundle = tracking_bundle()
        question = bundle.questions[0]
        old_question_revision = question.revisions[0]
        second_question_revision = make_revision(QuestionRevision, "question-1", "question-1-r2", header_args={"revision_no": 2, "previous": old_question_revision.header.revision_id}, review_state=ReviewState.ACCEPTED, parent_question_revision_id=None, printed_text=old_question_revision.printed_text, working_text=old_question_revision.working_text, missing_fields=(), evidence_refs=old_question_revision.evidence_refs)
        bundle = replace(bundle, questions=(replace(question, revisions=(old_question_revision, second_question_revision)), *bundle.questions[1:]))
        attempt = bundle.attempts[0]
        original_attempt_revision = attempt.revisions[0]
        rewritten = reseal(original_attempt_revision, header=replace(original_attempt_revision.header, revision_id="attempt-1-r2", revision_no=2, previous_revision_id=original_attempt_revision.header.revision_id), question_revision_id=second_question_revision.header.revision_id)
        bundle = replace(bundle, attempts=(replace(attempt, revisions=(original_attempt_revision, rewritten)),))
        with self.assertRaisesRegex(ContractError, "attempt_question_revision_rewritten"):
            validate_bundle(bundle)

    def test_non_accepted_assessment_and_old_attempt_revision_cannot_count(self):
        rejected = tracking_bundle(review_state=ReviewState.REJECTED)
        self.assertEqual(independent_successes(rejected), ())
        bundle = tracking_bundle()
        old_attempt = bundle.attempts[0].revisions[0]
        newer_attempt = reseal(old_attempt, header=replace(old_attempt.header, revision_id="attempt-1-r2", revision_no=2, previous_revision_id=old_attempt.header.revision_id), answer_text="1/2, clarified")
        new_attempt = replace(bundle.attempts[0], revisions=(old_attempt, newer_attempt))
        bundle = replace(bundle, attempts=(new_attempt,))
        self.assertEqual(independent_successes(bundle), ())

    def test_bundle_roundtrip_preserves_integer_bbox_values(self):
        region = self.bundle.regions[0]
        integer_region = reseal(region, geometry=(0, 0, 100, 200))
        bundle = replace(self.bundle, regions=(integer_region, *self.bundle.regions[1:]))
        validate_bundle(bundle)
        loaded = deserialize_bundle(serialize_bundle(bundle))
        self.assertEqual(loaded.regions[0].geometry, (0, 0, 100, 200))
        self.assertEqual(loaded, bundle)

    def test_malformed_json_and_bad_timezone_fail_as_contract_errors(self):
        with self.assertRaisesRegex(ContractError, "invalid_json"):
            deserialize_bundle("{")
        with self.assertRaisesRegex(ContractError, "invalid_json_number"):
            deserialize_bundle("NaN")
        region = self.bundle.regions[0]
        bad = reseal(region, header=replace(region.header, recorded_at="2026-09-30T12:30:00"))
        bundle = replace(self.bundle, regions=(bad, *self.bundle.regions[1:]))
        with self.assertRaisesRegex(ContractError, "timezone_required"):
            validate_bundle(bundle)

    def test_region_adjustment_keeps_question_and_old_evidence_on_prior_revision(self):
        qrev = self.bundle.questions[0].revisions[0]
        prior_ref = qrev.evidence_refs[0]
        prior_region = self.bundle.regions[0]
        adjusted = make_revision(RegionRevision, prior_region.region_id, "region-q1-page-1-r2", header_args={"revision_no": 2, "previous": prior_region.header.revision_id}, region_id=prior_region.region_id, household_id=HOUSEHOLD, image_id=prior_region.image_id, coordinate_space="original_pixels", geometry=(41.0, 100.0, 600.0, 500.0), purpose="corrected question boundary")
        bundle = replace(self.bundle, regions=(prior_region, adjusted, *self.bundle.regions[1:]))
        validate_bundle(bundle)
        self.assertEqual(bundle.questions[0].revisions[0].evidence_refs[0].region_revision_id, prior_region.header.revision_id)
        self.assertEqual(nodes_for_evidence(bundle, prior_ref.image_id, prior_region.header.revision_id), nodes_for_evidence(self.bundle, prior_ref.image_id, prior_region.header.revision_id))
        self.assertEqual(nodes_for_evidence(bundle, prior_ref.image_id, adjusted.header.revision_id), ())

    def test_resealed_malformed_revision_fields_and_unsealed_content_are_rejected(self):
        qrev = self.bundle.questions[0].revisions[0]
        unsealed_mutation = replace(qrev, working_text="tampered without a new revision")
        bundle = replace_question_revision(self.bundle, "question-1", unsealed_mutation)
        with self.assertRaisesRegex(ContractError, "content_hash_mismatch"):
            validate_bundle(bundle)
        region = self.bundle.regions[0]
        bool_counter = reseal(region, header=replace(region.header, revision_no=True))
        with self.assertRaisesRegex(ContractError, "invalid_integer"):
            validate_bundle(replace(self.bundle, regions=(bool_counter, *self.bundle.regions[1:])))
        nonfinite = replace(region, geometry=(0.0, 0.0, float("nan"), 20.0))
        with self.assertRaises(ContractError):
            validate_bundle(replace(self.bundle, regions=(nonfinite, *self.bundle.regions[1:])))

    def test_optional_review_and_unknown_reason_fields_are_typed_even_on_drafts(self):
        bundle = tracking_bundle(review_state=ReviewState.DRAFT)
        assessment = bundle.assessments[0]
        malformed_assessment = reseal(assessment.revisions[0], reviewed_by=True)
        bundle = replace(bundle, assessments=(replace(assessment, revisions=(malformed_assessment,)),))
        with self.assertRaisesRegex(ContractError, "invalid_id"):
            serialize_bundle(bundle)

        base = make_base_bundle()
        qrev = base.questions[0].revisions[0]
        draft_erratum = make_revision(ErratumRevision, "erratum-draft", "erratum-draft-r1", target_kind=ErratumTargetKind.QUESTION, target_revision_id=qrev.header.revision_id, printed_text=qrev.printed_text, corrected_text="draft corrected text", basis="synthetic review pending", evidence_refs=(qrev.evidence_refs[0],), review_state=ReviewState.DRAFT, reviewed_by=True)
        bad_erratum_bundle = replace(base, errata=(Erratum("erratum-draft", HOUSEHOLD, (draft_erratum,)),))
        with self.assertRaisesRegex(ContractError, "invalid_id"):
            validate_bundle(bad_erratum_bundle)

        draft_tracking = tracking_bundle(review_state=ReviewState.DRAFT)
        assessment = draft_tracking.assessments[0]
        dimensions = (replace(assessment.revisions[0].dimensions[0], unknown_reason=17), *assessment.revisions[0].dimensions[1:])
        malformed_dimension = reseal(assessment.revisions[0], dimensions=dimensions)
        bad_dimension_bundle = replace(draft_tracking, assessments=(replace(assessment, revisions=(malformed_dimension,)),))
        with self.assertRaisesRegex(ContractError, "invalid_text"):
            validate_bundle(bad_dimension_bundle)

    def test_list_valued_reference_and_identity_fields_raise_contract_errors(self):
        region = self.bundle.regions[0]
        malformed_region = reseal(region, image_id=["image-page-1"])
        with self.assertRaisesRegex(ContractError, "invalid_id"):
            validate_bundle(replace(self.bundle, regions=(malformed_region, *self.bundle.regions[1:])))

        tracking = tracking_bundle(author_state=AuthorState.CONFIRMED, author_learner_id=["learner-1"])
        with self.assertRaisesRegex(ContractError, "invalid_id"):
            validate_bundle(tracking)

        tracking = tracking_bundle()
        attempt = tracking.attempts[0]
        malformed_attempt_revision = reseal(attempt.revisions[0], replacement_attempt_id=["attempt-replacement"])
        bad_attempt_bundle = replace(tracking, attempts=(replace(attempt, revisions=(malformed_attempt_revision,)),))
        with self.assertRaisesRegex(ContractError, "invalid_id"):
            validate_bundle(bad_attempt_bundle)


if __name__ == "__main__":
    unittest.main()
