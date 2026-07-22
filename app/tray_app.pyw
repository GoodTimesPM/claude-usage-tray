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
import threading
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFont
import pystray

POLL_SECONDS = 180  # 3 minutes - sweet spot between freshness and idle load
REQUEST_TIMEOUT = 6
CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"

_state_lock = threading.Lock()
_state = {
    "five_hour": None,
    "seven_day": None,
    "five_hour_resets": None,
    "seven_day_resets": None,
    "last_ok": None,
    "error": None,
}
_wake_event = threading.Event()
_stop_event = threading.Event()


def _read_access_token():
    with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["claudeAiOauth"]["accessToken"]


def _fetch_usage():
    token = _read_access_token()
    resp = requests.get(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    return {
        "five_hour": round(payload["five_hour"]["utilization"]),
        "seven_day": round(payload["seven_day"]["utilization"]),
        "five_hour_resets": payload["five_hour"].get("resets_at"),
        "seven_day_resets": payload["seven_day"].get("resets_at"),
    }


def _format_reset(iso_ts):
    if not iso_ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%a %I:%M %p").lstrip("0")
    except ValueError:
        return "unknown"


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


def _tooltips():
    """Build (5h tooltip, 7d tooltip) strings, each under the ~127 char Windows tray limit."""
    with _state_lock:
        s = dict(_state)

    if s["five_hour"] is None and s["error"]:
        msg = f"Claude usage unavailable\n{s['error']}"[:127]
        return msg, msg

    suffix = f"\n(stale since {s['last_ok']}: {s['error']})" if s["error"] else ""
    tip_5h = f"Claude 5h session usage: {s['five_hour']}%\nResets {_format_reset(s['five_hour_resets'])}{suffix}"
    tip_7d = f"Claude 7d weekly usage: {s['seven_day']}%\nResets {_format_reset(s['seven_day_resets'])}{suffix}"
    return tip_5h[:127], tip_7d[:127]


def _poll_loop(icon_5h, icon_7d):
    while not _stop_event.is_set():
        try:
            result = _fetch_usage()
            with _state_lock:
                _state.update(result)
                _state["error"] = None
                _state["last_ok"] = datetime.now().strftime("%I:%M %p").lstrip("0")
        except Exception as exc:
            with _state_lock:
                _state["error"] = str(exc)[:60]

        with _state_lock:
            stale = _state["error"] is not None
            five_hour = _state["five_hour"]
            seven_day = _state["seven_day"]

        icon_5h.icon = _make_number_icon(five_hour, stale=stale)
        icon_7d.icon = _make_number_icon(seven_day, stale=stale)
        tip_5h, tip_7d = _tooltips()
        icon_5h.title = tip_5h
        icon_7d.title = tip_7d

        _wake_event.wait(POLL_SECONDS)
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
