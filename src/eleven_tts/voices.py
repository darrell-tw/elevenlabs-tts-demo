"""Voice discovery — list and search the voice catalog.

Used to find a Taiwanese-Mandarin voice id to drop into `.env`. Returns small
dataclasses instead of raw SDK models so callers (and the CLI) have a stable,
predictable shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .client import TTSClient
from .errors import classify_api_error


@dataclass(frozen=True)
class VoiceInfo:
    voice_id: str
    name: str
    category: Optional[str] = None
    labels: Optional[dict[str, Any]] = None

    def label(self, key: str) -> Optional[str]:
        if not self.labels:
            return None
        value = self.labels.get(key)
        return str(value) if value is not None else None

    def describe(self) -> str:
        """One-line, human-friendly summary for CLI output."""
        bits = [self.name, f"({self.voice_id})"]
        accent = self.label("accent") or self.label("language")
        if accent:
            bits.append(f"[{accent}]")
        if self.category:
            bits.append(f"- {self.category}")
        return " ".join(bits)


def _to_info(voice: Any) -> VoiceInfo:
    return VoiceInfo(
        voice_id=getattr(voice, "voice_id", ""),
        name=getattr(voice, "name", "") or "",
        category=getattr(voice, "category", None),
        labels=getattr(voice, "labels", None),
    )


def list_voices(client: TTSClient) -> list[VoiceInfo]:
    """Return all voices available to the account."""
    try:
        resp = client._sdk.voices.get_all()
    except Exception as exc:
        raise classify_api_error(exc) from exc
    return [_to_info(v) for v in getattr(resp, "voices", [])]


def search_voices(
    client: TTSClient,
    *,
    query: Optional[str] = None,
    voice_type: Optional[str] = None,
    category: Optional[str] = None,
    page_size: int = 30,
) -> list[VoiceInfo]:
    """Search voices already in this account (e.g. query='Taiwan' to find a
    Taiwanese-Mandarin voice previously added to My Voices).

    Note this only searches voices already in *your* account — it does not
    reach into the ElevenLabs shared voice library. Pass ``category="premade"``
    to restrict results to the official default voices, which are guaranteed
    usable via the API on every plan (unlike voices sourced from the shared
    library, which the API rejects for free-tier accounts even after they've
    been added to My Voices — see README "Known limitations").
    """
    try:
        resp = client._sdk.voices.search(
            search=query, voice_type=voice_type, category=category, page_size=page_size
        )
    except Exception as exc:
        raise classify_api_error(exc) from exc
    return [_to_info(v) for v in getattr(resp, "voices", [])]
