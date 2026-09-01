"""The closed manuscript schema, as the server sees it (P2-13, P1-10, D1).

The schema itself is declared in ``web/src/editor/extensions.ts`` - that is where the editor is
built and where a new node would actually be added. This module is the server's **mirror** of it,
and it exists because Markdown is the first server-side feature that has to be *total* over the
node vocabulary: the projection deliberately walks a node it has never heard of rather than
throwing (a projection that rejected an unknown node would turn a schema question into lost
text), but a serializer cannot invent syntax for one.

The two are held together the way the projection is - by a shared fixture rather than by
discipline. ``server/tests/fixtures/schema/closed_schema.json`` states the vocabulary once;
``tests/test_markdown.py`` asserts this module and the serializer cover exactly it, and
``web/src/__tests__/schema.test.ts`` asserts the schema TipTap actually built is exactly it. So
a node added to the editor fails a test on both sides of the wire in the commit that adds it,
which is the point of a closed list.

Attribute defaults
------------------

:data:`ATTR_DEFAULTS` is not decoration. ProseMirror's ``Node.toJSON`` emits an ``attrs`` object
whenever the node *type* declares one, defaults included - so a heading arrives as
``{"level": 1}`` and an ordered list as ``{"start": 1, "type": null}``, always. An importer that
omitted them would produce documents that render correctly and still fail the round-trip
comparison in P2-14, which is asserted as JSON equality against what the editor produces. So the
defaults are written down here, once, and :func:`node` is the only place a node is built.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ALLOWED_MARKS",
    "ALLOWED_NODES",
    "ATTR_DEFAULTS",
    "MAX_HEADING_LEVEL",
    "UnknownNodeError",
    "empty_paragraph",
    "node",
]

#: Every node type the manuscript may contain, sorted. Mirrors ``ALLOWED_NODES``.
ALLOWED_NODES: tuple[str, ...] = (
    "blockquote",
    "bulletList",
    "doc",
    "hardBreak",
    "heading",
    "horizontalRule",
    "listItem",
    "orderedList",
    "paragraph",
    "text",
)

#: Every mark the manuscript may carry, sorted. Emphasis only. Mirrors ``ALLOWED_MARKS``.
ALLOWED_MARKS: tuple[str, ...] = ("bold", "italic")

#: The attributes each node type declares, with the values ProseMirror fills in. A type absent
#: from this mapping declares none and its JSON carries no ``attrs`` key at all.
ATTR_DEFAULTS: dict[str, dict[str, Any]] = {
    "heading": {"level": 1},
    "orderedList": {"start": 1, "type": None},
}

#: The deepest heading the editor offers (``HEADING_LEVELS`` is 1-3). An imported ``####`` is
#: not a node the schema cannot hold - it is a heading whose level it cannot hold - so it is
#: taken down to this and the demotion is reported (P2-14).
MAX_HEADING_LEVEL = 3


class UnknownNodeError(ValueError):
    """A node type outside :data:`ALLOWED_NODES` reached code that must be total over it.

    Raised by the Markdown serializer rather than guessed at. A document holding one has been
    written by something that is not this editor, and inventing syntax for it would put text
    into a file that could never be read back.
    """

    def __init__(self, node_type: str) -> None:
        super().__init__(
            f"{node_type!r} is not in the manuscript schema; "
            f"expected one of {', '.join(ALLOWED_NODES)}"
        )
        self.node_type = node_type


def node(node_type: str, **fields: Any) -> dict[str, Any]:
    """Build one node exactly as ProseMirror's ``toJSON`` would emit it.

    Attributes passed in override the defaults; the rest of the type's declared attributes are
    filled in, and an empty ``content`` is dropped, so the result compares equal to a document
    that came out of the editor.
    """
    built: dict[str, Any] = {"type": node_type}
    declared = ATTR_DEFAULTS.get(node_type)
    if declared is not None:
        attrs = dict(declared)
        attrs.update(fields.pop("attrs", None) or {})
        built["attrs"] = attrs
    else:
        fields.pop("attrs", None)
    if not fields.get("content", True):
        # ProseMirror omits `content` for a node with no children, so an empty heading is
        # `{"type": "heading", "attrs": {"level": 2}}` and not the same thing with an empty
        # list in it. Dropping it here is what makes the round trip an equality.
        fields.pop("content")
    built.update(fields)
    return built


def empty_paragraph() -> dict[str, Any]:
    """The one node a document may never be without.

    A ProseMirror ``doc`` is ``block+``: it cannot be empty. An imported file with nothing in it
    - and an exported chapter that was empty - both come back as this, which is exactly
    ``projection.empty_document()``'s content.
    """
    return node("paragraph")
