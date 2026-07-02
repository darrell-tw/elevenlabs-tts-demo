"""Typed exception hierarchy and a classifier that turns raw SDK / transport
errors into meaningful, actionable exceptions.

The whole point of this demo is that callers never see a bare traceback from a
401, a rate limit, or a dropped connection — each failure mode maps to a
distinct exception with a clear message and a `retryable` flag the retry layer
can act on.
"""

from __future__ import annotations

from typing import Any, Optional


class TTSError(Exception):
    """Base class for every error this package raises.

    Attributes:
        message:     human-readable explanation.
        status_code: HTTP status code, when the failure came from the API.
        retryable:   whether retrying the same request might succeed.
    """

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        retryable: Optional[bool] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable


class ConfigError(TTSError):
    """Missing or invalid configuration (e.g. no API key)."""


class ValidationError(TTSError):
    """Input rejected before or by the API (empty text, too long, bad params)."""


class AuthenticationError(TTSError):
    """Invalid or missing API key (HTTP 401)."""


class PermissionError(TTSError):  # noqa: A001 - deliberately shadowing builtin in this namespace
    """Key is valid but lacks permission for this operation (HTTP 403)."""


class QuotaExceededError(TTSError):
    """Account character/credit quota is exhausted. Not retryable."""


class RateLimitError(TTSError):
    """Too many requests (HTTP 429). Retryable after a short wait.

    Attributes:
        retry_after: seconds to wait before retrying, if the API supplied it.
    """

    retryable = True

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = 429,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message, status_code=status_code, retryable=True)
        self.retry_after = retry_after


class ServerError(TTSError):
    """ElevenLabs returned a 5xx. Retryable."""

    retryable = True


class NetworkError(TTSError):
    """Connection failed or timed out before a response. Retryable."""

    retryable = True


# Keywords that, when present in an error body, indicate the account ran out of
# quota rather than supplying a bad key. ElevenLabs reports quota exhaustion on
# a 401 in some plans, so message inspection is needed to disambiguate.
_QUOTA_HINTS = ("quota_exceeded", "quota exceeded", "exceeds your quota", "out of credits")


def _body_text(body: Any) -> str:
    """Best-effort flattening of an error body to a lowercase string for keyword
    matching, regardless of whether it's a dict, str, or nested detail object."""
    if body is None:
        return ""
    if isinstance(body, str):
        return body.lower()
    try:
        import json

        return json.dumps(body, default=str).lower()
    except Exception:
        return str(body).lower()


def _extract_retry_after(headers: Any) -> Optional[float]:
    if not headers:
        return None
    try:
        # headers may be a dict or an httpx.Headers-like mapping (case-insensitive)
        value = None
        if hasattr(headers, "get"):
            value = headers.get("retry-after") or headers.get("Retry-After")
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_api_error(exc: Exception) -> TTSError:
    """Map an SDK or transport exception to a typed :class:`TTSError`.

    Recognizes:
      * httpx timeout / connection errors  -> NetworkError
      * ElevenLabs ApiError by status code -> Auth/Permission/Quota/RateLimit/
                                              Validation/ServerError
      * anything else                      -> TTSError (non-retryable)

    Imports of optional dependencies happen lazily so this module can be unit
    tested without importing the whole SDK if it isn't installed.
    """
    # 1. Transport-level failures (timeouts, connection resets) from httpx.
    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return NetworkError(f"Request timed out: {exc}", retryable=True)
        if isinstance(exc, httpx.TransportError):
            return NetworkError(f"Network/transport error: {exc}", retryable=True)
    except ImportError:
        pass

    # 2. ElevenLabs API errors carry a status_code and (sometimes) a body.
    status_code = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    headers = getattr(exc, "headers", None)

    if status_code is not None:
        body_text = _body_text(body)

        if status_code == 401:
            if any(h in body_text for h in _QUOTA_HINTS):
                return QuotaExceededError(
                    "API quota exhausted (reported on 401). Check your plan usage.",
                    status_code=status_code,
                )
            return AuthenticationError(
                "Authentication failed (401). Check ELEVENLABS_API_KEY.",
                status_code=status_code,
            )
        if status_code == 403:
            return PermissionError(
                "Permission denied (403). The key lacks access to this operation.",
                status_code=status_code,
            )
        if status_code in (402, 429):
            if any(h in body_text for h in _QUOTA_HINTS):
                return QuotaExceededError(
                    "API quota exhausted. Not retryable until usage resets.",
                    status_code=status_code,
                )
            if status_code == 429:
                return RateLimitError(
                    "Rate limit exceeded (429). Backing off before retry.",
                    status_code=status_code,
                    retry_after=_extract_retry_after(headers),
                )
            return QuotaExceededError(
                "Payment required / quota exhausted (402).", status_code=status_code
            )
        if status_code in (400, 422):
            return ValidationError(
                f"Request rejected ({status_code}). Check text, voice_id, and model_id. "
                f"Detail: {body_text or 'n/a'}",
                status_code=status_code,
            )
        if 500 <= status_code < 600:
            return ServerError(
                f"ElevenLabs server error ({status_code}). Retrying may help.",
                status_code=status_code,
                retryable=True,
            )
        return TTSError(
            f"Unexpected API error ({status_code}). Detail: {body_text or 'n/a'}",
            status_code=status_code,
        )

    # 3. Already one of ours — pass through unchanged.
    if isinstance(exc, TTSError):
        return exc

    # 4. Unknown — wrap without marking retryable.
    return TTSError(f"Unexpected error: {exc}")
