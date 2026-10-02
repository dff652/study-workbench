from __future__ import annotations

from dataclasses import replace
import unittest

from app.domain import (
    ActualDateState,
    AuthorState,
    ContractError,
    EvidencePurpose,
    Granularity,
    Legibility,
    Origin,
    ReviewState,
    SourceImage,
    deserialize_bundle,
    serialize_bundle,
)
from app.imports import build_legacy_bundle


HOUSEHOLD = "household-synthetic"
RECORDED = "2026-10-02T12:00:00+08:00"
GROUPS = {1: "方法一", 2: "方法二", 3: "方法三", 4: "方法四", 5: "方法五", 6: "方法六"}


def image(token: str, *, image_id: str | None = None, sha: str | None = None, recorded_at: str = RECORDED) -> SourceImage:
    return SourceImage(image_id or f"image-{token}", HOUSEHOLD, sha or token[0] * 64, f"fixture://{token}", "image/jpeg", 1000, 1400, recorded_at)


def row(book: str, num: str, group: int, photo: str, *, aux: str = "") -> dict:
    return {
        "book": book,
        "num": num,
        "group": group,
        "photo": photo,
        "feature": "原始特征",
        "method": "原始方法字段",
        "tag": "原始标签",
        "tip": "原始提示",
        "aux": aux,
    }


def mixed_conversion(*, recorded_at: str = RECORDED, image_sha: str = "a" * 64):
    entries = [
        row("J1", "1", 1, "000001/000002", aux="1 拆数；5 区间比较；1 再拆数"),
        row("J1", "1(2)-3", 3, "000002/000003", aux="6 方程"),
        row("J1", "2(1)", 2, "000004"),
        row("W4", "12", 6, "000001"),
    ]
    images = {token: image(token, sha=image_sha if token == "000001" else token[0] * 64) for token in ("000001", "000002", "000003", "000004")}
    return entries, images, build_legacy_bundle(entries, GROUPS, images, household_id=HOUSEHOLD, dataset_key="synthetic", recorded_at=recorded_at)


class LegacyCatalogConversionTests(unittest.TestCase):
    def test_mixed_hierarchy_preserves_raw_rows_and_unknown_question_content(self):
        entries, _, conversion = mixed_conversion()
        bundle = conversion.bundle
        by_num = {(question.household_id, question.question_id): question for question in bundle.questions}
        q1_row = conversion.index_rows[0]
        question = next(q for q in bundle.questions if q.question_id == q1_row["question_id"])
        revision = question.revisions[0]
        self.assertIs(revision.review_state, ReviewState.DRAFT)
        self.assertIsNone(revision.printed_text)
        self.assertIsNone(revision.working_text)
        self.assertEqual(revision.missing_fields, ("printed_text", "working_text", "region_coordinates", "attempt_source"))
        self.assertEqual(q1_row["raw"], entries[0])
        self.assertEqual(q1_row["photo_tokens"], ["000001", "000002"])
        self.assertEqual([ref.image_id for ref in revision.evidence_refs], ["image-000001", "image-000002", "image-000003"])
        self.assertEqual([ref.sequence for ref in revision.evidence_refs], [1, 2, 3])
        self.assertTrue(all(ref.granularity is Granularity.WHOLE_IMAGE and ref.region_missing and ref.gaps == ("region_missing",) for ref in revision.evidence_refs))
        child = next(q for q in bundle.questions if q.question_id == conversion.index_rows[1]["question_id"])
        parent = next(q for q in bundle.questions if q.question_id == child.parent_question_id)
        root = next(q for q in bundle.questions if q.question_id == parent.parent_question_id)
        indexed_question_ids = {item["question_id"] for item in conversion.index_rows}
        self.assertNotIn(parent.question_id, indexed_question_ids)
        self.assertIn(root.question_id, indexed_question_ids)
        self.assertEqual(child.revisions[0].parent_question_revision_id, parent.revisions[0].header.revision_id)
        self.assertEqual(parent.revisions[0].parent_question_revision_id, root.revisions[0].header.revision_id)
        simple_child = next(q for q in bundle.questions if q.question_id == conversion.index_rows[2]["question_id"])
        self.assertIsNotNone(simple_child.parent_question_id)
        self.assertEqual(len(bundle.questions), 6)
        self.assertEqual(len(by_num), 6)
        revisions = [q.revisions[0] for q in bundle.questions]
        revisions += [method.revisions[0] for method in bundle.methods]
        revisions += [observation.revisions[0] for observation in bundle.observations]
        revisions += list(bundle.method_question_links)
        self.assertTrue(all(revision.header.revision_no == 1 and revision.header.previous_revision_id is None for revision in revisions))
        self.assertTrue(all(revision.header.created_by == "legacy-importer" and revision.header.recorded_at == RECORDED and revision.header.origin is Origin.IMPORT for revision in revisions))

    def test_auxiliary_links_parse_only_explicit_group_ids_and_keep_first_occurrence(self):
        _, _, conversion = mixed_conversion()
        row_info = conversion.index_rows[0]
        self.assertEqual(row_info["aux_method_revision_ids"], [
            next(method.revisions[0].header.revision_id for method in conversion.bundle.methods if method.revisions[0].name == GROUPS[1]),
            next(method.revisions[0].header.revision_id for method in conversion.bundle.methods if method.revisions[0].name == GROUPS[5]),
        ])
        primary_and_aux = [link for link in conversion.bundle.method_question_links if link.question_revision_id == row_info["question_revision_id"]]
        self.assertEqual([link.role for link in primary_and_aux], ["primary", "auxiliary", "auxiliary"])
        self.assertTrue(all(link.review_state is ReviewState.DRAFT for link in primary_and_aux))
        self.assertEqual(conversion.counts, {
            "index_entries": 4,
            "root_questions": 3,
            "question_entities": 6,
            "images": 4,
            "methods": 6,
            "primary_links": 4,
            "auxiliary_links": 3,
            "observations": 4,
        })

    def test_unknown_source_observations_never_create_attempts_or_mastery(self):
        _, _, conversion = mixed_conversion()
        bundle = conversion.bundle
        self.assertEqual(bundle.learners, ())
        self.assertEqual(bundle.attempts, ())
        self.assertEqual(bundle.assessments, ())
        self.assertEqual(bundle.errata, ())
        self.assertEqual(len(bundle.observations), 4)
        for observation in bundle.observations:
            self.assertIsNone(observation.profile_context_id)
            revision = observation.revisions[0]
            self.assertIs(revision.author_state, AuthorState.UNKNOWN)
            self.assertIs(revision.legibility, Legibility.UNKNOWN)
            self.assertIs(revision.actual_date_state, ActualDateState.UNKNOWN)
            self.assertIsNone(revision.actual_date)
            self.assertIsNone(revision.author_learner_id)
            self.assertIsNone(revision.confirmed_by)
            self.assertIsNone(revision.confirmed_at)
            self.assertIsNone(revision.confirmation_basis)
            self.assertEqual(len(revision.evidence_refs), 1)
            self.assertIs(revision.evidence_refs[0].purpose, EvidencePurpose.OTHER)

    def test_ids_are_scoped_and_independent_of_timestamp_or_file_hash(self):
        _, _, first = mixed_conversion()
        _, _, second = mixed_conversion(recorded_at="2026-10-03T00:00:00+08:00", image_sha="b" * 64)
        self.assertEqual([row["question_id"] for row in first.index_rows], [row["question_id"] for row in second.index_rows])
        self.assertEqual([row["question_revision_id"] for row in first.index_rows], [row["question_revision_id"] for row in second.index_rows])
        self.assertEqual([row["primary_method_revision_id"] for row in first.index_rows], [row["primary_method_revision_id"] for row in second.index_rows])
        self.assertNotEqual(first.bundle.questions[0].revisions[0].header.content_hash, second.bundle.questions[0].revisions[0].header.content_hash)
        other_scope = build_legacy_bundle([], GROUPS, {}, household_id=HOUSEHOLD, dataset_key="different", recorded_at=RECORDED)
        self.assertNotEqual(first.bundle.methods[0].method_id, other_scope.bundle.methods[0].method_id)

    def test_bundle_hashes_and_canonical_serialization_round_trip(self):
        _, _, conversion = mixed_conversion()
        for question in conversion.bundle.questions:
            self.assertEqual(len(question.revisions[0].header.content_hash), 64)
        encoded = serialize_bundle(conversion.bundle)
        decoded = deserialize_bundle(encoded)
        self.assertEqual(decoded, conversion.bundle)
        self.assertEqual(serialize_bundle(decoded), encoded)

    def test_source_images_deduplicate_by_id_and_reject_conflicting_metadata(self):
        entries = [row("J1", "1", 1, "000001/000002")]
        same = image("000001", image_id="shared")
        conversion = build_legacy_bundle(entries, GROUPS, {"000001": same, "000002": same}, household_id=HOUSEHOLD, dataset_key="synthetic", recorded_at=RECORDED)
        self.assertEqual(len(conversion.bundle.images), 1)
        self.assertEqual(len(conversion.bundle.observations), 1)
        conflicting = replace(same, storage_key="fixture://different")
        with self.assertRaises(ContractError):
            build_legacy_bundle(entries, GROUPS, {"000001": same, "000002": conflicting}, household_id=HOUSEHOLD, dataset_key="synthetic", recorded_at=RECORDED)

    def test_duplicate_rows_unknown_photos_bad_groups_numbers_types_and_extra_fields_reject(self):
        valid = row("J1", "1", 1, "000001")
        cases = [
            ([valid, dict(valid)], {"000001": image("000001")}, GROUPS),
            ([row("J1", "1", 1, "000099")], {"000001": image("000001")}, GROUPS),
            ([row("J1", "1", 1, "000001")], {"000001": image("000001")}, {**GROUPS, 7: "未知"}),
            ([row("J1", "0", 1, "000001")], {"000001": image("000001")}, GROUPS),
            ([row("J1", "1(0)", 1, "000001")], {"000001": image("000001")}, GROUPS),
            ([row("J1", "1", True, "000001")], {"000001": image("000001")}, GROUPS),
            ([{key: value for key, value in valid.items() if key != "tip"}], {"000001": image("000001")}, GROUPS),
            ([{**valid, "method": 5}], {"000001": image("000001")}, GROUPS),
            ([{**valid, "extra": "reject"}], {"000001": image("000001")}, GROUPS),
            ([row("J1", "1", 1, "000001/")], {"000001": image("000001")}, GROUPS),
        ]
        for entries, images, groups in cases:
            with self.subTest(entries=entries, groups=groups):
                with self.assertRaises(ContractError):
                    build_legacy_bundle(entries, groups, images, household_id=HOUSEHOLD, dataset_key="synthetic", recorded_at=RECORDED)

    def test_malformed_or_unknown_auxiliary_prefix_rejects_without_guessing(self):
        for aux in ("拆数", "1拆数", "7 未知", "1 拆数；", "1；；5 区间比较"):
            with self.subTest(aux=aux), self.assertRaises(ContractError):
                build_legacy_bundle([row("J1", "1", 1, "000001", aux=aux)], GROUPS, {"000001": image("000001")}, household_id=HOUSEHOLD, dataset_key="synthetic", recorded_at=RECORDED)


if __name__ == "__main__":
    unittest.main()
