# The Vexo band and how Kin uses it

Our band: **57** (`Vexo-HACK-57`). Kit and full docs: https://github.com/VexoAI-Org/vexo-open-kit
(clone it inside this repo folder as `vexo-open-kit/`; `docs/api.md` is the reference).

## What it has

| Sense / do | Details | Kin uses it for |
|---|---|---|
| Microphone | Opus, 16 kHz mono, 50 packets/s; adjustable gain | Everything heard |
| Loudness meter | Up to 50 readings/s | Wearer vs others (we compute it from the audio instead) |
| Accelerometer + gyro | Up to ~833–1666 samples/s | (future: gestures) |
| Built-in gestures | `tap`, `double-tap`, `free-fall`, `tilt`, `orientation`, `motion-start/stop` | Double-tap = ask / "I'm fine"; free-fall = fall check |
| Activity | Steps, cadence, still/walk/run | (future: "you've been sitting a while") |
| Signal strength (RSSI) | Bluetooth only | (future: wander alert) |
| Battery, temperature | Temperature is the chip's, not skin | Dashboard status |
| Colour light | Patterns; **locked solid blue while the mic is on** | Nothing (it's always blue for us) |
| Storage | Small, shared, readable by anyone who connects | Nothing (never store anything private there) |

**It does not have:** a speaker, vibration, a camera, GPS, heart rate, or any on-band AI. Answers play
from the laptop (or Meta glasses as Bluetooth audio).

## Gotchas

- **Double-tap before every connect.** The light blinks blue; it can be found for 60 s.
- **One Bluetooth program at a time.** Close the kit's dashboard tab before running Kin.
- Everything resets on disconnect; Kin sets the mic and events again on every connect.
- Kin connects with `auto_reconnect=True`; a dropped link comes back for 2 minutes without a double-tap.
- macOS asks to allow Bluetooth for the terminal: say yes.
- The mic hears everyone near the band. The blue light shows it's on. Tell people nearby.
- A tap thumps in the audio: harmless.

## Architecture

```
band mic ──BLE (Opus)──► kit PcmDecoder ──► BandAudioSource (Pipecat)
                                              ▼
                                   DeepgramSTTService (diarize)
                                              ▼
                                       KinRouter (kin/voice.py)
                     LISTEN ─────────────────┴─────────────── ASK (after double-tap)
   memory.add_line → chunk (6 s pause / 30 s)        LLMUserAggregator → OpenAILLMService (tools:
   → brain.digest → importance 0-3 → memory          who_is, find_item, get_todos, remember, purchase)
   → safety.check_scam on every sentence             → ElevenLabsTTSService → Speaker (laptop/glasses)
                                                     → LLMAssistantAggregator
band events: double-tap → ask / "I'm fine"   free-fall → fall check
memory.py (SQLite) ◄── dashboard.py (FastAPI + WebSocket, localhost:8700) ── vision.py (Gemini)
```

Missing keys fall back so the app always runs: no Deepgram key → typed transcripts; no OpenAI key →
rule answers from memory; no ElevenLabs key → the Mac's voice; no Stripe key → simulated purchases;
no Gemini key → vision off.

## Tuning knobs (`kin/app.py`)

| Constant | Default | Meaning |
|---|---|---|
| `WEARER_DB` | -32 | dBFS above which an utterance counts as the wearer. Tune on the real band. |
| `CHUNK_PAUSE` | 6 s | Quiet that ends a conversation chunk (then the brain digests it) |
| `CHUNK_MAX` | 30 s | Digest at least this often while people keep talking |
| `FALL_WAIT` | 15 s | Time to double-tap "I'm fine" after a fall |
| `ask_pause` | 1.2 s | Pause after the question before Kin answers |
