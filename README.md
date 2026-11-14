# Kin

**A memory companion for people with early memory loss, built on the Vexo band.**

Kin listens quietly through a wristband, remembers the people, plans and places that matter,
and answers out loud when you double-tap: *"Who was that?"* → *"That's Sarah, your daughter.
She's moving to Oakland next week."* It protects you from scams, buys things only within
limits your family sets, checks on you after a fall, and keeps your family in the loop.

Built at VexoHacks (Nov 14, 2026).

## How it works

```
Vexo band mic ──BLE──► laptop ──► Pipecat pipeline
                                   Deepgram STT (speaker labels)
                                   └► Kin router
                                       LISTEN: transcript ► importance filter (0-3) ► memory (SQLite)
                                       ASK (double-tap): OpenAI + tools ► ElevenLabs voice ► speaker
band gestures: double-tap = ask / "I'm fine"   free-fall = "Are you okay?"
safety: scam detection on every sentence, Stripe purchases inside family guardrails
vision: camera frames ► Gemini ► "where things are"
family dashboard: live transcript, people, to-dos, items, alerts, purchases
```

| Part | File | Sponsor |
|---|---|---|
| Band connection, modes, fall check | `kin/app.py` | Vexo |
| Voice pipeline (STT → router → LLM tools → TTS) | `kin/voice.py` | Pipecat, Deepgram, OpenAI, ElevenLabs |
| What's worth remembering | `kin/brain.py` | OpenAI |
| Shared memory | `kin/memory.py` | |
| Scam detection + spending guard | `kin/safety.py` | Stripe |
| Where things are | `kin/vision.py` | Gemini, Marv Labs camera |
| Family dashboard | `kin/dashboard.py`, `kin/static/` | |

## Run it

```bash
# one time
git clone https://github.com/VexoAI-Org/vexo-open-kit.git
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "pipecat-ai[deepgram,openai,elevenlabs,silero]" bleak av \
    python-dotenv fastapi "uvicorn[standard]" stripe google-genai sounddevice numpy websockets opencv-python
cp .env.example .env        # fill in your keys and KIN_BAND (the number on your band's bag)
```

```bash
.venv/bin/python -m kin.app --demo        # scripted story on a pretend band (no hardware, no keys needed)
.venv/bin/python -m kin.app --sim         # pretend band, you type the conversation
.venv/bin/python -m kin.app               # the real band: double-tap it first so it can be found
.venv/bin/python -m kin.app --webcam 0    # + vision from the laptop camera
```

Dashboard: http://localhost:8700

Terminal keys: `t` double-tap · `f` fall · `a <question>` ask · `1 <text>` someone speaks ·
`w <text>` wearer speaks · `s` show memory · `q` quit.

Every key is optional: without Deepgram you type the conversation, without OpenAI Kin answers
from memory with simple rules, without ElevenLabs it uses the Mac's voice, without Stripe purchases
are simulated, without Gemini vision is off.

## Privacy

The band's solid blue light shows when the microphone is on. Small talk and strangers' chatter are
scored 0 and not kept; the raw transcript is kept for 24 hours only. Family members can delete
any memory from the dashboard.
