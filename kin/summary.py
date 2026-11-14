"""'Today so far': a short, plain-language summary of the wearer's day for the family dashboard.

Built from what Kin kept (important lines, people, facts, to-dos, item locations, alerts, what Kin said),
never from small talk. Regenerated at most once a minute, only when something changed.

    from kin import summary
    summary.today()        -> {"text": "...", "ts": 1794680000.0}
"""
from __future__ import annotations

import logging
import threading
import time

from . import config, memory

log = logging.getLogger("kin.summary")
_lock = threading.Lock()
_cache: dict = {"text": "", "ts": 0.0, "key": None}
MIN_GAP = 60.0

PROMPT = """You write the "Today so far" note that a caring adult child reads about their parent, {wearer},
who has early memory loss and wears Kin, a listening wristband. Write 2 to 4 short, warm, plain sentences
in the past tense about today: who he saw and anything important they said, what he did or planned,
reminders Kin gave and whether he followed up, and anything worrying (scam calls, falls, wandering) with
the time, stated calmly. Report each safety event exactly as listed: never say he was fine after a fall
unless the list says he double-tapped after that fall; an unanswered fall must be mentioned clearly. Only state what the notes show: never comment on what's missing or unknown
("the notes didn't say..."), never mention "notes". No lists, no jargon, no speaker labels, don't invent anything, don't mention
small talk. If very little happened, say so in one sentence.

Today's notes (times are local):
{notes}"""


def _notes() -> tuple[str, tuple]:
    start = time.time() - 16 * 3600
    lines = [l for l in memory.recent_lines(16 * 3600, limit=400) if l["importance"] is None or l["importance"] >= 1
             or l["speaker"] == "kin"]
    fmt = lambda ts: time.strftime("%-I:%M %p", time.localtime(ts))
    out = []
    for p in memory.people():
        facts = "; ".join(f["text"] for f in p["facts"][:4])
        out.append(f"- Person: {p['name']} ({p['relationship'] or 'relationship unknown'}). {facts}")
    for t in memory.todos(open_only=False)[:15]:
        if t["ts"] > start:
            out.append(f"- To-do at {fmt(t['ts'])}: {t['text']}{' (due ' + t['due'] + ')' if t['due'] else ''}"
                       f"{' — done' if t['done'] else ''}")
    for i in memory.items(10):
        if i["ts"] > start:
            out.append(f"- At {fmt(i['ts'])} his {i['item']} was {i['location']}")
    LABEL = {"scam": "POSSIBLE SCAM", "fall": "POSSIBLE FALL (Kin asked if he was okay)",
             "fall_ok": "He double-tapped: he was fine after that fall",
             "fall_emergency": "NO ANSWER after a possible fall: emergency alert sent to family",
             "wander": "BAND LEFT HOME (possible wandering)", "spending": "Purchase blocked"}
    safety = sorted((a for a in memory.alerts(40) if a["ts"] > start), key=lambda a: a["ts"])
    if safety:
        out.append("SAFETY EVENTS, in order (report these exactly, don't merge or soften them):")
        out += [f"- {fmt(a['ts'])}: {LABEL.get(a['kind'], a['kind'])}" for a in safety]
    for l in lines[-40:]:
        who = "Kin" if l["speaker"] == "kin" else (l["name"] or ("him" if l["speaker"] == "wearer" else "someone"))
        out.append(f"- {fmt(l['ts'])} {who}: {l['text']}")
    key = (len(lines), lines[-1]["id"] if lines else 0, len(out))
    return "\n".join(out)[:7000], key


def _fallback(notes: str) -> str:
    n_people = len(memory.people())
    alerts = [a for a in memory.alerts(20) if a["kind"] in ("scam", "fall", "fall_emergency", "wander")
              and time.time() - a["ts"] < 16 * 3600]
    parts = [f"{config.WEARER_NAME} talked with {n_people} {'person' if n_people == 1 else 'people'} Kin knows today."
             if n_people else f"Kin has been listening with {config.WEARER_NAME} today."]
    todo = [t for t in memory.todos()]
    if todo:
        parts.append(f"He still plans to {todo[0]['text'].rstrip('.').lower()}.")
    if alerts:
        parts.append(f"There {'was' if len(alerts) == 1 else 'were'} {len(alerts)} alert"
                     f"{'' if len(alerts) == 1 else 's'} today; see below.")
    return " ".join(parts)


def today(force: bool = False) -> dict:
    """The current summary; regenerated when memory changed and at least a minute has passed."""
    notes, key = _notes()
    n_alerts = len(memory.alerts(100))
    with _lock:
        new_safety = n_alerts != _cache.get("alerts")    # a fall/scam/wander must show up right away
        fresh = _cache["key"] == key or (time.time() - _cache["ts"] < MIN_GAP and _cache["text"] and not new_safety)
        if fresh and not force:
            return {"text": _cache["text"], "ts": _cache["ts"]}
    if not notes.strip():
        text = f"Nothing to report yet today. Kin is listening with {config.WEARER_NAME}."
    elif config.OPENAI_API_KEY:
        try:
            from openai import OpenAI
            r = OpenAI(api_key=config.OPENAI_API_KEY).chat.completions.create(
                model=config.OPENAI_MODEL, reasoning_effort="none",
                messages=[{"role": "user", "content": PROMPT.format(wearer=config.WEARER_NAME, notes=notes)}])
            text = r.choices[0].message.content.strip()
        except Exception as e:
            log.warning("summary failed, using a simple one: %s", e)
            text = _fallback(notes)
    else:
        text = _fallback(notes)
    with _lock:
        _cache.update(text=text, ts=time.time(), key=key, alerts=n_alerts)
    return {"text": text, "ts": _cache["ts"]}
