"""Kin's eyes: watch a camera, notice where personal items are, remember it.

    source  = WebcamSource(0)            # or FolderSource("demo_frames"), MarvSource("rtsp://...")
    watcher = VisionWatcher(source)      # every 0.5 s: grab -> wait till still -> skip if unchanged -> Gemini -> memory
    watcher.start()                      # daemon thread
    watcher.what_do_you_see()            # "Kin, what do you see?" -> {'sentence', 'items', 'snapshot'}
    watcher.look_now()                   # items only -> [{'item','location','confidence'}]
    watcher.stop()

    normalize_item("car keys") -> "keys"     # same names for voice + vision
    where_is("my reading glasses")           # memory row incl. 'snapshot', name-normalised
    describe_scene(jpeg) -> "You're at your desk; your keys are next to the laptop."
    enroll_face(name, jpeg) / who_is_in_frame(jpeg)   # OPTIONAL, family-enrolled people only

New items, or items whose location changed, are saved as snapshots/<ts>_<item>.jpg and logged
with memory.add_item(item, location, source='vision', snapshot='snapshots/...').

CLI:  python -m kin.vision --webcam 0 | --folder path | --url URL  [--interval 0.5] [--once | --see]
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
    import numpy as np
except ImportError:
    np = None


class _LazyCV2:
    """Imports OpenCV on first use only: importing it next to PyAV prints scary (harmless) duplicate-class
    warnings, and Kin's ears/brain only need normalize_item from this module."""
    _mod = None

    def __getattr__(self, name):
        if _LazyCV2._mod is None:
            import cv2 as _cv2
            _LazyCV2._mod = _cv2
        return getattr(_LazyCV2._mod, name)

    def __bool__(self):
        try:
            import importlib.util
            return importlib.util.find_spec("cv2") is not None
        except Exception:
            return False


cv2 = _LazyCV2()


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
        self._warned_at = 0.0

    def _open(self):
        self._cap = cv2.VideoCapture(self.target)
        if not self._cap.isOpened():
            if time.monotonic() - self._warned_at > 30:       # don't spam every tick
                log.warning("vision: could not open camera %r (on macOS: allow camera access for this app "
                            "in System Settings > Privacy & Security > Camera)", self.target)
                self._warned_at = time.monotonic()
            self._cap = None
            return
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)     # we poll slowly: always want the newest frame

    def read(self) -> bytes | None:
        with self._lock:
            if self._cap is None:
                self._open()
                if self._cap is None:
                    return None
            if isinstance(self.target, int):
                self._cap.grab()                       # drop a possibly stale buffered frame
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
# Item names: one canonical name per thing, so "where are my car keys?" finds "keys"
# ======================================================================
_SINGLE = {   # one-word synonyms
    "keys": "key keys keyring keyrings keychain fob",
    "glasses": "glasses eyeglasses readers spectacles specs eyewear",
    "sunglasses": "sunglasses shades",
    "wallet": "wallet billfold cardholder",
    "handbag": "handbag purse bag tote",
    "phone": "phone phones cellphone mobile smartphone iphone android telephone",
    "pills": "pill pills medication medications medicine medicines meds tablets pillbox vitamins",
    "tv remote": "remote remotes",
    "hearing aids": "hearing-aid hearing-aids",
    "watch": "watch wristwatch smartwatch",
    "cane": "cane",
    "hat": "hat cap",
    "umbrella": "umbrella umbrellas brolly",
}
_MULTI = {    # multi-word phrases (matched at the end of the name, longest first)
    "keys": "car key|car keys|house key|house keys|door key|door keys|key ring|key rings|key chain|key fob|"
            "set of keys|bunch of keys",
    "glasses": "eye glasses|reading glasses|pair of glasses|prescription glasses",
    "sunglasses": "sun glasses",
    "wallet": "card holder",
    "handbag": "hand bag|tote bag|shoulder bag",
    "phone": "cell phone|mobile phone|smart phone|android phone",
    "pills": "pill bottle|pill bottles|pill box|pill organizer|pill organiser|pill case|prescription bottle|"
             "medicine bottle|bottle of pills",
    "tv remote": "remote control|tv remote|television remote|tv remote control",
    "hearing aids": "hearing aid|hearing aids",
    "watch": "wrist watch|smart watch",
    "cane": "walking stick|walking cane",
    "hat": "baseball cap",
}
_PHRASES: dict[str, str] = {w: c for c, ws in _SINGLE.items() for w in ws.split()}
_PHRASES.update({p: c for c, ps in _MULTI.items() for p in ps.split("|")})
_FILLER = re.compile(r"^(?:my|the|a|an|your|his|her|their|our|some|old|new)\s+")
_CUT = re.compile(r"\s(?:on|in|at|with|by|near|from|for)\s.*$")


def _canon_tail(words: list[str]) -> str | None:
    for n in range(min(len(words), 4), 0, -1):
        tail = " ".join(words[-n:])
        if tail in _PHRASES:
            return _PHRASES[tail]
    return None


def normalize_item(name: str) -> str:
    """Canonical everyday name for an item, so voice and vision agree:
    'Car Keys' / 'key' / 'my keyring' -> 'keys', 'reading glasses' / 'eyeglasses' -> 'glasses',
    'black leather wallet' -> 'wallet', 'iPhone' -> 'phone', 'pill bottle' -> 'pills',
    'keys on a ring' -> 'keys'. Unknown things are just cleaned up: 'Blue Books.' -> 'blue book'."""
    s = " ".join(re.sub(r"[^a-z0-9 -]+", " ", str(name).lower().replace("'s ", " ")).split())
    s = s.replace("hearing aid", "hearing-aid")
    while (t := _FILLER.sub("", s)) != s:
        s = t
    s = _CUT.sub("", s).strip()
    if not s:
        return ""
    if s in _PHRASES:
        return _PHRASES[s]
    words = s.split()
    canon = _canon_tail(words)
    if canon:
        return canon
    if " of " in s:                                 # 'bottle of pills', 'set of car keys'
        canon = _canon_tail(s.split(" of ", 1)[1].split())
        if canon:
            return canon
    last = words[-1]
    if last.endswith("ies") and len(last) > 4:
        last = last[:-3] + "y"
    elif last.endswith("es") and last[:-2].endswith(("sh", "ch", "x", "ss")):
        last = last[:-2]
    elif last.endswith("s") and not last.endswith(("ss", "us")) and len(last) > 3:
        last = last[:-1]
    words[-1] = last
    return " ".join(words).replace("-", " ")


def where_is(name: str) -> dict | None:
    """memory.find_item with name normalising: latest row for 'car keys' / 'my reading glasses' etc.
    Returns the memory row (item, location, ts, source, snapshot) or None."""
    canon = normalize_item(name)
    return (memory.find_item(canon) if canon else None) or memory.find_item(str(name))


# ======================================================================
# Gemini: what personal items are visible, and where?
# ======================================================================
PROMPT = """You are the eyes of a memory helper for an older person with early memory loss.
Look at this photo and list the PERSONAL ITEMS that have been PUT DOWN somewhere and are clearly visible -
things people misplace: keys, glasses, sunglasses, wallet, purse or handbag, phone, pills or pill bottle,
pill organizer, TV remote, hearing aids, watch, cane, hat, umbrella.
Do NOT list: furniture, people, computers, keyboards, cups, food, or anything you are not sure is there.
Do NOT list items someone is holding or wearing (glasses on a face, a watch on a wrist, a phone in a hand).

For each item give:
- item: a short everyday name, lowercase, singular ("keys", "glasses", "wallet", "phone", "pills", "tv remote")
- location: where it is, in plain friendly words relative to furniture or landmarks an older person
  knows, like "on the desk next to the laptop" or "on the arm of the blue sofa".
  No left/right of the image, no coordinates, no technical words.
- confidence: 0.0 to 1.0, how sure you are the item is really there.

Return an empty list if no such items are visible."""

KNOWN_HINT = """
Items already remembered, and where:
{known}
If one of these is still in the same spot, describe that spot with EXACTLY the same words as above."""

SCENE_PROMPT = """You are the eyes of a memory helper for an older person with early memory loss.
They just asked "what do you see?". Answer in ONE short, warm, plain sentence (max 25 words), spoken out loud,
describing what is in front of them - the room or surface and the most useful things on it.
Don't mention image quality, cameras, or that this is a photo."""

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


class GeminiBusy(Exception):
    """Gemini said 429 / 5xx; we're backing off. `retry_in` = seconds until the next attempt is allowed."""

    def __init__(self, msg: str = "", retry_in: float = 0.0):
        super().__init__(msg)
        self.retry_in = retry_in


BACKOFF_START, BACKOFF_MAX = 2.0, 30.0
_busy_until = 0.0
_busy_delay = 0.0
_thinking_ok = True            # thinking_budget=0 saves ~0.3 s; switched off if the model rejects it


def busy_for() -> float:
    """Seconds left in the current Gemini back-off (0 = go ahead)."""
    return max(0.0, _busy_until - time.monotonic())


def _note_busy(e: Exception) -> GeminiBusy:
    global _busy_until, _busy_delay
    _busy_delay = min(BACKOFF_MAX, max(BACKOFF_START, _busy_delay * 2))
    _busy_until = time.monotonic() + _busy_delay
    log.warning("vision: Gemini busy (%s) - backing off %.0fs", str(e)[:80], _busy_delay)
    return GeminiBusy(str(e), _busy_delay)


def _is_busy_error(e: Exception) -> bool:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if isinstance(code, int) and (code == 429 or code >= 500):
        return True
    s = str(e)
    return any(t in s for t in ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "429", "503", "overloaded", "timed out"))


_client_lock = threading.Lock()


def _gemini():
    global _client
    with _client_lock:      # two threads creating clients at once -> one gets closed mid-request
        if _client is None:
            from google import genai
            _client = genai.Client(api_key=config.GEMINI_API_KEY)
        return _client


def _shrink(jpeg: bytes, max_width: int = 768) -> bytes:
    """Smaller upload = faster answer. Snapshots keep the full frame; Gemini gets <= 768 px wide."""
    if cv2 is None:
        return jpeg
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None or img.shape[1] <= max_width:
        return jpeg
    h, w = img.shape[:2]
    img = cv2.resize(img, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else jpeg


def _have_key() -> bool:
    global _warned_no_key
    if config.GEMINI_API_KEY:
        return True
    if not _warned_no_key:
        log.warning("vision: GEMINI_API_KEY missing - vision returns nothing (disabled)")
        _warned_no_key = True
    return False


def _generate(parts: list, schema=None, temperature: float = 0.1) -> str:
    """One Gemini call. Raises GeminiBusy on 429/5xx (and starts a back-off); other errors propagate."""
    global _busy_delay, _thinking_ok
    from google.genai import types
    kw = {"temperature": temperature}
    if schema is not None:
        kw.update(response_mime_type="application/json", response_schema=schema)
    for attempt in (0, 1):
        if _thinking_ok:
            kw["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        else:
            kw.pop("thinking_config", None)
        try:
            resp = _gemini().models.generate_content(
                model=config.GEMINI_MODEL, contents=parts, config=types.GenerateContentConfig(**kw))
            _busy_delay = 0.0
            return resp.text or ""
        except Exception as e:
            if _thinking_ok and attempt == 0 and "hink" in str(e) and getattr(e, "code", 0) == 400:
                _thinking_ok = False         # model doesn't take a thinking budget: retry without it
                continue
            if _is_busy_error(e):
                raise _note_busy(e) from e
            raise
    return ""


def detect_items(jpeg: bytes, known: dict[str, str] | None = None) -> list[dict]:
    """Like describe_frame but raises GeminiBusy when rate-limited (the watcher uses this to back off).
    `known` = {item: location} already remembered, so Gemini reuses the same wording for unmoved things."""
    if not jpeg or not _have_key():
        return []
    from google.genai import types
    prompt = PROMPT
    if known:
        prompt += KNOWN_HINT.format(known="\n".join(f"- {k}: {v}" for k, v in known.items()))
    text = _generate([types.Part.from_bytes(data=_shrink(jpeg), mime_type="image/jpeg"), prompt],
                     RESPONSE_SCHEMA)
    return _clean(json.loads(text or "[]"))


def describe_frame(jpeg: bytes, known: dict[str, str] | None = None) -> list[dict]:
    """Ask Gemini which personal items are in the frame. Returns [{'item','location','confidence'}].
    Returns [] without a GEMINI_API_KEY (logged once), while backing off, or on any API error (logged)."""
    try:
        return detect_items(jpeg, known)
    except GeminiBusy:
        return []
    except Exception as e:
        log.warning("vision: Gemini call failed: %s", e)
        return []


def describe_scene(jpeg: bytes) -> str:
    """One plain spoken sentence about what the camera sees ("You're at your desk; your keys are next to
    the laptop."). Returns "" without a key / on error (caller says "I can't see right now")."""
    if not jpeg or not _have_key():
        return ""
    from google.genai import types
    try:
        text = _generate([types.Part.from_bytes(data=_shrink(jpeg), mime_type="image/jpeg"), SCENE_PROMPT],
                         temperature=0.3)
    except Exception as e:
        log.warning("vision: describe_scene failed: %s", e)
        return ""
    text = " ".join(text.split()).strip().strip('"')
    m = re.match(r"(.+?[.!?])(\s|$)", text)        # keep it to one sentence
    return (m.group(1) if m else text)[:300]


def _clean(raw) -> list[dict]:
    """Normalise model output (canonical item names); merge duplicates (keep the most confident)."""
    if isinstance(raw, dict):
        raw = raw.get("items", [])
    best: dict[str, dict] = {}
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict):
            continue
        item = normalize_item(d.get("item", ""))
        loc = " ".join(str(d.get("location", "")).split()).strip().rstrip(".")
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
# Faces (OPTIONAL, consent-based): only people the family enrolls
# ======================================================================
FACES_DIR = config.ROOT / "snapshots" / "faces"

FACE_PROMPT = """The first image is a camera frame. The following images are reference photos of people the
family has enrolled, each preceded by that person's name. Which of the enrolled people are clearly visible in the
camera frame? Only answer with names from the list, and only if you are confident it is the same person.
Return JSON: a list of names (empty if none)."""


def enroll_face(name: str, jpeg: bytes, faces_dir: str | Path | None = None) -> str:
    """Store a reference photo for a person the FAMILY chose to enroll. Returns the saved path.
    Consent rule: never call this for someone who wasn't explicitly enrolled by the family."""
    if not name.strip() or not jpeg:
        raise ValueError("enroll_face needs a name and a photo")
    d = Path(faces_dir or FACES_DIR) / _slug(name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "name.txt").write_text(name.strip())
    path = d / f"{time.strftime('%Y%m%d-%H%M%S')}-{len(list(d.glob('*.jpg')))}.jpg"
    path.write_bytes(jpeg)
    return str(path)


def enrolled_faces(faces_dir: str | Path | None = None) -> dict[str, list[Path]]:
    """{name: [reference photo paths]} for everyone enrolled."""
    root = Path(faces_dir or FACES_DIR)
    out: dict[str, list[Path]] = {}
    if not root.is_dir():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        photos = sorted(d.glob("*.jpg"))
        if photos:
            name = (d / "name.txt").read_text().strip() if (d / "name.txt").exists() else d.name
            out[name] = photos
    return out


def who_is_in_frame(jpeg: bytes, faces_dir: str | Path | None = None, per_person: int = 2) -> list[str]:
    """Names of ENROLLED people Gemini recognises in the frame ([] if none, nobody enrolled, or no key)."""
    faces = enrolled_faces(faces_dir)
    if not jpeg or not faces or not _have_key():
        return []
    from google.genai import types
    parts = [types.Part.from_bytes(data=_shrink(jpeg), mime_type="image/jpeg")]
    for name, photos in faces.items():
        parts.append(f"Enrolled person: {name}")
        parts += [types.Part.from_bytes(data=_shrink(p.read_bytes(), 384), mime_type="image/jpeg")
                  for p in photos[-per_person:]]
    parts.append(FACE_PROMPT)
    try:
        names = json.loads(_generate(parts, {"type": "ARRAY", "items": {"type": "STRING"}}) or "[]")
    except Exception as e:
        log.warning("vision: who_is_in_frame failed: %s", e)
        return []
    known = {n.lower(): n for n in faces}
    return [known[n.lower().strip()] for n in names if isinstance(n, str) and n.lower().strip() in known]


# ======================================================================
# The watcher
# ======================================================================
_STOP = set("""the a an of is are it its on in at by to near next beside behind under underneath
over above top inside onto into with and from sitting lying placed resting left right front back side
edge corner middle center centre""".split())
_PREP = set("on in at by near next beside behind under underneath over above top inside onto into with".split())


def _landmarks(s: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words if w not in _STOP}


def _surface(s: str) -> set[str]:
    """The first landmark phrase: 'on the wooden desk next to the laptop' -> {'wooden','desk'}."""
    words = re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()
    out, started = [], False
    for w in words:
        if w in _STOP:
            if started and (w in _PREP or w in ("and", "next", "beside")):
                break
            continue
        started = True
        out.append(w[:-1] if w.endswith("s") and len(w) > 3 else w)
    return set(out)


def same_place(a: str, b: str, threshold: float = 0.5) -> bool:
    """Gemini rephrases, so compare landmark words, not strings:
    'on the kitchen table by the fruit bowl' == 'next to the fruit bowl on the kitchen table',
    'on the desk next to the laptop' == 'on the wooden desk in front of the keyboard' (same surface),
    but 'on the coffee table' != 'on the kitchen table'."""
    wa, wb = _landmarks(a), _landmarks(b)
    if not wa or not wb:
        return a.strip().lower() == b.strip().lower()
    if wa <= wb or wb <= wa:              # one is just a more detailed version of the other
        return True
    if len(wa & wb) / len(wa | wb) >= threshold:
        return True
    sa, sb = _surface(a), _surface(b)     # same surface, different neighbour: still the same spot
    return bool(sa and sb and (sa <= sb or sb <= sa))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "item"


class VisionWatcher:
    """Polls a FrameSource, asks Gemini about changed frames, and logs new/moved items to memory.

    Each tick (every `interval` s):
      1. motion check vs the previous frame - if the scene is still moving (a person walking through,
         a hand putting keys down) wait; nothing is sent to Gemini until it has been still for
         `settle` ticks. So walking through the frame costs no Gemini calls and logs nothing.
      2. change check vs the last frame Gemini saw - unchanged scenes are skipped (re-checked every
         `force_every` s anyway).
      3. Gemini lists items + plain locations; new or moved items are logged once (snapshot + memory).
    Gemini 429/5xx -> exponential back-off (2 s .. 30 s), the frame is retried afterwards.

    on_item(event) is called for every logged item: {'item','location','confidence','snapshot','id'}.
    """

    def __init__(self, source: FrameSource, interval: float = 0.5, diff_threshold: float = 0.002,
                 motion_threshold: float = 0.01, settle: int = 1, force_every: float = 60.0,
                 min_confidence: float = 0.6, describe: Callable[[bytes], list[dict]] | None = None,
                 snapshot_dir: str | Path | None = None, on_item: Callable[[dict], None] | None = None):
        self.source = source
        self.interval = interval
        self.diff_threshold = diff_threshold      # fraction of thumbnail pixels that must change vs last described
        self.motion_threshold = motion_threshold  # frame-to-frame change above this = still moving, wait
        self.settle = settle                      # still ticks required before describing (0 = don't wait)
        self.force_every = force_every            # describe at least this often (s) even if nothing changed; 0 = never
        self._last_described = 0.0
        self.min_confidence = min_confidence
        self.describe = describe                  # None = Gemini (detect_items, with back-off + wording hints)
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else config.ROOT / "snapshots"
        self.on_item = on_item
        self.known: dict[str, str] = {}       # item -> last logged location (this run)
        self.last_seen: list[dict] = []       # last detections, whatever changed or not
        self.last_latency = 0.0               # seconds the last Gemini call took
        self.stats = {"frames": 0, "skipped": 0, "moving": 0, "described": 0, "logged": 0, "busy": 0}
        self._last_sig = None                 # last frame Gemini described
        self._prev_sig = None                 # previous polled frame (motion)
        self._still = 0
        self._last_jpeg: bytes | None = None
        self._lock = threading.Lock()
        self._gemini_lock = threading.Lock()  # look_now and the thread never call Gemini at the same time
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- one tick ----
    def step(self) -> list[dict]:
        """Grab one frame; if it changed enough and has settled, describe it and log new/moved items.
        Returns what was logged."""
        jpeg = self.source.read()
        if not jpeg:
            return []
        with self._lock:
            self.stats["frames"] += 1
            self._last_jpeg = jpeg
            sig = frame_signature(jpeg)
            motion = frame_difference(sig, self._prev_sig)
            self._prev_sig = sig
            if self.settle:
                if motion >= self.motion_threshold:
                    self._still = 0
                    self.stats["moving"] += 1
                    return []
                self._still += 1
                if self._still < self.settle:
                    self.stats["moving"] += 1
                    return []
            stale = self.force_every and time.monotonic() - self._last_described >= self.force_every
            if (self._last_sig is not None and not stale
                    and frame_difference(sig, self._last_sig) < self.diff_threshold):
                self.stats["skipped"] += 1
                return []
            if self.describe is None and busy_for() > 0:
                self.stats["busy"] += 1
                return []
        return self._process(jpeg, sig)[1]

    def _frame_now(self) -> bytes | None:
        jpeg = self.source.read()
        if jpeg:
            self._last_jpeg = jpeg
        return jpeg or self._last_jpeg

    def look_now(self) -> list[dict]:
        """On demand: describe the current frame regardless of change. Logs new/moved items too.
        Returns every item seen, [{'item','location','confidence'}]."""
        jpeg = self._frame_now()
        if not jpeg:
            return []
        return self._process(jpeg, frame_signature(jpeg))[0]

    def what_do_you_see(self) -> dict:
        """For "Kin, what do you see?": {'sentence': one plain sentence, 'items': [...], 'snapshot': jpeg bytes}.
        The two Gemini calls run in parallel (~2-3 s total). sentence is "" if Gemini is unavailable."""
        jpeg = self._frame_now()
        if not jpeg:
            return {"sentence": "", "items": [], "snapshot": None}
        box: dict = {}
        t = threading.Thread(target=lambda: box.update(s=describe_scene(jpeg)), daemon=True)
        t.start()
        items = self._process(jpeg, frame_signature(jpeg))[0]
        t.join(timeout=20)
        return {"sentence": box.get("s", ""), "items": items, "snapshot": jpeg}

    def _call(self, jpeg: bytes) -> list[dict] | None:
        """Run the describer. None = Gemini busy (don't treat the frame as seen)."""
        try:
            if self.describe is None:
                return detect_items(jpeg, dict(self.known))
            return self.describe(jpeg)
        except GeminiBusy:
            self.stats["busy"] += 1
            return None
        except Exception as e:
            log.warning("vision: Gemini call failed: %s", e)
            return None

    def _process(self, jpeg: bytes, sig=None) -> tuple[list[dict], list[dict]]:
        with self._gemini_lock:
            t0 = time.monotonic()
            raw = self._call(jpeg)
            latency = time.monotonic() - t0
        if raw is None:
            return [], []
        found = [d for d in _clean(raw) if d["confidence"] >= self.min_confidence]
        logged = []
        with self._lock:
            self.last_latency = latency
            self._last_described = time.monotonic()
            if sig is not None:
                self._last_sig = sig
            self.stats["described"] += 1
            self.last_seen = found
            for d in found:
                if self._is_new_or_moved(d["item"], d["location"]):
                    logged.append(self._log(d, jpeg))
        log.debug("vision: Gemini %.2fs -> %s", latency, found)
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
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--once", action="store_true", help="look once, print, and exit")
    ap.add_argument("--see", action="store_true", help='answer "what do you see?" once and exit')
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    src = make_source(a.webcam, a.folder, a.url)
    w = VisionWatcher(src, interval=a.interval)
    if a.see:
        for _ in range(10):                  # webcams need a few frames to expose
            src.read()
        t0 = time.monotonic()
        r = w.what_do_you_see()
        print(f"{r['sentence']}  ({time.monotonic() - t0:.1f}s)")
        for d in r["items"]:
            print(f"  {d['item']}: {d['location']} ({d['confidence']:.0%})")
        src.close()
        return
    if a.once:
        for _ in range(10):
            src.read()
        for d in w.look_now():
            print(f"{d['item']}: {d['location']} ({d['confidence']:.0%})")
        src.close()
        return
    w.start()
    try:
        while True:
            time.sleep(10)
            log.info("vision: %s last Gemini %.2fs", w.stats, w.last_latency)
    except KeyboardInterrupt:
        pass
    finally:
        w.stop(close_source=True)


if __name__ == "__main__":
    main()
