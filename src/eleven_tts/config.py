"""Configuration loading.

Settings come from environment variables, with a tiny built-in `.env` loader so
the demo works after `cp .env.example .env` without adding a python-dotenv
dependency. Real environment variables always win over `.env` values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import ConfigError

# Safe, well-known public voice (George). Used only when no voice is configured;
# for Taiwanese-Mandarin output, set ELEVENLABS_VOICE_ID (see `voices --search`).
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"


def load_dotenv(path: str | os.PathLike[str] = ".env") -> dict[str, str]:
    """Parse a `.env` file into a dict. Returns {} if the file does not exist.

    Supports `KEY=VALUE`, `#` comments, blank lines, optional `export ` prefix,
    and surrounding single/double quotes. Does not perform variable expansion —
    kept deliberately small and predictable.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _coalesce(key: str, dotenv: dict[str, str], default: Optional[str] = None) -> Optional[str]:
    """Real env var first, then .env, then default. Empty strings count as unset."""
    value = os.environ.get(key) or dotenv.get(key)
    if value is None or value == "":
        return default
    return value


@dataclass(frozen=True)
class Settings:
    """Resolved configuration for the TTS client."""

    api_key: str
    voice_id: str = DEFAULT_VOICE_ID
    model_id: str = DEFAULT_MODEL_ID
    output_format: str = DEFAULT_OUTPUT_FORMAT
    max_retries: int = 4
    max_concurrency: int = 3
    request_timeout: float = 30.0

    @classmethod
    def from_env(cls, dotenv_path: str | os.PathLike[str] = ".env") -> "Settings":
        """Build Settings from environment + `.env`.

        Raises:
            ConfigError: if ELEVENLABS_API_KEY is not set anywhere.
        """
        dotenv = load_dotenv(dotenv_path)

        api_key = _coalesce("ELEVENLABS_API_KEY", dotenv)
        if not api_key:
            raise ConfigError(
                "ELEVENLABS_API_KEY is not set. Copy .env.example to .env and add "
                "your key, or export ELEVENLABS_API_KEY in your shell."
            )

        return cls(
            api_key=api_key,
            voice_id=_coalesce("ELEVENLABS_VOICE_ID", dotenv, DEFAULT_VOICE_ID) or DEFAULT_VOICE_ID,
            model_id=_coalesce("ELEVENLABS_MODEL_ID", dotenv, DEFAULT_MODEL_ID) or DEFAULT_MODEL_ID,
            output_format=_coalesce(
                "ELEVENLABS_OUTPUT_FORMAT", dotenv, DEFAULT_OUTPUT_FORMAT
            )
            or DEFAULT_OUTPUT_FORMAT,
            max_retries=_int_env("ELEVENLABS_MAX_RETRIES", dotenv, 4),
            max_concurrency=_int_env("ELEVENLABS_MAX_CONCURRENCY", dotenv, 3),
            request_timeout=_float_env("ELEVENLABS_REQUEST_TIMEOUT", dotenv, 30.0),
        )

    def redacted_key(self) -> str:
        """A safe-to-log representation of the API key (never the full value)."""
        if len(self.api_key) <= 8:
            return "***"
        return f"{self.api_key[:4]}…{self.api_key[-2:]}"


def _int_env(key: str, dotenv: dict[str, str], default: int) -> int:
    value = _coalesce(key, dotenv)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {value!r}") from exc


def _float_env(key: str, dotenv: dict[str, str], default: float) -> float:
    value = _coalesce(key, dotenv)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {value!r}") from exc
