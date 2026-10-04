"""Build identity is explicit; a running development tree is not a release."""
import os
import re

VERSION = "0.2.0-dev"
CHANGELOG = [{"version": VERSION, "date": "2026-10-05", "changes": [
    "知识题库、学习档案、文档和设置均可在同一工作台内操作。",
    "多张原图按队列上传，失败项可单独重试。",
    "逐题解析支持原图来源、层级小问、方法关联、草稿保存和历史对照。",
    "解析可生成逐题、分讲和合集 PDF／Word，并逐页预览和分别记录检查结果。",
]}, {"version": VERSION, "date": "2026-10-04", "changes": [
    "新增同源工作台、学习证据总览及历次作答记录。",
    "资料整理、来源核对与五册交付进入同一任务流程。",
    "工具草稿保留原始输入、来源映射和确认历史。",
    "同页原图核对、资料与知识关联进度、复测计划接入工作台。",
    "可选内容准备保留阶段历史，人工确认后保存正式内容。",
]}]


def identity():
    revision = os.environ.get("SWB_SOURCE_REVISION", "unknown")
    if not re.fullmatch(r"[0-9a-f]{7,40}", revision):
        revision = "unknown"
    return {"version": VERSION, "release_state": "development",
            "source_revision": revision, "build_date": os.environ.get("SWB_BUILD_DATE") or None,
            "changelog": CHANGELOG, "help_url": "/help/"}
