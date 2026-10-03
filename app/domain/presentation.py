"""Optional, versioned display syntax; it cannot change the underlying text.

Math and source images occupy a whole line. Image numbers refer only to the
evidence sequence pinned in the same revision. No HTML, URL or path is parsed.
"""
from dataclasses import dataclass
import re

from .arithmetic import formula_ast


@dataclass(frozen=True, slots=True)
class DisplayLine:
    kind: str
    text: str
    sequence: int | None = None


EMPHASIS = re.compile(r"(\*\*([^*\n]+)\*\*|==([^=\n]+)==)")
MATH = re.compile(r"\[\[math:(.+)\]\]\Z")
IMAGE = re.compile(r"\[\[image:([1-9][0-9]*)\|(.+)\]\]\Z")


def display_lines(markup):
    if not isinstance(markup, str) or not 0 < len(markup) <= 24000:
        raise ValueError("排版文本必须为 1～24000 字。")
    result = []
    for line in markup.strip().splitlines():
        math = MATH.fullmatch(line)
        image = IMAGE.fullmatch(line)
        if math:
            expression = math.group(1)
            formula_ast(expression)  # Bounded parser, never eval.
            result.append(DisplayLine("math", expression))
        elif image:
            if len(image.group(2)) > 2000:
                raise ValueError("图片替代文字不能超过 2000 字。")
            result.append(DisplayLine("image", image.group(2), int(image.group(1))))
        else:
            remainder = EMPHASIS.sub(lambda match: match.group(2) or match.group(3), line)
            if "[[" in remainder or "**" in remainder or "==" in remainder:
                raise ValueError("公式或图片标记须单独一行；重点标记须成对且不能嵌套。")
            result.append(DisplayLine("text", line))
    return tuple(result)


def validate_display(markup, text, refs):
    if markup is None:
        return
    lines = display_lines(markup)
    plain = "\n".join(EMPHASIS.sub(lambda m: m.group(2) or m.group(3), line.text)
                      if line.kind == "text" else line.text for line in lines)
    # Browser textareas submit CRLF; treat line endings equally while retaining
    # the exact original text in its immutable revision and hash.
    normalized_text=text.replace('\r\n','\n').replace('\r','\n') if isinstance(text,str) else None
    if normalized_text is None or plain.strip() != normalized_text.strip():
        raise ValueError("排版去除标记后的正文必须与当前正文一致；修改原文应另存修订。")
    sequences = {ref.sequence for ref in refs if ref.region_revision_id and not ref.region_missing}
    if any(line.kind == "image" and line.sequence not in sequences for line in lines):
        raise ValueError("图片回退必须引用本版本已有且有坐标的来源区域序号。")
