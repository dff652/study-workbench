"""Native PDF/Word snapshots with shared question pages and bounded previews."""
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

from django.conf import settings
from lxml import etree

from app.exports.contracts import ExportError, canonical, digest, document_dict
from app.exports.fonts import prepare_fonts
from app.exports.snapshots import export_document, private_directory, verify_snapshot, write_private
from app.printing.layout import paginate
from app.printing.services import _font_inputs
from app.web.services import asset_path
from . import bridge
from .vendor import model
from .vendor.common import assert_no_symlinks
from .vendor.contracts import document_dict as companion_document_dict


def _tool(name, *args, timeout=90):
    executable = shutil.which(name)
    if executable is None:
        raise ExportError("missing_renderer_tool", "A PDF preview tool is missing")
    try:
        return subprocess.run([executable, *map(str, args)], capture_output=True, check=True,
                              timeout=timeout, env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"})
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ExportError("preview_failed", "PDF preview or verification failed") from exc


def _verify_word(path, document):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() or len(archive.namelist()) != len(set(archive.namelist())):
            raise ExportError("invalid_word", "Word archive failed verification")
        root = etree.fromstring(archive.read("word/document.xml"), etree.XMLParser(resolve_entities=False, no_network=True))
        equations = root.xpath("//*[local-name()='oMath']")
        expected = sum(block.kind == "math" for page in document.pages for block in page)
        if len(equations) != expected:
            raise ExportError("invalid_word", "Editable equations are missing")
        external = [name for name in archive.namelist() if name.endswith(".rels") and b'TargetMode="External"' in archive.read(name)]
        if external:
            raise ExportError("invalid_word", "Word document contains external resources")


def _paginate_questions(content, fonts, root):
    for question in content["questions"]:
        native = bridge.native_document(model._question_document(content, question))
        pages = tuple(measured for page in native.pages for measured in paginate(list(page), fonts, root))
        value = json.loads(canonical(document_dict(replace(native, pages=pages))))
        # Return measured question pages to the fixed compiler. All three
        # organizations then reuse these exact bodies in the same order.
        for page in value["pages"]:
            for block in page:
                if block["kind"] == "companion_image":
                    block["kind"] = "diagram"
                    figure = block["content"]
                    figure["width_mm"] = figure.pop("width_points") * 25.4 / 72
                    figure["no_hint_confirmed"] = False
        question["pages"] = value["pages"]


def render(output, assets):
    root = Path(settings.SWB_DATA_ROOT).resolve()
    assert_no_symlinks(root)
    content = bridge.companion_content(output.revision, assets)
    manifest = output.revision.sources["manifest"]
    bridge.verify_assets(content, manifest, root)
    plans = model.compile_documents(content)
    documents = [bridge.native_document(plan["document"], content["lectures"]) for plan in plans]
    destination = root / "solutions" / "outputs" / output.pk.hex / f"version-{output.version}"
    assert_no_symlinks(destination)
    parent = private_directory(destination.parent)
    if destination.exists():
        raise ExportError("output_conflict", "A render claim cannot replace an existing output")
    stage = Path(tempfile.mkdtemp(prefix=".rendering-", dir=parent))
    try:
        fonts, font_manifest = prepare_fonts(documents, stage / "fonts", **_font_inputs())
        _paginate_questions(content, fonts, root)
        model.validate_content(content, manifest)
        plans = model.compile_documents(content)
        tool_version = _tool("pdftoppm", "-v").stderr.decode("utf-8", "replace").splitlines()[0]
        recipe = {"content_hash": output.revision.content_hash, "sources": output.revision.sources,
            "companion_source": bridge.verify_vendor(), "font_manifest": font_manifest, "preview_tool": tool_version,
            "adapter": {path.name: digest(path.read_bytes()) for path in sorted(Path(__file__).parent.glob("*.py"))}}
        write_private(stage / "companion-content.json", content)
        write_private(stage / "source-manifest.json", manifest)
        write_private(stage / "recipe.json", recipe)
        result_documents = []
        for plan in plans:
            document = bridge.native_document(plan["document"], content["lectures"])
            directory, generated = export_document(document, stage / "documents", fonts, font_manifest, asset_root=root)
            verify_snapshot(directory)
            _verify_word(directory / "document.docx", document)
            info = _tool("pdfinfo", directory / "document.pdf").stdout.decode("utf-8", "replace")
            count = re.search(r"^Pages:\s+(\d+)$", info, re.MULTILINE)
            if count is None or int(count[1]) != len(document.pages):
                raise ExportError("invalid_pdf", "PDF page count differs from selected content")
            preview_dir = private_directory(stage / "previews" / document.document_id)
            _tool("pdftoppm", "-scale-to", "1400", "-png", directory / "document.pdf", preview_dir / "page")
            previews = sorted(preview_dir.glob("page-*.png"))
            if len(previews) != len(document.pages):
                raise ExportError("invalid_preview", "Some PDF pages have no preview")
            files = {"document.pdf": directory / "document.pdf", "document.docx": directory / "document.docx"}
            files.update({f"page-{index}.png": path for index, path in enumerate(previews, 1)})
            organization = "per_question" if document.document_id.startswith("question-") else "per_lecture" if document.document_id.startswith("lecture-") else "combined"
            result_documents.append({"id": document.document_id, "title": document.title,
                "organization": organization, "question_ids": plan["question_ids"], "formats": plan["formats"],
                "page_count": len(document.pages), "page_questions": plan["page_questions"],
                "previews": [f"page-{index}.png" for index in range(1, len(previews) + 1)],
                "files": {name: {"key": str(destination.relative_to(root) / path.relative_to(stage)),
                    "sha256": digest(path.read_bytes()), "size": path.stat().st_size} for name, path in files.items()},
                "snapshot_id": generated["snapshot_id"], "export_id": generated["export_id"]})
        for path in stage.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        size = sum(path.stat().st_size for path in stage.rglob("*") if path.is_file())
        if size > 512 * 1024 * 1024:
            raise ExportError("solution_output_large", "Generated output exceeds the bounded size")
        result = {"recipe_sha256": digest(canonical(recipe)), "content_hash": output.revision.content_hash,
            "documents": result_documents, "machine_verified": True, "zip": True,
            "source_revision": output.revision_id, "checks": {name: {"status": "not_tested", "notes": ""}
                for name in ("content", "math", "pdf_visual", "word_pc", "word_macos")}}
        write_private(stage / "output-manifest.json", result)
        # Cancellation and source changes are checked by the claiming service
        # before this immutable version can become a visible successful result.
        stage.rename(destination)
        return result
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def output_file(output, document_id, name):
    if output.state not in {"output_check", "complete"}:
        raise ExportError("output_unavailable", "Output has not completed")
    document = next((item for item in output.result.get("documents", []) if item["id"] == document_id), None)
    if document is None or name not in document["files"]:
        raise ExportError("output_unavailable", "No selected output file")
    if name in {"document.pdf", "document.docx"} and name.split(".")[-1] not in document["formats"]:
        raise ExportError("output_unavailable", "This output format was not selected")
    record = document["files"][name]
    assert_no_symlinks(Path(settings.SWB_DATA_ROOT) / record["key"])
    return asset_path(record["key"], record["sha256"])


def archive(output):
    checks = output.result.get("checks", {})
    if any(check["status"] == "fail" for check in checks.values()):
        raise ExportError("review_failed", "A failed review blocks delivery")
    buffer, total = BytesIO(), 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as result:
        for document in output.result.get("documents", []):
            for format_name in document["formats"]:
                path = output_file(output, document["id"], "document." + format_name)
                total += path.stat().st_size
                if total > 128 * 1024 * 1024:
                    raise ExportError("solution_output_large", "Selected ZIP exceeds its size limit")
                info = zipfile.ZipInfo(document["id"] + "." + format_name, (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                result.writestr(info, path.read_bytes())
        result.writestr("checks.json", canonical({"content_hash": output.result["content_hash"],
            "recipe_sha256": output.result["recipe_sha256"], "output_version": output.version,
            "machine_verified": True, "checks": checks}))
        result.writestr("README.txt", "逐题解析 · 家长答案\n不同组织方式重复使用同一题目正文。\n机器检查不代表内容、数学、PDF版式或 Word 客户端已核对。具体范围见 checks.json。\n原始照片不包含在此压缩包中。\n")
    buffer.seek(0)
    return buffer
