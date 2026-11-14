# VexoHacks: everything we know

Saturday, Nov 14, 2026, at Y Combinator, San Francisco. Hosted by Vexo (YC F26). Theme:
**"Build beyond the screen"**: wearables, voice, real-world experiences. Tracks: Voice, Vision, Ambient
(pick one or combine; Kin covers all three).

Sources: the organizers' kickoff deck (a draft, so some details may change), vexoai.com/hackathon,
the Luma page and organizer announcements. **Check Discord for changes.** It is the main channel for updates.

## Schedule (Pacific)

| Time | What |
|---|---|
| 8:30 | Check-in + breakfast |
| 9:00 | Welcome + kickoff |
| 9:15 | Sponsor introductions |
| 9:30 | Fireside chat: Ming Hua, VP of Wearables at Meta |
| 10:00 | Final announcements |
| 10:15 | **Hacking starts** |
| 10:25–10:45 | Product demos (Subvocal, Marv Labs) |
| 12:30 | Lunch |
| **6:00** | **Hacking closes, submissions due, dinner** |
| 6:30 | Judging starts (round 1: "show what you built") |
| 8:00–9:00 | Finals + closing |

## Rules

- Teams encouraged. In-person participation.
- **Public GitHub repo** (this one) and **a hardware-related project** (the Vexo band).
- Meet each track's requirements for every track you enter.
- Final commits and the final video before **6:00 PM PT**.
- Wear your badge and wristband. No smoking, vaping or alcohol. Respect staff-only areas.

## Submission checklist (due 6:00 PM)

- [ ] GitHub repo with README (this repo)
- [ ] Video demo (record by ~5:00; keep a backup in case the live demo fails)
- [ ] Devpost submission (link is posted closer to the deadline; watch Discord)
- [ ] Ready to show a **working demo in person** at judging

Judging criteria and pitch length were not published. Plan a 2-minute live demo and ask at kickoff.

## Prizes

Overall prizes and sponsor-track prizes are separate: one project can win both.

| Prize | Award | Kin's angle | Status |
|---|---|---|---|
| **Overall 1st** | $5K OpenAI credits, VITURE Pro 2 XR glasses, 3 months ElevenLabs Pro, 1 year Superserve Pro, **YC final interview** | The whole product | Core built |
| Overall 2nd | $2.5K OpenAI credits + DJI drone | | |
| Overall 3rd | $1K OpenAI credits + Ray-Ban Meta glasses | | |
| **Best Voice Use Case on Pipecat** | Up to $100K Deepgram credits + **Nintendo Switches** | Pipecat runs the whole voice pipeline; Deepgram STT with speaker labels | Built; test with real keys |
| **Best ElevenLabs Project** | 3 months ElevenLabs Scale per team member | Kin's warm, calm voice | Wired; needs key |
| **Best Use of Gemini 4** | 1st $2K GCP credits per member, 2nd $1K, 3rd $500 | Vision: camera → Gemini → "where things are" | Built; needs key + camera |
| **Best Economic Agent (Stripe)** | $3K / $2K / $1K Stripe credits | Buys within family limits, blocks scams | Built; simulated until a test key |

The Pipecat prize slide was marked "work in progress". Confirm at the Deepgram/Pipecat table what
they want to see.

**Order of attack:** core first (Overall + Pipecat + ElevenLabs), then Gemini (vision), then Stripe.

## Free credits (claim early; never paste keys into chat or git)

| Sponsor | What | How |
|---|---|---|
| Vexo | Deepgram key + OpenAI key per team | From the organizers with the band |
| OpenAI | $50 API credits per participant | Single-use links from organizers; redeem before Nov 16 |
| ElevenLabs | 1 month Creator | Tied to your registration email |
| Gemini | Credits via temporary accounts for on-site attendees | Google table |
| Stripe | $500 credits + free US incorporation | Stripe startup-benefits page for VexoHacks |
| Superserve | $100 credit, code `VEXOHACKS` | Redeem by Nov 14, 11:59 PM PT |
| MiniMax | $30 API credits | Claim form in their Discord channel |
| Marv Labs | Cameras to build with | Their booth |

Not used by Kin (don't force them in): Mastra, MiniMax, Brex, Superserve.

## Hardware available

- **Vexo band** (ours: **band 57**, `Vexo-HACK-57`): mic, motion sensor, taps, light. See [BAND.md](BAND.md).
- **Marv Labs cameras**: ask at their booth (a stream URL works with `--camera-url`).
- **Meta Ray-Ban glasses** (ours): optional extra. See the glasses section in [PLAN.md](PLAN.md).

## Organizer rules for the bands

- **Only connect to your own band** (about 100 bands in the room). The kit filters by number.
- The **firmware is fixed**: don't try to change the band. Build on the laptop.
- The Bluetooth contract in `vexo-open-kit/docs/bluetooth-contract.md` is the source of truth.
