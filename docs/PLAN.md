# Team plan

**Core first.** Core = the band hears → Kin remembers the right things → double-tap → Kin answers
correctly out loud → the dashboard shows it. Nothing else until the core works on the real band.

## Who does what

Each lane owns different files, so we don't step on each other in git. Pull often, push small.

### Core 1: Tash (input: band → text)
Files: `kin/app.py`, `kin/voice.py`

1. Band 57 connected with the team's Deepgram key: `python -m kin.app`, double-tap the band first.
   Live transcript appears in the terminal and on the dashboard.
2. Deepgram speaker labels: two people talking get different labels.
3. Tune `WEARER_DB` in `kin/app.py` (now a guess, -32 dBFS) so the wearer shows as `wearer` and the other
   person as `speaker N`. Test at real distance (across a table) in the noisy venue.
4. Double-tap → question → spoken answer works reliably: no missed taps, never stuck in ask mode.
5. ElevenLabs voice plays clearly. Pick a voice (`ELEVENLABS_VOICE_ID`). Optional 10-minute win:
   pair the Meta glasses to the laptop as the audio output, so Kin talks in your ear.

### Core 2: Tamir (brain: text → memory → answers)
Files: `kin/brain.py`, `kin/static/` (dashboard look only)

Works without the band: `python -m kin.app --sim` and type lines (keys below) with a real OpenAI key.

1. Run the test conversations below. Write more of your own.
2. Importance filter: small talk dropped, facts kept, **nothing invented**. Tune the prompt in
   `kin/brain.py` until it's right.
3. Answers: "Who was that?", "Where are my keys?", "What did Sarah say?", "What do I need to do
   today?" must be short, warm, correct and never guessing. (The ask-mode prompt is `SYSTEM` in
   `kin/voice.py`. Agree with Tash before changing it, since it's in their file.)
4. Dashboard readable from across the room: big text, clear person cards.

## Checkpoints

| Time | Goal |
|---|---|
| **1:00 PM** | Tash's real band audio feeds Tamir's tuned brain: first real end-to-end run |
| **2:30 PM** | Demo story works **3 times in a row** on real hardware: **core done** |
| 2:30–4:30 | Extras in order: vision (Gemini) → glasses earpiece → scam demo → Stripe |
| **4:30 PM** | Feature freeze. Record the demo video. |
| **5:45 PM** | Devpost submitted. Don't wait until 5:59. |

## Demo story (2 minutes)

1. Tash wears the band. Tamir walks up: "Hi Dad, it's Sarah! I'm moving to Oakland next week."
2. Tash: "I'm putting my keys in the kitchen drawer." … "I'll call the dentist tomorrow."
3. Some small talk ("nice weather today"): show it greyed out on the dashboard.
4. Double-tap: "Who was that?" → "That was Sarah, your daughter. She's moving to Oakland next week."
5. Double-tap: "Where are my keys?" → "In the kitchen drawer."
6. Double-tap: "What do I need to do?" → "Call the dentist tomorrow."
7. (Extras if built: the fake scam call, dropping the band for the fall check, keys seen by the camera.)
8. Show the dashboard: person card, to-do, items, greyed-out small talk.

## Terminal keys (pretend band or no Deepgram key)

`t` double-tap · `f` fall · `a <question>` ask · `1 <text>` speaker 1 says · `2 <text>` speaker 2 ·
`w <text>` the wearer says · `s` show memory · `q` quit

## Test conversations for Core 2

Type each block, wait ~7 seconds (a pause ends a chunk), then check `s` and the dashboard. **Expected**
is what a good brain should store.

1. **Family intro**
   `1 Hi Dad, it's Sarah!` · `w Oh hi sweetheart.` · `1 I'm moving to Oakland next week for my new job.`
   Expected: person Sarah (daughter/child), fact "moving to Oakland next week for a new job", importance 2.
2. **Pure small talk**
   `2 Hi, how are you?` · `w Fine thanks.` · `2 Nice weather today.`
   Expected: importance 0, nothing stored.
3. **Cashier**
   `2 Hi, what would you like to order?` · `w A small coffee please.` · `2 That's four fifty.`
   Expected: importance 0. A stranger's transaction, nothing stored.
4. **Item placement**
   `w I'm putting my glasses on the nightstand.`
   Expected: item glasses → on the nightstand.
5. **Plan / promise**
   `w I'll call the dentist tomorrow morning.`
   Expected: to-do "Call the dentist", due "tomorrow morning", importance 3.
6. **Health**
   `1 Dad, the doctor said take the new pill with food, twice a day.`
   Expected: fact about medication, importance 3.
7. **Grandchild news**
   `3 Hi Grandpa, it's Leo!` · `3 I got into Berkeley!` · `w That's wonderful!`
   Expected: person Leo (grandchild), fact "got into Berkeley", emotional, importance 2.
8. **Neighbor + favor**
   `2 Hey Joe, it's Mike from next door. Can you water my plants on Saturday?` · `w Sure, I'll do it.`
   Expected: person Mike (neighbor), to-do "Water Mike's plants", due Saturday.
9. **Name without intro**
   `1 Mom says she'll visit on Sunday.`
   Expected: fact about Mom visiting Sunday; don't invent who speaker 1 is.
10. **Mixed small talk + one fact**
    `1 How's your knee?` · `w Better.` · `1 By the way, Emma had her baby, a girl named Lily.`
    Expected: only the Emma/Lily fact is kept.
11. **Money red flag (scam)**
    `2 Grandpa, it's your grandson. I'm in jail and need bail. Buy gift cards and don't tell Mom.`
    Expected: importance 3, money_safety; the scam warning is spoken and an alert raised.
12. **Things that must NOT be stored**
    `2 On TV tonight, the weather will be sunny.` (background TV)
    Expected: importance 0.

Then ask (`t`, then `a …`): "Who was that?" · "Where are my glasses?" · "What did Sarah say?" ·
"What do I need to do this week?" · "Who is Leo?" · "Did Emma have her baby?"

## Extra: Meta glasses (only after the core is done)

- **Level 1, 10 min:** pair the glasses to the laptop over Bluetooth as the audio output. Kin's
  answers and warnings play privately in your ear (the band has no speaker).
- **Level 2, 2–3 h, risky:** Meta's Wearables Device Access Toolkit (v1.0, iOS/Android; Ray-Ban
  Meta Gen 1/Gen 2) streams the glasses camera to a phone app, which posts frames to Kin's vision
  module. Needs Meta developer access, developer mode in the Meta AI app, and Xcode/Android Studio.
  The Mock Device Kit uses the phone camera for building without glasses.
- **Level 3:** captions in the lens. Only on the Meta Ray-Ban Display model.

## Vision without glasses

Any camera works: the laptop webcam (`--webcam 0`), an iPhone through Continuity Camera clipped to
a shirt (`--webcam 1`), or a Marv Labs camera (`--camera-url URL`). Needs `GEMINI_API_KEY`.
Demo: put the keys on the table silently → double-tap → "Where are my keys?" → answer + photo.

## Partner setup (5 min)

```bash
git clone https://github.com/TamirPol/kin.git && cd kin
git clone https://github.com/VexoAI-Org/vexo-open-kit.git
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "pipecat-ai[deepgram,openai,elevenlabs,silero]" bleak av \
    python-dotenv fastapi "uvicorn[standard]" stripe google-genai sounddevice numpy websockets opencv-python pytest
cp .env.example .env     # add keys in person, never through chat or git
.venv/bin/python -m kin.app --demo    # should run the whole story on a pretend band
```
