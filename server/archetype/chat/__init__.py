"""Where a chat lives (P4-9, D30).

A conversation is project-scoped like everything else (D6), soft-deleted like everything else
(D22, D25), and stored in its own two tables rather than in Phase 6's ``run`` shape. **A Phase 4
turn is not a run**: a run is what will one day *produce* one assistant turn, and it will
reference the message this package stores rather than replace it.

The package holds storage and nothing else. Composing what a model is given is
:mod:`archetype.llm.context`, and talking to one is :mod:`archetype.llm` - neither is imported
from here, so a conversation can be read, listed, and restored with no provider configured at all.
"""

from __future__ import annotations

from .conversations import (
    ChatMessage,
    Conversation,
    ConversationNotFoundError,
    ConversationStore,
)

__all__ = [
    "ChatMessage",
    "Conversation",
    "ConversationNotFoundError",
    "ConversationStore",
]
