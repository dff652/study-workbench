import unittest

from app.domain.attempt_ordering import order_attempts


def attempt(attempt_id, *, day="2026-10-01", created_at, previous=None,
            question="q1", learner="learner-1", kind="first", state="active",
            replacement=None, recorded_at=None):
    return {
        "attempt_id": attempt_id,
        "previous_attempt_id": previous,
        "question_id": question,
        "learner_id": learner,
        "attempt_kind": kind,
        "state": state,
        "replacement_attempt_id": replacement,
        "actual_date_state": "known" if day else "unknown",
        "actual_date": day,
        "created_at": created_at,
        # Current revision timestamp is intentionally irrelevant to ordering.
        "recorded_at": recorded_at or created_at,
    }


class AttemptOrderingTests(unittest.TestCase):
    def test_same_day_branches_follow_valid_previous_edges_then_original_entry_time(self):
        first = attempt("z-first", created_at="2026-10-01T09:00:00+08:00")
        correction = attempt("a-correction", created_at="2026-10-01T10:00:00+08:00",
                            previous="z-first", kind="retry")
        branch_retest = attempt("m-retest", created_at="2026-10-01T11:00:00+08:00",
                                previous="z-first", kind="retest")
        repeated_retest = attempt("b-retest", created_at="2026-10-01T12:00:00+08:00",
                                  previous="a-correction", kind="retest")

        result = order_attempts([first, correction, branch_retest, repeated_retest])

        self.assertEqual([row["attempt_id"] for row in result],
                         ["b-retest", "m-retest", "a-correction", "z-first"])
        self.assertEqual({row["ordering_basis"] for row in result}, {"same_day_chain"})
        self.assertTrue(all(row["ordering_group"] == "known_date" for row in result))

    def test_actual_day_beats_cross_day_parent_and_current_revision_time(self):
        later_actual_day_parent = attempt("parent", day="2026-10-03",
            created_at="2026-10-01T08:00:00+08:00")
        earlier_actual_day_child = attempt("child", day="2026-10-02",
            created_at="2026-10-01T09:00:00+08:00", previous="parent",
            # Editing an old record must not make it appear newly entered.
            recorded_at="2026-10-06T22:00:00+08:00")
        standalone_same_day = attempt("standalone", day="2026-10-03",
            created_at="2026-10-01T10:00:00+08:00")

        result = order_attempts([later_actual_day_parent, earlier_actual_day_child,
                                 standalone_same_day])

        self.assertEqual([row["attempt_id"] for row in result],
                         ["standalone", "parent", "child"])
        self.assertEqual(result[-1]["ordering_basis"], "actual_date")
        self.assertEqual(result[0]["ordering_basis"], "first_recorded_at")

    def test_unknown_dates_are_a_separate_last_group_and_use_initial_time(self):
        unknown_old = attempt("unknown-old", day=None,
            created_at="2026-10-01T09:00:00+08:00",
            recorded_at="2026-10-06T23:00:00+08:00")
        dated = attempt("dated", day="2026-10-01",
            created_at="2026-10-01T08:00:00+08:00")
        unknown_new = attempt("unknown-new", day=None,
            created_at="2026-10-01T10:00:00+08:00")

        result = order_attempts([unknown_old, dated, unknown_new])

        self.assertEqual([row["attempt_id"] for row in result],
                         ["dated", "unknown-new", "unknown-old"])
        self.assertEqual([row["ordering_group"] for row in result],
                         ["known_date", "unknown_date", "unknown_date"])
        self.assertEqual(result[1]["ordering_basis"], "first_recorded_at_unknown_date")

    def test_exact_entry_time_tie_uses_stable_input_order_not_identifier_or_kind(self):
        older_input = attempt("z-id", kind="retest", created_at="2026-10-01T09:00:00Z")
        newer_input = attempt("a-id", kind="first", created_at="2026-10-01T09:00:00Z")

        result = order_attempts([older_input, newer_input])

        self.assertEqual([row["attempt_id"] for row in result], ["a-id", "z-id"])
        self.assertEqual({row["ordering_basis"] for row in result}, {"first_recorded_at"})

    def test_only_same_question_and_learner_previous_links_order_as_a_chain(self):
        parent = attempt("parent", created_at="2026-10-01T09:00:00Z")
        same_day_but_other_question = attempt("other-question", created_at="2026-10-01T11:00:00Z",
                                               previous="parent", question="q2")
        same_day_but_other_learner = attempt("other-learner", created_at="2026-10-01T10:00:00Z",
                                              previous="parent", learner="learner-2")

        result = order_attempts([parent, same_day_but_other_question, same_day_but_other_learner])

        self.assertEqual([row["attempt_id"] for row in result],
                         ["other-question", "other-learner", "parent"])
        self.assertEqual({row["ordering_basis"] for row in result}, {"first_recorded_at"})

    def test_withdrawn_identity_and_replacement_links_remain_separate_events(self):
        original = attempt("original", created_at="2026-10-01T09:00:00Z",
                           state="withdrawn", replacement="replacement")
        replacement = attempt("replacement", created_at="2026-10-01T10:00:00Z")
        replacement["supersedes_attempt_id"] = "original"

        result = order_attempts([original, replacement])

        self.assertEqual([row["attempt_id"] for row in result], ["replacement", "original"])
        self.assertEqual(result[0]["state"], "active")
        self.assertEqual(result[1]["state"], "withdrawn")
        self.assertEqual(result[1]["replacement_attempt_id"], "replacement")
        self.assertEqual({row["ordering_basis"] for row in result}, {"first_recorded_at"})


if __name__ == "__main__":
    unittest.main()
