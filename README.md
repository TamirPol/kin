# Kin

**A wristband that remembers the people you love, for you.**

Kin is a memory companion for people with early memory loss, built on the **Vexo band**. It listens all
day, keeps only what matters (people, plans, where things are), and answers out loud when you double-tap
or say *"Hey Kin."* It interrupts scam calls, checks on you after a fall, and buzzes your family's phone when
something's wrong. The wearer never touches a screen. The family gets a calm live page.

> *"Who was that?"* → *"That was Sarah, your daughter. She's moving to Oakland next week."*

Built solo at **VexoHacks**, Nov 14 2026, Y Combinator SF ("Build beyond the screen").
**Video:** *(link)* · [Devpost write-up](docs/DEVPOST.md) · [Pitch & live demo](docs/PITCH.md) · [Recording plan](docs/RECORDING.md)

| Family page | Setup | Scam alert on the family's phone |
|---|---|---|
| ![Family page](docs/img/family.png) | ![Setup page](docs/img/setup.png) | ![Phone alert](docs/img/phone-alert.png) |
| ![The band](docs/img/band.png) | ![Hearing check](docs/img/test.png) | ![Today so far](docs/img/summary.png) |

## 30-second overview

- **Problem:** about 7M Americans live with Alzheimer's, cared for by 11M+ unpaid family members
  *(Alzheimer's Association 2024)*, and over-60s reported ~$4.9B in fraud losses in 2024 *(FBI IC3)*.
- **Product:** a band (no screen for the wearer) + a laptop home base + a family page and phone alerts.
- **AI:** six cooperating agents: a Pipecat voice agent with 7 tools, an importance-scoring memory brain, a
  scam detector, Gemini 4 vision, on-device voiceprints and a daily-summary writer.
- **Proof:** runs on the real band. End-to-end suite 32/32, brain eval 12/12, scam eval 14/14 with 0 false alarms.
- **Business:** caregivers pay a subscription. Memory clinics and insurers are the channel.

## Quickstart

```bash
bash scripts/kin.sh                       # real band: double-tap it, then open http://localhost:8700
.venv/bin/python -m kin.app --demo        # no band, no keys: the whole story on a pretend band
```

First time only:

```bash
git clone https://github.com/TamirPol/kin.git && cd kin
git clone https://github.com/VexoAI-Org/vexo-open-kit.git
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "pipecat-ai[deepgram,openai,elevenlabs,silero]" bleak av \
    python-dotenv fastapi "uvicorn[standard]" google-genai sounddevice numpy websockets \
    opencv-python sherpa-onnx watchfiles pytest
cp .env.example .env                      # then add keys without showing them:
bash scripts/set_key.sh DEEPGRAM_API_KEY  # same for OPENAI_API_KEY, ELEVENLABS_API_KEY, GEMINI_API_KEY
```

Then open **http://localhost:8700/setup** for the wearer's name, a 10-second voice recording and emergency
contacts (each gets a phone-alert link for the free **ntfy** app).

| Page | What it's for |
|---|---|
| http://localhost:8700 | Family page: status, *Today so far*, people, to-dos, items, alerts |
| http://localhost:8700/setup | Wearer, voice enrollment, emergency contacts, test alert |
| http://localhost:8700/test | Hearing check: band/mic/mode lights, live mic meter, checklist |

<details>
<summary>More ways to run, terminal keys, fallbacks</summary>

```bash
bash scripts/kin.sh --sim                   # pretend band (auto-reloads on code changes)
.venv/bin/python -m kin.app --demo --stay   # scripted story, then keep running
.venv/bin/python -m kin.app --sim           # pretend band, type the conversation
.venv/bin/python -m kin.app --webcam 0      # + vision (--camera-url URL for a stream)
bash scripts/actors.sh sarah|leo|scam|doctor|neighbor|cashier   # laptop speakers play the other people
bash scripts/clean_slate.sh                 # fresh memory before a demo (backup kept; voiceprints kept)
```

Terminal keys (`python -m kin.app`): `t` double-tap · `f` fall · `r` remind now · `away` / `home` band
leaves/returns · `a <question>` ask · `1 <text>` someone speaks · `w <text>` wearer speaks · `s` show memory · `q` quit.

Every key is optional. Without Deepgram you type the conversation, and without OpenAI you get rule-based
memory and answers. Without ElevenLabs Kin uses OpenAI TTS or the Mac voice, and without Gemini vision is off. `KIN_VOICE=openai` saves ElevenLabs characters while testing.
</details>

## What it does

**For the wearer, with no screen**
- **Remembers what matters.** Each conversation chunk is scored 0–3. Small talk, cashiers and the TV are
  forgotten. People, news, plans, health and item locations are kept.
- **Knows voices.** On-device voiceprints recognize people across days. Who's speaking is a vote between
  voice, loudness at the wrist and context.
- **Answers out loud:** double-tap or "Hey Kin," with conversation mode for follow-ups. It hedges instead of guessing.
- **Gentle reminders** for due to-dos when the room is quiet. Say "I did it" and it's marked done.
- **Talk slower / faster** on request, saved per voice.

**Safety net**
- **Scam interruption** from the caller's words *and* the wearer's side of a phone call. A calm spoken
  warning ("please don't send anything until you've checked with Sarah") and a family alert. Kin never buys
  anything or moves money.
- **Fall check:** free-fall → "Are you okay? Say I'm fine, or double-tap your band." He has 10 s after it asks
  (taps from the impact itself are ignored). "No," "I'm not fine," "help" or "I fell" alert the family at once,
  and phones only buzz if he's not okay or doesn't answer.
- **Wander alert** (weak band signal or a lost link) ·
  **confusion alert** (sounds lost → reassurance + family alert).
- **Phone push alerts** to each emergency contact through ntfy, with deliberately generic text.
- **Vision** (built, not in the live demo): camera → Gemini 4 → "your glasses are on the nightstand," with a photo.

**For the family:** a live page with a plain-language status, an LLM-written *Today so far*, and Today
cards for people, to-dos, items and alerts. The conversation is behind a toggle. Family can
add people, tick off to-dos, acknowledge alerts and delete any fact.

## Architecture

```
Vexo band ─ mic (Opus/BLE) · double-tap · free-fall · signal strength
   ▼ vexo-open-kit (Bluetooth contract, Opus decoder)
Pipecat pipeline:  BandAudioSource → Deepgram STT (nova-3, diarized) → KinRouter
   speaker = vote(voiceprint · loudness at the wrist · context)
   LISTEN ─► memory + scam/money watch on every sentence ─► brain.digest (OpenAI, importance 0-3) ─► SQLite
   ASK (double-tap / "Hey Kin") ─► OpenAI agent + 7 tools ─► ElevenLabs TTS ─► earbuds / speaker
vision.py   camera → Gemini 4 → items + photo ─► memory
safety.py   scam heuristics + LLM second opinion
summary.py  "Today so far" (OpenAI)          notify.py  ntfy push → each emergency contact
dashboard.py  FastAPI + WebSocket → family page, /setup, /test
```

| Sponsor | Role in Kin | Code |
|---|---|---|
| **Vexo** | The band: mic, double-tap, free-fall, signal strength (wander), auto-reconnect | `kin/app.py` |
| **Pipecat** | The voice pipeline. The custom `KinRouter` handles listen/ask, wake phrase and conversation mode | `kin/voice.py` |
| **Deepgram** | Streaming STT with diarization and word timings (per-speaker loudness and voice clips) | `kin/voice.py`, `kin/app.py` |
| **OpenAI** | Memory brain, 7-tool voice agent, scam second opinion, *Today so far* | `kin/brain.py`, `kin/voice.py`, `kin/safety.py`, `kin/summary.py` |
| **ElevenLabs** | Kin's calm voice (Bella), with speed control | `kin/voice.py` |
| **Gemini 4** | `gemini-4-hydrogen` vision → items and friendly locations | `kin/vision.py` |
| (ours) | Voiceprints (sherpa-onnx TitaNet), SQLite memory, ntfy alerts, settings, family pages | `kin/voiceprint.py`, `kin/memory.py`, `kin/notify.py`, `kin/settings.py`, `kin/dashboard.py`, `kin/static/` |

## Privacy

- The band's light is solid blue whenever the mic is on.
- Kin never stores audio. Deepgram transcribes the stream (model-improvement opt-out), and voiceprints are
  numeric embeddings in `voiceprints/`, not recordings.
- Small talk and strangers score 0 and never become memories. Strangers and likely scammers are never saved as people.
- Memory is a local SQLite file, and settings live in `kin_settings.json`, which is never committed.
- Phone alerts pass through ntfy's public server, so each contact gets a long random topic and the messages
  are generic ("Possible scam call"): no transcripts, names, amounts or places.
- Family can delete any fact from the family page.
- *Not yet:* automatic 24-hour transcript pruning (`memory.prune_transcript` exists but isn't scheduled) and a
  "pause listening" gesture.

## Tests

```bash
.venv/bin/python -m pytest -q tests/test_safety.py tests/test_vision.py tests/test_voiceprint.py   # unit
.venv/bin/python tests/e2e_scenarios.py    # end to end: real Kin on a pretend band, real Deepgram + OpenAI
.venv/bin/python tests/eval_brain.py       # what's worth remembering, 12 conversations
.venv/bin/python tests/eval_scam.py        # scam detector (add --no-llm for heuristics only)
.venv/bin/python tests/eval_answers.py     # prints Kin's answers on a seeded day, for review
```

| Suite | Result |
|---|---|
| Unit: safety / vision / voiceprint | rerun after the purchase removal / 50 / 14 passed |
| End to end | 32/32 |
| Brain eval | 12/12 |
| Scam eval (heuristics only) | 14/14 scams caught, 0/12 false alarms |

Each eval runs on a temporary database and never touches `kin.db`, your settings or your voiceprints.

## Docs

[DEVPOST.md](docs/DEVPOST.md) (submission and judging criteria) · [PITCH.md](docs/PITCH.md) (pitch, live run-sheet, Q&A) ·
[RECORDING.md](docs/RECORDING.md) (ship checklist and video) · [BAND.md](docs/BAND.md) (the Vexo band) ·
[HACKATHON.md](docs/HACKATHON.md) (event, rules, prizes) · [PLAN.md](docs/PLAN.md) (build plan, test conversations)
