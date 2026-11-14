"""Phone push alerts for the family, through ntfy (https://ntfy.sh, free, open source).

The family installs the ntfy app and subscribes to Kin's private topic (a long random name kept in .env as
KIN_NTFY_TOPIC). When Kin raises a scam, fall or wander alert, the phone gets a real push notification.

Privacy: the alert passes through ntfy's public server, and anyone who knows the topic name can read it.
So the topic is long and random, and messages are short and generic: never transcripts, names of other
people, amounts or places.

    python -m kin.notify          # prints the topic + subscribe link and sends a test notification
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import urllib.request
from pathlib import Path

from . import config, memory

log = logging.getLogger("kin.notify")
SERVER = os.environ.get("KIN_NTFY_SERVER", "https://ntfy.sh").rstrip("/")
ENV_FILE = config.ROOT / ".env"

# alert kind -> (title, short generic body, ntfy priority 1-5, tags)
MESSAGES = {
    "scam": ("{w} may not be OK", "Possible scam call. Kin warned him not to send any money.", 5, "rotating_light"),
    # "fall" itself sends nothing: Kin asks first and only "fall_emergency" (no answer) alerts the phones
    "fall_emergency": ("{w} needs a check-in now", "No answer after a possible fall. Please call or visit.", 5,
                       "sos"),
    "wander": ("{w} may have wandered off", "His band lost touch with home.", 4, "walking"),
    "confused": ("{w} may need you", "He sounded confused or unwell. Kin is keeping him calm; please call him.", 4,
                 "speech_balloon"),
    "spending": ("Kin blocked a purchase", "A purchase was blocked by the family limits.", 3, "credit_card"),
}


def topic() -> str:
    """The private topic; created once and saved to .env (which is never committed)."""
    t = os.environ.get("KIN_NTFY_TOPIC", "").strip()
    if t:
        return t
    t = "kin-" + secrets.token_urlsafe(18).replace("_", "").replace("-", "")[:24].lower()
    try:
        with open(ENV_FILE, "a") as f:
            f.write(f"\nKIN_NTFY_TOPIC={t}\n")
        os.chmod(ENV_FILE, 0o600)
    except OSError as e:
        log.warning("Could not save the ntfy topic to .env: %s", e)
    os.environ["KIN_NTFY_TOPIC"] = t
    return t


def subscribe_url() -> str:
    return f"{SERVER}/{topic()}"


def topics() -> list[str]:
    """Every emergency contact's own topic (from /setup); the household topic if none are set up."""
    try:
        from . import settings
        t = [c["topic"] for c in settings.contacts() if c.get("topic")]
    except Exception:
        t = []
    return t or [topic()]


def send(title: str, body: str, priority: int = 3, tags: str = "", to: list[str] | None = None) -> bool:
    """Push one notification to every emergency contact (or the given topics). Never raises."""
    if os.environ.get("KIN_NTFY", "on").lower() in ("off", "0", "false"):
        return False
    ok = False
    for t in (to or topics()):
        ok = _send_one(t, title, body, priority, tags) or ok
    return ok


def _send_one(t: str, title: str, body: str, priority: int, tags: str) -> bool:
    req = urllib.request.Request(f"{SERVER}/{t}", data=body.encode(), method="POST", headers={
        "Title": title.encode("utf-8").decode("latin-1", "ignore"),
        "Priority": str(priority), "Tags": tags})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return 200 <= r.status < 300
    except Exception as e:
        log.warning("Phone alert not sent: %s", e)
        return False


def _on_change(event: dict) -> None:
    if event.get("table") != "alerts":
        return
    row = event.get("row") or {}
    if row.get("seen"):                       # an acknowledgement, not a new alert
        return
    msg = MESSAGES.get(row.get("kind", ""))
    if not msg:
        return
    title, body, prio, tags = msg
    threading.Thread(target=send, args=(title.format(w=config.WEARER_NAME), body, prio, tags),
                     daemon=True).start()


_hooked = False


def start() -> str:
    """Send phone alerts for every new scam/fall/wander alert. Returns the subscribe URL."""
    global _hooked
    if not _hooked:
        memory.on_change(_on_change)
        _hooked = True
    return subscribe_url()


if __name__ == "__main__":
    url = subscribe_url()
    print(f"Kin phone alerts topic: {topic()}\nSubscribe in the ntfy app (or open): {url}")
    ok = send("Kin is connected", f"Phone alerts for {config.WEARER_NAME} are on.", 3, "white_check_mark")
    print("Test notification sent." if ok else "Could not send the test notification.")
