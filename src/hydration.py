"""Fire-and-forget media hydration (transcription + vision description),
triggered live by listener.py right after a new photo/voice-note/video-note
ingests. Runs as asyncio.create_task() — no external queue needed for two job
types at this volume; the event loop itself is the queue. The listener keeps
a strong reference to each task (see listener.py) so it can't be
garbage-collected mid-run, a well-known asyncio footgun for fire-and-forget
tasks.

Retry: 3 attempts per item, short backoff between them. After the 3rd
failure, the column is set to a distinguishable failure sentinel instead of
staying NULL — leaving it NULL would make every future batch run (or another
live attempt) retry a permanently-broken file forever.

Also embeds the message once hydration finishes (success or sentinel) — see
the `finally` block below — so a voice note/photo becomes searchable via
semantic_search without a manual embed.py run.
"""
import asyncio
import logging

from db import set_media_description, set_transcript
from embed import embed_one

log = logging.getLogger("hydration")

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5


async def hydrate_media(chat_id: int, message_id: int, media_type: str, media_path: str) -> None:
    if media_type in ("voice", "audio", "video_note"):
        kind, run_one, save = "transcript", _transcribe_one, set_transcript
    elif media_type == "photo":
        kind, run_one, save = "vision description", _describe_one, set_media_description
    else:
        return  # video/document/other — nothing to hydrate

    try:
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                result = await run_one(media_path)
                save(chat_id, message_id, result)
                log.info("chat=%s msg=%s %s hydrated (attempt %d)", chat_id, message_id, kind, attempt)
                return
            except Exception as e:
                last_error = e
                log.warning(
                    "chat=%s msg=%s %s attempt %d/%d failed: %s",
                    chat_id, message_id, kind, attempt, MAX_ATTEMPTS, e,
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS)

        sentinel = f"[{kind} failed after {MAX_ATTEMPTS} attempts: {last_error}]"
        save(chat_id, message_id, sentinel)
        log.error("chat=%s msg=%s %s permanently failed, wrote sentinel", chat_id, message_id, kind)
    finally:
        # Embed now that transcript/media_description exists (or a failure
        # sentinel does) — runs exactly once, on every exit path.
        try:
            await asyncio.to_thread(embed_one, chat_id, message_id)
        except Exception as e:
            log.warning("chat=%s msg=%s embedding failed: %s", chat_id, message_id, e)


async def _transcribe_one(media_path: str) -> str:
    from transcribe import transcribe_one
    return await asyncio.to_thread(transcribe_one, media_path)


async def _describe_one(media_path: str) -> str:
    from vision import describe_one
    return await asyncio.to_thread(describe_one, media_path)
