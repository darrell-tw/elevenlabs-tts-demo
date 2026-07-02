"""Command-line interface.

    eleven-tts say "你好，歡迎使用" --out out/hello.mp3
    eleven-tts say --text-file script.txt --voice <id> --language zh
    eleven-tts voices --search Taiwan
    eleven-tts batch --input lines.txt --out-dir out/ --concurrency 3

Configuration (API key etc.) comes from the environment / .env. Failures are
reported as a single clear line and an exit code — never a raw traceback.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from .client import AsyncTTSClient, TTSClient
from .config import Settings
from .errors import ConfigError, TTSError
from .logconf import get_logger, setup_logging
from .synth import SynthesisRequest, synthesize_batch_async
from .voices import list_voices, search_voices

_log = get_logger("eleven_tts.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eleven-tts", description="ElevenLabs Text-to-Speech integration demo."
    )
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    parser.add_argument("--json-logs", action="store_true", help="emit logs as JSON lines")
    sub = parser.add_subparsers(dest="command", required=True)

    # say
    p_say = sub.add_parser("say", help="synthesize a single piece of text to one file")
    src = p_say.add_mutually_exclusive_group(required=True)
    src.add_argument("text", nargs="?", help="text to synthesize")
    src.add_argument("--text-file", type=Path, help="read text from this file")
    p_say.add_argument("--voice", help="voice id (overrides ELEVENLABS_VOICE_ID)")
    p_say.add_argument("--model", help="model id (overrides default)")
    p_say.add_argument("--format", dest="output_format", help="output format")
    p_say.add_argument("--language", help="ISO 639-1 language code (e.g. zh, en)")
    p_say.add_argument("--out", type=Path, default=Path("out/output.mp3"), help="output file")

    # voices
    p_voices = sub.add_parser("voices", help="list or search available voices")
    p_voices.add_argument("--search", help="search query (e.g. 'Taiwan')")

    # batch
    p_batch = sub.add_parser("batch", help="synthesize many lines concurrently (async)")
    p_batch.add_argument("--input", type=Path, required=True, help="file with one text per line")
    p_batch.add_argument("--out-dir", type=Path, default=Path("out"), help="output directory")
    p_batch.add_argument("--voice", help="voice id for all items")
    p_batch.add_argument("--model", help="model id for all items")
    p_batch.add_argument("--format", dest="output_format", help="output format for all items")
    p_batch.add_argument("--language", help="ISO 639-1 language code for all items")
    p_batch.add_argument("--concurrency", type=int, help="max in-flight requests")

    return parser


def _read_text(args: argparse.Namespace) -> str:
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8")
    return args.text


def _cmd_say(settings: Settings, args: argparse.Namespace) -> int:
    client = TTSClient(settings)
    path = client.synthesize_to_file(
        _read_text(args),
        args.out,
        voice_id=args.voice,
        model_id=args.model,
        output_format=args.output_format,
        language_code=args.language,
    )
    print(f"Wrote {path}")
    return 0


def _cmd_voices(settings: Settings, args: argparse.Namespace) -> int:
    client = TTSClient(settings)
    voices = search_voices(client, query=args.search) if args.search else list_voices(client)
    if not voices:
        print("No voices found.")
        return 0
    for v in voices:
        print(v.describe())
    return 0


def _cmd_batch(settings: Settings, args: argparse.Namespace) -> int:
    lines = [
        line.strip()
        for line in Path(args.input).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not lines:
        print("Input file has no non-empty lines.", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    requests = [
        SynthesisRequest(
            text=line,
            out_path=out_dir / f"{i:03d}.mp3",
            voice_id=args.voice,
            model_id=args.model,
            output_format=args.output_format,
            language_code=args.language,
        )
        for i, line in enumerate(lines, start=1)
    ]

    client = AsyncTTSClient(settings)
    summary = asyncio.run(
        synthesize_batch_async(client, requests, concurrency=args.concurrency)
    )

    for r in summary.results:
        if r.ok:
            print(f"  ok    {r.path}")
        else:
            print(f"  FAIL  {r.request.out_path}: {type(r.error).__name__}: {r.error}")
    print(f"\nBatch done: {len(summary.succeeded)} ok, {len(summary.failed)} failed.")
    return 0 if not summary.failed else 1


_COMMANDS = {"say": _cmd_say, "voices": _cmd_voices, "batch": _cmd_batch}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    setup_logging(
        level=logging.DEBUG if args.verbose else logging.INFO, json=args.json_logs
    )

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        return _COMMANDS[args.command](settings, args)
    except TTSError as exc:
        # Typed, actionable failure — no traceback for the user.
        print(f"Error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
