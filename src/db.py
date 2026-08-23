import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("CDMM_DB_PATH", Path(__file__).resolve().parent.parent / "data" / "cdmm.db"))


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")  # listener writes + mcp_server reads happen concurrently
    return conn


def ensure_tables() -> None:
    with _get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            chat_id         INTEGER NOT NULL,
            message_id      INTEGER NOT NULL,
            edited_at       TEXT,
            chat_name       TEXT,
            sender_id       INTEGER,
            sender_name     TEXT,
            sent_at         TEXT,
            text            TEXT,
            media_type      TEXT,
            media_path      TEXT,
            reply_to_msg_id INTEGER,
            raw_json        TEXT,
            transcript      TEXT,
            ingested_at     TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (chat_id, message_id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON messages(sent_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender_name ON messages(sender_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_media_type ON messages(media_type)")

        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        if "embedding" not in existing_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN embedding BLOB")
        if "media_description" not in existing_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN media_description TEXT")


def get_last_message_id(chat_id: int) -> int:
    """Checkpoint for backfill/reconnect — MAX(message_id) is crash-proof by construction
    (no separate timestamp state that can drift, unlike the old hydrate_state approach)."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(message_id), 0) FROM messages WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return int(row[0])


def upsert_message(
    message_id: int,
    chat_id: int,
    chat_name: str,
    sender_id,
    sender_name: str,
    sent_at,
    text: str,
    media_type: str,
    media_path: str,
    raw_json: str,
    edited_at=None,
    reply_to_msg_id=None,
) -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO messages (
                chat_id, message_id, edited_at, chat_name, sender_id, sender_name,
                sent_at, text, media_type, media_path, reply_to_msg_id, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (chat_id, message_id) DO UPDATE SET
                edited_at       = excluded.edited_at,
                chat_name       = excluded.chat_name,
                sender_id       = excluded.sender_id,
                sender_name     = excluded.sender_name,
                sent_at         = excluded.sent_at,
                text            = excluded.text,
                media_type      = excluded.media_type,
                media_path      = excluded.media_path,
                reply_to_msg_id = excluded.reply_to_msg_id,
                raw_json        = excluded.raw_json,
                ingested_at     = datetime('now'),
                embedding       = CASE WHEN text IS excluded.text THEN embedding ELSE NULL END
            """,
            (
                chat_id, message_id, edited_at, chat_name, sender_id, sender_name,
                sent_at, text, media_type, media_path, reply_to_msg_id, raw_json,
            ),
        )


def set_transcript(chat_id: int, message_id: int, transcript: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE messages SET transcript = ? WHERE chat_id = ? AND message_id = ?",
            (transcript, chat_id, message_id),
        )


def get_untranscribed(limit: int = 50) -> list[tuple]:
    """Voice/audio messages with a downloaded file but no transcript yet."""
    with _get_conn() as conn:
        return conn.execute(
            """
            SELECT chat_id, message_id, media_path FROM messages
            WHERE media_type IN ('voice', 'audio', 'video_note')
              AND media_path IS NOT NULL
              AND transcript IS NULL
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def set_media_description(chat_id: int, message_id: int, description: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE messages SET media_description = ? WHERE chat_id = ? AND message_id = ?",
            (description, chat_id, message_id),
        )


def get_unanalyzed_photos(limit: int = 50) -> list[tuple]:
    """Photos with a downloaded file but no vision description yet."""
    with _get_conn() as conn:
        return conn.execute(
            """
            SELECT chat_id, message_id, media_path FROM messages
            WHERE media_type = 'photo'
              AND media_path IS NOT NULL
              AND media_description IS NULL
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def set_embedding(chat_id: int, message_id: int, vector: bytes) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE messages SET embedding = ? WHERE chat_id = ? AND message_id = ?",
            (vector, chat_id, message_id),
        )


def get_unembedded(limit: int = 200) -> list[tuple]:
    """Messages with text, a transcript, or a vision description but no
    embedding yet — embed.py combines whichever of the three are present."""
    with _get_conn() as conn:
        return conn.execute(
            """
            SELECT chat_id, message_id, text, transcript, media_description FROM messages
            WHERE embedding IS NULL
              AND (
                  (text IS NOT NULL AND TRIM(text) != '')
                  OR (transcript IS NOT NULL AND TRIM(transcript) != '')
                  OR (media_description IS NOT NULL AND TRIM(media_description) != '')
              )
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_embeddings_for_search(chat_name: str = "", sender_name: str = "", since_days: int = 365):
    """Returns (chat_id, message_id, embedding_bytes) for the given filters — the
    candidate pool semantic_search ranks by cosine similarity against the query."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d %H:%M:%S")

    where = ["embedding IS NOT NULL", "sent_at >= ?"]
    params = [cutoff]
    if chat_name:
        where.append("chat_name LIKE ?")
        params.append(f"%{chat_name}%")
    if sender_name:
        where.append("sender_name LIKE ?")
        params.append(f"%{sender_name}%")

    with _get_conn() as conn:
        return conn.execute(
            f"SELECT chat_id, message_id, embedding FROM messages WHERE {' AND '.join(where)}",
            params,
        ).fetchall()
