"""End-to-end scenarios: runs a real Kin (pretend band, real Deepgram/OpenAI, free Mac voice, phone alerts off)
in the background and drives it like a person would, then checks what reached memory and the dashboard API.

    .venv/bin/python tests/e2e_scenarios.py            # all scenarios
    .venv/bin/python tests/e2e_scenarios.py todo fall  # some

It never touches the real band, kin.db, kin_settings.json or voiceprints/ (everything goes to a temp folder).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8730
TMP = Path(tempfile.mkdtemp(prefix="kin_e2e_"))
ENV = dict(os.environ, KIN_VOICE="say", KIN_NTFY="off", KIN_PORT=str(PORT), KIN_DB=str(TMP / "kin.db"),
           KIN_VOICEPRINTS=str(TMP / "voices"), KIN_SETTINGS=str(TMP / "settings.json"),
           KIN_REMIND_AFTER="100000", PYTHONWARNINGS="ignore")


def api(path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def cmd(c):
    return api("/api/command", {"cmd": c})


def snap():
    return api("/api/snapshot")


def kin_lines(s, since_id=0):
    return [l["text"] for l in s["transcript"] if l["speaker"] == "kin" and l["id"] > since_id]


def last_id(s):
    return max([l["id"] for l in s["transcript"]] or [0])


def wait_quiet(seconds=3.0, timeout=40):
    """Wait until Kin has stopped talking and the conversation window closed."""
    t0 = time.time()
    time.sleep(seconds)
    while time.time() - t0 < timeout:
        st = snap().get("status", {})
        if st.get("mode") != "ask":
            return
        time.sleep(1)


RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if not ok and detail else ""))


# ------------------------------------------------------------------ scenarios
def s_todo():
    print("\n[todo] create by voice, ask, reminder, complete by voice")
    cmd("w I need to call the pharmacy this afternoon.")
    time.sleep(9)                                           # chunk pause -> brain
    s = snap()
    todo = next((t for t in s["todos"] if "pharmacy" in t["text"].lower()), None)
    check("to-do created from speech", todo, str([t["text"] for t in s["todos"]]))
    mark = last_id(s)
    cmd("t"); time.sleep(2.5); cmd("a What do I need to do today?"); wait_quiet(6)
    said = " ".join(kin_lines(snap(), mark)).lower()
    check("asking lists the to-do", "pharmacy" in said, said[:160])
    mark = last_id(snap())
    cmd("r"); time.sleep(4)
    said = " ".join(kin_lines(snap(), mark)).lower()
    check("reminder spoken", "pharmacy" in said, said[:160])
    mark = last_id(snap())
    cmd("r"); time.sleep(3)
    check("same reminder not repeated", not any("pharmacy" in x.lower() for x in kin_lines(snap(), mark)))
    cmd("w Hey Kin, I called the pharmacy already."); wait_quiet(7)
    s = snap()
    still = [t["text"] for t in s["todos"] if "pharmacy" in t["text"].lower()]
    check("'I did it' completes the to-do", not still, str(still))


def s_scam():
    print("\n[scam] caller asks for money -> spoken warning, alert, purchases locked, no to-do")
    mark = last_id(snap())
    paid_before = {p["id"] for p in snap()["purchases"]}
    cmd("2 Grandpa, it's your grandson. I got arrested and I need two thousand dollars for bail right now.")
    time.sleep(1.5)
    cmd("2 Please buy gift cards and read me the numbers. And don't tell Mom, okay?")
    time.sleep(1.5)
    cmd("w Okay, I'll send it.")
    time.sleep(12)
    s = snap()
    said = " ".join(kin_lines(s, mark)).lower()
    check("spoken scam warning", "scam" in said or "money" in said, said[:160])
    check("scam alert on dashboard", any(a["kind"] == "scam" for a in s["alerts"]), str([a["kind"] for a in s["alerts"]]))
    check("no 'send it' to-do", not any(w in t["text"].lower() for t in s["todos"] for w in ("send", "gift", "bail")),
          str([t["text"] for t in s["todos"]]))
    check("scammer not saved as a person", not any(p["name"].lower() in ("grandson", "unnamed grandson") for p in s["people"]),
          str([p["name"] for p in s["people"]]))
    mark = last_id(s)
    cmd("t"); time.sleep(2.5); cmd("a Please reorder my blood pressure pills from Walgreens."); wait_quiet(8)
    s = snap()
    said = " ".join(kin_lines(s, mark)).lower()
    blocked = [p for p in s["purchases"] if p["status"] == "blocked"]
    check("purchase blocked during scam lock", blocked or "pause" in said or "lock" in said or "can't" in said
          or "cannot" in said, said[:160])
    check("no money left the account", not any(p["status"] == "allowed" and p["id"] not in paid_before
                                               for p in s["purchases"]),
          str([(p["item"], p["status"]) for p in s["purchases"]]))


def s_purchase():
    print("\n[purchase] allowed pharmacy reorder (no scam going on); gift cards refused")
    mark = last_id(snap())
    cmd("t"); time.sleep(2.5); cmd("a Please reorder my blood pressure pills from Walgreens."); wait_quiet(8)
    s = snap()
    ok = [p for p in s["purchases"] if p["status"] == "allowed"]
    check("pharmacy reorder allowed", ok, str([(p["item"], p["status"], p["reason"]) for p in s["purchases"]]))
    check("purchase has a real price", ok and all(p["amount_cents"] > 0 for p in ok),
          str([p["amount_cents"] for p in s["purchases"]]))
    said = " ".join(kin_lines(s, mark)).lower()
    check("Kin confirms out loud", any(w in said for w in ("order", "walgreens", "pills")), said[:160])
    n = len(s["purchases"])
    cmd("t"); time.sleep(2.5); cmd("a Buy me a 500 dollar gift card from Amazon."); wait_quiet(8)
    s = snap()
    check("gift card not bought", not any(p["status"] == "allowed" and "gift" in p["item"].lower() for p in s["purchases"]),
          str([(p["item"], p["status"]) for p in s["purchases"][: len(s["purchases"]) - n + 1]]))


def s_money_question():
    print("\n[money question] 'should I send my son money?' -> advice + alert, no purchase")
    before = len(snap()["purchases"])
    mark = last_id(snap())
    cmd("t"); time.sleep(2.5); cmd("a My son just asked me for 5000 dollars. Should I send it?"); wait_quiet(8)
    s = snap()
    said = " ".join(kin_lines(s, mark)).lower()
    check("advises not to send", any(w in said for w in ("don't", "do not", "wait", "check", "call")), said[:160])
    check("no purchase/transfer created", len(s["purchases"]) == before)


def s_fall():
    print("\n[fall] check-in; double-tap = fine; no answer = emergency")
    mark = last_id(snap())
    cmd("f"); time.sleep(4)
    s = snap()
    check("asks 'are you okay?'", any("okay" in x.lower() for x in kin_lines(s, mark)), str(kin_lines(s, mark)))
    check("fall alert raised", any(a["kind"] == "fall" for a in s["alerts"]))
    cmd("t"); time.sleep(4)
    s = snap()
    check("double-tap = I'm fine", any(a["kind"] == "fall_ok" for a in s["alerts"]))
    check("no emergency after 'fine'", not any(a["kind"] == "fall_emergency" for a in s["alerts"]))
    time.sleep(3)
    cmd("f"); time.sleep(20)
    s = snap()
    check("no answer -> emergency alert", any(a["kind"] == "fall_emergency" for a in s["alerts"]),
          str([a["kind"] for a in s["alerts"]]))


def s_wander():
    print("\n[wander] band leaves -> alert; back -> recovers")
    cmd("away"); time.sleep(16)
    s = snap()
    check("wander alert", any(a["kind"] == "wander" for a in s["alerts"]), str([a["kind"] for a in s["alerts"]]))
    cmd("home"); time.sleep(3)


def s_people_items():
    print("\n[people + items + small talk]")
    cmd("1 Hi Dad, it's Sarah!"); time.sleep(1)
    cmd("1 I'm moving to Oakland next week for my new job."); time.sleep(1)
    cmd("w I'm putting my glasses on the nightstand."); time.sleep(1)
    cmd("3 Hi, what can I get for you today?"); time.sleep(1)
    cmd("3 That'll be four fifty. Have a nice day!")
    time.sleep(10)
    s = snap()
    sarah = next((p for p in s["people"] if p["name"].lower() == "sarah"), None)
    check("Sarah saved as daughter", sarah and any(w in (sarah["relationship"] or "").lower() for w in ("daughter", "child")),
          str([(p["name"], p["relationship"]) for p in s["people"]]))
    check("Sarah's news saved", sarah and any("oakland" in f["text"].lower() for f in sarah["facts"]))
    check("glasses location saved", any("glasses" in i["item"] and "nightstand" in i["location"] for i in s["items"]),
          str([(i["item"], i["location"]) for i in s["items"]]))
    check("cashier not saved as a person", len(s["people"]) <= 2, str([p["name"] for p in s["people"]]))
    mark = last_id(s)
    cmd("w Hey Kin, who was that?"); wait_quiet(7)
    said = " ".join(kin_lines(snap(), mark)).lower()
    check("'who was that' names Sarah", "sarah" in said, said[:160])
    mark = last_id(snap())
    cmd("w Hey Kin, where are my glasses?"); wait_quiet(7)
    said = " ".join(kin_lines(snap(), mark)).lower()
    check("'where are my glasses' answered", "nightstand" in said, said[:160])
    mark = last_id(snap())
    cmd("w Hey Kin, what time is it there in Oakland?"); time.sleep(4); cmd("w Thanks!"); wait_quiet(6)
    said = kin_lines(snap(), mark)
    check("thanks gets a reply and ends", any(w in " ".join(said).lower() for w in ("welcome", "any time", "anytime", "glad")),
          str(said))


def s_summary():
    print("\n[summary + dashboard]")
    time.sleep(2)
    t = api("/api/summary").get("text", "")
    check("summary mentions Sarah", "sarah" in t.lower(), t[:200])
    check("summary mentions the scam or fall", any(w in t.lower() for w in ("scam", "fall", "money")), t[:200])
    print("  summary:", t)


SCENARIOS = {"people": s_people_items, "todo": s_todo, "purchase": s_purchase, "scam": s_scam, "money": s_money_question,
             "fall": s_fall, "wander": s_wander, "summary": s_summary}


def main():
    pick = [a for a in sys.argv[1:] if a in SCENARIOS] or list(SCENARIOS)
    import socket
    with socket.socket() as so:
        if so.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"Port {PORT} is busy: an old test copy is still running. Stop it first "
                     f"(lsof -ti tcp:{PORT} | xargs kill).")
    log = open(TMP / "kin.log", "w")
    proc = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "kin.app", "--sim", "--mute", "--no-console"],
                            cwd=ROOT, env=ENV, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if snap().get("status", {}).get("band") == "sim":
                    break
            except Exception:
                pass
            time.sleep(1)
        print(f"Kin test copy up on :{PORT} (logs: {TMP / 'kin.log'})")
        for name in pick:
            try:
                SCENARIOS[name]()
            except Exception as e:
                check(f"{name} crashed", False, repr(e))
    finally:
        if "--keep" not in sys.argv:
            proc.terminate()
            try:
                proc.wait(10)
            except Exception:
                proc.kill()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    for n, _, d in failed:
        print(f"  FAIL {n}: {d}")


if __name__ == "__main__":
    main()
