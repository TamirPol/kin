# Devpost submission: copy-paste fields

> Before pasting: check the **Evidence** table at the bottom. Market figures are marked *(source)* or
> *(estimate)*. Say them that way.

---

## Project name

**Kin**

## Tagline (≤ 60 chars)

**A wristband that remembers the people you love, for you.** (57)

Alternates: *Your memory, on your wrist. Double-tap to ask.* (46) · *A memory companion for early memory loss.* (42)

---

## Inspiration

Early memory loss rarely starts with forgetting how to do things. It starts with the small things that hurt.
A grandchild walks in and you can't find their name. You ask your daughter the same question three times.
You can't find your keys again. Then a stranger calls saying "Grandpa, it's me, I'm in jail, buy gift cards,"
and you're the easiest target in the family.

Today's tools are a phone, a notebook, and a worried relative calling every day. A phone means remembering
to pick it up, unlock it, open an app and type, which is exactly what gets hard. We wanted something you
never operate. It listens all day, keeps only what matters, answers when you tap your wrist, and tells your
family when something's wrong. "Build beyond the screen" fit exactly: the wearer never looks at a screen.

## What it does

Kin runs on a **Vexo band** and a laptop as the home base. The band has no speaker, so Kin talks through
the laptop or Bluetooth earbuds.

**For the wearer (no screen):**
- **Remembers what matters.** Everything the band hears is transcribed with speaker labels and scored
  **0–3** per conversation chunk. Greetings, weather, a cashier and the TV score 0 and never become memories.
  People, family news, plans, health instructions and where things were put become **people, facts,
  to-dos and item locations**. Plans, health and money are always importance 3.
- **Knows who's talking.** On-device **voiceprints** (TitaNet-small through sherpa-onnx, embeddings only,
  never audio) recognize voices across days. Kin learns the wearer's voice automatically and names other
  voices when they're introduced ("Hi Dad, it's Sarah"). An optional 10-second enrollment on the setup page
  makes it more reliable.
- **Answers out loud.** Double-tap the band, or say **"Hey Kin, …"**. *"Who was that?"* → *"That was Sarah,
  your daughter. She's moving to Oakland next week."* **Conversation mode** keeps listening for follow-ups
  ("and her son?") for ~9 s after each answer and ends on "thanks." It never guesses a name.
- **Gentle reminders.** Kin brings up a due to-do when the room is quiet ("Just a gentle reminder: you
  planned to call the dentist"), only once each, even across restarts. "I did it" marks it done.
- **Adjusts to you.** "Talk slower" changes the speaking speed, saved per voice.

**Safety net:**
- **Scam interruption, both sides of the call.** A scam detector checks every sentence (heuristics plus
  an LLM second opinion), and a **money-talk detector also listens to the wearer's side**. On a phone call
  the band mostly hears the wearer ("you need two thousand dollars for bail?"). Kin speaks a calm warning
  ("Please don't send anything until you've checked with Sarah"), alerts the family and **pauses purchases
  for 30 minutes**. Scammers are never saved as people, and their requests never become to-dos.
- **Fall check.** Band free-fall → *"Are you okay? Double-tap your band if you're fine."* No answer in 15 s
  → an emergency alert.
- **Wander alert.** The band's Bluetooth signal gets weak for 10 s, or the link drops for 30 s → alert. Kin
  keeps reconnecting past the band's 2-minute window.
- **Confusion alert.** If the wearer sounds lost ("where am I?"), Kin reassures them with who they are and
  something familiar from today, and quietly alerts the family.
- **Phone push alerts** through ntfy to each emergency contact (each gets a private random topic).
  Messages are deliberately generic: no transcripts, names, amounts or places go through ntfy.
- **Guarded purchases (Stripe).** *"Reorder my blood pressure pills from Walgreens"* → a Stripe test-mode
  PaymentIntent, only for approved merchants, under the family's per-purchase limit and daily cap, never
  gift cards, crypto or wires, and never during a scam lock. The rules are in Python, below the LLM.
- **Vision (Gemini 4).** A camera feeds frames to Gemini 4. Personal items (keys, glasses, pill bottle…) are
  logged with plain-language locations and a photo, so *"Where are my glasses?"* works even if you never said.

**For the family (the only screen):**
- **Family page** (localhost:8700): a plain-language status hero ("Joe is fine · listening"), a
  **"Today so far"** summary written by an LLM from what Kin kept (never small talk, and a safety event is
  reported exactly as it happened), and Today cards for people, to-dos, items and alerts. The full
  conversation sits behind a toggle. Family can add a person, tick off a to-do, acknowledge an alert or delete any fact.
- **Setup page** (/setup): wearer's name, a voice recording with a read-aloud script, and emergency contacts
  with a "send test alert" button.
- **Hearing check** (/test): band, mic and mode lights, a live mic meter and a self-ticking checklist.

## How we built it

```
Vexo band ─ mic (Opus/BLE) · double-tap · free-fall · RSSI
   ▼ vexo-open-kit (Bluetooth contract, Opus decoder)
Pipecat pipeline:  BandAudioSource → Deepgram STT (nova-3, diarized, word timings) → KinRouter
   KinRouter: who's speaking = vote(voiceprint, loudness at the wrist, context)
     LISTEN → memory.add_line → money_watch + safety.check_scam (every sentence)
            → chunk (6 s pause / 30 s) → brain.digest (OpenAI structured JSON, importance 0-3) → SQLite
     ASK (double-tap / "Hey Kin") → OpenAI LLM + 8 tools → ElevenLabs TTS → laptop / earbuds
                                   (conversation mode: follow-ups for 9 s)
   vision.py: camera → change detection → Gemini 4 → items + photo → memory
   safety.py: guardrails → Stripe PaymentIntent (test mode)
   summary.py: "Today so far" (OpenAI) · notify.py: ntfy push per emergency contact
   dashboard.py: FastAPI + WebSocket → family page, /setup, /test
```

About 4,500 lines of Python in `kin/` plus a vanilla JS/CSS front end. One SQLite file is the contract between
the parts: every module writes through `memory.py`, which fires change events that the dashboard and
phone alerts subscribe to.

| Tech | Real role in the code |
|---|---|
| **Vexo band** | The only thing the wearer touches. Opus mic over BLE (decoded with vexo-open-kit, following its Bluetooth contract), `double-tap` (ask / "I'm fine"), `free-fall` (fall check), link RSSI (wander alert), auto-reconnect, and a tap threshold tuned on the real band (`KIN_TAP_G`). |
| **Pipecat** | The backbone pipeline. Our custom `KinRouter` frame processor sends each finished sentence to memory or to the LLM, handles the wake phrase and conversation mode, and keeps the raw conversation out of the LLM context. Tools use `FunctionSchema`, and speaking speed changes live via `TTSUpdateSettingsFrame`. |
| **Deepgram** | Streaming STT, `nova-3-general` with diarization, smart format, interim results and model-improvement opt-out. Word timings let Kin measure each speaker's loudness and cut each speaker's audio for voiceprints. |
| **OpenAI** | (1) The importance brain (strict JSON schema: people, facts, to-dos, items, speaker names). (2) The voice agent with 8 tools. (3) The scam second opinion. (4) The "Today so far" writer. |
| **ElevenLabs** | Kin's warm, calm voice (Bella) for answers, reminders, scam warnings and fall check-ins, with adjustable speed. `KIN_VOICE=openai` saves characters while testing. |
| **Gemini 4** | `gemini-4-hydrogen` vision with a JSON response schema: frame → `{item, location, confidence}` in older-adult-friendly words ("on the arm of the blue sofa"). Only called when the scene changes and settles. Item names are normalized so voice and vision agree ("car keys" = "keys"). |
| **Stripe** | A test-mode `PaymentIntent` with item, merchant and agent metadata, only after every deterministic guardrail passes. Every attempt, allowed or blocked, is logged and shown to the family. |
| **ntfy** | Free, open-source push notifications to each emergency contact's phone. |

**Graceful fallbacks:** no Deepgram key gives typed transcripts. No OpenAI key gives rule-based memory and
answers. No ElevenLabs key uses OpenAI TTS or the Mac voice, no Stripe key simulates charges, and no Gemini
key turns vision off. `python -m kin.app --demo` runs the whole story with no band and no keys.

## Challenges we ran into

- **Who's talking, from a wrist.** Diarization gives "speaker 0/1," not "the wearer," and the labels reset
  every session. A fixed loudness threshold failed in the loud venue. Now each sentence's speaker is a
  **vote** between a voiceprint match, *relative* loudness (the wearer is consistently loudest at the wrist,
  measured per word with Deepgram timings) and context (same voice as before, or talking to Kin).
- **Remembering less.** Deciding what to forget is the hard part. Twelve test conversations (cashier, TV,
  a name mentioned without an intro, a grandson-in-jail scam…) and `tests/eval_brain.py` got the brain to
  12/12.
- **Phone scams where the band hears only one side.** The caller's voice is in the phone, not near the
  band. So we added money-talk detection on the wearer's own words.
- **Real hardware.** Missed taps (the threshold went from 1.4 g to 1.0 g, plus debouncing), Opus decoder
  drift after reconnects, Bluetooth earbud pops (a high-latency buffer and a silent lead-in), and one
  Bluetooth client per band.
- **An agent that can spend money.** Every limit is deterministic Python *below* the LLM, and the purchase
  tool's description forbids "sending money to a person."

## Accomplishments that we're proud of

- A full product, not a demo script: onboarding, daily use, safety net and a family view, all on a wearable with no screen.
- **Tested like a product:** an end-to-end scenario suite that drives a real Kin (pretend band, real
  Deepgram and OpenAI) and checks memory plus the dashboard API: **32/32**. Brain eval **12/12**. Scam eval:
  **14/14 scams caught, 0/12 false alarms** with heuristics alone. Unit tests: safety 50, vision 50,
  voiceprint 14, all passing.
- A scam warning that interrupts *during* the call, on either side of it.
- It never crashes for a missing key, so it demos anywhere.

## What we learned

- For memory loss, **"I'm not sure"** beats a confident wrong name.
- The importance filter is the product. Transcription is a commodity, and deciding what's worth keeping isn't.
- Guardrails for an economic agent belong in code. The model doesn't get to enforce them.
- On a wearable the interaction budget is one gesture and one short sentence back. Everything else is
  the family's screen.

## What's next for Kin

- **Meta glasses: camera + earpiece.** The glasses camera feeds vision (Meta Wearables Device Access Toolkit)
  so Kin sees what you see, and Kin's voice plays privately in your ear.
- **Caregiver app.** The family page as a phone app with real-time approval of over-limit purchases and
  family-curated memories ("Remind Dad that Leo starts at Berkeley in August").
- **Face recognition for enrolled family** (a vision hook exists, opt-in only), and voiceprints shared across a family's devices.
- **Clinical pilot** with a memory clinic: measure fewer repeated questions, fewer caregiver check-in
  calls and scams avoided.
- **Retention controls:** automatic 24-hour transcript pruning and a "pause listening" gesture.

## Built with

`python` `pipecat` `deepgram` `openai` `elevenlabs` `gemini` `google-genai` `stripe` `vexo` `bluetooth-le`
`bleak` `sherpa-onnx` `onnx` `fastapi` `websockets` `sqlite` `ntfy` `opencv` `javascript` `html` `css`

## Links

- GitHub: https://github.com/TamirPol/kin
- Video: *(paste link)*

---

## How Kin meets each judging criterion

### Approach & Idea (viability, market, investors, feasibility, creativity)
- **Who pays: caregivers.** The wearer gets the band, and the adult children pay a subscription for the
  family page, phone alerts and spending guardrails, the way families already pay for medical-alert pendants.
  Suggested price: **~$29/month** *(estimate)*.
- **Market.** About **7 million** Americans 65+ live with Alzheimer's, and **11+ million** unpaid family
  caregivers give about **18 billion hours** of care a year *(source: Alzheimer's Association, 2024 Facts &
  Figures)*. Americans over 60 reported **~$4.9 billion** in fraud losses in 2024 *(source: FBI IC3 Elder
  Fraud Report 2024)*. One blocked gift-card scam pays for years of Kin.
- **Go-to-market (B2B2C).** Memory clinics and neurologists prescribe it at MCI diagnosis. Long-term-care
  insurers and Medicare Advantage plans cover it as fall and fraud risk reduction. Home-care agencies and
  memory-care facilities pay per resident. *(Strategy, not yet validated.)*
- **Feasible now.** It runs on an inexpensive band plus a laptop or home hub, using hosted APIs. Cost per
  wearer per day is low but not yet measured *(estimate to do)*. Voiceprints run on-device.
- **Creative.** Forgetting on purpose (importance 0–3), a wearer who never touches a screen, and a scam
  detector that listens to the wearer's half of a phone call.

### Product: Technical (live demo, prototyping, technical depth)
- **Real hardware:** the Vexo band over BLE using the kit's Bluetooth contract (Opus audio, gestures, RSSI),
  with reconnects, decoder resets and the tap threshold tuned on the device.
- **Streaming real-time stack:** Deepgram streaming STT with diarization and word timings, a Pipecat pipeline,
  streaming TTS, sub-second routing between listen and ask modes.
- **On-device ML:** TitaNet speaker embeddings in ONNX through sherpa-onnx (~8 ms per utterance on an M-series laptop).
- **Tested:** e2e 32/32, brain eval 12/12, scam eval 14/14 with 0 false alarms, 114 unit tests, plus
  `tests/eval_answers.py` for answer quality.

### Presentation
A 90-second story (Sarah visits, a double-tap, a scam call, the family's phone buzzes) with a live demo on the
real band and a fallback `--demo` mode. See [PITCH.md](PITCH.md).

### Product: Design
- **Wearer:** zero UI. One gesture or "Hey Kin," one short calm sentence back, a speed they can change by
  asking, gentle reminders only when the room is quiet, and never the same reminder twice.
- **Family:** the page leads with a plain-language status and "Today so far," not a log. The conversation
  is behind a toggle, it shows a calm "Connecting…" instead of red alarms while restarting, and it works in
  light and dark.
- **Onboarding:** /setup asks for the name, records a voice with a read-aloud script, and adds contacts with
  a test-alert button. /test checks the band and mic before you rely on it.
- **Privacy by design:** generic push messages, embeddings instead of audio, a local SQLite file, and family
  can delete any fact.

### X Factor
The moment a scam call is interrupted mid-sentence, the purchase lock engages, and the daughter's phone
buzzes across the room, without the wearer ever touching anything.

### AI Relevance & Depth (meaningful use of AI agents)
Six cooperating AI components, each with a narrow job and code-level guardrails:
1. **Voice agent:** Pipecat + OpenAI with **8 tools** (`who_is`, `find_item`, `get_todos`, `remember`,
   `complete_todo`, `set_speech_speed`, `alert_family`, `purchase`), conversation mode and a wake phrase.
2. **Memory brain:** an importance scorer and extractor with a strict JSON schema, eval 12/12.
3. **Scam detector:** heuristics plus an LLM second opinion (which can't clear an unknown caller asking
   for money under pressure), plus a money-talk watcher on the wearer's side.
4. **Vision agent:** Gemini 4 structured item and location extraction with change detection.
5. **Voice identity:** on-device voiceprints plus a three-signal speaker vote.
6. **Family summarizer:** "Today so far," instructed to report safety events exactly and never invent.

The economic agent can act (Stripe), but only through deterministic guardrails it can't override.

---

## Sponsor prize blurbs

### Best Voice Use Case on Pipecat (Deepgram)
For someone with early memory loss, voice isn't a convenience. It's the only interface left. Kin is a
two-mode Pipecat voice agent. It **listens** all day (Deepgram nova-3 diarization and word timings feed a
memory brain and a speaker vote with voiceprints), and on a double-tap or "Hey Kin" it **answers** (an
OpenAI agent with 8 tools, then ElevenLabs), with conversation mode for follow-ups. A custom Pipecat
`FrameProcessor` routes every sentence to memory or to the LLM and keeps raw conversation out of the LLM
context. Speaking speed changes live mid-pipeline when the wearer asks to slow down. No screen anywhere.

### Best ElevenLabs Project
Kin's voice is the whole product from the wearer's side, and it speaks at stressful moments: a scam call in
progress, a possible fall, a face they can't place. We chose a warm voice (Bella), kept every reply to one or
two short sentences, and let the wearer say "talk slower." The voice that tells you your daughter's name is
the same one that tells you to hang up on the scammer, and that trust is the point.

### Best Use of Gemini 4
Gemini 4 (`gemini-4-hydrogen`) is Kin's eyes for the most common memory-loss frustration: *where did I put
it?* Frames go to Gemini with a structured JSON schema and a prompt written for older adults, and come back as
items with plain-language locations. Kin calls Gemini only when the scene changes and settles, compares
landmarks so a rephrased location isn't logged twice, and normalizes names so the vision "car keys" and a
spoken "keys" match. Every sighting is saved with a photo the family can see.

### Stripe: Best Economic Agent
Older adults with memory loss are among the most targeted people in the economy, so an agent that spends
their money has to be safer than they are. Kin orders everyday things by voice and pays with a Stripe
PaymentIntent, but only after **deterministic guardrails the LLM can't override**: approved merchants only,
a family-set per-purchase limit and daily cap, never gift cards, crypto or wires, and an automatic
**30-minute purchase lock after any scam or money-talk alert**. Every attempt, allowed or blocked with a
reason, shows up on the family page. It's an economic agent built to say no.

---

## Evidence

| Claim | Evidence |
|---|---|
| Unit tests | `pytest tests/test_safety.py` 50 passed (1 live-Stripe skip) · `test_vision.py` 50 passed · `test_voiceprint.py` 14 passed (run Nov 14) |
| Scam detector | `tests/eval_scam.py --no-llm`: 14/14 scams caught (13 high), 0/12 false alarms (run Nov 14) |
| End to end | `tests/e2e_scenarios.py`: 32/32 (team run, real Deepgram + OpenAI, pretend band) |
| Brain | `tests/eval_brain.py`: 12/12 (team run) |
| Answers | `tests/eval_answers.py` prints answers for human review |
| Real band | Commits "Real-band fixes", tap threshold, decoder reset, wander. **Confirm live at the venue before claiming each one.** |
| Stripe | Test mode only. Without `sk_test_…` charges are simulated (`sim_…` ids). |
| Not built yet | Transcript auto-prune (function exists, not scheduled), clearing the scam lock from the family page, face recognition in the live loop |
