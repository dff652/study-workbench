"""Chinese display labels for learning records and their evidence."""

ATTEMPT_KIND_LABELS = {
    "first": "首次",
    "correction": "订正",
    "retry": "重做",
    "retest": "复测",
}
SOURCE_KIND_LABELS = {
    "independent_answer": "独立作答",
    "assisted_answer": "提示后作答",
    "classroom_note": "课堂笔记",
    "copied_work": "抄录",
    "unknown": "来源未知",
}
INDEPENDENCE_LABELS = {
    "confirmed_independent": "人工确认独立",
    "not_independent": "确认非独立",
    "unknown": "未知／未确认",
}
PROMPT_STATUS_LABELS = {
    "none_confirmed": "人工确认无提示",
    "given": "有提示",
    "unknown": "提示情况未知",
}
LEGIBILITY_LABELS = {
    "readable": "清楚可辨",
    "partial": "部分可辨",
    "illegible": "看不清",
    "blank": "空白",
    "missing": "缺少证据",
    "unknown": "未知",
}
DIMENSION_LABELS = {
    "answer": "答案",
    "method": "方法选择",
    "process": "解题过程",
    "calculation": "计算",
    "notation": "符号表达",
}
JUDGMENT_LABELS = {
    "unknown": "无法判断",
    "correct": "正确",
    "incorrect": "错误",
    "partial": "部分完成",
}
BASIS_LABELS = {
    "observed": "直接观察到",
    "inferred": "推测",
    "undetermined": "依据尚未确定",
}
REVIEW_STATE_LABELS = {
    "draft": "待审核",
    "accepted": "已接受",
    "rejected": "已退回",
    "stale": "依赖已变化",
    "withdrawn": "已撤回",
}
ATTEMPT_STATE_LABELS = {
    "active": "有效",
    "withdrawn": "已撤回",
}


def label(mapping, value):
    """Return the Chinese display label while preserving unknown future values."""
    raw = getattr(value, "value", value)
    return mapping.get(raw, raw or "未知")


def attempt_choice_label(attempt_id, revision, question_title=""):
    """Describe one real event without changing its selected revision or date."""
    known_date = getattr(revision.actual_date_state, "value", revision.actual_date_state) == "known"
    day = str(revision.actual_date) if known_date and revision.actual_date else "日期未知"
    answer = " ".join((revision.answer_text or "").split())[:40] or "答案未记录"
    conditions = f"{label(INDEPENDENCE_LABELS, revision.independence)}／{label(PROMPT_STATUS_LABELS, revision.prompt_status)}"
    parts = [day, label(ATTEMPT_KIND_LABELS, revision.attempt_kind), label(SOURCE_KIND_LABELS, revision.source_kind)]
    if question_title:
        parts.append(question_title[:40])
    parts.extend([conditions, answer, f"#{attempt_id[-8:]}"])
    return " · ".join(parts)
