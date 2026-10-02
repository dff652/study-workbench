"""Strict shared rich-text parsing for PDF paragraphs and Word runs."""
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
import re

from .contracts import ExportError


_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


@dataclass(frozen=True, slots=True)
class RichRun:
    text: str
    bold: bool = False
    superscript: bool = False
    color: str | None = None
    backcolor: str | None = None


@dataclass(frozen=True, slots=True)
class RichBreak:
    pass


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.frames = [("", {})]
        self.events = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            if attrs:
                raise ExportError("unsupported_markup", "Line breaks cannot have attributes")
            self.events.append(RichBreak())
            return
        allowed = {"b": set(), "super": set(), "font": {"color", "backcolor"}}
        if tag not in allowed or any(name not in allowed[tag] for name, _ in attrs):
            raise ExportError("unsupported_markup", "Only b, br, super and font colors are supported")
        if len({name for name, _ in attrs}) != len(attrs):
            raise ExportError("unsupported_markup", "Duplicate markup attribute")

        state = self.frames[-1][1].copy()
        values = dict(attrs)
        for name, value in attrs:
            if not isinstance(value, str) or re.fullmatch(r"#[0-9A-Fa-f]{6}", value) is None:
                raise ExportError("unsupported_markup", "Colors require six hexadecimal digits")
        if tag == "b":
            state["bold"] = True
        elif tag == "super":
            state["superscript"] = True
        else:
            if "color" in values:
                state["color"] = values["color"]
            if "backcolor" in values:
                state["backcolor"] = values["backcolor"]
        self.frames.append((tag, state))

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.handle_starttag(tag, attrs)
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if len(self.frames) == 1 or self.frames[-1][0] != tag:
            raise ExportError("unsupported_markup", "Markup tags must be balanced and nested")
        self.frames.pop()

    def handle_data(self, value):
        if not value:
            return
        state = self.frames[-1][1]
        run = RichRun(
            value,
            state.get("bold", False),
            state.get("superscript", False),
            state.get("color"),
            state.get("backcolor"),
        )
        if self.events and isinstance(self.events[-1], RichRun) and _same_style(self.events[-1], run):
            previous = self.events[-1]
            self.events[-1] = RichRun(previous.text + run.text, run.bold, run.superscript, run.color, run.backcolor)
        else:
            self.events.append(run)

    def handle_comment(self, value):
        raise ExportError("unsupported_markup", "Markup comments are unsupported")

    def handle_decl(self, value):
        raise ExportError("unsupported_markup", "Markup declarations are unsupported")

    def handle_pi(self, data):
        raise ExportError("unsupported_markup", "Processing instructions are unsupported")

    def unknown_decl(self, data):
        raise ExportError("unsupported_markup", "Unknown markup declarations are unsupported")


def _same_style(first, second):
    return (first.bold, first.superscript, first.color, first.backcolor) == (
        second.bold, second.superscript, second.color, second.backcolor
    )


def parse_rich(value):
    parser = _Parser()
    parser.feed(re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+", lambda match: "<super>" + match.group().translate(_SUPERSCRIPT_DIGITS) + "</super>", value))
    parser.close()
    if len(parser.frames) != 1:
        raise ExportError("unsupported_markup", "Unclosed markup tag")
    return tuple(parser.events)


def pdf_markup(value):
    parts = []
    for event in parse_rich(value):
        if isinstance(event, RichBreak):
            parts.append("<br/>")
            continue
        content = escape(event.text, quote=False)
        wrappers = []
        if event.color or event.backcolor:
            attrs = []
            if event.color:
                attrs.append(f'color="{event.color}"')
            if event.backcolor:
                attrs.append(f'backColor="{event.backcolor}"')
            wrappers.append(("font", " ".join(attrs)))
        if event.bold:
            wrappers.append(("b", ""))
        if event.superscript:
            wrappers.append(("super", ""))
        for tag, attrs in wrappers:
            parts.append(f"<{tag}{(' ' + attrs) if attrs else ''}>")
        parts.append(content)
        for tag, _ in reversed(wrappers):
            parts.append(f"</{tag}>")
    return "".join(parts)


def visible_runs(value):
    """Return visible rich-text runs for deterministic font coverage checks."""
    return tuple(event for event in parse_rich(value) if isinstance(event, RichRun))
