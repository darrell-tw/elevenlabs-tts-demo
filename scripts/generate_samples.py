#!/usr/bin/env python3
"""One-shot script: generate the committed sample audio (Traditional Chinese +
English).

    python scripts/generate_samples.py

Requires ELEVENLABS_API_KEY (env or .env). The voice used is **pinned via
`ELEVENLABS_VOICE_ID` in `.env`** rather than picked freshly on every run.

Known limitation (see README "Known limitations"): a Taiwanese-Mandarin voice
("Yu", accent `taiwan mandarin`) was located in the ElevenLabs shared voice
library with `client.voices.get_shared(search=...)` and successfully added to
this account with `client.voices.share(...)` — but the Text-to-Speech API
rejects it at synthesis time on the free plan with `402 payment_required` /
`paid_plan_required` ("Free users cannot use library voices via the API").
This is a plan-wide restriction confirmed across multiple shared-library
voices, not a quirk of one voice. The pinned default therefore falls back to
an official **premade** voice (George), which every plan can use via the API.

If no voice is pinned, this script falls back to searching the account's own
*premade* voices only (never the shared library, and never a `professional`
category voice, to avoid re-hitting the same 402).

Writes `samples/MANIFEST.md` recording exactly which voice/model/text produced
each committed file, plus the quota spent generating them.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eleven_tts import AsyncTTSClient, Settings, TTSClient  # noqa: E402
from eleven_tts.config import DEFAULT_VOICE_ID, load_dotenv  # noqa: E402
from eleven_tts.errors import TTSError  # noqa: E402
from eleven_tts.logconf import setup_logging  # noqa: E402
from eleven_tts.synth import SynthesisRequest, synthesize_batch_async  # noqa: E402
from eleven_tts.voices import search_voices  # noqa: E402

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
MANIFEST_PATH = SAMPLES_DIR / "MANIFEST.md"

ZH_TEXT = "第一步，往往決定了之後的一切。歡迎使用 ElevenLabs 文字轉語音示範。"
EN_TEXT = "The first step often decides everything that follows. Welcome to this ElevenLabs text-to-speech demo."


def _explicit_voice_id(dotenv_path: str = ".env") -> Optional[str]:
    """The raw `ELEVENLABS_VOICE_ID`, or ``None`` if the user never set one.

    Deliberately bypasses ``Settings``, which always resolves to *some* voice
    id (falling back to ``DEFAULT_VOICE_ID``) — this needs to distinguish
    "explicitly pinned" from "using the library default".
    """
    dotenv = load_dotenv(dotenv_path)
    return os.environ.get("ELEVENLABS_VOICE_ID") or dotenv.get("ELEVENLABS_VOICE_ID") or None


def _resolve_zh_voice(client: TTSClient) -> tuple[str, str]:
    """Return ``(voice_id, description)`` for the Chinese-language sample."""
    explicit = _explicit_voice_id()
    if explicit:
        return explicit, f"pinned via ELEVENLABS_VOICE_ID ({explicit})"

    for query in ("Taiwan", "Mandarin", "Chinese"):
        try:
            # category="premade" is deliberate: shared-library voices found via
            # search are rejected by the API on the free plan (402), even once
            # added to My Voices. Restricting to premade guarantees the
            # auto-picked voice is actually usable.
            voices = search_voices(client, query=query, page_size=10, category="premade")
        except TTSError:
            voices = []
        if voices:
            chosen = voices[0]
            print(f"No ELEVENLABS_VOICE_ID set; using premade search '{query}' result: {chosen.describe()}")
            return chosen.voice_id, f"auto-selected via search('{query}', category=premade) — not pinned, may vary"

    print(f"No ELEVENLABS_VOICE_ID set and no premade match; using library default {DEFAULT_VOICE_ID}")
    return DEFAULT_VOICE_ID, "library default (George) — no Taiwanese-accented voice usable on this plan"


def _voice_name(client: TTSClient, voice_id: str) -> str:
    """Best-effort lookup of a human-readable voice name for the manifest."""
    try:
        voices = client._sdk.voices.get_all()
        for v in getattr(voices, "voices", []):
            if getattr(v, "voice_id", None) == voice_id:
                return getattr(v, "name", voice_id) or voice_id
    except Exception:  # noqa: BLE001 - name lookup is cosmetic, never fatal
        pass
    return voice_id


def _quota(client: TTSClient) -> tuple[int, int] | None:
    try:
        user = client._sdk.user.get()
        sub = getattr(user, "subscription", None)
        used = getattr(sub, "character_count", None)
        limit = getattr(sub, "character_limit", None)
        if used is not None and limit is not None:
            return int(used), int(limit)
    except Exception:  # noqa: BLE001 - quota report is best-effort
        pass
    return None


def _write_manifest(
    *,
    zh_voice_id: str,
    zh_voice_name: str,
    zh_voice_note: str,
    model_id: str,
    quota_before: tuple[int, int] | None,
    quota_after: tuple[int, int] | None,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    before_s = f"{quota_before[0]}/{quota_before[1]}" if quota_before else "unknown"
    after_s = f"{quota_after[0]}/{quota_after[1]}" if quota_after else "unknown"
    spent = (
        str(quota_after[0] - quota_before[0])
        if quota_before and quota_after
        else "unknown"
    )

    content = f"""# Sample audio manifest

Regenerated by `scripts/generate_samples.py` on {now}. This file is the
source of truth for exactly what produced the committed `.mp3` files below —
regenerate it any time by re-running the script (it overwrites both).

## samples/sample_zh_tw.mp3 (Traditional Chinese)

- **Voice**: {zh_voice_name} (`{zh_voice_id}`) — {zh_voice_note}
- **Model**: `{model_id}`
- **Language code**: `zh`
- **Text**: "{ZH_TEXT}"

## samples/sample_en.mp3 (English)

- **Voice**: {zh_voice_name} (`{zh_voice_id}`) — same pinned voice as above (single-voice account on the free plan)
- **Model**: `{model_id}`
- **Language code**: `en`
- **Text**: "{EN_TEXT}"

## Quota

- Before this run: {before_s} characters used
- After this run: {after_s} characters used
- Spent generating these two samples: {spent} characters

## Provenance & known limitation

Both files were generated with a real call to the ElevenLabs Text-to-Speech
API (free tier) — see the "ElevenLabs" attribution line in the top-level
README.

**Taiwanese-Mandarin accent was attempted but is not achievable on the free
plan.** A Taiwanese-Mandarin voice ("Yu", accent `taiwan mandarin`) was found
in the ElevenLabs shared voice library via `client.voices.get_shared(search=
"Taiwan")` and successfully added to this account with `client.voices.share(
...)`. However, calling `text_to_speech.convert()` with that voice_id fails
with `402 payment_required` / `paid_plan_required`: *"Free users cannot use
library voices via the API. Please upgrade your subscription to use this
voice."* This was confirmed across three different shared-library voices
(Yu, Yi Min, Stacy) — it is a plan-wide API restriction, not specific to one
voice. The `free_users_allowed` flag returned by `get_shared()` does **not**
reflect API usability (it was `true` for all three, yet all three 402'd).

The samples above therefore use {zh_voice_name}, an official **premade**
voice bundled with every ElevenLabs account (including free), which the API
accepts on any plan. It has no Taiwanese accent. Getting a Taiwanese-Mandarin
accent working would require upgrading to a paid ElevenLabs plan (Starter or
above) and re-running this script with `ELEVENLABS_VOICE_ID=fQj4gJSexpu8RDE2Ii5m`
(the "Yu" voice, already added to this account's My Voices).
"""
    MANIFEST_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH}")


def main() -> int:
    setup_logging()
    try:
        settings = Settings.from_env()
    except TTSError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    sync_client = TTSClient(settings)
    quota_before = _quota(sync_client)

    zh_voice_id, zh_voice_note = _resolve_zh_voice(sync_client)
    zh_voice_name = _voice_name(sync_client, zh_voice_id)

    async_client = AsyncTTSClient(settings)
    requests = [
        SynthesisRequest(
            text=ZH_TEXT,
            out_path=SAMPLES_DIR / "sample_zh_tw.mp3",
            voice_id=zh_voice_id,
            language_code="zh",
        ),
        SynthesisRequest(
            text=EN_TEXT,
            out_path=SAMPLES_DIR / "sample_en.mp3",
            language_code="en",
        ),
    ]

    summary = asyncio.run(synthesize_batch_async(async_client, requests, concurrency=2))
    for r in summary.results:
        status = "ok" if r.ok else f"FAILED ({type(r.error).__name__}: {r.error})"
        print(f"  {r.request.out_path.name}: {status}")

    quota_after = _quota(sync_client)

    print(f"\nModel: {settings.model_id}")
    print(f"Voice (zh): {zh_voice_name} ({zh_voice_id}) — {zh_voice_note}")
    if quota_before and quota_after:
        print(f"Quota before: {quota_before[0]}/{quota_before[1]}")
        print(f"Quota after:  {quota_after[0]}/{quota_after[1]}")
    print(f"Done: {len(summary.succeeded)} ok, {len(summary.failed)} failed.")

    if not summary.failed:
        _write_manifest(
            zh_voice_id=zh_voice_id,
            zh_voice_name=zh_voice_name,
            zh_voice_note=zh_voice_note,
            model_id=settings.model_id,
            quota_before=quota_before,
            quota_after=quota_after,
        )

    return 0 if not summary.failed else 1


if __name__ == "__main__":
    sys.exit(main())
