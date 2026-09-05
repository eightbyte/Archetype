"""The LLM provider layer (Phase 4).

``port.py`` is the interface: the normalized shapes, the closed vocabularies, and the
``LLMProvider`` protocol Phases 6 and 7 are written against. It is pure - pydantic and the
standard library, no I/O and no SDK.

``adapters/`` is the **only** place a provider SDK may be imported (specs/providers.md section 11,
phase-4-plan section 2 ruling 2). The rule is enforced by an import-graph test rather than
remembered, because an SDK type that escapes into a route is how "nothing above the port knows
which provider is in play" quietly stops being true.

This package exports the port and nothing else. Importing an adapter from here would put a
provider SDK on the import path of everything that touches the port, which is the same mistake the
anchors package refused when it kept ``AnchorStore`` out of its own ``__init__``.
"""

from __future__ import annotations

from .port import (
    PROVIDER_ERROR_CODES,
    ROLES,
    STOP_REASONS,
    STREAM_EVENT_TYPES,
    TOOL_CHOICES,
    Capabilities,
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    Message,
    ProviderError,
    ProviderErrorCode,
    Role,
    StopReason,
    StreamDelta,
    StreamDone,
    StreamError,
    StreamEvent,
    StreamStart,
    StreamUsage,
    ToolCall,
    ToolChoice,
    ToolDeclaration,
    Usage,
    parse_stream_event,
)

__all__ = [
    "PROVIDER_ERROR_CODES",
    "ROLES",
    "STOP_REASONS",
    "STREAM_EVENT_TYPES",
    "TOOL_CHOICES",
    "Capabilities",
    "CompletionRequest",
    "CompletionResult",
    "LLMProvider",
    "Message",
    "ProviderError",
    "ProviderErrorCode",
    "Role",
    "StopReason",
    "StreamDelta",
    "StreamDone",
    "StreamError",
    "StreamEvent",
    "StreamStart",
    "StreamUsage",
    "ToolCall",
    "ToolChoice",
    "ToolDeclaration",
    "Usage",
    "parse_stream_event",
]
