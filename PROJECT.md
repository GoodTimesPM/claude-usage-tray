# Token Usage in Tray

Windows system tray app that shows two live Claude Pro usage percentages, always visible, no clicking/hovering required.

## Status: working, installed, running (2026-07-22)

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
- **3-minute poll interval** (`POLL_SECONDS` in `app/tray_app.pyw`). Jordan asked for "1 or 5 minutes, whichever is the sweet spot" — split the difference. Easy to change, it's one constant.
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

## If something breaks later

- **Icons show "?" / gray, tooltip says unavailable:** usually means `~/.claude/.credentials.json` token is stale. Open Claude Code once (anything that talks to the API) to force a token refresh, then "Refresh now" from the tray menu.
- **Endpoint stops working (404/shape change):** re-derive it the same way it was found — grep `claude.exe` for `usage`/`ratelimit` strings — Anthropic may have moved or restructured it.
- **To change poll frequency:** edit `POLL_SECONDS` in `app/tray_app.pyw`.
- **To fully remove:** run `uninstall_startup.ps1`, then delete this folder.
