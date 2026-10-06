"""Consistent ordering for recorded learning events.

Actual dates order events first. Within one known date, an explicit previous
attempt relationship orders a child before its parent in a newest-first list.
Unrelated events use the attempt's original recording time, then source order.
Revision timestamps and identifiers are deliberately not ordering inputs.
"""

from datetime import date, datetime, timezone
from heapq import heappop, heappush
from typing import Iterable, Mapping


def _date_key(row: Mapping) -> str | None:
    state = getattr(row.get("actual_date_state"), "value", row.get("actual_date_state"))
    value = row.get("actual_date")
    if state != "known" or value in (None, ""):
        return None
    if isinstance(value, datetime):
        value = value.date()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return None


def _recorded_key(value: object) -> float | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(timezone.utc).timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _same_attempt_scope(child: Mapping, parent: Mapping) -> bool:
    child_question, parent_question = child.get("question_id"), parent.get("question_id")
    if not child_question or child_question != parent_question:
        return False
    child_learner, parent_learner = child.get("learner_id"), parent.get("learner_id")
    return not (child_learner and parent_learner and child_learner != parent_learner)


def _newest_first(indices: list[int], rows: list[dict], date_by_index: dict[int, str | None]) -> list[int]:
    """Topologically order same-date attempts, preferring later originals."""
    index_by_id = {rows[index].get("attempt_id"): index for index in indices
                   if rows[index].get("attempt_id")}
    next_indices: dict[int, list[int]] = {index: [] for index in indices}
    indegree = {index: 0 for index in indices}

    # A child precedes its previous attempt in a newest-first chronology.
    # Links across dates are intentionally ignored because actual date wins.
    for child_index in indices:
        child = rows[child_index]
        parent_index = index_by_id.get(child.get("previous_attempt_id"))
        if (parent_index is None or date_by_index[child_index] is None
                or date_by_index[parent_index] != date_by_index[child_index]
                or not _same_attempt_scope(child, rows[parent_index])):
            continue
        next_indices[child_index].append(parent_index)
        indegree[parent_index] += 1

    recorded = {index: _recorded_key(rows[index].get("created_at")) for index in indices}
    ready: list[tuple[int, float, int, int]] = []

    def enqueue(index: int) -> None:
        stamp = recorded[index]
        # Latest original entry first; a later stable input position breaks an
        # exact timestamp tie without consulting attempt IDs or event labels.
        heappush(ready, (-(stamp is not None), -(stamp or 0.0), -index, index))

    for index in indices:
        if indegree[index] == 0:
            enqueue(index)

    ordered: list[int] = []
    while ready:
        _, _, _, index = heappop(ready)
        ordered.append(index)
        for parent_index in next_indices[index]:
            indegree[parent_index] -= 1
            if indegree[parent_index] == 0:
                enqueue(parent_index)

    # Valid bundles reject previous-attempt cycles. If a caller supplies an
    # invalid partial graph, keep the remaining items deterministic by the
    # same timestamp/input rule instead of falling back to IDs.
    if len(ordered) != len(indices):
        remaining = set(indices) - set(ordered)
        ordered.extend(sorted(remaining, key=lambda index: (
            recorded[index] is not None,
            recorded[index] if recorded[index] is not None else 0.0,
            index,
        ), reverse=True))
    return ordered


def order_attempts(rows: Iterable[Mapping]) -> list[dict]:
    """Return copied attempt rows in a shared newest-first presentation order.

    Required fields are ``attempt_id``, ``actual_date_state`` and
    ``actual_date``. ``previous_attempt_id``, ``question_id``, ``learner_id``
    and the original ``created_at`` are used when available. Returned rows
    include grouping and explanation fields for the UI.
    """
    result = [dict(row) for row in rows]
    date_by_index = {index: _date_key(row) for index, row in enumerate(result)}
    dated: dict[str, list[int]] = {}
    unknown: list[int] = []
    for index, day in date_by_index.items():
        if day is None:
            unknown.append(index)
        else:
            dated.setdefault(day, []).append(index)

    ordered_indices: list[int] = []
    chain_members: set[int] = set()
    for day in sorted(dated, reverse=True):
        indices = dated[day]
        index_by_id = {result[index].get("attempt_id"): index for index in indices
                       if result[index].get("attempt_id")}
        for child_index in indices:
            row = result[child_index]
            parent_index = index_by_id.get(row.get("previous_attempt_id"))
            if (parent_index is not None and parent_index != child_index
                    and _same_attempt_scope(row, result[parent_index])):
                chain_members.update((child_index, parent_index))
        ordered_indices.extend(_newest_first(indices, result, date_by_index))

    # Unknown dates remain a separately identifiable final group. Their list
    # order uses only the original record time and stable input position.
    ordered_indices.extend(_newest_first(unknown, result, date_by_index))

    same_day_counts = {day: len(indices) for day, indices in dated.items()}
    for index, row in enumerate(result):
        day = date_by_index[index]
        if day is None:
            row.update(ordering_group="unknown_date",
                       ordering_basis="first_recorded_at_unknown_date",
                       ordering_basis_label="实际日期未知，按初次录入时间排列")
        elif index in chain_members:
            row.update(ordering_group="known_date", ordering_basis="same_day_chain",
                       ordering_basis_label="同日按前次作答关系排列")
        elif same_day_counts[day] > 1:
            row.update(ordering_group="known_date", ordering_basis="first_recorded_at",
                       ordering_basis_label="同日按初次录入时间排列")
        else:
            row.update(ordering_group="known_date", ordering_basis="actual_date",
                       ordering_basis_label="按实际作答日期排列")
    return [result[index] for index in ordered_indices]
