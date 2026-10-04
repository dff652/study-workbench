"""Product labels shared by server forms and read-only screen fragments."""
from collections import Counter
from .learning_labels import (
    ATTEMPT_KIND_LABELS, BASIS_LABELS, DIMENSION_LABELS, INDEPENDENCE_LABELS,
    JUDGMENT_LABELS, LEGIBILITY_LABELS, PROMPT_STATUS_LABELS, SOURCE_KIND_LABELS,
)


LABELS = {
    **ATTEMPT_KIND_LABELS, **BASIS_LABELS, **DIMENSION_LABELS,
    **INDEPENDENCE_LABELS, **JUDGMENT_LABELS, **LEGIBILITY_LABELS,
    **PROMPT_STATUS_LABELS, **SOURCE_KIND_LABELS,
    "accepted": "已核对", "rejected": "退回修改", "withdrawn": "已撤回",
    "unreviewed": "待核对", "draft": "草稿", "pending": "待核对",
    "confirmed": "已确认", "known": "已确认", "unknown": "未知",
    "manual": "人工录入", "human": "人工录入", "ocr": "图片转写",
    "import": "资料导入", "imported": "导入待核对", "ai": "模型建议",
    "stale": "关联内容已变化", "active": "有效", "ready": "已就绪",
    "model": "模型建议", "derived": "整理生成", "primary": "主要方法",
    "secondary": "辅助方法", "prerequisite": "前置知识", "tested": "考查知识",
    "definition": "定义出处", "formula": "公式", "diagram": "图示", "other": "其他来源",
    "question": "题干", "knowledge": "知识点",
    "question_type": "题型", "method": "方法", "answer": "答案",
    "solution": "解析", "handwriting": "手写内容", "context": "背景资料",
    "learner": "学习者", "observation": "来源观察", "assessment": "评价",
    "attempt": "作答", "teaching_diagram": "教学图", "erratum": "资料勘误",
    "parent_answers": "家长答案", "student_practice": "学生练习",
    "independent_retest": "无提示复测", "knowledge_summary": "知识整理",
    "parent_observation": "家长观察", "independent_practice": "无提示练习", "classification_index": "分类索引", "learning_report": "学习报告",
    "printed_text": "题干待补", "original_number": "原题号待补",
    "region": "来源区域待补", "region_id": "来源区域待补",
    "region_revision_id": "来源区域待补", "unit": "单位待确认",
    "source": "来源待补", "source_region": "来源区域待补",
    "owner": "家庭所有者", "reviewer": "审核成员", "viewer": "只读成员",
    "planned": "安排中", "rescheduled": "已改期", "completed": "已完成复习",
    "cancelled": "已取消", "queued": "等待处理", "running": "正在处理",
    "failed": "未完成", "manual_entry": "人工录入", "not_tested": "尚未测试",
}


def ui_label(value, kind=None):
    value = getattr(value, "value", value)
    if value is None or value == "":
        return "待确认"
    if kind == "judgment":
        return JUDGMENT_LABELS.get(str(value), "无法判断")
    if any("\u4e00" <= char <= "\u9fff" for char in str(value)):
        return str(value)
    return LABELS.get(str(value), "待确认")


def household_choices(rows):
    rows = list(rows)
    return [(str(row.household_id), "我的家庭" if len(rows) == 1 else f"家庭 {index}")
            for index, row in enumerate(rows, 1)]


def distinct_choices(pairs):
    """Disambiguate same-name choices while keeping private values unchanged."""
    pairs = list(pairs)
    counts, seen = Counter(label for _, label in pairs), Counter()
    result = []
    for value, label in pairs:
        seen[label] += 1
        result.append((value, label if counts[label] == 1 else f"{label}（同名条目 {seen[label]}）"))
    return result
