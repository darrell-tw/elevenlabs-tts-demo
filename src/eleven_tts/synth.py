"""Batch synthesis — synchronous (sequential) and asynchronous (concurrent).

The async path is the interesting one: it fans out across many texts but caps
in-flight requests with an ``asyncio.Semaphore`` so we never hammer the API.
One failing item does not sink the batch — every item comes back as a
:class:`BatchResult` carrying either an output path or a typed error.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .client import AsyncTTSClient, TTSClient
from .errors import TTSError
from .logconf import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class SynthesisRequest:
    """One unit of batch work: text in, audio file out."""

    text: str
    out_path: Path
    voice_id: Optional[str] = None
    model_id: Optional[str] = None
    output_format: Optional[str] = None
    language_code: Optional[str] = None

    def _kwargs(self) -> dict[str, object]:
        return {
            k: v
            for k, v in {
                "voice_id": self.voice_id,
                "model_id": self.model_id,
                "output_format": self.output_format,
                "language_code": self.language_code,
            }.items()
            if v is not None
        }


@dataclass
class BatchResult:
    """Outcome of synthesizing one request."""

    request: SynthesisRequest
    path: Optional[Path] = None
    error: Optional[TTSError] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, request: SynthesisRequest, path: Path) -> "BatchResult":
        return cls(request=request, path=path)

    @classmethod
    def failure(cls, request: SynthesisRequest, error: TTSError) -> "BatchResult":
        return cls(request=request, error=error)


@dataclass
class BatchSummary:
    """Aggregate view of a batch run."""

    results: list[BatchResult] = field(default_factory=list)

    @property
    def succeeded(self) -> list[BatchResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> list[BatchResult]:
        return [r for r in self.results if not r.ok]

    def __len__(self) -> int:
        return len(self.results)


def synthesize_batch(
    client: TTSClient, requests: Sequence[SynthesisRequest]
) -> BatchSummary:
    """Synthesize each request sequentially. Never raises for a single failure."""
    results: list[BatchResult] = []
    for req in requests:
        try:
            path = client.synthesize_to_file(req.text, req.out_path, **req._kwargs())
            results.append(BatchResult.success(req, path))
        except TTSError as exc:
            _log.error(
                "Batch item failed",
                extra={"out_path": str(req.out_path), "error_type": type(exc).__name__},
            )
            results.append(BatchResult.failure(req, exc))
    return BatchSummary(results)


async def synthesize_batch_async(
    client: AsyncTTSClient,
    requests: Sequence[SynthesisRequest],
    *,
    concurrency: Optional[int] = None,
) -> BatchSummary:
    """Synthesize requests concurrently, capped at ``concurrency`` in-flight.

    ``concurrency`` defaults to the client's configured ``max_concurrency``.
    A failing item is captured, not raised, so the whole batch always completes.
    """
    limit = concurrency or client.settings.max_concurrency
    semaphore = asyncio.Semaphore(limit)
    _log.info(
        "Starting async batch",
        extra={"items": len(requests), "concurrency": limit},
    )

    async def _worker(req: SynthesisRequest) -> BatchResult:
        async with semaphore:
            try:
                path = await client.synthesize_to_file(req.text, req.out_path, **req._kwargs())
                return BatchResult.success(req, path)
            except TTSError as exc:
                _log.error(
                    "Batch item failed",
                    extra={"out_path": str(req.out_path), "error_type": type(exc).__name__},
                )
                return BatchResult.failure(req, exc)

    results = await asyncio.gather(*(_worker(r) for r in requests))
    return BatchSummary(list(results))
