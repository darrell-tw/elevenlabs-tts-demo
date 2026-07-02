"""Clean integration layer for the ElevenLabs Text-to-Speech API.

Public surface:
    Settings              - configuration loaded from environment / .env
    TTSClient             - synchronous client (retry + typed errors)
    AsyncTTSClient        - asynchronous client (concurrency-limited batches)
    SynthesisRequest      - one unit of work for batch synthesis
    errors                - typed exception hierarchy
"""

from .config import Settings
from .client import TTSClient, AsyncTTSClient
from .synth import SynthesisRequest, synthesize_batch, synthesize_batch_async
from . import errors

__all__ = [
    "Settings",
    "TTSClient",
    "AsyncTTSClient",
    "SynthesisRequest",
    "synthesize_batch",
    "synthesize_batch_async",
    "errors",
]
