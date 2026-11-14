"""Kin's eyes: watch a camera, notice where personal items are, remember it.

    source  = WebcamSource(0)            # or FolderSource("demo_frames"), MarvSource("rtsp://...")
    watcher = VisionWatcher(source)      # every 3 s: grab -> skip if unchanged -> Gemini -> memory
    watcher.start()                      # daemon thread
    watcher.look_now()                   # on demand ("Kin, what do you see?") -> [{'item','location','confidence'}]
    watcher.stop()

New items, or items whose location changed, are saved as snapshots/<ts>_<item>.jpg and logged
with memory.add_item(item, location, source='vision', snapshot='snapshots/...').

CLI:  python -m kin.vision --webcam 0 | --folder path | --url URL  [--interval 3] [--once]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable

from . import config, memory

log = logging.getLogger("kin.vision")

try:
    import cv2
    import numpy as np
except ImportError:          # vision still imports; webcam/diff fall back gracefully
    cv2 = None
    np = None


# ======================================================================
# Frame sources
# ======================================================================
class FrameSource:
    """Anything that yields JPEG frames. read() returns JPEG bytes, or None if no frame right now."""

    def read(self) -> bytes | None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _OpenCVSource(FrameSource):
    """Shared OpenCV capture (webcam index or stream URL). Reopens if the stream drops."""

    def __init__(self, target, jpeg_quality: int = 85, max_width: int = 1280):
        if cv2 is None:
            raise RuntimeError("opencv-python is not installed: uv pip install --python .venv/bin/python opencv-python")
        self.target = target
        self.jpeg_quality = jpeg_quality
        self.max_width = max_width
        self._cap = None
        self._lock = threading.Lock()

    def _open(self):
        self._cap = cv2.VideoCapture(self.target)
        if not self._cap.isOpened():
            log.warning("vision: could not open camera %r", self.target)
            self._cap = None

    def read(self) -> bytes | None:
        with self._lock:
            if self._cap is None:
                self._open()
                if self._cap is None:
                    return None
            ok, frame = self._cap.read()
            if not ok or frame is None:
                self._cap.release()
                self._cap = None          # try again next time
                return None
        h, w = frame.shape[:2]
        if w > self.max_width:
            frame = cv2.resize(frame, (self.max_width, int(h * self.max_width / w)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        return buf.tobytes() if ok else None

    def close(self) -> None:
        with self._lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None


class WebcamSource(_OpenCVSource):
    """Laptop webcam: the stand-in for camera glasses. (macOS asks for camera permission on first use.)"""

    def __init__(self, index: int = 0, **kw):
        super().__init__(index, **kw)


class FolderSource(FrameSource):
    """Replays the JPEGs in a folder in name order (demo / tests without a camera)."""

    def __init__(self, path, loop: bool = True):
        self.path = Path(path)
        self.files = sorted(p for p in self.path.iterdir()
                            if p.suffix.lower() in (".jpg", ".jpeg") and p.is_file())
        self.loop = loop
        self._i = 0
        if not self.files:
            log.warning("vision: no JPEGs in %s", self.path)

    def read(self) -> bytes | None:
        if not self.files:
            return None
        if self._i >= len(self.files):
            if not self.loop:
                return None
            self._i = 0
        data = self.files[self._i].read_bytes()
        self._i += 1
        return data


class MarvSource(_OpenCVSource):
    """Marv Labs camera glasses. ---- STUB: API not known yet. ----

    Best guess: the device exposes an RTSP or HTTP (MJPEG) stream URL, which OpenCV opens directly,
    e.g. MarvSource("rtsp://192.168.1.50:554/live") or MarvSource("http://<ip>/stream.mjpg").

    TODO(marv): confirm stream URL format / discovery (mDNS? companion app? cloud relay?).
    TODO(marv): auth (token header or user:pass@ in the URL?).
    TODO(marv): if they only offer a snapshot endpoint (HTTP GET -> JPEG), override read() to fetch it
                with urllib and return the bytes directly, skipping OpenCV.
    TODO(marv): if they offer an SDK with a frame callback, buffer the latest frame and return it here.
    """

    def __init__(self, url: str, **kw):
        if not url:
            raise ValueError("MarvSource needs the camera stream URL")
        super().__init__(url, **kw)


# ======================================================================
# Change detection (cheap, local, no API call)
# ======================================================================
def frame_signature(jpeg: bytes):
    """Tiny grayscale thumbnail used to compare frames. Falls back to the raw bytes without OpenCV."""
    if cv2 is None:
        return jpeg
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return jpeg
    img = cv2.GaussianBlur(cv2.resize(img, (160, 120), interpolation=cv2.INTER_AREA), (5, 5), 0)
    return img.astype(np.int16)


PIXEL_DELTA = 25   # grey levels a thumbnail pixel must change by to count (above sensor noise)


def frame_difference(a, b) -> float:
    """Fraction of thumbnail pixels that changed noticeably: 0.0 = same, 1.0 = everything changed.
    A fraction (not a mean) so that a small thing appearing - keys on a table - still counts."""
    if a is None or b is None:
        return 1.0
    if isinstance(a, bytes) or isinstance(b, bytes) or a.shape != b.shape:
        return 0.0 if (isinstance(a, bytes) and a == b) else 1.0
    return float(np.mean(np.abs(a - b) > PIXEL_DELTA))


# ======================================================================
# Gemini: what personal items are visible, and where?
# ======================================================================
PROMPT = """You are the eyes of a memory helper for an older person with early memory loss.
Look at this photo and list the notable PERSONAL ITEMS that are clearly visible - things people misplace:
keys, glasses, reading glasses, sunglasses, wallet, purse, handbag, phone, pill bottle, pill organizer,
TV remote, hearing aids, watch, cane, walking stick, hat, umbrella, book, mug, jacket, shoes, charger.
Skip furniture, people, and anything you are not sure is there.

For each item give:
- item: a short everyday name, lowercase, singular ("keys", "glasses", "pill bottle", "tv remote")
- location: where it is, in plain friendly words relative to furniture or landmarks an older person
  knows, like "on the kitchen table next to the fruit bowl" or "on the arm of the blue sofa".
  No left/right of the image, no coordinates, no technical words.
- confidence: 0.0 to 1.0, how sure you are the item is really there.

Return an empty list if no such items are visible."""

RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "item": {"type": "STRING"},
            "location": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
        },
        "required": ["item", "location", "confidence"],
    },
}

_client = None
_warned_no_key = False


def _gemini():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def describe_frame(jpeg: bytes) -> list[dict]:
    """Ask Gemini which personal items are in the frame. Returns [{'item','location','confidence'}].
    Returns [] without a GEMINI_API_KEY (logged once) or on any API error (logged)."""
    global _warned_no_key
    if not config.GEMINI_API_KEY:
        if not _warned_no_key:
            log.warning("vision: GEMINI_API_KEY missing - describe_frame returns [] (vision disabled)")
            _warned_no_key = True
        return []
    if not jpeg:
        return []
    try:
        from google.genai import types
        resp = _gemini().models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.1,
            ),
        )
        raw = json.loads(resp.text or "[]")
    except Exception as e:
        log.warning("vision: Gemini call failed: %s", e)
        return []
    return _clean(raw)


def _clean(raw) -> list[dict]:
    """Normalise model output; merge duplicates of the same item (keep the most confident)."""
    if isinstance(raw, dict):
        raw = raw.get("items", [])
    best: dict[str, dict] = {}
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict):
            continue
        item = str(d.get("item", "")).lower().strip().strip(".")
        loc = str(d.get("location", "")).strip()
        try:
            conf = max(0.0, min(1.0, float(d.get("confidence", 0))))
        except (TypeError, ValueError):
            conf = 0.0
        if not item or not loc:
            continue
        if item not in best or conf > best[item]["confidence"]:
            best[item] = {"item": item, "location": loc, "confidence": conf}
    return list(best.values())


# ======================================================================
# The watcher
# ======================================================================
_STOP = set("""the a an of is are it its on in at by to near next beside behind under underneath
over above top inside onto into with and from sitting lying placed resting left right front back side
edge corner middle center centre""".split())


def _landmarks(s: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words if w not in _STOP}


def same_place(a: str, b: str, threshold: float = 0.5) -> bool:
    """Gemini rephrases, so compare landmark words, not strings:
    'on the kitchen table by the fruit bowl' == 'next to the fruit bowl on the kitchen table',
    but 'on the coffee table' != 'on the kitchen table'."""
    wa, wb = _landmarks(a), _landmarks(b)
    if not wa or not wb:
        return a.strip().lower() == b.strip().lower()
    if wa <= wb or wb <= wa:              # one is just a more detailed version of the other
        return True
    return len(wa & wb) / len(wa | wb) >= threshold


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "item"


class VisionWatcher:
    """Polls a FrameSource, asks Gemini about changed frames, and logs new/moved items to memory.

    on_item(event) is called for every logged item: {'item','location','confidence','snapshot','id'}.
    """

    def __init__(self, source: FrameSource, interval: float = 3.0, diff_threshold: float = 0.002,
                 force_every: float = 60.0,
                 min_confidence: float = 0.5, describe: Callable[[bytes], list[dict]] | None = None,
                 snapshot_dir: str | Path | None = None, on_item: Callable[[dict], None] | None = None):
        self.source = source
        self.interval = interval
        self.diff_threshold = diff_threshold      # fraction of thumbnail pixels that must change
        self.force_every = force_every            # describe at least this often (s) even if nothing changed; 0 = never
        self._last_described = 0.0
        self.min_confidence = min_confidence
        self.describe = describe or describe_frame
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else config.ROOT / "snapshots"
        self.on_item = on_item
        self.known: dict[str, str] = {}       # item -> last logged location (this run)
        self.last_seen: list[dict] = []       # last detections, whatever changed or not
        self.stats = {"frames": 0, "skipped": 0, "described": 0, "logged": 0}
        self._last_sig = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- one tick ----
    def step(self) -> list[dict]:
        """Grab one frame; if it changed enough, describe it and log new/moved items. Returns what was logged."""
        jpeg = self.source.read()
        if not jpeg:
            return []
        with self._lock:
            self.stats["frames"] += 1
            sig = frame_signature(jpeg)
            stale = self.force_every and time.monotonic() - self._last_described >= self.force_every
            if (self._last_sig is not None and not stale
                    and frame_difference(sig, self._last_sig) < self.diff_threshold):
                self.stats["skipped"] += 1
                return []
            self._last_sig = sig
        return self._process(jpeg)[1]

    def look_now(self) -> list[dict]:
        """On demand: describe the current frame regardless of change. Logs new/moved items too.
        Returns every item seen, [{'item','location','confidence'}]."""
        jpeg = self.source.read()
        if not jpeg:
            return []
        with self._lock:
            self._last_sig = frame_signature(jpeg)
        return self._process(jpeg)[0]

    def _process(self, jpeg: bytes) -> tuple[list[dict], list[dict]]:
        found = [d for d in _clean(self.describe(jpeg)) if d["confidence"] >= self.min_confidence]
        logged = []
        with self._lock:
            self._last_described = time.monotonic()
            self.stats["described"] += 1
            self.last_seen = found
            for d in found:
                if self._is_new_or_moved(d["item"], d["location"]):
                    logged.append(self._log(d, jpeg))
        return found, logged

    def _is_new_or_moved(self, item: str, location: str) -> bool:
        prev = self.known.get(item)
        if prev is None:
            # after a restart, don't re-log what memory already has in the same spot
            m = memory.find_item(item)
            if m and m["item"] == item and same_place(m["location"], location):
                self.known[item] = m["location"]
                return False
            return True
        return not same_place(prev, location)

    def _log(self, d: dict, jpeg: bytes) -> dict:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = self.snapshot_dir / f"{ts}_{_slug(d['item'])}.jpg"
        n = 1
        while path.exists():
            path = self.snapshot_dir / f"{ts}_{_slug(d['item'])}-{n}.jpg"
            n += 1
        path.write_bytes(jpeg)
        try:
            rel = str(path.resolve().relative_to(config.ROOT.resolve()))
        except ValueError:
            rel = str(path)
        rid = memory.add_item(d["item"], d["location"], source="vision", snapshot=rel)
        self.known[d["item"]] = d["location"]
        self.stats["logged"] += 1
        ev = {**d, "snapshot": rel, "id": rid}
        log.info("vision: %s -> %s (%.0f%%) [%s]", d["item"], d["location"], d["confidence"] * 100, rel)
        if self.on_item:
            try:
                self.on_item(ev)
            except Exception:
                log.exception("vision: on_item callback failed")
        return ev

    # ---- background thread ----
    def start(self) -> "VisionWatcher":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="kin-vision", daemon=True)
        self._thread.start()
        log.info("vision: watching every %.1fs", self.interval)
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                self.step()
            except Exception:
                log.exception("vision: step failed")
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - t0)))

    def stop(self, close_source: bool = False) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 30)
            self._thread = None
        if close_source:
            self.source.close()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


def make_source(webcam: int | None = None, folder: str | None = None, url: str | None = None) -> FrameSource:
    if folder:
        return FolderSource(folder)
    if url:
        return MarvSource(url)
    return WebcamSource(webcam or 0)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m kin.vision", description="Kin vision watcher")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--webcam", type=int, metavar="INDEX", help="webcam index (default 0)")
    g.add_argument("--folder", help="replay JPEGs from a folder")
    g.add_argument("--url", help="camera stream URL (RTSP/HTTP), e.g. Marv Labs glasses")
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--once", action="store_true", help="look once, print, and exit")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    src = make_source(a.webcam, a.folder, a.url)
    w = VisionWatcher(src, interval=a.interval)
    if a.once:
        for d in w.look_now():
            print(f"{d['item']}: {d['location']} ({d['confidence']:.0%})")
        src.close()
        return
    w.start()
    try:
        while True:
            time.sleep(10)
            log.info("vision: %s", w.stats)
    except KeyboardInterrupt:
        pass
    finally:
        w.stop(close_source=True)


if __name__ == "__main__":
    main()
