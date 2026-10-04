"""Closed, editable companion contract. Missing learning evidence stays missing."""
import re

from app.domain.arithmetic import ArithmeticError, formula_ast
from app.exports.contracts import canonical
from app.persistence import services as core


SCHEMA = "swb.solution.v1"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
RELATIONS = {"knowledge": "knowledge", "primary_method": "method",
             "secondary_method": "method", "question_type": "question_type"}
QUESTION_KEYS = {
    "id", "question_revision_id", "lecture_id", "number", "title", "statement", "sources", "parts",
    "thinking", "lecture_method", "alternative_method", "steps", "pitfalls", "formulas", "figures",
    "links", "corrections", "unknowns",
}


def fail(message):
    raise core.PersistenceError("invalid_solution", message)


def fields(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        fail("解析内容字段不完整，请刷新后重试。")


def text(value, maximum=20000, *, nullable=False, empty=True):
    if value is None and nullable:
        return
    if (type(value) is not str or len(value) > maximum or (not empty and not value.strip())
            or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value)):
        fail("请填写有效文字，并缩短超长内容。")


def array(value, maximum=100):
    if type(value) is not list or len(value) > maximum:
        fail("条目过多或格式无效，请分批整理。")


def identifier(value):
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        fail("条目标识无效，请刷新后重试。")


def source(ref, pages):
    fields(ref, {"page_id", "region"})
    page = pages.get(ref["page_id"]) if isinstance(ref["page_id"], str) else None
    if page is None:
        fail("来源必须属于当前资料。")
    region = ref["region"]
    if region is not None:
        image = page.image.payload
        if (type(region) is not list or len(region) != 4 or any(type(x) is not int for x in region)
                or not 0 <= region[0] < region[2] <= image["width"]
                or not 0 <= region[1] < region[3] <= image["height"]):
            fail("选区超出原图，请重新框选；整图来源请保留区域未知。")


def validate(content, pages, revisions, assets):
    fields(content, {"schema_version", "title", "lectures", "questions", "outputs"})
    if content["schema_version"] != SCHEMA or len(canonical(content)) > 1024 * 1024:
        fail("解析草稿版本不支持或内容超过 1 MiB。")
    text(content["title"], 160)
    array(content["lectures"])
    lectures = set()
    for lecture in content["lectures"]:
        fields(lecture, {"id", "title"})
        identifier(lecture["id"])
        text(lecture["title"], 160, empty=False)
        if lecture["id"] in lectures:
            fail("讲次不能重复。")
        lectures.add(lecture["id"])
    array(content["questions"])
    question_ids, part_ids, numbers = set(), set(), set()
    for question in content["questions"]:
        fields(question, QUESTION_KEYS)
        identifier(question["id"])
        if question["id"] in question_ids or type(question["lecture_id"]) is not str or question["lecture_id"] not in lectures:
            fail("题目重复或讲次不存在。")
        question_ids.add(question["id"])
        for name in ("number", "title"):
            text(question[name], 160)
        number = (question["lecture_id"], question["number"])
        if question["number"] and number in numbers:
            fail("同一讲内的题号不能重复。")
        numbers.add(number)
        rid = question["question_revision_id"]
        if rid is not None and (type(rid) is not str or rid not in revisions or revisions[rid].entity.kind != "question"):
            fail("题目版本不属于当前家庭。")
        fields(question["statement"], {"text", "status"})
        text(question["statement"]["text"], nullable=True)
        if question["statement"]["status"] not in ("complete", "partial", "unknown"):
            fail("请明确题干的完整程度。")
        array(question["sources"], 30)
        for ref in question["sources"]:
            source(ref, pages)
        array(question["parts"], 100)
        parts = {}
        for part in question["parts"]:
            fields(part, {"id", "parent_id", "label", "statement", "answer", "unit"})
            identifier(part["id"])
            if part["id"] in part_ids:
                fail("小问不能重复。")
            part_ids.add(part["id"])
            parts[part["id"]] = part
            if part["parent_id"] is not None:
                identifier(part["parent_id"])
            text(part["label"], 160)
            for name in ("statement", "answer", "unit"):
                text(part[name], nullable=True)
        for part in parts.values():
            parent, visited = part["parent_id"], {part["id"]}
            while parent is not None:
                if parent not in parts or parent in visited:
                    fail("小问的上级必须在同一题内，且不能循环引用。")
                visited.add(parent)
                parent = parts[parent]["parent_id"]
            if any(child["parent_id"] == part["id"] for child in parts.values()) and part["answer"]:
                fail("上级小问用于组织内容，答案请填写在末级小问。")
        for name in ("thinking", "lecture_method", "alternative_method"):
            text(question[name])
        for name in ("steps", "pitfalls", "unknowns", "formulas"):
            array(question[name])
            for value in question[name]:
                text(value, 512 if name == "formulas" else 20000)
                if name == "formulas" and value.strip():
                    try:
                        formula_ast(value)
                    except ArithmeticError as exc:
                        fail(f"公式暂不支持：{exc}")
        array(question["links"])
        seen_links = set()
        primary_count = 0
        for link in question["links"]:
            fields(link, {"revision_id", "relation"})
            if type(link["revision_id"]) is not str or type(link["relation"]) is not str:
                fail("请选择已有知识或方法。")
            node = revisions.get(link["revision_id"])
            kind = RELATIONS.get(link["relation"])
            if node is None or node.entity.kind != kind:
                fail("知识、方法或题型与选定的关联类型不符。")
            identity = (link["revision_id"], link["relation"])
            if identity in seen_links:
                fail("同一关系不能重复添加。")
            seen_links.add(identity)
            primary_count += link["relation"] == "primary_method"
        if primary_count > 1:
            fail("每道题只能指定一种主要方法。")
        array(question["figures"], 30)
        for figure in question["figures"]:
            fields(figure, {"asset_id", "role", "caption", "width_mm"})
            if type(figure["asset_id"]) is not str or figure["asset_id"] not in assets:
                fail("图示必须从当前资料已上传的图片中选择。")
            if figure["role"] not in ("question", "method", "answer"):
                fail("请指定图示用于题干、解法或答案。")
            text(figure["caption"], 2000)
            if type(figure["width_mm"]) not in (int, float) or not 10 <= figure["width_mm"] <= 172:
                fail("图示宽度须在 10～172 毫米之间。")
            asset = assets[figure["asset_id"]]
            if asset.source is not None and asset.source not in question["sources"]:
                fail("原图或裁切图须与该题的来源区域一致。")
        array(question["corrections"])
        for correction in question["corrections"]:
            fields(correction, {"kind", "original", "replacement", "basis"})
            if correction["kind"] not in ("printing_error", "naming", "draft_correction"):
                fail("请选择资料印刷错误、命名调整或草稿修正。")
            for name in ("original", "replacement", "basis"):
                text(correction[name], empty=False)
    fields(content["outputs"], {"per_question", "per_lecture", "combined"})
    for formats in content["outputs"].values():
        array(formats, 2)
        if any(type(value) is not str or value not in ("pdf", "docx") for value in formats) or len(set(formats)) != len(formats):
            fail("输出格式仅支持 PDF 和 Word。")


def gaps(content):
    result = []
    if not content["questions"]:
        result.append({"question_id": "", "message": "尚未添加题目"})
    for question in content["questions"]:
        messages = list(question["unknowns"])
        if question["statement"]["status"] != "complete" or not question["statement"]["text"]:
            messages.append("题干待补或待核对")
        if not question["sources"]:
            messages.append("原图来源待补")
        elif any(ref["region"] is None for ref in question["sources"]):
            messages.append("来源已关联整图，精确区域待补")
        parents = {part["parent_id"] for part in question["parts"]}
        if not question["parts"]:
            messages.append("小问及答案待补")
        for part in question["parts"]:
            if part["id"] in parents:
                continue
            if not part["answer"]:
                messages.append(f"{part['label'] or '小问'}：答案未知")
            if part["unit"] is None:
                messages.append(f"{part['label'] or '小问'}：单位待确认（无单位时可填写‘无单位’）")
        if not question["lecture_method"].strip():
            messages.append("本讲解法待补")
        result.extend({"question_id": question["id"], "message": message} for message in dict.fromkeys(messages) if message)
    return result
