# Live demo: 2:00 demo + 1:00 Q&A

In-person judging starts **right after 6:00 PM**: each team gets **2 minutes of demo and 1 minute of Q&A**.
This page is the whole plan. Print section 1, or keep it on your phone. The 1-minute backup video is in
[RECORDING.md](RECORDING.md).

**Voice-first.** Double-taps through the strap fabric are unreliable, so the demo runs on your voice:
**"Hey Kin, …"** to ask and **"I'm fine"** to answer a fall check. Taps from the impact of the fall itself are
ignored, so the drop can't answer its own check. If you do tap, **two quick single taps**
(within 0.8 s) count as a double-tap.

You play **Grandpa Joe**. The laptop plays the other people (hotkeys **1** and **2** on the family page).
Your phone is "Sarah's phone." The judges watch the family page.

---

## 1. The run (exactly 2:00)

```
          JUDGES
   [your phone, face-up, ntfy open, ringer ON]
 ┌───────────────────┐
 │  family page      │  laptop angled toward the judges, zoom 150%, page FOCUSED (hotkeys)
 └───────────────────┘
   you beside the laptop, band on your wrist · a cushion on the table (for the fall)
```

| Time | You say / do | Judges see and hear |
|---|---|---|
| **0:00–0:10** | **Hook:** "Your daughter walks in… and you can't find her name. Seven million Americans live with that. *(lift the wrist)* This band finds it for you." | The band's blue light |
| 0:10–0:15 | "Joe never touches a screen. This is his daughter's screen." | The family page: calm status and the seeded morning in **Today so far** |
| 0:15–0:30 | Press **1**. Hold the band ~20 cm from the laptop speaker while Sarah talks. | Sarah: "Hi Dad, it's Sarah! … moving to Oakland … I'll call you on Sunday." Her lines appear live. |
| 0:30–0:35 | Wrist to your mouth: "Oakland! Wow." | The line appears labeled **Joe** |
| 0:35–0:47 | **"Hey Kin, who was that?"** Then **stay silent** until Kin answers. | Kin: *"That was Sarah, your daughter. She's moving to Oakland next week."* The Sarah card is on the page. |
| 0:47–0:50 | **"Thanks, Kin."** | "You're welcome." Back to listening. |
| 0:50–1:08 | Press **2** (the scam call). Let it play. Kin cuts in. **Pick up your phone as it buzzes and turn it to the judges.** | Scammer: "…two thousand dollars for bail… gift cards… don't tell Mom." Kin: *"Hold on, that sounds like someone asking for money. Please don't send anything until you've checked with Sarah."* The phone shows **"Grandpa Joe may not be OK"**. The page goes **red**. |
| 1:08–1:15 | "It only heard Joe's side of a real call. It interrupted, told him not to send anything, and his daughter's phone buzzed." | The red hero and the scam alert |
| 1:15–1:35 | **Fall:** drop the band onto the cushion. Kin asks. Wait one beat, then **"I'm fine."** | Kin: *"Are you okay? Say I'm fine, or double-tap your band."* … *"Okay, glad you're alright."* "He has ten seconds after Kin asks. If he says 'no' or 'help', the family is alerted right away. The phones only buzz if he's not okay or doesn't answer, so nobody panics over a dropped band." |
| 1:35–1:48 | Point at **Today so far**. "Under the hood: Pipecat, Deepgram streaming with speaker labels, voiceprints for *who* said it, a memory brain that scores everything 0 to 3, and ElevenLabs for the voice." | The summary mentions Sarah, the scam call and the fall, calmly |
| 1:48–2:00 | **Close:** "Small talk forgotten, family remembered, scammer stopped. Joe never touched a screen. That's Kin." | The whole page |

**Rules while it runs**
1. After "Hey Kin, …", **say nothing** until Kin answers. Everything you say gets added to the question.
2. **"Thanks, Kin"** closes the conversation. Otherwise for ~9 s Kin treats anything you say to the judges as a follow-up.
3. Before pressing **2**, make sure Kin is back to listening (step 0:47).
4. **Over time?** Cut the fall (1:15–1:35) and go straight to Today so far. **Under time?** "Hey Kin, when is Sarah calling?" → "On Sunday."

---

## 2. Q&A (1:00): four 15-second answers

**"What's real and what's mocked?"** "Real: the Vexo band over Bluetooth, the Pipecat pipeline, Deepgram, the
OpenAI brain and agent, ElevenLabs, on-device voiceprints and the phone push. The morning on the page was typed
in through the same pipeline. Everything after that was live. End-to-end tests pass 32 of 32."

**"Privacy?"** "The blue light is on whenever the mic is. Kin never stores audio, voiceprints are numbers, and
small talk and strangers score zero and are forgotten. Phone alerts are generic, with no names or transcripts."

**"What if it gets a name wrong?"** "It never invents one. Who said what is a vote between voiceprint, loudness
at the wrist and context, and when unsure it says 'I'm not sure.' The brain eval passes 12 of 12."

**"Why a band, and who pays?"** "The people who need this can't reliably unlock a phone, and a band is always on
them. The family pays a subscription, like a medical-alert pendant, and memory clinics and insurers are the channel."

*(Also built, if asked: Gemini 4 vision for "where are my glasses?". Not demoed today, so don't claim more
than that. Kin never buys anything or moves money, by design.)*

---

## 3. Setup (T−15 → T−0)

**Hardware:** laptop on the charger, band charged, phone > 50%. `caffeinate -dimsu &`. Mac on Do Not Disturb.
Phone: Focus **off**, ringer on. Output = **MacBook Pro Speakers** at 90–95% (Kin's echo gate ignores its own
voice coming back through the band). Close any vexo-open-kit tab (one Bluetooth client).
Network: `ping -c 5 api.deepgram.com`. If it's slow, switch to the hotspot **now**.

**Start Kin** (tab 1, leave it running):

```bash
cd ~/kin && KIN_VOICE=elevenlabs KIN_REMIND_AFTER=7200 bash scripts/kin.sh
```

Double-tap (or tap twice) to connect. `KIN_REMIND_AFTER=7200` stops a reminder going off mid-demo.

**Setup page** http://localhost:8700/setup: wearer **Grandpa Joe**. **Record your voice at the demo table**
(a voiceprint recorded in venue noise matches better in venue noise). Emergency contact **Sarah**, with the
ntfy topic subscribed on your phone → **Send test alert** → it buzzes. Check http://localhost:8700/test is all green.

**Reset and seed** (tab 2), before the first run and **between every judge group** (~40 s):

```bash
bash scripts/demo_reset.sh
```

This wipes today (voices and contacts are kept), waits for Kin to reconnect, then seeds a morning: Dr. Patel's
pill instructions, Mike's plants on Saturday, glasses on the nightstand. Nothing in it mentions Sarah or money.
The scam and the fall leave alerts (and the red status), so always reset.

**Screen:** one tab, http://localhost:8700, zoom 150%, light theme, **click the page so it has focus** (for
hotkeys 1/2). Do one dry run, then reset.

Typed helpers for emergencies (tab 2):

```bash
k(){ curl -s -o /dev/null -X POST localhost:8700/api/command -H 'content-type: application/json' -d "{\"cmd\":\"$*\"}"; }
ask(){ k "a $*"; }    # ask Who was that?   (a typed question when Deepgram mishears)
```

`k t` = a tap, `k f` = a fall.

---

## 4. When something goes wrong (≤ 15 s each, then move on)

| Problem | Do | Say |
|---|---|---|
| "Hey Kin" not picked up | Say it again, closer and slower. Or two quick taps. Or `ask Who was that?` | "Loud room. Here it is typed, same brain." |
| A wrong or "not sure" answer | "Thanks, Kin," then ask once more. Then use `ask …`. | "It says 'not sure' rather than guess a name. That's on purpose." |
| Hotkey does nothing | Click the page to focus it and press again. Or run `bash scripts/actors.sh sarah` / `scam`. | |
| Band doesn't feel the drop | `k f` in tab 2 | "Same fall check, triggered by hand." |
| Phone doesn't buzz | Point at the red page. | "Same alert on Sarah's page. Venue network." |
| Band disconnects | Two taps near the laptop. `kin.sh` reconnects by itself. | "A hundred bands on one Bluetooth channel." |
| Band or Wi-Fi gone for > 20 s | Ctrl-C tab 1, then `KIN_DB=demo.db KIN_NTFY_IN_SIM=1 .venv/bin/python -m kin.app --demo --stay` | "Same code, fed by a pretend band." |
| Everything | Play the 1-minute video (downloaded, open in QuickTime). | "Here's the recording from this afternoon, same band." |
