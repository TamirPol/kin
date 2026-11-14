"""Kin: the main program. Connects the Vexo band, runs the Pipecat pipeline, and ties
memory, safety, the dashboard and vision together.

    python -m kin.app            # real band (number from KIN_BAND in .env, or --band 42)
    python -m kin.app --sim      # pretend band, no hardware
    python -m kin.app --demo     # pretend band + a scripted demo conversation

Band gestures:  double-tap = ask Kin (or "I'm fine" during a fall check)
                free-fall  = fall check ("Are you okay?")
Terminal keys (handy without a band or a Deepgram key):
    t              pretend double-tap
    f              pretend fall
    a <question>   ask Kin directly
    1 <text>       say <text> as "speaker 1" (w <text> = as the wearer)
    s              show memory          q  quit
"""
from __future__ import annotations

import argparse
import asyncio
import logging
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
WEARER_DB = -32.0          # utterances louder than this (dBFS at the wrist) count as the wearer
FALL_WAIT = 15.0           # seconds to double-tap "I'm fine" after a fall


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
        self._chunk: list[dict] = []
        self._chunk_started = 0.0
        self._last_heard = 0.0
        self._fall_task: asyncio.Task | None = None
        self._decoder = None
        self.dashboard = None
        self.vision = None

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
            self.band = await Band.connect(self.args.band, auto_reconnect=not (self.args.sim or self.args.demo), **kw)
        except Exception as e:
            log.error("Could not connect to band %s: %s", self.args.band, e)
            self.band_state = "disconnected"
            self.publish_status(note=f"Band not connected: {e}")
            return
        self.band_state = "sim" if self.sim else "connected"
        log.info("Connected to %s (%s)", self.band.name, self.band_state)
        try:
            from vexo_open.audio import PcmDecoder
            self._decoder = PcmDecoder()
        except Exception as e:
            log.warning("No Opus decoder (pip install av): %s", e)
        self.band.on("audio", self._on_audio)
        self.band.on("double-tap", self._on_double_tap)
        self.band.on("free-fall", self._on_fall)
        self.band.on("disconnect", lambda e: self._set_band("disconnected"))
        self.band.on("reconnected", lambda e: self._set_band("connected"))
        await self.band.set_events(kinds=["tap", "double-tap", "free-fall"])
        await self.band.configure(audio=True, events=True)     # light goes solid blue: mic is on
        self.publish_status()

    def _set_band(self, s):
        self.band_state = s
        self.publish_status()

    async def _on_audio(self, a):
        if not self._decoder:
            return
        pcm = self._decoder.feed(a)
        from vexo_open.audio import level_db
        self._levels.append((time.time(), level_db(pcm)))
        await self.source.feed(pcm)

    async def _on_double_tap(self, e=None):
        if self._fall_task and not self._fall_task.done():
            self._fall_task.cancel()
            memory.add_alert("fall_ok", f"{config.WEARER_NAME} double-tapped: they are fine.")
            self.publish_status(note="They're okay")
            await self.router.speak("Okay, glad you're alright.")
            return
        if self.mode == "listen":
            self.mode = "ask"
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
    def speaker_label(self, spk) -> str:
        """Turns Deepgram's speaker into 'wearer' or 'speaker N', using loudness: the band
        is on the wearer's wrist, so their voice is much louder than anyone else's."""
        num = getattr(spk, "number", None) if spk else None
        label = f"speaker {num}" if num is not None else "speaker ?"
        now = time.time()
        recent = [db for t, db in self._levels if now - t < 2.5]
        if recent:
            loud = statistics.quantiles(recent, n=10)[-1] if len(recent) >= 10 else max(recent)
            self._speaker_db.setdefault(label, []).append(loud)
            hist = self._speaker_db[label][-8:]
            if statistics.median(hist) >= WEARER_DB:
                return "wearer"
        return label

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
        elif cmd == "s":
            await self.flush()
            print(memory.summary_for_llm())
        elif cmd == "q":
            raise KeyboardInterrupt

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
        jobs = [asyncio.create_task(self.chunk_loop())]
        if self.args.demo:
            jobs.append(asyncio.create_task(self.demo()))
        if not self.args.no_console:
            jobs.append(asyncio.create_task(self.console()))
        print(__doc__.split("Terminal keys")[1] if not self.args.demo else "Running demo...")
        try:
            if self.args.demo and not self.args.stay:
                await jobs[1]
            else:
                await run_task
        finally:
            for j in jobs:
                j.cancel()
            if self.band:
                try:
                    await self.band.disconnect()
                except Exception:
                    pass
            await voice.end(self.task)
            try:
                await asyncio.wait_for(run_task, 5)
            except Exception:
                pass


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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
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
