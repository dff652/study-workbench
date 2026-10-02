"""Formula geometry and editable Word math for the bounded print format."""
from reportlab.pdfbase import pdfmetrics
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .contracts import ExportError, validate_math


def formula_strings(node):
    validate_math(node)
    if node[0] == "t":
        yield node[1]
    else:
        for child in node[1:]:
            yield from formula_strings(child)


def metric(node, font_name, font_size):
    kind = node[0]
    if kind == "t":
        return pdfmetrics.stringWidth(node[1], font_name, font_size), 0.8 * font_size, 0.23 * font_size
    if kind == "r":
        dimensions = [metric(child, font_name, font_size) for child in node[1:]]
        return (
            sum(value[0] for value in dimensions),
            max(value[1] for value in dimensions),
            max(value[2] for value in dimensions),
        )
    if kind == "f":
        numerator = metric(node[1], font_name, font_size * 0.86)
        denominator = metric(node[2], font_name, font_size * 0.86)
        return (
            max(numerator[0], denominator[0]) + 0.5 * font_size,
            0.2 * font_size + 0.19 * font_size + numerator[2] + numerator[1],
            -0.2 * font_size + 0.19 * font_size + denominator[1] + denominator[2],
        )
    base = metric(node[1], font_name, font_size)
    index = metric(node[2], font_name, font_size * 0.65)
    if kind == "u":
        return base[0] + index[0], max(base[1], 0.60 * font_size + index[1]), base[2]
    return base[0] + index[0], base[1], max(base[2], 0.32 * font_size + index[2])


def paint(canvas, node, x, y, font_size, font_name):
    kind = node[0]
    if kind == "t":
        canvas.setFont(font_name, font_size)
        canvas.drawString(x, y, node[1])
        return
    if kind == "r":
        for child in node[1:]:
            paint(canvas, child, x, y, font_size, font_name)
            x += metric(child, font_name, font_size)[0]
        return
    if kind == "f":
        width, _, _ = metric(node, font_name, font_size)
        numerator = metric(node[1], font_name, font_size * 0.86)
        denominator = metric(node[2], font_name, font_size * 0.86)
        paint(node=node[1], canvas=canvas, x=x + (width - numerator[0]) / 2,
              y=y + 0.39 * font_size + numerator[2], font_size=font_size * 0.86,
              font_name=font_name)
        paint(node=node[2], canvas=canvas, x=x + (width - denominator[0]) / 2,
              y=y + 0.01 * font_size - denominator[1], font_size=font_size * 0.86,
              font_name=font_name)
        canvas.setLineWidth(0.65)
        canvas.line(x + 0.1 * font_size, y + 0.2 * font_size,
                    x + width - 0.1 * font_size, y + 0.2 * font_size)
        return
    base_width = metric(node[1], font_name, font_size)[0]
    offset = 0.60 * font_size if kind == "u" else -0.32 * font_size
    paint(canvas, node[1], x, y, font_size, font_name)
    paint(canvas, node[2], x + base_width, y + offset, font_size * 0.65, font_name)


def omath(node):
    """Convert only the supported formula nodes into editable OMML."""
    validate_math(node)
    kind = node[0]
    if kind == "t":
        run = OxmlElement("m:r")
        text = OxmlElement("m:t")
        text.text = node[1]
        text.set(qn("xml:space"), "preserve")
        run.append(text)
        return [run]
    if kind == "r":
        return [element for child in node[1:] for element in omath(child)]
    if kind == "f":
        tag, slots = "f", ("num", "den")
    elif kind == "u":
        tag, slots = "sSup", ("e", "sup")
    elif kind == "d":
        tag, slots = "sSub", ("e", "sub")
    else:
        raise ExportError("unsupported_formula", "Use a source-labelled formula_image for unsupported notation")

    root = OxmlElement(f"m:{tag}")
    for slot, child in zip(slots, node[1:]):
        part = OxmlElement(f"m:{slot}")
        for element in omath(child):
            part.append(element)
        root.append(part)
    return [root]
