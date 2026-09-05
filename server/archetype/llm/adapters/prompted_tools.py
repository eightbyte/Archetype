"""The prompted-JSON tool fallback (P4-7, D31).

For a provider with no tool-calling API. The declarations are rendered into the system prompt, the
model's JSON is parsed back out of the reply, and it is presented at the port as ordinary
``tool_calls`` - **so nothing above the port can tell the difference, which is the entire
requirement** (``specs/providers.md`` section 8).

It is built here and used in Phase 6. Phase 4 declares no tools and calls none; the recorded
fixtures and this module's own corpus are its only consumers until the agent arrives, which is the
mitigation D31 was ruled on and the risk it knowingly takes.

Three rules, each of which is a way this could quietly lie:

* **A parse failure is ``provider_refused`` with the raw text preserved, never a silently empty
  tool call.** A model that meant to call a tool and produced JSON we could not read has not
  called no tools - it has failed, and the caller must be able to see the reply that failed.
* **A reply that calls no tool is not a failure.** The marker is what separates the two: a reply
  with no ``"tool_calls"`` in it never wanted to call anything, and a reply that has the marker
  and will not parse did.
* **Ids are minted positionally.** ``call_0``, ``call_1``, in the order the model wrote them. An
  id pairs a call with its result *inside one turn* and means nothing outside it, so a position is
  a complete identity - and it makes a fallback reply reproducible, which a random token would
  not. Nothing above the port may assume an id's shape (section 8, rule 3).

**Pure.** The standard library and the port. It lives in ``adapters/`` because rendering a prompt
and parsing a reply is translation, and translation is what an adapter is for - not because it
touches a provider, which it does not.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from ..port import ProviderError, StopReason, ToolCall, ToolDeclaration

__all__ = [
    "TOOL_CALL_MARKER",
    "ParsedReply",
    "apply_fallback",
    "extract_tool_calls",
    "system_instructions",
]

#: What the model is asked to write, and what tells this module the model tried to. A reply with
#: no marker called no tool; a reply with the marker that will not parse is a refusal.
TOOL_CALL_MARKER: Final[str] = '"tool_calls"'

_INSTRUCTIONS_HEADER: Final[str] = (
    "You have access to the tools below. To call one, reply with a single JSON object and "
    "nothing else:\n"
    '{"tool_calls": [{"name": "<tool name>", "arguments": {<arguments>}}]}\n'
    "Call more than one tool by putting more than one object in the list. If no tool is needed, "
    "answer normally and do not mention this format.\n\n"
    "Tools:"
)


def system_instructions(tools: tuple[ToolDeclaration, ...]) -> str:
    """The system-prompt section that stands in for a tools parameter.

    Returns ``""`` for no tools, so a caller can concatenate unconditionally and a provider with
    nothing declared sees a prompt with nothing added to it.
    """
    if not tools:
        return ""
    lines = [_INSTRUCTIONS_HEADER]
    for tool in tools:
        schema = json.dumps(tool.parameters, sort_keys=True)
        description = tool.description or "(no description)"
        lines.append(f"- {tool.name}: {description}\n  arguments schema: {schema}")
    return "\n".join(lines)


class ParsedReply:
    """What a reply turned out to be: the calls it made, and the words that were not them."""

    __slots__ = ("text", "tool_calls")

    def __init__(self, text: str, tool_calls: tuple[ToolCall, ...]) -> None:
        self.text = text
        self.tool_calls = tool_calls

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"ParsedReply(text={self.text!r}, tool_calls={self.tool_calls!r})"


def extract_tool_calls(text: str, *, provider: str = "") -> ParsedReply:
    """Read a reply written to the envelope above.

    Raises:
        ProviderError: ``provider_refused``, when the reply says it is calling a tool and the JSON
            cannot be read as one. ``detail`` carries the raw text.
    """
    if TOOL_CALL_MARKER not in text:
        return ParsedReply(text, ())

    found = _find_envelope(text)
    if found is None:
        raise _refusal(
            "the reply said it was calling a tool but no JSON object could be read out of it",
            text,
            provider,
        )
    envelope, start, end = found

    raw_calls = envelope.get("tool_calls")
    if not isinstance(raw_calls, list):
        raise _refusal("the reply's `tool_calls` was not a list", text, provider)

    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        if not isinstance(raw, dict):
            raise _refusal(f"tool call {index} was not an object", text, provider)
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise _refusal(f"tool call {index} named no tool", text, provider)
        arguments = raw.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise _refusal(
                f"tool call {index} had arguments that were not an object", text, provider
            )
        calls.append(ToolCall(id=f"call_{index}", name=name, arguments=arguments))

    remainder = _drop_trailing_fence(text[:start]) + _drop_leading_fence(text[end:])
    return ParsedReply(remainder.strip(), tuple(calls))


def apply_fallback(
    text: str, stop_reason: StopReason, *, provider: str = ""
) -> tuple[str, tuple[ToolCall, ...], StopReason]:
    """Read a reply and report it as a native provider would have.

    Written once and called by both adapters, because P4-7's bar is that a native path and a
    fallback path produce **identical** normalised calls - and two copies of "and then set the
    stop reason" is exactly how the two would come to differ by one field.

    ``stop_reason`` becomes ``tool_use`` when a call was found, because that is what happened;
    ``raw_stop_reason`` is the caller's to keep, and it keeps the provider's own word (``stop``,
    ``end_turn``) untouched. That pairing is the whole record of a fallback having been used, and
    it is deliberately not a flag: nothing above the port may branch on it (section 8, rule 2).
    """
    parsed = extract_tool_calls(text, provider=provider)
    if not parsed.tool_calls:
        return text, (), stop_reason
    return parsed.text, parsed.tool_calls, "tool_use"


def _find_envelope(text: str) -> tuple[dict[str, Any], int, int] | None:
    """The first ``{...}`` in the reply that parses and carries ``tool_calls``.

    Scanning for a balanced object rather than matching a fence: a model puts its JSON inside
    ```` ```json ````, inside a bare fence, or with a sentence either side of it, and all three
    are the same object with different decoration. ``raw_decode`` is what makes "the JSON stops
    here" the decoder's answer instead of a bracket-counting guess of ours.
    """
    decoder = json.JSONDecoder()
    position = 0
    while True:
        start = text.find("{", position)
        if start == -1:
            return None
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            position = start + 1
            continue
        if isinstance(value, dict) and "tool_calls" in value:
            return value, start, end
        position = max(end, start + 1)


#: The fence a model wraps its JSON in, on either side of the object that was just removed. Only
#: an *empty* one is dropped - the pattern is anchored at the cut, so a fenced code block
#: elsewhere in the reply is left exactly as the model wrote it.
_TRAILING_FENCE: Final[re.Pattern[str]] = re.compile(r"\s*```[A-Za-z0-9_+-]*\s*$")
_LEADING_FENCE: Final[re.Pattern[str]] = re.compile(r"^\s*```\s*")


def _drop_trailing_fence(before: str) -> str:
    """The fence opener the extracted object was sitting inside, if it was."""
    return _TRAILING_FENCE.sub("", before)


def _drop_leading_fence(after: str) -> str:
    """And its closer."""
    return _LEADING_FENCE.sub("", after)


def _refusal(reason: str, text: str, provider: str) -> ProviderError:
    return ProviderError(
        "provider_refused",
        f"a prompted tool call could not be read: {reason}",
        provider=provider,
        detail={"raw_text": text},
    )
