"""Kin: the main program. Connects the Vexo band, runs the Pipecat pipeline, and ties
memory, safety, the dashboard and vision together.

    python -m kin.app            # real band (number from KIN_BAND in .env, or --band 42)
    python -m kin.app --sim      # pretend band, no hardware
    python -m kin.app --demo     # pretend band + a scripted demo conversation

Band gestures:  double-tap = ask Kin (or "I'm fine" during a fall check)
                free-fall  = fall check ("Are you okay?")
Terminal keys (handy without a band or a Deepgram key):
    t              pretend double-tap      r  remind me now      away / home  band leaves / returns
    f              pretend fall
    a <question>   ask Kin directly
    1 <text>       say <text> as "speaker 1" (w <text> = as the wearer)
    s              show memory          q  quit
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import statistics
import sys
import time
from collections import deque

from . import brain, config, memory
from . import voice

sys.path.insert(0, str(config.KIT / "python"))
from vexo_open import Band                                   # noqa: E402  (the kit's async library)

log = logging.getLogger("kin")

CHUNK_PAUSE = 6.0          # seconds of quiet that end a conversation chunk
CHUNK_MAX = 30.0           # digest at least this often while people keep talking
WEARER_MARGIN_DB = 4.0     # the wearer's voice must be this much louder (median) than the next voice
IMPACT_G = float(__import__("os").environ.get("KIN_IMPACT_G", "3.0"))     # a jolt this hard may be a fall
DIP_G = float(__import__("os").environ.get("KIN_DIP_G", "0.6"))           # ...if just before it the wrist dropped (low g)
STILL_AFTER = float(__import__("os").environ.get("KIN_STILL_AFTER", "0.3"))  # avg |g-1| after it: lying still
FALL_WAIT = 10.0           # seconds to answer the fall check, counted after Kin has asked
REMIND_AFTER = float(__import__("os").environ.get("KIN_REMIND_AFTER", "600"))  # remind of a to-do this long after it was made
REMIND_QUIET = 20.0        # only remind when nobody has spoken for this long
REMIND_MIN_AGE = float(__import__("os").environ.get("KIN_REMIND_MIN_AGE", "600"))  # never remind about something just said
WANDER_RSSI = -88          # dBm: weaker than this means the band is far from the laptop/base
WANDER_SECONDS = float(__import__("os").environ.get("KIN_WANDER_SECONDS", "10"))  # weak signal this long -> alert (link lost: 3x)
WEARER_MATCH = float(__import__("os").environ.get("KIN_WEARER_MATCH", "0.3"))  # voiceprint score that means "the wearer"
CONVO_WINDOW = 9.0         # after Kin answers, keep listening this long for a follow-up
WAKE = __import__("re").compile(r"^\W*(?:(?:hey|hi|okay|ok|hello)[\s,]+)?(?:kin|ken|kim|kinn|kenn|kin's)\b[\s,.!?]*(.*)$|^\W*(?:hicken|hikin|hikken|heykin|heyken|hey-kin|a kin|ay kin)\b[\s,.!?]*(.*)$", __import__("re").I)
CLOSERS = __import__("re").compile(r"\b(thank you|thanks|thank u|bye|goodbye|that'?s all|that'?s it|never ?mind|ok(?:ay)? cool|got it)\b", __import__("re").I)
DUE_NOW = ("today", "tonight", "this morning", "this afternoon", "this evening", "now", "soon")


class Kin:
    def __init__(self, args):
        self.args = args
        self.mode = "listen"
        self.speaking = False
        self.ask_pause = 1.2          # quiet that ends a question (reset while Deepgram still hears words)
        self.has_diarization = bool(config.DEEPGRAM_API_KEY)
        self.band = None
        self.band_state = "disconnected"
        self._levels: deque = deque(maxlen=150)               # (time, dB) for the last 3 s
        self._speaker_db: dict[str, list[float]] = {}
        self._last_wearer: str | None = None
        self._wearer_dg, self._wearer_dg_t = "", 0.0   # Deepgram label of the last wearer sentence
        self._dg_decision: dict[str, tuple[str, str]] = {}   # Deepgram label -> last confident (speaker, name)
        self._pkt_db: list[float] = []
        self._pkt_pcm: list[bytes] = []
        self._dg_voice: dict[str, dict] = {}      # Deepgram label -> last voiceprint match (this session)
        self._wearer_votes: dict[str, int] = {}
        self._enrolling = None                    # (name, role, until) while onboarding a voice
        self._enroll_buf: list[bytes] = []
        self._last_tap = 0.0
        self._ask_started = 0.0
        self._motion: deque = deque(maxlen=400)   # (time, |acceleration| in g) for impact detection
        self._closing = False                     # the wearer said thanks/bye: end after this answer
        self.answered_once = False                # in this conversation: later turns must sound like the wearer
        self._chunk: list[dict] = []
        self._chunk_started = 0.0
        self._last_heard = 0.0
        self._fall_task: asyncio.Task | None = None
        self._decoder = None
        self.dashboard = None
        self.vision = None
        self._reminded: set[int] = set()
        self._far_since = 0.0
        self._lost_since = 0.0
        self._wander_alerted = False

    # ------------------------------------------------------------------ pipeline
    async def build(self):
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.worker import PipelineParams, PipelineWorker

        self.source = voice.BandAudioSource()
        self.stt = voice.make_stt()
        self.router = voice.KinRouter(self)
        self.llm, self.ctx = voice.make_llm_parts(self)
        self.tts = voice.make_tts()
        self.speaker = voice.Speaker(self)
        parts = [self.source, self.stt, self.router]
        if self.llm:
            parts += [self.ctx.user(), self.llm]
        parts += [self.tts, self.speaker]
        if self.llm:
            parts.append(self.ctx.assistant())
        self.task = PipelineWorker(Pipeline(parts),
                                 params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
                                 cancel_on_idle_timeout=False, cancel_runner_on_idle_timeout=False,
                                 idle_timeout_secs=None)

    def knows_wearer_voice(self) -> bool:
        try:
            from . import voiceprint
            return bool(voiceprint.wearer())
        except Exception:
            return False

    def new_conversation(self):
        """A fresh conversation: forget earlier Q&A (stale answers make the AI repeat its own mistakes).
        Recent talk is still in the system prompt's memory, so follow-ups keep their context."""
        self.answered_once = False
        if self.ctx:
            try:
                self.ctx.user().context.set_messages([])
            except Exception as e:
                log.warning("could not reset the conversation: %s", e)

    def refresh_system_prompt(self):
        if self.llm:                             # fresh memory in the system prompt before each question
            # Pipecat rebuilds the instruction from its *base* copy whenever Kin speaks, so update the base
            # (the KinRouter also sends an official LLMUpdateSettingsFrame right before the question)
            si = voice.system_prompt()
            self.llm._settings.system_instruction = si
            if hasattr(self.llm, "_base_system_instruction"):
                self.llm._base_system_instruction = si
                try:
                    self.llm._compose_system_instruction()
                except Exception:
                    pass
            return si

    # ------------------------------------------------------------------ band
    async def connect_band(self):
        kw = {}
        self.sim = None
        if self.args.sim or self.args.demo:
            from vexo_open.transports.sim import SimTransport
            packets = None
            if self.args.replay:
                from vexo_open import audio
                packets = audio.ogg_packets(self.args.replay)
            # auto_tap=False: the pretend band only taps when we say so ('t' / 'f' in the terminal)
            self.sim = SimTransport(self.args.band, auto_tap=False, audio_packets=packets)
            kw["transport"] = self.sim
        try:
            tries = 12 if os.environ.get("KIN_RELOAD") and not self.sim else 1
            for attempt in range(tries):
                try:
                    self.band = await Band.connect(self.args.band, auto_reconnect=not (self.args.sim or self.args.demo), **kw)
                    break
                except Exception as e:
                    if attempt == tries - 1:
                        raise
                    log.info("Looking for band %s… (double-tap it if this takes long)", self.args.band)
                    self.publish_status(note="Looking for the band… double-tap it")
                    await asyncio.sleep(3)
        except Exception as e:
            log.error("Could not connect to band %s: %s", self.args.band, e)
            self.band_state = "disconnected"
            self.publish_status(note=f"Band not connected: {e}")
            return
        log.info("Connected to %s (%s)", self.band.name, "sim" if self.sim else "connected")
        await self._setup_band()

    async def _setup_band(self):
        self.band_state = "sim" if self.sim else "connected"
        try:
            from vexo_open.audio import PcmDecoder
            self._decoder = PcmDecoder()
        except Exception as e:
            log.warning("No Opus decoder (pip install av): %s", e)
        self.band.on("audio", self._on_audio)
        self.band.on("double-tap", self._on_double_tap)
        self.band.on("tap", self._on_tap)              # two quick single taps also count (fabric muffles taps)
        self.band.on("free-fall", self._on_fall)
        self.band.on("disconnect", self._on_disconnect)
        self.band.on("reconnected", lambda e: self._set_band("connected"))
        self.band.on("reconnecting", self._on_reconnecting)
        self.band.on("link", self._on_link)
        # a firmer tap threshold (default 0.8 g) so walking and gesturing don't count as double-taps
        await self.band.set_events(kinds=["tap", "double-tap", "free-fall"], tap_threshold=float(os.environ.get("KIN_TAP_G", "1.1")))
        try:                                                   # +20 dB (max, the default) clips in a loud room
            await self.band.set_mic_gain(float(os.environ.get("KIN_MIC_GAIN", "14")))
        except Exception as e:
            log.info("mic gain unchanged: %s", e)
        await self.band.configure(audio=True, events=True)     # light goes solid blue: mic is on
        try:                                                   # impact-based fall detection: accelerometer 50 Hz,
            await self.band.set_motion(accel_range=8)          # 8 g range (the default 2 g clips every impact)
            await self.band.configure(motion=50, sensors="accel")
            self.band.on("motion", self._on_motion)
        except Exception as e:
            log.info("No motion stream (falls use the band's free-fall event only): %s", e)
        if self.band.transport_kind in ("ble", "sim"):
            try:
                await self.band.configure(link=True)           # signal strength once a second (wander alert)
            except Exception as e:
                log.info("No signal strength on this link: %s", e)
        self.publish_status()

    def _set_band(self, s):
        self.band_state = s
        if s == "connected":
            if self._lost_since:
                log.info("Band is back in range after %.0f s", time.time() - self._lost_since)
            self._lost_since, self._far_since, self._wander_alerted = 0.0, 0.0, False
        self.publish_status()

    def _on_reconnecting(self, e=None):
        """The link dropped (out of range?): the kit is trying to get it back for 2 minutes."""
        self.band_state = "reconnecting"
        self._lost_since = self._lost_since or time.time()
        log.warning("Band link lost: out of range? Reconnecting…")
        self.publish_status(note="Band out of range: reconnecting")

    def _on_disconnect(self, e=None):
        self._set_band("disconnected")
        if getattr(e, "reason", "") == "lost" and not self._lost_since:
            self._lost_since = time.time()

    # ------------------------------------------------------------------ wander alert
    def _on_link(self, e):
        rssi = getattr(e, "rssi", None)
        if rssi is None:
            return
        now = time.time()
        if rssi < WANDER_RSSI:
            self._far_since = self._far_since or now
        else:
            self._far_since = 0.0
            self._wander_alerted = False

    async def reconnect_loop(self):
        """If the band stays gone past its own 2-minute auto-reconnect, keep looking for it."""
        while True:
            await asyncio.sleep(5)
            if self.sim or self.band_state != "disconnected" or (self.band and getattr(self.band, "reconnecting", False)):
                continue
            try:
                kw = {}
                self.band = await Band.connect(self.args.band, auto_reconnect=True, **kw)
            except Exception:
                self.publish_status(note="Band out of range: double-tap it when back")
                continue
            log.info("Band is back: reconnected to %s", self.band.name)
            self._lost_since, self._far_since, self._wander_alerted = 0.0, 0.0, False
            await self._setup_band()

    async def wander_loop(self):
        while True:
            await asyncio.sleep(1)
            now = time.time()
            far = self._far_since and now - self._far_since > WANDER_SECONDS
            gone = self._lost_since and now - self._lost_since > WANDER_SECONDS * 3
            if (far or gone) and not self._wander_alerted:
                self._wander_alerted = True
                why = "has lost touch with the band" if gone else "the band is far from home base"
                memory.add_alert("wander", f"{config.WEARER_NAME} may have wandered off: {why}.")
                self.publish_status(note="Wander alert sent to family")
                log.warning("WANDER: %s", why)

    # ------------------------------------------------------------------ proactive reminders
    def _due_todo(self, force: bool = False) -> dict | None:
        now = time.time()
        for t in memory.todos():
            if t["id"] in self._reminded or (t.get("reminded") or 0) > 0:
                continue
            due = (t["due"] or "").lower()
            if any(w in due for w in ("tomorrow", "next week", "next month", "weekend")) or \
                    re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", due) and \
                    time.strftime("%A").lower() not in due:
                continue                               # not today: no nagging now
            age = now - t["ts"]
            if force or (age > REMIND_MIN_AGE and any(w in due for w in DUE_NOW)) or age > REMIND_AFTER:
                return t
        return None

    async def remind(self, force: bool = False) -> bool:
        t = self._due_todo(force)
        if not t:
            return False
        self._reminded.add(t["id"])
        memory.mark_reminded(t["id"])             # survives restarts: never the same reminder twice
        text = t["text"].rstrip(".")
        text = text[0].lower() + text[1:] if text[:1].isupper() and not text[:2].isupper() else text
        due = f" {t['due']}" if t["due"] and t["due"].lower() not in text.lower() else ""
        log.info("REMIND: %s", t["text"])
        self.publish_status(note=f"Reminder: {t['text']}")
        await self.router.speak(f"Just a gentle reminder: you planned to {text}{due}.")
        return True

    async def reminder_loop(self):
        while True:
            await asyncio.sleep(15)
            quiet = time.time() - max(self._last_heard, 0) > REMIND_QUIET
            if self.mode == "listen" and not self.speaking and quiet and not (self._fall_task and not self._fall_task.done()):
                await self.remind()

    async def _on_audio(self, a):
        if not self._decoder:
            return
        try:
            pcm = self._decoder.feed(a)
        except Exception:
            pcm = b""
        if not pcm:                                   # decoder out of step (e.g. after a reconnect)
            self._empty = getattr(self, "_empty", 0) + 1
            if self._empty in (25, 250):              # 0.5 s of empties: start a fresh decoder
                from vexo_open.audio import PcmDecoder
                self._decoder = PcmDecoder()
                log.warning("Audio decoder reset (empty sound from the band)")
            return
        self._empty = 0
        from vexo_open.audio import level_db
        db = level_db(pcm)
        self._levels.append((time.time(), db))
        self._pkt_db.append(db)                   # index i = audio time i*20 ms, Deepgram's clock
        self._pkt_pcm.append(pcm)
        if len(self._pkt_pcm) > 15000:            # keep ~5 min of sound for voiceprints
            drop = len(self._pkt_pcm) - 15000
            for k in range(drop):
                self._pkt_pcm[k] = b""
        if self._enrolling:
            self._enroll_buf.append(pcm)
        self._audio_packets = getattr(self, "_audio_packets", 0) + 1
        await self.source.feed(pcm)

    async def meter_loop(self):
        """Live mic level for the /test page, twice a second."""
        while True:
            await asyncio.sleep(0.5)
            if not self.dashboard:
                continue
            now = time.time()
            recent = [db for t, db in self._levels if now - t < 0.5]
            last_t = self._levels[-1][0] if self._levels else 0
            self.dashboard.publish({"table": "mic", "row": {
                "db": round(max(recent), 1) if recent else None,
                "arriving": bool(last_t and now - last_t < 2),
                "speaking": self.speaking, "mode": self.mode, "band": self.band_state}})

    async def ask_timeout_loop(self):
        """Back to listening when the conversation goes quiet (no follow-up within CONVO_WINDOW s)."""
        while True:
            await asyncio.sleep(1)
            if (self.mode == "ask" and not self.speaking and not self.router._question and not self.router._last_q
                    and time.time() - self._ask_started > CONVO_WINDOW):
                self.mode = "listen"
                log.info("Back to listening (no question)")
                self.publish_status()

    async def enroll(self, name: str, role: str, seconds: float = 20.0):
        """Onboarding: record `seconds` of this person talking near the band and save their voiceprint."""
        if self._enrolling:
            return
        self._enroll_buf, self._enrolling = [], (name, role, time.time() + seconds)
        log.info("Recording %s's voice for %.0f s… keep talking", name, seconds)
        self.publish_status(note=f"Recording {name}'s voice: keep talking for {seconds:.0f} seconds")
        if self.dashboard:
            self.dashboard.publish({"table": "enroll", "row": {"name": name, "role": role, "state": "recording",
                                                                "seconds": seconds}})
        await asyncio.sleep(seconds)
        pcm, self._enrolling = b"".join(self._enroll_buf), None
        try:
            from . import voiceprint
            rec = await asyncio.to_thread(voiceprint.enroll, name, pcm, role)
            if role and role != "wearer":
                memory.upsert_person(name, relationship=role, speaker=rec.get("id", ""))
            msg, state = f"Got it: I'll recognise {name}'s voice now.", "done"
        except Exception as e:
            msg, state = f"I couldn't learn {name}'s voice ({e}). Try again, talking a bit louder.", "failed"
        log.info(msg)
        self.publish_status(note=msg)
        if self.dashboard:
            self.dashboard.publish({"table": "enroll", "row": {"name": name, "role": role, "state": state, "text": msg}})
        await self.router.speak(msg)

    async def summary_loop(self):
        """Keep the family's 'Today so far' note fresh: at most once a minute, only after changes."""
        from . import summary
        last = None
        while True:
            await asyncio.sleep(20)
            if not self.dashboard:
                continue
            try:
                s = await asyncio.to_thread(summary.today)
            except Exception as e:
                log.warning("summary: %s", e)
                continue
            if s["text"] != last:
                last = s["text"]
                self.dashboard.publish({"table": "summary", "row": s})

    async def mic_loop(self):
        """Every 10 s: is sound arriving from the band, and how loud (quiet room ~ -50 dB, talking ~ -30)."""
        last = 0
        while True:
            await asyncio.sleep(10)
            if not self.band or self.sim:
                continue
            n = getattr(self, "_audio_packets", 0)
            if n == last:
                log.warning("No sound from the band in the last 10 s (is it connected? mic on = solid blue light)")
            else:
                recent = [db for t, db in self._levels if time.time() - t < 10]
                peak = max(recent) if recent else -99
                log.info("MIC sound arriving | loudest %.0f dB (lower = quieter; the venue is loud)", peak)
            last = n

    async def _on_tap(self, e=None):
        """The band's own double-tap detection struggles through the strap's fabric; two single taps within
        0.8 s count as a double-tap too."""
        now = time.time()
        self._tap_seen = now
        if now - getattr(self, "_single_tap_t", 0) < 0.5:
            self._single_tap_t = 0.0
            await self._on_double_tap(e)
        else:
            self._single_tap_t = now

    async def _on_double_tap(self, e=None):
        now = time.time()
        self._tap_seen = now
        log.info("(band: double-tap)")
        if now - self._last_tap < 2.0:              # one gesture, several events: ignore repeats
            return
        self._last_tap = now
        if self.fall_check_active():
            await self.fall_ok("double-tapped")
            return
        if self.mode == "listen":
            self.mode = "ask"
            self.new_conversation()
            asyncio.create_task(self.flush())   # save what was just heard so the answer can use it
            self._ask_started = now
            log.info("MODE: ask (double-tap)")
            self.publish_status(note="Listening for your question")
            await self.say_yes()
        else:
            self.mode = "listen"
            self.publish_status()

    def _on_motion(self, e):
        """A fall while WEARING the band (the band's free-fall event only fires when the band itself drops):
        a brief low-g dip (falling), then an impact over IMPACT_G, not right after a tap, then ~1.5 s of a fairly
        still wrist. Standing up or sitting down has the jolt but not the dip."""
        ax, ay, az = getattr(e, "ax", None), getattr(e, "ay", None), getattr(e, "az", None)
        if ax is None:
            return
        g = (ax * ax + ay * ay + az * az) ** 0.5
        now = time.time()
        self._motion.append((now, g))
        dropped = any(gg <= DIP_G for tt, gg in self._motion if now - 1.2 <= tt < now - 0.02)   # falling phase
        if (g >= IMPACT_G and dropped and now - getattr(self, "_tap_seen", 0) > 1.5 and not self.fall_check_active()
                and now - getattr(self, "_impact_t", 0) > 20):
            self._impact_t = now
            asyncio.create_task(self._impact_then_still(now, g))

    async def _impact_then_still(self, t0: float, peak: float):
        await asyncio.sleep(2.4)
        after = [g for t, g in self._motion if t0 + 0.7 <= t <= t0 + 2.4]
        if len(after) < 20:
            return
        movement = sum(abs(g - 1.0) for g in after) / len(after)
        log.info("(motion: impact %.1f g, then movement %.2f)", peak, movement)
        if movement < STILL_AFTER and not self.fall_check_active():
            log.warning("Fall detected from motion (impact %.1f g, then still)", peak)
            await self._on_fall()

    async def _on_fall(self, e=None):
        if self._fall_task and not self._fall_task.done():
            return
        self._fall_task = asyncio.create_task(self._fall_check())

    async def _fall_check(self):
        """'Are you okay?' -> FALL_WAIT seconds to answer (double-tap OR say "I'm fine"), counted from when Kin
        has finished asking. Only no answer alerts the family's phones."""
        memory.add_alert("fall", f"Possible fall detected for {config.WEARER_NAME}. Checking in.")
        self.publish_status(note="Possible fall: checking in")
        self._fall_listening = False                        # taps from the impact itself don't count
        await self.router.speak("Are you okay? Say I'm fine, or double-tap your band.")
        t0 = time.time()
        await asyncio.sleep(0.5)
        while self.speaking and time.time() - t0 < 10:      # the countdown starts once the question is heard
            await asyncio.sleep(0.2)
        self._fall_listening = True
        await asyncio.sleep(FALL_WAIT)
        self._fall_listening = False
        memory.add_alert("fall_emergency", f"No response after a possible fall. Family should check on "
                                           f"{config.WEARER_NAME} now.")
        await self.router.speak("I'm letting your family know.")

    async def reported_fall(self, said: str):
        """He says he fell / can't get up / is hurt: that's a fall emergency, alert the family now."""
        if time.time() - getattr(self, "_reported_fall_t", 0) < 60:
            return
        self._reported_fall_t = time.time()
        memory.add_alert("fall_emergency", f"{config.WEARER_NAME} said he fell or is hurt (\"{said[:60]}\"). "
                                           "Please check on him now.")
        log.warning("Fall reported by voice: %s", said)
        self.mode = "listen"
        await self.router.speak("I'm getting your family now. Stay where you are, help is coming.")

    def fall_check_active(self) -> bool:
        return bool(self._fall_task and not self._fall_task.done())

    async def fall_not_ok(self, said: str):
        """'No' / 'I'm not fine' / 'help' after a fall: alert the family right away."""
        if not self.fall_check_active():
            return
        self._fall_task.cancel()
        memory.add_alert("fall_emergency", f"{config.WEARER_NAME} said they're not okay after a possible fall "
                                           f"(\"{said[:60]}\"). Please check on them now.")
        log.warning("Fall check: NOT okay (%s)", said)
        await self.router.speak("I'm getting your family now. Stay where you are, help is coming.")

    async def fall_ok(self, how: str = "double-tapped"):
        """The wearer answered the fall check."""
        if not self.fall_check_active():
            return
        if how == "double-tapped" and not getattr(self, "_fall_listening", False):
            log.info("(tap ignored: it came from the fall itself, before Kin asked)")
            return
        self._fall_task.cancel()
        memory.add_alert("fall_ok", f"{config.WEARER_NAME} {how}: they are fine.")
        self.publish_status(note="They're okay")
        log.info("Fall check: %s %s", config.WEARER_NAME, how)
        await self.router.speak("Okay, glad you're alright.")

    # ------------------------------------------------------------------ speakers
    def _utterance_db(self, spk, result) -> float | None:
        """Loudness of exactly this speaker's words, using Deepgram's word timings."""
        try:
            words = result.channel.alternatives[0].words or []
            mine = [w for w in words if str(w.speaker) == str(spk.label)]
            if not mine or not self._pkt_db:
                return None
            i0, i1 = int(mine[0].start / 0.02), int(mine[-1].end / 0.02) + 1
            seg = sorted(self._pkt_db[max(0, i0):i1])
            return seg[int(len(seg) * 0.8)] if seg else None
        except Exception:
            return None

    def _utterance_pcm(self, spk, result) -> bytes:
        try:
            words = result.channel.alternatives[0].words or []
            mine = [w for w in words if str(w.speaker) == str(spk.label)]
            if not mine:
                return b""
            i0, i1 = int(mine[0].start / 0.02), int(mine[-1].end / 0.02) + 1
            return b"".join(self._pkt_pcm[max(0, i0):i1])
        except Exception:
            return b""

    def voice_label(self, spk, result=None) -> tuple[str, str]:
        """(speaker, name) for a finished sentence. One question: is this the wearer's voice, yes or no?
          voice    - voiceprint match (strong; survives restarts and days)
          loudness - the wearer's voice is the loudest at the wrist
          context  - same Deepgram voice as the last wearer sentence; talking to Kin in a conversation
        """
        loud_label = self.speaker_label(spk, result)          # 'wearer' or 'speaker N' (relative loudness)
        dg = str(getattr(spk, "label", "")) if spk is not None else ""
        try:
            from . import voiceprint
        except Exception:
            voiceprint = None
        m = None
        if voiceprint is not None and spk is not None:
            pcm = self._utterance_pcm(spk, result)
            if pcm:
                try:
                    m = voiceprint.observe(pcm)
                except Exception as e:
                    log.warning("voiceprint failed: %s", e)
        fresh = bool(m and m.get("id"))
        if fresh:
            self._dg_voice[dg] = m
        else:
            m = self._dg_voice.get(dg)                        # short clip: same Deepgram voice as last time
        m = m or {}
        thr = getattr(voiceprint, "THRESHOLD", 0.5) if voiceprint else 0.5
        score = m.get("score") or 0.0
        wearer_known = bool(voiceprint and voiceprint.wearer())

        # One simple question: is this the wearer's voice, yes or no? (Names of others come from what is said.)
        if fresh and wearer_known:
            # the closest known voice is the wearer's: yes, even if the match is a bit weak in a noisy room
            is_wearer = bool((m.get("is_wearer") or m.get("role") == "wearer") and score >= WEARER_MATCH)
            why = [f"voiceprint {'matches' if is_wearer else 'does not match'} the wearer ({score:.2f})"]
        elif fresh:                                           # no wearer voice yet: loudness decides, and teaches it
            is_wearer = loud_label == "wearer"
            why = ["no wearer voiceprint yet: loudness"]
        else:                                                 # too short to recognise: keep this voice's last label
            prev = self._dg_decision.get(dg)                  # too short to check: this Deepgram voice's last
            if prev:                                          # checked label, else relative loudness
                log.info("VOICE short clip, same voice as before -> %s",
                         "you (wearer)" if prev[0] == "wearer" else "someone else")
                return prev
            is_wearer = loud_label == "wearer"
            why = ["short clip, by loudness"]
        log.info("VOICE %s -> %s", ", ".join(why), "you (wearer)" if is_wearer else "someone else")

        if fresh and dg:                                      # remember this voice's decision for short lines
            self._dg_decision[dg] = ("wearer", config.WEARER_NAME) if is_wearer else \
                ((m["id"], m.get("name") or "") if m.get("id") else (loud_label, ""))
        if is_wearer:
            self._wearer_dg, self._wearer_dg_t = dg, time.time()
            if voiceprint is not None and m.get("id") and not m.get("name") and not voiceprint.wearer():
                n = self._wearer_votes[m["id"]] = self._wearer_votes.get(m["id"], 0) + 1
                if n >= 4:                                    # no onboarding: learn the wearer's voice
                    try:
                        voiceprint.name_voice(m["id"], config.WEARER_NAME, role="wearer")
                        log.info("Learned %s's voice (the wearer)", config.WEARER_NAME)
                    except Exception as e:
                        log.warning("could not name the wearer's voice: %s", e)
            return "wearer", config.WEARER_NAME
        if m.get("id"):
            return m["id"], (m.get("name") or "")
        return loud_label if loud_label != "wearer" else "speaker ?", ""

    def speaker_label(self, spk, result=None) -> str:
        """Turns Deepgram's speaker number into 'wearer' or 'speaker N'.

        Deepgram tells the voices apart; we decide which voice is the wearer by RELATIVE loudness:
        the band is on the wearer's wrist, so their voice is consistently the loudest one. An absolute
        threshold doesn't work (real levels vary a lot with the room and the mic gain).
        KIN_WEARER_SPEAKER=N forces speaker N to be the wearer.
        """
        num = getattr(spk, "number", None) if spk else None
        label = f"speaker {num}" if num is not None else "speaker ?"
        loud = self._utterance_db(spk, result) if spk is not None else None
        if loud is None:                                        # fallback: the last 3 seconds
            now = time.time()
            recent = sorted(db for t, db in self._levels if now - t < 3.0)
            loud = recent[int(len(recent) * 0.8)] if recent else None
        if loud is not None:
            self._speaker_db.setdefault(label, []).append(loud)
            self._speaker_db[label] = self._speaker_db[label][-20:]
        forced = os.environ.get("KIN_WEARER_SPEAKER")
        if forced:
            return "wearer" if label == f"speaker {forced}" else label
        if label == self._wearer_label():
            return "wearer"
        return label

    def _wearer_label(self) -> str | None:
        """The speaker whose voice is clearly the loudest at the wrist."""
        known = {l: v for l, v in self._speaker_db.items() if v and l != "speaker ?"}
        if len(known) == 1:                         # only one voice heard so far: that's the wearer
            self._last_wearer = next(iter(known))
            return self._last_wearer
        meds = {l: statistics.median(v) for l, v in known.items() if len(v) >= 2}
        if not meds:
            return self._last_wearer
        ranked = sorted(meds.items(), key=lambda kv: kv[1], reverse=True)
        if len(ranked) == 1:
            self._last_wearer = ranked[0][0]        # only one voice so far: assume it's the wearer
            return self._last_wearer
        (top, a), (_, b) = ranked[0], ranked[1]
        if a - b >= WEARER_MARGIN_DB:
            self._last_wearer = top
        return self._last_wearer

    # ------------------------------------------------------------------ listening -> memory
    MONEY_SAY = __import__("re").compile(
        r"(\b(send|sending|wire|transfer|give|giving|pay|paying|lend|venmo|zelle)\b.{0,25}"
        r"(\$\s?\d|\bmoney\b|\bcash\b|\bdollars?\b|\bgift ?cards?\b|\bbank\b|\bcard number)|"
        r"\bhow much (money|do you need)\b|\bgift ?cards?\b|\bbail\b|\bsocial security\b|\bssn\b|"
        r"\b(card|account|routing) number\b|\bcard (info|information|details)\b|\bbank (info|details)\b|"
        r"\b(give|tell|read|share|send|confirm|verify)\b.{0,30}\b(credit card|debit card|bank card|"
        r"pin|password|passcode|bank account)\b|\b(need|want|what'?s)\b.{0,12}\byour\b.{0,20}\b(card|pin|password|"
        r"passcode|bank|account)\b|\bwestern union\b|\bcrypto|bitcoin\b|"
        r"\btime ?share\b|\byou'?ve won\b|\b(lottery|sweepstakes|prize)\b|\birs\b|\bwarrant\b|\bmedicare (card|number)\b)",
        __import__("re").I)

    async def money_watch(self, speaker: str, text: str):
        """Money in a conversation (either side; on a phone call the band mostly hears the wearer):
        warn out loud right away and alert the family. At most once per 2 minutes."""
        if not self.MONEY_SAY.search(text) or time.time() - getattr(self, "_warned_scam", 0) < 120:
            return
        self._warned_scam = time.time()
        from . import safety
        who = safety.family_contact()
        try:
            safety.set_scam_lock("money talk in a conversation")
        except Exception:
            pass
        memory.add_alert("scam", f"Money came up in a conversation with {config.WEARER_NAME} "
                                 f"(\"{text[:80]}\"). Kin warned him not to send money.")
        log.warning("SCAM: money talk: %s", text)
        await self.router.speak(f"Hold on, this could be a scam. Please don't give any money, card numbers or "
                                f"personal details until you've checked with {who}. I've let them know.")

    async def heard(self, speaker: str, text: str, name: str = ""):
        """A finished sentence from the band (listen mode). Never blocks the pipeline: the scam check runs on
        the raw words right away; cleanup + storing happen in order on a background queue."""
        name = config.WEARER_NAME if speaker == "wearer" else name
        self._last_heard = time.time()
        await self.money_watch(speaker, text)
        if not hasattr(self, "_hear_q"):
            self._hear_q = asyncio.Queue()
            asyncio.create_task(self._hear_worker())
        await self._hear_q.put((speaker, text, name))

    async def _hear_worker(self):
        while True:
            speaker, raw, name = await self._hear_q.get()
            try:
                await self._store_heard(speaker, raw, name)
            except Exception as e:
                log.warning("could not store a sentence: %s", e)

    async def _store_heard(self, speaker: str, raw: str, name: str):
        text = raw
        backlog = self._hear_q.qsize() if hasattr(self, "_hear_q") else 0
        try:                                           # careful AI cleanup of clear mishearings, with context
            if backlog > 0:
                raise RuntimeError("busy")             # sentences are piling up: store them as heard, don't fall behind
            from . import cleanup
            recent = [f"{l['name'] or l['speaker']}: {l['text']}" for l in memory.recent_lines(300)[-6:]]
            text, fixed = await asyncio.to_thread(cleanup.clean, raw, recent)
            if fixed:
                log.info("(cleaned up: %r -> %r)", raw, text)
        except Exception:
            text = raw
        if text != raw:
            await self.money_watch(speaker, text)      # the cleaned words may reveal money talk too
        if not name:
            p = memory.person_by_speaker(speaker)
            name = p["name"] if p else ""
        rid = memory.add_line(speaker, text, name=name)
        log.info("HEARD %s%s: %s", speaker, f" ({name})" if name and speaker != "wearer" else "", text)
        now = time.time()
        if not self._chunk:
            self._chunk_started = now
        self._chunk.append({"id": rid, "speaker": speaker, "name": name, "text": text})
        self._last_heard = now
        await self._scam_check()

    async def chunk_loop(self):
        while True:
            await asyncio.sleep(0.5)
            now = time.time()
            if self._chunk and (now - self._last_heard > CHUNK_PAUSE or now - self._chunk_started > CHUNK_MAX):
                lines, self._chunk = self._chunk, []
                await self.digest(lines)

    def flag_money(self, text: str) -> None:
        """Someone is asking the wearer for money (told to Kin directly): alert the family, once per 2 min."""
        import re
        if not re.search(r"(\$\s?\d|\b\d[\d,]* ?(dollars|bucks)\b|\b(send|wire|transfer|give)\b.*\b(money|cash|\$)|"
                         r"\bgift ?cards?\b|\bbail\b)", text, re.I):
            return
        if time.time() - getattr(self, "_money_flag_t", 0) < 120:   # own timer: must not silence a later
            return                                                   # spoken warning about a real scam call
        self._money_flag_t = time.time()
        memory.add_alert("scam", f"{config.WEARER_NAME} was asked for money and asked Kin about it. Kin told him "
                                 "to check with family first.")
        log.warning("SCAM: money request mentioned to Kin")

    async def digest(self, lines):
        res = await asyncio.to_thread(brain.digest, lines)
        if res and res.get("category") == "money_safety" and time.time() - getattr(self, "_warned_scam", 0) > 120:
            self._warned_scam = time.time()
            from . import safety
            who = safety.family_contact()
            memory.add_alert("scam", f"Money request heard in a conversation with {config.WEARER_NAME}. Kin warned him.")
            log.warning("SCAM (from the conversation): money request")
            await self.router.speak(f"That sounded like someone asking you for money. Please don't send anything "
                                    f"until you've checked with {who}. I've let them know.")
        if res:
            log.info("MEMORY importance=%s %s | people=%s facts=%d todos=%d items=%d", res.get("importance"),
                     res.get("category"), [p["name"] for p in res.get("people", [])], len(res.get("facts", [])),
                     len(res.get("todos", [])), len(res.get("items", [])))

    async def flush(self):
        q = getattr(self, "_hear_q", None)
        for _ in range(40):                            # let queued sentences be stored first (max ~4 s)
            if not q or q.empty():
                break
            await asyncio.sleep(0.1)
        if self._chunk:
            lines, self._chunk = self._chunk, []
            await self.digest(lines)

    async def _scam_check(self):
        try:
            from . import safety
        except ImportError:
            return
        lines = [l for l in self._chunk[-8:]]
        try:
            r = await asyncio.to_thread(safety.check_scam, lines)
        except Exception as e:
            log.warning("scam check failed: %s", e)
            return
        if r and r.get("risk") == "high" and not getattr(self, "_warned_scam", 0) > time.time() - 120:
            self._warned_scam = time.time()
            log.warning("SCAM: %s", r.get("reason"))
            await self.router.speak(r.get("say") or "This sounds like a scam. Please don't send any money.")

    # ------------------------------------------------------------------ ask mode end
    async def say_yes(self):
        """'Yes?' right away: pre-rendered at startup, played directly (no 2-4 s TTS round trip)."""
        pcm = getattr(self, "_yes_pcm", None)
        if not pcm or isinstance(self.tts, voice.SayTTS):
            await self.router.speak("Yes?")
            return
        self.speaking = True
        memory.add_line("kin", "Yes?", name="Kin")
        log.info("KIN SAYS: Yes?")
        try:
            await asyncio.to_thread(self.speaker.play_pcm, pcm, 24000)
            await asyncio.sleep(0.4)                      # let the buffered audio finish
        finally:
            self.done_speaking()

    def speaker_stop(self):
        try:
            self.speaker.stop()
        except Exception:
            pass
        p = getattr(self.tts, "_proc", None)
        if p and p.poll() is None:
            p.terminate()

    def hearing_kin(self, text: str) -> bool:
        """Echo gate: while Kin talks out loud (and a moment after), the band hears Kin's own voice. Drop those
        sentences, and anything that closely matches what Kin just said."""
        if self.speaking or time.time() - getattr(self, "_spoke_at", 0) < 0.9:
            return True
        last = (getattr(self, "_last_said", "") or "").lower()
        if last and time.time() - getattr(self, "_spoke_at", 0) < 6:
            import difflib
            if difflib.SequenceMatcher(None, last, text.lower()).ratio() > 0.6:
                return True
        return False

    def done_speaking(self):
        """Kin finished talking. In a conversation, keep listening for a follow-up (conversation mode):
        the window restarts after every answer and closes after CONVO_WINDOW s of silence, or right after
        a goodbye/thanks."""
        self.speaking = False
        self._spoke_at = time.time()
        try:
            self._last_said = next((l["text"] for l in reversed(memory.recent_lines(30)) if l["speaker"] == "kin"), "")
        except Exception:
            pass
        self.router._last_q = ""                 # answered: no fallback needed any more
        if self.mode == "ask":
            if self._closing:
                self._closing = False
                self.mode = "listen"
                log.info("Conversation ended")
                self.publish_status()
            else:
                self._ask_started = time.time()  # follow-up window starts now
                if (getattr(self, "_last_said", "") or "").strip().rstrip("?").lower() not in ("yes", ""):
                    self.answered_once = True     # a real answer was given (not just "Yes?")
                self.publish_status(note="Still listening: ask a follow-up, or say thanks")

    # ------------------------------------------------------------------ dashboard, vision
    def publish_status(self, note: str = ""):
        if self.dashboard:
            try:
                self.dashboard.publish({"table": "status", "row": {"mode": self.mode, "band": self.band_state,
                                                                     "note": note}})
            except Exception:
                pass

    def start_extras(self):
        if not (self.args.sim or self.args.demo) or os.environ.get("KIN_NTFY_IN_SIM"):
            try:
                from . import notify
                log.info("Phone alerts on: subscribe to %s in the ntfy app", notify.start())
            except Exception as e:
                log.warning("Phone alerts off: %s", e)
        if not self.args.no_dashboard:
            try:
                from . import dashboard
                dashboard.start_in_thread(config.DASHBOARD_PORT, host="127.0.0.1")
                self.dashboard = dashboard
                loop = asyncio.get_running_loop()
                dashboard.set_command_handler(
                    lambda cmd: asyncio.run_coroutine_threadsafe(self.command(cmd), loop))
                log.info("Dashboard: http://localhost:%s", config.DASHBOARD_PORT)
            except ImportError:
                log.info("Dashboard module not built yet.")
            except Exception as e:
                log.warning("Dashboard failed to start: %s", e)
        if self.args.webcam is not None or self.args.camera_url:
            try:
                from . import vision
                src = vision.MarvSource(self.args.camera_url) if self.args.camera_url else \
                    vision.WebcamSource(self.args.webcam)
                self.vision = vision.VisionWatcher(src)
                self.vision.start()
                log.info("Vision watcher started.")
            except Exception as e:
                log.warning("Vision not started: %s", e)

    # ------------------------------------------------------------------ terminal + demo
    async def console(self):
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            await self.command(line.rstrip("\n"))

    async def command(self, line: str):
        cmd, _, rest = line.partition(" ")
        if cmd in ("t", "f"):
            kind = "double-tap" if cmd == "t" else "free-fall"
            if self.sim:
                self.sim.tap(kind)               # goes through the band's real event path
            elif cmd == "t":
                await self._on_double_tap()
            else:
                await self._on_fall()
        elif cmd == "a" and rest:
            await self.router.ask(rest)
        elif cmd in ("w", "1", "2", "3") and rest:
            spk = "wearer" if cmd == "w" else f"speaker {cmd}"
            if isinstance(self.stt, voice.TypedSTT):
                await self.stt.say(spk, rest)
            else:
                await self.router._on_sentence(spk, rest)
        elif cmd == "r":
            if not await self.remind(force=True):
                print("No open to-dos to remind about.")
        elif cmd == "away":
            if self.sim:
                self.sim.set_rssi(-95)           # pretend the band walked out of range
            else:
                self._far_since = time.time() - WANDER_SECONDS - 1
        elif cmd == "home":
            if self.sim:
                self.sim.set_rssi(-50)
            self._far_since, self._wander_alerted = 0.0, False
        elif cmd == "enroll" and rest:
            role, _, name = rest.partition(" ")       # e.g. "enroll wearer Grandpa Joe", "enroll daughter Sarah"
            await self.enroll(name.strip() or config.WEARER_NAME, role.strip())
        elif cmd == "s":
            await self.flush()
            print(memory.summary_for_llm())
        elif cmd == "q":
            self._quit.set()

    async def demo(self):
        """A scripted run of the whole story, for testing without a microphone."""
        say = self.command
        await asyncio.sleep(2)
        for line in ["1 Hi Dad, it's Sarah!", "w Oh hi sweetheart, so good to see you.",
                     "1 I'm moving to Oakland next week for my new job.",
                     "w I'm putting my keys in the kitchen drawer.",
                     "w I'll call the dentist tomorrow."]:
            await say(line)
            await asyncio.sleep(0.6)
        await asyncio.sleep(CHUNK_PAUSE + 1.5)
        for q in ["Who was that?", "Where are my keys?"]:
            await say("t")
            await asyncio.sleep(1.0)
            await say("a " + q)
            await self._wait_quiet()
        await say("2 Grandpa, it's your grandson. I'm in jail and I need bail. Buy gift cards and don't tell Mom.")
        await self._wait_quiet()
        await say("f")
        await asyncio.sleep(2)
        await say("t")
        await self._wait_quiet()
        await self.flush()
        print("\n==== MEMORY AFTER DEMO ====\n" + memory.summary_for_llm())
        print("ALERTS:", [a["kind"] for a in memory.alerts()])

    async def _wait_quiet(self, timeout=30):
        t0 = time.time()
        await asyncio.sleep(0.5)
        while (self.speaking or self.mode == "ask") and time.time() - t0 < timeout:
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.3)

    # ------------------------------------------------------------------ run
    async def run(self):
        from pipecat.workers.runner import WorkerRunner
        await self.build()
        self.start_extras()
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(self.task)
        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.5)
        try:                                           # "Yes?" in Kin's voice, ready to play instantly
            self._yes_pcm = await asyncio.wait_for(asyncio.to_thread(voice.synth_pcm, "Yes?"), 12)
        except Exception:
            self._yes_pcm = None
        try:                                           # warm the cleanup model so the first sentence isn't slow
            from . import cleanup
            asyncio.create_task(asyncio.to_thread(cleanup.clean, "hello there my friend", []))
        except Exception:
            pass
        try:
            from . import voiceprint
            await asyncio.to_thread(voiceprint.warm_up)
        except Exception as e:
            log.warning("Voice recognition off: %s", e)
        await self.connect_band()
        self._quit = asyncio.Event()
        jobs = [asyncio.create_task(self.chunk_loop()), asyncio.create_task(self.reminder_loop()),
                asyncio.create_task(self.wander_loop()), asyncio.create_task(self.mic_loop()), asyncio.create_task(self.meter_loop()),
                asyncio.create_task(self.ask_timeout_loop()),
                asyncio.create_task(self.reconnect_loop()), asyncio.create_task(self.summary_loop())]
        demo_task = asyncio.create_task(self.demo()) if self.args.demo else None
        if demo_task:
            jobs.append(demo_task)
        if not self.args.no_console:
            jobs.append(asyncio.create_task(self.console()))
        print(__doc__.split("Terminal keys")[1] if not self.args.demo else "Running demo...")
        try:
            waits = {run_task, asyncio.create_task(self._quit.wait())}
            if demo_task and not self.args.stay:
                waits.add(demo_task)
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for j in jobs:
                j.cancel()
            # Under the auto-reloader, leave the link to drop instead of closing it: a dropped band stays
            # findable for 2 minutes, so the restarted Kin reconnects without anyone double-tapping.
            if self.band and not os.environ.get("KIN_RELOAD"):
                try:
                    await self.band.disconnect()
                except Exception:
                    pass
            await voice.end(self.task)
            try:
                await asyncio.wait_for(run_task, 5)
            except Exception:
                pass


class Pretty(logging.Formatter):
    """Short, readable terminal lines: what Kin heard, what it said, what happened."""
    STYLE = [("HEARD ", "\033[37m  👂 "), ("KIN SAYS: ", "\033[1;32m  🗣  KIN (out loud): "),
             ("ASK: ", "\033[1;36m  ❓ YOU ASKED: "), ("MODE: ask", "\033[1;36m  👆 double-tap: asking mode"),
             ("MEMORY ", "\033[35m  🧠 saved: "), ("SCAM", "\033[1;31m  🚨 SCAM"), ("REMIND", "\033[33m  ⏰ REMIND"),
             ("WANDER", "\033[1;31m  🚶 WANDER"), ("MIC ", "\033[90m  🎚  "),
             ("VOICE ", "\033[36m  🎙  ")]

    def format(self, record):
        msg = record.getMessage()
        t = time.strftime("%H:%M:%S", time.localtime(record.created))
        for prefix, style in self.STYLE:
            if msg.startswith(prefix):
                return f"\033[90m{t}\033[0m{style}{msg[len(prefix):]}\033[0m"
        if record.levelno >= logging.WARNING:
            return f"\033[90m{t}\033[0m  \033[33m⚠️  {msg}\033[0m"
        return f"\033[90m{t}  {msg}\033[0m"


def main():
    from . import settings
    settings.apply()                                  # the wearer's name from /setup
    try:
        settings.seed_memory()                        # the people from /setup, also after a memory reset
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Kin: memory companion on a Vexo band")
    ap.add_argument("--band", type=int, default=config.BAND_NUMBER)
    ap.add_argument("--sim", action="store_true", help="pretend band, no hardware")
    ap.add_argument("--demo", action="store_true", help="pretend band + scripted demo, then exit")
    ap.add_argument("--replay", help="an .ogg/.opus file the pretend band plays as its microphone")
    ap.add_argument("--webcam", type=int, help="start vision on this webcam index")
    ap.add_argument("--camera-url", help="start vision on a camera stream URL (Marv Labs)")
    ap.add_argument("--stay", action="store_true", help="with --demo: keep running afterwards")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--no-console", action="store_true")
    ap.add_argument("--mute", action="store_true", help="don't play the fallback voice out loud")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    handler = logging.StreamHandler()
    handler.setFormatter(Pretty())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    for noisy in ("httpx", "httpx2", "httpcore", "openai", "websockets", "uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not args.verbose:
        from loguru import logger
        logger.remove()
        logger.add(sys.stderr, level="WARNING")
    kin = Kin(args)
    if args.mute:
        voice.SayTTS.mute = True
    try:
        asyncio.run(kin.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
