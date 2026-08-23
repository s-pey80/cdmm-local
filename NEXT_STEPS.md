# Next Steps

## Immediate

1. **cdmm_bot has never actually been run.** Ingestion (listener + backfill) is live and confirmed working, but the Telegram chat interface — the thing you actually talk to — has never been started once.
   - `~/telegram-kb-bots/launchd/com.siddharth.bot.cdmm_bot.plist` exists but is not loaded (`launchctl list` only shows `yb_bot`)
   - `~/telegram-kb-bots/state/cdmm_bot/` (session store, history.csv) doesn't exist yet — zero messages sent to it, ever
   - Everything it needs is already in place: `bots.yaml` has the `cdmm_bot` entry (mcp_config, allowed_tools, system_prompt), `CDMM_BOT_TOKEN` is set in `telegram-kb-bots/.env`, `mcp.json` points at `mcp_server.py`
   - To start: `launchctl load ~/telegram-kb-bots/launchd/com.siddharth.bot.cdmm_bot.plist`, then message the bot on Telegram and confirm it can actually call the MCP tools and answer a real question (e.g. "what's the latest message from Dan")

2. **3 of 271 voice messages are still untranscribed.** `mlx-whisper` transcription is otherwise working (268/271 done). Re-run `python src/transcribe.py` and check `data/transcribe.log` for why those 3 failed.

3. **Vision analysis has essentially never run.** Only 2 of 1634 photos have a `media_description` (both from `hydration.py`'s live per-message path). The batch backfill (`python src/vision.py`, `mlx-vlm`/Qwen3-VL-4B) has never been run once — no `vision.log` exists at all. Model + weights are already installed/cached in `.venv`, just needs running repeatedly (default `limit=50` per call) against the ~1632-photo backlog.

4. **Message 1436 in Dan's public channel is unexplained.** Never appeared in `listener.log` — no "ingested", no "edit captured", no "ERROR" line. Likely a `MessageService` event (pin/join/etc, which `ingest.py` correctly skips without logging), but this was never confirmed against live Telegram. Low priority — worth a quick look next time the channel is being poked at.

## Cleanup

5. **Git commit author is wrong.** The initial commit (`9ae6deb`) used an auto-detected identity (`siddharth@Siddharths-Mac-mini.local`) since no global git identity is set. Fix with `git config --global user.email/user.name`, then optionally `git commit --amend --reset-author` on that one commit.

6. **The `cdmm` MCP server isn't usable from an interactive Claude Code session** — only from the `telegram-kb-bots` subprocess runner. If you want to query CDMM data through *this* kind of session directly (not just via the Telegram bot), it needs `claude mcp add`.

## Known-fixed (context for later, not action items)

- **2026-08-22**: Fixed a bug where `DANIEL_MCEVOY_CHANNEL_ID` in `config.py` was stored without Telegram's `-100` channel-ID prefix, causing the live listener to silently file every message from Dan's public channel under a second, orphaned `chat_id`/`chat_name` — invisible to queries even though the log printed "ingested". Config fixed, 1340 historical rows migrated, listener restarted and verified.
- **2026-08-22**: First git commit made — the repo had no commit history at all despite the code existing since 2026-08-19.
