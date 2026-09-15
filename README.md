# Claude usage tray

Two Windows tray icons showing how much of your Claude subscription you have
used. One number for the 5-hour session window, one for the 7-day window. No
clicking, no hovering, no browser tab.

<p align="center">
  <img src="docs/icons.png" alt="Green 14, amber 72 and red 94 icons, shown large and at real tray size">
</p>

<p align="center"><em>Green under 70%, amber to 89%, red past that. The small
row is actual size in the tray.</em></p>

The point is peripheral vision. You find out you are at 88% of the weekly cap
by glancing at the taskbar, not by running out mid-task.

**Contents** &middot; [Install](#install) &middot;
[Where the numbers come from](#where-the-numbers-come-from) &middot;
[The shared cache file](#the-shared-cache-file) &middot;
[Configuration](#configuration) &middot;
[Cost while running](#cost-while-running) &middot;
[Troubleshooting](#troubleshooting) &middot;
[License](#license)

---

## Install

You need Windows, Python 3.9 or newer on PATH, and Claude Code signed in on
this machine (this app reads the token Claude Code already stored, it has no
login of its own).

Download the [latest release](https://github.com/GoodTimesPM/claude-usage-tray/archive/refs/heads/main.zip)
and extract it, or clone it:

```powershell
git clone https://github.com/GoodTimesPM/claude-usage-tray.git
cd claude-usage-tray
```

Then double-click **`Install.cmd`**. A console window opens, installs
`pystray`, `Pillow` and `requests` for your user, puts a shortcut in your
Startup folder, and starts the app. Two numbers appear in the tray within a
few seconds. Close the window once it says done.

(`Install.cmd` also clears the "downloaded from the internet" flag Windows
puts on files pulled from a zip, then runs `install.ps1` for you. If you'd
rather run PowerShell yourself: `.\install.ps1` from a terminal opened in this
folder — just don't double-click `install.ps1` directly, Windows opens `.ps1`
files in an editor instead of running them.)

Right-click either icon for `Refresh now` and `Quit`. Hover for the exact
percentage and the reset time.

To remove it, double-click **`Uninstall.cmd`** (or run `.\uninstall.ps1`).
That deletes the shortcut and stops the process. The Startup folder is the
launch mechanism on purpose. It is one visible file you can delete, rather than
a registry key or a scheduled task you have to go looking for.

## Where the numbers come from

`GET https://api.anthropic.com/api/oauth/usage`, sent with the OAuth access
token Claude Code keeps in `~/.claude/.credentials.json`, plus the header
`anthropic-beta: oauth-2025-04-20`. The response carries
`five_hour.utilization` and `seven_day.utilization`.

Be clear about what that is. This is not a documented public API. It is the
endpoint the Claude Code CLI calls to power its own "approaching usage limit"
warnings, found by pulling strings out of the installed `claude.exe`. Anthropic
can change or remove it without notice, and if they do, this app breaks. It
sends your own token to Anthropic's own server to read your own account, and it
sends nothing anywhere else, but you are relying on an internal endpoint and
you should decide about that with your eyes open.

The same goes for the token refresh. When the stored access token is within ten
minutes of expiring, the app mints a new one from the refresh token using the
same grant Claude Code uses, and writes the result back to the credentials file
atomically so a concurrent CLI read never sees half a file. That keeps Claude
Code working too, since the refreshed token is the one it will pick up next.
Only a dead refresh token needs a real `claude` login.

**The rate limit is the thing that shapes this app.** The endpoint allows about
five requests per rolling five minutes *per account*, and the Claude Code CLI
spends from the same budget. So the poll interval is 300 seconds: one request
per window, the rest left for the CLI. A 429 is treated as a normal outcome
rather than an error, waiting exactly the server's `Retry-After` plus jitter.
Lowering the interval does not get you fresher numbers. It gets both tools rate
limited.

## The shared cache file

Every successful read is written to
`%LOCALAPPDATA%\claude-usage\usage.json` (temp file plus `os.replace`, so a
reader never sees a partial write):

```json
{
  "five_hour": 32,
  "seven_day": 18,
  "five_hour_resets": "2026-07-23T00:09:59Z",
  "seven_day_resets": "2026-07-24T08:59:59Z",
  "read_at": "2026-07-23T19:41:02.117854+00:00"
}
```

This exists because of the per-account rate limit. If you have another local
tool that wants these numbers, point it at this file instead of letting it poll
the endpoint. Two pollers means 429s for both.

[Colony Dash](https://github.com/GoodTimesPM/colony-dash) reads it this way.

## Configuration

Everything is an environment variable, so nothing here needs editing.

| Variable | Default | What it does |
| --- | --- | --- |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Where Claude Code keeps its config. Same variable Claude Code itself honours. |
| `CLAUDE_TRAY_CREDENTIALS` | `<config dir>/.credentials.json` | The credentials file, if it is somewhere unusual. |
| `CLAUDE_TRAY_CACHE` | `%LOCALAPPDATA%\claude-usage\usage.json` | Where to publish each good read. |
| `CLAUDE_TRAY_POLL_SECONDS` | `300` | Poll interval. Floors at 60. Read the rate limit section before lowering it. |
| `CLAUDE_TRAY_FONT` | Arial Bold, then Segoe UI Semibold, Calibri Bold, Verdana Bold | A `.ttf` for the number. It must be heavy; anything lighter turns to mush at 16px. |

## Cost while running

About 44 MB of RAM and one HTTPS GET every five minutes. The tray icons are
native Win32 (`Shell_NotifyIcon`) and event-driven, so the only thing running
between polls is one sleeping thread. No console window, no logging to disk,
no window at all.

Two icons rather than one stacked icon, because two numbers in a 16px square is
unreadable. That was tested by rendering and downscaling, not guessed.

## Troubleshooting

**"rate limited, retry in Nm" in the tooltip.** Expected during heavy Claude
Code use. You are sharing one budget with the CLI. It heals itself.

**"login expired - run 'claude' to sign in again".** The app tried to refresh
and the refresh token was rejected too, which means it is genuinely dead. Run
`claude` once, then `Refresh now` from the tray menu.

**Grey icons showing `?`.** No successful read since launch. Check that the
credentials file exists and that Claude Code is signed in.

**Numbers frozen with no error.** The tooltip shows the age of the last good
read ("read 7m ago"). If that keeps climbing, restart the app. The poll loop is
wrapped so it cannot die silently, because the worst failure mode for something
like this is showing stale numbers as if they were current.

**404 or a changed response shape.** Anthropic moved the endpoint. Re-derive it
the way it was found in the first place: grep `claude.exe` for `usage` and
`ratelimit` strings.

## License

MIT. See [LICENSE](LICENSE).

Not affiliated with, endorsed by, or supported by Anthropic.
