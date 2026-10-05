"""Editable knowledge content, separate from question and learner evidence."""
from app.domain.arithmetic import ArithmeticError, formula_ast
from app.exports.contracts import canonical
from app.persistence import services as core
from app.web import subjects
from . import schema
from .vendor.knowledge_model import SUBJECT_KINDS, SECTION_LABELS

SCHEMA = "swb.knowledge.v1"
PROFILES = {"mathematics": "数学证明", "science": "科学观察", "language": "语言分析", "humanities": "人文证据"}
ITEM_KEYS = {"id", "knowledge_revision_id", "lecture_id", "order", "title", "kind", "origin", "sources",
    "original", "statement", "definitions", "conditions", "dependencies", "steps", "corrections", "unknowns"}


def fail(message):
    raise core.PersistenceError("invalid_knowledge", message)


def fields(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        fail("知识讲解字段不完整，请保留输入并重新读取。")


def figures(item):
    for step in item["steps"]:
        if step["figure"] is not None:
            yield step["figure"]


def validate(content, pages, revisions, assets):
    fields(content, {"schema_version", "title", "school_subject", "learner_level", "lectures", "knowledge", "outputs"})
    if content["schema_version"] != SCHEMA or len(canonical(content)) > 1024 * 1024:
        fail("知识草稿版本不支持或内容超过 1 MiB。")
    subjects.validate(content["school_subject"])
    schema.text(content["title"], 160)
    schema.text(content["learner_level"], 160)
    schema.array(content["lectures"])
    lectures = {}
    for lecture in content["lectures"]:
        fields(lecture, {"id", "title", "rule_profile"})
        schema.identifier(lecture["id"])
        schema.text(lecture["title"], 160, empty=False)
        if type(lecture["rule_profile"]) is not str or lecture["rule_profile"] not in PROFILES:
            fail("请为每讲选择讲解依据类别，它与学校学科分别保存。")
        if lecture["id"] in lectures:
            fail("讲次不能重复。")
        lectures[lecture["id"]] = lecture
    schema.array(content["knowledge"])
    items, step_ids, orders = {}, set(), set()
    for item in content["knowledge"]:
        fields(item, ITEM_KEYS)
        schema.identifier(item["id"])
        if (item["id"] in items or type(item["lecture_id"]) is not str or item["lecture_id"] not in lectures
                or type(item["order"]) is not int or not 1 <= item["order"] <= 10000):
            fail("知识条目、讲次或顺序无效。")
        order = (item["lecture_id"], item["order"])
        if order in orders:
            fail("同讲的知识顺序不能重复。")
        orders.add(order)
        profile = lectures[item["lecture_id"]]["rule_profile"]
        if type(item["kind"]) is not str or item["kind"] not in SUBJECT_KINDS[profile]:
            fail("知识性质与本讲的依据类别不符，请核对定义、定理或解释的类型。")
        if item["origin"] not in ("source", "foundation", "supplement"):
            fail("请说明知识来自原页、基础知识还是补充知识。")
        rid = item["knowledge_revision_id"]
        if rid is not None and (type(rid) is not str or rid not in revisions or revisions[rid].entity.kind != "knowledge"):
            fail("关联知识版本不属于当前家庭。")
        for name in ("title", "statement", "definitions", "original"):
            schema.text(item[name], 160 if name == "title" else 2000)
        for name in ("conditions", "unknowns", "dependencies"):
            schema.array(item[name])
            for value in item[name]:
                schema.text(value, 2000, empty=False)
        schema.array(item["sources"], 30)
        page_ids = set()
        for ref in item["sources"]:
            fields(ref, {"page_id", "region", "printed_page"})
            schema.source({"page_id": ref["page_id"], "region": ref["region"]}, pages)
            schema.text(ref["printed_page"], 160, nullable=True)
            if ref["page_id"] in page_ids:
                fail("同一知识的原图来源不能重复。")
            page_ids.add(ref["page_id"])
        schema.array(item["steps"])
        for step in item["steps"]:
            fields(step, {"id", "section", "text", "formula", "figure", "new_page"})
            schema.identifier(step["id"])
            if step["id"] in step_ids:
                fail("讲解步骤不能重复。")
            step_ids.add(step["id"])
            if type(step["section"]) is not str or step["section"] not in SECTION_LABELS:
                fail("请选择步骤所属的讲解部分。")
            schema.text(step["text"], 2000)
            schema.text(step["formula"], 512, nullable=True)
            if step["formula"]:
                try:
                    formula_ast(step["formula"])
                except ArithmeticError as exc:
                    fail(str(exc))
            if type(step["new_page"]) is not bool:
                fail("请明确是否在步骤前分页。")
        source_item = {"sources": [{"page_id": r["page_id"], "region": r["region"]} for r in item["sources"]]}
        for figure in figures(item):
            schema.validate_figure(figure, source_item, assets)
        schema.array(item["corrections"])
        for correction in item["corrections"]:
            fields(correction, {"kind", "original", "replacement", "basis"})
            if correction["kind"] not in ("printing_error", "naming", "draft_correction"):
                fail("请分别记录资料印刷错误、命名或草稿订正。")
            for name in ("original", "replacement", "basis"):
                schema.text(correction[name], 2000, empty=False)
        items[item["id"]] = item
    active, complete = set(), set()
    def visit(identifier):
        if identifier in active:
            fail("知识依赖不能成环或依赖自身。")
        if identifier in complete:
            return
        active.add(identifier)
        dependencies = items[identifier]["dependencies"]
        if len(set(dependencies)) != len(dependencies) or any(value not in items for value in dependencies):
            fail("知识依赖重复或未包含在这份讲解中。")
        for value in dependencies:
            visit(value)
        active.remove(identifier)
        complete.add(identifier)
    for identifier in items:
        visit(identifier)
    fields(content["outputs"], {"inventory", "per_knowledge", "per_lecture", "combined"})
    for formats in content["outputs"].values():
        schema.array(formats, 2)
        if any(type(value) is not str or value not in ("pdf", "docx") for value in formats) or len(set(formats)) != len(formats):
            fail("输出格式仅支持 PDF 和 Word。")


def gaps(content):
    result = []
    if not content["knowledge"]:
        result.append({"knowledge_id": "", "message": "尚未添加知识条目"})
    if not content["learner_level"].strip():
        result.append({"knowledge_id": "", "message": "学习层级待说明"})
    for item in content["knowledge"]:
        notes = list(item["unknowns"])
        for field, label in (("title", "名称"), ("statement", "完整结论")):
            if not item[field].strip():
                notes.append(label + "待补")
        if item["origin"] == "source" and (not item["sources"] or not item["original"].strip()):
            notes.append("原页结论和原图来源待补")
        if not item["conditions"]:
            notes.append("适用条件待补")
        present = {step["section"] for step in item["steps"] if step["text"].strip()}
        for section in set(SECTION_LABELS) - {"other"} - present:
            notes.append(SECTION_LABELS[section] + "待补")
        result.extend({"knowledge_id": item["id"], "message": note} for note in dict.fromkeys(notes))
    return result
