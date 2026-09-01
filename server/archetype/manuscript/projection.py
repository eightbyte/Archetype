"""Text projection, heading extraction, and the block index (P1-7, P2-5, D18).

A pure module: ProseMirror document JSON in, ``(text_plain, headings, word_count)`` out. No
database, no framework, no I/O. This is the most-reused code in the project - the TOC reads it
now, chunking reads it in Phase 5, and agent context composition reads it in Phase 6 - so its
rules are written down here rather than inferred from its callers.

A mirror of this module lives at ``web/src/editor/projection.ts`` so the TOC stays live between
saves. Both are driven by the same fixture set (``tests/fixtures/projection/cases.json``), so
drift shows up as a test failure rather than as a confusing TOC. The server answer wins on save
(D18).

The rules
---------

**Blocks.** ``paragraph`` and ``heading`` are text blocks: each contributes one block of text.
Container nodes (``blockquote``, ``bulletList``, ``orderedList``, ``listItem``, and the document
itself) contribute nothing of their own and are walked through. A block that comes out empty is
dropped, so exactly one blank line separates blocks and later chunking can split on real
boundaries instead of guessing.

**No decoration.** List items get no bullet, blockquotes get no quote marker, marks contribute
nothing. ``text_plain`` is what the words are, not what they look like; formatting lives in
``content_json``.

**Scene breaks are text.** A ``horizontalRule`` projects as its own block reading ``* * *``. It
is a real narrative boundary, and a chunker that could not see it would cut across a scene
change. It contributes no words (see below).

**Line breaks.** A ``hardBreak`` is a newline *within* a block. Blank lines inside a block are
dropped, because a blank line is how blocks are separated and a block must not be able to forge
one.

**Headings.** Every ``heading`` node is a heading, including an empty one, and its ``ordinal`` is
its index among all heading nodes in document order, counting from zero. That makes an ordinal
mean exactly "the Nth heading node in this document", which is what jump-to-heading resolves
against before anchors exist (P1-11). Skipping empty headings would renumber every heading below
the one being typed.

**Words.** A word is a run of Unicode letters and digits, optionally joined by apostrophes or
dashes, so ``well-known`` is one word and ``* * *`` is none. The count is taken over
``text_plain``, headings included, and it is the only word-count definition in the project.

**Unknown nodes are projected, not rejected.** A node type this module has never heard of is
walked for its content. The TipTap schema is a closed list (P1-10), enforced where the document
is authored; a projection that threw here would turn a schema question into lost text.

The block index (P2-5)
----------------------

Anchors are *authored* in ProseMirror positions and *matched* in ``text_plain`` offsets, and the
two spaces are not related by arithmetic across a document: two sibling paragraphs are two
positions apart and two characters apart, a paragraph closing a blockquote is three positions
from the next paragraph and still two characters, and a ``horizontalRule`` is one position and
five characters. They *are* linear within a text block. So :class:`Projection` carries a
:class:`Block` per block it emits, produced by the **same walk** that produces ``text_plain`` -
not a second one, because two walks over the same tree are two chances to disagree about what a
block is, and an index that disagrees with the text it indexes makes every anchor in the project
subtly wrong at once. ``specs/anchors.md`` section 2 is the specification.

**``mappable`` is whether an anchor may begin or end inside a block.** It is false for a
``horizontalRule`` - five characters nobody typed over one position, with no honest
correspondence between them - and false for a block that projects to nothing, because there is
nothing in it to anchor. Both still appear in the index, so that positions on either side of
them convert correctly.

The two conversions are :func:`text_offset_to_pm_position` and :func:`pm_range_to_text_span`.
Within a block they are a **walk** of its inline text rather than arithmetic, because each line
of a block is trimmed and empty lines are dropped: a paragraph carrying a stray trailing space
is shorter in ``text_plain`` than in the document, and arithmetic would point one character
early for every character trimmed away. The walk takes the arithmetic shortcut exactly when the
block's projected length equals the length of the text its inline nodes hold, which is nearly
always.

The mirror at ``web/src/editor/projection.ts`` has **no** index and does not need one: for the
open document ProseMirror's own transaction mapping is exact and free, and after a reload the
server's answer arrives with the document (D21). One implementation, not two.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BLOCK_SEPARATOR",
    "MAX_DEPTH",
    "SCENE_BREAK",
    "Block",
    "Heading",
    "InvalidDocumentError",
    "Projection",
    "count_words",
    "empty_document",
    "pm_range_to_text_span",
    "project",
    "text_offset_to_pm_position",
    "tidy_block",
    "validate_document",
]

#: What separates two blocks in ``text_plain``. Exactly one blank line, always.
BLOCK_SEPARATOR = "\n\n"

#: How a ``horizontalRule`` reads in ``text_plain``.
SCENE_BREAK = "* * *"

#: How deep a document may nest before it is rejected. A blockquote holding a list holding a
#: paragraph is four levels; sixty-four is far past anything the editor can produce, and it
#: keeps a hand-crafted payload from recursing this module into a stack overflow.
MAX_DEPTH = 64

_TEXT_BLOCK_TYPES = frozenset({"paragraph", "heading"})
_SCENE_BREAK_TYPES = frozenset({"horizontalRule"})
_LINE_BREAK_TYPES = frozenset({"hardBreak"})

# Unicode letters and digits - [^\W_] is \w without the underscore - optionally joined by an
# apostrophe (straight or curly) or a dash. The TypeScript mirror spells the same rule with
# \p{L} and \p{N}, because JavaScript's \w is ASCII-only and would split "naive" spelled with
# a diaeresis into two words.
# The hyphen is last so it is a literal inside the character class, not a range.
_WORD_JOINERS = "'\u2019\u2010-\u2015-"
_WORD_PATTERN = re.compile(rf"[^\W_]+(?:[{_WORD_JOINERS}][^\W_]+)*", re.UNICODE)

_MIN_HEADING_LEVEL = 1
_MAX_HEADING_LEVEL = 6


class InvalidDocumentError(ValueError):
    """The value is not a well-formed ProseMirror document.

    Raised before anything is written, so a malformed payload never reaches storage (P1-6).
    """


@dataclass(frozen=True, slots=True)
class Heading:
    """One heading, addressed by its position among the document's headings."""

    level: int
    text: str
    ordinal: int

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "text": self.text, "ordinal": self.ordinal}


@dataclass(frozen=True, slots=True)
class Block:
    """One block of the projection, in both coordinate systems (P2-5).

    ``pm_from``/``pm_to`` span the block's **content**: for a text block that is one past the
    position of the node itself, up to one before its closing position. For a leaf block - a
    ``horizontalRule`` - there is no content, so they span the node's own single position.

    ``text_from``/``text_to`` span the block in ``text_plain``, excluding the separators around
    it. A block that projects to nothing gets a zero-length span at the end of the text built so
    far, so that positions on either side of it still convert.

    ``mappable`` is whether an anchor may begin or end inside this block (``specs/anchors.md``
    section 2). It is false for a scene break and for a block that projects to nothing. A
    non-mappable block that still carries text is a scene break, and a range that spans one has
    no honest quote - so :func:`pm_range_to_text_span` refuses it.
    """

    pm_from: int
    pm_to: int
    text_from: int
    text_to: int
    mappable: bool
    #: The block's inline text *before* the projection trimmed it - the walk's input, and the
    #: only thing the two conversions need beyond the four offsets. Not part of the index as
    #: ``specs/anchors.md`` states it (see the Phase 2 plan's as-built deviations): carrying it
    #: is what lets a conversion be a pure function of the projection rather than of the
    #: document, so the resolver never has to hold the document JSON to answer a position.
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        """The index as the shared fixture file states it - the four offsets and the flag."""
        return {
            "pm_from": self.pm_from,
            "pm_to": self.pm_to,
            "text_from": self.text_from,
            "text_to": self.text_to,
            "mappable": self.mappable,
        }


@dataclass(frozen=True, slots=True)
class Projection:
    """Everything the server derives from ``content_json`` on save (D18)."""

    text_plain: str
    headings: tuple[Heading, ...]
    word_count: int
    #: One entry per block emitted by the walk, in document order (P2-5). Empty only for a
    #: document with no blocks at all.
    blocks: tuple[Block, ...] = ()

    def headings_as_dicts(self) -> list[dict[str, Any]]:
        return [heading.to_dict() for heading in self.headings]

    def blocks_as_dicts(self) -> list[dict[str, Any]]:
        return [block.to_dict() for block in self.blocks]


def empty_document() -> dict[str, Any]:
    """A fresh copy of the document TipTap produces for an empty editor."""
    return {"type": "doc", "content": [{"type": "paragraph"}]}


def count_words(text: str) -> int:
    """The number of words in ``text``. The one word-count definition in the project."""
    return len(_WORD_PATTERN.findall(text))


def project(document: Any) -> Projection:
    """Derive ``text_plain``, the heading list, and the word count from a document.

    Args:
        document: A ProseMirror/TipTap document - ``{"type": "doc", "content": [...]}``.

    Raises:
        InvalidDocumentError: If the value is not a well-formed document. Validation runs
            first, so a caller holding a return value has a document it can store.
    """
    validate_document(document)

    walk = _Walk()
    position = 0
    for node in _children(document):
        position = walk.visit(node, position)

    text_plain = BLOCK_SEPARATOR.join(walk.blocks)
    return Projection(
        text_plain=text_plain,
        headings=tuple(walk.headings),
        word_count=count_words(text_plain),
        blocks=tuple(walk.index),
    )


def validate_document(document: Any, *, max_depth: int = MAX_DEPTH) -> None:
    """Check that ``document`` is a well-formed ProseMirror document.

    Structure only - the node *vocabulary* is not checked here (see the module docstring).

    Raises:
        InvalidDocumentError: With a message naming the offending path, so a rejected save can
            say something more useful than "invalid".
    """
    if not isinstance(document, Mapping):
        raise InvalidDocumentError(f"document must be a JSON object, got {type(document).__name__}")
    if document.get("type") != "doc":
        raise InvalidDocumentError(f"document type must be 'doc', got {document.get('type')!r}")
    _validate_content(document, path="doc", depth=0, max_depth=max_depth)


def _validate_content(node: Mapping[str, Any], *, path: str, depth: int, max_depth: int) -> None:
    if depth > max_depth:
        raise InvalidDocumentError(f"document nests deeper than {max_depth} levels at {path}")

    content = node.get("content")
    if content is None:
        return
    if not isinstance(content, list):
        raise InvalidDocumentError(f"{path}.content must be an array, got {type(content).__name__}")

    for index, child in enumerate(content):
        child_path = f"{path}.content[{index}]"
        if not isinstance(child, Mapping):
            raise InvalidDocumentError(
                f"{child_path} must be a JSON object, got {type(child).__name__}"
            )
        child_type = child.get("type")
        if not isinstance(child_type, str) or not child_type:
            raise InvalidDocumentError(f"{child_path}.type must be a non-empty string")
        if child_type == "text" and not isinstance(child.get("text"), str):
            raise InvalidDocumentError(f"{child_path} is a text node without a string 'text'")
        attrs = child.get("attrs")
        if attrs is not None and not isinstance(attrs, Mapping):
            raise InvalidDocumentError(f"{child_path}.attrs must be a JSON object")
        _validate_content(
            child, path=f"{child_path}({child_type})", depth=depth + 1, max_depth=max_depth
        )


def _children(node: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    content = node.get("content")
    return content if isinstance(content, list) else ()


@dataclass(slots=True)
class _Walk:
    """The one walk: text blocks, headings, and the block index, built together (P2-5)."""

    blocks: list[str] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    index: list[Block] = field(default_factory=list)
    #: The length of ``text_plain`` as built so far, separators included.
    text_length: int = 0

    def visit(self, node: Mapping[str, Any], position: int) -> int:
        """Append this node's contribution, depth-first; return the position just after it.

        ProseMirror's position arithmetic, stated once: a text node spans its length, a leaf
        spans one, and any other node spans two - its own open and close - plus whatever its
        children span.
        """
        node_type = node.get("type")

        if node_type in _TEXT_BLOCK_TYPES:
            raw, inline_size = _inline_scan(node)
            text = _tidy(raw)
            if node_type == "heading":
                self.headings.append(
                    Heading(level=_heading_level(node), text=text, ordinal=len(self.headings))
                )
            self._add(
                text,
                pm_from=position + 1,
                pm_to=position + 1 + inline_size,
                raw=raw,
                # An unknown *inline* node costs two positions and contributes only the text it
                # wraps, so the block stops being linear and there is no honest offset in it.
                # The closed schema (P1-10) has no such node; a future one gets an answer here.
                mappable=bool(text) and inline_size == len(raw),
            )
            return position + 2 + inline_size

        if node_type in _SCENE_BREAK_TYPES:
            self._add(SCENE_BREAK, pm_from=position, pm_to=position + 1, raw="", mappable=False)
            return position + 1

        if node_type in _LINE_BREAK_TYPES:
            return position + 1

        if node_type == "text":
            # Inline text directly inside a container is malformed but well-formed enough to
            # store, and it still occupies its own length in positions.
            text_value = node.get("text")
            return position + (len(text_value) if isinstance(text_value, str) else 0)

        inner = position + 1
        for child in _children(node):
            inner = self.visit(child, inner)
        return inner + 1

    def _add(self, text: str, *, pm_from: int, pm_to: int, raw: str, mappable: bool) -> None:
        """Record one block, in both coordinate systems.

        A block that projects to nothing is dropped from the text - that is the P1-7 rule - but
        it still takes an entry, with a zero-length span where it sits, so that a position
        inside it converts to something rather than to nothing.
        """
        if not text:
            self.index.append(
                Block(
                    pm_from=pm_from,
                    pm_to=pm_to,
                    text_from=self.text_length,
                    text_to=self.text_length,
                    mappable=mappable,
                    raw=raw,
                )
            )
            return

        text_from = self.text_length + (len(BLOCK_SEPARATOR) if self.blocks else 0)
        self.blocks.append(text)
        self.text_length = text_from + len(text)
        self.index.append(
            Block(
                pm_from=pm_from,
                pm_to=pm_to,
                text_from=text_from,
                text_to=self.text_length,
                mappable=mappable,
                raw=raw,
            )
        )


def _inline_scan(node: Mapping[str, Any]) -> tuple[str, int]:
    """The untidied inline text of a block, and how many positions its content spans.

    The two are equal for every block the closed schema can produce - a text node contributes
    its length to both and a ``hardBreak`` contributes one to each - which is exactly what makes
    the block linear and therefore mappable. They differ only when an inline node this module
    does not know wraps some text, because the wrapper costs two positions and contributes none.
    """
    parts: list[str] = []
    size = 0
    for child in _children(node):
        child_type = child.get("type")
        if child_type == "text":
            text = child.get("text")
            if isinstance(text, str):
                parts.append(text)
                size += len(text)
        elif child_type in _LINE_BREAK_TYPES:
            parts.append("\n")
            size += 1
        else:
            # An inline node this module does not know contributes whatever text it wraps.
            inner, inner_size = _inline_scan(child)
            parts.append(inner)
            size += inner_size + 2
    return "".join(parts), size


def tidy_block(text: str) -> str:
    """Trim each line and drop the empty ones - a block may not contain a blank line.

    Public because the Markdown serializer (P2-13) needs the *same* rule: a chapter exported to
    Markdown and stripped of its syntax must read as its ``text_plain``, and Markdown has no
    representation for a blank line inside a block anyway. One implementation, cited from both.
    """
    return _tidy_scan(text)[0]


def _tidy(text: str) -> str:
    return tidy_block(text)


def _tidy_scan(raw: str) -> tuple[str, tuple[tuple[int, int, int], ...]]:
    """Tidy one block's inline text, and say where each surviving piece came from.

    Returns the tidied text and the runs that map it back to ``raw``: each run is
    ``(text_offset, raw_offset, length)``, and together they cover the tidied text contiguously
    from zero. There is exactly one implementation of the tidy rule and this is it -
    :func:`_tidy` throws the runs away - because a second one that agreed with it today would be
    a way for the index and the text to disagree tomorrow.

    The newline that joins two surviving lines is a run of its own, mapped to the raw offset
    just past the previous line's last kept character. That is where the boundary is, whether or
    not the writer left trailing whitespace after it.
    """
    parts: list[str] = []
    runs: list[tuple[int, int, int]] = []
    text_length = 0
    raw_offset = 0
    previous_end = 0

    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped:
            if parts:
                runs.append((text_length, previous_end, 1))
                parts.append("\n")
                text_length += 1
            start = raw_offset + (len(line) - len(line.lstrip()))
            runs.append((text_length, start, len(stripped)))
            parts.append(stripped)
            text_length += len(stripped)
            previous_end = start + len(stripped)
        raw_offset += len(line) + 1

    return "".join(parts), tuple(runs)


# -- the two conversions (P2-5, specs/anchors.md section 2) ----------------------------------


def text_offset_to_pm_position(projection: Projection, offset: int) -> int | None:
    """The ProseMirror position for an offset in ``text_plain``.

    An offset that falls in the ``BLOCK_SEPARATOR`` *between* two blocks converts to the end of
    the **preceding** block - not the start of the following one - so that a range and its end
    can never straddle a boundary in different directions.

    Returns:
        The position, or ``None`` when the offset is outside the text or inside a block that
        has no honest correspondence between the two spaces (a scene break).
    """
    if offset < 0 or offset > len(projection.text_plain):
        return None

    preceding_end: int | None = None
    for block in projection.blocks:
        if not block.mappable:
            # A block that projects to nothing is passed over; an offset inside a scene break
            # has no position at all, because its five characters occupy exactly one.
            if block.text_from <= offset <= block.text_to and block.text_to > block.text_from:
                return None
            continue
        if offset < block.text_from:
            return preceding_end
        if offset <= block.text_to:
            return block.pm_from + _raw_offset_within(block, offset - block.text_from)
        preceding_end = block.pm_to
    return None


def pm_range_to_text_span(
    projection: Projection, from_pos: int, to_pos: int
) -> tuple[int, int] | None:
    """The ``text_plain`` span a ProseMirror range covers.

    A range whose ends fall in different blocks is a real range: the span runs from the first to
    the last and includes the separators between them.

    A position that is not inside any mappable block is snapped to the mappable text the range
    actually covers - a start forward, an end backward - so a selection that begins before the
    first paragraph or ends past the last one describes the text it encloses and never more.

    Returns:
        ``(text_from, text_to)``, or ``None`` when either end lands inside a scene break, when
        the range spans one, or when the range encloses no mappable text at all. A quote taken
        across a scene break would contain five characters nobody typed, which is why spanning
        one is refused rather than silently included (``specs/anchors.md`` section 8).
    """
    if to_pos < from_pos:
        return None

    start = _text_offset_of(projection, from_pos, at_end=False)
    end = _text_offset_of(projection, to_pos, at_end=True)
    if start is None or end is None or end < start:
        return None

    for block in projection.blocks:
        if block.mappable or block.text_to == block.text_from:
            continue
        if start < block.text_to and block.text_from < end:
            return None
    return (start, end)


def _text_offset_of(projection: Projection, position: int, *, at_end: bool) -> int | None:
    """One end of a range, in ``text_plain`` offsets. See :func:`pm_range_to_text_span`."""
    preceding_end: int | None = None
    for block in projection.blocks:
        if not block.mappable:
            # A block that projects to nothing is passed over; a scene break is refused,
            # because its five characters correspond to no position inside it.
            if block.text_to > block.text_from and block.pm_from <= position <= block.pm_to:
                return None
            continue
        if position < block.pm_from:
            return preceding_end if at_end else block.text_from
        if position <= block.pm_to:
            return block.text_from + _text_offset_within(block, position - block.pm_from)
        preceding_end = block.text_to
    return preceding_end if at_end else None


def _raw_offset_within(block: Block, text_offset: int) -> int:
    """Where a block-relative text offset sits in the block's untrimmed inline text."""
    if len(block.raw) == block.text_to - block.text_from:
        return text_offset  # nothing was trimmed, so the walk is exactly this arithmetic

    end = 0
    for run_text, run_raw, length in _tidy_scan(block.raw)[1]:
        if text_offset < run_text + length:
            return run_raw + (text_offset - run_text)
        end = run_raw + length
    return end


def _text_offset_within(block: Block, raw_offset: int) -> int:
    """Where a block-relative position sits in the block's projected text.

    A position inside whitespace the projection trimmed away has no text offset of its own; it
    reads as the end of the last surviving piece before it, which is the same backward snap the
    separator rule uses.
    """
    if len(block.raw) == block.text_to - block.text_from:
        return raw_offset

    text = 0
    for run_text, run_raw, length in _tidy_scan(block.raw)[1]:
        if raw_offset < run_raw:
            return text
        if raw_offset < run_raw + length:
            return run_text + (raw_offset - run_raw)
        text = run_text + length
    return text


def _heading_level(node: Mapping[str, Any]) -> int:
    """The heading's level, clamped to 1-6. A missing or unusable level reads as 1."""
    attrs = node.get("attrs")
    level = attrs.get("level") if isinstance(attrs, Mapping) else None
    if isinstance(level, bool) or not isinstance(level, int):
        return _MIN_HEADING_LEVEL
    return max(_MIN_HEADING_LEVEL, min(_MAX_HEADING_LEVEL, level))
