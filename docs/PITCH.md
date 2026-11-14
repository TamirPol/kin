# Pitch, live demo and judge Q&A

Judging criteria: **Approach & Idea · Product–Technical · Presentation · Product–Design · X Factor ·
AI Relevance & Depth.** Each pitch beat below is tagged with the criterion it answers.

## 90-second pitch (~230 words)

> **[Hold up the band.]** *(Presentation)*
>
> Seven million Americans live with Alzheimer's, and eleven million family members look after them for free.
> It doesn't start with forgetting how to cook. It starts with your grandson walking in and you can't find
> his name. And then a stranger calls: "Grandpa, I'm in jail, buy gift cards, don't tell Mom." *(Approach: the problem)*
>
> This is **Kin**: a memory companion on the Vexo band. The person wearing it never touches a screen. *(Design)*
>
> Kin listens all day but **only keeps what matters**: names, family news, where you put your keys, what you
> promised. Small talk and the TV score zero and are forgotten. It knows voices, so it knows *who* said what. *(AI depth)*
>
> When you're lost, you double-tap or say "Hey Kin." "Who was that?" "That was Sarah, your daughter.
> She's moving to Oakland next week."
>
> And it's a safety net. It interrupts a scam call mid-sentence, even when it can only hear your half of the
> call, and locks your spending. It checks on you after a fall. And it buzzes your daughter's phone. *(X factor)*
>
> Under the hood there are six cooperating AI agents on real hardware: a Pipecat voice agent with eight
> tools, a memory brain, a scam detector, Gemini 4 vision, on-device voiceprints and a daily-summary writer.
> End-to-end tests pass 32 of 32. *(Technical, AI depth)*
>
> Caregivers are the buyers. Memory clinics and insurers are the channel. *(Approach: business)*
>
> Let me show you.

*(~85 s at a calm pace. Cut to 60 s by dropping the "six agents" sentence and the business line, and save them for Q&A.)*

---

## 2-minute live demo run-sheet

**Solo setup.** Tamir wears the band. The laptop speakers play the other people with `scripts/actors.sh`,
and Kin talks through **earbuds** (or a second speaker) so the two don't overlap. Hold the band ~30 cm from
the laptop speakers. A phone subscribed to the ntfy topic sits face-up in front of the judges.

### T–10 minutes

```bash
bash scripts/kin.sh                 # leave running (auto-reloads, reconnects without a double-tap)
bash scripts/clean_slate.sh         # fresh memory (backup kept as kin.db.bak); keeps voiceprints
```
1. `.env`: `KIN_VOICE=elevenlabs`. Double-tap the band and wait for "Connected."
2. Open http://localhost:8700/test and check band, mic and mode are green and the mic meter moves when you talk.
3. Open http://localhost:8700 (the family page) full-screen, facing the judges. The status should read listening.
4. /setup: send a **test alert** to make sure the phone buzzes.
5. Optional vision: restart with `--webcam 0`, glasses **out of frame**.

### The run

| Time | Action | What's heard | Judges see | Criterion |
|---|---|---|---|---|
| 0:00 | Point at the band's blue light | "It's listening. Watch my daughter's screen." | Family page, status hero | Design |
| 0:05 | `bash scripts/actors.sh sarah` | "Hi Dad, it's Sarah! … moving to Oakland next week … I'll call you on Sunday." | Live lines | Technical |
| 0:20 | Wearer says | "I'm putting my keys in the kitchen drawer. I'll call the dentist tomorrow." | Lines labeled as the wearer | AI (speaker vote) |
| 0:28 | `bash scripts/actors.sh cashier` *(optional)* | "That'll be four fifty…" | Line appears | |
| 0:35 | Pause ~6 s, point at the screen | "Kin just decided what's worth keeping." | **Sarah** card + Oakland, to-do **Call the dentist**, **keys → kitchen drawer**, cashier forgotten, **Today so far** updates | AI depth |
| 0:45 | **Double-tap**, "Who was that?" | "That was Sarah, your daughter. She's moving to Oakland next week." | Status: talking with Kin | Technical |
| 0:52 | Follow-up, no tap: "When is she calling?" | "On Sunday." (conversation mode) | | AI depth |
| 0:58 | "Thanks." Then "**Hey Kin**, where are my keys?" | "In the kitchen drawer." | | Design |
| 1:05 | *(Stripe)* **Double-tap**, "Reorder my blood pressure pills from Walgreens." | "Done. I ordered…" | Purchases: green, `pi_…` (or `sim_…`) | Stripe |
| 1:15 | `bash scripts/actors.sh scam` | "Grandpa? It's your grandson… two thousand dollars for bail… gift cards… don't tell Mom." | Kin interrupts with a calm warning. **The phone buzzes.** Alert: scam, purchases paused. | **X factor** |
| 1:35 | **Double-tap**, "Buy a two hundred dollar gift card." | "I've paused all purchases for a little while to keep you safe." | Purchases: red, blocked | Stripe |
| 1:45 | Point at "Today so far" | Read one line aloud | Summary mentions Sarah and the scam call, calmly | Design |
| 1:50 | Wrap | "Small talk forgotten, family remembered, scammer stopped, and I never touched a screen." | Whole page | Presentation |

**Order matters:** purchase **before** the scam. The lock lasts 30 minutes and the family page can't clear it,
so to reset, run `clean_slate.sh` (it restarts Kin).

**If there's time:** drop the band onto a cushion. Kin says "Are you okay? Double-tap if you're fine," the
phone buzzes, you double-tap, and Kin says "Glad you're alright." Or say "Where am I? I don't know where I
am" to show the confusion reassurance and alert.

### Fallbacks

| Problem | Do this | Say this |
|---|---|---|
| Band won't connect | Double-tap it. `kin.sh` keeps retrying. After 30 s, switch to the simulator. | "Bluetooth with 100 bands in a room. Same code, simulated band." |
| Double-tap missed | Say "Hey Kin, …" instead. Or click the test buttons on /test. | |
| Wrong speaker label | Keep going. Answers come from what was said. | |
| **Band or Wi-Fi gone** | `KIN_DB=demo.db .venv/bin/python -m kin.app --demo --stay` runs the whole story (Sarah, keys, dentist, two questions, scam, fall) on a pretend band and keeps the family page up. | "This is the exact same pipeline, fed by a pretend band." |
| No internet at all | `DEEPGRAM_API_KEY= OPENAI_API_KEY= ELEVENLABS_API_KEY= GEMINI_API_KEY= STRIPE_SECRET_KEY= KIN_DB=offline.db .venv/bin/python -m kin.app --demo --stay` (rule-based memory, Mac voice, simulated Stripe, no push) | "Every cloud piece has an offline fallback." |
| Everything | Play the video. | |

---

## Likely judge questions

**1. Privacy and consent: it hears everyone near the wearer?**
The band's light is solid blue whenever the mic is on. Kin never stores audio: Deepgram transcribes the
stream with model-improvement opt-out, and voiceprints are numeric embeddings, not recordings. Small talk and
strangers score 0: they show in the recent conversation but never become memories, and strangers or likely
scammers are never saved as people. It's a local SQLite file. Phone alerts are deliberately generic ("Possible
scam call"), so no names, amounts or transcripts pass through the push service. Family can delete any fact.
*Honest gaps:* the 24-hour transcript prune isn't scheduled yet, and bystander consent (a "pause" gesture,
a visible notice) is next.

**2. How accurate is who-is-who?**
Each sentence's speaker is a vote between three signals: an on-device voiceprint match (it survives
restarts and days), relative loudness at the wrist (the wearer is consistently loudest), and context (same voice as
a moment ago, or talking to Kin). A name only gets attached when someone is clearly introduced, or enrolled on
/setup. The agent is told never to invent a name and to say it isn't sure instead. The vote is robust to one
noisy signal. The worst case is a new voice in a loud room, which gets "someone" rather than a wrong name.

**3. Why a band and not a phone?**
The people who need this most can't reliably find, unlock and operate a phone, and pulling one out to ask "who
is this?" in front of your grandson costs dignity. A band is always on you, the interface is one gesture, and it
gives us body signals a pocketed phone doesn't: free-fall, and distance from home through Bluetooth signal strength.

**4. Business model?**
Caregivers pay: a monthly subscription (~$29/month, *estimate*) for the family page, alerts and guardrails,
like a medical-alert pendant. The channel is B2B2C: memory clinics prescribe it at an MCI diagnosis, and long-term-care
insurers and Medicare Advantage plans cover it as fall and fraud risk reduction. Then memory-care facilities
pay per resident. Over-60s reported ~$4.9B in fraud losses in 2024 *(FBI IC3)*, so one blocked scam pays for years.

**5. How is it different from CrossSense, MemPal or Bee?**
Bee and the AI-pendant category record your day for productivity summaries. They're built for intact memory,
and they keep everything. Kin forgets on purpose and answers with one gesture. CrossSense and MemPal target
the same population but lean on smart glasses, a screen or a phone app. Kin needs no screen for the wearer,
and it **acts**: it interrupts scams on either side of a call, locks spending, checks in after falls and pushes alerts to family.
*(Check these comparisons before you say them. Don't overclaim about products you haven't used.)*

**6. What's real and what's mocked?**
Real: the Vexo band over BLE, Pipecat, Deepgram streaming, the OpenAI brain, agent and summarizer, ElevenLabs,
Gemini vision, on-device voiceprints, ntfy push and Stripe PaymentIntents. Mocked or limited: Stripe is
**test mode** with a test card. The merchant list and price table are hard-coded. The "home base" is a laptop.
`--demo` is a scripted run on a simulated band, used only as a fallback. Tests: e2e 32/32 drives a real Kin on a
pretend band with real Deepgram and OpenAI.
