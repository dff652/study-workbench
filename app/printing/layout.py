"""Measured pagination for dynamic plain-text business exports."""
from html import escape, unescape
import re

from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph

from app.exports.contracts import Block, ExportError, resolve_formula_image, resolve_diagram
from app.exports.renderer import (
    _MathLine, _formula_image_flowables, _paragraph_styles, _register_fonts,
)
from app.exports.rich import pdf_markup


def paginate(blocks, fonts, asset_root):
    registered, _ = _register_fonts(fonts)
    styles = _paragraph_styles(registered)
    width = A4[0] - 106
    capacity = A4[1] - 105

    def height(block):
        if block.kind == 'space':
            return float(block.content)
        if block.kind == 'math':
            flowables = [_MathLine(block.content, registered['math'])]
        elif block.kind in {'formula_image','diagram'}:
            path = (resolve_diagram if block.kind=='diagram' else resolve_formula_image)(block.content, asset_root)
            flowables = _formula_image_flowables(block.content, path, styles,diagram=block.kind=='diagram')
        else:
            flowables = [Paragraph(pdf_markup(block.content), styles[block.kind])]
        return sum(f.wrap(width, capacity)[1] + f.getSpaceBefore() + f.getSpaceAfter()
                   for f in flowables)

    queue = list(blocks)
    pages, page, used = [], [], 0
    while queue:
        block = queue.pop(0)
        # Keep a short question with its figure and writing space. Measuring
        # each block alone can strand the next question's text at a page foot.
        if block.role == 'question' and page:
            group = [block]
            for following in queue:
                if following.role == 'question':
                    group.append(following)
                else:
                    if following.kind == 'space':
                        group.append(following)
                    break
            group_height = sum(height(item) for item in group)
            if group_height <= capacity and used + group_height > capacity:
                pages.append(tuple(page))
                page, used = [], 0
        required = height(block)
        if required > capacity:
            if block.kind not in {'p', 'small'}:
                raise ExportError('layout_overflow', 'A block exceeds one printable page')
            # These business blocks contain escaped plain text and line breaks.
            # Split at a measured character boundary, preserving every character.
            text = unescape(re.sub(r'<br\s*/?>', '\n', block.content))
            lower, upper = 1, len(text)
            available = capacity - used
            while lower < upper:
                midpoint = (lower + upper + 1) // 2
                candidate = Block(block.kind, escape(text[:midpoint]).replace('\n', '<br/>'), block.role)
                if height(candidate) <= available:
                    lower = midpoint
                else:
                    upper = midpoint - 1
            first = Block(block.kind, escape(text[:lower]).replace('\n', '<br/>'), block.role)
            if height(first) > available:
                if page:
                    pages.append(tuple(page)); page, used = [], 0
                    queue.insert(0, block)
                    continue
                raise ExportError('layout_overflow', 'Text cannot fit the printable width')
            queue.insert(0, Block(block.kind, escape(text[lower:]).replace('\n', '<br/>'), block.role))
            block, required = first, height(first)
        # Keep a section heading with its following block when they fit together.
        following = height(queue[0]) if block.kind == 'h' and queue else 0
        keep_height = required + (min(following, 60) if following > capacity else following)
        if page and used + keep_height > capacity:
            pages.append(tuple(page)); page, used = [], 0
        page.append(block)
        used += required
    if page:
        pages.append(tuple(page))
    if len(pages) > 100:
        raise ExportError('layout_overflow', 'Export exceeds 100 printable pages')
    return tuple(pages)
