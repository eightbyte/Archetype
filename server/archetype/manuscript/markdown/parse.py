"""Markdown import: CommonMark in, the closed schema out (P2-14, D15).

The parser is `markdown-it-py`, not ours (phase-2 plan section 2, ruling 3). Serializing this
schema is small, total, and ours to define; parsing CommonMark is neither - nested emphasis,
lazy continuation, setext headings and list tightness are corners a hand-rolled parser gets
subtly wrong in ways nobody notices until an import mangles a chapter someone typed. This module
is the part that *is* ours: turning a token stream into manuscript nodes, and saying out loud
what it could not keep.

Nothing is silently discarded
-----------------------------

Markdown can express more than the manuscript schema holds. Every such construct produces a
:class:`Notice` - what it was, which line it was on, and what happened to it - and the import
route returns the list. Where the construct carries **words**, the words are kept and only the
construct is lost, because a code fence in a chapter is far more likely to be a paragraph the
writer indented than a program:

===================  ==========================================================
code fence, indented the text is kept as a paragraph, its lines as hard breaks
code block
inline code          the text is kept, without the code formatting
link                 the link text is kept, the target is not
image                the alt text is kept if there is any
heading below H3     the heading is kept, taken down to level 3
a title over 200     the title is kept, cut to fit
characters
===================  ==========================================================

A construct the closed schema *can* hold is simply held: headings, paragraphs, blockquotes,
bullet and ordered lists, thematic breaks, bold, italic, and hard breaks.

Everything else is **not a construct**, and that is deliberate. The parser runs the strict
``commonmark`` preset with ``html`` off, so a table, a strikethrough, a footnote, and a ``<div>``
are not syntax it knows - they arrive as the characters the writer typed, in a paragraph. That
is why they produce no notice: nothing was dropped. Enabling a plugin so that the importer could
announce having flattened a table would mean the *parser* recognises constructs the product has
decided not to have, and would leave the notice list a mix of real losses and things that merely
looked like one. What it costs is that a table's row boundaries become spaces, by the soft-break
rule below; every character of it survives.

Two normalisations that are not losses
--------------------------------------

A **soft break** - the newline in a hard-wrapped paragraph - becomes a single space. The line on
which a sentence happens to wrap in a text file is not a fact about the manuscript, and turning
each wrap into a hard break would fill an imported chapter with breaks nobody typed.

Adjacent runs carrying the same marks are **merged into one text node**, which is what the
editor holds and what the serializer writes, so ``import(export(doc)) == doc`` compares equal as
JSON rather than nearly-equal.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from markdown_it import MarkdownIt
from markdown_it.token import Token

from ..documents import MAX_TITLE_LENGTH
from .schema import ALLOWED_MARKS, MAX_HEADING_LEVEL, empty_paragraph, node

__all__ = [
    "IMPORT_MODES",
    "ImportMode",
    "ImportedChapter",
    "ImportedManuscript",
    "Notice",
    "parse_markdown",
    "read_manuscript",
]


class ImportMode:
    """How a Markdown file becomes chapters."""

    #: The whole file is one chapter. A leading H1 stays in the text - this is the mode the
    #: round-trip corpus runs in, and eating the first heading would break it.
    ONE_CHAPTER: Final[str] = "one-chapter"
    #: Every top-level H1 starts a chapter and becomes its title. Text before the first H1 is a
    #: chapter of its own. This is the shape the combined export writes.
    SPLIT_ON_H1: Final[str] = "split-on-h1"


#: Both modes, for validation at the wire edge and in this module. Spelled in
#: ``api/schemas.py`` as well, and a test asserts the two are the same set - the discipline B10
#: established for the anchor status filter.
IMPORT_MODES: Final[frozenset[str]] = frozenset({ImportMode.ONE_CHAPTER, ImportMode.SPLIT_ON_H1})

_H1 = 1

# `commonmark` is the strict preset: no tables, no strikethrough, no linkify. `html` off on top
# of it, so a `<div>` in a manuscript is the five characters the writer typed rather than a node
# this schema has no room for.
_PARSER = MarkdownIt("commonmark", {"html": False})

_EMPHASIS_MARKS = {"strong": "bold", "em": "italic"}


@dataclass(frozen=True, slots=True)
class Notice:
    """One thing the closed schema could not hold, and what became of it.

    ``element`` names what it was and ``line`` is 1-based, pointing at the line it started on,
    so the report reads
    against the file the writer chose rather than against the token stream.
    """

    element: str
    line: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"element": self.element, "line": self.line, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ImportedChapter:
    """One chapter an import would create. ``title`` is ``None`` for "let the store name it"."""

    title: str | None
    content: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ImportedManuscript:
    """Everything an import found, before anything has been written.

    Held as a value on purpose: P2-14 refuses an oversized chapter *before* creating any of
    them, which is only possible if parsing and creating are two steps.
    """

    chapters: tuple[ImportedChapter, ...]
    notices: tuple[Notice, ...]


def read_manuscript(
    markdown: str, *, mode: str = ImportMode.ONE_CHAPTER, title: str | None = None
) -> ImportedManuscript:
    """Read a Markdown file into the chapters it describes.

    Args:
        markdown: The file's text. Anything is valid input - a plain text file is valid
            Markdown, and a writer will try one.
        mode: :data:`ImportMode.ONE_CHAPTER` or :data:`ImportMode.SPLIT_ON_H1`.
        title: The title for the single chapter of ``one-chapter`` mode. Ignored by
            ``split-on-h1``, which takes each chapter's title from its own heading.

    Raises:
        ValueError: If ``mode`` is not one of :data:`IMPORT_MODES`.
    """
    if mode not in IMPORT_MODES:
        raise ValueError(f"unknown import mode {mode!r}; expected one of {sorted(IMPORT_MODES)}")

    blocks, notices = parse_markdown(markdown)
    if mode == ImportMode.ONE_CHAPTER:
        chapters = [ImportedChapter(title=title, content=_document(blocks))]
    else:
        chapters, split_notices = _split_on_h1(blocks)
        notices = [*notices, *split_notices]
    return ImportedManuscript(chapters=tuple(chapters), notices=tuple(notices))


def parse_markdown(markdown: str) -> tuple[list[dict[str, Any]], list[Notice]]:
    """The top-level blocks of a Markdown file, and what could not be kept.

    The blocks are returned bare rather than wrapped in a ``doc`` so that ``split-on-h1`` can
    cut between them without unwrapping anything.
    """
    notices: list[Notice] = []
    blocks = _Reader(notices).blocks(_PARSER.parse(markdown))
    return blocks, notices


def _document(blocks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Wrap blocks as a document. A ProseMirror ``doc`` is ``block+`` and can never be empty."""
    return {"type": "doc", "content": list(blocks) or [empty_paragraph()]}


def _split_on_h1(blocks: Sequence[dict[str, Any]]) -> tuple[list[ImportedChapter], list[Notice]]:
    """Cut the block list at every top-level H1, which becomes the chapter's title."""
    notices: list[Notice] = []
    chapters: list[ImportedChapter] = []
    title: str | None = None
    current: list[dict[str, Any]] = []

    def close() -> None:
        if title is not None or current:
            chapters.append(ImportedChapter(title=title, content=_document(current)))

    for block in blocks:
        if block.get("type") == "heading" and block.get("attrs", {}).get("level") == _H1:
            close()
            title, cut = _title_of(block)
            notices.extend(cut)
            current = []
            continue
        current.append(block)
    close()

    return chapters or [ImportedChapter(title=None, content=_document([]))], notices


def _title_of(heading: dict[str, Any]) -> tuple[str | None, list[Notice]]:
    """A heading's plain text as a chapter title, cut to what a title may be."""
    text = " ".join(_plain_text(heading.get("content") or []).split())
    if not text:
        return None, []
    if len(text) <= MAX_TITLE_LENGTH:
        return text, []
    return text[:MAX_TITLE_LENGTH].rstrip(), [
        Notice(
            element="chapter title",
            line=1,
            detail=(
                f"a chapter title may be at most {MAX_TITLE_LENGTH} characters; "
                "the heading was cut to fit"
            ),
        )
    ]


def _plain_text(nodes: Iterable[dict[str, Any]]) -> str:
    parts: list[str] = []
    for child in nodes:
        if child.get("type") == "text":
            parts.append(str(child.get("text") or ""))
        elif child.get("type") == "hardBreak":
            parts.append(" ")
    return "".join(parts)


class _Reader:
    """The token stream, turned into blocks. One instance per file; notices accumulate in it."""

    def __init__(self, notices: list[Notice]) -> None:
        self.notices = notices

    # -- blocks -----------------------------------------------------------------------------

    def blocks(self, tokens: Sequence[Token]) -> list[dict[str, Any]]:
        """Walk the flat token stream with an explicit stack of open containers."""
        stack: list[list[dict[str, Any]]] = [[]]
        openers: list[Token] = []

        for token in tokens:
            kind = token.type

            if kind.endswith("_open"):
                stack.append([])
                openers.append(token)
                continue

            if kind.endswith("_close"):
                children = stack.pop()
                opener = openers.pop()
                built = self._container(opener, children)
                if built is not None:
                    stack[-1].append(built)
                continue

            if kind == "inline":
                stack[-1].extend(self._inline(token))
                continue

            block = self._leaf(token)
            if block is not None:
                stack[-1].append(block)

        # A malformed stream cannot leave containers open - markdown-it always balances - but
        # flattening rather than raising keeps an import from failing over a parser surprise.
        while len(stack) > 1:
            children = stack.pop()
            stack[-1].extend(children)
        return stack[0]

    def _container(self, opener: Token, children: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Close one container token, given the blocks or inline nodes it collected."""
        kind = opener.type

        if kind == "paragraph_open":
            return node("paragraph", content=children) if children else None
        if kind == "heading_open":
            return node("heading", attrs={"level": self._level(opener)}, content=children)
        if kind == "blockquote_open":
            return node("blockquote", content=children or [empty_paragraph()])
        if kind == "bullet_list_open":
            return node("bulletList", content=children or [self._empty_item()])
        if kind == "ordered_list_open":
            start = opener.attrGet("start")
            # markdown-it records `start` only when the list does not begin at 1, and a
            # list may legitimately begin at 0, so the test is presence and not truth.
            attrs = {} if start is None else {"start": int(start)}
            return node("orderedList", attrs=attrs, content=children or [self._empty_item()])
        if kind == "list_item_open":
            return node("listItem", content=children or [empty_paragraph()])

        # An opener this reader has not been taught - only reachable if a rule is enabled that
        # the presets above leave off. Its children are kept; the wrapper is reported.
        self._note(opener, opener.tag or kind, "the surrounding formatting was not kept")
        return node("paragraph", content=children) if children else None

    def _leaf(self, token: Token) -> dict[str, Any] | None:
        """A block token with no children of its own."""
        if token.type == "hr":
            return node("horizontalRule")
        if token.type in {"fence", "code_block"}:
            what = "code fence" if token.type == "fence" else "indented code block"
            self._note(token, what, "the text was kept as a paragraph; the code formatting was not")
            return self._code_paragraph(token.content)
        if token.type == "html_block":
            # Unreachable while `html` is off, and harmless if it is ever turned on.
            return self._code_paragraph(token.content)
        return None

    def _code_paragraph(self, content: str) -> dict[str, Any] | None:
        lines = [line for line in content.rstrip("\n").split("\n")]
        inline: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            if index:
                inline.append(node("hardBreak"))
            if line:
                inline.append(node("text", text=line))
        return node("paragraph", content=inline) if inline else None

    def _empty_item(self) -> dict[str, Any]:
        return node("listItem", content=[empty_paragraph()])

    def _level(self, token: Token) -> int:
        """``h1``-``h6`` as a level the editor offers, reporting anything it has to take down."""
        try:
            level = int((token.tag or "h1")[1:])
        except ValueError:
            level = 1
        if level > MAX_HEADING_LEVEL:
            self._note(
                token,
                f"heading level {level}",
                f"the editor offers levels 1 to {MAX_HEADING_LEVEL}; "
                f"the heading was imported at level {MAX_HEADING_LEVEL}",
            )
            return MAX_HEADING_LEVEL
        return max(1, level)

    # -- inline -----------------------------------------------------------------------------

    def _inline(self, token: Token) -> list[dict[str, Any]]:
        """One ``inline`` token's children, as text and hard breaks carrying marks."""
        line = self._line(token)
        out: list[dict[str, Any]] = []
        marks: list[str] = []

        for child in token.children or []:
            kind = child.type

            if kind in {"text", "text_special", "html_inline"}:
                self._append_text(out, child.content, marks)
            elif kind == "softbreak":
                self._append_text(out, " ", marks)
            elif kind == "hardbreak":
                out.append(node("hardBreak"))
            elif kind in {"strong_open", "em_open"}:
                marks.append(_EMPHASIS_MARKS[child.tag])
            elif kind in {"strong_close", "em_close"}:
                mark = _EMPHASIS_MARKS[child.tag]
                if mark in marks:
                    marks.remove(mark)
            elif kind == "code_inline":
                self._note_at(line, "inline code", "the text was kept; the code formatting was not")
                self._append_text(out, child.content, marks)
            elif kind == "link_open":
                href = child.attrGet("href") or ""
                self._note_at(
                    line, "link", f"the link text was kept; {href or 'the target'} was not"
                )
            elif kind == "link_close":
                pass
            elif kind == "image":
                alt = (child.content or "").strip()
                source = child.attrGet("src") or ""
                self._note_at(
                    line,
                    "image",
                    f"an image is not part of the manuscript; {source or 'it'} was not kept",
                )
                if alt:
                    self._append_text(out, alt, marks)
            else:
                self._note_at(line, child.tag or kind, "it was not kept")

        return out

    def _append_text(self, out: list[dict[str, Any]], text: str, marks: Sequence[str]) -> None:
        """Add text, merging it into the previous node when the marks are the same.

        The merge is what makes the round trip an equality: the serializer writes one run per
        set of marks, so an importer that left ``a``/``b``/``c`` as three nodes would produce a
        document that renders identically and compares unequal.
        """
        if not text:
            return
        ordered = [mark for mark in ALLOWED_MARKS if mark in marks]
        if out and out[-1].get("type") == "text" and _marks_of(out[-1]) == ordered:
            out[-1]["text"] = str(out[-1]["text"]) + text
            return
        built = node("text", text=text)
        if ordered:
            built["marks"] = [{"type": mark} for mark in ordered]
        out.append(built)

    # -- notices ----------------------------------------------------------------------------

    def _note(self, token: Token, element: str, detail: str) -> None:
        self._note_at(self._line(token), element, detail)

    def _note_at(self, line: int, element: str, detail: str) -> None:
        self.notices.append(Notice(element=element, line=line, detail=detail))

    @staticmethod
    def _line(token: Token) -> int:
        return (token.map[0] + 1) if token.map else 1


def _marks_of(text_node: dict[str, Any]) -> list[str]:
    return [str(mark.get("type")) for mark in text_node.get("marks") or []]
