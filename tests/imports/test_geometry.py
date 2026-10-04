from __future__ import annotations

import unittest

from app.domain import ContractError, ReviewState, SourceImage, deserialize_bundle, serialize_bundle
from app.imports import build_legacy_bundle
from app.imports.geometry import build_geometry_bundle, geometry_profile


HOUSEHOLD = "household-synthetic"
RECORDED = "2026-10-04T09:00:00+08:00"
GROUPS = {number: f"合成方法{number}" for number in range(1, 7)}
AUXILIARY = {"合成标签甲": 2, "合成标签乙": 5, "合成标签丙": 2}


def image(token: str) -> SourceImage:
    return SourceImage(
        image_id=f"image-{token}",
        household_id=HOUSEHOLD,
        sha256=token[0] * 64,
        storage_key=f"fixture://{token}",
        media_type="image/jpeg",
        width=1000,
        height=1400,
        recorded_at=RECORDED,
    )


def row(book: str, num: str, group: int, photo: str, *, aux: str = "") -> dict:
    return {
        "book": book,
        "num": num,
        "group": group,
        "photo": photo,
        "feature": "合成特征",
        "method": "合成方法说明",
        "tag": "合成标签",
        "tip": "合成提示",
        "aux": aux,
    }


def convert(entries: list[dict], images: dict[str, SourceImage], *, auxiliary_mapping=AUXILIARY, recorded_at=RECORDED):
    return build_geometry_bundle(
        entries,
        GROUPS,
        images,
        household_id=HOUSEHOLD,
        dataset_key="synthetic-geometry",
        recorded_at=recorded_at,
        auxiliary_mapping=auxiliary_mapping,
    )


class GeometryCatalogConversionTests(unittest.TestCase):
    def test_geometry_books_and_plus_photo_syntax(self):
        books = ("J3", "J4", "W5", "W6", "W7", "W8", "W9")
        profile = geometry_profile(AUXILIARY)
        self.assertEqual(profile.format_id, "geometry.v1")
        self.assertEqual(profile.books, books)
        self.assertEqual(profile.photo_separator, "+")
        entries = [row(book, "1", 1, "000001+000002") for book in books]
        conversion = convert(entries, {token: image(token) for token in ("000001", "000002")})

        self.assertEqual([item["book"] for item in conversion.index_rows], list(books))
        self.assertEqual([item["photo_tokens"] for item in conversion.index_rows], [["000001", "000002"]] * len(books))
        indexed_books = {item["question_id"]: item["book"] for item in conversion.index_rows}
        question_order = [indexed_books[question.question_id] for question in conversion.bundle.questions]
        self.assertEqual(question_order, list(books))
        with self.assertRaises(ContractError):
            convert([row("J1", "1", 1, "000001")], {"000001": image("000001")})
        with self.assertRaises(ContractError):
            convert([row("J3", "1", 1, "000001/000002")], {token: image(token) for token in ("000001", "000002")})

    def test_left_right_children_keep_textual_identity_and_sort_left_first(self):
        entries = [
            row("J3", "7(右)", 1, "000001"),
            row("J3", "7(左)", 1, "000002"),
            row("J3", "7", 1, "000003"),
        ]
        conversion = convert(entries, {token: image(token) for token in ("000001", "000002", "000003")})
        questions = conversion.bundle.questions
        self.assertEqual([entry["num"] for entry in conversion.index_rows], ["7(右)", "7(左)", "7"])
        index_by_num = {item["num"]: item for item in conversion.index_rows}
        question_by_num = {
            num: next(question for question in questions if question.question_id == index_by_num[num]["question_id"])
            for num in ("7", "7(左)", "7(右)")
        }
        ordered_nums = [
            next(num for num, item in index_by_num.items() if item["question_id"] == question.question_id)
            for question in questions
        ]
        self.assertEqual(ordered_nums, ["7", "7(左)", "7(右)"])

        root = question_by_num["7"]
        for side in ("7(左)", "7(右)"):
            child = question_by_num[side]
            self.assertEqual(child.parent_question_id, root.question_id)
            self.assertEqual(child.revisions[0].parent_question_revision_id, root.revisions[0].header.revision_id)

    def test_cross_page_evidence_order_raw_values_and_unknown_content_are_preserved(self):
        entries = [
            row("W5", "3", 1, "000002+000001"),
            row("W5", "3(左)", 2, "000004+000003"),
            row("W5", "3(右)", 3, "000003+000005"),
        ]
        images = {token: image(token) for token in ("000001", "000002", "000003", "000004", "000005")}
        conversion = convert(entries, images)
        self.assertIs(conversion.index_rows[0]["raw"], entries[0])
        self.assertEqual(conversion.index_rows[1]["raw"]["num"], "3(左)")
        self.assertEqual(conversion.index_rows[1]["raw"]["photo"], "000004+000003")
        self.assertEqual(conversion.index_rows[1]["photo_tokens"], ["000004", "000003"])

        root_id = conversion.index_rows[0]["question_id"]
        root = next(question for question in conversion.bundle.questions if question.question_id == root_id)
        self.assertEqual(
            [ref.image_id for ref in root.revisions[0].evidence_refs],
            ["image-000002", "image-000001", "image-000004", "image-000003", "image-000005"],
        )
        self.assertEqual([ref.sequence for ref in root.revisions[0].evidence_refs], [1, 2, 3, 4, 5])
        self.assertIs(root.revisions[0].review_state, ReviewState.DRAFT)
        self.assertIsNone(root.revisions[0].printed_text)
        self.assertIsNone(root.revisions[0].working_text)
        self.assertEqual(conversion.bundle.attempts, ())
        self.assertEqual(conversion.bundle.assessments, ())
        self.assertTrue(all(observation.revisions[0].author_state.value == "unknown" for observation in conversion.bundle.observations))

    def test_ids_are_deterministic_and_bundle_round_trips(self):
        entries = [row("J4", "12(2)-3", 3, "000001+000002")]
        images = {token: image(token) for token in ("000001", "000002")}
        first = convert(entries, images)
        later = convert(entries, images, recorded_at="2026-10-05T09:00:00+08:00")
        self.assertEqual([item["question_id"] for item in first.index_rows], [item["question_id"] for item in later.index_rows])
        self.assertEqual([item["question_revision_id"] for item in first.index_rows], [item["question_revision_id"] for item in later.index_rows])

        encoded = serialize_bundle(first.bundle)
        decoded = deserialize_bundle(encoded)
        self.assertEqual(decoded, first.bundle)
        self.assertEqual(serialize_bundle(decoded), encoded)

    def test_auxiliary_names_require_exact_mapping_and_deduplicate_stably(self):
        entries = [row("J3", "1", 1, "000001", aux="合成标签甲; 合成标签乙; 合成标签丙; 合成标签甲")]
        conversion = convert(entries, {"000001": image("000001")})
        index = conversion.index_rows[0]
        method_revision_ids = {method.revisions[0].name: method.revisions[0].header.revision_id for method in conversion.bundle.methods}
        self.assertEqual(index["aux_method_revision_ids"], [method_revision_ids[GROUPS[2]], method_revision_ids[GROUPS[5]]])

        blank = convert([row("J3", "2", 1, "000001")], {"000001": image("000001")}, auxiliary_mapping={})
        self.assertEqual(blank.index_rows[0]["aux_method_revision_ids"], [])
        for name in ("合成标签甲的近似名", "合成标签甲; 未映射标签"):
            with self.subTest(name=name), self.assertRaises(ContractError) as raised:
                convert([row("J3", "1", 1, "000001", aux=name)], {"000001": image("000001")})
            self.assertEqual(raised.exception.issues[0].code, "unknown_auxiliary_name")

    def test_profile_snapshots_mapping_and_rejects_invalid_mappings(self):
        mapping = {"合成名称": 2}
        profile = geometry_profile(mapping)
        mapping["合成名称"] = 5
        conversion = build_legacy_bundle(
            [row("J3", "1", 1, "000001", aux="合成名称")],
            GROUPS,
            {"000001": image("000001")},
            household_id=HOUSEHOLD,
            dataset_key="synthetic-profile",
            recorded_at=RECORDED,
            profile=profile,
        )
        method_revision_ids = {method.revisions[0].name: method.revisions[0].header.revision_id for method in conversion.bundle.methods}
        self.assertEqual(conversion.index_rows[0]["aux_method_revision_ids"], [method_revision_ids[GROUPS[2]]])

        for invalid in (None, {"": 1}, {" padded ": 1}, {"synthetic": True}, {"synthetic": 0}, {"synthetic": 7}, {1: 2}):
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                geometry_profile(invalid)

    def test_invalid_geometry_number_and_missing_photo_reject(self):
        for num in ("0", "1(0)", "1(左)-2", "1(中)", "1()"):
            with self.subTest(num=num), self.assertRaises(ContractError):
                convert([row("J3", num, 1, "000001")], {"000001": image("000001")})
        with self.assertRaises(ContractError) as raised:
            convert([row("J3", "1", 1, "000001+000099")], {"000001": image("000001")})
        self.assertEqual(raised.exception.issues[0].code, "unknown_photo")

    def test_calculation_profile_keeps_its_original_slash_syntax(self):
        entry = row("J1", "8(2)-3", 1, "000001/000002", aux="2 合成辅助标签")
        conversion = build_legacy_bundle(
            [entry],
            GROUPS,
            {token: image(token) for token in ("000001", "000002")},
            household_id=HOUSEHOLD,
            dataset_key="synthetic-calculation",
            recorded_at=RECORDED,
        )
        self.assertEqual(conversion.index_rows[0]["raw"], entry)
        self.assertEqual(conversion.index_rows[0]["photo_tokens"], ["000001", "000002"])
        self.assertEqual(conversion.index_rows[0]["num"], "8(2)-3")
        self.assertEqual(conversion.bundle.attempts, ())


if __name__ == "__main__":
    unittest.main()
