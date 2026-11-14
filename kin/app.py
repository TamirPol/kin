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
FALL_WAIT = 15.0           # seconds to double-tap "I'm fine" after a fall
REMIND_AFTER = float(__import__("os").environ.get("KIN_REMIND_AFTER", "600"))  # remind of a to-do this long after it was made
REMIND_QUIET = 20.0        # only remind when nobody has spoken for this long
WANDER_RSSI = -88          # dBm: weaker than this means the band is far from the laptop/base
WANDER_SECONDS = 10.0      # ... for this long (or the link is lost this long) -> wander alert
DUE_NOW = ("today", "tonight", "this morning", "this afternoon", "this evening", "now", "soon")


class Kin:
    def __init__(self, args):
        self.args = args
        self.mode = "listen"
        self.speaking = False
        self.ask_pause = 1.2
        self.has_diarization = bool(config.DEEPGRAM_API_KEY)
        self.band = None
        self.band_state = "disconnected"
        self._levels: deque = deque(maxlen=150)               # (time, dB) for the last 3 s
        self._speaker_db: dict[str, list[float]] = {}
        self._last_wearer: str | None = None
        self._pkt_db: list[float] = []
        self._last_tap = 0.0
        self._ask_started = 0.0
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
        from pipecat.pipeline.task import PipelineParams, PipelineTask

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
        self.task = PipelineTask(Pipeline(parts),
                                 params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
                                 cancel_on_idle_timeout=False)

    def refresh_system_prompt(self):
        if self.ctx:
            msgs = self.ctx.user().context.get_messages()
            if msgs and msgs[0].get("role") == "system":
                msgs[0]["content"] = voice.system_prompt()

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
        self.band.on("free-fall", self._on_fall)
        self.band.on("disconnect", self._on_disconnect)
        self.band.on("reconnected", lambda e: self._set_band("connected"))
        self.band.on("reconnecting", self._on_reconnecting)
        self.band.on("link", self._on_link)
        # a firmer tap threshold (default 0.8 g) so walking and gesturing don't count as double-taps
        await self.band.set_events(kinds=["tap", "double-tap", "free-fall"], tap_threshold=float(os.environ.get("KIN_TAP_G", "1.0")))
        await self.band.configure(audio=True, events=True)     # light goes solid blue: mic is on
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
            if t["id"] in self._reminded:
                continue
            due = (t["due"] or "").lower()
            if force or any(w in due for w in DUE_NOW) or now - t["ts"] > REMIND_AFTER:
                return t
        return None

    async def remind(self, force: bool = False) -> bool:
        t = self._due_todo(force)
        if not t:
            return False
        self._reminded.add(t["id"])
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
        """Back to listening if no question comes within 10 s of a double-tap."""
        while True:
            await asyncio.sleep(1)
            if (self.mode == "ask" and not self.speaking and not self.router._question and not self.router._last_q
                    and time.time() - self._ask_started > 10):
                self.mode = "listen"
                log.info("Back to listening (no question)")
                self.publish_status()

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

    async def _on_double_tap(self, e=None):
        now = time.time()
        if now - self._last_tap < 2.0:              # one gesture, several events: ignore repeats
            return
        self._last_tap = now
        if self._fall_task and not self._fall_task.done():
            self._fall_task.cancel()
            memory.add_alert("fall_ok", f"{config.WEARER_NAME} double-tapped: they are fine.")
            self.publish_status(note="They're okay")
            await self.router.speak("Okay, glad you're alright.")
            return
        if self.mode == "listen":
            self.mode = "ask"
            self._ask_started = now
            log.info("MODE: ask (double-tap)")
            self.publish_status(note="Listening for your question")
            await self.router.speak("Yes?")
        else:
            self.mode = "listen"
            self.publish_status()

    async def _on_fall(self, e=None):
        if self._fall_task and not self._fall_task.done():
            return
        self._fall_task = asyncio.create_task(self._fall_check())

    async def _fall_check(self):
        memory.add_alert("fall", f"Possible fall detected for {config.WEARER_NAME}. Checking in.")
        self.publish_status(note="Possible fall: checking in")
        await self.router.speak("Are you okay? Double-tap your band if you're fine.")
        await asyncio.sleep(FALL_WAIT)
        memory.add_alert("fall_emergency", f"No response after a possible fall. Family should check on "
                                           f"{config.WEARER_NAME} now.")
        await self.router.speak("I'm letting your family know.")

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
    async def heard(self, speaker: str, text: str):
        name = config.WEARER_NAME if speaker == "wearer" else ""
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

    async def digest(self, lines):
        res = await asyncio.to_thread(brain.digest, lines)
        if res:
            log.info("MEMORY importance=%s %s | people=%s facts=%d todos=%d items=%d", res.get("importance"),
                     res.get("category"), [p["name"] for p in res.get("people", [])], len(res.get("facts", [])),
                     len(res.get("todos", [])), len(res.get("items", [])))

    async def flush(self):
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
    def done_speaking(self):
        self.speaking = False
        self.router._last_q = ""                 # answered: no fallback needed any more
        if self.mode == "ask" and not self.router._question and getattr(self, "_answered", False):
            self.mode = "listen"
            self.publish_status()
        self._answered = self.mode == "ask"

    # ------------------------------------------------------------------ dashboard, vision
    def publish_status(self, note: str = ""):
        if self.dashboard:
            try:
                self.dashboard.publish({"table": "status", "row": {"mode": self.mode, "band": self.band_state,
                                                                     "note": note}})
            except Exception:
                pass

    def start_extras(self):
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
        from pipecat.pipeline.runner import PipelineRunner
        await self.build()
        self.start_extras()
        runner = PipelineRunner(handle_sigint=False)
        run_task = asyncio.create_task(runner.run(self.task))
        await asyncio.sleep(0.5)
        await self.connect_band()
        self._quit = asyncio.Event()
        jobs = [asyncio.create_task(self.chunk_loop()), asyncio.create_task(self.reminder_loop()),
                asyncio.create_task(self.wander_loop()), asyncio.create_task(self.mic_loop()), asyncio.create_task(self.meter_loop()),
                asyncio.create_task(self.ask_timeout_loop()),
                asyncio.create_task(self.reconnect_loop())]
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
             ("WANDER", "\033[1;31m  🚶 WANDER"), ("MIC ", "\033[90m  🎚  ")]

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
