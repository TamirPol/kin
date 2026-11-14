# Demo video shot list (≤ 2:00, one person, phone + screen recording)

**Gear:** a phone on a stand or propped on books (shoots the wrist, the table and your face), and a
QuickTime screen recording of the dashboard (File → New Screen Recording, **with the mic on** so Kin's
voice from the laptop is captured). Edit in iMovie / CapCut: phone footage on top, dashboard cut in
or picture-in-picture.

**Record in this order to save time:** (1) the screen recording of one full live run, (2) phone close-ups
of the same run (or a second run), (3) the voice-over. Sync on Kin's spoken answers. They're easy to
spot in both tracks.

**Playing the other people alone:** record Sarah's and the scammer's lines in advance (a friend's voice
memo, or your own voice with a different pitch) and play them from a second phone near the band. Or run
`--sim`/`--demo` for those beats and say so on screen. **Be honest:** if a shot uses the simulator, put
"simulated band" in the caption.

**Setup:** `KIN_DB=video.db .venv/bin/python -m kin.app --webcam 0` (fresh memory), dashboard at
http://localhost:8700 in a clean full-screen browser window, light theme, zoom 125% so text reads on a phone.

| # | Time | Shot (camera) | Audio / on-screen text |
|---|---|---|---|
| 1 | 0:00–0:08 | **Phone:** close-up of the band on a wrist, blue light on. Slow push-in. | VO: "For people with early memory loss, the hardest part isn't forgetting how to do things. It's forgetting *people*." |
| 2 | 0:08–0:15 | **Phone:** wide shot, a person at a kitchen table. Title card over it. | Text: **Kin: a memory companion on the Vexo band.** VO: "This is Kin. The person wearing it never touches a screen." |
| 3 | 0:15–0:30 | **Phone:** "Sarah" (played from a second phone or a friend) talks to the wearer. **Cut to screen:** lines appearing live in the transcript. | Sarah: "Hi Dad, it's Sarah! I'm moving to Oakland next week." Wearer: "I'm putting my keys in the kitchen drawer. I'll call the dentist tomorrow." Sarah: "Nice weather today." |
| 4 | 0:30–0:42 | **Screen:** after the 6-second pause, the person card for Sarah, the to-do, the keys item, and the weather line greyed out. Zoom in on each (do it in the edit). | VO: "Kin listens, but only keeps what matters. Sarah, her news, where the keys are, the dentist. The weather is scored zero and forgotten." |
| 5 | 0:42–0:58 | **Phone:** finger double-taps the band (tight close-up). Wearer: "Who was that?" | Kin (laptop audio): "That was Sarah, your daughter. She's moving to Oakland next week." Caption the answer. |
| 6 | 0:58–1:06 | **Phone:** double-tap. "Where are my keys?" | Kin: "In the kitchen drawer." |
| 7 | 1:06–1:18 | **Phone:** glasses set on the table in the webcam's view. **Screen:** the item appears with a camera photo. Double-tap, "Where are my glasses?" | Kin answers with the Gemini location. Text: **Vision: Gemini 4**. |
| 8 | 1:18–1:28 | **Phone:** double-tap, "Can you reorder my blood pressure pills from Walgreens? They're about thirteen dollars." **Screen:** Purchases row turns green. | Kin: "Done. I ordered…" Text: **Stripe test mode · family limit $50**. |
| 9 | 1:28–1:45 | **Phone:** a second phone on speaker plays the scam line. **Screen:** the red scam alert and "Purchases locked." | Scammer: "Grandpa, it's your grandson. I'm in jail and I need bail. Buy gift cards and don't tell Mom." Kin: "This sounds like a scam. Please don't buy anything… It's okay to hang up." |
| 10 | 1:45–1:52 | **Phone:** band dropped onto a cushion. Kin: "Are you okay?" Double-tap. | Kin: "Okay, glad you're alright." **Screen:** fall / fall_ok alerts. *(Cut this shot first if you're over time.)* |
| 11 | 1:52–2:00 | **Screen:** the full dashboard. End card. | VO: "Kin remembers the people you love, protects you, and keeps your family close. Built on Vexo, with Pipecat, Deepgram, OpenAI, ElevenLabs, Gemini 4 and Stripe." Text: **github.com/TamirPol/kin** |

## Tips

- **Audio first.** Kin's answers are the money shots. Laptop volume up, room quiet, phone mic close
  to the laptop speaker. If ElevenLabs audio doesn't make it into the screen recording, record the laptop
  speaker with the phone and use that track.
- Keep the wrist in frame for every double-tap. It's the "beyond the screen" proof.
- Don't speed-ramp Kin's voice. Do cut the dead time while it thinks.
- Hard cap: 2:00. If long, cut shots 10, then 7, then 6.
- Export 1080p, upload unlisted to YouTube, and paste the link into Devpost and the README.
- **Backup:** if live recording fails, record `KIN_DB=vid2.db .venv/bin/python -m kin.app --demo --stay`
  with the dashboard (it runs the whole story by itself), and caption it "simulated band."
