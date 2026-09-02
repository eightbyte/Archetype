"""Markdown export: the closed schema in, Markdown out (P2-13, D15).

**Total by construction.** Every node in
:data:`~archetype.manuscript.markdown.schema.ALLOWED_NODES` and every mark in ``ALLOWED_MARKS``
has a case here, and :data:`HANDLED_NODES` names them so a test can compare the two sets. A node
this module has not been taught raises :class:`UnknownNodeError` rather than being guessed at:
inventing syntax for one would put text into a file that could never be read back, which is the
same failure Markdown import exists to make impossible.

The syntax
----------

======================  =========================================================
``heading``             ``#``, ``##``, ``###`` - the level, clamped to 1-6
``paragraph``           the text, one line
``hardBreak``           a backslash at the end of a line
``blockquote``          ``>`` on every line
``bulletList``          ``-``, continuation lines indented two spaces
``orderedList``         ``1.``, numbered up from the list's ``start``
``horizontalRule``      ``* * *`` - the same :data:`SCENE_BREAK` the projection
                        uses, so a scene break reads the same everywhere
``bold``                ``**``
``italic``              ``*``
======================  =========================================================

Blocks are separated by exactly one blank line, which is what the projection does too.

One chapter or many
-------------------

:func:`document_to_markdown` writes one chapter's body and nothing else - it is the round-trip
artifact, and the levels in it are the levels the writer chose.
:func:`chapters_to_markdown` writes the whole manuscript, each chapter's title as an H1 and
**every heading in its body one level down**, because level 1 belongs to the titles there. It is
a reading artifact with no round trip promised, and the demotion is what lets an import of it
split into the chapters it was made from rather than at every heading the writer typed (D15).

Escaping
--------

The fiddly part, and the reason this file is longer than its output. Two layers, applied in
order:

**Inline.** ``\\``, `````, ``*``, ``_``, ``[`` and ``]`` are escaped wherever they occur, so a
paragraph the writer typed as ``* * *`` comes back as ``\\* \\* \\*`` and stays three asterisks
rather than becoming the scene break the serializer spells the same way. ``&`` is escaped only
when it begins something a parser would read as a character reference, and ``<`` only when the
next character could open a tag or an autolink - escaping either unconditionally would litter
ordinary prose for a case that is not there.

**Line start.** Every line of every block, because a Markdown block construct can interrupt a
paragraph from any of its lines, not just the first. A leading ``#``, ``>``, ``-``, ``+``, a
digit run followed by ``.`` or ``)``, a line of ``=``, or a run of ``~`` gets one backslash. The
``*`` forms need no rule here: they are already escaped inline, which is why an emphasis
delimiter at the start of a line - ``**Marlow** said`` - is left alone and still reads as bold.

What Markdown cannot hold
-------------------------

Three normalisations, each a place where Markdown has no representation for something the
schema can express. Each is asserted directly in ``tests/test_markdown.py`` so it is a stated
rule rather than a discovered surprise, and none of them is reachable by ordinary typing:

* **An empty paragraph between two blocks is dropped.** A blank line is how Markdown separates
  blocks, so a block made of one cannot survive. This is the projection's rule as well - see
  :func:`~archetype.manuscript.projection.tidy_block` - and it is why an exported chapter
  stripped of its syntax reads as its own ``text_plain``.
* **A line break inside a heading becomes a space.** An ATX heading is one line by definition.
* **A newline inside a text node is a line break**, exactly as the projection reads it, so it
  comes back as a ``hardBreak``. The editor cannot produce one; a hand-written payload can.
* **Whitespace at the edge of an emphasis run moves outside it.** ``** bold **`` is not emphasis
  in CommonMark, so a bold run the writer selected with a trailing space is written as
  ``**bold** `` instead. Not a character of text changes - only which of them the mark covers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..projection import SCENE_BREAK, tidy_block
from .schema import ALLOWED_MARKS, UnknownNodeError

__all__ = [
    "BULLET",
    "HANDLED_NODES",
    "HARD_BREAK",
    "UnknownMarkError",
    "chapters_to_markdown",
    "document_to_markdown",
]

#: The bullet this serializer writes. ``-`` rather than ``*``, so a bullet list and a scene
#: break never begin with the same character.
BULLET = "-"

#: How a ``hardBreak`` is written: a backslash at the end of the line it ends.
HARD_BREAK = "\\"

#: The emphasis delimiter per mark. Ordered as ``ALLOWED_MARKS`` is, which is the order
#: ProseMirror normalises a text node's marks into, so nesting is deterministic.
EMPHASIS: dict[str, str] = {"bold": "**", "italic": "*"}

#: Blocks this module writes, inline nodes it writes, and the two structural nodes that are
#: neither (``doc`` is the root :func:`document_to_markdown` is handed, ``listItem`` is written
#: by the list that contains it). Their union is exactly ``ALLOWED_NODES`` - asserted by a test,
#: which is what makes "every node has a case" a fact rather than an intention.
BLOCK_NODES: frozenset[str] = frozenset(
    {"paragraph", "heading", "horizontalRule", "blockquote", "bulletList", "orderedList"}
)
INLINE_NODES: frozenset[str] = frozenset({"text", "hardBreak"})
STRUCTURAL_NODES: frozenset[str] = frozenset({"doc", "listItem"})
HANDLED_NODES: frozenset[str] = BLOCK_NODES | INLINE_NODES | STRUCTURAL_NODES

_MIN_HEADING_LEVEL = 1
_MAX_WRITABLE_HEADING_LEVEL = 6

#: How far every heading in a chapter's body is pushed down in the **combined** export, where the
#: chapter titles occupy level 1. See :func:`chapters_to_markdown` for why (P2-13, D15).
_CHAPTER_BODY_OFFSET = 1

# One pass, so a backslash inserted here is never escaped again by a later character in the set.
_INLINE_ESCAPES = str.maketrans({character: "\\" + character for character in "\\`*_[]"})

# A character reference a parser would decode. `&amp;` must come back as `&amp;`, not as `&`.
_ENTITY = re.compile(r"&(?:#[0-9]{1,8}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{0,31});")

# `<` only matters where it could open a tag or an autolink. `a < b` is left as it was typed.
_TAG_LIKE = re.compile(r"<(?=[A-Za-z!/?])")

# A block construct at the start of a line. `*` is absent deliberately - it is escaped inline,
# so the only `*` that can reach the start of a line is an emphasis delimiter this module wrote.
_LINE_START = re.compile(
    r"""^(?:
          \#{1,6}(?=[ \t]|$)          # an ATX heading
        | >                           # a blockquote
        | [-+]                        # a bullet, a thematic break, a setext underline
        | [0-9]{1,9}(?P<ordinal>[.)])(?=[ \t]|$)   # an ordered list item
        | =+$                         # a setext heading underline
        | ~{3,}                       # a tilde code fence
      )""",
    re.VERBOSE,
)

# A closing sequence of an ATX heading: `## Chapter ##` is a heading reading "Chapter".
_HEADING_TAIL = re.compile(r"#+$")


class UnknownMarkError(ValueError):
    """A mark outside ``ALLOWED_MARKS`` reached the serializer.

    The sibling of :class:`UnknownNodeError`, and refused for the same reason.
    """

    def __init__(self, mark: object) -> None:
        super().__init__(
            f"{mark!r} is not in the manuscript schema; expected one of {', '.join(ALLOWED_MARKS)}"
        )
        self.mark = mark


def document_to_markdown(document: Mapping[str, Any]) -> str:
    """One chapter's content as Markdown, with no trailing newline.

    The chapter's **title is not written**. This is the round-trip artifact - P2-14 promises
    ``import(export(doc)) == doc`` - and a title written into the body would come back as a
    heading the writer never typed. The title travels in the download's filename, and in the
    combined export it is written by :func:`chapters_to_markdown`, which promises no round trip.

    Raises:
        UnknownNodeError: The document holds a node type outside the closed schema.
        UnknownMarkError: A text node carries a mark outside the closed schema.
    """
    return "\n".join(_group_lines(_children(document)))


def chapters_to_markdown(chapters: Iterable[tuple[str, Mapping[str, Any]]]) -> str:
    """Every chapter in order, each preceded by its title as an H1 (P2-13, D15).

    A reading and hand-off artifact, **not** a round-trip format (phase-2 plan section 2, ruling
    4): the chapter boundaries are H1s, and the schema has no node that means "chapter", so
    reading them back would mean inventing a container syntax and parsing it - a private format
    wearing Markdown's clothes. Import splits on H1 because that is a useful thing to do with a
    file shaped like this one, not because this is a format with a promise attached.

    **Every heading in a chapter's body is written one level down** - H1 as ``##``, H2 as
    ``###``, H3 as ``####`` - because level 1 belongs to the chapter titles here (deviation D15,
    found by the section 8 acceptance run on 2026-09-01). Without it a manuscript that uses an
    H1 inside a chapter - which the closed schema permits, and a writer will do - exports a file
    whose chapter boundaries and body headings are the same character, and re-importing it with
    ``split-on-h1`` cuts the chapter in two at a heading that was never a chapter break. The
    demotion is also the honest structure: in one combined document the chapter titles *are* the
    top level and everything inside one is subordinate to it.

    The cost is at the floor. The editor offers three levels, so a body H3 is written as ``####``
    and comes back from an import at level 3 with a notice saying so - a loss that announces
    itself, in the file that never promised a round trip. :func:`document_to_markdown`, which
    does promise one, is untouched.
    """
    parts: list[str] = []
    for title, content in chapters:
        heading = _heading_line(_MIN_HEADING_LEVEL, _inline_text_of(title))
        body = "\n".join(_group_lines(_children(content), level_offset=_CHAPTER_BODY_OFFSET))
        parts.append(f"{heading}\n\n{body}" if body else heading)
    return "\n\n".join(parts)


# -- blocks ---------------------------------------------------------------------------------


def _group_lines(nodes: Iterable[Mapping[str, Any]], *, level_offset: int = 0) -> list[str]:
    """A run of sibling blocks, separated by exactly one blank line.

    A block that writes nothing - an empty paragraph - takes no blank line with it, so two
    paragraphs with an empty one between them come out adjacent. That is the projection's rule
    (``tidy_block``) applied one level up, and it is the one thing export does not preserve.

    ``level_offset`` pushes every heading below here down that many levels, and travels into
    blockquotes and list items with the walk: a heading is subordinate to the chapter title
    wherever in the chapter it sits. It is zero everywhere but the combined export.
    """
    lines: list[str] = []
    for child in nodes:
        block = _block_lines(child, level_offset=level_offset)
        if not block:
            continue
        if lines:
            lines.append("")
        lines.extend(block)
    return lines


def _block_lines(node: Mapping[str, Any], *, level_offset: int = 0) -> list[str]:
    """One block, as the lines it occupies. Empty when the block writes nothing."""
    node_type = node.get("type")

    if node_type == "paragraph":
        return _text_block_lines(node)
    if node_type == "heading":
        return _heading_block_lines(node, level_offset=level_offset)
    if node_type == "horizontalRule":
        return [SCENE_BREAK]
    if node_type == "blockquote":
        # `>` on a line of its own when the quote is empty, rather than nothing: an empty
        # blockquote is a node the schema can hold, and dropping it would lose it silently.
        body = _group_lines(_children(node), level_offset=level_offset) or [""]
        return _prefixed(body, marker="> ", indent="> ")
    if node_type == "bulletList":
        return _list_lines(node, ordered=False, level_offset=level_offset)
    if node_type == "orderedList":
        return _list_lines(node, ordered=True, level_offset=level_offset)

    if node_type in INLINE_NODES or node_type in STRUCTURAL_NODES:
        raise UnknownNodeError(f"{node_type} (not a block)")
    raise UnknownNodeError(str(node_type))


def _text_block_lines(node: Mapping[str, Any]) -> list[str]:
    """A paragraph: its lines, each escaped, every one but the last ending in a backslash."""
    text = tidy_block(_inline_text(_children(node)))
    if not text:
        return []
    lines = [_escape_line_start(line) for line in text.split("\n")]
    return [line + HARD_BREAK for line in lines[:-1]] + lines[-1:]


def _heading_block_lines(node: Mapping[str, Any], *, level_offset: int = 0) -> list[str]:
    """A heading: one line, always. An internal line break becomes a space."""
    attrs = node.get("attrs")
    raw_level = attrs.get("level") if isinstance(attrs, Mapping) else None
    level = (
        raw_level
        if isinstance(raw_level, int) and not isinstance(raw_level, bool)
        else _MIN_HEADING_LEVEL
    )
    text = tidy_block(_inline_text(_children(node)))
    return [_heading_line(level + level_offset, " ".join(text.split("\n")))]


def _heading_line(level: int, text: str) -> str:
    """``### text``, with the closing-sequence trap escaped and an empty heading still a heading."""
    level = max(_MIN_HEADING_LEVEL, min(_MAX_WRITABLE_HEADING_LEVEL, level))
    hashes = "#" * level
    if not text:
        return hashes
    tail = _HEADING_TAIL.search(text)
    if tail is not None and (tail.start() == 0 or text[tail.start() - 1].isspace()):
        text = f"{text[: tail.start()]}\\{text[tail.start() :]}"
    return f"{hashes} {text}"


def _list_lines(node: Mapping[str, Any], *, ordered: bool, level_offset: int = 0) -> list[str]:
    """A list: one marker per item, continuation lines indented to the marker's width.

    Items are written tight - no blank line between them - and an item holding more than one
    block gets blank lines inside it, which makes the list loose. The distinction is invisible
    here: a list item always holds a paragraph in this schema, so tight and loose parse back to
    the same nodes and only the rendered spacing differs.
    """
    number = _start_of(node) if ordered else 0
    lines: list[str] = []
    for item in _children(node):
        if item.get("type") != "listItem":
            raise UnknownNodeError(f"{item.get('type')} (not a list item)")
        marker = f"{number}. " if ordered else f"{BULLET} "
        body = _group_lines(_children(item), level_offset=level_offset) or [""]
        lines.extend(_prefixed(body, marker=marker, indent=" " * len(marker)))
        number += 1
    return lines


def _start_of(node: Mapping[str, Any]) -> int:
    """An ordered list's first number. Only the first is read back, so only it has to be right."""
    attrs = node.get("attrs")
    start = attrs.get("start") if isinstance(attrs, Mapping) else None
    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        return 1
    return start


def _prefixed(lines: Sequence[str], *, marker: str, indent: str) -> list[str]:
    """Put ``marker`` on the first line and ``indent`` on the rest, leaving no trailing space."""
    out: list[str] = []
    for index, line in enumerate(lines):
        prefix = marker if index == 0 else indent
        out.append(f"{prefix}{line}" if line else prefix.rstrip())
    return out


# -- inline ---------------------------------------------------------------------------------


def _inline_text(children: Iterable[Mapping[str, Any]]) -> str:
    """A block's inline content as one string, escaped, with ``\\n`` where the lines break.

    Adjacent text nodes carrying the same marks are written as one emphasis run, so a sentence
    the editor happens to hold as three bold text nodes does not come out as ``**a****b****c**``.
    """
    nodes = [child for child in children]
    parts: list[str] = []
    index = 0
    while index < len(nodes):
        child = nodes[index]
        node_type = child.get("type")
        if node_type == "hardBreak":
            parts.append("\n")
            index += 1
            continue
        if node_type != "text":
            raise UnknownNodeError(f"{node_type} (not inline)")

        marks = _marks_of(child)
        run: list[str] = []
        while (
            index < len(nodes)
            and nodes[index].get("type") == "text"
            and _marks_of(nodes[index]) == marks
        ):
            value = nodes[index].get("text")
            run.append(value if isinstance(value, str) else "")
            index += 1
        parts.append(_emphasise("".join(run), marks))
    return "".join(parts)


def _inline_text_of(text: str) -> str:
    """A bare string - a chapter title - escaped as if it were an unmarked text node."""
    return _escape_text(text)


def _marks_of(node: Mapping[str, Any]) -> tuple[str, ...]:
    """A text node's marks, in ``ALLOWED_MARKS`` order.

    ProseMirror normalises a node's marks into schema order, and ``ALLOWED_MARKS`` is that
    order, so two runs that carry the same marks compare equal however the JSON listed them.
    """
    marks = node.get("marks")
    if not marks:
        return ()
    names: set[str] = set()
    for mark in marks:
        name = mark.get("type") if isinstance(mark, Mapping) else None
        if not isinstance(name, str) or name not in ALLOWED_MARKS:
            raise UnknownMarkError(name)
        names.add(name)
    return tuple(mark for mark in ALLOWED_MARKS if mark in names)


def _emphasise(text: str, marks: Sequence[str]) -> str:
    """Wrap escaped text in its emphasis delimiters.

    Leading and trailing whitespace is moved **outside** the delimiters: ``* text *`` is not
    emphasis in CommonMark, so a bold run the writer selected with a trailing space would
    otherwise export as literal asterisks.
    """
    if not marks:
        return _escape_text(text)
    body = text.strip()
    if not body:
        return _escape_text(text)

    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    wrapped = _escape_text(body)
    for mark in reversed(marks):
        delimiter = EMPHASIS[mark]
        wrapped = f"{delimiter}{wrapped}{delimiter}"
    return f"{lead}{wrapped}{trail}"


def _escape_text(text: str) -> str:
    """Escape the characters that would otherwise be read as syntax. See the module docstring."""
    escaped = text.translate(_INLINE_ESCAPES)
    escaped = _ENTITY.sub(lambda match: "\\" + match.group(0), escaped)
    return _TAG_LIKE.sub("\\\\<", escaped)


def _escape_line_start(line: str) -> str:
    """Escape a block construct that would otherwise begin - or interrupt - a paragraph."""
    match = _LINE_START.match(line)
    if match is None:
        return line
    at = match.start("ordinal") if match.group("ordinal") is not None else 0
    return f"{line[:at]}\\{line[at:]}"


def _children(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    content = node.get("content")
    if not isinstance(content, list):
        return []
    return [child for child in content if isinstance(child, Mapping)]
