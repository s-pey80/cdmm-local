"""Reactive ingestion listener — reacts to new/edited messages in real time via
Telethon's events.NewMessage, instead of polling. Run continuously under launchd
(see launchd/com.cdmm.listener.plist).

On startup, runs a backfill pass first to catch up on anything missed while the
listener was down (message-ID-based, so it's crash-proof — see backfill.py).

Usage:
    python src/listener.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
from telethon import TelegramClient, events

from config import CHAT_NAMES, MONITORED_CHAT_IDS
from db import ensure_tables
from embed import embed_one
from hydration import hydrate_media
from ingest import process_message

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["TELEGRAM_PHONE"]
SESSION_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sessions", "telegram_session")

# Fire-and-forget hydration/embed tasks must be kept referenced somewhere or
# asyncio can garbage-collect them mid-run — this set is that reference.
_background_tasks: set[asyncio.Task] = set()

_HYDRATED_MEDIA_TYPES = ("voice", "audio", "video_note", "photo")


def _chat_name(chat_id: int) -> str:
    return CHAT_NAMES.get(chat_id, str(chat_id))


def _spawn_hydration(chat_id: int, message_id: int, media_type: str | None, media_path: str | None) -> None:
    """Kicks off transcription/vision as a background task, not awaited —
    the listener keeps processing new messages while this runs. Embedding
    happens at the end of hydrate_media() itself, once the transcript/
    description it produces actually exists."""
    if media_type not in _HYDRATED_MEDIA_TYPES or not media_path:
        return
    task = asyncio.create_task(hydrate_media(chat_id, message_id, media_type, media_path))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _spawn_embed(chat_id: int, message_id: int) -> None:
    """Embeds immediately as a background task — for messages that don't go
    through hydration (plain text, edits, or media types hydrate_media
    doesn't handle) there's no transcript/description to wait for."""
    task = asyncio.create_task(_embed_one_safe(chat_id, message_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _embed_one_safe(chat_id: int, message_id: int) -> None:
    try:
        await asyncio.to_thread(embed_one, chat_id, message_id)
    except Exception as e:
        print(f"  ERROR embedding chat={chat_id} msg={message_id}: {e}")


async def main() -> None:
    ensure_tables()

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start(phone=PHONE)
    print("Telegram client connected.")

    # Catch up on anything sent while the listener was down before going live.
    from backfill import run_backfill
    await run_backfill(client)

    @client.on(events.NewMessage(chats=MONITORED_CHAT_IDS))
    async def on_new_message(event):
        chat_id = event.chat_id
        chat_name = _chat_name(chat_id)
        try:
            ingested, media_type, media_path = await process_message(client, event.message, chat_id, chat_name)
            if ingested:
                print(f"[{chat_name}] msg {event.message.id} ingested")
                if media_type in _HYDRATED_MEDIA_TYPES and media_path:
                    _spawn_hydration(chat_id, event.message.id, media_type, media_path)
                else:
                    _spawn_embed(chat_id, event.message.id)
        except Exception as e:
            print(f"  ERROR processing msg in {chat_name}: {e}")

    @client.on(events.MessageEdited(chats=MONITORED_CHAT_IDS))
    async def on_edited_message(event):
        chat_id = event.chat_id
        chat_name = _chat_name(chat_id)
        try:
            # Not re-hydrated on edit — an edited caption doesn't change the
            # media itself, and re-transcribing/re-describing unchanged media
            # would just waste compute. upsert_message's own edit handling
            # already nulls out `embedding` on a real text edit, so re-embed
            # here to pick that up (recombines the new text with whatever
            # transcript/media_description already exists).
            await process_message(client, event.message, chat_id, chat_name)
            print(f"[{chat_name}] msg {event.message.id} edit captured")
            _spawn_embed(chat_id, event.message.id)
        except Exception as e:
            print(f"  ERROR processing edit in {chat_name}: {e}")

    print(f"Listening on {len(MONITORED_CHAT_IDS)} chats...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
