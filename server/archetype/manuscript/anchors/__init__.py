"""Anchors: durable references to ranges of manuscript text (Phase 2).

Phase 2 Group A lands the storage half - the ``anchor`` table (migration 002) and the status
vocabulary. The resolver (``resolve.py``, P2-6) and the store and routes over it (P2-7) arrive
with Group B; ``specs/anchors.md`` is the specification both are written against.
"""

from .status import (
    ALL_STATUSES,
    EFFECTIVE_STATUS_SQL,
    STORED_STATUSES,
    AnchorStatus,
    effective_status,
)

__all__ = [
    "ALL_STATUSES",
    "EFFECTIVE_STATUS_SQL",
    "STORED_STATUSES",
    "AnchorStatus",
    "effective_status",
]
