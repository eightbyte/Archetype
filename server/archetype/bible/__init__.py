"""The story bible: the structured record of the narrative (Phase 3).

Seven kinds of entry share **one** record, one store, one search, one revision history, and - in
Phase 7 - one review queue (D26). The difference between a character and a place is ``kind`` plus
the contents of ``attributes_json``, validated against the per-kind definition in
:mod:`archetype.bible.schema` and served to the client by ``GET /api/bible/schema``.

``specs/bible.md`` is the specification, written before this package existed. It fixes the record,
the two closed vocabularies, story-time and its two contradiction kinds, the revision and retcon
rules, and what an entry does **not** promise. Read it before changing anything here.

The package exports the pure half only. :class:`~archetype.bible.entries.EntryStore` and its
siblings are imported from their own modules, for the reason ``anchors/__init__`` does the same:
the pure modules must stay importable without dragging a store - and its errors - along with them.
"""

from __future__ import annotations

from .schema import (
    BIBLE_SCHEMA,
    ENTRY_KINDS,
    RELATIONS,
    FieldDefinition,
    FieldType,
    InvalidAttributesError,
    KindDefinition,
    RelationDefinition,
    validate,
)

__all__ = [
    "BIBLE_SCHEMA",
    "ENTRY_KINDS",
    "RELATIONS",
    "FieldDefinition",
    "FieldType",
    "InvalidAttributesError",
    "KindDefinition",
    "RelationDefinition",
    "validate",
]
