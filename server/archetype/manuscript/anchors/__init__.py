"""Anchors: durable references to ranges of manuscript text (Phase 2).

``specs/anchors.md`` is the specification, written in P2-4 before any of this code.

* :mod:`.status` (P2-1) - the status vocabulary, and the one rule that derives ``orphaned``.
* :mod:`.resolve` (P2-6) - the matching ladder. Pure: no database, no framework, no I/O.
* :mod:`.records` (P2-7) - the stored anchor, and the one place a row becomes one.
* :mod:`.rewrite` (P2-7) - re-resolution inside the transaction of the save that caused it.
* :mod:`.store` (P2-7) - :class:`~.store.AnchorStore`, the repository the routes drive.

The layering is deliberate and one-way. :mod:`.rewrite` is what
:class:`~archetype.manuscript.documents.DocumentStore` calls on every write, so it must not
import the document store back; :mod:`.store` sits above both and raises the *same*
:class:`~archetype.manuscript.documents.StaleVersionError` a save raises. Which is why only the
pure halves are re-exported here: importing the store from this file would close the cycle.
"""

from .records import ANCHOR_COLUMNS, Anchor, anchor_from_row, as_record
from .resolve import (
    CONTEXT_CHARS,
    MAX_QUOTE_CHARS,
    MIN_CONTEXT_SCORE,
    RESOLUTION_BUDGET_MS,
    WIN_MARGIN,
    AnchorRangeError,
    AnchorRecord,
    Extraction,
    Resolution,
    ResolutionContext,
    Suggestion,
    collapse,
    context_for,
    extract,
    max_suggestion_chars,
    normalise,
    resolve,
    resolve_all,
)
from .status import (
    ALL_STATUSES,
    EFFECTIVE_STATUS_SQL,
    STORED_STATUSES,
    AnchorStatus,
    effective_status,
)

__all__ = [
    "ALL_STATUSES",
    "ANCHOR_COLUMNS",
    "CONTEXT_CHARS",
    "EFFECTIVE_STATUS_SQL",
    "MAX_QUOTE_CHARS",
    "MIN_CONTEXT_SCORE",
    "RESOLUTION_BUDGET_MS",
    "STORED_STATUSES",
    "WIN_MARGIN",
    "Anchor",
    "AnchorRangeError",
    "AnchorRecord",
    "AnchorStatus",
    "Extraction",
    "Resolution",
    "ResolutionContext",
    "Suggestion",
    "anchor_from_row",
    "as_record",
    "collapse",
    "context_for",
    "effective_status",
    "extract",
    "max_suggestion_chars",
    "normalise",
    "resolve",
    "resolve_all",
]
