"""Kin family dashboard: a small FastAPI app with a live WebSocket feed.

The main app calls:
    from kin import dashboard
    dashboard.start_in_thread()                 # serves http://localhost:8700
    dashboard.publish({'table': 'status', 'row': {'mode': 'listen', 'band': 'connected', 'note': ''}})

Every memory write (memory.on_change) and every publish() is pushed to all /ws clients.
Both can be called from any thread or event loop.

Run on its own:  .venv/bin/python -m kin.dashboard
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, memory

STATIC_DIR = Path(__file__).resolve().parent / "static"
SNAPSHOT_DIR = config.ROOT / "snapshots"

# ---------- live event fan-out (thread-safe) ----------
_clients: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
_clients_lock = threading.Lock()
_status: dict = {"mode": "listen", "band": "disconnected", "note": ""}
_hooked = False
_command_handler = None        # set by the main app: fn(cmd: str) runs a terminal-style command


def set_command_handler(fn) -> None:
    """The main app registers how to run test commands from the /test page (t, f, r, a <question>...)."""
    global _command_handler
    _command_handler = fn


def _broadcast(event: dict) -> None:
    """Called from any thread. Hands the event to every connected client's loop."""
    try:
        msg = memory.dumps(event)
    except Exception:
        return
    with _clients_lock:
        clients = list(_clients)
    for loop, q in clients:
        try:
            loop.call_soon_threadsafe(q.put_nowait, msg)
        except RuntimeError:          # loop closed
            pass


def publish(event: dict) -> None:
    """Send a non-memory event (e.g. {'table':'status','row':{...}}) to the dashboard."""
    if event.get("table") == "status" and isinstance(event.get("row"), dict):
        _status.update(event["row"])
        event = {"table": "status", "row": dict(_status)}
    _broadcast(event)


def _hook_memory() -> None:
    global _hooked
    if not _hooked:
        memory.on_change(_broadcast)
        _hooked = True


# ---------- small helpers that memory.py doesn't have ----------
def _delete_fact(fid: int) -> dict | None:
    with memory._lock:
        row = memory.db().execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
        if not row:
            return None
        memory.db().execute("DELETE FROM facts WHERE id=?", (fid,))
        memory.db().commit()
    return dict(row)


def _mark_alert_seen(aid: int) -> dict | None:
    """Family acknowledged an alert on the dashboard (uses the existing alerts.seen column)."""
    with memory._lock:
        memory.db().execute("UPDATE alerts SET seen=1 WHERE id=?", (aid,))
        memory.db().commit()
        row = memory.db().execute("SELECT * FROM alerts WHERE id=?", (aid,)).fetchone()
    return dict(row) if row else None


class CommandIn(BaseModel):
    cmd: str


class NameIn(BaseModel):
    name: str


class ContactIn(BaseModel):
    name: str
    relationship: str = ""


class PersonIn(BaseModel):
    name: str
    relationship: str = ""


# ---------- the app ----------
def create_app() -> FastAPI:
    _hook_memory()
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    app = FastAPI(title="Kin dashboard")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/test")
    def test_page():
        return FileResponse(STATIC_DIR / "test.html", headers={"Cache-Control": "no-store"})

    @app.post("/api/command")
    def command(c: CommandIn):
        cmd = c.cmd.strip()[:300]
        if cmd.split(" ", 1)[0] not in ("t", "f", "r", "a", "w", "1", "2", "3", "away", "home", "enroll"):
            raise HTTPException(400, "unknown command")
        if not _command_handler:
            raise HTTPException(503, "Kin is not running")
        _command_handler(cmd)
        return {"ok": True}

    @app.get("/setup")
    def setup_page():
        return FileResponse(STATIC_DIR / "setup.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/settings")
    def get_settings():
        from . import settings, notify
        s = settings.get()
        for c in s["contacts"]:
            c["subscribe_url"] = f"{notify.SERVER}/{c['topic']}"
        return s

    @app.post("/api/settings/wearer")
    def set_wearer(n: NameIn):
        from . import settings
        try:
            s = settings.set_wearer(n.name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        publish({"table": "status", "row": {"note": f"Kin is now looking after {s['wearer']['name']}"}})
        return s

    @app.post("/api/contacts")
    def add_contact(c: ContactIn):
        from . import settings, notify
        try:
            row = settings.add_contact(c.name, c.relationship)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if c.relationship:
            memory.upsert_person(row["name"], relationship=row["relationship"])
        row["subscribe_url"] = f"{notify.SERVER}/{row['topic']}"
        return row

    @app.post("/api/people")
    def add_life_person(c: ContactIn):
        from . import settings
        try:
            row = settings.add_person(c.name, c.relationship)
        except ValueError as e:
            raise HTTPException(400, str(e))
        memory.upsert_person(row["name"], relationship=row["relationship"])
        return row

    @app.delete("/api/people/{pid}")
    def remove_life_person(pid: str):
        from . import settings
        if not settings.remove_person(pid):
            raise HTTPException(404, "no such person")
        return {"ok": True}

    @app.delete("/api/contacts/{cid}")
    def remove_contact(cid: str):
        from . import settings
        if not settings.remove_contact(cid):
            raise HTTPException(404, "no such contact")
        return {"ok": True}

    @app.post("/api/contacts/{cid}/test")
    def test_contact(cid: str):
        from . import settings, notify
        c = next((x for x in settings.contacts() if x["id"] == cid), None)
        if not c:
            raise HTTPException(404, "no such contact")
        ok = notify.send("Kin test alert", f"Hi {c['name']}, you'll get alerts about {config.WEARER_NAME} here.",
                         3, "white_check_mark", to=[c["topic"]])
        return {"ok": ok}

    @app.post("/api/actor/{name}")
    def actor(name: str):
        """Demo helper: the laptop speakers play another person (scripts/actors.sh). Localhost only."""
        import subprocess
        if name not in ("sarah", "leo", "scam", "doctor", "neighbor", "cashier"):
            raise HTTPException(404, "unknown actor")
        subprocess.Popen(["bash", str(config.ROOT / "scripts" / "actors.sh"), name],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "playing": name}

    @app.get("/api/summary")
    def summary_today():
        from . import summary
        return summary.today()

    @app.get("/api/voices")
    def voices():
        try:
            from . import voiceprint
            return {"voices": voiceprint.list_voices()}
        except Exception as e:
            return {"voices": [], "error": str(e)}

    @app.get("/api/snapshot")
    def snapshot():
        s = memory.snapshot()
        s["status"] = dict(_status)
        s["config"] = {"wearer": config.WEARER_NAME, "spend_limit_cents": config.SPEND_LIMIT_CENTS}
        return JSONResponse(json.loads(memory.dumps(s)))

    @app.post("/api/person")
    def add_person(p: PersonIn):
        name = p.name.strip()
        if not name:
            raise HTTPException(400, "name is required")
        pid = memory.upsert_person(name[:80], p.relationship.strip()[:80])
        return memory.person(pid)

    @app.post("/api/todo/{tid}/done")
    def todo_done(tid: int):
        memory.finish_todo(tid)
        return {"ok": True, "id": tid}

    @app.post("/api/alert/{aid}/seen")
    def alert_seen(aid: int):
        row = _mark_alert_seen(aid)
        if not row:
            raise HTTPException(404, "no such alert")
        _broadcast({"table": "alerts", "row": row})
        return {"ok": True, "id": aid}

    @app.delete("/api/fact/{fid}")
    def delete_fact(fid: int):
        row = _delete_fact(fid)
        if not row:
            raise HTTPException(404, "no such fact")
        _broadcast({"table": "facts_deleted", "row": {"id": fid, "person_id": row["person_id"]}})
        if row["person_id"]:
            p = memory.person(row["person_id"])
            if p:
                _broadcast({"table": "people", "row": p})
        return {"ok": True, "id": fid}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        entry = (loop, q)
        with _clients_lock:
            _clients.add(entry)
        try:
            await sock.send_text(memory.dumps({"table": "status", "row": dict(_status)}))

            async def drain_incoming():
                while True:
                    await sock.receive_text()      # ignore; detects disconnect

            reader = asyncio.create_task(drain_incoming())
            try:
                while True:
                    getter = asyncio.create_task(q.get())
                    done, _ = await asyncio.wait({getter, reader}, return_when=asyncio.FIRST_COMPLETED)
                    if reader in done:
                        getter.cancel()
                        break
                    await sock.send_text(getter.result())
            finally:
                reader.cancel()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            with _clients_lock:
                _clients.discard(entry)

    app.mount("/snapshots", StaticFiles(directory=SNAPSHOT_DIR), name="snapshots")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def start_in_thread(port: int = config.DASHBOARD_PORT, host: str = "0.0.0.0") -> threading.Thread:
    """Run the dashboard in a daemon thread. Returns the thread."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(create_app(), host=host, port=port, log_level="warning"))
    t = threading.Thread(target=server.run, name="kin-dashboard", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    import uvicorn

    print(f"Kin dashboard on http://localhost:{config.DASHBOARD_PORT}  (db: {config.DB_PATH})")
    uvicorn.run(create_app(), host="0.0.0.0", port=config.DASHBOARD_PORT, log_level="info")
