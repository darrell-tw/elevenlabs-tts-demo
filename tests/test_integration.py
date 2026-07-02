"""Integration tests that call the REAL ElevenLabs API.

Excluded by default (see pyproject `addopts = -m 'not integration'`).
Run explicitly once ELEVENLABS_API_KEY is set:

    pytest -m integration

These prove the repo's core claim: it genuinely talks to ElevenLabs end-to-end.
"""

import asyncio

import pytest

from eleven_tts import AsyncTTSClient, Settings, TTSClient
from eleven_tts.errors import ConfigError
from eleven_tts.synth import SynthesisRequest, synthesize_batch_async
from eleven_tts.voices import search_voices

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings():
    try:
        return Settings.from_env()
    except ConfigError:
        pytest.skip("ELEVENLABS_API_KEY not configured; skipping integration tests")


def _looks_like_audio(data: bytes) -> bool:
    # MP3 starts with an ID3 tag or an MPEG frame sync (0xFF Ex).
    return len(data) > 1000 and (data[:3] == b"ID3" or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0))


def test_real_synthesis_returns_audio(settings):
    client = TTSClient(settings)
    audio = client.synthesize("第一步，決定了之後的一切。", language_code="zh")
    assert _looks_like_audio(audio)


def test_real_voice_search(settings):
    client = TTSClient(settings)
    voices = search_voices(client, query="Taiwan")
    assert isinstance(voices, list)  # may be empty depending on account/library


def test_real_async_batch(settings, tmp_path):
    client = AsyncTTSClient(settings)
    requests = [
        SynthesisRequest(text="Hello from ElevenLabs.", out_path=tmp_path / "en.mp3"),
        SynthesisRequest(text="第二步，穩住節奏。", out_path=tmp_path / "zh.mp3", language_code="zh"),
    ]
    summary = asyncio.run(synthesize_batch_async(client, requests, concurrency=2))
    assert len(summary.succeeded) == 2
    assert all(r.path.exists() and r.path.stat().st_size > 1000 for r in summary.succeeded)
