"""Kin's Pipecat pipeline: the band's microphone in, Deepgram, Kin's router, the LLM, a voice out.

    BandAudioSource -> Deepgram STT (diarized) -> KinRouter -> user ctx -> OpenAI LLM (tools)
                    -> ElevenLabs TTS -> Speaker -> assistant ctx

The router decides where each finished sentence goes:
  LISTEN mode: into memory (transcript, then brain.digest in chunks)
  ASK mode:    to the LLM as the wearer's question; the spoken answer comes back through TTS.
Missing keys fall back so the app always runs: no Deepgram key -> typed/scripted transcripts,
no OpenAI key -> rule answers from memory, no ElevenLabs key -> the Mac's `say` voice.
"""
from __future__ import annotations

import asyncio
import os
import logging
import shutil
import subprocess
import time

from pipecat.frames.frames import (
    EndFrame, ErrorFrame, Frame, InputAudioRawFrame, InterimTranscriptionFrame, LLMFullResponseEndFrame,
    LLMMessagesAppendFrame, LLMTextFrame, StartFrame, TranscriptionFrame, TTSAudioRawFrame,
    TTSSpeakFrame, TTSStoppedFrame, TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from . import config, memory

log = logging.getLogger("kin.voice")
import re as _re
FINE = _re.compile(r"\b(i'?m|i am|im)\s+(fine|ok(ay)?|alright|all right|good|not hurt)\b|\b(yes|yeah)\b.{0,12}\b(fine|ok(ay)?)\b|"
                   r"^\W*(fine|okay|ok|all good|i'?m good)\W*$", _re.I)
NOT_FINE = _re.compile(r"^\W*no\b|\bnot (fine|ok(ay)?|alright|all right|good)\b|\bhelp\b|\bi (fell|fall|can'?t get up)|"
                       r"\b(hurt|pain|bleeding|dizzy)\b|\bcall (someone|sarah|my|911|an ambulance)", _re.I)
STOP = _re.compile(r"^\W*(?:(?:okay|ok|kin|hey kin|i said|no)[\s,.]+)?(stop|stop it|stop talking|be quiet|quiet|shush|"
                   r"shut up|enough|that'?s enough|never ?mind|cancel|forget it)\b(?!\W+\w+\W+\w+\W+\w+\W+\w)|"
                   r"\bstop talking\b|\bbe quiet\b|\bshut up\b|\bnever ?mind\b(?=\W*$)", _re.I)
SAID_FELL = _re.compile(r"\bi(?:'ve| have| just)?\s*(fell|fallen|slipped|tripped|fell down|fell over)\b|\bi can'?t get up\b|"
                        r"\bi(?:'m| am) hurt\b|\bi hurt (my|myself)\b|\bi'?m on the floor\b", _re.I)
NEGATED_FELL = _re.compile(r"\b(didn'?t|did not|never|haven'?t)\s+(fall|fell|slip|trip)|\bi'?m not hurt\b|\bif i fall\b|"
                           r"\bfell (asleep|for|behind|in love|apart|off the wagon)\b", _re.I)
FILLER = _re.compile(r"^\W*(yeah|yes|yep|yup|okay|ok|mm+|hmm+|uh+|um+|uh huh|right|sure|alright|cool|wow|oh)\W*$", _re.I)


# --------------------------------------------------------------------------- audio in
class BandAudioSource(FrameProcessor):
    """First processor in the pipeline. The band handler calls `feed(pcm)` with 20 ms of
    16 kHz mono 16-bit sound; it becomes an InputAudioRawFrame for the STT."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._started = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self._started = True
        await self.push_frame(frame, direction)

    async def feed(self, pcm: bytes):
        if self._started:
            await self.push_frame(InputAudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1))


class TypedSTT(FrameProcessor):
    """Stand-in for Deepgram when there is no key: `say(speaker, text)` injects a final
    transcript, so everything after it (memory, ask mode, voice) works and can be tested."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if not isinstance(frame, InputAudioRawFrame):        # swallow audio, pass the rest
            await self.push_frame(frame, direction)

    async def say(self, speaker: str, text: str):
        f = TranscriptionFrame(text=text, user_id="band", timestamp=str(time.time()))
        f.result = {"kin_speaker": speaker}
        await self.push_frame(f)


def _keyterms() -> list[str]:
    """Words Deepgram should listen for: Kin, the wearer, and everyone Kin has met (names get misheard)."""
    words = ["Kin", config.WEARER_NAME.split()[-1]]
    try:
        from . import settings
        words += [p["name"] for p in settings.people()] + [c["name"] for c in settings.contacts()]
        words += [p["name"] for p in memory.people()[:40]]
    except Exception:
        pass
    seen, out = set(), []
    for w in words:
        if w and w.lower() not in seen:
            seen.add(w.lower()); out.append(w)
    return out[:50]


def make_stt():
    if config.DEEPGRAM_API_KEY:
        from pipecat.services.deepgram.stt import DeepgramSTTService
        from pipecat.transcriptions.language import Language
        # 16 kHz mono linear16 from the band. US English only. Endpointing 400 ms + utterance end 1 s: Deepgram's
        # default (~10 ms) cuts sentences at every tiny pause, and fragments are transcribed much worse.
        return DeepgramSTTService(
            api_key=config.DEEPGRAM_API_KEY, sample_rate=16000, encoding="linear16", channels=1, mip_opt_out=True,
            settings=DeepgramSTTService.Settings(
                model="nova-3", language=Language.EN_US, diarize=True, keyterm=_keyterms(),
                smart_format=True, punctuate=True, numerals=True, interim_results=True,
                endpointing=int(os.environ.get("KIN_ENDPOINTING_MS", "300")),
                utterance_end_ms=int(os.environ.get("KIN_UTTERANCE_END_MS", "1000"))),
        )
    log.warning("No Deepgram key: using typed transcripts (type lines in the terminal).")
    return TypedSTT()


# --------------------------------------------------------------------------- router
class KinRouter(FrameProcessor):
    """Sends finished sentences to memory (LISTEN) or to the LLM (ASK)."""

    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self._question: list[str] = []
        self._ask_timer: asyncio.Task | None = None
        self._last_q = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)) and STOP.search(frame.text or "") \
                and (self.app.speaking or self.app.mode == "ask"):
            await self.stop_talking()                        # "stop" / "be quiet" works even mid-sentence
            return
        if isinstance(frame, ErrorFrame) and direction == FrameDirection.UPSTREAM and self._last_q:
            q, self._last_q = self._last_q, ""               # the LLM failed: never leave the wearer hanging
            log.warning("LLM failed (%s); answering from memory.", str(frame.error)[:120])
            await self.speak(rule_answer(q))
            return
        if isinstance(frame, InterimTranscriptionFrame):
            if self.app.dashboard and frame.text.strip():   # live "hearing..." text for the test page
                self.app.dashboard.publish({"table": "interim", "row": {"text": frame.text.strip()}})
            if self.app.mode == "ask" and frame.text.strip() and self._ask_timer and not self._ask_timer.done():
                self._ask_timer.cancel()                     # they're still talking: don't answer half a question
                self._ask_timer = asyncio.create_task(self._ask_after_pause())
            return                                           # partial guesses: not stored
        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text and self.app.hearing_kin(text):
                return                                       # Kin's own voice coming back through the band
            if text:
                speaker, name = self._voice_of(frame)
                await self._on_sentence(speaker, text, name)
            return                                           # never let raw transcripts reach the LLM
        await self.push_frame(frame, direction)

    def _voice_of(self, frame: TranscriptionFrame) -> tuple[str, str]:
        if isinstance(frame.result, dict) and frame.result.get("kin_speaker"):
            return frame.result["kin_speaker"], ""
        return self.app.voice_label(getattr(frame, "speaker", None), frame.result)

    def _speaker_of(self, frame: TranscriptionFrame) -> str:
        if isinstance(frame.result, dict) and frame.result.get("kin_speaker"):
            return frame.result["kin_speaker"]
        return self.app.speaker_label(getattr(frame, "speaker", None), frame.result)

    async def _on_sentence(self, speaker: str, text: str, name: str = ""):
        from .app import WAKE, CLOSERS
        if STOP.search(text) and (self.app.speaking or self.app.mode == "ask"):
            await self.stop_talking()
            return
        woke = False                                         # "Hey Kin, ..." is always the wearer talking to Kin
        if speaker != "kin" and SAID_FELL.search(text) and not NEGATED_FELL.search(text) and not self.app.fall_check_active():
            await self.app.reported_fall(text)               # "I fell" -> the fall alert, not a generic one
            return
        if self.app.fall_check_active() and NOT_FINE.search(text):
            await self.app.fall_not_ok(text)                 # "no / I'm not fine / help": family alerted now
            return
        if self.app.fall_check_active() and FINE.search(text):
            await self.app.fall_ok("said they're fine")      # "I'm fine" answers the fall check, like a double-tap
            return
        if self.app._enrolling:                              # someone is reading their voice sample: not a
            return                                           # question, not a memory
        if self.app.mode != "ask" and speaker != "kin":
            m = WAKE.match(text)
            if m:                                            # "Hey Kin, where are my keys?"
                await self.app.heard(speaker, text, name)
                self.app.mode = "ask"
                self.app.new_conversation()
                asyncio.create_task(self.app.flush())       # save what was just heard first
                self.app._ask_started = time.time()
                self.app.publish_status(note="Listening for your question")
                woke = True
                rest = (m.group(1) or m.group(2) or "").strip()
                if rest:
                    text = rest
                else:
                    await self.app.say_yes()
                    return
        # Anyone may talk to Kin (family can say "Hey Kin, Joe needs to pick up his pills"): no voice filter here.
        if self.app.mode == "ask":
            if FILLER.match(text) and not self._question:
                return                                       # "yeah" / "okay" / "mm" on its own isn't a question
            if CLOSERS.search(text) and len(text.split()) <= 6:
                self.app._closing = True                     # "thank you" -> "you're welcome", then stop
            self._question.append(text)                      # whoever speaks after the double-tap is asking
            if self._ask_timer:
                self._ask_timer.cancel()
            self._ask_timer = asyncio.create_task(self._ask_after_pause())
        else:
            await self.app.heard(speaker, text, name)

    async def _ask_after_pause(self):
        await asyncio.sleep(self.app.ask_pause)
        q = " ".join(self._question).strip()
        self._question = []
        if q:
            await self.ask(q)

    async def ask(self, question: str):
        log.info("ASK: %s", question)
        await self.app.heard("wearer", question, config.WEARER_NAME)   # also remembered (e.g. "I left my keys...")
        self.app.flag_money(question)                        # "should I send my son $5,000?" -> family alert
        self.app.publish_status(note=f"Question: {question}")
        if config.OPENAI_API_KEY:
            self._last_q = question
            si = self.app.refresh_system_prompt()
            if si and self.app.llm is not None:
                from pipecat.frames.frames import LLMUpdateSettingsFrame
                await self.push_frame(LLMUpdateSettingsFrame(
                    delta=type(self.app.llm).Settings(system_instruction=si), service=self.app.llm))
            await self.push_frame(LLMMessagesAppendFrame(
                messages=[{"role": "user", "content": question}], run_llm=True))
        else:
            await self.speak(rule_answer(question))

    async def stop_talking(self):
        """Cut Kin off right now and go back to quietly listening."""
        log.info("Stopped by the wearer")
        self._question = []
        if self._ask_timer:
            self._ask_timer.cancel()
        self._last_q = ""
        from pipecat.frames.frames import InterruptionFrame
        await self.push_frame(InterruptionFrame())          # LLM + TTS drop what they were doing
        self.app.speaker_stop()
        self.app.mode = "listen"
        self.app.speaking = False
        self.app._spoke_at = time.time()
        self.app.publish_status(note="Stopped")

    async def speak(self, text: str):
        """Say something without the LLM (fall check, scam warning, rule answers)."""
        self.app._saying = text                              # so its echo through the band can be recognised
        self.app.speaking = True
        self.app._spoke_at = time.time()
        await self.push_frame(TTSSpeakFrame(text))


def last_other_person(seconds: float = 1800) -> dict | None:
    """The most recent known person (not the wearer, not Kin) heard in the last half hour."""
    for l in reversed(memory.recent_lines(seconds)):
        if l["speaker"] in ("wearer", "kin", ""):
            continue
        p = memory.person_by_speaker(l["speaker"]) or (memory.find_person(l["name"]) if l["name"] else None)
        if p:
            return p
    return None


def rule_answer(q: str) -> str:
    """Answers from memory without an LLM, for when there is no OpenAI key."""
    import re
    ql = q.lower()
    m = re.search(r"where (?:are|is|did i (?:put|leave)) (?:my |the )?([a-z ]+?)\??$", ql)
    if m:
        from .vision import where_is
        it = where_is(m.group(1).strip())
        return (f"Your {it['item']} {'are' if it['item'].endswith('s') else 'is'} {it['location']}."
                if it else f"I haven't seen where your {m.group(1)} went yet.")
    if "who" in ql:
        p = last_other_person() or \
            next((memory.find_person(w) for w in re.findall(r"[A-Z][a-z]+", q) if memory.find_person(w)), None)
        if p:
            fact = p["facts"][0]["text"].split(": ", 1)[-1] if p["facts"] else ""
            rel = f", your {p['relationship']}" if p["relationship"] and p["relationship"] != "child" else \
                  (", your child" if p["relationship"] == "child" else "")
            return f"That's {p['name']}{rel}." + (f" Last time: {fact}" if fact else "")
        return "I'm not sure who that is yet."
    if "todo" in ql or "to do" in ql or "plan" in ql or "remember" in ql:
        ts = memory.todos()
        return ("You planned to: " + "; ".join(t["text"] for t in ts[:3]) + ".") if ts else "You have nothing planned."
    return "I'm here. You can ask me who someone is, where you put something, or what you planned."


# --------------------------------------------------------------------------- LLM + tools
SYSTEM = """You are Kin, a warm, calm companion living in a wristband worn by {wearer}, who has early memory loss.
The person talking to you is {wearer}: that is their name, always. It is now {now}.

How to answer:
- You speak out loud: usually ONE short sentence, at most two. No lists, no markdown. Don't say their name.
- If they ask you to stop doing something (e.g. a phrase or habit), stop for the rest of the conversation.
- Use everything in "What you remember" below, including the recent conversation, to understand short or unfinished
  questions ("and her?", "what about the pills", "where did I put them") and follow-ups.
- "Who was here / who did I see today?": name everyone heard today, most recent first, with one detail each.
- Never invent names, places or facts. If memory doesn't have it, say so kindly and offer what you do know.
- Answer only the latest question; don't repeat earlier answers. Thanks or goodbye: reply warmly in a few words.
- If something isn't a question, respond naturally and briefly, like a kind friend would.
- If they're frustrated with you ("why can't you hear me?"), apologise briefly and ask them to say it again closer
  to the band. That is NOT confusion: no family alert.
- If, in what they say RIGHT NOW, they sound confused, lost, unwell or frightened ("where am I?", "I feel dizzy",
  "I don't know what's happening"): stay calm and reassuring, tell them who they are and something familiar from
  today, suggest sitting down, and use alert_family. Never use alert_family because of earlier alerts or falls -
  those were already handled.
- If they say they're fine or that they didn't fall, believe them, say something warm and move on. Don't bring up
  past alerts or tell them to stay seated unless they say they're hurt.
- If they feel lonely or sad: be warm, mention someone who cares (from memory), offer to remind them to call.
- Money: you never buy or send anything. If someone asked them for money (even family) or they ask whether to send
  money, kindly tell them not to send anything until they've called that person back on a number they already
  know, or checked with family. Never help with gift cards, wire transfers or giving out card numbers.
- When they say they've done a to-do, mark it done with complete_todo.
- If they ask you to tell or message someone, use send_message (only that: it already alerts them), then confirm in a
  few words ("Sent to Abigail.") and, if they're lost or scared, reassure them calmly.
- When they TELL you something (where they put things, plans, news), it is saved automatically: just confirm
  briefly ("Got it, AirPods on the table."). Don't say you have no note of something they just told you.

What you remember:
{memory}"""


def make_llm_parts(app):
    """Returns (llm, context_pair) or (None, None) without an OpenAI key."""
    if not config.OPENAI_API_KEY:
        log.warning("No OpenAI key: ask mode answers from memory with simple rules.")
        return None, None
    from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from pipecat.services.openai.llm import OpenAILLMService

    # gpt-6 models refuse tool calls on chat completions unless reasoning is off; it's also faster.
    llm = OpenAILLMService(api_key=config.OPENAI_API_KEY,
                           settings=OpenAILLMService.Settings(model=config.OPENAI_MODEL,
                                                              system_instruction=system_prompt(),
                                                              extra={"reasoning_effort": "none"}))

    async def who_is(params):
        name = params.arguments.get("name", "")
        p = memory.find_person(name) if name else None
        await params.result_callback(p or last_other_person() or {"unknown": True})

    async def find_item(params):
        from .vision import where_is
        await params.result_callback(where_is(params.arguments["item"]) or {"not_seen": True})

    async def get_todos(params):
        await params.result_callback({"todos": memory.todos()})

    async def remember(params):
        memory.add_fact(params.arguments["text"], None, "wearer_note", 3)
        await params.result_callback({"saved": True})

    async def set_speech_speed(params):
        from . import settings
        from pipecat.frames.frames import TTSUpdateSettingsFrame
        how = (params.arguments.get("change") or "").lower()
        cur = settings.speed()
        new = 1.0 if how == "normal" else cur - 0.15 if how == "slower" else cur + 0.1 if how == "faster" else cur
        new = settings.set_speed(new)
        tts = app.tts
        if isinstance(tts, SayTTS):
            tts.speed = new
        elif hasattr(type(tts), "Settings"):
            await params.llm.push_frame(TTSUpdateSettingsFrame(delta=type(tts).Settings(speed=new)))
        await params.result_callback({"speed": new, "range": "0.7 (slowest) to 1.2 (fastest)"})

    async def send_message(params):
        """'Tell Abigail I don't know where I am' -> a push notification to that emergency contact."""
        from . import notify, settings
        a = params.arguments
        to = (a.get("to") or "").strip().lower()
        text = (a.get("message") or "").strip()[:240]
        urgent = bool(a.get("urgent"))
        contacts = settings.contacts()
        pick = [c for c in contacts if to and (to in c["name"].lower() or to in (c.get("relationship") or "").lower())]
        targets = pick or contacts
        if not targets or not text:
            await params.result_callback({"sent": False, "reason": "no emergency contacts are set up" if not targets
                                          else "empty message"})
            return
        title = f"Message from {config.WEARER_NAME}" + (" (needs help)" if urgent else "")
        ok = await asyncio.to_thread(notify.send, title, text, 5 if urgent else 3,
                                     "sos" if urgent else "speech_balloon", [c["topic"] for c in targets])
        app._message_sent_at = time.time()                  # the message itself is the family alert: no second push
        memory.add_alert("message",
                         f"{config.WEARER_NAME} sent a message to {', '.join(c['name'] for c in targets)}: {text}")
        await params.result_callback({"sent": ok, "to": [c["name"] for c in targets]})

    async def alert_family(params):
        if time.time() - getattr(app, "_message_sent_at", 0) < 60:
            await params.result_callback({"family_alerted": True, "note": "they already got his message"})
            return
        reason = (params.arguments.get("reason") or "He may need help.")[:200]
        memory.add_alert("confused", f"{config.WEARER_NAME} sounded confused or unwell: {reason}")
        await params.result_callback({"family_alerted": True})

    async def complete_todo(params):
        words = params.arguments.get("text", "").lower()
        done = []
        for t in memory.todos():
            if words and (words in t["text"].lower() or any(w in t["text"].lower() for w in words.split() if len(w) > 3)):
                memory.finish_todo(t["id"])
                done.append(t["text"])
        await params.result_callback({"done": done} if done else {"not_found": True})

    tools = [
        FunctionSchema("who_is", "Who a person is, by name; with no name, who the wearer is talking to now.",
                       {"name": {"type": "string"}}, [], handler=who_is),
        FunctionSchema("find_item", "Where the wearer last put an item (keys, glasses, wallet...).",
                       {"item": {"type": "string"}}, ["item"], handler=find_item),
        FunctionSchema("get_todos", "The wearer's open plans and to-dos.", {}, [], handler=get_todos),
        FunctionSchema("remember", "Save something the wearer explicitly asks you to remember.",
                       {"text": {"type": "string"}}, ["text"], handler=remember),
        FunctionSchema("set_speech_speed", "Change how fast Kin talks when they ask (slower, faster, or normal).",
                       {"change": {"type": "string", "enum": ["slower", "faster", "normal"]}}, ["change"],
                       handler=set_speech_speed),
        FunctionSchema("send_message", "Send a short message from the wearer to an emergency contact's phone when they "
                       "ask ('tell Abigail I'm running late', 'tell her I don't know where I am'). Write it in first "
                       "person as the wearer would. urgent=true if it shows they need help (lost, hurt, scared).",
                       {"to": {"type": "string", "description": "contact name or relationship; empty = everyone"},
                        "message": {"type": "string"}, "urgent": {"type": "boolean"}}, ["message"],
                       handler=send_message),
        FunctionSchema("alert_family", "Quietly let the family know he may need help, ONLY when what he says right "
                       "now shows he is disoriented (doesn't know where he is, what day it is, who someone is), unwell "
                       "or frightened. Never for frustration with Kin or the device ('why can't you hear me?'), never "
                       "because of earlier alerts or falls, never when he says he's fine.",
                       {"reason": {"type": "string"}}, ["reason"], handler=alert_family),
        FunctionSchema("complete_todo", "Mark one of the wearer's to-dos as done when they say they did it.",
                       {"text": {"type": "string", "description": "words from the to-do"}}, ["text"],
                       handler=complete_todo),
    ]
    context = LLMContext(messages=[], tools=tools)
    return llm, LLMContextAggregatorPair(context)


def system_prompt() -> str:
    now = time.strftime("%A, %B %-d, %Y, %-I:%M %p")
    return SYSTEM.format(wearer=config.WEARER_NAME, now=now, memory=memory.summary_for_llm())


# --------------------------------------------------------------------------- voice out
def synth_pcm(text: str) -> bytes | None:
    """Pre-render a short phrase (e.g. "Yes?") as 24 kHz 16-bit mono PCM in Kin's current voice, so it can be
    played instantly instead of waiting ~2-4 s for streaming TTS. None if it can't be made."""
    want = os.environ.get("KIN_VOICE", "").lower()
    try:
        if config.ELEVENLABS_API_KEY and want in ("", "elevenlabs"):
            import json as _json, urllib.request as _u
            req = _u.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}"
                             "?output_format=pcm_24000", method="POST",
                             data=_json.dumps({"text": text, "model_id": "eleven_flash_v2_5"}).encode(),
                             headers={"xi-api-key": config.ELEVENLABS_API_KEY, "Content-Type": "application/json"})
            with _u.urlopen(req, timeout=10) as r:
                return r.read()
        if config.OPENAI_API_KEY and want in ("", "openai", "elevenlabs"):
            from openai import OpenAI
            r = OpenAI(api_key=config.OPENAI_API_KEY, timeout=10).audio.speech.create(
                model="gpt-4o-mini-tts", voice=os.environ.get("KIN_OPENAI_VOICE", "sage"), input=text,
                response_format="pcm", instructions="Warm, calm, gentle.")
            return r.read() if hasattr(r, "read") else r.content
    except Exception as e:
        log.info("could not pre-render %r: %s", text, e)
    return None


def _saved_speed() -> float:
    try:
        from . import settings
        return settings.speed()
    except Exception:
        return 1.0


def make_tts():
    """Voice choice: KIN_VOICE=elevenlabs|openai|say forces one (tests use 'say' so they never spend
    ElevenLabs characters); otherwise ElevenLabs if there's a key, then OpenAI, then the Mac voice."""
    want = os.environ.get("KIN_VOICE", "").lower()
    if want == "say":
        return SayTTS()
    if config.ELEVENLABS_API_KEY and want in ("", "elevenlabs"):
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
        return ElevenLabsTTSService(api_key=config.ELEVENLABS_API_KEY,
                                    settings=ElevenLabsTTSService.Settings(voice=config.ELEVENLABS_VOICE_ID,
                                                                           speed=_saved_speed()))
    if config.OPENAI_API_KEY and want in ("", "openai", "elevenlabs"):
        from pipecat.services.openai.tts import OpenAITTSService
        log.info("Voice: OpenAI text-to-speech%s", " (KIN_VOICE=openai: saving ElevenLabs characters)" if want == "openai" else " (no ElevenLabs key)")
        return OpenAITTSService(api_key=config.OPENAI_API_KEY, settings=OpenAITTSService.Settings(
            voice=os.environ.get("KIN_OPENAI_VOICE", "sage"), speed=_saved_speed(),
            instructions="Speak warmly, slowly and calmly, like a kind friend talking to an older person."))
    log.warning("No ElevenLabs or OpenAI key: using the Mac's built-in voice.")
    return SayTTS()


class SayTTS(FrameProcessor):
    """Fallback voice: collects the LLM's words (or a TTSSpeakFrame) and speaks them with `say`."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._buf: list[str] = []
        self.spoken: list[str] = []                     # for tests

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame):
            self._buf.append(frame.text)
        elif isinstance(frame, TTSSpeakFrame):
            await self._say(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            text = "".join(self._buf).strip()
            self._buf = []
            if text:
                await self._say(text)
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)

    async def _say(self, text: str):
        log.info("KIN SAYS: %s", text)
        self.spoken.append(text)
        memory.add_line("kin", text, name="Kin")
        if shutil.which("say") and not getattr(self, "mute", False):
            rate = str(int(185 * getattr(self, "speed", _saved_speed())))
            self._proc = subprocess.Popen(["say", "-r", rate, text])
            await asyncio.to_thread(self._proc.wait)
        await self.push_frame(TTSStoppedFrame())


class Speaker(FrameProcessor):
    """Plays TTS audio on the laptop speakers (the band has no speaker) and tells the app
    when Kin has finished talking."""

    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self._stream = None
        self._said: list[str] = []
        self.audio_bytes = 0                              # for tests: how much sound was played

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            self.app.speaking = True
            self.audio_bytes += len(frame.audio)
            await asyncio.to_thread(self._play, frame)
        elif isinstance(frame, TTSTextFrame):             # what the TTS actually spoke
            self._said.append(frame.text)
            self.app._saying = " ".join(self._said)
        if isinstance(frame, (TTSStoppedFrame,)):
            text = " ".join(t.strip() for t in self._said if t.strip()).replace(" ,", ",").replace(" .", ".")
            self._said = []
            if text and not isinstance(self.app.tts, SayTTS):
                log.info("KIN SAYS: %s", text)
                memory.add_line("kin", text, name="Kin")
            self.app.done_speaking()
        await self.push_frame(frame, direction)

    def play_pcm(self, pcm: bytes, rate: int = 24000):
        """Play pre-rendered audio right away (blocking; call from a thread)."""
        from types import SimpleNamespace
        self._play(SimpleNamespace(audio=pcm, sample_rate=rate, num_channels=1))

    def stop(self):
        """Silence now: abort whatever audio is still buffered."""
        st, self._stream = self._stream, None
        self._said = []
        if st is not None:
            try:
                st.abort(); st.close()
            except Exception:
                pass

    def _play(self, frame: TTSAudioRawFrame):
        try:
            import sounddevice as sd
            if self._stream is None or self._stream.samplerate != frame.sample_rate:
                # latency="high": a bigger buffer, so gaps between streamed chunks don't underrun and
                # pop ("poom") - very audible on Bluetooth earbuds. A short silent lead-in for the same reason.
                self._stream = sd.RawOutputStream(samplerate=frame.sample_rate, channels=frame.num_channels,
                                                  dtype="int16", latency="high")
                self._stream.start()
                self._stream.write(b"\x00\x00" * int(frame.sample_rate * 0.15) * frame.num_channels)
            self._stream.write(frame.audio)
        except Exception as e:
            log.warning("Could not play audio: %s", e)


async def end(task):
    await task.queue_frame(EndFrame())
