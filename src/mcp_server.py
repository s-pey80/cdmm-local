"""CDMM MCP Server — exposes CDMM V2 Telegram message data (local SQLite) as MCP
tools. Ported from cdmm-legacy's Azure SQL version — same 7 query tools, same
signatures, just pointed at data/cdmm.db. The vision/search_media_descriptions tool
was dropped: Claude reads photo files directly via the Read tool now (see
media_path), no pre-computed GPT-4o description needed.

Run via stdio, invoked by telegram-kb-bots' runner.py through --mcp-config.

Usage:
    python src/mcp_server.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP

from db import get_embeddings_for_search

DB_PATH = Path(os.environ.get("CDMM_DB_PATH", Path(__file__).resolve().parent.parent / "data" / "cdmm.db"))
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-large-en-v1.5")
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_embed_model = None


def _get_embed_model():
    """Lazy-loaded singleton — avoids paying the model-load cost for tool calls
    that never use semantic_search."""
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def _get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, timeout=30)


def _message_link(chat_id: int, message_id: int) -> str:
    """Build a t.me deep link for a message in a private group/channel."""
    stripped = str(abs(chat_id)).removeprefix("100")
    return f"https://t.me/c/{stripped}/{message_id}"


def _row_to_dict(cursor, row) -> dict:
    return dict(zip((c[0] for c in cursor.description), row))


def _since_dt(since_days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=since_days)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _query(sql: str, params: list) -> list[dict]:
    conn = _get_conn()
    cursor = conn.execute(sql, params)
    rows = []
    for r in cursor.fetchall():
        d = _row_to_dict(cursor, r)
        d["message_link"] = _message_link(d["chat_id"], d["message_id"])
        rows.append(d)
    conn.close()
    return rows


mcp = FastMCP("cdmm")


@mcp.tool()
def get_chat_summary() -> str:
    """
    Returns a summary of all monitored CDMM chats: message counts, latest
    message timestamp, and chat IDs. Use this first to orient yourself before
    answering questions about community activity.
    """
    conn = _get_conn()
    cursor = conn.execute("""
        SELECT chat_name, chat_id, COUNT(*) AS message_count, MAX(sent_at) AS latest_message_at
        FROM messages
        GROUP BY chat_name, chat_id
        ORDER BY latest_message_at DESC
    """)
    rows = [_row_to_dict(cursor, r) for r in cursor.fetchall()]
    conn.close()
    return json.dumps(rows, default=str)


@mcp.tool()
def search_messages(
    query: str,
    chat_name: str = "",
    sender_name: str = "",
    since_days: int = 90,
    limit: int = 20,
) -> str:
    """
    Search messages by keyword or phrase. Searches the message text field.
    Optionally filter by chat name, sender name, or time window.
    Returns messages with message_link so you can cite sources directly.

    Args:
        query: keyword or phrase to search for
        chat_name: limit to chats whose name contains this substring (optional)
        sender_name: limit to senders whose name contains this substring (optional)
        since_days: only return messages from the last N days (default 90)
        limit: max number of results (default 20)
    """
    params = [f"%{query}%", _since_dt(since_days)]
    where = "WHERE text LIKE ? AND sent_at >= ?"
    if chat_name:
        where += " AND chat_name LIKE ?"
        params.append(f"%{chat_name}%")
    if sender_name:
        where += " AND sender_name LIKE ?"
        params.append(f"%{sender_name}%")

    sql = f"""
        SELECT message_id, chat_id, chat_name, sender_name, sent_at, text,
               media_type, media_path, reply_to_msg_id, transcript
        FROM messages
        {where}
        ORDER BY sent_at DESC
        LIMIT {int(limit)}
    """
    return json.dumps(_query(sql, params), default=str)


@mcp.tool()
def get_latest_messages(
    chat_name: str = "",
    sender_name: str = "",
    limit: int = 20,
) -> str:
    """
    Returns the most recent messages across all chats or a specific chat.
    Use this for 'catch me up' requests or to see what's been posted recently.

    Args:
        chat_name: limit to chats whose name contains this substring (optional)
        sender_name: limit to senders whose name contains this substring (optional)
        limit: max number of results (default 20)
    """
    params = []
    filters = []
    if chat_name:
        filters.append("chat_name LIKE ?")
        params.append(f"%{chat_name}%")
    if sender_name:
        filters.append("sender_name LIKE ?")
        params.append(f"%{sender_name}%")
    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    sql = f"""
        SELECT message_id, chat_id, chat_name, sender_name, sent_at, text,
               media_type, media_path, transcript
        FROM messages
        {where}
        ORDER BY sent_at DESC
        LIMIT {int(limit)}
    """
    return json.dumps(_query(sql, params), default=str)


@mcp.tool()
def get_messages_by_sender(
    sender_name: str,
    chat_name: str = "",
    since_days: int = 30,
    limit: int = 30,
) -> str:
    """
    Returns all messages from a specific sender. Use this for questions like
    'what has Dan posted recently?' or 'find all messages from [member]'.

    Args:
        sender_name: sender name substring to match (required)
        chat_name: limit to chats whose name contains this substring (optional)
        since_days: only return messages from the last N days (default 30)
        limit: max number of results (default 30)
    """
    params = [f"%{sender_name}%", _since_dt(since_days)]
    where = "WHERE sender_name LIKE ? AND sent_at >= ?"
    if chat_name:
        where += " AND chat_name LIKE ?"
        params.append(f"%{chat_name}%")

    sql = f"""
        SELECT message_id, chat_id, chat_name, sender_name, sent_at, text,
               media_type, media_path, transcript
        FROM messages
        {where}
        ORDER BY sent_at DESC
        LIMIT {int(limit)}
    """
    return json.dumps(_query(sql, params), default=str)


@mcp.tool()
def get_messages_by_media_type(
    media_type: str,
    chat_name: str = "",
    since_days: int = 30,
    limit: int = 20,
) -> str:
    """
    Returns messages that contain a specific type of media. Use this to find
    voice notes, photos, videos, etc. Voice/audio messages include a transcript
    once transcription has run; photos include media_path so you can open the
    image file directly with the Read tool.

    Args:
        media_type: one of: photo, voice, video, video_note, audio, document
        chat_name: limit to chats whose name contains this substring (optional)
        since_days: only return messages from the last N days (default 30)
        limit: max number of results (default 20)
    """
    params = [media_type, _since_dt(since_days)]
    where = "WHERE media_type = ? AND sent_at >= ?"
    if chat_name:
        where += " AND chat_name LIKE ?"
        params.append(f"%{chat_name}%")

    sql = f"""
        SELECT message_id, chat_id, chat_name, sender_name, sent_at, text,
               media_type, media_path, transcript
        FROM messages
        {where}
        ORDER BY sent_at DESC
        LIMIT {int(limit)}
    """
    return json.dumps(_query(sql, params), default=str)


@mcp.tool()
def get_messages_in_date_range(
    start_date: str,
    end_date: str,
    chat_name: str = "",
    limit: int = 50,
) -> str:
    """
    Returns messages between two dates. Use this for summarizing a specific
    time period, e.g. 'what happened in the community last week?'

    Args:
        start_date: ISO date string e.g. '2025-01-01'
        end_date: ISO date string e.g. '2025-01-31'
        chat_name: limit to chats whose name contains this substring (optional)
        limit: max number of results (default 50)
    """
    params = [start_date, end_date]
    where = "WHERE date(sent_at) >= date(?) AND date(sent_at) <= date(?)"
    if chat_name:
        where += " AND chat_name LIKE ?"
        params.append(f"%{chat_name}%")

    sql = f"""
        SELECT message_id, chat_id, chat_name, sender_name, sent_at, text,
               media_type, media_path
        FROM messages
        {where}
        ORDER BY sent_at ASC
        LIMIT {int(limit)}
    """
    return json.dumps(_query(sql, params), default=str)


@mcp.tool()
def search_transcripts(
    query: str,
    chat_name: str = "",
    sender_name: str = "",
    since_days: int = 365,
    limit: int = 10,
) -> str:
    """
    Search voice note and audio message transcripts by keyword or phrase.
    Use this for questions like 'what did Dan say about Bitcoin in his voice notes?'
    or 'find voice messages mentioning portfolio allocation'.

    Args:
        query: keyword or phrase to search for in transcripts
        chat_name: limit to chats whose name contains this substring (optional)
        sender_name: limit to senders whose name contains this substring (optional)
        since_days: only return messages from the last N days (default 365)
        limit: max number of results (default 10)
    """
    params = [f"%{query}%", _since_dt(since_days)]
    where = "WHERE transcript LIKE ? AND sent_at >= ?"
    if chat_name:
        where += " AND chat_name LIKE ?"
        params.append(f"%{chat_name}%")
    if sender_name:
        where += " AND sender_name LIKE ?"
        params.append(f"%{sender_name}%")

    sql = f"""
        SELECT message_id, chat_id, chat_name, sender_name, sent_at, media_type, transcript
        FROM messages
        {where}
        ORDER BY sent_at DESC
        LIMIT {int(limit)}
    """
    return json.dumps(_query(sql, params), default=str)


@mcp.tool()
def semantic_search(
    query: str,
    chat_name: str = "",
    sender_name: str = "",
    since_days: int = 365,
    limit: int = 10,
) -> str:
    """
    Meaning-based search over message content and voice-note transcripts — finds
    relevant messages even when they don't share exact keywords with the query.
    Use this for vague/conceptual questions (e.g. "how has sentiment on ETH shifted",
    "find messages where people were worried about a rug") where search_messages'
    exact-substring matching would miss paraphrased or synonymous wording. For
    questions with a specific term, ticker, or name, search_messages alone is often
    enough — use both together when unsure.

    Args:
        query: a natural-language question or description of what you're looking for
        chat_name: limit to chats whose name contains this substring (optional)
        sender_name: limit to senders whose name contains this substring (optional)
        since_days: only consider messages from the last N days (default 365)
        limit: max number of results (default 10)
    """
    import numpy as np

    candidates = get_embeddings_for_search(chat_name=chat_name, sender_name=sender_name, since_days=since_days)
    if not candidates:
        return json.dumps([])

    model = _get_embed_model()
    query_vec = model.encode(_BGE_QUERY_PREFIX + query, normalize_embeddings=True, convert_to_numpy=True)

    keys = [(c[0], c[1]) for c in candidates]
    matrix = np.stack([np.frombuffer(c[2], dtype=np.float32) for c in candidates])
    scores = matrix @ query_vec  # both sides pre-normalized, so this is cosine similarity

    top_idx = np.argsort(-scores)[:int(limit)]
    top_keys = [keys[i] for i in top_idx]
    top_scores = {keys[i]: float(scores[i]) for i in top_idx}

    conn = _get_conn()
    placeholders = ",".join("(?,?)" for _ in top_keys)
    flat_params = [v for pair in top_keys for v in pair]
    cursor = conn.execute(
        f"""
        SELECT message_id, chat_id, chat_name, sender_name, sent_at, text,
               media_type, media_path, transcript
        FROM messages
        WHERE (chat_id, message_id) IN (VALUES {placeholders})
        """,
        flat_params,
    )
    rows = []
    for r in cursor.fetchall():
        d = _row_to_dict(cursor, r)
        d["message_link"] = _message_link(d["chat_id"], d["message_id"])
        d["relevance"] = round(top_scores[(d["chat_id"], d["message_id"])], 3)
        rows.append(d)
    conn.close()

    rows.sort(key=lambda r: -r["relevance"])
    return json.dumps(rows, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
