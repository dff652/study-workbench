"""Translate validated revision display syntax to the closed print blocks."""
from html import escape

from app.domain.arithmetic import formula_ast
from app.domain.presentation import display_lines, EMPHASIS
from .contracts import Block


def body_blocks(text, markup=None, *, role="body", image_resolver=None):
    if markup is None:
        return [Block("p", escape(text or "").replace("\n", "<br/>"), role)]
    result = []
    for line in display_lines(markup):
        if line.kind == "math":
            result.append(Block("math", formula_ast(line.text), role))
        elif line.kind == "image":
            if image_resolver is None:
                raise ValueError("Source image resolver is required")
            result.append(Block("formula_image", image_resolver(line.sequence, line.text), role))
        else:
            parts = []
            start = 0
            for match in EMPHASIS.finditer(line.text):
                parts.append(escape(line.text[start:match.start()]))
                value = escape(match.group(2) or match.group(3))
                parts.append("<b>" + value + "</b>" if match.group(2) else
                             '<font backcolor="#FFF59D">' + value + '</font>')
                start = match.end()
            parts.append(escape(line.text[start:]))
            result.append(Block("p", "".join(parts), role))
    return result
