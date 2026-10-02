"""Prepare renamed CJK subsets from explicit font files and document characters."""
from pathlib import Path
import shutil

from fontTools import subset
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from .contracts import ExportError, FontSet, digest, plain_text, validate_document


FOOTER_TEXT = "历史未审核 草稿 已审核 快照 / 0123456789abcdef · 不支持的公式，图片回退 来源 公式图片：公式来源："
SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def document_characters(documents):
    text = FOOTER_TEXT
    for document in documents:
        validate_document(document)
        text += document.title
        for page in document.pages:
            for block in page:
                if block.kind in {"math"}:
                    continue  # Formula leaves use the separately verified math font.
                elif block.kind == "table":
                    text += "".join(plain_text(cell).translate(SUPERSCRIPT_DIGITS) for row in block.content[0] for cell in row)
                elif block.kind == "map":
                    text += "".join(block.content["root"])
                    text += "".join(value for group in block.content["groups"] for key in ("label", "detail") for value in group[key])
                elif block.kind == "formula_image":
                    text += block.content["alt"] + block.content["source_ref"]
                elif isinstance(block.content, str):
                    text += plain_text(block.content).translate(SUPERSCRIPT_DIGITS)
    return {ord(char) for char in text if not char.isspace()} | set(range(32, 127))


def _convert(source_path, target, characters, weight, face_index):
    source = TTFont(source_path, fontNumber=face_index, recalcTimestamp=False)
    try:
        if source["name"].getDebugName(1) != "Noto Sans CJK SC":
            raise ExportError("font_face_mismatch", "The selected CJK face must be Noto Sans CJK SC")
        missing = characters - set(source.getBestCmap())
        if missing:
            raise ExportError("missing_glyph", "CJK source font lacks codepoints: " + ",".join(f"U+{v:04X}" for v in sorted(missing)))
        options = subset.Options()
        options.layout_features = []
        options.recalc_timestamp = False
        selection = subset.Subsetter(options=options)
        selection.populate(unicodes=characters)
        selection.subset(source)
        order, glyphset = source.getGlyphOrder(), source.getGlyphSet()
        glyphs = {}
        for name in order:
            pen = TTGlyphPen(glyphset)
            glyphset[name].draw(Cu2QuPen(pen, max_err=1.0, reverse_direction=True))
            glyphs[name] = pen.glyph()
        builder = FontBuilder(source["head"].unitsPerEm, isTTF=True)
        builder.setupGlyphOrder(order)
        builder.setupCharacterMap(source.getBestCmap())
        builder.setupGlyf(glyphs)
        builder.setupHorizontalMetrics(source["hmtx"].metrics)
        builder.setupHorizontalHeader(ascent=source["hhea"].ascent, descent=source["hhea"].descent)
        builder.setupNameTable({"familyName": "Study Workbench Sans SC", "styleName": weight,
            "uniqueFontIdentifier": "StudyWorkbenchSansSC-" + weight,
            "fullName": "Study Workbench Sans SC " + weight, "psName": "StudyWorkbenchSansSC-" + weight})
        builder.setupOS2(sTypoAscender=source["OS/2"].sTypoAscender, sTypoDescender=source["OS/2"].sTypoDescender,
            usWinAscent=source["OS/2"].usWinAscent, usWinDescent=source["OS/2"].usWinDescent,
            usWeightClass=700 if weight == "Bold" else 400)
        builder.setupPost()
        builder.setupMaxp()
        builder.font.recalcTimestamp = False
        builder.font["head"].created = source["head"].created
        builder.font["head"].modified = source["head"].modified
        builder.save(target)
    finally:
        source.close()


def prepare_fonts(documents, output_dir, *, regular_source, bold_source, math_source,
                  cjk_notice, math_notice, face_index=2):
    """Only new private staging directories are accepted. No system font changes."""
    output = Path(output_dir)
    sources = {"regular": Path(regular_source), "bold": Path(bold_source), "math": Path(math_source)}
    notices = {"cjk": Path(cjk_notice), "math": Path(math_notice)}
    if any(not path.is_file() for path in (*sources.values(), *notices.values())):
        raise ExportError("missing_font", "Explicit source fonts and license notices are required")
    characters = document_characters(documents)
    output.mkdir(mode=0o700)
    try:
        for key, weight in (("regular", "Regular"), ("bold", "Bold")):
            _convert(sources[key], output / f"CJK-{weight}.ttf", characters, weight, face_index)
        shutil.copyfile(sources["math"], output / "Math.ttf")
        for key, path in notices.items():
            shutil.copyfile(path, output / f"{key}-LICENSE.txt")
        for path in output.iterdir():
            path.chmod(0o600)
        fonts = FontSet(output / "CJK-Regular.ttf", output / "CJK-Bold.ttf", output / "Math.ttf")
        manifest = {"word_family": fonts.word_family, "cjk_face_index": face_index,
            "characters": sorted(characters), "source_hashes": {key: digest(path.read_bytes()) for key, path in sources.items()},
            "files": {path.name: digest(path.read_bytes()) for path in output.iterdir()},
            "renamed_family": "Study Workbench Sans SC"}
        return fonts, manifest
    except BaseException:
        shutil.rmtree(output)
        raise
