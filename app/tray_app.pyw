"""
Claude usage tray icons.

Shows two tray icons, each a single big number:

  - "5h" icon = current 5-hour session-limit utilization % (Pro/Max rolling window)
  - "7d" icon = current 7-day (weekly) limit utilization %

Data comes from Anthropic's account usage endpoint, using the OAuth token
Claude Code already stores locally in ~/.claude/.credentials.json. This is
the same endpoint/token the Claude Code CLI itself uses to power its own
usage warnings - we're just reading our own account's own status.

Design goals: near-zero idle resource use. A single background thread wakes
every POLL_SECONDS, makes one small HTTPS GET, and updates both icons. The
tray icons themselves are event-driven (native Win32), not polled. No disk
logging, no extra windows, no console (.pyw + pythonw.exe).
"""

import json
import os
import random
import threading
import time
from datetime import datetime, timedelta, timezone

# How long each window lasts, used to roll a known reset time forward when the
# endpoint temporarily stops reporting one (see _format_reset / the poll loop).
FIVE_HOUR_PERIOD = 5 * 3600
SEVEN_DAY_PERIOD = 7 * 24 * 3600

import requests
from PIL import Image, ImageDraw, ImageFont
import pystray

# The usage endpoint allows roughly 5 requests per rolling 5 minutes, and the
# Claude Code CLI itself spends from that same per-account budget. Polling any
# faster than the window just starves the CLI and earns 429s, so we sit at one
# poll per window and leave the rest of the budget to the CLI.
POLL_SECONDS = 300
MIN_POLL_SECONDS = 60
MAX_POLL_SECONDS = 1800
STALE_AFTER_SECONDS = 900  # only dim the icons after 15 min with no good read
REQUEST_TIMEOUT = 6
CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# Every good read is published here so other local tools can have the numbers
# without polling the endpoint themselves. The rate limit above is per-account,
# so a second poller would earn 429s for both of us. This app is the only
# poller; everything else reads this file. (Colony Dash is the first consumer -
# see colony-dash/ARCHITECTURE.md 6.2.)
USAGE_CACHE_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "claude-usage", "usage.json"
)
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"

# Same refresh flow Claude Code itself uses (found by grepping claude.exe for
# "grant_type:\"refresh_token\"" / TOKEN_URL / CLIENT_ID, same technique used
# to find USAGE_URL). Lets this app refresh its own access token instead of
# needing Claude Code to be opened once to do it.
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
# Refresh proactively once less than this much life is left on the access
# token, so a normal 5-min poll cycle always catches it before it actually
# expires rather than racing the clock.
REFRESH_MARGIN_MS = 10 * 60 * 1000

_state_lock = threading.Lock()
_state = {
    "five_hour": None,
    "seven_day": None,
    "five_hour_resets": None,
    "seven_day_resets": None,
    "last_ok": None,
    "last_ok_at": None,  # monotonic timestamp, for measuring staleness
    "error": None,
}
_wake_event = threading.Event()
_stop_event = threading.Event()


class RateLimited(Exception):
    """429 from the usage endpoint, carrying the server's own Retry-After."""

    def __init__(self, retry_after):
        super().__init__("rate limited")
        self.retry_after = retry_after


class TokenStale(Exception):
    """The access token was rejected and refreshing it also failed - the
    stored refresh token itself is dead, so a real `claude` login is needed."""


def _load_credentials():
    with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_credentials(creds):
    # Atomic write (temp file + os.replace) so a concurrent Claude Code CLI
    # read never sees a half-written file.
    tmp_path = CREDENTIALS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2)
    os.replace(tmp_path, CREDENTIALS_PATH)


def _publish_usage(result):
    """Write the last good read to the shared cache. Best-effort by design: a
    failure here must never disturb the tray icons, which are the actual job."""
    try:
        os.makedirs(os.path.dirname(USAGE_CACHE_PATH), exist_ok=True)
        payload = dict(result)
        payload["read_at"] = datetime.now(timezone.utc).isoformat()
        tmp_path = USAGE_CACHE_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, USAGE_CACHE_PATH)  # atomic; readers never see a partial file
    except Exception:
        pass


def _refresh_access_token(creds):
    """Mint a new access token from the stored refresh token and persist it
    back to the credentials file, same as Claude Code does on its own launch.
    Raises on failure (network error, or the refresh token itself being dead -
    that's the one case that still needs a real `claude` login)."""
    # Verified against the live endpoint (2026-07-27): including "scope" in
    # this body gets a 400 "Invalid request format" back, even though claude.exe
    # itself builds a scope field for this same grant_type. Omit it - the
    # refresh grant works fine without it and returns the account's actual scopes.
    oauth = creds["claudeAiOauth"]
    body = {
        "grant_type": "refresh_token",
        "refresh_token": oauth["refreshToken"],
        "client_id": CLIENT_ID,
    }
    resp = requests.post(TOKEN_URL, json=body, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    now_ms = int(time.time() * 1000)
    oauth["accessToken"] = data["access_token"]
    oauth["refreshToken"] = data.get("refresh_token", oauth["refreshToken"])
    oauth["expiresAt"] = now_ms + int(data["expires_in"]) * 1000
    if "refresh_token_expires_in" in data:
        oauth["refreshTokenExpiresAt"] = now_ms + int(data["refresh_token_expires_in"]) * 1000

    _save_credentials(creds)
    return oauth["accessToken"]


def _get_usage(token):
    return requests.get(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        },
        timeout=REQUEST_TIMEOUT,
    )


def _fetch_usage():
    creds = _load_credentials()
    oauth = creds["claudeAiOauth"]
    now_ms = int(time.time() * 1000)

    if oauth.get("expiresAt", 0) - now_ms < REFRESH_MARGIN_MS:
        try:
            _refresh_access_token(creds)
        except Exception:
            pass  # fall through on the old token; a real problem surfaces below

    resp = _get_usage(oauth["accessToken"])

    if resp.status_code in (401, 403):
        # Access token died sooner than expiresAt claimed (or the proactive
        # refresh above failed transiently) - refresh once and retry before
        # giving up.
        try:
            token = _refresh_access_token(creds)
        except Exception:
            raise TokenStale()
        resp = _get_usage(token)
        if resp.status_code in (401, 403):
            raise TokenStale()

    if resp.status_code == 429:
        try:
            retry_after = int(resp.headers.get("Retry-After", ""))
        except ValueError:
            retry_after = POLL_SECONDS
        raise RateLimited(retry_after)

    resp.raise_for_status()
    payload = resp.json()
    return {
        "five_hour": round(payload["five_hour"]["utilization"]),
        "seven_day": round(payload["seven_day"]["utilization"]),
        "five_hour_resets": payload["five_hour"].get("resets_at"),
        "seven_day_resets": payload["seven_day"].get("resets_at"),
    }


def _format_reset(iso_ts, period_seconds=None):
    if not iso_ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    # Windows reset on a fixed cadence, so a reset time that has already lapsed
    # (e.g. the value we last saw before the week rolled over, kept because the
    # endpoint briefly stopped reporting a new one) can be advanced by whole
    # periods to recover the correct next reset without a fresh read.
    if period_seconds:
        now = datetime.now(timezone.utc)
        if dt <= now:
            elapsed = (now - dt).total_seconds()
            dt += timedelta(seconds=period_seconds * (int(elapsed // period_seconds) + 1))
    return dt.astimezone().strftime("%a %I:%M %p").lstrip("0")


def _severity_color(pct):
    if pct is None:
        return (110, 110, 110, 255)
    if pct >= 90:
        return (195, 45, 45, 255)
    if pct >= 70:
        return (210, 150, 30, 255)
    return (40, 140, 70, 255)


_FONT_CACHE = {}


def _get_font(size):
    if size not in _FONT_CACHE:
        try:
            _FONT_CACHE[size] = ImageFont.truetype(FONT_PATH, size)
        except OSError:
            _FONT_CACHE[size] = ImageFont.load_default()
    return _FONT_CACHE[size]


def _make_number_icon(pct, stale=False):
    size = 64
    color = _severity_color(pct)
    if stale:
        color = tuple(int(c * 0.55) for c in color[:3]) + (255,)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([1, 1, size - 2, size - 2], radius=16, fill=color)

    text = "?" if pct is None else str(min(pct, 99))
    font = _get_font(40 if len(text) < 3 else 32)
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((size / 2 - w / 2 - bbox[0], size / 2 - h / 2 - bbox[1]), text, font=font, fill="white")
    return img


def _is_stale(state):
    """True once the newest good read is old enough that the numbers can't be trusted."""
    if state["last_ok_at"] is None:
        return True
    return (time.monotonic() - state["last_ok_at"]) > STALE_AFTER_SECONDS


def _tooltips():
    """Build (5h tooltip, 7d tooltip) strings, each under the ~127 char Windows tray limit."""
    with _state_lock:
        s = dict(_state)

    if s["five_hour"] is None:
        msg = f"Claude usage unavailable\n{s['error'] or 'starting up'}"[:127]
        return msg, msg

    if s["error"]:
        age_min = int((time.monotonic() - s["last_ok_at"]) // 60) if s["last_ok_at"] else 0
        suffix = f"\n{s['error']} - read {age_min}m ago ({s['last_ok']})"
    else:
        suffix = ""
    tip_5h = f"Claude 5h session usage: {s['five_hour']}%\nResets {_format_reset(s['five_hour_resets'], FIVE_HOUR_PERIOD)}{suffix}"
    tip_7d = f"Claude 7d weekly usage: {s['seven_day']}%\nResets {_format_reset(s['seven_day_resets'], SEVEN_DAY_PERIOD)}{suffix}"
    return tip_5h[:127], tip_7d[:127]


def _poll_loop(icon_5h, icon_7d):
    """Poll forever. This loop must never be allowed to die - if it does, the icons
    freeze on old numbers while the process keeps running, which looks like working
    software. Every step is therefore inside a catch-all."""
    consecutive_failures = 0

    while not _stop_event.is_set():
        wait = POLL_SECONDS

        try:
            result = _fetch_usage()
            consecutive_failures = 0
            with _state_lock:
                # The endpoint briefly drops resets_at right after a window rolls
                # over (utilization 0, window not yet "active"). Don't let that
                # null wipe the last reset we knew - _format_reset rolls the kept
                # value forward a period so the tooltip stays correct meanwhile.
                for key in ("five_hour_resets", "seven_day_resets"):
                    if result[key] is None:
                        result[key] = _state[key]
                _state.update(result)
                _state["error"] = None
                _state["last_ok"] = datetime.now().strftime("%I:%M %p").lstrip("0")
                _state["last_ok_at"] = time.monotonic()
                published = dict(result)
            _publish_usage(published)

        except RateLimited as exc:
            # Not a malfunction - the shared per-account budget is spent, usually
            # because the Claude Code CLI is actively polling it too. Wait exactly
            # as long as the server asked, plus jitter so we don't resync with it.
            consecutive_failures = 0
            wait = max(exc.retry_after + random.randint(5, 30), MIN_POLL_SECONDS)
            with _state_lock:
                _state["error"] = f"rate limited, retry in {wait // 60}m"

        except TokenStale:
            consecutive_failures += 1
            wait = min(POLL_SECONDS * 2 ** min(consecutive_failures, 3), MAX_POLL_SECONDS)
            with _state_lock:
                _state["error"] = "login expired - run 'claude' to sign in again"

        except Exception as exc:
            consecutive_failures += 1
            wait = min(POLL_SECONDS * 2 ** min(consecutive_failures, 3), MAX_POLL_SECONDS)
            with _state_lock:
                _state["error"] = str(exc)[:50]

        try:
            with _state_lock:
                stale = _is_stale(_state)
                five_hour = _state["five_hour"]
                seven_day = _state["seven_day"]

            icon_5h.icon = _make_number_icon(five_hour, stale=stale)
            icon_7d.icon = _make_number_icon(seven_day, stale=stale)
            tip_5h, tip_7d = _tooltips()
            icon_5h.title = tip_5h
            icon_7d.title = tip_7d
        except Exception:
            # A transient Win32/Shell_NotifyIcon failure must not end the loop.
            pass

        _wake_event.wait(wait)
        _wake_event.clear()


def _on_quit(icon, item):
    _stop_event.set()
    _wake_event.set()
    icon_5h.stop()
    icon_7d.stop()


def main():
    global icon_5h, icon_7d

    placeholder = _make_number_icon(None)
    menu = pystray.Menu(
        pystray.MenuItem("Refresh now", lambda icon, item: _wake_event.set()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _on_quit),
    )

    icon_5h = pystray.Icon("claude-usage-5h", placeholder, "Claude 5h session usage", menu)
    icon_7d = pystray.Icon("claude-usage-7d", placeholder, "Claude 7d weekly usage", menu)

    poll_thread = threading.Thread(target=_poll_loop, args=(icon_5h, icon_7d), daemon=True)
    poll_thread.start()

    icon_7d.run_detached()
    icon_5h.run()


if __name__ == "__main__":
    main()
