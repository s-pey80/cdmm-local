# Next Steps

_Last checked 2026-08-28 against live state (`launchctl`, `sqlite3 data/cdmm.db`, log files) — see Resolved section for what changed since 2026-08-22._

## Immediate

1. **1 photo still missing a vision description** (out of 1194, down from a backlog of ~1632 — see Resolved): `chat=-1003978882989 msg=1342`. A different message in the same chat (`msg=1556`) previously failed with `[METAL] ... Insufficient Memory` / `GPU Timeout` errors and succeeded on a later retry, so `1342` likely just needs another `python src/vision.py` pass.

2. **Message 1436 in Dan's public channel is still unexplained.** Still absent from the DB, still never appeared in `listener.log` — no "ingested", no "edit captured", no "ERROR" line. Likely a `MessageService` event (pin/join/etc, which `ingest.py` correctly skips without logging), but never confirmed against live Telegram. Low priority.

## Cleanup

3. **Failure sentinels can silently mask themselves as "done."** `hydration.py` writes a `"[transcript failed after N attempts: ...]"` (or `vision`) string into the `transcript`/`media_description` column after exhausting retries. `get_untranscribed()` (`db.py`) and the vision equivalent only query `WHERE transcript IS NULL` / `WHERE media_description IS NULL` — a sentinel-holding row is NOT NULL, so it's silently excluded from every retry pass forever unless someone notices and manually clears it (as happened with item 4 below). Worth either querying for the sentinel pattern too, or using a separate boolean/status column instead of overloading the content column.

4. **Git commit author is still wrong.** No global git identity is set (`git config user.email`/`user.name` both empty), so all 3 commits so far are authored as `siddharth@Siddharths-Mac-mini.local`. Worth fixing with `git config --global user.email/user.name` before more commits land, now that the repo is being shared with mastermind members.

5. **The `cdmm` MCP server still isn't registered for interactive Claude Code sessions** (`claude mcp list` only shows the Google connectors) — only reachable via the `telegram-kb-bots` subprocess runner (your actual instance) or `src/bot.py` (the repo's standalone runner, see item 6). Add via `claude mcp add` if you want to query CDMM data directly from a session like this one.

6. **`src/bot.py` (added 2026-08-28) has never been run.** It's a new standalone single-bot runner written for the open-sourced repo — a trimmed version of the `telegram-kb-bots` pattern (long-poll → `claude -p` with `mcp.json` → reply), so mastermind members get a working Telegram bot without needing the author's separate multi-bot project. It has not been tested against real Telegram or a real `claude -p` call yet. Before telling anyone it works: create a test bot token via @BotFather, set `CDMM_BOT_TOKEN`/`CDMM_BOT_ALLOWED_USER_IDS` in `.env`, run `python src/bot.py`, and confirm it actually answers a real question end-to-end.

## Resolved since 2026-08-22

- ~~cdmm_bot has never actually been run~~ — **Done.** `com.siddharth.bot.cdmm_bot` is loaded and running (`launchctl list`), and `~/telegram-kb-bots/state/cdmm_bot/history.csv` shows real conversation history (last updated today), confirming it can call the MCP tools and answer real questions.
- ~~Vision analysis has essentially never run~~ — **Done.** 1193/1194 photos now have a `media_description` (was 2/1634).
- ~~Voice messages untranscribed~~ — **Fixed 2026-08-28, root cause found.** `com.cdmm.listener.plist` had no `PATH` in its launchd environment, so the live listener's subprocess calls to `ffmpeg` (`/opt/homebrew/bin/ffmpeg`) failed with `[Errno 2] No such file or directory: 'ffmpeg'` on every voice note ingested live (batch `backfill.py`/`transcribe.py` runs from a terminal were unaffected — they inherit a real shell PATH). 9 of these got a permanent failure sentinel written into `transcript` (see cleanup item 3 for why that's worse than it sounds) instead of staying retryable; 3 more were genuinely still NULL. Fixed: added `PATH` to `launchd/com.cdmm.listener.plist` and the loaded `~/Library/LaunchAgents/` copy, reloaded the service (new PID confirmed via `launchctl list`), reset all 9 sentinel rows to `NULL`, reran `python src/transcribe.py` — all 12 transcribed successfully, 0 remaining NULL or sentinel voice rows db-wide.

## Known-fixed (context for later, not action items)

- **2026-08-22**: Fixed a bug where `DANIEL_MCEVOY_CHANNEL_ID` in `config.py` was stored without Telegram's `-100` channel-ID prefix, causing the live listener to silently file every message from Dan's public channel under a second, orphaned `chat_id`/`chat_name` — invisible to queries even though the log printed "ingested". Config fixed, 1340 historical rows migrated, listener restarted and verified.
- **2026-08-22**: First git commit made — the repo had no commit history at all despite the code existing since 2026-08-19.
- **2026-08-28**: `README.md` added and repo reviewed for leaks ahead of sharing with CDMM mastermind members — `.env`/`data/` confirmed gitignored, no API keys/tokens/phone numbers found anywhere in git history. Chat IDs (including Dan's DM ID) stay hardcoded in `config.py` by design — see `README.md`.
