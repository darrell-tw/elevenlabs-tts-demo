"""Batch synthesis — async concurrency capping, partial failures, sync path.
No API key needed."""

import asyncio

import pytest

from eleven_tts.client import TTSClient
from eleven_tts.config import Settings
from eleven_tts.errors import ServerError
from eleven_tts.synth import SynthesisRequest, synthesize_batch, synthesize_batch_async


# --- fakes ------------------------------------------------------------------

class _FakeSettings:
    def __init__(self, max_concurrency):
        self.max_concurrency = max_concurrency


class FakeAsyncClient:
    """Drop-in for AsyncTTSClient: records peak in-flight concurrency."""

    def __init__(self, max_concurrency=2, fail_texts=()):
        self.settings = _FakeSettings(max_concurrency)
        self.fail_texts = set(fail_texts)
        self.current = 0
        self.peak = 0

    async def synthesize_to_file(self, text, out_path, **kwargs):
        self.current += 1
        self.peak = max(self.peak, self.current)
        try:
            await asyncio.sleep(0.01)  # simulate I/O so overlap can happen
            if text in self.fail_texts:
                raise ServerError("simulated failure", retryable=False)
            return out_path
        finally:
            self.current -= 1


class FakeApiError(Exception):
    def __init__(self, status_code):
        super().__init__(str(status_code))
        self.status_code = status_code
        self.body = None
        self.headers = None


class FakeSyncTTS:
    def __init__(self, fail_texts=()):
        self.fail_texts = set(fail_texts)

    def convert(self, voice_id, *, text, **kwargs):
        if text in self.fail_texts:
            raise FakeApiError(422)
        return iter([b"ok"])


class FakeSDK:
    def __init__(self, tts):
        self.text_to_speech = tts


def _reqs(tmp_path, texts):
    return [
        SynthesisRequest(text=t, out_path=tmp_path / f"{i:03d}.mp3")
        for i, t in enumerate(texts)
    ]


# --- async ------------------------------------------------------------------

def test_async_batch_respects_concurrency_cap(tmp_path):
    client = FakeAsyncClient(max_concurrency=2)
    reqs = _reqs(tmp_path, [f"line {i}" for i in range(8)])
    summary = asyncio.run(synthesize_batch_async(client, reqs))
    assert len(summary.succeeded) == 8
    assert client.peak <= 2
    assert client.peak >= 2  # confirms it actually ran concurrently, not serially


def test_async_concurrency_arg_overrides_settings(tmp_path):
    client = FakeAsyncClient(max_concurrency=5)
    reqs = _reqs(tmp_path, [f"line {i}" for i in range(6)])
    summary = asyncio.run(synthesize_batch_async(client, reqs, concurrency=1))
    assert client.peak == 1
    assert len(summary.succeeded) == 6


def test_async_partial_failure_does_not_sink_batch(tmp_path):
    client = FakeAsyncClient(max_concurrency=3, fail_texts={"bad"})
    reqs = _reqs(tmp_path, ["good", "bad", "good2"])
    summary = asyncio.run(synthesize_batch_async(client, reqs))
    assert len(summary) == 3
    assert len(summary.succeeded) == 2
    assert len(summary.failed) == 1
    assert isinstance(summary.failed[0].error, ServerError)


# --- sync -------------------------------------------------------------------

def test_sync_batch_collects_results_and_failures(tmp_path):
    settings = Settings(api_key="test")
    client = TTSClient(settings, sdk_client=FakeSDK(FakeSyncTTS(fail_texts={"b"})))
    summary = synthesize_batch(client, _reqs(tmp_path, ["a", "b", "c"]))
    assert len(summary.succeeded) == 2
    assert len(summary.failed) == 1
    # successful items actually wrote files
    assert all(r.path.read_bytes() == b"ok" for r in summary.succeeded)
