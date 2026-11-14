# Devpost submission: copy-paste fields

> Before pasting: check the **"Verified on real hardware?"** table at the bottom and change each
> ⚠️ to ✅ only after you've seen it work on the band in the venue. Don't claim what you haven't seen.

---

## Project name

**Kin**

## Tagline (≤ 60 chars)

**A wristband that remembers the people you love, for you.** (57 chars)

Alternates:
- *Your memory, on your wrist. Double-tap to ask.* (46)
- *A memory companion for early memory loss, on a band.* (52)

---

## Inspiration

Early memory loss rarely starts with forgetting how to do things. It starts with the small stuff that hurts:
a grandchild comes over and you can't find their name, you've asked your daughter the same question three
times, you can't find your keys again. Then a stranger on the phone says "Grandpa, it's me, I'm in jail"
and you're the easiest target in the family.

The tools for this are a phone, a notebook, and a worried relative calling every day. A phone means
remembering to pick it up, unlock it, open an app and type, which is exactly what gets hard. We wanted
something you never have to operate: it listens all day, keeps what matters, and answers when you tap
your wrist. Vexo's theme, "Build beyond the screen," fit exactly. The person using Kin never looks at a screen.
Only the family's dashboard has one.

## What it does

Kin runs on a **Vexo band** worn on the wrist and a laptop (the band has no speaker, so Kin talks
through the laptop or a Bluetooth earpiece).

- **Listens and remembers what matters.** Everything the band hears is transcribed with speaker labels.
  Every chunk of conversation (a 6-second pause, or 30 s of talk) is scored **0–3** by an importance
  filter. Greetings, weather, a cashier's "that's four fifty," and the TV score 0 and never reach memory.
  Names, family news, where you put things, plans and health instructions are saved as **people, facts,
  to-dos and item locations**.
- **Answers out loud when you double-tap.** Double-tap → "Yes?" → *"Who was that?"* → *"That was Sarah,
  your daughter. She's moving to Oakland next week."* Also *"Where are my keys?"*, *"What do I need to
  do today?"*, *"Remember that…"* The answering agent uses tools over memory (`who_is`, `find_item`,
  `get_todos`, `remember`, `purchase`) and is told never to guess a name or a fact.
- **Warns about scam calls as they happen.** Every sentence is checked for scam patterns (gift cards,
  bail, wire/crypto, card or Social Security numbers, impersonating a grandchild/IRS/police, "don't tell
  Mom"). On high risk, Kin speaks a calm warning, raises a family alert, and **locks purchases for 30
  minutes**. A scammer is never saved as a "person," and their requests never become to-dos.
- **Checks in after a fall.** The band's built-in free-fall event → *"Are you okay? Double-tap your band
  if you're fine."* A double-tap clears it. No answer in 15 s raises an emergency alert on the family dashboard.
- **Knows where things are (vision).** A camera (laptop webcam, an iPhone via Continuity Camera, or a
  stream URL) feeds frames to **Gemini 4**, which lists personal items (keys, glasses, pill bottle,
  remote…) and where they are in plain words. New or moved items are logged with a photo, so *"Where
  are my glasses?"* works even if you never said where you put them.
- **Buys things, but only inside the family's limits.** *"Can you reorder my blood pressure pills?"* →
  a **Stripe** test-mode PaymentIntent, only if the merchant is on the family's approved list
  (Walgreens, CVS, Safeway, Whole Foods, Amazon Pharmacy), it's under the per-purchase limit ($50 by
  default), it's under the daily cap (3× the limit), it isn't a gift card/crypto/wire, and there's no
  scam lock. These rules are plain Python. The LLM can't loosen them.
- **Keeps the family in the loop.** A live dashboard (localhost:8700, WebSocket updates) shows the
  transcript with small talk greyed out, person cards with facts, to-dos, item locations with camera
  snapshots, alerts (scam, fall, spending) and every purchase attempt, allowed or blocked. Family can add
  a person, tick off a to-do, or delete any fact.

## How we built it

```
Vexo band mic ──BLE (Opus 16 kHz)──► vexo-open-kit decoder ──► Pipecat pipeline
   BandAudioSource → Deepgram STT (nova-3, diarize) → KinRouter
      LISTEN: transcript → chunk → brain.digest (OpenAI, structured JSON) → SQLite memory
              + safety.check_scam on every new sentence
      ASK (double-tap): OpenAI LLM + tools over memory → ElevenLabs TTS → laptop speaker / earpiece
   band events: double-tap = ask / "I'm fine"   free-fall = fall check
   vision: camera → change detection → Gemini 4 → items (+ snapshot) → memory
   safety: scam heuristics (+ LLM confirm) · purchase guardrails → Stripe PaymentIntent (test mode)
   dashboard: FastAPI + WebSocket ← memory change events
```

Python 3.12, about 2,400 lines across `kin/app.py`, `voice.py`, `brain.py`, `memory.py`, `safety.py`,
`vision.py` and `dashboard.py`, plus a vanilla JS dashboard. One SQLite file is the contract between the
parts: every module writes through `memory.py`, which fires change events that the dashboard broadcasts live.

**What each sponsor technology actually does in Kin:**

| Tech | Real role in the code |
|---|---|
| **Vexo band** | The only thing the wearer touches. Microphone (Opus over BLE, decoded with the vexo-open-kit), `double-tap` gesture (ask / "I'm fine"), `free-fall` event (fall check), `auto_reconnect` for dropped links. Kin also tells the wearer from other speakers by loudness at the wrist (the wearer's voice is much louder). |
| **Pipecat** | The backbone: one pipeline of `BandAudioSource → DeepgramSTTService → KinRouter → LLM context → OpenAILLMService → ElevenLabsTTSService → Speaker`. Our custom `KinRouter` processor sends each finished sentence to memory (listen mode) or to the LLM (ask mode), and keeps raw transcripts from ever reaching the LLM. Function calling goes through Pipecat's `FunctionSchema` and `LLMContext`. |
| **Deepgram** | Streaming STT, `nova-3-general` with **diarization**, smart formatting and interim results. Speaker labels are what make "Who was that?" possible. Kin maps "speaker N" to a name when someone introduces themselves. |
| **OpenAI** | Three jobs: (1) the **importance filter**, structured JSON output that scores each chunk 0–3 and extracts people/facts/to-dos/items, with strict rules (never invent, never save strangers or scammers); (2) the **ask-mode agent** with tools over memory; (3) a second opinion on scam risk, which can downgrade a heuristic flag but never clear an unknown caller asking for money under pressure. |
| **ElevenLabs** | Kin's voice: a warm, calm, slow voice matters a lot for someone who's confused or scared. `ElevenLabsTTSService` streams audio for answers, scam warnings and the fall check. |
| **Gemini 4** | Vision. `gemini-4-hydrogen` (fastest Gemini 4 model) with a JSON response schema turns a camera frame into `[{item, location, confidence}]` in older-person-friendly words ("on the arm of the blue sofa", never "left of frame"). Cheap pixel-diff change detection means Gemini is only called when the scene changes. |
| **Stripe** | The economic agent's hands: a `PaymentIntent` in **test mode** (`pm_card_visa`, confirmed) with item/merchant/agent metadata, only after every guardrail passes. Every attempt, allowed or blocked, is logged and shown to the family. |

**Graceful fallbacks:** every key is optional so the demo can't die. No Deepgram key means typed transcripts.
No OpenAI key means rule-based memory and answers. No ElevenLabs key uses the Mac's `say` voice. No Stripe
key gives simulated charges, and no Gemini key turns vision off. `python -m kin.app --demo` runs the whole
story with no band and no keys.

## Challenges we ran into

- **Who's talking, from a wrist.** Diarization gives "speaker 0/1/2," not "the wearer." The band is on
  the wearer's wrist, so we measure loudness per utterance and treat consistently loud speakers as the
  wearer (`WEARER_DB`). It has to be tuned for the room, and a noisy hackathon floor is the worst case.
- **Remembering less.** The hard part of a memory product is what to forget. A naive version filled up
  with "nice weather" and "that's four fifty." We wrote 12 test conversations (family intro, cashier,
  TV in the background, a grandson-in-jail scam, a name mentioned without an intro…) and an eval script
  (`tests/eval_brain.py`) and tuned the prompt until small talk was dropped and nothing was invented.
- **Scammers vs family.** "Grandpa, it's me" is both your grandson and the most common scam. We score
  unknown voices and known people differently. Family mentioning a pharmacy is fine, but money plus
  urgency plus secrecy still flags. Scammers never get saved as people.
- **An agent that can spend money.** We kept every limit in deterministic Python *below* the LLM, so a
  prompt injection or a confused model can't buy a gift card.
- **One Bluetooth client per band**, a fixed firmware, and no speaker on the band: all answers go out
  through the laptop or a paired earpiece.

## Accomplishments that we're proud of

- The whole loop is wired end to end: band audio → memory → double-tap → spoken answer → live dashboard
  (fully verified in the band simulator; see the hardware table below for what's confirmed on band 57).
- An importance filter that really does drop small talk, with an eval to prove it, plus safety tests (28)
  and vision tests (16) passing.
- A scam warning that interrupts *during* the call, and a purchase lock that follows from it automatically.
- Nothing about it requires the wearer to look at or operate a screen.
- It never crashes for a missing key, so it demos anywhere.

## What we learned

- For memory-loss care, **"I'm not sure"** beats a confident wrong name. We pushed the agent to hedge
  ("I think that might be Sarah") instead of guessing.
- The importance filter is the product. Transcription is a commodity, and deciding what's worth keeping isn't.
- Guardrails for an economic agent belong in code. The model doesn't get to enforce them.
- Wearables change the interaction budget: one gesture, one short spoken sentence back.

## What's next for Kin

- **Meta glasses: camera + earpiece.** Stream the glasses camera (Meta Wearables Device Access Toolkit)
  into the vision module so Kin sees what you see, and play Kin's voice privately in your ear.
- **Voiceprints.** Recognize Sarah by her voice the next time she visits, not just within one session.
  Today the speaker-to-name mapping only lasts the session.
- **Caregiver app.** The dashboard as a phone app with push notifications for fall and scam alerts,
  real-time approval of over-limit purchases, and family-curated memories ("Remind Dad that Leo starts
  at Berkeley in August").
- **Real notifications.** Today "I've told your family" means an alert on the dashboard; next is SMS
  or a call to the family contact.
- **Wander alerts and routines** from the band's step counter, activity and signal strength.
- **Consent and retention controls**: enforce the 24-hour transcript window automatically, and add a
  "don't record" gesture.

## Built with

`python` `pipecat` `deepgram` `openai` `elevenlabs` `gemini` `google-genai` `stripe` `vexo` `bluetooth-le`
`bleak` `fastapi` `websockets` `sqlite` `opencv` `javascript` `html` `css`

## Links

- GitHub: https://github.com/TamirPol/kin
- Video: *(paste link)*

---

## Sponsor prize blurbs

### Best Voice Use Case on Pipecat (Deepgram)

For someone with early memory loss, voice isn't a convenience. It's the only interface left. Kin is a
voice agent with two modes in one Pipecat pipeline: it **listens** all day (Deepgram nova-3 with
diarization feeding a memory brain) and, on a double-tap of the Vexo band, it **answers** (OpenAI with
tools over that memory, then ElevenLabs). A custom Pipecat `FrameProcessor` (`KinRouter`) routes each
finished sentence to memory or to the LLM, and keeps the raw conversation out of the LLM context.
Deepgram's speaker labels are what make *"Who was that?"* answerable at all. No screen anywhere.

### Best ElevenLabs Project

Kin's voice is the whole product from the wearer's side, and it often speaks at stressful moments: a
scam call in progress, a possible fall, a face they can't place. We used ElevenLabs for a warm, calm voice
that says short, simple sentences: *"This sounds like a scam. Please don't buy anything or give any
numbers. It's okay to hang up."* The same voice that tells you your daughter's name tells you to hang up
on the scammer, and that trust is the point.

### Best Use of Gemini 4

Kin uses Gemini 4 (`gemini-4-hydrogen`) as its eyes for the most common memory-loss frustration: *where did I
put it?* Camera frames go to Gemini with a structured JSON schema and a prompt tuned for older adults, and
the answer comes back as items and plain-language locations ("on the kitchen table next to the fruit
bowl"). Pixel-diff change detection means Gemini is only called when the scene changes, and "moved"
compares landmarks, so a rephrased location isn't logged twice. Every sighting is saved with a photo the
family can see, and *"Where are my glasses?"* works even if you never said where you put them.

### Stripe: Best Economic Agent

Older adults with memory loss are the most targeted people in the economy, so an agent that spends their
money has to be safer than they are. Kin can order everyday things by voice (*"reorder my blood pressure
pills"*), and it pays with a Stripe PaymentIntent, but only after **deterministic guardrails** the LLM can't
override: approved merchants only, a per-purchase limit and a daily cap set by the family, no gift
cards/crypto/wires ever, and an automatic **30-minute purchase lock after a detected scam call**. Every
attempt, allowed or blocked with a reason, shows up on the family dashboard. It's an economic agent built to
say no as well as yes.

### Overall

Kin turns a screenless wristband into a memory, a scam shield and a safety net for one of the
fastest-growing groups of people who need help. The wearer only has to double-tap. The families already
spending hours a week worrying are the ones who'd pay.

---

## Verified on real hardware?

Update this before submitting. ✅ = seen working at the venue. ⚠️ = works in code/tests or the `--demo`
simulation, not yet confirmed on the real band.

| Feature | Status | Evidence |
|---|---|---|
| Full story on the pretend band, no keys (`--demo`) | ✅ | Ran it: Sarah + keys + dentist stored, both answers right, scam warned, fall check cleared |
| Safety guardrails | ✅ | `tests/test_safety.py`: 28 passed (live Stripe test skipped without a key) |
| Vision pipeline | ✅ | `tests/test_vision.py`: 16 passed (mocked Gemini) |
| Band 57 audio → Deepgram transcript | ⚠️ | |
| Wearer vs other speaker (`WEARER_DB` tuned) | ⚠️ | |
| Double-tap → spoken answer on the band | ⚠️ | |
| Free-fall event → fall check on the band | ⚠️ | |
| ElevenLabs voice | ⚠️ | |
| OpenAI importance filter (eval score) | ⚠️ | `tests/eval_brain.py`, write the score here |
| Gemini 4 on a live camera | ⚠️ | |
| Stripe test-mode charge (`pi_…` id in the dashboard) | ⚠️ | |
