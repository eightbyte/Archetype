"""The settings surface (P4-11, D34) - the first route in this project that returns a setting.

Three claims, and they are the item's own *done when*:

* **a configured key is provably absent from the response**, asserted by searching the serialized
  body for the key's own value rather than by checking the fields somebody thought of;
* **``PATCH`` refuses every ``SecretStr`` field by name**, with a message that says where keys
  come from - because the writer who tries it is doing the reasonable thing;
* **an invalid provider name is a ``422``** rather than a broken app on the next request.

And one that is not in the item's text but is what keeps the shape honest: the served settings and
:meth:`Settings.public_dump` have **identical key sets**, so a setting added later cannot go
quietly unserved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from archetype.api.errors import PROVIDER_ERROR_STATUS, provider_error_status
from archetype.api.settings_routes import WRITABLE_SETTINGS, SettingsOut, SettingsPatchIn
from archetype.app import create_app
from archetype.config import CONFIG_FILE_ENV_VAR, Settings
from archetype.llm.port import PROVIDER_ERROR_CODES, ProviderError

KEY = "sk-ant-not-a-real-key-0123456789"
OTHER_KEY = "sk-openai-also-not-real-9876543210"


@pytest.fixture
def keyed_client(data_dir: Path) -> TestClient:
    """An application with both keys configured, exactly as an environment would supply them."""
    settings = Settings(
        data_dir=data_dir,
        web_dist=None,
        anthropic_api_key=SecretStr(KEY),
        openai_api_key=SecretStr(OTHER_KEY),
    )
    app: FastAPI = create_app(settings)
    return TestClient(app, raise_server_exceptions=False)


# -- what it serves ------------------------------------------------------------------------------


def test_the_served_settings_are_exactly_the_non_secret_ones(client: TestClient) -> None:
    """A setting added and not declared on the wire must fail here, not go unnoticed."""
    body = client.get("/api/settings").json()
    settings = Settings(data_dir=Path("."), web_dist=None)

    assert set(body["settings"]) == set(settings.public_dump())
    assert set(SettingsOut.model_fields) == set(settings.public_dump())


def test_no_key_reaches_the_browser(keyed_client: TestClient) -> None:
    """Exit criterion 9, on the one route that exists to talk about keys."""
    response = keyed_client.get("/api/settings")
    body = response.text

    assert KEY not in body
    assert OTHER_KEY not in body
    assert "anthropic_api_key" not in json.dumps(response.json()["settings"])


def test_the_screen_is_told_whether_a_key_is_present_and_nothing_more(
    keyed_client: TestClient,
) -> None:
    """D34: whether one is present, never its value, its length, or its first characters."""
    provider = keyed_client.get("/api/settings").json()["provider"]

    assert provider["has_key"] == {"anthropic": True, "openai": True}
    assert provider["key_present"] is True
    assert provider["key_env_var"] == "ARCHETYPE_ANTHROPIC_API_KEY"
    assert provider["configured"] is True
    assert provider["reason"] == ""
    assert str(len(KEY)) not in json.dumps(provider)


def test_with_no_key_the_screen_is_told_which_one_is_missing(client: TestClient) -> None:
    provider = client.get("/api/settings").json()["provider"]

    assert provider["has_key"] == {"anthropic": False, "openai": False}
    assert provider["configured"] is False
    assert "ARCHETYPE_ANTHROPIC_API_KEY" in provider["reason"]


def test_the_writable_list_is_served_rather_than_assumed(client: TestClient) -> None:
    """The screen renders inputs from the server's list, so the two cannot fall out of step."""
    body = client.get("/api/settings").json()

    assert body["writable"] == list(WRITABLE_SETTINGS)
    assert all(name.startswith("llm_") for name in body["writable"])
    for process_level in ("data_dir", "host", "port", "web_dist", "log_level"):
        assert process_level not in body["writable"]


# -- what it writes ------------------------------------------------------------------------------


def test_a_patch_takes_effect_immediately_and_lands_in_the_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """P4-15: changing a provider takes effect on the next request, with no reload and no
    restart - and the file is where it persists to."""
    config = tmp_path / "written-config.yaml"
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(config))

    response = client.patch(
        "/api/settings", json={"llm_provider": "openai", "llm_model": "gpt-4o-mini"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["llm_provider"] == "openai"
    assert response.json()["provider"]["provider"] == "openai"

    assert yaml.safe_load(config.read_text(encoding="utf-8")) == {
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
    }
    # The next request sees it, without a restart.
    assert client.get("/api/settings").json()["settings"]["llm_model"] == "gpt-4o-mini"


def test_a_patch_that_presents_nothing_writes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An absent field and a field sent empty are different requests (the P3-9 rule)."""
    config = tmp_path / "untouched.yaml"
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(config))

    assert client.patch("/api/settings", json={}).status_code == 200
    assert not config.exists()


def test_a_field_sent_empty_clears_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(tmp_path / "cleared.yaml"))
    client.patch("/api/settings", json={"llm_base_url": "http://localhost:1234/v1"})

    body = client.patch("/api/settings", json={"llm_base_url": ""}).json()
    assert body["settings"]["llm_base_url"] == ""


def test_a_secret_is_refused_by_name_and_told_where_keys_come_from(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D34, at the edge. The second refusal is in ``write_config_values`` and has its own test."""
    config = tmp_path / "never-written.yaml"
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(config))

    for field in sorted(Settings.secret_fields()):
        response = client.patch("/api/settings", json={field: "sk-please-store-this"})
        assert response.status_code == 422
        detail = json.dumps(response.json()["error"]["detail"])
        assert field in detail
        assert "environment only" in detail
    assert not config.exists()
    assert "sk-please-store-this" not in json.dumps(client.get("/api/settings").json())


def test_a_provider_this_build_cannot_serve_is_a_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Refused *here* and nowhere else: Settings stays tolerant so a typo in the environment
    breaks the assistant and never the application, but a value about to be written to a file is
    a different thing - storing one that can never work is writing a fault to disk."""
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(tmp_path / "not-written.yaml"))

    response = client.patch("/api/settings", json={"llm_provider": "gemini"})
    assert response.status_code == 422
    assert "no adapter" in json.dumps(response.json()["error"]["detail"])

    # And the application is entirely undisturbed by having been asked.
    assert client.get("/api/health").status_code == 200


def test_a_process_level_setting_is_not_writable(client: TestClient) -> None:
    """``data_dir`` and ``port`` are resolved once, at startup - see the module docstring."""
    for field, value in (("data_dir", "/tmp/elsewhere"), ("port", 9999), ("web_dist", "/x")):
        assert client.patch("/api/settings", json={field: value}).status_code == 422


def test_an_out_of_range_value_is_refused(client: TestClient) -> None:
    assert client.patch("/api/settings", json={"llm_max_tokens": 0}).status_code == 422
    assert client.patch("/api/settings", json={"llm_context_budget": -1}).status_code == 422


def test_the_patch_model_and_settings_agree_field_for_field() -> None:
    """The two spellings of one constraint, held together - the ``AnchorStatusFilter`` rule.

    ``model_copy`` does not re-validate, so the patch model *is* the validation. A constraint that
    drifted here would let a value Settings would have refused reach a running application.
    """
    assert set(SettingsPatchIn.model_fields) == set(WRITABLE_SETTINGS)
    for name in WRITABLE_SETTINGS:
        theirs = Settings.model_fields[name]
        ours = SettingsPatchIn.model_fields[name]
        assert ours.annotation == theirs.annotation, name
        assert ours.metadata == theirs.metadata, name
        assert ours.default == theirs.default, name


def test_the_config_file_is_reported_so_a_writer_can_find_it(client: TestClient) -> None:
    assert client.get("/api/settings").json()["config_file"].endswith(".yaml")


# -- the provider failure taxonomy over HTTP (ruling 4) -------------------------------------------


def test_every_provider_error_code_has_a_status_and_none_is_a_500() -> None:
    """Restated independently of the map, so widening the taxonomy fails here rather than
    being confirmed by a check that reads the list it is checking."""
    assert set(PROVIDER_ERROR_STATUS) == set(PROVIDER_ERROR_CODES)
    assert set(PROVIDER_ERROR_STATUS.values()) == {413, 429, 502, 503}
    assert provider_error_status("something_nobody_has_written_yet") == 502


def test_a_provider_failure_reaching_a_route_is_the_envelope_and_never_a_crash(
    settings: Settings,
) -> None:
    """Ruling 4, through the real handler stack rather than through the map alone.

    **No Phase 4 route raises this** - the socket carries provider failures as ``error`` events
    and the settings route reports an unconfigured provider as data (deviation ``C9``). The
    handler is registered anyway, and exercised here on a route this test adds, because without it
    the first provider call from a Phase 6 route would reach the writer as a ``500`` carrying a
    request id and nothing else: the traceback stays in the log, which is exactly where the cause
    would then be.
    """
    app: FastAPI = create_app(settings)

    def boom() -> None:
        raise ProviderError(
            "provider_rate_limited", "that account is out of quota", provider="anthropic"
        )

    app.add_api_route("/api/boom", boom, methods=["GET"])
    response = TestClient(app, raise_server_exceptions=False).get("/api/boom")

    assert response.status_code == 429
    body = response.json()["error"]
    assert body["code"] == "provider_rate_limited"
    assert body["message"] == "that account is out of quota"
    assert body["detail"] == {"provider": "anthropic"}
