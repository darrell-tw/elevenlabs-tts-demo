"""Client behavior with a fake SDK — validation, byte collection, error
translation, and retry integration. No API key needed."""

import asyncio

import pytest

from eleven_tts.client import MAX_TEXT_CHARS, AsyncTTSClient, TTSClient
from eleven_tts.config import Settings
from eleven_tts.errors import AuthenticationError, ValidationError


class FakeApiError(Exception):
    def __init__(self, status_code, body=None, headers=None):
        super().__init__(f"fake {status_code}")
        self.status_code = status_code
        self.body = body
        self.headers = headers


class FakeSyncTTS:
    """Stand-in for client._sdk.text_to_speech (sync)."""

    def __init__(self, chunks=None, fail_times=0, status_code=429):
        self.chunks = chunks or [b"au", b"dio"]
        self.fail_times = fail_times
        self.status_code = status_code
        self.calls = 0

    def convert(self, voice_id, *, text, model_id=None, output_format=None,
                language_code=None, request_options=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise FakeApiError(self.status_code)
        return iter(self.chunks)


class FakeAsyncTTS:
    """Stand-in for client._sdk.text_to_speech (async)."""

    def __init__(self, chunks=None):
        self.chunks = chunks or [b"au", b"dio"]

    def convert(self, voice_id, *, text, model_id=None, output_format=None,
                language_code=None, request_options=None):
        chunks = self.chunks

        async def _gen():
            for c in chunks:
                yield c

        return _gen()


class FakeSDK:
    def __init__(self, tts):
        self.text_to_speech = tts


def _settings():
    return Settings(api_key="test-key", max_retries=3)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)


@pytest.mark.parametrize("bad", ["", "   ", "\n\t"])
def test_empty_text_rejected_before_api(bad):
    sdk = FakeSDK(FakeSyncTTS())
    client = TTSClient(_settings(), sdk_client=sdk)
    with pytest.raises(ValidationError):
        client.synthesize(bad)
    assert sdk.text_to_speech.calls == 0  # never hit the API


def test_too_long_text_rejected():
    client = TTSClient(_settings(), sdk_client=FakeSDK(FakeSyncTTS()))
    with pytest.raises(ValidationError):
        client.synthesize("x" * (MAX_TEXT_CHARS + 1))


def test_happy_path_collects_bytes():
    client = TTSClient(_settings(), sdk_client=FakeSDK(FakeSyncTTS([b"foo", b"bar"])))
    assert client.synthesize("hello") == b"foobar"


def test_retries_on_429_then_succeeds():
    sdk = FakeSDK(FakeSyncTTS(fail_times=2, status_code=429))
    client = TTSClient(_settings(), sdk_client=sdk)
    assert client.synthesize("hello") == b"audio"
    assert sdk.text_to_speech.calls == 3


def test_auth_error_not_retried():
    sdk = FakeSDK(FakeSyncTTS(fail_times=99, status_code=401))
    client = TTSClient(_settings(), sdk_client=sdk)
    with pytest.raises(AuthenticationError):
        client.synthesize("hello")
    assert sdk.text_to_speech.calls == 1  # no retry on auth failure


def test_synthesize_to_file_writes(tmp_path):
    client = TTSClient(_settings(), sdk_client=FakeSDK(FakeSyncTTS([b"abc"])))
    out = tmp_path / "nested" / "out.mp3"
    path = client.synthesize_to_file("hello", out)
    assert path.read_bytes() == b"abc"


def test_async_happy_path_collects_bytes():
    client = AsyncTTSClient(_settings(), sdk_client=FakeSDK(FakeAsyncTTS([b"a", b"b", b"c"])))
    assert asyncio.run(client.synthesize("hello")) == b"abc"


def test_async_validation_rejects_empty():
    client = AsyncTTSClient(_settings(), sdk_client=FakeSDK(FakeAsyncTTS()))
    with pytest.raises(ValidationError):
        asyncio.run(client.synthesize(""))
