"""Asks Kin realistic questions about a seeded day and prints every answer, for a human (or a reviewer) to judge.

    .venv/bin/python tests/eval_answers.py

Runs a private Kin copy (pretend band, free Mac voice muted, alerts off, temp memory).
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
PORT = 8731
TMP = Path(tempfile.mkdtemp(prefix="kin_ans_"))
ENV = dict(os.environ, KIN_VOICE="say", KIN_NTFY="off", KIN_PORT=str(PORT), KIN_DB=str(TMP / "kin.db"),
           KIN_VOICEPRINTS=str(TMP / "voices"), KIN_SETTINGS=str(TMP / "settings.json"),
           KIN_REMIND_AFTER="100000", PYTHONWARNINGS="ignore")

# a realistic morning, as Kin would have heard it
DAY = [
    "1 Hi Dad, it's Sarah!", "1 I'm moving to Oakland next week for my new job.",
    "1 I'll call you on Sunday evening, okay?", "w That's wonderful, sweetheart.",
    "w I'm putting my reading glasses on the kitchen table.",
    "2 Hello Joe, this is Doctor Patel's office.",
    "2 Please take your new blood pressure pill with food, twice a day, starting tomorrow.",
    "w I need to pick up the pills at Walgreens this afternoon.",
    "3 Hi Grandpa, it's Leo!", "3 I got into Berkeley! I start in the fall.",
    "w I'll put my wallet in the top drawer of the dresser.",
]
QUESTIONS = [
    "Who was here today?",
    "What's my daughter's name?",
    "Where is Sarah moving?",
    "When is Sarah calling me?",
    "Who is Leo?",
    "What did the doctor say?",
    "Where did I put my glasses?",
    "Where's my wallet?",
    "What do I need to do today?",
    "Did I take my pills yet?",
    "What day is it today?",
    "What time is it?",
    "Where are my car keys?",
    "Who is Michael?",
    "I feel a bit lonely today.",
    "I'm confused, where am I?",
    "What's my name?",
    "Can you remind me again who was here?",
    "Should I give my credit card number to the man on the phone?",
    "Tell me a joke.",
]


def api(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def main():
    log = open(TMP / "kin.log", "w")
    proc = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "kin.app", "--sim", "--mute", "--no-console"],
                            cwd=ROOT, env=ENV, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if api("/api/snapshot").get("status", {}).get("band") == "sim":
                    break
            except Exception:
                pass
            time.sleep(1)
        for line in DAY:
            api("/api/command", {"cmd": line}); time.sleep(1.2)
        time.sleep(10)
        s = api("/api/snapshot")
        print("MEMORY:", [(p["name"], p["relationship"]) for p in s["people"]], [t["text"] for t in s["todos"]],
              [(i["item"], i["location"]) for i in s["items"]], "\n")
        for q in QUESTIONS:
            mark = max([l["id"] for l in api("/api/snapshot")["transcript"]] or [0])
            api("/api/command", {"cmd": "t"}); time.sleep(2.5)        # a new conversation, like a real double-tap
            mark = max([l["id"] for l in api("/api/snapshot")["transcript"]] or [0])
            api("/api/command", {"cmd": "a " + q})
            t0 = time.time()
            ans = []
            while time.time() - t0 < 20:
                time.sleep(1)
                tr = api("/api/snapshot")["transcript"]
                ans = [l["text"] for l in tr if l["speaker"] == "kin" and l["id"] > mark and l["text"] != "Yes?"]
                if ans:
                    time.sleep(1.5)
                    tr = api("/api/snapshot")["transcript"]
                    ans = [l["text"] for l in tr if l["speaker"] == "kin" and l["id"] > mark]
                    break
            print(f"Q: {q}\nA: {' / '.join(ans) or '(no answer)'}  [{time.time() - t0:.1f}s]\n")
            time.sleep(10)                                   # let the conversation window close
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
