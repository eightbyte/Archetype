"""The registry - the **only** place a provider is constructed (P4-8, D34).

``specs/providers.md`` section 11. A caller receives an :class:`~archetype.llm.port.LLMProvider`
and never a class name; swapping provider is a settings change with no code change, which is one
of this phase's exit criteria and step 12 of its acceptance run.

Three rules, each a way this could go wrong quietly:

* **A key is read here and nowhere else, and it is read from settings** - which read it from the
  environment, because that is the only layer permitted to supply a ``SecretStr`` (D8, narrowed to
  the environment by P1-2 and made a decision by D34). Nothing in this module returns one, logs
  one, or puts one in an error message.
* **An unconfigured provider raises ``provider_unconfigured`` before any request is composed.**
  Not when the request is sent, and not as an empty answer - the writer is told which key is
  missing and where it comes from, which is what step 1 of section 8 checks.
* **A provider name this build has no adapter for breaks the assistant, never the app.** It is a
  plain string in settings rather than a ``Literal``, deliberately: a typo in one environment
  variable must not stop a writer from opening their manuscript, and the taxonomy already has the
  code for it.

This module is **not** exported from ``archetype.llm``. Importing it pulls httpx and both adapters
onto the path of everything that touches the port, which is the mistake the anchors package
refused when it kept ``AnchorStore`` out of its own ``__init__``.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from ..config import Settings
from .adapters.anthropic import DEFAULT_CAPABILITIES as ANTHROPIC_CAPABILITIES
from .adapters.anthropic import AnthropicAdapter
from .adapters.openai_compat import DEFAULT_CAPABILITIES as OPENAI_CAPABILITIES
from .adapters.openai_compat import OpenAICompatibleAdapter
from .port import Capabilities, LLMProvider, ProviderError

__all__ = [
    "PROVIDER_NAMES",
    "build_provider",
    "capabilities_from",
    "key_presence",
    "provider_status",
]

#: Every provider name this build has an adapter for. Closed, and asserted against the adapters
#: package by a test rather than kept in step with it by hand.
PROVIDER_NAMES: Final[tuple[str, ...]] = ("anthropic", "openai")

#: Which key each provider needs, by settings field name. The message a writer sees names the
#: environment variable, because "set a key" without saying which one is not help.
_KEY_FIELDS: Final[dict[str, str]] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
}


def capabilities_from(settings: Settings, defaults: Capabilities) -> Capabilities:
    """The adapter's own declaration, with anything settings actually say applied over it.

    ``max_context`` of ``0`` in settings means "leave the adapter's own answer alone" rather than
    "no context", which is what lets a writer raise the Anthropic adapter's deliberately
    conservative default without having to know what it was.
    """
    return Capabilities(
        native_tools=settings.llm_native_tools,
        streaming=settings.llm_streaming,
        supports_system=settings.llm_supports_system,
        max_context=settings.llm_max_context or defaults.max_context,
    )


def build_provider(settings: Settings, *, client: httpx.AsyncClient | None = None) -> LLMProvider:
    """Build the configured provider, or say why there is not one.

    ``client`` is injectable for the same reason it is on the adapters: the suite replays recorded
    payloads and opens no socket.

    Raises:
        ProviderError: ``provider_unconfigured`` - no provider selected, a name this build has no
            adapter for, or a provider whose key is not set.
    """
    name = (settings.llm_provider or "").strip().lower()
    if not name:
        raise _unconfigured(
            "no provider is selected. Set ARCHETYPE_LLM_PROVIDER to one of: "
            + ", ".join(PROVIDER_NAMES)
        )
    if name not in PROVIDER_NAMES:
        raise _unconfigured(
            f"there is no adapter for a provider called {name!r}. "
            "ARCHETYPE_LLM_PROVIDER must be one of: " + ", ".join(PROVIDER_NAMES)
        )

    key = _key_for(settings, name)
    if not key:
        raise _unconfigured(
            f"no API key is set for {name}. Set {_env_var_for(name)} in the environment and "
            "restart - keys are never read from a file this application wrote (D8, D34)."
        )

    if name == "anthropic":
        return AnthropicAdapter(
            api_key=key,
            base_url=settings.llm_base_url,
            capabilities=capabilities_from(settings, ANTHROPIC_CAPABILITIES),
            client=client,
        )
    return OpenAICompatibleAdapter(
        api_key=key,
        base_url=settings.llm_base_url,
        capabilities=capabilities_from(settings, OPENAI_CAPABILITIES),
        client=client,
        stream_usage=settings.llm_stream_usage,
    )


def provider_status(settings: Settings) -> dict[str, Any]:
    """What the settings screen may say about the provider - and nothing more (D34).

    **Whether a key is present, never the key**, never its length, and never its first characters.
    This lives here rather than in a route because it is the registry's knowledge of what it can
    build; routes carry no domain logic, and a second copy of "is this configured" in the API
    layer is the copy that would drift.
    """
    name = (settings.llm_provider or "").strip().lower()
    key_present = bool(_key_for(settings, name)) if name in PROVIDER_NAMES else False
    reason = ""
    try:
        build_provider(settings)
    except ProviderError as exc:
        reason = exc.message
    return {
        "provider": name,
        "known_providers": list(PROVIDER_NAMES),
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "max_tokens": settings.llm_max_tokens,
        "context_budget": settings.llm_context_budget,
        "key_present": key_present,
        "has_key": key_presence(settings),
        "key_env_var": _env_var_for(name) if name in PROVIDER_NAMES else "",
        "key_env_vars": {provider: _env_var_for(provider) for provider in PROVIDER_NAMES},
        "configured": not reason,
        "reason": reason,
    }


def key_presence(settings: Settings) -> dict[str, bool]:
    """Whether a key is set, **per provider** - and nothing else about it (P4-11, D34).

    The settings screen shows this so a writer can see that swapping to the other provider will
    work *before* they swap, which is the difference between a settings screen and a guess. It is
    a boolean per name and it is derived here, in the one module permitted to unwrap a key, so no
    caller ever has to touch one to find out whether it exists.
    """
    return {provider: bool(_key_for(settings, provider)) for provider in PROVIDER_NAMES}


def _key_for(settings: Settings, provider: str) -> str:
    """The configured key for a provider, as a plain string, at the one point it is unwrapped."""
    field = _KEY_FIELDS.get(provider)
    if field is None:
        return ""
    secret = getattr(settings, field, None)
    return secret.get_secret_value().strip() if secret is not None else ""


def _env_var_for(provider: str) -> str:
    field = _KEY_FIELDS.get(provider, "")
    return f"ARCHETYPE_{field.upper()}" if field else ""


def _unconfigured(message: str) -> ProviderError:
    return ProviderError("provider_unconfigured", message)
