"""Closed skill exchange. Document prose never becomes inferred learning events."""
import json
import re

from app.exports.contracts import canonical, digest, ExportError
from app.persistence import services as core
from .skill_packet import validate_packet

SCHEMA = "swb.skill-import.v1"
SCHEMA_V2 = "swb.skill-import.v2"
KINDS = {"question", "knowledge", "method", "question_type", "answer", "link", "observation", "diagram"}


def fail(message):
    raise core.PersistenceError("invalid_exchange", message)


def decode(raw):
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        fail("交换包必须为不超过 1 MiB 的 JSON。")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("交换包包含重复键。")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _value: fail("不允许非有限数值。"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        fail("交换包不是有效 JSON。")
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 100:
            fail("交换包嵌套不能超过 100 层。")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def validate(value, pages):
    if not isinstance(value, dict) or set(value) - {"schema_version", "sources", "records", "packet", "ledger", "catalog", "tool_inputs", "assets"}:
        fail("交换包字段不受支持；不丢弃未知字段。")
    if not isinstance(value.get('schema_version'), str) or value.get("schema_version") not in {SCHEMA, SCHEMA_V2}:
        fail("请使用明确的结构化交换契约；旧索引或五册正文不能替代完整题库。")
    if (value["schema_version"] == SCHEMA and "assets" in value) or (value["schema_version"] == SCHEMA_V2 and "assets" not in value):
        fail("图示资产须使用明确的 v2 契约。")
    sources = value.get("sources")
    rows = value.get("records")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 100 or not isinstance(rows, list) or len(rows) > 300:
        fail("来源或条目数量无效。")
    source_map = {}
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"id", "page_id", "sha256"}:
            fail("每个来源必须明确页 ID 与原图 SHA256。")
        identity = source["id"]
        if not isinstance(source['page_id'], str): fail("资料页身份须为明确字符串。")
        page = pages.get(source["page_id"])
        if not isinstance(identity, str) or not re.fullmatch(r"[\w.-]{1,100}", identity) or identity in source_map:
            fail("来源身份重复或无效。")
        if page is None or source["sha256"] != page.image.sha256:
            fail("来源与当前资料页不一致。")
        from app.web.services import asset_path
        asset_path(page.image.payload["storage_key"], source["sha256"])
        source_map[identity] = page
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "kind", "data"} or not isinstance(row.get('kind'), str) or row.get("kind") not in KINDS:
            fail("草稿类型或字段无效；学习评价必须走明确的逐次作答流程。")
        if not isinstance(row["id"], str) or not re.fullmatch(r"[\w.-]{1,100}", row["id"]) or row["id"] in ids:
            fail("草稿身份重复或无效。")
        ids.add(row["id"])
        if not isinstance(row["data"], dict):
            fail("草稿内容必须为对象。")
        if row["kind"] == "diagram" and value["schema_version"] != SCHEMA_V2:
            fail("教学图记录须使用 v2 契约。")
        refs = row["data"].get("sources", [])
        if not isinstance(refs, list) or len(refs) > 30:
            fail("来源区域数量无效。")
        for ref in refs:
            if (not isinstance(ref, dict) or set(ref) != {"source_id", "bbox"}
                    or not isinstance(ref.get('source_id'), str) or ref.get("source_id") not in source_map):
                fail("区域必须引用已映射的原图。")
            box = ref["bbox"]
            page = source_map[ref["source_id"]]
            if (not isinstance(box, list) or len(box) != 4 or any(type(n) is not int for n in box)
                    or not 0 <= box[0] < box[2] <= page.image.payload["width"] or not 0 <= box[1] < box[3] <= page.image.payload["height"]):
                fail("区域使用原图整数坐标；未知坐标不能自动补全。")
        if row["kind"] in {"question", "knowledge", "method", "question_type", "observation"} and not refs:
            fail("内容条目必须提供明确来源区域。")
    try:
        from .assets import validate_records
        validate_records(rows, value.get("assets", {}))
    except (ExportError, KeyError, TypeError, ValueError) as exc:
        fail(str(exc))
    packet = value.get("packet")
    if packet is not None:
        try:
            tool = value.get("tool_inputs", {})
            if not isinstance(tool, dict):
                fail("工具输入记录必须为对象。")
            validate_packet(packet, tool.get("sources"), value.get("catalog"), rows, value.get("assets", {}))
        except ExportError as exc:
            fail(str(exc))
    # Force finite, bounded JSON after all checks, retaining catalog/ledger verbatim.
    try:
        if len(canonical(value)) > 1024 * 1024:
            fail("交换包过大。")
    except (ValueError, TypeError):
        fail("交换包不能规范化。")
    return digest(canonical(value))
