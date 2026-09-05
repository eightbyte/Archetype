"""The context budget - a hard refusal, not a truncation (P4-8, plan section 2 ruling 7).

``specs/providers.md`` section 7 in code. A request whose composed context exceeds the effective
budget is **refused** with ``context_too_large`` naming what was too big, and nothing is silently
dropped. Truncation is how a continuity answer comes back confidently wrong, because the half of
the chapter that contradicted it was the half that got cut; a writer narrowing their selection is
a correct and cheap fix, and a quiet cut is neither.

Two properties this module has on purpose:

* **It is pure**, so it sits in ``llm/`` rather than ``llm/adapters/``: no HTTP client, no
  settings object, no provider. It takes a request, a capability, and a number.
* **It never asks a provider to count.** The estimate is ours and it runs *before* the call - a
  token count that required a request would spend the money the check exists to protect. ``Usage``
  after the fact is the provider's true number, and the two will differ, which section 7 says in
  as many words so that a reader who notices does not report it as a bug.

The estimate is deliberately **conservative**: it over-counts, so the refusal lands slightly
before the provider's own would. Refusing a request that would have fitted costs nothing and is
fixed in one gesture; sending one that does not is billed and then rejected.
"""

from __future__ import annotations

import math
from typing import Final

from .port import Capabilities, CompletionRequest, ProviderError

__all__ = [
    "CHARS_PER_TOKEN",
    "PER_MESSAGE_OVERHEAD",
    "check_budget",
    "effective_budget",
    "estimate_request_tokens",
    "estimate_tokens",
]

#: Characters per token, over English prose. Real tokenizers average nearer four; three and a half
#: is the conservative direction, and this is an estimate rather than a measurement by design.
CHARS_PER_TOKEN: Final[float] = 3.5

#: What the framing round a message costs - a role, a separator, whatever a provider wraps it in.
#: Small, and it stops a conversation of two hundred short turns from estimating as nearly free.
PER_MESSAGE_OVERHEAD: Final[int] = 4


def estimate_tokens(text: str) -> int:
    """A conservative token estimate for a piece of text."""
    if not text:
        return 0
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_request_tokens(req: CompletionRequest) -> int:
    """What a whole request is likely to cost on the way in.

    The tool declarations are counted too: they are sent on every request, and a Phase 6 agent
    with a dozen tools declared carries a real prompt whether or not it calls one.
    """
    total = 0
    for message in req.messages:
        total += PER_MESSAGE_OVERHEAD + estimate_tokens(message.content)
        for call in message.tool_calls:
            total += estimate_tokens(call.name) + estimate_tokens(str(call.arguments))
    for tool in req.tools:
        total += estimate_tokens(tool.name) + estimate_tokens(tool.description)
        total += estimate_tokens(str(tool.parameters))
    return total


def effective_budget(capabilities: Capabilities, configured: int) -> int:
    """``min(max_context, llm_context_budget)`` - over the values that were actually declared.

    ``max_context`` of ``0`` means **not declared**, which is what the OpenAI-compatible adapter
    says by default because the server on the other end is deliberately unknown. Taking a literal
    minimum with zero would refuse every request ever composed, so an undeclared window simply
    leaves the writer's own budget standing.
    """
    declared = [value for value in (capabilities.max_context, configured) if value > 0]
    return min(declared) if declared else 0


def check_budget(
    req: CompletionRequest,
    capabilities: Capabilities,
    configured: int,
    *,
    provider: str = "",
) -> int:
    """Refuse an over-long request before it is sent, and return the estimate when it fits.

    Raises:
        ProviderError: ``context_too_large``, naming the estimate and the budget it exceeded.
    """
    estimate = estimate_request_tokens(req)
    budget = effective_budget(capabilities, configured)
    if budget and estimate + req.max_tokens > budget:
        raise ProviderError(
            "context_too_large",
            f"the composed context is about {estimate:,} tokens and the answer may run to "
            f"{req.max_tokens:,} more, against a budget of {budget:,}. Nothing was sent - "
            f"select less, or raise the budget in settings.",
            provider=provider,
            detail={
                "estimated_input_tokens": estimate,
                "max_tokens": req.max_tokens,
                "budget": budget,
                "provider_max_context": capabilities.max_context,
                "configured_budget": configured,
            },
        )
    return estimate
