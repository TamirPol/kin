# Pitch, live demo and judge Q&A

## 90-second spoken pitch (~220 words)

> **[Hold up the band.]**
>
> Nearly seven million Americans live with Alzheimer's, and millions more with early memory loss. It doesn't start
> with forgetting how to cook. It starts with a grandchild walking in and you can't find their name. You
> ask your daughter the same question three times. And a stranger calls saying "Grandpa, it's me, I'm in
> jail, send gift cards," and you're the easiest target in the family.
>
> This is **Kin**. It's a memory companion on the Vexo band, and the person wearing it never touches a screen.
>
> Kin listens all day, but it only **remembers what matters**: names, family news, where you put your
> keys, what you promised to do. Small talk, the cashier and the TV get scored zero and forgotten.
>
> When you're lost, you **double-tap your wrist** and ask. "Who was that?" "That was Sarah, your
> daughter. She's moving to Oakland next week."
>
> It also **protects** you. It warns you during a scam call and locks your spending. It checks on you
> after a fall. It can see where you left your glasses, and it can reorder your pills, but only inside
> limits your family sets.
>
> And your family sees all of it live, on this dashboard.
>
> Under the hood: a Pipecat voice pipeline with Deepgram, OpenAI and ElevenLabs, Gemini 4 for vision,
> and Stripe for guarded purchases. Let me show you.

*(Timing: ~85 s at a calm pace. If you're cut to 60 s, drop the "Under the hood" line and the vision/pills sentence.)*

---

## 2-minute live demo run-sheet

**Roles.** **Wearer** = Tamir, band on the wrist. **Sarah** = a friend or volunteer (or ask a judge to
read the card). **Scam voice** = the same helper reading the scam line from a card, or a phone on speaker
playing a pre-recorded clip. If you're truly alone: type the other person's lines in the terminal with
`1 …` / `2 …` (real Deepgram still transcribes your own voice).

### Before judges arrive (T–5 min)

1. Close the vexo-open-kit dashboard tab (**one Bluetooth client per band**).
2. Start fresh so old memories don't leak into the demo:
   ```bash
   KIN_DB=demo.db .venv/bin/python -m kin.app
   ```
   Double-tap the band first so it can be found. Wait for "Connected to Vexo-HACK-57."
3. Open http://localhost:8700 full-screen on a second display (or the laptop, angled to the judges).
   Header should say **band: connected** and **mode: listen**.
4. Laptop volume up (the band has no speaker), or the earpiece paired. Do a test "Who was that?"
   **in a different DB** so it doesn't pollute `demo.db`.
5. Optional vision: add `--webcam 0` (or `1` for an iPhone via Continuity Camera) and point it at the
   table. Keep your keys or glasses **out of frame** until the vision beat.
6. Print the cue cards below.

### The run

| Time | Who / action | What's said | Dashboard should show |
|---|---|---|---|
| 0:00 | Wearer, pointing at the band | "The blue light means it's listening. Watch the dashboard." | Transcript empty, mode **listen** |
| 0:10 | **Sarah** walks up | "Hi Dad, it's Sarah! I'm moving to Oakland next week for my new job." | Lines appear live as `speaker N` |
| 0:20 | Wearer | "Oh hi sweetheart. I'm putting my keys in the kitchen drawer. And I'll call the dentist tomorrow." | Lines appear as `wearer` (or `Grandpa Joe`) |
| 0:30 | Sarah (small talk) | "Nice weather today, huh?" | Line appears |
| 0:36 | **Pause ~6 s** (chunk ends). Point at the screen. | Wearer: "Kin just decided what's worth keeping." | **Sarah** person card (daughter) + Oakland fact; to-do **Call the dentist · tomorrow**; item **keys → kitchen drawer**; the weather line **greyed out** |
| 0:45 | **Double-tap** | Kin: "Yes?" · Wearer: "Who was that?" | Mode → **ask**, note "Question: Who was that?" |
| 0:50 | Kin answers | "That was Sarah, your daughter. She's moving to Oakland next week." | Kin's line in the transcript, mode back to **listen** |
| 1:00 | **Double-tap** | "Where are my keys?" → "In the kitchen drawer." | |
| 1:08 | *(Stripe, if OpenAI key works)* **Double-tap** | "Can you reorder my blood pressure pills from Walgreens? They're about thirteen dollars." → "Done. I ordered your … for $13.00." (Say a price: the agent fills in the amount, so don't let it guess.) | **Purchases**: green **allowed**, Stripe `pi_…` id (or `sim_…` without a key) |
| 1:20 | **Scam voice** (phone on speaker / helper) | "Grandpa, it's your grandson. I'm in jail and I need bail. Buy gift cards and don't tell Mom." | Kin interrupts: "This sounds like a scam… It's okay to hang up." **Alert: scam**, "Purchases locked for 30 minutes." |
| 1:35 | *(Optional)* **Double-tap** | "Buy a gift card for $200." → "I've paused all purchases for a little while to keep you safe." | **Purchases**: red **blocked**, reason "scam lock active" |
| 1:45 | *(Optional, vision)* Put the glasses on the table in camera view, wait ~5 s, **double-tap** | "Where are my glasses?" → location from Gemini | **Items**: glasses with a **photo** |
| 1:50 | Wearer, wrap | "Small talk forgotten, family remembered, scammer stopped, and I never touched a screen." | Whole dashboard |

**Fall check (only if there's time, and only onto something soft):** let the band drop onto a cushion →
"Are you okay? Double-tap your band if you're fine." → double-tap → "Okay, glad you're alright."
Dashboard: alerts **fall** then **fall_ok**. If free-fall doesn't trigger, press `f` + Enter in the terminal.

**Order matters:** do the allowed purchase **before** the scam. After a scam the purchase lock lasts
30 minutes, and the dashboard can't clear it, so restart the app to reset.

### Cue cards

- **Sarah:** "Hi Dad, it's Sarah! I'm moving to Oakland next week for my new job." … "Nice weather today, huh?"
- **Scam:** "Grandpa, it's your grandson. I'm in jail and I need bail. Buy gift cards and don't tell Mom."

### Fallbacks

| Problem | Do this | Say this |
|---|---|---|
| Band won't connect / BLE flaky | Ctrl-C, double-tap the band, restart. Still failing → switch to the simulator below. | "Bluetooth with 100 bands in a room. Here's the same pipeline on a simulated band." |
| Deepgram labels the wearer wrong | Keep going. Answers still work from what was said. Or switch to typed lines: `w …` for wearer, `1 …` for Sarah. | |
| Double-tap missed | Press `t` + Enter in the terminal (same code path), then ask. Or `a Who was that?` | |
| **Total fallback** (band or Wi-Fi gone) | `KIN_DB=demo2.db .venv/bin/python -m kin.app --demo --stay` runs the whole scripted story on a pretend band (Sarah, keys, dentist, two questions, scam, fall) and keeps the dashboard up afterwards. | "This is the exact same code, with a pretend band feeding it." |
| No Wi-Fi at all | Blank the cloud keys so nothing tries the network: `DEEPGRAM_API_KEY= OPENAI_API_KEY= ELEVENLABS_API_KEY= GEMINI_API_KEY= STRIPE_SECRET_KEY= KIN_DB=offline.db .venv/bin/python -m kin.app --demo --stay` (rule-based memory, Mac voice, simulated Stripe). | "Every cloud piece has an offline fallback." |
| Laptop audio silent | Read Kin's answer off the dashboard transcript (Kin's lines show there). | |
| Everything is on fire | Play the backup video. | |

---

## Likely judge questions

**1. Privacy and consent: it's recording everyone around the wearer?**
The band's light is locked solid blue whenever the mic is on, so it's visible. Kin doesn't keep a
recording. Audio streams to Deepgram for transcription and is never saved; we turn Deepgram's model
improvement program off (`mip_opt_out`). Small talk and strangers score 0, which means they're visible in the
recent transcript but never become memories. Strangers and anyone who looks like a scammer are never
saved as people. Family can delete any fact from the dashboard. It's all a local SQLite file on the
family's laptop, no Kin cloud. *Honest gap:* the code has a 24-hour transcript-pruning function but it
isn't scheduled yet, and a consent flow for bystanders (a "pause" gesture, a visible notice) is next.

**2. How accurate is who-is-who? What if it says the wrong name?**
Two layers. Deepgram diarization separates voices, and Kin labels the loudest-at-the-wrist voice as
the wearer. A name only gets attached when someone is clearly introduced ("Hi Dad, it's Sarah"). The
brain is told never to invent a name, and the answering agent is told to hedge ("I think that might be
Sarah") rather than guess, because a wrong name is worse than "I'm not sure." Limits: speaker labels
only last the session, and loudness calibration depends on the room. Voiceprints are the next step.

**3. Why a band, not a phone app?**
The people who need this most are the ones who can't reliably find, unlock and operate a phone. Taking
out a phone to ask "who is this?" in front of your grandson is the opposite of dignity. A band is
always on you, always listening, and the whole interface is one gesture: double-tap. It also gives us
things a pocketed phone doesn't, like free-fall detection on the body and a mic close to the wearer's voice.

**4. Business model?**
Caregivers pay. The wearer gets the band, and the adult children pay a monthly subscription for the
dashboard, alerts and spending guardrails, the way they already pay for medical alert pendants.
Caregivers already spend hours a week on check-in calls, and Americans over 60 lose billions a year to fraud,
so one blocked gift-card scam pays for years of Kin. Later: home-care agencies and memory-care
facilities, priced per resident.

**5. How is this different from CrossSense, MemPal or Bee?**
Bee (and the "AI pendant" category) records your whole day for productivity summaries. It's built for
people with intact memory, and it keeps everything. Kin is the opposite: an aggressive importance filter
built for memory loss, with one-gesture spoken recall. MemPal and CrossSense target the same population,
but they lean on screens, smart glasses or a phone app. Kin needs no screen for the wearer. It's also the
only one of these that **acts**: real-time scam interruption with a purchase lock, fall check-ins, and an
economic agent with family-set limits. *(Check these comparisons before you say them. Don't
overclaim about competitors you haven't used.)*

**6. What's real and what's mocked?**
Real code end to end: band BLE audio, the Pipecat pipeline, Deepgram, the OpenAI importance filter and
tools, ElevenLabs, Gemini vision and Stripe PaymentIntents. *(Say only the ones the
[Devpost hardware table](DEVPOST.md#verified-on-real-hardware) marks ✅.)*
Honest limits: Stripe is in **test mode** with a test card. "I've told your family" means a dashboard alert,
not an SMS yet. Voice purchases need the OpenAI agent (no rule-based path), the item list and approved
merchants are hard-coded for the demo, and speaker names last one session. The `--demo` mode is a
scripted conversation on a simulated band, used only as a fallback.
