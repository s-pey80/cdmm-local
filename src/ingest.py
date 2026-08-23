"""Shared message-processing logic used by both listener.py (live) and backfill.py (historical)."""
import io

from telethon.tl.types import MessageMediaWebPage, MessageService

from db import upsert_message
from media_store import save_media

_MEDIA_EXT = {
    "photo": "jpg",
    "video": "mp4",
    "audio": "ogg",
    "document": "bin",
}


def detect_media_type(msg) -> str | None:
    """None for a link-preview webpage — Telethon's msg.photo/video/audio/
    document properties all transparently unwrap a webpage preview's embedded
    thumbnail/document (see their own docstrings), which would otherwise get
    misclassified as real attached media. Must check this before any of
    those properties, not after."""
    if isinstance(msg.media, MessageMediaWebPage):
        return None
    if msg.photo:
        return "photo"
    if msg.video:
        return "video"
    if msg.audio:
        return "audio"
    if msg.document:
        doc = msg.document
        if doc and hasattr(doc, "attributes"):
            for attr in doc.attributes:
                type_name = type(attr).__name__
                if type_name == "DocumentAttributeAudio":
                    return "voice" if getattr(attr, "voice", False) else "audio"
                if type_name == "DocumentAttributeVideo":
                    return "video_note" if getattr(attr, "round_message", False) else "video"
        return "document"
    if msg.media:
        return "other"
    return None


async def process_message(client, msg, chat_id: int, chat_name: str) -> tuple[bool, str | None, str | None]:
    """Downloads media (if any) and upserts the message row. Returns
    (ingested, media_type, media_path) — ingested is False for MessageService
    events (joins/leaves/pins), which are skipped entirely. media_type/
    media_path let the caller (listener.py) decide whether to kick off
    transcription/vision hydration without re-deriving anything."""
    if isinstance(msg, MessageService):
        return False, None, None

    sender_id = msg.sender_id
    sender_name = None
    if msg.sender:
        first = getattr(msg.sender, "first_name", "") or ""
        last = getattr(msg.sender, "last_name", "") or ""
        username = getattr(msg.sender, "username", "") or ""
        sender_name = (f"{first} {last}".strip() or username) or None

    media_type = detect_media_type(msg)
    media_path = None
    if media_type:
        ext = _MEDIA_EXT.get(media_type, "bin")
        filename = f"{media_type}.{ext}"
        try:
            buf = io.BytesIO()
            await client.download_media(msg, file=buf)
            media_path = save_media(chat_id, msg.id, filename, buf.getvalue())
        except Exception as e:
            print(f"  WARNING: media download failed for msg {msg.id}: {e}")

    reply_to_msg_id = None
    if msg.reply_to and hasattr(msg.reply_to, "reply_to_msg_id"):
        reply_to_msg_id = msg.reply_to.reply_to_msg_id

    try:
        raw_json = msg.to_json()
    except Exception:
        raw_json = None

    upsert_message(
        message_id=msg.id,
        chat_id=chat_id,
        chat_name=chat_name,
        sender_id=sender_id,
        sender_name=sender_name,
        sent_at=msg.date,
        text=msg.text,
        media_type=media_type,
        media_path=media_path,
        raw_json=raw_json,
        edited_at=msg.edit_date,
        reply_to_msg_id=reply_to_msg_id,
    )
    return True, media_type, media_path
