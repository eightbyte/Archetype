"""Provider adapters - the **only** place a provider's wire format is known (P4-5, P4-6).

phase-4-plan section 2, ruling 2, and ``specs/providers.md`` section 11: no provider SDK is
imported outside this package. Not in a route, not in a store, not in a test that is not an
adapter test. An SDK type that escapes into a route is how "nothing above the port knows which
provider is in play" quietly stops being true, and it does not announce itself - the app goes on
working until the second provider is configured.

**This build uses no SDK at all.** ``specs/project-outline.md`` section 3 fixes LLM access as
*HTTP via httpx, one adapter per provider*, so the rule holds in a stronger form and is asserted
in both directions by ``tests/test_llm_port.py``: no ``anthropic`` or ``openai`` import above this
package, and no ``httpx`` import above it either. The transport is where the SDK would have been,
and it is fenced into the same place.

What lives here:

* ``transport.py`` - one httpx client, and the one place a status code or a dropped connection
  becomes a :class:`~archetype.llm.port.ProviderError`. Retries nothing, deliberately (ruling 6).
* ``sse.py`` - the framing both providers stream over, parsed once. Pure.
* ``prompted_tools.py`` - the prompted-JSON tool fallback (P4-7). Pure, and provider-agnostic: it
  is here because rendering a prompt and parsing a reply *is* translation.
* ``anthropic.py`` - the Messages API (P4-5).
* ``openai_compat.py`` - the chat-completions shape, for any server that speaks it (P4-6).

The two adapter classes are exported for the registry, which is the only thing that constructs one
(``llm/registry.py``, P4-8). They are deliberately **not** re-exported from ``archetype.llm``:
that package exports the port and nothing else, and putting an adapter in it would drag httpx onto
the import path of everything that touches the port - the mistake the anchors package refused when
it kept ``AnchorStore`` out of its own ``__init__``.
"""

from __future__ import annotations

from .anthropic import AnthropicAdapter
from .openai_compat import OpenAICompatibleAdapter

__all__ = ["AnthropicAdapter", "OpenAICompatibleAdapter"]
