"""Error classification — the heart of the integration. No API key needed."""

import httpx
import pytest

from eleven_tts.errors import (
    AuthenticationError,
    NetworkError,
    PermissionError,
    QuotaExceededError,
    RateLimitError,
    ServerError,
    TTSError,
    ValidationError,
    classify_api_error,
)


class FakeApiError(Exception):
    """Mimics elevenlabs ApiError: carries status_code / body / headers."""

    def __init__(self, status_code, body=None, headers=None):
        super().__init__(f"fake api error {status_code}")
        self.status_code = status_code
        self.body = body
        self.headers = headers


def test_401_is_authentication_error():
    err = classify_api_error(FakeApiError(401))
    assert isinstance(err, AuthenticationError)
    assert err.retryable is False


def test_401_with_quota_body_is_quota_error():
    err = classify_api_error(FakeApiError(401, body={"detail": {"status": "quota_exceeded"}}))
    assert isinstance(err, QuotaExceededError)
    assert err.retryable is False


def test_403_is_permission_error():
    assert isinstance(classify_api_error(FakeApiError(403)), PermissionError)


def test_429_is_retryable_rate_limit_with_retry_after():
    err = classify_api_error(FakeApiError(429, headers={"retry-after": "7"}))
    assert isinstance(err, RateLimitError)
    assert err.retryable is True
    assert err.retry_after == 7.0


def test_429_with_quota_body_is_quota_not_rate_limit():
    err = classify_api_error(FakeApiError(429, body="account quota exceeded"))
    assert isinstance(err, QuotaExceededError)


@pytest.mark.parametrize("status", [400, 422])
def test_4xx_validation_errors(status):
    err = classify_api_error(FakeApiError(status, body={"detail": "bad voice"}))
    assert isinstance(err, ValidationError)
    assert err.retryable is False


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_retryable_server_error(status):
    err = classify_api_error(FakeApiError(status))
    assert isinstance(err, ServerError)
    assert err.retryable is True


def test_timeout_is_retryable_network_error():
    err = classify_api_error(httpx.TimeoutException("timed out"))
    assert isinstance(err, NetworkError)
    assert err.retryable is True


def test_transport_error_is_network_error():
    err = classify_api_error(httpx.ConnectError("refused"))
    assert isinstance(err, NetworkError)
    assert err.retryable is True


def test_unknown_error_is_wrapped_non_retryable():
    err = classify_api_error(ValueError("boom"))
    assert isinstance(err, TTSError)
    assert err.retryable is False


def test_existing_tts_error_passes_through():
    original = ValidationError("empty text")
    assert classify_api_error(original) is original
