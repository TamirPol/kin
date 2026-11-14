# Recording the demo video (one person + a remote helper)

## Ship checklist (do this first)

- [ ] **Clean slate:** `bash scripts/clean_slate.sh` (with `bash scripts/kin.sh` running; old memory backed up to `kin.db.bak`, voiceprints kept)
- [ ] **Voice:** `KIN_VOICE=elevenlabs` in `.env` (not `openai`/`say`). Say "Hey Kin, hello" once to check it's Bella.
- [ ] **Wi-Fi:** stable connection (Deepgram, OpenAI, ElevenLabs and ntfy are all online). Hotspot as backup.
- [ ] **ntfy:** the helper's phone (and yours) subscribed to an emergency-contact topic. /setup → **send test alert** → it buzzes.
- [ ] **Family page theme:** pick light or dark and keep it for every take. Browser zoom 125%, full-screen, no other tabs or bookmarks bar.
- [ ] **Band charged**, mic light solid blue, /test page all green, vexo-open-kit dashboard tab **closed** (one Bluetooth client).
- [ ] **Earbuds** charged and paired (Kin's voice, see Audio below). Mac notifications off (Focus → Do Not Disturb).
- [ ] **Devpost fields** pasted from [DEVPOST.md](DEVPOST.md), with the video link added once it's uploaded.
- [ ] **Repo public**, README screenshots in `docs/img/`, video link in the README, last commit pushed before 6:00 PM.

---

## The setup

```
  [tripod phone] ── records POV: wrist, table, laptop screen edge, your face (room audio)
        │
  you + band ───── ~30 cm ──── laptop speakers: the helper on WhatsApp desktop, or scripts/actors.sh
                                laptop screen: family page (recorded with Cmd-Shift-5)
  Kin's voice ──► earbuds (so the band doesn't hear Kin) + captured on the Mac (see Audio)
  helper (remote) ── WhatsApp video call on the LAPTOP, ntfy on HER phone = "the daughter"
```

- **Phone on a tripod** (or propped on books): landscape, 1080p/30. The frame shows your wrist and the table,
  with the laptop at an angle. Lock exposure and focus (long-press on iPhone).
- **Screen recording of the family page:** Cmd-Shift-5 → Record Selected Portion (the browser window) →
  Options → Microphone: see Audio. Start it before the phone, then clap once on camera so the two line up.
- **The helper on WhatsApp:** run the call on **WhatsApp desktop on the laptop**, so her voice comes out of
  the laptop speakers next to the band, the same place `actors.sh` plays from. The phone stays free to film.
  - **She plays Sarah**, reading the lines below in her own voice. Kin hears a real second voice.
  - **She is also the family**: her phone gets the ntfy push. When the scam happens, she holds her phone up to
    her camera and the buzz is in the WhatsApp window you're screen-recording. That's the X-factor shot.
  - **The scam caller:** `bash scripts/actors.sh scam` (a different, male voice, so Kin doesn't think it's
    Sarah). Or she reads it with the call on speaker.
  - **No helper?** `bash scripts/actors.sh sarah` and `scam` do both parts from the laptop speakers.

**Helper's cue card**
- Sarah: "Hi Dad, it's Sarah!" … "I just wanted to tell you, I'm moving to Oakland next week for my new job." … "I'll call you on Sunday."
- *(Wait for the scam. When your phone buzzes, hold it up to the camera for 3 seconds.)*

### Audio: getting Kin's voice clearly

The band must not hear Kin, or Kin's own words get transcribed as another speaker. So Kin talks into
**earbuds**, which is how it was tested on the real band. But then the tripod phone can't hear Kin, and
Cmd-Shift-5 records a microphone, not the Mac's own sound. Pick one, and test it in a 10-second take first:

1. **Best: record the Mac's sound.** Install the free **BlackHole 2ch** audio driver. In Audio MIDI Setup,
   create a Multi-Output Device (earbuds + BlackHole) and set it as the Mac's output. In Cmd-Shift-5 →
   Options, choose BlackHole as the microphone. The screen recording then carries Kin, the helper and actors,
   clean, while you hear Kin in the earbuds. Your own voice comes from the phone track. *(~5 min, needs an
   install, so do it before the deadline crunch.)*
2. **Quick: laptop speakers for Kin.** Unpair the earbuds and the phone hears everything naturally. Keep the
   band as far from the speakers as the actors allow, and check the family page after the take. If Kin's
   sentences show up as someone else's, go back to option 1.
3. **Captions.** Kin's words always appear in the conversation on the family page, so caption every Kin
   line in the edit anyway. It helps judges watching muted.

---

## Shot list (≤ 2:00)

| # | Time | Picture | Sound / text on screen |
|---|---|---|---|
| 1 | 0:00–0:07 | **Phone:** close-up of the band on your wrist, blue light on, slow push-in | VO: "For people with early memory loss, the hardest part isn't forgetting how to do things. It's forgetting people." |
| 2 | 0:07–0:13 | **Phone:** wide shot of you at the table. Title card. | **Kin: a memory companion on the Vexo band.** VO: "The person wearing it never touches a screen." |
| 3 | 0:13–0:30 | **Phone** wide, cut to **screen**: lines appearing live | Sarah (helper): "Hi Dad, it's Sarah! … moving to Oakland next week … I'll call you on Sunday." You: "I'm putting my keys in the kitchen drawer. I'll call the dentist tomorrow." |
| 4 | 0:30–0:42 | **Screen:** after the 6 s pause, zoom (in the edit) on the Sarah card, the dentist to-do, keys → kitchen drawer, "Today so far" | VO: "Kin only keeps what matters, and it knows who said it." Text: **importance 0–3 · voiceprints** |
| 5 | 0:42–0:55 | **Phone:** tight shot of the double-tap. "Who was that?" | Kin: "That was Sarah, your daughter. She's moving to Oakland next week." Caption it. |
| 6 | 0:55–1:05 | **Phone:** no tap. "When is she calling?" … "Thanks." Then "Hey Kin, where are my keys?" | Kin: "On Sunday." … "In the kitchen drawer." Text: **conversation mode · "Hey Kin"** |
| 7 | 1:05–1:15 | **Phone:** double-tap, "Reorder my blood pressure pills from Walgreens." **Screen:** green purchase row | Kin: "Done. I ordered…" Text: **Stripe test mode · family limit $50** |
| 8 | 1:15–1:35 | **Phone:** laptop speakers play the scam (`actors.sh scam`). **Screen:** the scam alert. **WhatsApp window:** the helper holds up her buzzing phone. | Scammer: "…two thousand dollars for bail… gift cards… don't tell Mom." Kin: "This sounds like a scam…" Text: **The family's phone, live** |
| 9 | 1:35–1:43 | **Phone:** double-tap, "Buy a two hundred dollar gift card." **Screen:** red blocked row | Kin: "I've paused all purchases…" |
| 10 | 1:43–1:52 | **Screen:** scroll the family page: Today so far, people, alerts | VO: "Six AI agents, a real band, and a family that knows their dad is okay." |
| 11 | 1:52–2:00 | End card | **Built on Vexo · Pipecat · Deepgram · OpenAI · ElevenLabs · Gemini 4 · Stripe** · **github.com/TamirPol/kin** |

Optional inserts if you're under time: the fall check (drop the band onto a cushion → "Are you okay?" →
double-tap, and the helper's phone buzzes), or glasses appearing on the table with a Gemini photo (run Kin
with `--webcam 0`).

**Phone notification close-up (insert):** if the WhatsApp shot is too small, record your own phone's screen
(Control Center → Screen Recording) while /setup → **send test alert** fires, and cut 2 s of the banner into shot 8.

## Retake plan

- Record **3 full takes** back to back. Between takes run `bash scripts/clean_slate.sh` and wait for Kin to
  restart (~5 s). Voiceprints are kept, so Sarah and you are still recognized.
- A take is usable if shots 3–8 worked. Fix anything else with inserts. Re-record single beats (a clean
  double-tap close-up, the phone banner, the VO) afterwards. They don't need to be the same take.
- After the **scam**, purchases stay locked for 30 minutes. Always clean-slate before the next take.
- **Band misbehaving** (won't connect, missed taps after 2 tries): switch to
  `KIN_DB=video.db KIN_NTFY_IN_SIM=1 .venv/bin/python -m kin.app --demo --stay` (the whole story on a
  pretend band, with push still on). Record the screen only, and caption it **"simulated band."** Don't
  pass it off as the real band.
- Record the **voice-over last** with the phone's Voice Memos, mouth 20 cm away, in a quiet corner.

## Cut it in 15 minutes (iMovie; CapCut is the same idea)

1. *(2 min)* New Movie, then import the phone clip, the screen recording, the VO and the end card (a Keynote slide exported as PNG works).
2. *(3 min)* Put the phone clip on the timeline and line up the screen recording above it using the clap.
   Use **Cutaway** for the screen shots, or **Picture in Picture** (screen big, phone small in a corner) for shots 3–4 and 8.
3. *(4 min)* Split (Cmd-B) and delete dead time while Kin thinks. Keep Kin's sentences whole, at normal speed.
4. *(3 min)* Titles: lower-third captions for every Kin line, plus the tag lines from the shot list.
5. *(2 min)* Drop the VO under shots 1, 2, 4 and 10. Duck the clip audio to 30% under the VO.
6. *(1 min)* Check it's **≤ 2:00**. Over time? Cut shot 9, then 6, then the cashier. Share → File → 1080p.
   Upload to YouTube as **Unlisted**, then paste the link into Devpost and the README.
