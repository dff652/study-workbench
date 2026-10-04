"""Pure compatibility projection; no database, filesystem assets or model calls."""
from copy import deepcopy
import math
from app.exports.contracts import ExportError, canonical, digest, document_from_dict, PURPOSES


def validate_packet(packet, sources=None, catalog=None, records=None, assets=None):
    required = {"schema_version", "batch_id", "sources_sha256", "catalog_sha256", "documents", "omitted_purposes"}
    if (not isinstance(packet, dict) or not required <= set(packet) or set(packet) - required - {"review"}
            or packet["schema_version"] != "swf.packet.v1" or not isinstance(packet["batch_id"], str) or not packet["batch_id"]):
        raise ExportError("invalid_packet", "skill 包字段或版本无效。")
    for value, key in ((sources, "sources_sha256"), (catalog, "catalog_sha256")):
        sha = packet[key]
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ExportError("invalid_packet", "skill 输入哈希无效。")
        if value is not None and (not isinstance(value, dict) or value.get("batch_id") != packet["batch_id"] or digest(canonical(value)) != sha):
            raise ExportError("stale_input", "skill 包不对应选定输入。")
    if not isinstance(packet["documents"], list) or len(packet["documents"]) != 5 or packet["omitted_purposes"] != []:
        raise ExportError("invalid_packet", "完整五册必须齐备。")
    purposes, ids = [], []
    for original in packet["documents"]:
        if not isinstance(original, dict) or original.get("schema_version") != "swf.print.v1":
            raise ExportError("invalid_packet", "skill 文档契约版本无效。")
        projection = deepcopy(original)
        if not isinstance(projection.get('pages'), list):
            raise ExportError('invalid_document', '文档 pages 须为页面数组。')
        for page in projection['pages']:
            if not isinstance(page, list):
                raise ExportError('invalid_document', '每页须为 block 数组。')
            for block in page:
                if not isinstance(block, dict):
                    raise ExportError('invalid_block', '每个 block 须为对象。')
                if block.get("kind") == "formula_image":
                    raise ExportError("unsupported_asset", "公式位图尚无明确原生对应；请提供封闭公式 AST，不静默删图。")
                if block.get("kind") != "diagram":
                    continue
                from .assets import diagram_content
                content = block.get("content")
                fields = {"storage_key", "sha256", "source_ref", "alt", "width_mm", "no_hint_confirmed"}
                if (not isinstance(content, dict) or set(content) != fields
                        or type(content["width_mm"]) not in (int, float) or not math.isfinite(content["width_mm"])
                        or not 10 <= content["width_mm"] <= 172 or type(content["no_hint_confirmed"]) is not bool):
                    raise ExportError("invalid_diagram", "旧图示字段或尺寸无效。")
                matches = [row["data"] for row in (records or []) if row["kind"] == "diagram"
                           and row["data"]["png_asset"] == content["storage_key"]
                           and row["data"]["placement"] == block.get("role")]
                if len(matches) != 1 or not assets or content["storage_key"] not in assets:
                    raise ExportError("missing_asset_mapping", "五册图示须精确对应本输入一个教学图记录与真实资产。")
                data = matches[0]
                if (assets[content["storage_key"]]["sha256"] != content["sha256"] or content["alt"] != data["alt"]
                        or content["no_hint_confirmed"] != data["independent_safe"]
                        or abs(content["width_mm"] * 72 / 25.4 - data["width_points"]) > 1e-6):
                    raise ExportError("stale_asset_mapping", "五册图示哈希、用途、宽度或提示状态与伴随记录不符。")
                block["content"] = diagram_content(data, assets, content["source_ref"])
        document = document_from_dict({**projection, "schema_version": "study-workbench.print.v0.1"})
        if document.source.sha256 != packet["catalog_sha256"]:
            raise ExportError("stale_source", "文档来源哈希与目录不符。")
        purposes.append(document.purpose)
        ids.append(document.document_id)
    if set(purposes) != PURPOSES or len(set(ids)) != 5:
        raise ExportError("invalid_packet", "五册用途或文档身份重复。")
    # A tool's review ledger is retained as evidence of its work, never native publication.
    return packet
