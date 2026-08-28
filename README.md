# CDMM

A local, personal-use Telegram archive + query layer for Dan's Crypto Mastermind (CDMM). It listens to the CDMM group/channel chats you're a member of (plus your own 1:1 DM with Dan), stores everything in a local SQLite database, and exposes it as searchable tools — full-text, semantic, transcripts, and photo descriptions — that an LLM (via MCP) can query on your behalf.

Everything runs locally on your own machine, under your own Telegram account. There's no shared server, no cloud hosting, and no one else can see your data — it's your own copy of the messages your account already has access to.

## What it does

- **`listener.py`** — stays connected to Telegram (via [Telethon](https://docs.telethon.dev)) and ingests new messages and edits in real time.
- **`backfill.py`** — one-time/rerunnable historical import for everything the listener hasn't seen yet.
- **`transcribe.py`** — transcribes voice messages locally with `mlx-whisper` (Apple Silicon).
- **`vision.py`** — describes photos locally with `mlx-vlm` (Qwen3-VL-4B-Instruct), so you can later ask things like "find all the BTC charts Dan posted."
- **`embed.py`** — embeds message/transcript text locally with `sentence-transformers` for semantic search.
- **`mcp_server.py`** — exposes it all as MCP tools: `get_chat_summary`, `search_messages`, `get_latest_messages`, `get_messages_by_sender`, `get_messages_by_media_type`, `get_messages_in_date_range`, `search_transcripts`, `semantic_search`.
- **`bot.py`** — a standalone Telegram bot: long-polls Telegram, answers by shelling out to `claude -p` scoped to the MCP tools above, and replies in-chat.

Nothing here talks to any cloud AI provider. Transcription, vision, and embeddings all run on-device.

## Requirements

- macOS on Apple Silicon (the transcription/vision models use MLX)
- Python 3.11+
- A Telegram account that's a member of the CDMM chats you want to ingest
- Telegram API credentials from [my.telegram.org](https://my.telegram.org) (your own `API_ID`/`API_HASH` — free, takes a minute)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in API_ID, API_HASH, TELEGRAM_PHONE
```

The first time you run anything that touches Telethon, it'll prompt you to log in (phone code, and 2FA password if you have one) and save a local session file — this happens once.

```bash
python src/backfill.py   # historical import
python src/listener.py   # live listener (Ctrl-C to stop)
```

To keep the listener running in the background, use `launchd/com.cdmm.listener.plist` — copy it into `~/Library/LaunchAgents/`, **edit the hardcoded `/Users/siddharth/cdmm` paths to your own username/path first**, then:

```bash
launchctl load ~/Library/LaunchAgents/com.cdmm.listener.plist
```

`mcp.json` also hardcodes an absolute path to the venv's Python and `mcp_server.py` — update that to your own path.

Transcription and vision are optional and can be run anytime after backfill:

```bash
python src/transcribe.py
python src/vision.py
```

## Chat interface

`src/bot.py` is a standalone Telegram bot: it long-polls Telegram and answers each message by calling `claude -p` with `mcp.json` wired in, restricted to `Read` plus the CDMM MCP tools. Requires [Claude Code](https://claude.com/product/claude-code) installed and logged in on the machine running it.

1. Create a bot via [@BotFather](https://t.me/BotFather), grab the token.
2. In `.env`, set `CDMM_BOT_TOKEN` and `CDMM_BOT_ALLOWED_USER_IDS` (your own Telegram user ID — find it via [@userinfobot](https://t.me/userinfobot); leaving this empty lets *anyone* who finds the bot talk to it).
3. Run it:

```bash
python src/bot.py
```

To keep it running in the background, use `launchd/com.cdmm.bot.plist` the same way as the listener's plist above (copy to `~/Library/LaunchAgents/`, fix the hardcoded paths, `launchctl load`).

This is a minimal, single-bot script — long-poll, shell out to `claude -p`, reply, done. The author's own instance actually runs through a separate multi-bot project used across several personal Telegram bots (shared session/history handling, interactive tool-approval buttons, etc.) — that project isn't part of this repo, and isn't needed for CDMM alone. `bot.py` covers everything CDMM's MCP tools need on their own.

## Config

`src/config.py` lists the monitored CDMM chat IDs by name — these are the same for everyone in the mastermind (Telegram chat/user IDs are global, not per-account), so you shouldn't need to change them. `.env` holds only your personal credentials and model choices and is gitignored — never commit it.

## Notes

- `data/` (the SQLite DB and downloaded media) is gitignored — it's your own local archive, not shared via this repo.
- Private (DM) messages have no `t.me` deep link in Telegram — citations for DM-sourced messages are plain text (chat name + date + message ID), not links.
- See `NEXT_STEPS.md` for known gaps and in-progress items.
