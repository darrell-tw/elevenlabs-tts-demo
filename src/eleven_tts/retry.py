"""Retry with exponential backoff + jitter, for both sync and async callables.

A call is retried only when it raises a :class:`TTSError` whose ``retryable``
flag is set (rate limits, 5xx, network blips). Non-retryable errors (auth,
validation, quota) propagate immediately — retrying them just wastes quota.

The functions take a *thunk* (zero-arg callable) so they compose cleanly with
the client methods, which already translate raw SDK errors into TTSError.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Awaitable, Callable, TypeVar

from .errors import RateLimitError, TTSError
from .logconf import get_logger

T = TypeVar("T")

_log = get_logger(__name__)

# Hard cap on a single backoff sleep, so a server-suggested Retry-After or a
# large exponent can't stall the whole batch.
_MAX_BACKOFF_SECONDS = 30.0


def _backoff_delay(attempt: int, base_delay: float, exc: TTSError) -> float:
    """Compute the delay before the next attempt (0-indexed ``attempt``).

    Honors a server-provided ``retry_after`` on rate limits; otherwise uses
    exponential growth with full jitter to avoid thundering-herd retries.
    """
    if isinstance(exc, RateLimitError) and exc.retry_after:
        return min(exc.retry_after, _MAX_BACKOFF_SECONDS)
    raw = base_delay * (2 ** attempt)
    return min(raw, _MAX_BACKOFF_SECONDS) * (0.5 + random.random() / 2)  # full jitter


def call_with_retry(
    thunk: Callable[[], T],
    *,
    max_retries: int = 4,
    base_delay: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``thunk``, retrying retryable TTSErrors up to ``max_retries`` times.

    ``sleep`` is injectable so tests can run with zero real delay.
    """
    attempt = 0
    while True:
        try:
            return thunk()
        except TTSError as exc:
            if not exc.retryable or attempt >= max_retries:
                raise
            delay = _backoff_delay(attempt, base_delay, exc)
            _log.warning(
                "Retryable error; backing off",
                extra={
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "delay_s": round(delay, 2),
                    "error_type": type(exc).__name__,
                    "status_code": exc.status_code,
                },
            )
            sleep(delay)
            attempt += 1


async def call_with_retry_async(
    thunk: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 4,
    base_delay: float = 0.5,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Async counterpart of :func:`call_with_retry`."""
    attempt = 0
    while True:
        try:
            return await thunk()
        except TTSError as exc:
            if not exc.retryable or attempt >= max_retries:
                raise
            delay = _backoff_delay(attempt, base_delay, exc)
            _log.warning(
                "Retryable error; backing off",
                extra={
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "delay_s": round(delay, 2),
                    "error_type": type(exc).__name__,
                    "status_code": exc.status_code,
                },
            )
            await sleep(delay)
            attempt += 1
