# Next Steps

_Last checked 2026-08-28 against live state (`launchctl`, `sqlite3 data/cdmm.db`, log files) — see Resolved section for what changed since 2026-08-22._

## Immediate

1. **3 voice messages still untranscribed** (out of 280 total, up from 271 — new ones arrived via ingestion since the last check): `chat=-1001631368049 msg=1440`, `chat=-1003948790012 msg=1272`, `chat=-1003652254158 msg=873`. Re-run `python src/transcribe.py` and check `data/transcribe.log` for why those three fail.

2. **1 photo still missing a vision description** (out of 1194, down from a backlog of ~1632 — see Resolved): `chat=-1003978882989 msg=1342`. A different message in the same chat (`msg=1556`) previously failed with `[METAL] ... Insufficient Memory` / `GPU Timeout` errors and succeeded on a later retry, so `1342` likely just needs another `python src/vision.py` pass.

3. **Message 1436 in Dan's public channel is still unexplained.** Still absent from the DB, still never appeared in `listener.log` — no "ingested", no "edit captured", no "ERROR" line. Likely a `MessageService` event (pin/join/etc, which `ingest.py` correctly skips without logging), but never confirmed against live Telegram. Low priority.

## Cleanup

4. **Git commit author is still wrong.** No global git identity is set (`git config user.email`/`user.name` both empty), so all 3 commits so far are authored as `siddharth@Siddharths-Mac-mini.local`. Worth fixing with `git config --global user.email/user.name` before more commits land, now that the repo is being shared with mastermind members.

5. **The `cdmm` MCP server still isn't registered for interactive Claude Code sessions** (`claude mcp list` only shows the Google connectors) — only reachable via the `telegram-kb-bots` subprocess runner (your actual instance) or `src/bot.py` (the repo's standalone runner, see item 6). Add via `claude mcp add` if you want to query CDMM data directly from a session like this one.

6. **`src/bot.py` (added 2026-08-28) has never been run.** It's a new standalone single-bot runner written for the open-sourced repo — a trimmed version of the `telegram-kb-bots` pattern (long-poll → `claude -p` with `mcp.json` → reply), so mastermind members get a working Telegram bot without needing the author's separate multi-bot project. It has not been tested against real Telegram or a real `claude -p` call yet. Before telling anyone it works: create a test bot token via @BotFather, set `CDMM_BOT_TOKEN`/`CDMM_BOT_ALLOWED_USER_IDS` in `.env`, run `python src/bot.py`, and confirm it actually answers a real question end-to-end.

## Resolved since 2026-08-22

- ~~cdmm_bot has never actually been run~~ — **Done.** `com.siddharth.bot.cdmm_bot` is loaded and running (`launchctl list`), and `~/telegram-kb-bots/state/cdmm_bot/history.csv` shows real conversation history (last updated today), confirming it can call the MCP tools and answer real questions.
- ~~Vision analysis has essentially never run~~ — **Done.** 1193/1194 photos now have a `media_description` (was 2/1634).
- ~~3 of 271 voice messages untranscribed~~ — Same count, different messages: still 3 outstanding, but the pool grew to 280 and 277 of those are now done. See item 1 above for the current IDs.

## Known-fixed (context for later, not action items)

- **2026-08-22**: Fixed a bug where `DANIEL_MCEVOY_CHANNEL_ID` in `config.py` was stored without Telegram's `-100` channel-ID prefix, causing the live listener to silently file every message from Dan's public channel under a second, orphaned `chat_id`/`chat_name` — invisible to queries even though the log printed "ingested". Config fixed, 1340 historical rows migrated, listener restarted and verified.
- **2026-08-22**: First git commit made — the repo had no commit history at all despite the code existing since 2026-08-19.
- **2026-08-28**: `README.md` added and repo reviewed for leaks ahead of sharing with CDMM mastermind members — `.env`/`data/` confirmed gitignored, no API keys/tokens/phone numbers found anywhere in git history. Chat IDs (including Dan's DM ID) stay hardcoded in `config.py` by design — see `README.md`.
