"""Configuration and secrets (P1-2).

Settings layer **defaults < ``config.yaml`` < ``ARCHETYPE_*`` environment variables**, with the
environment winning so a shell can always override a file.

Secret discipline (D8) is established here, before there is a secret to guard:

* a secret-valued setting is any field annotated :class:`~pydantic.SecretStr`;
* it is read from the environment **only** - the YAML layer cannot supply one;
* it is excluded from every serialization of the settings object, and must be declared
  ``Field(exclude=True)`` or the class fails to build;
* no route ever returns one. :meth:`Settings.public_dump` is the only sanctioned way to hand
  settings to a response, and it strips secrets a second time.

D8 also permits a gitignored ``config.yaml`` to carry secrets; P1-2 narrows that to the
environment only, which is the stricter of the two and contradicts neither.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

import yaml
from pydantic import Field, SecretStr, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

__all__ = [
    "CONFIG_FILE_ENV_VAR",
    "PROJECT_ROOT",
    "Settings",
    "get_settings",
    "load_settings",
    "reset_settings_cache",
]

#: Repository root: ``<repo>/server/archetype/config.py`` -> ``<repo>``.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Points the YAML layer at a different file. Read from the environment so a shell can always
#: override, including in tests.
CONFIG_FILE_ENV_VAR = "ARCHETYPE_CONFIG_FILE"

DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config.yaml"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

LogLevel = Literal["critical", "error", "warning", "info", "debug", "trace"]


def _is_secret_annotation(annotation: Any) -> bool:
    """True for ``SecretStr`` and for optionals/unions containing it."""
    if annotation is SecretStr:
        return True
    if get_origin(annotation) is Union:
        return any(_is_secret_annotation(arg) for arg in get_args(annotation))
    return False


def secret_field_names(model_fields: dict[str, FieldInfo]) -> frozenset[str]:
    """Names of the secret-valued fields in a settings model."""
    return frozenset(
        name for name, field in model_fields.items() if _is_secret_annotation(field.annotation)
    )


class YamlSettingsSource(PydanticBaseSettingsSource):
    """Reads ``config.yaml``, refusing to supply secret-valued fields.

    A missing file is not an error - a fresh clone has no ``config.yaml``. A file that is not a
    YAML mapping is an error, because ignoring it would hide a typo in the writer's config.
    """

    def __init__(self, settings_cls: type[BaseSettings], path: Path | None = None) -> None:
        super().__init__(settings_cls)
        self.path = path if path is not None else self._path_from_env()
        self._data = self._read()

    @staticmethod
    def _path_from_env() -> Path:
        override = os.environ.get(CONFIG_FILE_ENV_VAR)
        return Path(override) if override else DEFAULT_CONFIG_FILE

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise TypeError(f"{self.path} must contain a YAML mapping, got {type(raw).__name__}")
        secrets = secret_field_names(self.settings_cls.model_fields)
        return {str(k): v for k, v in raw.items() if str(k) not in secrets}

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._data)


class _SecretPolicyBaseSettings(BaseSettings):
    """Fails at class-definition time if a secret field is not declared ``exclude=True``.

    The guard lives on the base so it also covers subclasses - Phase 4 adds provider keys to
    :class:`Settings` and cannot quietly regress the rule.
    """

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        for name in sorted(secret_field_names(cls.model_fields)):
            if cls.model_fields[name].exclude is not True:
                raise TypeError(
                    f"{cls.__name__}.{name} is a secret-valued setting and must be declared "
                    f"Field(..., exclude=True) so it stays out of every serialization (D8)."
                )

    @classmethod
    def secret_fields(cls) -> frozenset[str]:
        """Names of this model's secret-valued fields."""
        return secret_field_names(cls.model_fields)

    def public_dump(self) -> dict[str, Any]:
        """A JSON-safe dump with every secret removed. The only shape a route may return."""
        data = self.model_dump(mode="json")
        for name in self.secret_fields():
            data.pop(name, None)
        return data


class Settings(_SecretPolicyBaseSettings):
    """Phase 1 settings. Provider and embedding keys arrive in Phases 4 and 5."""

    model_config = SettingsConfigDict(
        env_prefix="ARCHETYPE_",
        extra="ignore",
        validate_default=True,
    )

    data_dir: Path = Field(
        default=DEFAULT_DATA_DIR,
        description="Runtime data root. Project files live in <data_dir>/projects (D17).",
    )
    host: str = Field(
        default="127.0.0.1",
        description=(
            "Bind address. Loopback by default - a deliberate posture, not an oversight: "
            "single user, no auth, no HTTPS (D7)."
        ),
    )
    port: int = Field(default=8787, ge=1, le=65535, description="Server port.")
    log_level: LogLevel = Field(default="info", description="Server log level.")

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        return value.lower() if isinstance(value, str) else value

    @field_validator("data_dir", mode="after")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Earlier sources win. Env beats YAML beats defaults; init kwargs beat everything, so a
        # caller (or a test) can always construct an explicit Settings.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlSettingsSource(settings_cls),
            file_secret_settings,
        )

    @property
    def projects_dir(self) -> Path:
        """Where project files are scanned for and created (D17)."""
        return self.data_dir / "projects"

    def ensure_dirs(self) -> Path:
        """Create the data directories if absent and return the projects directory."""
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        return self.projects_dir


def load_settings(**overrides: Any) -> Settings:
    """Build a fresh :class:`Settings`, resolving every layer.

    Not cached - see :func:`get_settings` for the process-wide instance.
    """
    return Settings(**overrides)


_settings: Settings | None = None


def get_settings() -> Settings:
    """The process-wide settings instance, built on first use."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings_cache() -> None:
    """Drop the cached instance so the next :func:`get_settings` re-reads its layers."""
    global _settings
    _settings = None
