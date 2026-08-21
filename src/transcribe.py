"""Local transcription for voice/audio messages — mlx-whisper instead of Azure
Speech, matching what cdmm-legacy had already decided (see its .env: "transcription
moves to local mlx-whisper on Mac Mini"). Apple-Silicon-native via MLX, no
build-from-source step, and this Mac already has the large-v3-turbo model cached.

Vision/photo enrichment was dropped entirely — Claude reads images natively via
the Read tool, no pre-computed description needed.

Usage:
    python src/transcribe.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import mlx_whisper
from dotenv import load_dotenv

from db import ensure_tables, get_untranscribed, set_transcript

load_dotenv()

MODEL = os.environ.get("MLX_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")


def transcribe_one(media_path: str) -> str:
    """Single-file transcription — used both by the batch runner below and by
    hydration.py's live per-message path. mlx_whisper.transcribe() loads the
    model internally; MLX caches it process-wide after the first call, so
    this doesn't reload from disk on every invocation within one process."""
    if not Path(media_path).exists():
        raise FileNotFoundError(media_path)
    result = mlx_whisper.transcribe(media_path, path_or_hf_repo=MODEL)
    return result["text"].strip()


def run_transcription(limit: int = 50) -> int:
    ensure_tables()
    rows = get_untranscribed(limit=limit)
    print(f"Transcription: {len(rows)} messages to process")

    done = 0
    for chat_id, message_id, media_path in rows:
        if not media_path or not Path(media_path).exists():
            continue
        try:
            transcript = transcribe_one(media_path)
            set_transcript(chat_id, message_id, transcript)
            done += 1
            print(f"  [{done}/{len(rows)}] chat={chat_id} msg={message_id} ok")
        except Exception as e:
            print(f"  FAILED chat={chat_id} msg={message_id}: {e}")

    print(f"Transcription done. {done} messages transcribed.")
    return done


if __name__ == "__main__":
    run_transcription()
