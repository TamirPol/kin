"""Kin's memory: one SQLite file shared by every part of the app.

This module is the contract between the parts (band/listen, ask, dashboard, safety,
vision). Other modules only call the functions here; they never write SQL themselves.

Tables
  transcript  every heard line (kept 24 h): speaker label, resolved name, text, importance
  people      one row per person: name, relationship, voice speaker label (this session)
  facts       things learned about a person (person_id may be NULL for general facts)
  todos       plans and promises
  items       where things were put (source 'voice' or 'vision', optional snapshot path)
  alerts      scam / fall / spending alerts for the family
  purchases   what the Stripe agent tried to buy and whether it was allowed
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from .config import DB_PATH

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_listeners: list = []          # callables(event: dict) -> None, for live dashboard updates

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcript (
  id INTEGER PRIMARY KEY, ts REAL, speaker TEXT, name TEXT, text TEXT,
  importance INTEGER DEFAULT -1, category TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE, relationship TEXT DEFAULT '',
  speaker TEXT DEFAULT '', last_seen REAL, created REAL);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY, ts REAL, person_id INTEGER, text TEXT, category TEXT, importance INTEGER);
CREATE TABLE IF NOT EXISTS todos (
  id INTEGER PRIMARY KEY, ts REAL, text TEXT, due TEXT DEFAULT '', person_id INTEGER, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY, ts REAL, item TEXT, location TEXT, source TEXT, snapshot TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY, ts REAL, kind TEXT, text TEXT, seen INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY, ts REAL, item TEXT, merchant TEXT, amount_cents INTEGER,
  status TEXT, reason TEXT, stripe_id TEXT DEFAULT '');
"""


def db() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            cols = {r[1] for r in _conn.execute("PRAGMA table_info(todos)")}
            if "reminded" not in cols:                  # added later: when Kin last reminded about it
                _conn.execute("ALTER TABLE todos ADD COLUMN reminded REAL DEFAULT 0")
            _conn.commit()
        return _conn


def _exec(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = db().execute(sql, args)
        db().commit()
        return cur.lastrowid


def _rows(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in db().execute(sql, args).fetchall()]


def on_change(fn) -> None:
    """Register fn(event) to be called after every write. event = {'table': ..., 'row': {...}}."""
    _listeners.append(fn)


def _emit(table: str, row: dict) -> None:
    for fn in list(_listeners):
        try:
            fn({"table": table, "row": row})
        except Exception:
            pass


# ---------- transcript ----------
def add_line(speaker: str, text: str, name: str = "") -> int:
    ts = time.time()
    rid = _exec("INSERT INTO transcript(ts,speaker,name,text) VALUES(?,?,?,?)", (ts, speaker, name, text))
    _emit("transcript", {"id": rid, "ts": ts, "speaker": speaker, "name": name, "text": text, "importance": -1})
    return rid


def rate_lines(ids: list[int], importance: int, category: str = "") -> None:
    for i in ids:
        _exec("UPDATE transcript SET importance=?, category=? WHERE id=?", (importance, category, i))
        _emit("transcript_rated", {"id": i, "importance": importance, "category": category})


def recent_lines(seconds: float = 86400, limit: int = 200) -> list[dict]:
    return _rows("SELECT * FROM transcript WHERE ts>? ORDER BY id DESC LIMIT ?", (time.time() - seconds, limit))[::-1]


def prune_transcript(hours: float = 24) -> None:
    _exec("DELETE FROM transcript WHERE ts<?", (time.time() - hours * 3600,))


# ---------- people ----------
def upsert_person(name: str, relationship: str = "", speaker: str = "") -> int:
    name = name.strip()
    now = time.time()
    with _lock:
        row = db().execute("SELECT * FROM people WHERE name=?", (name,)).fetchone()
        if row:
            _exec("UPDATE people SET relationship=COALESCE(NULLIF(?,''),relationship), "
                  "speaker=COALESCE(NULLIF(?,''),speaker), last_seen=? WHERE id=?",
                  (relationship, speaker, now, row["id"]))
            pid = row["id"]
        else:
            pid = _exec("INSERT INTO people(name,relationship,speaker,last_seen,created) VALUES(?,?,?,?,?)",
                        (name, relationship, speaker, now, now))
    _emit("people", person(pid))
    return pid


def person(pid: int) -> dict | None:
    r = _rows("SELECT * FROM people WHERE id=?", (pid,))
    if not r:
        return None
    p = r[0]
    p["facts"] = _rows("SELECT * FROM facts WHERE person_id=? ORDER BY ts DESC", (pid,))
    return p


def find_person(name: str) -> dict | None:
    r = _rows("SELECT id FROM people WHERE name LIKE ?", (f"%{name.strip()}%",))
    return person(r[0]["id"]) if r else None


def person_by_speaker(speaker: str) -> dict | None:
    if not speaker:
        return None
    r = _rows("SELECT id FROM people WHERE speaker=? ORDER BY last_seen DESC", (speaker,))
    return person(r[0]["id"]) if r else None


def people() -> list[dict]:
    return [person(r["id"]) for r in _rows("SELECT id FROM people ORDER BY last_seen DESC")]


# ---------- facts, todos, items ----------
def add_fact(text: str, person_id: int | None = None, category: str = "", importance: int = 2) -> int:
    ts = time.time()
    rid = _exec("INSERT INTO facts(ts,person_id,text,category,importance) VALUES(?,?,?,?,?)",
                (ts, person_id, text, category, importance))
    _emit("facts", {"id": rid, "ts": ts, "person_id": person_id, "text": text, "category": category})
    if person_id:
        _emit("people", person(person_id))
    return rid


def add_todo(text: str, due: str = "", person_id: int | None = None) -> int:
    ts = time.time()
    rid = _exec("INSERT INTO todos(ts,text,due,person_id) VALUES(?,?,?,?)", (ts, text, due, person_id))
    _emit("todos", {"id": rid, "ts": ts, "text": text, "due": due, "done": 0})
    return rid


def todos(open_only: bool = True) -> list[dict]:
    return _rows("SELECT * FROM todos " + ("WHERE done=0 " if open_only else "") + "ORDER BY ts DESC")


def mark_reminded(tid: int) -> None:
    _exec("UPDATE todos SET reminded=? WHERE id=?", (time.time(), tid))


def finish_todo(tid: int) -> None:
    _exec("UPDATE todos SET done=1 WHERE id=?", (tid,))
    _emit("todos", {"id": tid, "done": 1})


def add_item(item: str, location: str, source: str = "voice", snapshot: str = "") -> int:
    ts = time.time()
    rid = _exec("INSERT INTO items(ts,item,location,source,snapshot) VALUES(?,?,?,?,?)",
                (ts, item.lower().strip(), location, source, snapshot))
    _emit("items", {"id": rid, "ts": ts, "item": item, "location": location, "source": source, "snapshot": snapshot})
    return rid


def find_item(item: str) -> dict | None:
    r = _rows("SELECT * FROM items WHERE item LIKE ? ORDER BY ts DESC LIMIT 1", (f"%{item.lower().strip()}%",))
    return r[0] if r else None


def items(limit: int = 50) -> list[dict]:
    return _rows("SELECT * FROM items ORDER BY ts DESC LIMIT ?", (limit,))


# ---------- alerts, purchases ----------
def add_alert(kind: str, text: str) -> int:
    ts = time.time()
    rid = _exec("INSERT INTO alerts(ts,kind,text) VALUES(?,?,?)", (ts, kind, text))
    _emit("alerts", {"id": rid, "ts": ts, "kind": kind, "text": text})
    return rid


def alerts(limit: int = 50) -> list[dict]:
    return _rows("SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,))


def add_purchase(item: str, merchant: str, amount_cents: int, status: str, reason: str, stripe_id: str = "") -> int:
    ts = time.time()
    rid = _exec("INSERT INTO purchases(ts,item,merchant,amount_cents,status,reason,stripe_id) VALUES(?,?,?,?,?,?,?)",
                (ts, item, merchant, amount_cents, status, reason, stripe_id))
    _emit("purchases", {"id": rid, "ts": ts, "item": item, "merchant": merchant,
                        "amount_cents": amount_cents, "status": status, "reason": reason})
    return rid


def purchases(limit: int = 50) -> list[dict]:
    return _rows("SELECT * FROM purchases ORDER BY ts DESC LIMIT ?", (limit,))


# ---------- everything, for the dashboard and the ask-mode prompt ----------
def snapshot() -> dict[str, Any]:
    return {"people": people(), "todos": todos(), "items": items(), "alerts": alerts(),
            "purchases": purchases(), "transcript": recent_lines(limit=100)}


def summary_for_llm(max_chars: int = 6000) -> str:
    """A compact text version of memory for the ask-mode system prompt."""
    s = snapshot()
    out = ["PEOPLE:"]
    for p in s["people"]:
        facts = "; ".join(f["text"] for f in p["facts"][:8])
        out.append(f"- {p['name']} ({p['relationship'] or 'relationship unknown'}): {facts}")
    out.append("OPEN TODOS:")
    out += [f"- {t['text']}" + (f" (due {t['due']})" if t['due'] else "") for t in s["todos"][:20]]
    out.append("WHERE THINGS ARE (latest first):")
    out += [f"- {i['item']}: {i['location']} ({_ago(i['ts'])})" for i in s["items"][:20]]
    text = "\n".join(out)
    return text[:max_chars]


def _ago(ts: float) -> str:
    m = int((time.time() - ts) / 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago"


def dumps(obj) -> str:
    return json.dumps(obj, default=str)
