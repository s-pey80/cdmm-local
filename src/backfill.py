"""Historical catch-up — pulls all messages since the last-seen message_id for each
chat. Message-ID-based (not timestamp-based), so it's crash-proof: however long the
listener was down, resuming from MAX(message_id) can't leave a gap the way a
timestamp-plus-buffer approach can (see old cdmm-legacy's NEXT_STEPS.md for the bug
this replaces).

A chat that has never been ingested (no rows yet) pulls its FULL history — this is
meant to be run once to seed data/cdmm.db with everything, then the listener takes
over incrementally. Use --days to cap the first-run pull instead (e.g. for a quick
test import).

Usage:
    python src/backfill.py            # full history on first run, incremental after
    python src/backfill.py --days 7   # cap first-run pull to the last N days

Also imported by listener.py to catch up on startup before going live.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
from telethon.errors import FloodWaitError

from config import CHAT_NAMES, MONITORED_CHAT_IDS
from db import ensure_tables, get_last_message_id
from ingest import process_message

DELAY_BETWEEN_CHATS = 2
DELAY_EVERY_N_MESSAGES = 100
DELAY_PER_BATCH = 1
MAX_RETRIES = 3

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE = os.environ["TELEGRAM_PHONE"]
SESSION_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sessions", "telegram_session")


async def run_backfill(client, first_run_lookback_days: int | None = None) -> int:
    """Runs one backfill pass over every monitored chat using an already-connected
    client. Returns total messages ingested/updated.

    first_run_lookback_days: if set, caps the pull for chats with no rows yet to the
    last N days. If None (default), a never-ingested chat pulls its full history."""
    ensure_tables()
    total = 0

    # Telethon can't resolve an entity from a bare ID unless it's already cached
    # (from a prior interaction in this session) — a fresh session fails on DMs
    # and channels the account hasn't recently touched. get_dialogs() populates
    # that cache for everything the account is a member of.
    await client.get_dialogs()

    for chat_id in MONITORED_CHAT_IDS:
        chat_name = CHAT_NAMES.get(chat_id, str(chat_id))
        last_id = get_last_message_id(chat_id)

        if last_id == 0:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=first_run_lookback_days)
                if first_run_lookback_days else None
            )
            label = f"last {first_run_lookback_days} days" if first_run_lookback_days else "full history"
            print(f"\n[{chat_name}] first run — fetching {label}...")
        else:
            cutoff = None
            print(f"\n[{chat_name}] fetching since message {last_id}...")

        count = 0
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                entity = await client.get_entity(chat_id)
            except Exception as e:
                print(f"  WARNING: could not resolve entity {chat_id}: {e}")
                break

            try:
                kwargs = {"min_id": last_id, "reverse": True} if last_id else {"reverse": True, "offset_date": cutoff}
                async for msg in client.iter_messages(entity, **kwargs):
                    ingested, _media_type, _media_path = await process_message(client, msg, chat_id, chat_name)
                    if ingested:
                        count += 1
                        print(f"  msg {msg.id} ({count} total)", end="\r", flush=True)
                        if count % DELAY_EVERY_N_MESSAGES == 0:
                            await asyncio.sleep(DELAY_PER_BATCH)
                break

            except FloodWaitError as e:
                wait = e.seconds + 5
                print(f"  FloodWait: sleeping {wait}s (attempt {attempt}/{MAX_RETRIES})")
                await asyncio.sleep(wait)
            except Exception as e:
                if attempt < MAX_RETRIES:
                    wait = 5 * attempt
                    print(f"  Connection error ({e}), retrying in {wait}s (attempt {attempt}/{MAX_RETRIES})")
                    await asyncio.sleep(wait)
                else:
                    print(f"  ERROR: gave up on {chat_name} after {MAX_RETRIES} attempts: {e}")

        print(f"  Ingested/updated {count} messages.")
        total += count
        await asyncio.sleep(DELAY_BETWEEN_CHATS)

    print(f"\nBackfill done. Total: {total} messages ingested/updated.")
    return total


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="Cap the first-run pull to the last N days (default: full history)")
    args = parser.parse_args()

    from telethon import TelegramClient
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start(phone=PHONE)
    print("Telegram client connected.")
    try:
        await run_backfill(client, first_run_lookback_days=args.days)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(_main())
