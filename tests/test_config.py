"""Config + .env parsing. No API key needed."""

import pytest

from eleven_tts.config import DEFAULT_VOICE_ID, Settings, load_dotenv
from eleven_tts.errors import ConfigError


def test_load_dotenv_parses_quotes_comments_and_export(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "ELEVENLABS_API_KEY=plain-key",
                'ELEVENLABS_VOICE_ID="quoted-voice"',
                "export ELEVENLABS_MODEL_ID='exported-model'",
                "NOT_A_PAIR",
            ]
        ),
        encoding="utf-8",
    )
    parsed = load_dotenv(env)
    assert parsed["ELEVENLABS_API_KEY"] == "plain-key"
    assert parsed["ELEVENLABS_VOICE_ID"] == "quoted-voice"
    assert parsed["ELEVENLABS_MODEL_ID"] == "exported-model"
    assert "NOT_A_PAIR" not in parsed


def test_load_dotenv_missing_file_returns_empty(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == {}


def test_from_env_raises_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env(dotenv_path=tmp_path / "nope.env")


def test_from_env_reads_key_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("ELEVENLABS_API_KEY=from-dotenv\n", encoding="utf-8")
    settings = Settings.from_env(dotenv_path=env)
    assert settings.api_key == "from-dotenv"
    assert settings.voice_id == DEFAULT_VOICE_ID  # default applied


def test_real_env_var_wins_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-real-env")
    env = tmp_path / ".env"
    env.write_text("ELEVENLABS_API_KEY=from-dotenv\n", encoding="utf-8")
    settings = Settings.from_env(dotenv_path=env)
    assert settings.api_key == "from-real-env"


def test_invalid_int_setting_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_MAX_RETRIES", "not-a-number")
    with pytest.raises(ConfigError):
        Settings.from_env(dotenv_path=tmp_path / "nope.env")


def test_redacted_key_never_exposes_full_value():
    settings = Settings(api_key="supersecretkey12345")
    red = settings.redacted_key()
    assert "supersecretkey12345" not in red
    assert red.startswith("supe")
