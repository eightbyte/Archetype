"""P1-2 - settings layering and the secret discipline (D8).

The layering tests assert each layer in isolation and then in combination, because the failure
that matters is not "YAML does not load" but "YAML silently beat the environment".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import Field, SecretStr

from archetype.config import (
    CONFIG_FILE_ENV_VAR,
    Settings,
    get_settings,
    load_settings,
    reset_settings_cache,
)


def write_config(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


# -- layer 1: defaults ----------------------------------------------------------------------


def test_defaults_are_the_documented_ones() -> None:
    settings = load_settings()
    assert settings.host == "127.0.0.1"  # loopback by default (D7)
    assert settings.port == 8787
    assert settings.log_level == "info"
    assert settings.data_dir.is_absolute()
    assert settings.projects_dir == settings.data_dir / "projects"


def test_a_missing_config_file_is_not_an_error() -> None:
    # A fresh clone has no config.yaml; the server must still start.
    assert load_settings().port == 8787


# -- layer 2: config.yaml -------------------------------------------------------------------


def test_yaml_overrides_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = write_config(tmp_path / "config.yaml", "port: 9001\nlog_level: debug\n")
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(config))

    settings = load_settings()
    assert settings.port == 9001
    assert settings.log_level == "debug"
    assert settings.host == "127.0.0.1"  # untouched keys keep their default


def test_an_empty_yaml_file_leaves_defaults_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(write_config(tmp_path / "config.yaml", "\n")))
    assert load_settings().port == 8787


def test_a_yaml_file_that_is_not_a_mapping_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(write_config(tmp_path / "config.yaml", "- a\n- b")))
    with pytest.raises(TypeError, match="YAML mapping"):
        load_settings()


# -- layer 3: environment -------------------------------------------------------------------


def test_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHETYPE_PORT", "9100")
    monkeypatch.setenv("ARCHETYPE_HOST", "0.0.0.0")
    settings = load_settings()
    assert settings.port == 9100
    assert settings.host == "0.0.0.0"


def test_env_beats_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = write_config(tmp_path / "config.yaml", "port: 9001\nlog_level: warning\n")
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(config))
    monkeypatch.setenv("ARCHETYPE_PORT", "9200")

    settings = load_settings()
    assert settings.port == 9200, "a shell must always be able to override a file"
    assert settings.log_level == "warning", "keys the env does not set still come from YAML"


def test_explicit_arguments_beat_every_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path / "config.yaml", "port: 1\n")
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(config))
    monkeypatch.setenv("ARCHETYPE_PORT", "2")
    assert load_settings(port=3).port == 3


# -- field handling -------------------------------------------------------------------------


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHETYPE_LOG_LEVEL", "DEBUG")
    assert load_settings().log_level == "debug"


def test_an_unknown_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHETYPE_LOG_LEVEL", "chatty")
    with pytest.raises(ValueError):
        load_settings()


def test_an_out_of_range_port_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHETYPE_PORT", "70000")
    with pytest.raises(ValueError):
        load_settings()


def test_a_relative_data_dir_resolves_against_the_repository_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARCHETYPE_DATA_DIR", "some/where")
    settings = load_settings()
    assert settings.data_dir.is_absolute()
    assert settings.data_dir.parts[-2:] == ("some", "where")


def test_ensure_dirs_creates_the_projects_directory(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    assert not settings.projects_dir.exists()
    assert settings.ensure_dirs() == settings.projects_dir
    assert settings.projects_dir.is_dir()
    settings.ensure_dirs()  # idempotent


def test_get_settings_is_cached_until_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHETYPE_PORT", "9300")
    assert get_settings() is get_settings()
    assert get_settings().port == 9300

    monkeypatch.setenv("ARCHETYPE_PORT", "9400")
    assert get_settings().port == 9300, "the cached instance does not re-read the environment"
    reset_settings_cache()
    assert get_settings().port == 9400


# -- the secret discipline (D8) -------------------------------------------------------------
#
# Phase 1 has no secret-valued setting. The guard is built and tested now so Phase 4, which adds
# provider keys, cannot quietly regress it.


class SettingsWithSecret(Settings):
    """Stands in for the Phase 4 shape: a real key alongside the ordinary settings."""

    api_key: SecretStr | None = Field(default=None, exclude=True)


def test_phase_1_declares_no_secrets() -> None:
    assert Settings.secret_fields() == frozenset()


def test_a_secret_field_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHETYPE_API_KEY", "sk-not-a-real-key")
    settings = SettingsWithSecret()
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "sk-not-a-real-key"


def test_a_secret_never_appears_in_any_serialization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHETYPE_API_KEY", "sk-not-a-real-key")
    settings = SettingsWithSecret()

    assert "api_key" not in settings.model_dump()
    assert "api_key" not in settings.model_dump(mode="json")
    assert "api_key" not in settings.public_dump()
    for rendering in (settings.model_dump_json(), repr(settings), str(settings)):
        assert "sk-not-a-real-key" not in rendering


def test_a_secret_cannot_be_supplied_by_config_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # P1-2 narrows D8: secret-valued settings come from the environment only.
    config = write_config(tmp_path / "config.yaml", "api_key: sk-from-a-file\nport: 9500\n")
    monkeypatch.setenv(CONFIG_FILE_ENV_VAR, str(config))

    settings = SettingsWithSecret()
    assert settings.api_key is None
    assert settings.port == 9500, "non-secret keys in the same file still load"


def test_declaring_a_secret_without_exclude_fails_at_class_definition() -> None:
    with pytest.raises(TypeError, match="exclude=True"):

        class Leaky(Settings):
            api_key: SecretStr | None = None
