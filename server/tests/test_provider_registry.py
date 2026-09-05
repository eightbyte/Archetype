"""P4-8 - provider configuration, the registry, the context budget, and the key that must not leak.

Three things are proved here, and each is one of Phase 4's exit criteria:

* **swapping provider is a settings change with no code change**, proved by building both adapters
  from configuration alone;
* **an unconfigured provider raises ``provider_unconfigured`` before any request is composed**,
  naming the environment variable the writer has to set;
* **no key reaches the browser**, proved by walking the whole API surface with a key configured
  and searching every response body for its value (D8, D34).

The budget lives here too, because it is what settings' ``llm_context_budget`` and an adapter's
declared window mean together, and because ``FakeProvider`` deliberately does not compute it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archetype.config import CONFIG_FILE_ENV_VAR, Settings
from archetype.llm.adapters.anthropic import AnthropicAdapter
from archetype.llm.adapters.openai_compat import OpenAICompatibleAdapter
from archetype.llm.budget import (
    check_budget,
    effective_budget,
    estimate_request_tokens,
    estimate_tokens,
)
from archetype.llm.port import Capabilities, CompletionRequest, Message, ProviderError
from archetype.llm.registry import PROVIDER_NAMES, build_provider, provider_status

from .conftest import replay

KEY = "sk-ant-a-key-that-must-never-leave-the-server"


def configured(**overrides: Any) -> Settings:
    """Settings as a writer's environment would produce them, with a real key set."""
    base: dict[str, Any] = {
        "web_dist": None,
        "llm_provider": "anthropic",
        "anthropic_api_key": KEY,
        "openai_api_key": "sk-openai-also-a-secret",
    }
    base.update(overrides)
    return Settings(**base)


def ask(text: str = "What happens here?", **overrides: Any) -> CompletionRequest:
    base: dict[str, Any] = {
        "messages": (Message(role="user", content=text),),
        "model": "a-model",
        "max_tokens": 256,
    }
    base.update(overrides)
    return CompletionRequest(**base)


# -- swapping provider is a settings change ---------------------------------------------------


def test_both_adapters_are_built_from_configuration_alone() -> None:
    """The exit criterion, and section 8's step 12 in one assertion."""
    assert isinstance(build_provider(configured(llm_provider="anthropic")), AnthropicAdapter)
    assert isinstance(build_provider(configured(llm_provider="openai")), OpenAICompatibleAdapter)


def test_the_registry_knows_exactly_the_providers_that_have_adapters() -> None:
    assert PROVIDER_NAMES == ("anthropic", "openai")
    for name in PROVIDER_NAMES:
        assert build_provider(configured(llm_provider=name)).name == name


def test_a_provider_name_is_read_case_insensitively_and_trimmed() -> None:
    """It comes out of an environment variable a person typed."""
    assert build_provider(configured(llm_provider=" Anthropic ")).name == "anthropic"


@pytest.mark.parametrize(
    ("settings_kwargs", "expected_in_message"),
    [
        ({"llm_provider": ""}, "no provider is selected"),
        ({"llm_provider": "gemini"}, "no adapter for a provider called 'gemini'"),
    ],
)
def test_an_unconfigured_provider_is_refused_before_anything_is_composed(
    settings_kwargs: dict[str, Any], expected_in_message: str
) -> None:
    with pytest.raises(ProviderError) as raised:
        build_provider(configured(**settings_kwargs))
    assert raised.value.code == "provider_unconfigured"
    assert expected_in_message in raised.value.message


def test_a_missing_key_names_the_environment_variable_that_supplies_it() -> None:
    """Section 8's step 1: it refuses, and it says where a key comes from."""
    with pytest.raises(ProviderError) as raised:
        build_provider(Settings(web_dist=None, llm_provider="anthropic"))
    assert raised.value.code == "provider_unconfigured"
    assert "ARCHETYPE_ANTHROPIC_API_KEY" in raised.value.message


def test_an_empty_key_is_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ARCHETYPE_ANTHROPIC_API_KEY=`` in a shell is how a writer turns one off."""
    monkeypatch.setenv("ARCHETYPE_ANTHROPIC_API_KEY", "   ")
    with pytest.raises(ProviderError) as raised:
        build_provider(Settings(web_dist=None, llm_provider="anthropic"))
    assert raised.value.code == "provider_unconfigured"


def test_a_provider_name_this_build_cannot_serve_breaks_the_assistant_and_not_the_app() -> None:
    """Which is why ``llm_provider`` is a plain string and not a Literal: a typo in one
    environment variable must not stop a writer from opening their manuscript."""
    settings = configured(llm_provider="gemeni")
    assert settings.llm_provider == "gemeni", "settings still build"
    assert create_client(settings).get("/api/health").status_code == 200


# -- what settings actually reach ---------------------------------------------------------------


async def test_the_base_url_from_settings_is_where_the_request_goes() -> None:
    client, calls = replay(json_body={"content": [], "stop_reason": "end_turn"})
    settings = configured(llm_base_url="http://127.0.0.1:11434/anthropic")
    try:
        await build_provider(settings, client=client).complete(ask())
    finally:
        await client.aclose()
    assert str(calls.last.url) == "http://127.0.0.1:11434/anthropic/v1/messages"


def test_the_capability_flags_are_configuration_and_reach_the_adapter() -> None:
    provider = build_provider(
        configured(
            llm_provider="openai",
            llm_native_tools=False,
            llm_streaming=False,
            llm_supports_system=False,
            llm_max_context=8192,
        )
    )
    assert provider.capabilities == Capabilities(
        native_tools=False, streaming=False, supports_system=False, max_context=8192
    )


def test_an_unset_max_context_leaves_the_adapter_s_own_declaration_alone() -> None:
    """Zero means "the adapter knows better than this setting does", which is what lets a writer
    raise the Anthropic adapter's deliberately conservative default without knowing what it was."""
    assert build_provider(configured()).capabilities.max_context == 200_000
    assert build_provider(configured(llm_provider="openai")).capabilities.max_context == 0


# -- the status the settings screen may show (D34) ----------------------------------------------


def test_the_status_says_a_key_is_present_and_never_anything_about_it() -> None:
    status = provider_status(configured())
    assert status["key_present"] is True
    assert status["configured"] is True
    assert status["key_env_var"] == "ARCHETYPE_ANTHROPIC_API_KEY"
    rendered = json.dumps(status)
    assert KEY not in rendered
    assert KEY[:8] not in rendered, "not its prefix either"
    assert str(len(KEY)) not in rendered, "and not its length"


def test_the_status_of_an_unconfigured_provider_carries_the_reason() -> None:
    status = provider_status(Settings(web_dist=None, llm_provider="anthropic"))
    assert status["key_present"] is False
    assert status["configured"] is False
    assert "ARCHETYPE_ANTHROPIC_API_KEY" in status["reason"]


# -- the key must not leave the server (D8, D34) ------------------------------------------------


def create_client(settings: Settings) -> TestClient:
    from archetype.app import create_app

    app: FastAPI = create_app(settings)
    return TestClient(app, raise_server_exceptions=False)


def test_no_key_appears_anywhere_in_the_whole_api_surface(data_dir: Path) -> None:
    """Exit criterion 9, by walking every route rather than by checking the ones we thought of.

    Most of these answer 404 or 422 against a placeholder id, and that is fine: what is being
    asserted is the **absence** of a string, and a route that refuses a request still writes a
    body. A route added later is covered without anyone remembering, which is the whole point of
    walking the schema instead of listing paths.
    """
    settings = configured(data_dir=data_dir)
    client = create_client(settings)
    client.post("/api/projects", json={"title": "A Manuscript"})

    paths = client.app.openapi()["paths"]
    checked = 0
    for path, operations in paths.items():
        concrete = path
        for segment in path.split("/"):
            if segment.startswith("{") and segment.endswith("}"):
                concrete = concrete.replace(segment, "prj_placeholder0")
        for method in operations:
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            response = client.request(method.upper(), concrete, json={})
            body = response.content.decode("utf-8", "replace")
            assert KEY not in body, f"{method.upper()} {concrete} leaked a key"
            assert "sk-openai-also-a-secret" not in body
            checked += 1
    assert checked > 20, "the walk must actually have walked something"


def test_the_settings_object_itself_still_refuses_to_render_a_key() -> None:
    settings = configured()
    for rendering in (
        settings.model_dump_json(),
        json.dumps(settings.public_dump()),
        repr(settings),
        str(settings),
    ):
        assert KEY not in rendering


def test_a_provider_key_cannot_be_supplied_by_config_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-2's narrowing of D8, now against a key the application would actually use."""
    config = tmp_path / "config.yaml"
    config.write_text(
        f"anthropic_api_key: {KEY}\nllm_model: a-model-from-a-file\n", encoding="utf-8"
    )
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(config))

    settings = Settings(web_dist=None)
    assert settings.anthropic_api_key is None
    assert settings.llm_model == "a-model-from-a-file", "non-secret keys in the same file load"


def test_a_key_read_from_the_environment_is_the_one_that_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHETYPE_ANTHROPIC_API_KEY", KEY)
    provider = build_provider(Settings(web_dist=None, llm_provider="anthropic"))
    assert provider._transport.headers["x-api-key"] == KEY  # noqa: SLF001 - the point of the test


# -- the context budget (ruling 7) ---------------------------------------------------------------


def test_the_estimate_is_conservative_rather_than_accurate() -> None:
    """It over-counts on purpose: refusing a request that would have fitted costs nothing and is
    fixed in one gesture, and sending one that does not is billed and then rejected."""
    text = "x" * 350
    assert estimate_tokens(text) == 100
    assert estimate_tokens("") == 0


def test_a_request_is_estimated_from_everything_that_is_actually_sent() -> None:
    plain = estimate_request_tokens(ask("a" * 700))
    assert plain >= 200
    with_tools = estimate_request_tokens(
        ask(
            "a" * 700,
            tools=(
                {
                    "name": "read_bible_entry",
                    "description": "Read one entry.",
                    "parameters": {"type": "object"},
                },
            ),
        )
    )
    assert with_tools > plain, "declarations are sent on every request whether or not one is used"


def test_the_effective_budget_is_the_smaller_of_the_two_that_were_declared() -> None:
    assert effective_budget(Capabilities(max_context=200_000), 100_000) == 100_000
    assert effective_budget(Capabilities(max_context=8_192), 100_000) == 8_192


def test_an_undeclared_window_leaves_the_writer_s_own_budget_standing() -> None:
    """Zero means *not declared*, which is the honest answer for a server we have never met. A
    literal minimum with zero would refuse every request ever composed."""
    assert effective_budget(Capabilities(max_context=0), 100_000) == 100_000
    assert effective_budget(Capabilities(max_context=0), 0) == 0


def test_an_over_long_request_is_refused_naming_what_was_too_big() -> None:
    with pytest.raises(ProviderError) as raised:
        check_budget(ask("a" * 40_000), Capabilities(max_context=0), 1_000, provider="anthropic")
    assert raised.value.code == "context_too_large"
    assert "budget of 1,000" in raised.value.message
    assert raised.value.detail["budget"] == 1_000
    assert raised.value.detail["estimated_input_tokens"] > 1_000


def test_the_answer_s_own_ceiling_counts_against_the_budget() -> None:
    """A composed context that fits with no room for a reply does not fit."""
    request = ask("a" * 350, max_tokens=4_000)
    check_budget(request, Capabilities(max_context=0), 8_000)
    with pytest.raises(ProviderError):
        check_budget(request, Capabilities(max_context=0), 4_050)


def test_a_budget_of_zero_everywhere_refuses_nothing() -> None:
    """Turning the check off is a thing a writer may do, and it leaves the provider's own refusal
    as the only guard - which is a stated cause too, just a billed one."""
    assert check_budget(ask("a" * 40_000), Capabilities(max_context=0), 0) > 0
