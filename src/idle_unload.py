"""Drops the lazy-loaded models (embedding, vision, whisper) once they've sat
unused for a while, so the long-running listener doesn't hold several GB of
weights between the occasional photo or voice note. Mirrors srpbot's
worker.unload_idle(). The next call just reloads from the local HF cache.

embed.py, vision.py and transcribe.py call touch() before and after each use;
listener.py calls unload_idle() on a timer. A model is only dropped by clearing
the module-level reference, so an in-flight call (which holds its own local
reference) finishes normally.
"""
import gc
import os
import sys
import time

UNLOAD_AFTER_SECONDS = int(os.environ.get("MODEL_UNLOAD_AFTER_SECONDS", "600"))

_last_used: dict[str, float] = {}


def touch(name: str) -> None:
    _last_used[name] = time.monotonic()


def unload_idle(now: float | None = None) -> list[str]:
    """Drop models unused for UNLOAD_AFTER_SECONDS. Returns what was unloaded."""
    now = time.monotonic() if now is None else now
    idle = lambda name: now - _last_used.get(name, now) >= UNLOAD_AFTER_SECONDS
    freed = []

    embed = sys.modules.get("embed")
    if embed is not None and embed._model is not None and idle("embed"):
        embed._model = None
        freed.append("embed")

    vision = sys.modules.get("vision")
    if vision is not None and vision._model is not None and idle("vision"):
        vision._model, vision._processor = None, None
        freed.append("vision")

    # mlx_whisper caches its model process-wide on ModelHolder, not in transcribe.py
    whisper = sys.modules.get("mlx_whisper.transcribe")
    holder = getattr(whisper, "ModelHolder", None)
    if holder is not None and holder.model is not None and idle("whisper"):
        holder.model, holder.model_path = None, None
        freed.append("whisper")

    if freed:
        gc.collect()
        mx = sys.modules.get("mlx.core")
        if mx is not None and hasattr(mx, "clear_cache"):
            mx.clear_cache()  # hand MLX's freed buffers back to the system
        torch = sys.modules.get("torch")
        if torch is not None and torch.backends.mps.is_available():
            torch.mps.empty_cache()  # same for sentence-transformers on MPS
        print(f"Unloaded {', '.join(freed)} after {UNLOAD_AFTER_SECONDS}s idle")
    return freed
