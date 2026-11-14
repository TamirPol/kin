# Backup video: 1 minute

Under the official rules the video is **optional, ≤ 1 minute, and a backup in case the live demo fails**.
Record it once it works, by ~5:15, before the 5:30 code freeze. The live demo is the main event: see
[LIVE_DEMO.md](LIVE_DEMO.md).

## Ship checklist (before 6:00 PM PT)

- [ ] **All commits pushed before 6:00** (code freeze ~5:30, then docs only)
- [ ] **Repo public**, README shows the screenshots in `docs/img/`, plus the video link
- [ ] **Devpost** (link drops right before 6:00): description, repo URL, 1-min video, tracks **Pipecat (Deepgram)** + **ElevenLabs** only. Text in [DEVPOST.md](DEVPOST.md).
- [ ] **Clean slate:** `bash scripts/demo_reset.sh` (wipes today, keeps voices and contacts, seeds a morning)
- [ ] **Voice:** `KIN_VOICE=elevenlabs` (Bella)
- [ ] **Wi-Fi** stable, phone hotspot ready
- [ ] **ntfy** subscribed on the phone that will appear on camera. /setup → **Send test alert** → it buzzes.
- [ ] **Family page:** light or dark, the same for every take. Zoom 125–150%, one tab, full-screen.
- [ ] **Band charged**, solid blue light, /test all green, vexo-open-kit tab closed
- [ ] Mac on Do Not Disturb. The phone on camera: Focus **off**, ringer on.

## Setup (one person, ~5 min)

- **Tripod phone** (or one propped on books): landscape 1080p, showing the wrist, the laptop at an angle,
  and the notification phone on the table. Lock focus and exposure.
- **Screen recording** of the family page: Cmd-Shift-5 → Record Selected Portion. Clap once on camera at
  the start so the two recordings line up.
- **Kin's voice through the laptop speakers.** Kin's echo gate drops its own voice coming back through the
  band, so the tripod phone can record Kin, the actors and you in one take. Earbuds aren't needed.
- **Actors:** with the family page focused, press **1** for Sarah and **2** for the scam call (the same lines
  as `bash scripts/actors.sh sarah|scam`, from the laptop speakers). Hold the band ~20 cm from the speaker.
- **WhatsApp helper option:** run the call on **WhatsApp desktop on the laptop**, so her voice comes out of
  the laptop speakers near the band. She reads Sarah's lines in her own voice instead of pressing 1, and
  holds up her phone when the alert reaches it (subscribe her phone to the Sarah contact's ntfy topic).
  The scam still comes from hotkey **2**: a different voice, so it isn't mistaken for Sarah.

## Shot list (≤ 60 s)

| # | Time | Picture | Sound / caption |
|---|---|---|---|
| 1 | 0:00–0:05 | Close-up of the band on the wrist, blue light on | Caption: **Kin: a memory companion on the Vexo band** |
| 2 | 0:05–0:17 | Wide shot: press **1**. Sarah talks from the laptop. Cut to the screen: her lines appear live. | Sarah: "Hi Dad, it's Sarah! … I'm moving to Oakland next week for my new job." |
| 3 | 0:17–0:27 | Wrist to the mouth: **"Hey Kin, who was that?"** | Kin: *"That was Sarah, your daughter. She's moving to Oakland next week."* Caption it. |
| 4 | 0:27–0:42 | Press **2**. The scam call plays. Kin cuts in. **The phone on the table lights up** (push-in or a cut to it). | Scammer: "…two thousand dollars for bail… gift cards… don't tell Mom." Kin: *"Hold on, that sounds like someone asking for money…"* Caption: **The family's phone, live** |
| 5 | 0:42–0:52 | Screen: the family page goes **red, "Grandpa Joe may not be OK"**, then scroll to **Today so far** | Caption: **Scam caught · warned out loud · family alerted** |
| 6 | 0:52–1:00 | End card | **Pipecat · Deepgram · OpenAI · ElevenLabs** on a Vexo band · **github.com/TamirPol/kin** |

Before shot 2, say "Thanks, Kin" or wait 10 s, so Kin is back to listening when the scam starts.
Pause ~6 s after Sarah so the chunk is saved. (A double-tap or "Hey Kin" also saves it right away.)

## Retakes

- Record **3 takes**, running `bash scripts/demo_reset.sh` between them. The scam leaves the page red and
  memory piles up, so reset every time.
- A take counts if shots 2–4 worked. Re-shoot the band close-up and the phone banner separately and cut them in.
- **Band misbehaving:** `KIN_DB=video.db KIN_NTFY_IN_SIM=1 .venv/bin/python -m kin.app --demo --stay`
  plays the whole story on a pretend band with push alerts on. Screen-record it and caption it **"simulated band."**

## Cut it in 10 minutes (iMovie / CapCut)

1. Import the phone clip and the screen recording, and line them up on the clap.
2. Use Picture in Picture (screen big, phone small) for shots 2 and 5, and Cutaway to the phone for shots 3–4.
3. Trim dead time while Kin thinks, but keep Kin's sentences whole and at normal speed.
4. Caption every Kin line (judges may watch muted). Add the end card.
5. Check it's ≤ 1:00, then export 1080p, upload to YouTube as **Unlisted**, and paste the link into Devpost and the README.
