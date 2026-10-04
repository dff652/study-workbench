"""Bounded portable diagram bytes. No database, network or inferred provenance."""
import base64
import binascii
import io
from pathlib import PurePosixPath
import re
import xml.etree.ElementTree as ET

from PIL import Image

from app.exports.contracts import Block, ExportDocument, ExportError, SourceRef, digest, validate_document

FIELDS = {"question", "placement", "png_asset", "vector_asset", "source", "alt", "conditions",
          "width_points", "min_label_points", "independent_safe", "basis"}
MEDIA = {".png": "image/png", ".svg": "image/svg+xml", ".pdf": "application/pdf"}
MAX_BYTES = 512 * 1024


def fail(message):
    raise ExportError("invalid_asset", message)


def decode_assets(assets):
    if not isinstance(assets, dict) or len(assets) > 32:
        fail("assets 必须是最多 32 个明确本机资源的对象。")
    decoded = {}
    for key, item in assets.items():
        if not isinstance(key, str): fail("资产键须为文本。")
        path = PurePosixPath(key)
        if (not key or path.is_absolute() or ".." in path.parts or "\\" in key or ":" in key
                or str(path) != key or path.suffix not in MEDIA):
            fail("资产键必须是规范的本机相对 PNG／PDF／SVG 路径。")
        if (not isinstance(item, dict) or set(item) != {"sha256", "media_type", "base64"}
                or item["media_type"] != MEDIA[path.suffix] or not isinstance(item["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) or not isinstance(item["base64"], str)
                or len(item["base64"]) > (MAX_BYTES + 2) // 3 * 4):
            fail("资产字段、类型或大小无效。")
        try:
            raw = base64.b64decode(item["base64"], validate=True)
            if not 1 <= len(raw) <= MAX_BYTES or digest(raw) != item["sha256"]:
                fail("资产字节与 SHA256 不符或超过 512 KiB。")
            if path.suffix == ".png":
                with Image.open(io.BytesIO(raw), formats=["PNG"]) as image:
                    if image.width * image.height > 4_000_000 or getattr(image, 'n_frames', 1) != 1:
                        fail("PNG 超过 400 万像素。")
                    image.verify()
                with Image.open(io.BytesIO(raw), formats=["PNG"]) as image:
                    image.load()
            elif path.suffix == ".svg":
                source = raw.decode("utf-8-sig")
                if "<!DOCTYPE" in source.upper() or "<!ENTITY" in source.upper():
                    fail("SVG 不允许实体或外部声明。")
                tree = ET.fromstring(source)
                if tree.tag not in {"svg", "{http://www.w3.org/2000/svg}svg"}:
                    fail("矢量文件不是 SVG。")
                for element in tree.iter():
                    if element.tag.rsplit("}", 1)[-1] in {"script", "foreignObject", "image", "use", "a", "animate",
                            "animateMotion", "animateTransform", "set", "audio", "video", "iframe", "object", "embed", "feImage"}:
                        fail("SVG 不允许主动或外部内容。")
                    for name, value in element.attrib.items():
                        if (name.rsplit("}", 1)[-1].lower().startswith("on") or "href" in name.lower()
                                or any(token in value.lower() for token in ('url(', 'javascript:', '@import'))):
                            fail("SVG 不允许事件或资源引用。")
            else:
                # Retained vector bytes are never executed; native print renders the PNG.
                if not raw.startswith(b'%PDF-') or not raw.rstrip().endswith(b'%%EOF'):
                    fail("PDF 矢量文件头／结束标记无效。")
        except (binascii.Error, ValueError, UnicodeError, OSError, ET.ParseError, Image.DecompressionBombError) as exc:
            if isinstance(exc, ExportError):
                raise
            fail("资产不能完整解码或矢量结构无效。")
        decoded[key] = raw
    return decoded


def diagram_content(data, assets, source_ref):
    """Compatibility projection only; native saving derives its exact region reference."""
    png, vector = assets[data["png_asset"]], assets[data["vector_asset"]]
    return {"storage_key": data["png_asset"], "sha256": png["sha256"],
            "vector_storage_key": data["vector_asset"], "vector_sha256": vector["sha256"],
            "source_ref": source_ref, **{k: data[k] for k in
                ("alt", "conditions", "width_points", "min_label_points", "independent_safe")}}


def validate_records(rows, assets):
    decoded = decode_assets(assets)
    questions = {row["id"]: row["data"] for row in rows if row["kind"] == "question"}
    used = set()
    placements = set()
    for row in rows:
        if row["kind"] != "diagram":
            continue
        data = row["data"]
        if set(data) != FIELDS or not isinstance(data["question"], str) or data["question"] not in questions:
            fail("教学图必须引用本输入题目并提供全部明确字段。")
        if not isinstance(data['placement'], str) or data["placement"] not in {"question", "answer"} or (data["question"], data["placement"]) in placements:
            fail("同题同用途只接收一个图版本；替换使用原生修订入口。")
        placements.add((data["question"], data["placement"]))
        if (not isinstance(data['source'], dict) or set(data['source']) != {'source_id', 'bbox'}
                or data["source"] not in questions[data["question"]].get("sources", [])):
            fail("教学图来源必须是本题的一个明确原图区域。")
        if (not isinstance(data["basis"], str) or not data["basis"].strip() or len(data["basis"]) > 4000
                or not isinstance(data['alt'], str) or not data['alt'].strip() or len(data['alt']) > 2000
                or not isinstance(data['conditions'], list) or any(not isinstance(c, str) or len(c) > 1000 for c in data['conditions'])
                or any(not isinstance(data[k], str) or data[k] not in assets for k in ("png_asset", "vector_asset"))):
            fail("教学图资产或核对依据缺失。")
        if (assets[data["png_asset"]]["media_type"] != "image/png"
                or assets[data["vector_asset"]]["media_type"] not in {"application/pdf", "image/svg+xml"}):
            fail("教学图须提供 PNG 及明确配对的矢量源。")
        content = diagram_content(data, assets, "explicit-source")
        validate_document(ExportDocument("diagram-check", "教学图兼容", "parent_answers",
                          ((Block("diagram", content, data["placement"]),),), SourceRef("input", "0" * 64)))
        if data["placement"] == "question" and data["independent_safe"] is not True:
            fail("复测题面图须明确核对无提示；有提示构造放解析图。")
        used.update((data["png_asset"], data["vector_asset"]))
    if used != set(assets):
        fail("每个资源必须有明确原生对应；不能静默遗弃辅助图。")
    return decoded
