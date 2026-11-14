# Live demo: 2 minutes, one presenter, a loud room

This is the in-person version of the demo, for the judging tables (6:30 PM) and the finals (8 PM). The video
plan is in [RECORDING.md](RECORDING.md), and the long pitch and Q&A are in [PITCH.md](PITCH.md).
**Print section 1 and the two judge cards, or keep them on your phone.**

You play **Grandpa Joe** (Kin's default wearer name, and every actor line says "Dad", "Grandpa" or "Joe").
The laptop plays the other people, your phone plays Sarah's phone, and the judges watch the family page.

---

## 0. Four rules that matter more than the script

These come from how the code behaves (`kin/app.py`, `kin/voice.py`). Break one and the demo goes wrong.

1. **After you ask Kin something, stop talking until Kin answers.** In ask mode everything *you* say is added
   to the question. If you fill the wait with "so what's happening here is…", that becomes part of the
   question. Count "one, two, three" in your head instead. Kin usually answers in 2 to 4 s.
2. **End every conversation with "Thanks, Kin."** For 9 s after each answer Kin waits for a follow-up
   (conversation mode), and anything you say to the judges in that window becomes a new question.
   "Thanks, Kin" closes it (Kin replies "You're welcome"). A second double-tap closes it too.
3. **Your voice must be enrolled** (/setup, at the demo table). With your voiceprint saved, voices that aren't
   yours (the judges, the room, Kin's own voice coming back out of the speaker) are *ignored* in ask mode. Without
   it, a judge's comment can become your question.
4. **Bring your wrist to your mouth when Joe speaks, and to the laptop speaker when an actor plays.** Then pull it
   back to your chest while Kin answers. The band has a single mic and the room is at −5 to −25 dBFS. Distance is
   the only noise control you have. Nothing in the code stops the band hearing Kin (there's no echo gate), so
   keeping the band away from Kin's speaker matters.

---

## 1. The 2:00 run-sheet

**Stage layout**

```
          JUDGES
   [phone face-up]        ← ntfy, ringer ON (it becomes "Sarah's phone")
 ┌───────────────────┐
 │  family page      │    laptop turned ~40° toward the judges, browser zoom 150%
 │  (90% of screen)  │    tiny Terminal strip at the bottom, command already typed
 └───────────────────┘
   YOU stand at the laptop's right side, band on the LEFT wrist (tap it with your right hand)
```

**Before each run:** the family page shows a morning (doctor, Mike next door, glasses; see 3.4). The Terminal
has `bash scripts/actors.sh sarah` typed but not run.

| Time | You say | Your hands / band | Judges see | Criterion it lands |
|---|---|---|---|---|
| **0:00–0:10** | **HOOK:** "Your daughter walks into the room… and you can't find her name. Seven million Americans live with that. *(lift the wrist)* This band finds it for you." | Lift the left wrist to eye level and turn it so the **blue light** faces them. | The band, its blue light | **Presentation** |
| 0:10–0:18 | "I'm Joe, seventy-eight. Joe never touches a screen. This is his daughter's screen." | Open palm toward the laptop. | Family page: "Listening", **Today so far** already says the doctor called this morning | **Design** ("never touches a screen") |
| 0:18–0:30 | *(silent)* | Click the Terminal strip and press **Return** (`actors.sh sarah`). Hold the band **10–20 cm from the left speaker grille** while Sarah talks (~10 s). | Sarah's three lines appear **live** on the family page, under someone other than Joe | **Technical** (live BLE → Pipecat → Deepgram) |
| 0:30–0:37 | Wrist to your mouth: "Oakland! Wow. … I'm putting my keys in the kitchen drawer. And I'll call the dentist tomorrow." | Wrist ~10 cm from your mouth. Short sentences. | The lines appear labeled **Joe** | **AI depth** (who-said-what vote) |
| 0:37–0:44 | *(silent ~6 s; point at the screen)* | Wrist down. Point at the People and Items cards. | After ~6 s of quiet Kin digests the chunk. **Sarah · daughter · moving to Oakland**, to-do **Call the dentist**, **keys → kitchen drawer** | **AI depth** |
| 0:44 | "Kin decided what was worth keeping. Small talk and this room score zero, so they're forgotten." | | Cards landing. *(If they haven't appeared yet, carry on. They'll arrive during the next beat. Say "there it goes" when they do.)* | **AI depth** |
| 0:48–0:55 | **Double-tap.** Kin: "Yes?" You: **"Who was that?"** *(then silence: rule 1)* | Double-tap with two firm fingers. Wrist to mouth for the question, then down. | Status: "Talking with Kin". Kin: *"That was Sarah, your daughter. She's moving to Oakland next week."* | **Technical** |
| 0:55–1:00 | No tap: **"When is she calling?"** | Wrist up, then down. | Kin: *"On Sunday."* | **AI depth** (conversation mode, memory) |
| 1:00–1:03 | **"Thanks, Kin."** | | "You're welcome." Back to listening. | (rule 2) |
| 1:03–1:12 | "Under the hood, every sentence goes to a memory brain that scores it 0 to 3, and on-device voiceprints decide *who* said it. That's how it knew it was Sarah, not me." | | Point at the **Sarah** card and the **Joe** labels. | **AI depth** |
| *1:12–1:22* | *Optional, only if the clock says ≤ 1:12:* **Double-tap**, "Reorder my blood pressure pills from Walgreens." *(silence)* … "Thanks, Kin." | | *"Done. I ordered your blood pressure pills from Walgreens for $12.99."* A green row with a `pi_…` id appears under Purchases | **Technical** (Stripe agent, guardrails) |
| 1:22–1:40 | **The scam, wearer side:** pick up your phone, hold it to your ear, wrist near your mouth: "Hello? … Leo? You're in *jail*? … You need **two thousand dollars for bail**? … Gift cards? … Okay, I won't tell your mom." | Phone at your **right** ear, band (left wrist) near your mouth. Stop as soon as Kin cuts in. | Kin, mid-call: *"Hold on, that sounds like someone asking for money. Please don't send anything until you've checked with Sarah. I've let them know."* **Your phone buzzes in your hand. Turn the screen to the judges.** A red **scam** alert and "purchases paused" on the page | **X FACTOR** ("it only heard *my* half of the call") |
| 1:40–1:48 | "It only heard *my* side of the call. It interrupted, buzzed my daughter, and locked spending for 30 minutes, below the AI, in code." | Put the phone down, still face-up. | Alert card, purchase lock | **Approach** (a real danger, a real action) |
| 1:48–2:00 | **CLOSE:** "Small talk forgotten, family remembered, scammer stopped. Six AI agents on a real Vexo band, and Joe never touched a screen. That's Kin." | Lift the wrist one last time. | The whole page: Today so far mentions Sarah and the scam call, calmly | **Presentation**, **AI relevance** |

**Over time?** Drop the Stripe beat first, then the "When is she calling?" follow-up. **Under time?** Double-tap
and say "Buy a two hundred dollar gift card." Kin answers *"Let's wait about 30 minutes before ordering
anything…"* and the purchase row turns red. Or, as the last beat, double-tap and ask "Where are my keys?"

**Why the scam comes from your side of the call:** the money watch (`MONEY_SAY` in `kin/app.py`) is a plain
pattern match, not an LLM call. "Bail", "gift cards" or "two thousand dollars" trigger it from **any** speaker,
and your voice, 10 cm from the mic, is the clearest thing the band hears in a loud room. It's also the stronger
story: a real scam call happens on a phone, where the band only hears the grandparent.

---

## 2. Doing it alone: who plays whom

| Role | Recommended in a loud room | Why | Alternative |
|---|---|---|---|
| **Sarah** | `bash scripts/actors.sh sarah` through the MacBook speakers, band 10–20 cm from the speaker grille | The same voice every time (macOS "Samantha"). It's short, rehearsed, and its voiceprint is already saved (voiceprints survive `clean_slate.sh`), so Kin may recognize her straight away. | **Judge reads Card A**, if the room is moderate and a judge is leaning in |
| **The scammer** | **You, the wearer's side** of a fake phone call | It's deterministic: the pattern match fires on your clearest audio, needs no extra speaker voice and no diarization, and lands the best line ("it only heard my half"). | `bash scripts/actors.sh scam` (a male voice, "Fred") if the room is quiet enough for judges to hear the laptop. Or **a judge reads Card B**: "Want to try to scam Joe?" |
| **Sarah's phone** | Your phone, with the ntfy topic of the emergency contact **named "Sarah"** | Kin says "checked with Sarah", and the buzz happens in your hand, so you can turn it to the judges | Point at the red alert on the family page |
| **Kin's voice** | Mac output = **MacBook Pro Speakers**, volume 90–100%, **earbuds disconnected** | Judges must hear Kin | A small Bluetooth speaker in front of the judges, ≥1 m from the band, works best: actors stay on the laptop (`actors.sh` always plays on "MacBook Pro Speakers") and Kin's voice is farther from the mic |

**Asking a judge to take part.** Do it when there are at least 2 judges and you can hear each other without
shouting. Hand over the card *before* you start the clock, and say: "When I nod, read this toward my wrist,
from about a foot away, a little louder than normal, with a pause between lines."

> **CARD A: you are Sarah, Joe's daughter**
> 1. "Hi Dad, it's Sarah!"
> 2. "I'm moving to Oakland next week for my new job."
> 3. "I'll call you on Sunday."
>
> *(Read toward the wristband, one line at a time.)*

> **CARD B: you are the scammer** *(read it like a nervous grandson)*
> 1. "Grandpa? It's me. I'm in trouble."
> 2. "I got arrested. I need two thousand dollars for bail."
> 3. "Buy gift cards and read me the numbers. Don't tell Mom."
>
> *(Read toward the wristband. Kin may interrupt you, and that's the point.)*

**Fallback if a judge's voice doesn't register.** Watch the family page. If their first line hasn't appeared
within about 3 s, say "The room's winning. Let me get Sarah on speaker," and press Return on `actors.sh sarah`.
For Card B, just say your half of the call ("Two thousand dollars for bail?"), which triggers the warning by
itself. **If nobody volunteers:** "No problem, my laptop does the voices," and run the default plan.

**Why not let a judge play Sarah by default?** An unknown voice at an unknown distance and volume, in a −10 dBFS
room, is the least predictable input you could pick. A judge's voice is a great way to answer "is this
canned?", but keep it as an upgrade, not the plan.

---

## 3. Setup, starting 15 minutes before judging

### 3.1 Hardware and the Mac (T−15)

- [ ] **Power:** laptop on the charger, band charged (red light = charge), phone > 50%. Run `caffeinate -dimsu &` so the Mac never sleeps.
- [ ] **Audio:** disconnect the earbuds (Bluetooth menu → Disconnect). System Settings → Sound → Output → **MacBook Pro Speakers**, then run:
  ```bash
  osascript -e 'set volume output volume 95'
  ```
  ```bash
  say -a "MacBook Pro Speakers" "Testing, one two three"
  ```
- [ ] **Mac notifications off** (Control Center → Focus → Do Not Disturb). **Phone: Focus OFF, ringer ON, volume up**, ntfy notifications allowed with sound, auto-lock 5 min.
- [ ] **Bluetooth:** keep the laptop within 1–2 m of the band, with no body between them, and close any vexo-open-kit dashboard tab (one Bluetooth client only).
- [ ] **Network:** run `ping -c 5 api.deepgram.com`. If it's slow (> 300 ms) or loses packets, switch to your phone hotspot **now**, not mid-demo.
- [ ] **Video fallback downloaded** and open in QuickTime (paused at 0:00) in a background window. Don't rely on YouTube on venue Wi-Fi.

### 3.2 Start Kin (T−12)

In Terminal tab 1 (leave it running):

```bash
cd ~/kin && KIN_VOICE=elevenlabs KIN_REMIND_AFTER=7200 bash scripts/kin.sh
```

*(The variables on the command line override `.env`, because `load_dotenv` doesn't override.
`KIN_REMIND_AFTER=7200` stops a "gentle reminder" about the morning's to-dos from going off in the middle of a
demo. Leave it out if you'd like one to fire between judges.)*

Double-tap the band and wait for "Connected" in the log. Then in Terminal tab 2:

```bash
cd ~/kin && bash scripts/clean_slate.sh
```

Paste these helper commands into tab 2. They drive the **real** running Kin through `/api/command`, so they
work on the real band too:

```bash
k(){ curl -s -o /dev/null -X POST localhost:8700/api/command -H 'content-type: application/json' -d "{\"cmd\":\"$*\"}"; }
tap(){ k t; }            # a double-tap, when the band misses yours
ask(){ k "a $*"; }       # a typed question when Deepgram mishears: ask Who was that?
```

### 3.3 Setup page (T−10): http://localhost:8700/setup

- [ ] **Wearer:** `Grandpa Joe` (the default; it matches every actor line).
- [ ] **Your voice:** record the 10-second read-aloud **at the demo table, at your demo wrist position**. A
  voiceprint recorded in venue noise matches better in venue noise. This is rule 3, so don't skip it.
- [ ] **Emergency contact:** name **Sarah**, relationship daughter, with the ntfy topic subscribed in the ntfy app
  on **your** phone. Click **Send test alert**. The phone must buzz within ~5 s.
- [ ] http://localhost:8700/test: band, mic and mode all green. The mic meter should jump when you talk
  at the wrist, and not hit the top from room noise alone.

### 3.4 Pre-seed a "morning" (T−8), so Today so far isn't empty

Paste this into tab 2. It feeds a believable morning through the **same** running pipeline (brain, memory,
summary), as if the band had heard it:

```bash
k "2 Hello Joe, this is Doctor Patel's office."; sleep 0.5
k "2 Please take your new blood pressure pill with food, twice a day, starting tomorrow."; sleep 0.5
k "w Okay. With food, twice a day."; sleep 9
k "3 Hey Joe, it's Mike from next door. Could you water my plants on Saturday while I'm away?"; sleep 0.5
k "w Sure Mike, Saturday it is."; sleep 9
k "w I left my reading glasses on the nightstand."
```

Within ~30 s the page should show Dr. Patel's instruction, the "Water Mike's plants Saturday" to-do,
glasses → nightstand, and a *Today so far* paragraph. *(Not one of these lines mentions Sarah, keys or money,
so the live demo stays fresh.)* If a judge asks, say it plainly: "This morning was typed in through the same
pipeline. Everything from here on is live."

> Ask the main session to save this block as `scripts/seed_morning.sh`, plus `scripts/demo_reset.sh` =
> `clean_slate.sh` + wait 8 s + `seed_morning.sh`. See section 6.

### 3.5 On screen (T−5)

- Browser: **one window, one tab**, http://localhost:8700, **zoom 150%**, light theme (bright venue), bookmarks
  bar hidden. Size it to ~90% of the screen.
- Terminal tab 2 as a **3-line strip** under the browser, with `bash scripts/actors.sh sarah` typed and not run.
- Phone face-up in front of the judges, ntfy app open.
- **One dry run** at the table with the room as noisy as it'll get. Then reset (3.6).

### 3.6 Between judge groups (60 s)

The scam locks purchases for 30 minutes, and memory piles up. After **every** run:

```bash
bash scripts/clean_slate.sh
```

Wait ~8 s for the restart (the band reconnects by itself), paste the 3.4 block again, and type
`bash scripts/actors.sh sarah` again without running it. Use the waiting time to chat with the judges (section 5).

---

## 4. Failure plan: what you do, what you say

Rule of thumb: **never debug in front of judges for more than 15 seconds.** Say the line, take the fallback,
and keep the story going.

| Problem | Do | Say (word for word) |
|---|---|---|
| **Double-tap missed** (no "Yes?") | Tap again, firmer. Or say **"Hey Kin, who was that?"**. Or type `tap` in tab 2. | "Two taps, like knocking on a door." |
| **Deepgram mishears the question** (a wrong or "not sure" answer) | "Thanks, Kin." Ask again once, slower and closer. Still wrong? `ask Who was that?` | "Loud room, and Kin says 'not sure' rather than guess a name. That's on purpose for someone with dementia. Same brain, typed:" |
| **Kin is slow** (no answer after 6 s) | Stay silent until 6 s (rule 1). Then double-tap to end it, and `ask …`. | "Hackathon Wi-Fi. Usually it's about two seconds." |
| **The Sarah card is late** | Keep going: ask "Who was that?" anyway. Point at the card when it lands. | "There it goes. It waits for the conversation to end before it decides." |
| **A sentence gets the wrong speaker label** | Ignore it. Answers come from what was said. | *(nothing)* |
| **Phone doesn't buzz** | Point at the red alert on the family page. | "Same alert on Sarah's page. The push goes out through ntfy, and the venue network's slow." |
| **Band disconnects** (status "Looking for the band…") | Double-tap it near the laptop. `kin.sh` reconnects by itself (the band stays findable for 2 minutes). | "A hundred bands on one Bluetooth channel. While it reconnects, here's what it remembered this morning." *(point at the morning cards)* |
| **Band still gone after 20 s** | Ctrl-C tab 1 (**free port 8700 first**), then run `KIN_DB=demo.db KIN_NTFY_IN_SIM=1 .venv/bin/python -m kin.app --demo --stay` | "Same code, fed by a pretend band. It runs the whole story: Sarah, keys, the scam, a fall." |
| **Wi-Fi dead** | Switch to the phone hotspot (Wi-Fi menu). Then restart without wiping memory: `echo "# reload $(date +%s)" > kin/_reload.py` | "Thirty seconds. Everything but the band talks to the cloud." |
| **No network at all** | Ctrl-C tab 1, then `DEEPGRAM_API_KEY= OPENAI_API_KEY= ELEVENLABS_API_KEY= GEMINI_API_KEY= STRIPE_SECRET_KEY= KIN_DB=offline.db .venv/bin/python -m kin.app --demo --stay` | "Every cloud piece has an offline fallback: rule-based memory, the Mac's voice, simulated payments." |
| **Purchase blocked at the Stripe beat** (the last group's scam lock) | Skip it. You forgot to reset. | "It still remembers the scam from the last group, so spending's locked for 30 minutes. That's the feature." |
| **Kin's voice gets transcribed as a person** | Ignore it. Pull your wrist back during answers. | *(nothing)* |
| **Everything** | Cmd-Tab to QuickTime and press Space. | "Let me show you the recording from this afternoon, same band, then I'll take questions." |

---

## 5. Judge questions (15-second answers) and the hallway pitch

**1. "It hears everyone around the wearer. What about privacy?"**
"The blue light is on whenever the mic is. Kin never stores audio. Voiceprints are numbers, not recordings.
Small talk and strangers score zero and never become memories, and phone alerts are generic, with no names or
transcripts. Bystander consent, like a pause gesture, is the next thing we're building."

**2. "What's real and what's mocked?"**
"Real: the band over Bluetooth, Pipecat, Deepgram, the OpenAI brain and agent, ElevenLabs, voiceprints, push
alerts and Stripe payment intents. Mocked: Stripe is in test mode, the store list is hard-coded, the laptop is
the home base, and this morning's conversations were typed in. End-to-end tests pass 32 of 32 against real
Deepgram and OpenAI."

**3. "How does it decide what's worth remembering?"**
"Every chunk of conversation is scored 0 to 3: people, plans, health and where things are score high, and the
cashier and the TV score zero. Who said it is a vote between voiceprint, loudness at the wrist and context. I
have an eval of 12 conversations for exactly that, and it passes 12 of 12."

**4. "What if it's wrong? A wrong name could really hurt someone with dementia."**
"That's the design rule: it never invents a name. With low confidence it says 'I'm not sure,' and the money
rules (limits, no gift cards, the scam lock) live in code, below the LLM, so a confused model can't spend money."

**5. "Why a band and not a phone app?"**
"The people who need this most can't find or unlock a phone, and pulling one out to ask 'who is this?' in front
of your grandson costs dignity. A band is always on you, it's one gesture, and it gives us falls and wandering."

**6. "Who pays?"**
"The family: a subscription around $29 a month, like a medical-alert pendant (that's an estimate). Memory
clinics prescribe it at diagnosis, and insurers cover it as fall and fraud prevention. Over-60s lost about
$4.9 billion to fraud in 2024, so one blocked scam pays for years."

*(If they ask about Bee, MemPal or CrossSense: "They record everything for people with intact memory, or they
need a screen. Kin forgets on purpose and acts: it interrupts scams and alerts family." Don't claim more than that.)*

### 30-second hallway version

> "You know how dementia starts? Not with forgetting how to cook. Your daughter walks in and you can't find her
> name. Kin is a wristband that finds it for you. It listens all day, keeps only what matters, and when you
> double-tap and ask 'who was that?', it whispers 'That's Sarah, your daughter, she's moving to Oakland.' And if a
> scammer calls asking for gift cards, it interrupts the call, locks your spending and buzzes your daughter's
> phone. No screen for the wearer, six AI agents underneath, running on the real Vexo band. Want to see it
> catch a scam?"

---

## 6. Tooling the main session should add (in priority order)

1. **Echo gate (most important for a speaker demo):** drop band transcripts while `app.speaking` is true and for
   ~0.8 s after `done_speaking()`. Without earbuds, Kin's own sentences come back through the band, as a
   "someone" line in the transcript. In listen mode they also run through the scam and memory checks: "let's not
   give any money" matches `MONEY_SAY`, which only the 2-minute cooldown holds back. That's a few lines in
   `KinRouter` / `heard()`.
2. **Digest on double-tap:** call `flush()` when ask mode starts (`_on_double_tap` and the wake phrase). In a loud
   room `_last_heard` keeps getting refreshed by background speech, so the "6 s of quiet" chunk end can stretch
   to `CHUNK_MAX` (30 s). Flushing makes the Sarah card and the answer use fresh memory every time.
3. **`scripts/seed_morning.sh`**: the 3.4 block. **`scripts/demo_reset.sh`**: `clean_slate.sh`, then wait until
   `/api/snapshot` responds, then `seed_morning.sh`. One command between judge groups.
4. **Actor hotkeys on the family page**, for example `POST /api/actor/{sarah|scam}` running `actors.sh`, bound to keys
   1 and 2 while the page is focused. Then the browser can be truly full-screen and the Terminal strip goes away.
5. *(Nice to have)* **A family-page "It was fine" button** → `safety.clear_scam_lock()`, so the Stripe beat works
   again without a full reset.
