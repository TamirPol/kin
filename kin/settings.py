"""Kin's household settings, set on the /setup page: who wears the band, and the emergency contacts.

Stored in kin_settings.json in the project root (never committed). Emergency contacts are the people who get
phone alerts; each has their own private ntfy topic, so one contact can be removed without affecting others.

    from kin import settings
    settings.wearer_name()                 -> "Grandpa Joe"
    settings.set_wearer("Ruth")            # also updates config.WEARER_NAME live
    settings.add_contact("Sarah", "daughter") -> {"id", "name", "relationship", "topic"}
    settings.contacts()
"""
from __future__ import annotations

import json
import secrets
import threading
from pathlib import Path

from . import config

import os
PATH = Path(os.environ.get("KIN_SETTINGS", config.ROOT / "kin_settings.json"))
_lock = threading.RLock()


def _load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(PATH)
    try:
        PATH.chmod(0o600)
    except OSError:
        pass


def get() -> dict:
    with _lock:
        d = _load()
        return {"wearer": d.get("wearer") or {"name": config.WEARER_NAME},
                "contacts": d.get("contacts") or []}


def wearer_name() -> str:
    return get()["wearer"].get("name") or config.WEARER_NAME


def set_wearer(name: str) -> dict:
    name = " ".join(name.split())[:60]
    if not name:
        raise ValueError("name is required")
    with _lock:
        d = _load()
        d["wearer"] = {"name": name}
        _save(d)
    config.WEARER_NAME = name                  # everything reads config.WEARER_NAME at call time
    return get()


def contacts() -> list[dict]:
    return get()["contacts"]


def add_contact(name: str, relationship: str = "") -> dict:
    name, relationship = " ".join(name.split())[:60], " ".join(relationship.split())[:40]
    if not name:
        raise ValueError("name is required")
    import os
    with _lock:
        d = _load()
        existing = os.environ.get("KIN_NTFY_TOPIC", "").strip()
        # the first contact keeps the household topic, so a phone that already subscribed keeps working
        topic = existing if existing and not d.get("contacts") else \
            "kin-" + secrets.token_urlsafe(18).replace("_", "").replace("-", "")[:24].lower()
        c = {"id": secrets.token_hex(4), "name": name, "relationship": relationship, "topic": topic}
        d.setdefault("contacts", []).append(c)
        _save(d)
    return c


def remove_contact(cid: str) -> bool:
    with _lock:
        d = _load()
        before = len(d.get("contacts", []))
        d["contacts"] = [c for c in d.get("contacts", []) if c["id"] != cid]
        _save(d)
        return len(d["contacts"]) != before


def first_contact_name() -> str:
    """Who Kin says it told ('I've let Sarah know'), or '' if no contacts are set up."""
    c = contacts()
    return c[0]["name"] if c else ""


def apply() -> None:
    """Load the saved wearer name into config at startup."""
    d = _load()
    if (d.get("wearer") or {}).get("name"):
        config.WEARER_NAME = d["wearer"]["name"]


def speed() -> float:
    """Kin's speaking speed (1.0 = normal), changed by voice: 'speak slower' / 'talk faster'."""
    try:
        return float(_load().get("voice_speed", 1.0))
    except (TypeError, ValueError):
        return 1.0


def set_speed(value: float) -> float:
    value = max(0.7, min(1.2, round(float(value), 2)))        # ElevenLabs' safe range; OpenAI allows more
    with _lock:
        d = _load()
        d["voice_speed"] = value
        _save(d)
    return value
