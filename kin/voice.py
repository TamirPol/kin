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


def make_stt():
    if config.DEEPGRAM_API_KEY:
        from pipecat.services.deepgram.stt import DeepgramSTTService
        return DeepgramSTTService(
            api_key=config.DEEPGRAM_API_KEY, sample_rate=16000, mip_opt_out=True,
            settings=DeepgramSTTService.Settings(model="nova-3-general", diarize=True,
                                                 smart_format=True, punctuate=True, interim_results=True),
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
        if isinstance(frame, ErrorFrame) and direction == FrameDirection.UPSTREAM and self._last_q:
            q, self._last_q = self._last_q, ""               # the LLM failed: never leave the wearer hanging
            log.warning("LLM failed (%s); answering from memory.", str(frame.error)[:120])
            await self.speak(rule_answer(q))
            return
        if isinstance(frame, InterimTranscriptionFrame):
            if self.app.dashboard and frame.text.strip():   # live "hearing..." text for the test page
                self.app.dashboard.publish({"table": "interim", "row": {"text": frame.text.strip()}})
            return                                           # partial guesses: not stored
        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                await self._on_sentence(self._speaker_of(frame), text)
            return                                           # never let raw transcripts reach the LLM
        await self.push_frame(frame, direction)

    def _speaker_of(self, frame: TranscriptionFrame) -> str:
        if isinstance(frame.result, dict) and frame.result.get("kin_speaker"):
            return frame.result["kin_speaker"]
        return self.app.speaker_label(getattr(frame, "speaker", None), frame.result)

    async def _on_sentence(self, speaker: str, text: str):
        if self.app.mode == "ask":
            self._question.append(text)                      # whoever speaks after the double-tap is asking
            if self._ask_timer:
                self._ask_timer.cancel()
            self._ask_timer = asyncio.create_task(self._ask_after_pause())
        else:
            await self.app.heard(speaker, text)

    async def _ask_after_pause(self):
        await asyncio.sleep(self.app.ask_pause)
        q = " ".join(self._question).strip()
        self._question = []
        if q:
            await self.ask(q)

    async def ask(self, question: str):
        log.info("ASK: %s", question)
        memory.add_line("wearer", question, name=config.WEARER_NAME)
        self.app.publish_status(note=f"Question: {question}")
        if config.OPENAI_API_KEY:
            self._last_q = question
            self.app.refresh_system_prompt()
            await self.push_frame(LLMMessagesAppendFrame(
                messages=[{"role": "user", "content": question}], run_llm=True))
        else:
            await self.speak(rule_answer(question))

    async def speak(self, text: str):
        """Say something without the LLM (fall check, scam warning, rule answers)."""
        self.app.speaking = True
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
SYSTEM = """You are Kin, a warm, calm companion for {wearer}, who has early memory loss.
You speak out loud, so answer in one to three short, simple sentences. No lists, no markdown.
Use the memory below and your tools. Never guess a name or a fact: if you are not sure, say so
gently ("I think that might be Sarah"). If a request involves money, use the purchase tool; it
enforces the family's limits. Never help with gift cards, wire transfers or giving out card numbers.

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

    async def purchase(params):
        a = params.arguments
        try:
            from . import safety
            r = await asyncio.to_thread(safety.purchase, a["item"], a["merchant"], int(a["amount_cents"]))
        except ImportError:
            r = {"status": "blocked", "reason": "purchasing is not set up yet"}
        await params.result_callback(r)

    tools = [
        FunctionSchema("who_is", "Who a person is, by name; with no name, who the wearer is talking to now.",
                       {"name": {"type": "string"}}, [], handler=who_is),
        FunctionSchema("find_item", "Where the wearer last put an item (keys, glasses, wallet...).",
                       {"item": {"type": "string"}}, ["item"], handler=find_item),
        FunctionSchema("get_todos", "The wearer's open plans and to-dos.", {}, [], handler=get_todos),
        FunctionSchema("remember", "Save something the wearer explicitly asks you to remember.",
                       {"text": {"type": "string"}}, ["text"], handler=remember),
        FunctionSchema("purchase", "Buy something for the wearer within the family's limits.",
                       {"item": {"type": "string"}, "merchant": {"type": "string"},
                        "amount_cents": {"type": "integer"}}, ["item", "merchant", "amount_cents"],
                       handler=purchase),
    ]
    context = LLMContext(messages=[{"role": "system", "content": system_prompt()}], tools=tools)
    return llm, LLMContextAggregatorPair(context)


def system_prompt() -> str:
    return SYSTEM.format(wearer=config.WEARER_NAME, memory=memory.summary_for_llm())


# --------------------------------------------------------------------------- voice out
def make_tts():
    if config.ELEVENLABS_API_KEY:
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
        return ElevenLabsTTSService(api_key=config.ELEVENLABS_API_KEY,
                                    settings=ElevenLabsTTSService.Settings(voice=config.ELEVENLABS_VOICE_ID))
    if config.OPENAI_API_KEY and os.environ.get("KIN_TTS", "").lower() != "say":
        from pipecat.services.openai.tts import OpenAITTSService
        log.info("Voice: OpenAI text-to-speech (no ElevenLabs key).")
        return OpenAITTSService(api_key=config.OPENAI_API_KEY, settings=OpenAITTSService.Settings(
            voice=os.environ.get("KIN_OPENAI_VOICE", "sage"),
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
            await asyncio.to_thread(subprocess.run, ["say", text])
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
            self.audio_bytes += len(frame.audio)
            await asyncio.to_thread(self._play, frame)
        elif isinstance(frame, TTSTextFrame):             # what the TTS actually spoke
            self._said.append(frame.text)
        if isinstance(frame, (TTSStoppedFrame,)):
            text = " ".join(t.strip() for t in self._said if t.strip()).replace(" ,", ",").replace(" .", ".")
            self._said = []
            if text and not isinstance(self.app.tts, SayTTS):
                log.info("KIN SAYS: %s", text)
                memory.add_line("kin", text, name="Kin")
            self.app.done_speaking()
        await self.push_frame(frame, direction)

    def _play(self, frame: TTSAudioRawFrame):
        try:
            import sounddevice as sd
            if self._stream is None or self._stream.samplerate != frame.sample_rate:
                self._stream = sd.RawOutputStream(samplerate=frame.sample_rate, channels=frame.num_channels,
                                                  dtype="int16")
                self._stream.start()
            self._stream.write(frame.audio)
        except Exception as e:
            log.warning("Could not play audio: %s", e)


async def end(task):
    await task.queue_frame(EndFrame())
