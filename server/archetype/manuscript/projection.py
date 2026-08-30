"""Text projection and heading extraction (P1-7, D18).

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
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BLOCK_SEPARATOR",
    "MAX_DEPTH",
    "SCENE_BREAK",
    "Heading",
    "InvalidDocumentError",
    "Projection",
    "count_words",
    "empty_document",
    "project",
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
class Projection:
    """Everything the server derives from ``content_json`` on save (D18)."""

    text_plain: str
    headings: tuple[Heading, ...]
    word_count: int

    def headings_as_dicts(self) -> list[dict[str, Any]]:
        return [heading.to_dict() for heading in self.headings]


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

    blocks: list[str] = []
    headings: list[Heading] = []
    for node in _children(document):
        _walk(node, blocks, headings)

    text_plain = BLOCK_SEPARATOR.join(blocks)
    return Projection(
        text_plain=text_plain,
        headings=tuple(headings),
        word_count=count_words(text_plain),
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


def _walk(node: Mapping[str, Any], blocks: list[str], headings: list[Heading]) -> None:
    """Append this node's contribution to ``blocks`` and ``headings``, depth-first."""
    node_type = node.get("type")

    if node_type in _TEXT_BLOCK_TYPES:
        text = _inline_text(node)
        if node_type == "heading":
            headings.append(Heading(level=_heading_level(node), text=text, ordinal=len(headings)))
        if text:
            blocks.append(text)
        return

    if node_type in _SCENE_BREAK_TYPES:
        blocks.append(SCENE_BREAK)
        return

    for child in _children(node):
        _walk(child, blocks, headings)


def _inline_text(node: Mapping[str, Any]) -> str:
    """The text of one text block: marks dropped, hard breaks kept, blank lines dropped."""
    return _tidy(_inline_parts(node))


def _inline_parts(node: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for child in _children(node):
        child_type = child.get("type")
        if child_type == "text":
            text = child.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif child_type in _LINE_BREAK_TYPES:
            parts.append("\n")
        else:
            # An inline node this module does not know contributes whatever text it wraps.
            parts.append(_inline_parts(child))
    return "".join(parts)


def _tidy(text: str) -> str:
    """Trim each line and drop the empty ones - a block may not contain a blank line."""
    return "\n".join(line for line in (raw.strip() for raw in text.split("\n")) if line)


def _heading_level(node: Mapping[str, Any]) -> int:
    """The heading's level, clamped to 1-6. A missing or unusable level reads as 1."""
    attrs = node.get("attrs")
    level = attrs.get("level") if isinstance(attrs, Mapping) else None
    if isinstance(level, bool) or not isinstance(level, int):
        return _MIN_HEADING_LEVEL
    return max(_MIN_HEADING_LEVEL, min(_MAX_HEADING_LEVEL, level))
