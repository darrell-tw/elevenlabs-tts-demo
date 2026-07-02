"""Retry/backoff logic. No API key needed; sleep is injected as a no-op."""

import asyncio

import pytest

from eleven_tts.errors import AuthenticationError, RateLimitError, ServerError
from eleven_tts.retry import call_with_retry, call_with_retry_async


def _recording_sleep():
    calls = []
    return calls, lambda delay: calls.append(delay)


def test_success_first_try_does_not_sleep():
    calls, sleep = _recording_sleep()
    result = call_with_retry(lambda: "ok", sleep=sleep)
    assert result == "ok"
    assert calls == []


def test_retries_then_succeeds():
    calls, sleep = _recording_sleep()
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ServerError("boom", retryable=True)
        return "done"

    result = call_with_retry(flaky, max_retries=5, sleep=sleep)
    assert result == "done"
    assert attempts["n"] == 3
    assert len(calls) == 2  # slept before each of the 2 retries


def test_non_retryable_raises_immediately():
    calls, sleep = _recording_sleep()

    def auth_fail():
        raise AuthenticationError("bad key")

    with pytest.raises(AuthenticationError):
        call_with_retry(auth_fail, max_retries=5, sleep=sleep)
    assert calls == []


def test_gives_up_after_max_retries():
    calls, sleep = _recording_sleep()

    def always_429():
        raise RateLimitError("slow down")

    with pytest.raises(RateLimitError):
        call_with_retry(always_429, max_retries=3, sleep=sleep)
    assert len(calls) == 3  # 3 retries then give up


def test_rate_limit_retry_after_is_honored():
    calls, sleep = _recording_sleep()
    attempts = {"n": 0}

    def once():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RateLimitError("wait", retry_after=5)
        return "ok"

    call_with_retry(once, sleep=sleep)
    assert calls == [5.0]  # honored exactly, no jitter applied to retry_after


def test_async_retry_then_succeeds():
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ServerError("boom", retryable=True)
        return "async-done"

    result = asyncio.run(call_with_retry_async(flaky, sleep=fake_sleep))
    assert result == "async-done"
    assert len(slept) == 1
