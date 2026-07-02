"""Sync and async wrappers around the ElevenLabs TTS endpoint.

Each public method:
  1. validates input *before* spending an API call,
  2. invokes the SDK and collects the streamed audio into bytes,
  3. translates any failure into a typed :class:`TTSError`, and
  4. runs the whole thing through retry-with-backoff.

The SDK client is injectable (``sdk_client=``) so unit tests can exercise the
validation, error-translation, and retry logic with a fake — no API key needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .config import Settings
from .errors import ValidationError, classify_api_error
from .logconf import get_logger
from .retry import call_with_retry, call_with_retry_async

_log = get_logger(__name__)

# Conservative single-request character ceiling. The API's real limit varies by
# model; we reject obviously-too-long input early rather than burn a failed call.
MAX_TEXT_CHARS = 10_000


def _validate_text(text: str) -> None:
    if text is None or not text.strip():
        raise ValidationError("Text is empty. Provide non-whitespace text to synthesize.")
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationError(
            f"Text is too long ({len(text)} chars; limit {MAX_TEXT_CHARS}). "
            "Split it into multiple requests (see synthesize_batch)."
        )


def _request_options(settings: Settings) -> dict[str, Any]:
    # fern's RequestOptions is a TypedDict; passing a plain dict is supported.
    # max_retries=0 disables the SDK's own retries so this package's retry layer
    # is the single, testable source of retry behavior.
    return {"timeout_in_seconds": settings.request_timeout, "max_retries": 0}


class TTSClient:
    """Synchronous Text-to-Speech client."""

    def __init__(self, settings: Settings, *, sdk_client: Optional[Any] = None) -> None:
        self.settings = settings
        if sdk_client is not None:
            self._sdk = sdk_client
        else:
            from elevenlabs import ElevenLabs

            self._sdk = ElevenLabs(api_key=settings.api_key)

    def synthesize(
        self,
        text: str,
        *,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        output_format: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> bytes:
        """Synthesize ``text`` and return the full audio as bytes.

        Raises a typed :class:`TTSError` on failure (never a bare SDK error).
        """
        _validate_text(text)
        voice = voice_id or self.settings.voice_id
        model = model_id or self.settings.model_id
        fmt = output_format or self.settings.output_format

        def _do() -> bytes:
            try:
                stream = self._sdk.text_to_speech.convert(
                    voice,
                    text=text,
                    model_id=model,
                    output_format=fmt,
                    language_code=language_code,
                    request_options=_request_options(self.settings),
                )
                return b"".join(stream)
            except Exception as exc:  # integration boundary: normalize every failure
                raise classify_api_error(exc) from exc

        _log.info(
            "Synthesizing",
            extra={"chars": len(text), "voice_id": voice, "model_id": model, "format": fmt},
        )
        return call_with_retry(
            _do, max_retries=self.settings.max_retries
        )

    def synthesize_to_file(self, text: str, out_path: str | Path, **kwargs: Any) -> Path:
        """Synthesize ``text`` and write the audio to ``out_path``."""
        audio = self.synthesize(text, **kwargs)
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        _log.info("Wrote audio", extra={"path": str(path), "bytes": len(audio)})
        return path


class AsyncTTSClient:
    """Asynchronous Text-to-Speech client (use for concurrent batches)."""

    def __init__(self, settings: Settings, *, sdk_client: Optional[Any] = None) -> None:
        self.settings = settings
        if sdk_client is not None:
            self._sdk = sdk_client
        else:
            from elevenlabs import AsyncElevenLabs

            self._sdk = AsyncElevenLabs(api_key=settings.api_key)

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        output_format: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> bytes:
        _validate_text(text)
        voice = voice_id or self.settings.voice_id
        model = model_id or self.settings.model_id
        fmt = output_format or self.settings.output_format

        async def _do() -> bytes:
            try:
                chunks: list[bytes] = []
                # async convert returns an AsyncIterator[bytes] (not a coroutine).
                async for chunk in self._sdk.text_to_speech.convert(
                    voice,
                    text=text,
                    model_id=model,
                    output_format=fmt,
                    language_code=language_code,
                    request_options=_request_options(self.settings),
                ):
                    chunks.append(chunk)
                return b"".join(chunks)
            except Exception as exc:  # integration boundary: normalize every failure
                raise classify_api_error(exc) from exc

        _log.info(
            "Synthesizing (async)",
            extra={"chars": len(text), "voice_id": voice, "model_id": model, "format": fmt},
        )
        return await call_with_retry_async(
            _do, max_retries=self.settings.max_retries
        )

    async def synthesize_to_file(self, text: str, out_path: str | Path, **kwargs: Any) -> Path:
        audio = await self.synthesize(text, **kwargs)
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        _log.info("Wrote audio (async)", extra={"path": str(path), "bytes": len(audio)})
        return path
