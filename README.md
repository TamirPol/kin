# Kin

**A wristband that remembers the people you love, for you.** Kin is a memory companion for people
with early memory loss, built on the Vexo band. The wearer never touches a screen.

> *"Who was that?"* (double-tap) → *"That was Sarah, your daughter. She's moving to Oakland next week."*

Built at VexoHacks, Nov 14 2026, Y Combinator SF. Theme: *Build beyond the screen*.
[Devpost write-up](docs/DEVPOST.md) · [Pitch & demo run-sheet](docs/PITCH.md) · [Video shot list](docs/VIDEO.md) · Video: *(link)*

## What it does

- **Remembers what matters, forgets the rest.** Every chunk of conversation is scored 0–3. Small talk,
  cashiers and the TV score 0 and never reach memory. Names, family news, plans, health instructions
  and where you put things become people, facts, to-dos and items.
- **Answers out loud on a double-tap.** "Who was that?", "Where are my keys?", "What do I need to do
  today?" It hedges instead of guessing a name.
- **Interrupts scam calls.** "Grandpa, I'm in jail, buy gift cards, don't tell Mom" → a calm spoken
  warning, a family alert, and a 30-minute purchase lock.
- **Checks in after a fall.** Band free-fall → "Are you okay? Double-tap if you're fine." No answer in
  15 s → emergency alert for the family.
- **Sees where things are.** A camera + Gemini 4 logs items like keys, glasses and pills, with a photo.
- **Spends money safely.** Voice purchases through Stripe (test mode), only at approved stores, under the
  family's limits, never gift cards/crypto/wires. The rules are plain Python, so the LLM can't override them.
- **Keeps the family in the loop.** A live dashboard with the transcript (small talk greyed out), person
  cards, to-dos, items, alerts and every purchase attempt. Family can add people, tick off to-dos and
  delete any fact.

## How it works

```
Vexo band ── mic (Opus over BLE) ──► Pipecat pipeline on the laptop
          ── double-tap ──► ask / "I'm fine"       BandAudioSource
          ── free-fall ───► fall check                  ▼
                                                 Deepgram STT (nova-3, diarized)
                                                        ▼
                                                    KinRouter
            LISTEN ◄────────────────────────────────────┴──────────────────────► ASK (after double-tap)
  brain.digest (OpenAI): importance 0-3                      OpenAI LLM + tools: who_is, find_item,
    → people / facts / to-dos / items                          get_todos, remember, purchase
  safety.check_scam on every sentence                        → ElevenLabs TTS → laptop speaker / earpiece
            │                                                               │
            ▼                                                               ▼
       memory.py (SQLite) ◄── vision.py: camera → Gemini 4 → items + photo
            │                 safety.py: guardrails → Stripe PaymentIntent (test mode)
            ▼
       dashboard.py (FastAPI + WebSocket, localhost:8700) → family
```

| Sponsor | What it does in Kin | File |
|---|---|---|
| **Vexo** band | Microphone, double-tap (ask / "I'm fine"), free-fall (fall check), auto-reconnect; loudness at the wrist tells the wearer from others | `kin/app.py` |
| **Pipecat** | The whole voice pipeline; the custom `KinRouter` sends sentences to memory or to the LLM | `kin/voice.py` |
| **Deepgram** | Streaming STT (`nova-3-general`) with speaker diarization | `kin/voice.py` |
| **OpenAI** | Importance filter (structured JSON), the ask-mode agent with memory tools, scam second opinion | `kin/brain.py`, `kin/voice.py`, `kin/safety.py` |
| **ElevenLabs** | Kin's calm voice for answers, scam warnings and fall check-ins | `kin/voice.py` |
| **Gemini 4** | `gemini-4-hydrogen` vision: frame → items + friendly locations (JSON schema) | `kin/vision.py` |
| **Stripe** | Guard-railed purchases as test-mode PaymentIntents | `kin/safety.py` |
| (ours) | SQLite memory shared by every part; live family dashboard | `kin/memory.py`, `kin/dashboard.py`, `kin/static/` |

**What's verified:** the full story runs on the simulated band with no keys (`--demo`), and
`tests/test_safety.py` (28 pass) and `tests/test_vision.py` (16 pass) are green. Live-hardware status
for each feature is tracked in [docs/DEVPOST.md](docs/DEVPOST.md#verified-on-real-hardware). Stripe runs in
test mode only, and "I've told your family" is a dashboard alert, not an SMS (yet).

## Run it

```bash
# one time
git clone https://github.com/TamirPol/kin.git && cd kin
git clone https://github.com/VexoAI-Org/vexo-open-kit.git
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "pipecat-ai[deepgram,openai,elevenlabs,silero]" bleak av \
    python-dotenv fastapi "uvicorn[standard]" stripe google-genai sounddevice numpy websockets opencv-python
cp .env.example .env        # fill in your keys and KIN_BAND (the number on your band's bag)
```

```bash
.venv/bin/python -m kin.app --demo        # scripted story on a pretend band (no hardware, no keys needed)
.venv/bin/python -m kin.app --demo --stay # same, then keep running (dashboard stays up)
.venv/bin/python -m kin.app --sim         # pretend band, you type the conversation
.venv/bin/python -m kin.app               # the real band: double-tap it first so it can be found
.venv/bin/python -m kin.app --webcam 0    # + vision from the laptop camera (--camera-url URL for a stream)
```

Dashboard: http://localhost:8700. Set `KIN_DB=demo.db` to start with a fresh memory.

Terminal keys: `t` double-tap · `f` fall · `a <question>` ask · `1 <text>` someone speaks ·
`w <text>` wearer speaks · `s` show memory · `q` quit.

Every key is optional: without Deepgram you type the conversation, without OpenAI Kin answers
from memory with simple rules (voice purchases need OpenAI), without ElevenLabs it uses the Mac's voice,
without Stripe purchases are simulated, and without Gemini vision is off.

Tests: `.venv/bin/python -m pytest -q tests/test_safety.py` · `.venv/bin/python -m pytest -q tests/test_vision.py` ·
`.venv/bin/python tests/eval_brain.py` (brain eval on 12 test conversations).

## Privacy

The band's solid blue light shows when the microphone is on. Audio is streamed to Deepgram for
transcription (model-improvement opt-out on) and never saved. Small talk and strangers' chatter are
scored 0: they appear in the recent transcript but never become memories, and strangers or likely
scammers are never saved as people. Everything lives in a local SQLite file. Family members can delete
any memory from the dashboard. Planned: automatic 24-hour transcript pruning (`memory.prune_transcript`
exists but isn't scheduled yet) and a "pause listening" gesture.

## Team docs

- [docs/HACKATHON.md](docs/HACKATHON.md): schedule, rules, submission checklist, prizes, free credits
- [docs/PLAN.md](docs/PLAN.md): checkpoints, demo script, test conversations, glasses
- [docs/BAND.md](docs/BAND.md): what the Vexo band can do, gotchas, architecture, tuning knobs
- [docs/DEVPOST.md](docs/DEVPOST.md) · [docs/PITCH.md](docs/PITCH.md) · [docs/VIDEO.md](docs/VIDEO.md): submission materials
