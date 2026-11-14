# Kin: sketch pitch, voice-over script and edit plan

The animation (`pitch/index.html`) runs **2:00** end to end (10 scenes, auto-advancing). Below is a voice-over
timed to it, and where to cut in real footage of you wearing the band. Each scene notes which judging
criterion it's working for.

## How to record the animation

```bash
.venv/bin/python -m http.server 8790 --bind 127.0.0.1
```

1. Open http://127.0.0.1:8790/pitch/?record=1 in Chrome, press `f` for fullscreen (or make the window 16:9).
   `record=1` hides the controls and the mouse. Captions are **on** by default: press `c` (or add
   `&captions=0`) to hide them when you use your own voice-over.
2. QuickTime → File → New Screen Recording, record the screen, then press `Home` in the page to restart from scene 1.
3. Let it play the full 2:00. Trim the head and tail in the editor.

Keys: `→` / `space` next scene · `←` previous · `1`–`9`, `0` jump to scene · `p` pause · `c` captions ·
`r` record mode · `f` fullscreen · `Home` restart. URL: `?scene=N` starts at scene N, `&t=S` seconds into it,
`&paused=1` freezes there (handy for stills/thumbnails).

**Recording scenes one at a time** (easiest for cutting): open `?record=1&scene=N`, record, stop when the
pen leaves the frame. Every scene is drawn completely when the pen exits, then holds about 2 seconds.

## Timeline + voice-over (~2.3 words/second, calm pace)

| # | Starts | Scene | Voice-over | Criteria |
|---|---|---|---|---|
| 1 | 0:00 | **The problem.** Grandpa Joe, three thought clouds, stats (7M+, 11M+, $3B+, labelled approximate) | "This is Grandpa Joe. He has early memory loss. He forgets who just visited, where he put his keys, and he can't tell when a call is a scam. Seven million Americans live with Alzheimer's, and eleven million family members look after them." | Approach & Idea |
| 2 | 0:11 | **Meet Kin.** Arm, Vexo band with a glowing blue light, "listens all day", "double-tap to ask" | "Meet Kin. A memory companion on the Vexo band. It listens all day, and he never touches a screen. He just double-taps his wrist and asks." | Product–Design, X Factor |
| 3 | 0:19 | **It remembers what matters.** Four speech bubbles → "what matters? 0–3" funnel → memory cards; the weather line fades to "forgotten" | "Kin hears everything, but keeps only what matters. Every line gets a score from zero to three. Small talk scores zero and is forgotten. Sarah's news, where the keys went, the dentist tomorrow: those become memories." | AI Relevance & Depth |
| 4 | 0:34 | **Just ask.** Sarah leaves, Joe is puzzled, double-tap inset, Kin's blue answer bubble, Joe smiles | "Later, Sarah's gone and Joe can't place her. Double-tap: 'Hey Kin, who was that?' 'That was Sarah, your daughter. She's moving to Oakland next week.' And if Kin isn't sure, it says so. It never guesses a name." | Product–Technical, Design |
| 5 | 0:46 | **The scam call.** Ringing phone, scammer bubble, red flash + SCAM? stamp, Kin's warning, Sarah's phone buzzes | "Then the phone rings. 'Grandpa, it's me, I'm in jail. Buy gift cards, don't tell Mom.' Kin catches it mid-call: 'This sounds like a scam. It's okay to hang up.' And Sarah's phone buzzes: Grandpa Joe may not be OK." | X Factor, AI Depth |
| 6 | 0:59 | **Checks in.** Band falls, "Are you okay?", 15-second countdown; house with home rings, dotted wandering path, push alert | "If the band feels a fall, Kin asks if he's okay. No double-tap in fifteen seconds, and the family gets an alert. If he wanders out of range of home, they hear about that too." | Product–Technical |
| 7 | 1:11 | **Family summary.** Laptop with "Today with Dad", Sarah smiling | "At the end of the day, the family gets a calm summary. Who visited, what matters, anything worrying. Never the small talk. Fewer worried calls, more real ones." | Product–Design |
| 8 | 1:22 | **Under the hood.** Architecture sketch with moving data dots | "Under the hood: the band streams audio over Bluetooth into a Pipecat pipeline. Deepgram transcribes and separates speakers, and voiceprints know Joe's voice. A router decides: listen, or answer. Listening, an OpenAI brain scores what matters into memory. On a double-tap, a voice agent answers with memory tools in an ElevenLabs voice. Gemini 4 is Kin's eyes for where things are, and every sentence gets a scam check." | AI Relevance & Depth, Technical |
| 9 | 1:40 | **Why it matters.** Families pay · clinics & care homes · private by design · "And dignity" | "Families already pay for medical-alert pendants, and one stopped scam pays for years of Kin. Next come memory clinics and care homes. It's private by design: small talk is never kept, and memory stays local. And dignity: he never has to pull out a phone." | Approach & Idea |
| 10 | 1:49 | **Finale.** Camera pulls back to show the whole storyboard, then zooms into "Kin: remembers, so they don't have to." + "live demo →" | "Kin. It remembers, so they don't have to. Let me show you." | Presentation |

Word count ≈ 300 for 2:00. If you need 90 seconds, cut the second sentence of scene 3, the voiceprints/router
sentences of scene 8 and all of scene 9 except the dignity line, and skip scene 6 with `→`.

## Where to cut in real footage

Real footage is what proves it works, so swap animation for camera whenever the animation has made its
point. Suggested inserts (shots from [docs/VIDEO.md](../docs/VIDEO.md)):

| After scene | Insert (5–15 s) | Why it helps |
|---|---|---|
| 2 (Meet Kin) | **Phone close-up:** the band on your wrist, blue light on, slow push-in. Hard cut from the sketched band to the real one. | Product–Design: the sketch becomes a real object |
| 3 (remembers) | **Screen:** the live dashboard. Sarah's lines appear, then the weather line greys out and the Sarah card, keys item and dentist to-do pop in. | Technical: the filter is real, not a slide |
| 4 (who was that) | **Phone:** tight shot of the double-tap, "Who was that?", Kin's real ElevenLabs answer from the laptop. Caption the answer. | X Factor: the money shot. Keep Kin's voice at full speed |
| 5 (scam) | **Phone + screen:** a second phone on speaker plays the scam line, Kin interrupts; cut to the red scam alert and the real ntfy notification on a phone. | AI Depth + X Factor |
| 6 (checks in) | *(optional)* band dropped onto a cushion, "Are you okay?", double-tap, "glad you're alright". Cut first if you're over time. | Technical |
| 7 (summary) | **Screen:** the real "Today so far" summary on the dashboard. | Product–Design |
| 8 (under the hood) | *(optional, 3 s)* the terminal with the Pipecat logs scrolling, or the item photo from Gemini vision. | Technical |
| 10 (finale) | Cut on "live demo →" straight into the live demo, or the end card with the GitHub link. | Presentation |

**Honesty rule:** if a shot uses the simulated band (`--demo` / `--sim`), say "simulated band" on screen.

## Editing tips

- Record the voice-over **after** cutting the footage, so the words land on the right picture. The scene
  table above gives the animation timing; the inserts add their own length.
- Turn captions off (`c`) in the screen recording if you add your own titles in the editor; leave them on
  for a silent-autoplay version (Devpost, social).
- Export 1080p. The animation is drawn on a 1920×1080 canvas, so it stays sharp at that size.
- For a thumbnail: `?scene=10&t=10&paused=1&record=1` is the finished title card;
  `?scene=10&t=2.5&paused=1&record=1` is the zoomed-out storyboard of the whole story.
