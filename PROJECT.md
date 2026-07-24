# Token Usage in Tray

Windows system tray app that shows two live Claude Pro usage percentages, always visible, no clicking/hovering required.

## Status: working, installed, running (rate-limit handling added 2026-07-23)

## What it does

Two small tray icons, each a single number on a color-coded background (green <70%, amber 70-89%, red 90%+):

- **5h icon** — current 5-hour session-limit utilization (the Pro/Max rolling session window)
- **7d icon** — current 7-day (weekly) limit utilization — this is the closest thing to "total spend %" a Pro subscription has (Pro has no dollar-metered usage, so there's no literal all-time total; the weekly cap is the broader limit)

Hovering either icon shows exact % and reset time in the tooltip. Right-click menu: "Refresh now" (forces an immediate poll) and "Quit".

## Data source (important - undocumented/internal)

`GET https://api.anthropic.com/api/oauth/usage`, authenticated with the OAuth **access token already stored locally** at `~/.claude/.credentials.json` (`claudeAiOauth.accessToken`), header `anthropic-beta: oauth-2025-04-20`.

This endpoint was found by grepping strings out of the installed `claude.exe` binary (`/api/oauth/usage`, plus response field paths `rate_limits.five_hour.used_percentage` / `rate_limits.seven_day.used_percentage`) — it's the same endpoint the Claude Code CLI itself calls to power its own "approaching usage limit" warnings. It is **not** public API documentation, so:

- It could change or disappear without notice if Anthropic reshapes the endpoint.
- The app does **not** manage OAuth refresh itself — it just re-reads the token from the credentials file on every poll. As long as Claude Code is used periodically (which keeps that file's token fresh), this keeps working. If the token in that file goes stale and Claude Code isn't run to refresh it, the tray icons will show stale data with a dimmed color and the tooltip will say so — no crash, no retry storm.

### Rate limit on this endpoint (measured 2026-07-23)

**The endpoint allows ~5 requests per rolling 5 minutes, per account.** On exceeding it, it returns `429` with `Retry-After: 300`. Measured directly: requests 1-5 in a burst returned 200, request 6 onward returned 429. The `Retry-After` value **counts down** (300 → 298 → 297) across subsequent 429s, so hammering it while limited does *not* extend the penalty — the window is fixed, not sliding-on-rejection.

Critically, **the Claude Code CLI spends from this same per-account budget.** So the tray app is not alone in the bucket: during active Claude Code use, the CLI can consume the whole allowance and the tray app's poll gets a 429. This is normal contention, not a malfunction, and is why `POLL_SECONDS` is 300 (one poll per window, leaving the rest of the budget to the CLI) rather than the original 180.

Response shape actually returned (verified 2026-07-22):
```json
{
  "five_hour": {"utilization": 13.0, "resets_at": "2026-07-23T00:09:59...Z", ...},
  "seven_day": {"utilization": 9.0, "resets_at": "2026-07-24T08:59:59...Z", ...},
  ...
}
```

## Why this design (decisions made 2026-07-22)

- **Two separate tray icons, not one.** Tried a single icon with both numbers stacked — illegible at real Windows tray size (16px on standard DPI; only readable at 32px+). A single big number per icon reads clearly at 16px, confirmed by rendering + downscaling test.
- **Python + pystray + Pillow + requests, not C#/.NET or Electron.** No .NET SDK was installed on this machine and winget isn't available either, so a compiled C# tray app would've needed an SDK install first. Python 3.12 was already present. Electron was ruled out on resource-use grounds per Jordan's explicit ask. `pystray`'s Windows backend is native Win32 (Shell_NotifyIcon), event-driven, not polled — idle cost is just the poll thread's sleep.
- **5-minute poll interval** (`POLL_SECONDS` in `app/tray_app.pyw`). Originally 3 minutes (Jordan asked for "1 or 5, whichever is the sweet spot" — split the difference), but that was set before the endpoint's ~5-req/5-min budget was known, and it starved the Claude Code CLI of the shared allowance. Now pinned to one poll per rate-limit window. **Do not lower this** without re-measuring the limit.
- **429 is handled as a first-class outcome, not an error** (added 2026-07-23). On 429 the app waits exactly the server's `Retry-After` plus 5-30s of jitter (so it doesn't resync with whatever else is spending the budget), and does *not* count it toward failure backoff. Other failures use exponential backoff up to 30 min. `401/403` is called out separately in the tooltip as "token stale - run Claude Code once", since that one has a specific user fix.
- **Icons only dim after 15 min without a good read** (`STALE_AFTER_SECONDS`), not on the first failed poll. A single 429 is expected during heavy CLI use and shouldn't make the tray look broken when the numbers are still seconds old.
- **No persistent logging.** Deliberately not writing to disk every cycle — avoids unnecessary I/O for a background app that's supposed to be invisible resource-wise.
- **Launch mechanism: Startup folder shortcut**, not a registry Run key or scheduled task. Chosen so Jordan can kill it instantly and visibly by deleting one `.lnk` file if it ever causes problems — matches his stated "if I notice performance issues I'm deleting it."

## Files

- `app/tray_app.pyw` — the whole app (single file, no console window since it's `.pyw` run via `pythonw.exe`)
- `app/requirements.txt` — `pystray`, `Pillow`, `requests` (all installed via `pip install --user`, already present on this machine as of 2026-07-22)
- `install_startup.ps1` — creates the Startup-folder shortcut (safe to re-run)
- `uninstall_startup.ps1` — removes the shortcut and kills any running instance

## Verified working (2026-07-22)

- Real API call against this account returned live data (5h: 13-14%, 7d: 9%)
- Icon legible at 16px and 20px (actual tray render sizes), tested via downscale
- Process runs stable, ~44MB RAM, no console window, no crash
- Startup shortcut installed at `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Claude Usage Tray.lnk`
- App started immediately (not just at next login) and is running now

## Bug found and fixed 2026-07-23: silent poll-thread death

Symptom: tooltip frozen reading `(stale since 8:28 PM: 429 Client Error: Too Many Requests)` for 26+ minutes, while the process was still alive and a manual request to the same endpoint returned 200. The rate-limit penalty is only 5 minutes, so it should have self-healed and didn't.

Cause: in the original `_poll_loop`, only `_fetch_usage()` was inside the `try`. The icon/tooltip updates (`icon.icon = ...`, `icon.title = ...`) sat *outside* it. Those call into Win32 `Shell_NotifyIcon`, which can fail transiently (Explorer restart, busy tray). One such failure raised out of the loop and killed the poll thread — leaving a process that looks perfectly alive but never updates again. Worst failure mode for a background app: it presents stale numbers as if they were current.

Fixes applied: the entire loop body is now inside a catch-all so the thread cannot die; the icon-update block has its own inner `try` that swallows Win32 errors; and the tooltip now reports the **age** of the last good read ("read 7m ago"), so a frozen app is immediately visible instead of ambiguous.

## Bug found and fixed 2026-07-24: "Resets unknown" right after a weekly reset

Symptom: just after the 7-day window rolled over for the first time, the 7d tooltip read `Claude 7d weekly usage: 0%` / `Resets unknown`.

Cause: right after a window resets (utilization back to 0, window not yet "active" — the payload's `limits[].is_active` is `false` for it), the endpoint returns `resets_at: null` for that window. The success branch did a blind `_state.update(result)`, so that null overwrote the previously-known reset, and `_format_reset(None)` → `"unknown"`.

Fix: on a good read, a null `*_resets` no longer clobbers the last known value — the cached one is kept. `_format_reset` now takes the window's period and, if the kept reset time has already lapsed, rolls it forward by whole periods (windows reset on a fixed cadence: +7 days weekly, +5h session) to recover the correct next reset without needing a fresh read. `"unknown"` now only shows if a reset value was *never* seen since launch. Cache is in-memory only (consistent with the no-disk-IO decision); a restart in that brief post-reset window is the one case that can still momentarily show "unknown" until the next good read repopulates it.

## If something breaks later

- **Tooltip says "rate limited, retry in Nm":** expected during heavy Claude Code use — the CLI and this app share one ~5-req/5-min budget. It self-heals; no action needed.
- **Tooltip says "token stale - run Claude Code once":** the token in `~/.claude/.credentials.json` was rejected (401/403). Open Claude Code once to force a refresh, then "Refresh now" from the tray menu.
- **Icons show "?" / gray, tooltip says unavailable:** no successful read has happened at all since launch — check the credentials file exists and is readable.
- **Numbers frozen but no error in tooltip:** check the "read Nm ago" age. If it keeps climbing, the poll thread died despite the catch-all — restart the app and investigate.
- **Endpoint stops working (404/shape change):** re-derive it the same way it was found — grep `claude.exe` for `usage`/`ratelimit` strings — Anthropic may have moved or restructured it.
- **To change poll frequency:** edit `POLL_SECONDS` in `app/tray_app.pyw` — but see the rate-limit section above; going below 300s trips 429s and steals budget from the Claude Code CLI.
- **To fully remove:** run `uninstall_startup.ps1`, then delete this folder.
