"""Standalone Telegram bot for CDMM — long-polls Telegram and answers by
shelling out to `claude -p`, scoped to this repo and restricted to the CDMM
MCP tools (mcp_server.py) plus Read. No bot can write, execute, or edit
anything.

This is a minimal, single-bot runner. The author's own CDMM instance
actually runs through a separate multi-bot project they use across several
personal Telegram bots (consolidated session/history/approval handling) —
that project isn't part of this repo. This script is the standalone
equivalent for CDMM alone: same core idea (long-poll -> `claude -p` ->
reply), no multi-bot config, no extra dependencies beyond what's in
requirements.txt.

Usage:
    python src/bot.py
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
MCP_CONFIG = str(PROJECT_ROOT / "mcp.json")
SESSION_PATH = PROJECT_ROOT / "data" / "bot_sessions.json"
TELEGRAM_MAX_LEN = 4000
CLAUDE_TIMEOUT_SECONDS = 180
SESSION_IDLE_EXPIRY_SECONDS = 24 * 60 * 60  # start a fresh session after a day of silence

ALLOWED_TOOLS = "Read,mcp__cdmm__*"

SYSTEM_PROMPT = """\
You are answering questions sent over Telegram. This process is fully \
non-interactive: there is no one available to approve a permission prompt, \
so never run Bash commands or suggest installing tools.

You are a research assistant with full access to the CDMM (Dan's Crypto
Mastermind) Telegram message history via MCP tools — search by keyword,
sender, date range, or media type, plus voice-note transcripts and photo
descriptions.

Guidelines:
- Always query the data before answering — do not make up information
- Use get_chat_summary first if you need to orient yourself
- search_messages does exact substring matching; semantic_search finds
  relevant messages by meaning even without shared keywords. For vague or
  conceptual questions, prefer semantic_search or use both together
- Use plain text only: no markdown bold/italics/headers/tables
- For lists, use simple dashes or numbers
- When referencing a specific group/channel message, include the sender
  name, date, and the actual URL from that message's message_link field —
  never write the literal word "(link)" as a stand-in
- Exception: for messages from a 1:1 DM (no message_link available), cite
  the sender name and date, and quote the exact supporting phrase verbatim
  so the reader can search for it themselves
- For photos, media_path points to a local file — open it directly with
  the Read tool if the image content is relevant
- For voice notes, use search_transcripts or the transcript field returned
  by the other tools
- If no relevant data is found, say so clearly rather than guessing

Keep answers concise and appropriate for a chat interface."""

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cdmm_bot")


def load_sessions() -> dict:
    return json.loads(SESSION_PATH.read_text()) if SESSION_PATH.exists() else {}


def save_sessions(sessions: dict) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(sessions, indent=2))


def run_claude(message: str, session_id: str | None) -> tuple[str, str]:
    cmd = [
        CLAUDE_BIN, "-p", message,
        "--output-format", "json",
        "--allowedTools", ALLOWED_TOOLS,
        "--append-system-prompt", SYSTEM_PROMPT,
        "--mcp-config", MCP_CONFIG,
    ]
    if session_id:
        cmd += ["--resume", session_id]

    result = subprocess.run(
        cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[-2000:]}")

    data = json.loads(result.stdout)
    return data["result"], data["session_id"]


def make_handler(allowed_user_ids: set[int]):
    sessions = load_sessions()

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if allowed_user_ids and user.id not in allowed_user_ids:
            log.warning("REJECTED sender id=%s username=%s", user.id, user.username)
            return

        chat_id = str(update.effective_chat.id)
        text = update.message.text or ""
        log.info("IN  chat=%s text=%r", chat_id, text)

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        entry = sessions.get(chat_id)
        session_id = None
        if entry:
            age_seconds = time.time() - entry.get("last_used_ms", 0) / 1000
            if age_seconds < SESSION_IDLE_EXPIRY_SECONDS:
                session_id = entry["session_id"]
            else:
                log.info("chat=%s session idle > %ds, starting fresh", chat_id, SESSION_IDLE_EXPIRY_SECONDS)

        try:
            loop = asyncio.get_running_loop()
            answer, new_session_id = await loop.run_in_executor(None, run_claude, text, session_id)
        except Exception:
            log.exception("claude invocation failed")
            await update.message.reply_text("Something went wrong answering that — check the logs.")
            return

        log.info("OUT chat=%s text=%r", chat_id, answer)

        sessions[chat_id] = {"session_id": new_session_id, "last_used_ms": int(time.time() * 1000)}
        save_sessions(sessions)

        for i in range(0, len(answer), TELEGRAM_MAX_LEN):
            await update.message.reply_text(answer[i:i + TELEGRAM_MAX_LEN])

    return handle_message


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.environ.get("CDMM_BOT_TOKEN")
    if not token:
        raise SystemExit("missing CDMM_BOT_TOKEN (check .env)")

    allowed_ids_raw = os.environ.get("CDMM_BOT_ALLOWED_USER_IDS", "")
    allowed_user_ids = {int(x) for x in allowed_ids_raw.split(",") if x.strip()}
    if not allowed_user_ids:
        log.warning("CDMM_BOT_ALLOWED_USER_IDS is empty — the bot will answer ANY Telegram user who messages it")

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, make_handler(allowed_user_ids)))

    log.info("starting cdmm_bot")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
