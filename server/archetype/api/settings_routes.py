"""The settings surface - the first route in this project that returns a setting (P4-11, D34).

api-contract listed "any route returning a setting" as absent from Phase 1 until this landed, with
one qualification: *never for secrets (D8); ``Settings.public_dump`` is the only sanctioned shape
if one is ever needed*. This is that need, and this module keeps that qualification exactly.

**The key stays environment-only and this surface is read-only about it** (D34, narrowing D8).
``GET`` reports *whether* a key is present, per provider, and never its value, its length, or its
first characters. ``PATCH`` refuses a secret-valued field **by name**, with a message saying where
keys come from, and the function that writes the file refuses one a second time
(:func:`archetype.config.write_config_values`) - because a guard at the edge protects one route
and a guard at the write protects every caller there will ever be.

What ``PATCH`` may write is the **provider block and nothing else**. ``data_dir``, ``host``,
``port``, ``log_level``, and ``web_dist`` are process-level: this application resolves its
projects directory and installs its static mount once, at startup, so a route that changed one of
them would leave a running server whose settings describe something it is not doing. They stay
readable, and they are changed the way they always have been - the environment, or the file, and a
restart (deviation ``C4``).

Its shapes live in this file rather than in a fourth ``*_schemas.py``. Two routes and four models
is not a module's worth of wire shapes, and splitting sixty lines across two files makes a reader
open both to learn one thing.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, Request
from pydantic import Field, model_validator

from ..config import Settings, config_file_path, write_config_values
from ..llm.registry import PROVIDER_NAMES, provider_status
from .errors import error_responses
from .schemas import Wire

__all__ = ["WRITABLE_SETTINGS", "router"]

router = APIRouter(prefix="/api")

#: What ``PATCH /api/settings`` may write. The provider block, closed, and in the order the
#: settings screen shows it. Everything else on :class:`~archetype.config.Settings` is readable
#: and not writable - see the module docstring for why.
WRITABLE_SETTINGS: Final[tuple[str, ...]] = (
    "llm_provider",
    "llm_base_url",
    "llm_model",
    "llm_max_tokens",
    "llm_context_budget",
    "llm_native_tools",
    "llm_streaming",
    "llm_supports_system",
    "llm_max_context",
    "llm_stream_usage",
)


class SettingsOut(Wire):
    """Every non-secret setting, mirrored field for field from :class:`Settings`.

    Built by splatting :meth:`Settings.public_dump` into a model that ``forbid``s extra fields, so
    a setting added later and not declared here **fails loudly** rather than quietly going
    unserved. A test asserts the two key sets are identical, which is where that failure is meant
    to be found; the strictness is what makes the test able to find it.
    """

    data_dir: str
    host: str
    port: int
    log_level: str
    web_dist: str | None
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_max_tokens: int
    llm_context_budget: int
    llm_native_tools: bool
    llm_streaming: bool
    llm_supports_system: bool
    llm_max_context: int
    llm_stream_usage: bool

    @classmethod
    def of(cls, settings: Settings) -> SettingsOut:
        return cls(**settings.public_dump())


class ProviderStatusOut(Wire):
    """What the registry knows about what it can build - and nothing more (D34).

    ``has_key`` is the per-provider presence map: a boolean each, so the screen can tell the
    writer that swapping to the other provider will work *before* they swap. ``key_env_var`` names
    where the current provider's key comes from, because "set a key" without saying which one is
    not help. Neither carries a key, a length, or a prefix.

    ``reason`` is the registry's own sentence when nothing can be built, so the settings screen and
    the chat panel say the same thing about the same condition.
    """

    provider: str
    known_providers: list[str]
    model: str
    base_url: str
    max_tokens: int
    context_budget: int
    key_present: bool
    has_key: dict[str, bool]
    key_env_var: str
    key_env_vars: dict[str, str]
    configured: bool
    reason: str

    @classmethod
    def of(cls, settings: Settings) -> ProviderStatusOut:
        return cls(**provider_status(settings))


class SettingsDocumentOut(Wire):
    """``GET /api/settings`` and the body of a successful ``PATCH``.

    ``writable`` is served rather than assumed, so the screen renders inputs from the server's
    own list and a field that stops being writable stops being editable in the same commit.
    ``config_file`` is where a ``PATCH`` lands - a local path, on a loopback-only API (D7), and
    the answer to the question a writer asks first when a setting does not stick.
    """

    settings: SettingsOut
    provider: ProviderStatusOut
    writable: list[str]
    config_file: str

    @classmethod
    def of(cls, settings: Settings) -> SettingsDocumentOut:
        return cls(
            settings=SettingsOut.of(settings),
            provider=ProviderStatusOut.of(settings),
            writable=list(WRITABLE_SETTINGS),
            config_file=str(config_file_path()),
        )


class SettingsPatchIn(Wire):
    """The provider block, every field optional.

    An absent field and a field sent empty are different requests, and the difference is read from
    pydantic's ``model_fields_set`` exactly as ``EntryUpdateIn.changes()`` reads it (P3-9): a
    ``PATCH`` that does not mention ``llm_base_url`` leaves it alone, and one that sends it as
    ``""`` clears it back to the adapter's own default.

    Each constraint is written here as well as on :class:`Settings`, and a test holds the two
    spellings together field by field - the same discipline ``AnchorStatusFilter`` is held to. The
    **defaults** are held together too, even though a default here is unreachable: only presented
    fields are ever applied. Two shapes that differ in a way nothing reads are two shapes a reader
    has to check, and a difference that means nothing today is one somebody will read as meaning
    something tomorrow.
    """

    llm_provider: str = "anthropic"
    llm_base_url: str = ""
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = Field(default=4096, ge=1)
    llm_context_budget: int = Field(default=100_000, ge=0)
    llm_native_tools: bool = True
    llm_streaming: bool = True
    llm_supports_system: bool = True
    llm_max_context: int = Field(default=0, ge=0)
    llm_stream_usage: bool = True

    @model_validator(mode="before")
    @classmethod
    def _refuse_a_secret_by_name(cls, data: Any) -> Any:
        """The first of two refusals (D34).

        It runs **before** the ``extra="forbid"`` check so that offering a key gets a sentence
        about where keys come from rather than "extra inputs are not permitted" - the writer who
        tries this is doing the reasonable thing, and the answer has to tell them what to do
        instead.
        """
        if isinstance(data, dict):
            offered = sorted(set(data) & Settings.secret_fields())
            if offered:
                names = ", ".join(offered)
                raise ValueError(
                    f"{names} may not be set through the API. An API key comes from the "
                    "environment only - set ARCHETYPE_ANTHROPIC_API_KEY or "
                    "ARCHETYPE_OPENAI_API_KEY and restart (D8, D34)."
                )
        return data

    @model_validator(mode="after")
    def _known_provider(self) -> SettingsPatchIn:
        """A provider name this build cannot serve is refused **here**, and only here.

        :class:`Settings` keeps ``llm_provider`` a plain string on purpose, so that a typo in an
        environment variable breaks the assistant and never the application. That tolerance is
        about a value arriving from outside; a value this application is about to *write to a
        file* is different, and storing one that can never work would be writing a fault to disk.
        """
        if "llm_provider" in self.model_fields_set and self.llm_provider not in PROVIDER_NAMES:
            raise ValueError(
                f"there is no adapter for a provider called {self.llm_provider!r}; "
                "expected one of: " + ", ".join(PROVIDER_NAMES)
            )
        return self

    def changes(self) -> dict[str, Any]:
        """Only the fields this request actually presented."""
        return {name: getattr(self, name) for name in sorted(self.model_fields_set)}


@router.get(
    "/settings",
    tags=["settings"],
    summary="Every non-secret setting, and what the provider layer can build",
    response_model=SettingsDocumentOut,
)
def get_settings_document(request: Request) -> SettingsDocumentOut:
    """The settings as they are in force right now, with every secret stripped twice."""
    return SettingsDocumentOut.of(request.app.state.settings)


@router.patch(
    "/settings",
    tags=["settings"],
    summary="Change a provider setting",
    response_model=SettingsDocumentOut,
    responses=error_responses(422),
)
def patch_settings(request: Request, body: SettingsPatchIn) -> SettingsDocumentOut:
    """Write the presented fields to ``config.yaml`` and put them in force immediately.

    Two things a reader should not have to discover by experiment:

    * **An empty body writes nothing at all.** No file is created, no timestamp moves. A no-op
      request is a no-op.
    * **The environment still wins.** These settings layer defaults < ``config.yaml`` <
      ``ARCHETYPE_*`` (P1-2), and this route writes the middle layer. A field also set in the
      environment is written to the file and then overridden by the shell on the next start - so
      the response reports what is **actually in force**, which is how the writer finds out.
    """
    changes = body.changes()
    if not changes:
        return SettingsDocumentOut.of(request.app.state.settings)

    write_config_values(changes)
    # Copied onto the settings in force rather than rebuilt from the layers. Rebuilding would
    # re-resolve every source and discard anything this process was constructed with - which the
    # suite relies on for its temporary data directory, and which a future embedded caller would
    # rely on for the same reason. The values are already validated: they arrived through a model
    # carrying the same constraints Settings does, and a test holds the two spellings together.
    updated = request.app.state.settings.model_copy(update=changes)
    request.app.state.settings = updated
    return SettingsDocumentOut.of(updated)
