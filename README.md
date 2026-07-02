# ElevenLabs TTS Integration Demo

A small, production-shaped Python integration with the [ElevenLabs](https://elevenlabs.io) Text-to-Speech API.

The point of this repo isn't feature count — it's **clean integration engineering**: typed error handling, retry with exponential backoff, concurrency-limited async batches, structured logging, environment-based config, a tested core, and a small CLI. It is bilingual by design and ships **Traditional-Chinese** and **English** samples (see [Known limitation](#known-limitation-no-taiwanese-mandarin-accent-on-the-free-plan) for why the Chinese sample doesn't have a Taiwanese accent on the free tier).

Runtime dependencies are intentionally minimal: only the official `elevenlabs` SDK. Everything else (config, retry, logging, CLI) is the Python standard library, so the integration surface is easy to audit.

## How it works

```
text ──▶ validate ──▶ ┌─────────────── retry / backoff ───────────────┐ ──▶ collect bytes ──▶ .mp3
                      │  ElevenLabs SDK  text_to_speech.convert(...)   │
                      └───────────────────────────────────────────────┘
                                          │ on failure
                                          ▼
                       classify ── 401 auth · 403 perm · 422 validation
                                   429 rate-limit · 5xx server · timeout · quota
                              (retryable errors are retried; the rest fail fast)
```

The async client adds an `asyncio.Semaphore` so batch synthesis fans out but never exceeds a configured number of in-flight requests.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # then edit .env and add your ELEVENLABS_API_KEY
```

Get a free API key at <https://elevenlabs.io/app/settings/api-keys>. Never paste the key into a chat or commit it — it lives only in `.env` (gitignored).

```bash
# Single line → one file
eleven-tts say "第一步，決定了之後的一切。" --language zh --out out/hello.mp3

# List/search voices already in *your* account (not the shared library —
# see "Known limitation" below for why a fresh account can't get a
# Taiwanese-Mandarin voice this way on the free tier)
eleven-tts voices --search Taiwan

# Concurrent batch (async) from a file of one-line-per-utterance
eleven-tts batch --input examples/lines.txt --out-dir out/ --concurrency 3
```

## Library API

```python
from eleven_tts import Settings, TTSClient, AsyncTTSClient
from eleven_tts.synth import SynthesisRequest, synthesize_batch_async
import asyncio

settings = Settings.from_env()

# Sync
TTSClient(settings).synthesize_to_file("Hello there.", "out/en.mp3")

# Async, concurrency-limited batch
client = AsyncTTSClient(settings)
requests = [
    SynthesisRequest(text="Hello there.", out_path="out/en.mp3"),
    SynthesisRequest(text="你好，世界。", out_path="out/zh.mp3", language_code="zh"),
]
summary = asyncio.run(synthesize_batch_async(client, requests, concurrency=3))
print(len(summary.succeeded), "ok,", len(summary.failed), "failed")
```

## Configuration

All settings come from the environment or `.env` (real env vars win). Only the key is required.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ELEVENLABS_API_KEY` | — (required) | API key |
| `ELEVENLABS_VOICE_ID` | George (`JBFqnCBsd6RMkjVDRZzb`) | default voice |
| `ELEVENLABS_MODEL_ID` | `eleven_multilingual_v2` | default model (handles Traditional Chinese) |
| `ELEVENLABS_OUTPUT_FORMAT` | `mp3_44100_128` | audio output format |
| `ELEVENLABS_MAX_RETRIES` | `4` | retry attempts for retryable errors |
| `ELEVENLABS_MAX_CONCURRENCY` | `3` | max in-flight async requests |
| `ELEVENLABS_REQUEST_TIMEOUT` | `30` | per-request timeout (seconds) |

## Error handling

Every failure becomes a typed exception under `eleven_tts.errors.TTSError` — callers never see a raw SDK traceback.

| Condition | Exception | Retried? |
|-----------|-----------|----------|
| Empty / too-long text | `ValidationError` | no (caught before the API call) |
| 401 | `AuthenticationError` | no |
| 401/402/429 with quota body | `QuotaExceededError` | no |
| 403 | `PermissionError` | no |
| 400 / 422 | `ValidationError` | no |
| 429 | `RateLimitError` (honors `Retry-After`) | yes |
| 5xx | `ServerError` | yes |
| timeout / connection drop | `NetworkError` | yes |

## Testing

```bash
pytest                  # unit tests only — no API key required (default)
pytest -m integration   # real API calls — requires ELEVENLABS_API_KEY
```

Unit tests inject a fake SDK client, so validation, error classification, retry, and async concurrency are all verified without spending any quota. The integration suite proves the repo actually talks to ElevenLabs end-to-end.

## Samples

Both files were generated with a real, successful call to the ElevenLabs
Text-to-Speech API on a free-tier account — nothing here is mocked or faked.
Sample audio generated with ElevenLabs.

| File | Voice | Model | Text |
|---|---|---|---|
| [`samples/sample_zh_tw.mp3`](samples/sample_zh_tw.mp3) | George (`JBFqnCBsd6RMkjVDRZzb`) | `eleven_multilingual_v2` | 第一步，往往決定了之後的一切。歡迎使用 ElevenLabs 文字轉語音示範。 |
| [`samples/sample_en.mp3`](samples/sample_en.mp3) | George (`JBFqnCBsd6RMkjVDRZzb`) | `eleven_multilingual_v2` | The first step often decides everything that follows. Welcome to this ElevenLabs text-to-speech demo. |

See [`samples/MANIFEST.md`](samples/MANIFEST.md) for the generation timestamp
and exact quota spent producing these files.

### Regenerating them

```bash
python scripts/generate_samples.py   # writes samples/sample_zh_tw.mp3 + samples/sample_en.mp3 + samples/MANIFEST.md
```

The voice is read from `ELEVENLABS_VOICE_ID` in `.env` so re-runs are
deterministic (no "search and pick whatever comes back first"). If unset, it
falls back to searching this account's own **premade** voices only.

### Known limitation: no Taiwanese-Mandarin accent on the free plan

The original goal was a Taiwanese-Mandarin-accented voice. Three
spec-recommended candidates from the ElevenLabs shared voice library — **Yu**
(`fQj4gJSexpu8RDE2Ii5m`), **Yi Min** (`ZQ45Xiky4ENZqOdRnyjs`), and **Stacy**
(`hkfHEbBvdQFNX4uWHqRF`) — were located with `client.voices.get_shared(search=
"Taiwan")` and each was successfully added to the account's own voice list
with `client.voices.share(public_user_id, voice_id, new_name=...)` (the SDK
method literally named `share` is actually "add a shared voice to your
collection").

Adding the voice succeeds, but **synthesizing with it does not**: the API
rejects every one of them at `text_to_speech.convert()` with `402
payment_required` / `paid_plan_required`:

> Free users cannot use library voices via the API. Please upgrade your subscription to use this voice.

This held for all three voices tested, so it's a plan-wide restriction on
using *any* shared-library ("professional" category) voice through the API on
the free tier — not a quirk of one voice. Note that `get_shared()` returns a
`free_users_allowed` flag that was `true` for all three candidates; that flag
does **not** predict API usability and should not be trusted for this
purpose.

**Workaround / path to actually get the accent**: upgrade to a paid
ElevenLabs plan (Starter or above), then set
`ELEVENLABS_VOICE_ID=fQj4gJSexpu8RDE2Ii5m` in `.env` and re-run
`python scripts/generate_samples.py` — the voice is already added to this
account, so no further setup is needed once the plan supports it.

The committed samples instead use **George**, an official premade voice
bundled with every ElevenLabs account (including free), which the API
accepts on any plan — it has no Taiwanese accent, but it is genuinely
synthesized via the real API, on the real free tier, with no workaround or
substitution of a different provider.

## Project layout

```
src/eleven_tts/
  config.py     env / .env loading → Settings
  errors.py     typed exception hierarchy + classify_api_error()
  retry.py      sync + async retry with backoff & jitter
  client.py     TTSClient / AsyncTTSClient (validate → SDK → bytes)
  synth.py      batch synthesis (sync sequential, async concurrency-capped)
  voices.py     list / search voices
  cli.py        `eleven-tts` command (say / voices / batch)
  logconf.py    structured stdlib logging
tests/          unit tests (no key) + integration tests (-m integration)
scripts/        generate_samples.py
```

## Design choices

- **Injectable SDK client** (`sdk_client=`) makes the integration logic unit-testable without a network or key.
- **Typed, retryable-aware errors** keep retry policy in one place — retry transient failures, fail fast on auth/validation/quota.
- **Full-jitter backoff** with a hard ceiling avoids thundering-herd retries.
- **Minimal dependencies** keep the security/audit surface small.

## License

MIT
