"""Read verified v3 snapshots rather than execute or depend on historical builders."""
from copy import deepcopy
import json
from pathlib import Path

from app.imports.package import checked_bytes, read_json
from .contracts import Block, ExportDocument, SourceRef, canonical, digest, document_dict, validate_document


# Only presentation labels are part of this adapter. Study records stay in private JSON.
LEGACY_MAP = {"root": ["计算专题", "观察结构", "选择方法"], "groups": [
    {"label": ["1 基础变形与换元"], "detail": ["拆数、凑整、提取公因数", "整体换元；平方差与完全平方"]},
    {"label": ["2 公式与通项"], "detail": ["首项、公差、项数、通项", "等差和、奇数和、平方和、立方和"]},
    {"label": ["3 分数裂项"], "detail": ["裂差、裂和、三因子分母", "先看结构，再定系数与首尾"]},
    {"label": ["4 整数裂项"], "detail": ["连续或等差因子的乘积求和", "构造多一个因子的乘积之差"]},
    {"label": ["5 比较与估算"], "detail": ["统一形式、与 1 比较", "循环小数；放缩连接裂项"]},
    {"label": ["6 方程与新定义"], "detail": ["比例、消元、特殊平方方程", "翻译规则；迭代、周期、取整"]},
]}
TITLES = ("五年级奥数｜知识地图与总结", "五年级奥数｜逐题分类索引", "五年级奥数｜知识与技巧掌握评价",
          "五年级奥数｜独立复测题", "五年级奥数｜复测答案与观察记录")
PURPOSES = ("knowledge_summary", "classification_index", "evidence_report", "independent_practice", "parent_answers")
EXPECTED_PAGES = (8, 12, 5, 2, 2)


def legacy_document(raw, *, ordinal, source_sha):
    pages = read_json(raw)
    converted = []
    for page in pages:
        blocks = []
        for kind, content in page:
            role = "body"
            if ordinal == 4:
                role = "title" if kind == "title" else "question" if kind in {"h", "math"} else "instruction"
                if kind == "p":
                    role = "answer_space" if content.startswith("过程：") else "question"
            if kind == "map":
                if content is not None:
                    raise ValueError("Unexpected historical map payload")
                content = deepcopy(LEGACY_MAP)
            blocks.append(Block(kind, content, role))
        converted.append(tuple(blocks))
    document = ExportDocument(f"legacy-{ordinal:02d}", TITLES[ordinal - 1], PURPOSES[ordinal - 1],
        tuple(converted), SourceRef(f"legacy-v3-content-{ordinal:02d}", source_sha))
    validate_document(document)
    if len(document.pages) != EXPECTED_PAGES[ordinal - 1]:
        raise ValueError("Historical page count differs from the fixed inventory")
    return document


def load_legacy_documents(inventory_path):
    """Return verified source bytes, specs and baseline records. No old code executes."""
    inventory_raw = Path(inventory_path).read_bytes()
    inventory = read_json(inventory_raw)
    root = Path(inventory["source_root"]).resolve()
    records = [row for row in inventory["files"] if row["path"].startswith("documents/v3/") and row["path"].endswith("/content.json")]
    records.sort(key=lambda row: row["path"])
    if len(records) != 5:
        raise ValueError("Expected the five existing v3 snapshots")
    documents, sources, baselines = [], {}, []
    for ordinal, record in enumerate(records, 1):
        raw = checked_bytes(root, record)
        documents.append(legacy_document(raw, ordinal=ordinal, source_sha=record["sha256"]))
        sources[f"content-{ordinal:02d}.source.json"] = raw
        parent = Path(record["path"]).parent
        baseline = {}
        for suffix in ("pdf", "docx"):
            matches = [row for row in inventory["files"] if row["path"] == str(parent / f"{parent.name}.{suffix}")]
            if len(matches) != 1:
                raise ValueError("Expected one inventoried baseline per format")
            # Baseline bytes are verified and retained locally for reproducible comparisons.
            baseline[suffix] = matches[0]
            sources[f"baseline-{ordinal:02d}.{suffix}"] = checked_bytes(root, matches[0])
        baselines.append(baseline)
    return tuple(documents), sources, {"inventory_sha256": digest(inventory_raw), "source_root": str(root),
        "content_records": records, "baselines": baselines, "expected_pages": list(EXPECTED_PAGES)}


def save_legacy_inputs(directory, documents, source_bytes, provenance):
    """The caller owns a new private staging directory."""
    directory = Path(directory)
    for name, raw in source_bytes.items():
        path = directory / name
        with path.open("xb") as handle:
            handle.write(raw)
        path.chmod(0o600)
    for document in documents:
        path = directory / f"{document.document_id}.spec.json"
        with path.open("xb") as handle:
            handle.write(canonical(document_dict(document)))
        path.chmod(0o600)
    provenance_path = directory / "source-manifest.local.json"
    with provenance_path.open("xb") as handle:
        handle.write(canonical(provenance))
    provenance_path.chmod(0o600)
