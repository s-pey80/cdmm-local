"""Local vision description for photos — mlx-vlm (Qwen3-VL-4B-Instruct),
same local/Apple-Silicon-native pattern as mlx-whisper for transcription.

Uses a plain free-text description prompt rather than cdmm-legacy's rigid
CHART/SCREENER/RESEARCH/... JSON-mode-classification prompt (see
cdmm-legacy/cdmm-data-ingestor/src/scripts/enrich.py's VISION_SYSTEM_PROMPT)
-- that prompt was tuned for GPT-4o Vision specifically, and a fixed
7-category JSON schema is a much easier target to hit reliably for a larger
model than a 4B local one. A free-text description search still supports the
same goal (finding a photo by content later, e.g. "find all BTC charts
posted") via search_media_descriptions/semantic_search in mcp_server.py.

Usage:
    python src/vision.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
from mlx_vlm import generate, load
from mlx_vlm.prompt_utils import apply_chat_template

from db import ensure_tables, get_unanalyzed_photos, set_media_description
from idle_unload import touch

load_dotenv()

MODEL = os.environ.get("MLX_VLM_MODEL", "mlx-community/Qwen3-VL-4B-Instruct-4bit")

DESCRIPTION_PROMPT = (
    "Describe this image concisely for search purposes. If it's a financial "
    "chart, screenshot, or trading screen, mention the asset/ticker, "
    "timeframe, and any visible price levels or indicators. If it's a "
    "screenshot of text (a tweet, article, chat, table), transcribe the key "
    "text content. Otherwise, just describe what's shown. 2-4 sentences."
)

_model = None
_processor = None


def _get_model():
    """Lazy-loaded singleton — mirrors mcp_server.py's _get_embed_model()
    pattern, so a live per-message call doesn't reload the model from disk
    each time within one process."""
    global _model, _processor
    if _model is None:
        _model, _processor = load(MODEL)
    return _model, _processor


def describe_one(image_path: str) -> str:
    """Single-photo description — used both by the batch runner below and by
    hydration.py's live per-message path."""
    if not Path(image_path).exists():
        raise FileNotFoundError(image_path)
    touch("vision")
    model, processor = _get_model()
    formatted_prompt = apply_chat_template(processor, model.config, DESCRIPTION_PROMPT, num_images=1)
    result = generate(model, processor, formatted_prompt, image=[image_path], verbose=False)
    touch("vision")
    return result.text.strip()


def run_vision(limit: int = 50) -> int:
    ensure_tables()
    rows = get_unanalyzed_photos(limit=limit)
    print(f"Vision: {len(rows)} photos to process")

    done = 0
    for chat_id, message_id, media_path in rows:
        if not media_path or not Path(media_path).exists():
            continue
        try:
            description = describe_one(media_path)
            set_media_description(chat_id, message_id, description)
            done += 1
            print(f"  [{done}/{len(rows)}] chat={chat_id} msg={message_id} ok")
        except Exception as e:
            print(f"  FAILED chat={chat_id} msg={message_id}: {e}")

    print(f"Vision done. {done} photos described.")
    return done


if __name__ == "__main__":
    run_vision()
