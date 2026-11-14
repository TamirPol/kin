"""Voiceprints: who is speaking, by voice.

The wearer (and family) say ~10 s into the band once; we keep a speaker embedding
(never the audio) in voiceprints/<name>.json and then label each utterance by voice.

Model: NVIDIA NeMo TitaNet-small (English), ONNX, run through sherpa-onnx on the CPU.
~40 MB, no torch, no Hugging Face token, ~8 ms per 2-3 s utterance on an M-series laptop. Downloaded once to ~/.cache/kin/ on first use
(override with KIN_SPEAKER_MODEL=/path/to/model.onnx).

    from kin import voiceprint
    voiceprint.warm_up()                         # loads the model (~0.3 s), do it at startup
    voiceprint.observe(pcm)    -> {'id': 'voice-3', 'name': None, 'new': True, ...}   # learns voices by itself
    voiceprint.name_voice('voice-3', 'Sarah', role='daughter')                    # later, when we learn who
    voiceprint.enroll("Ruth", pcm, role="wearer")    # optional onboarding, the most reliable path
    voiceprint.identify(pcm)   -> {'id': 'ruth', 'name': 'Ruth', 'role': 'wearer', 'score': 0.71, ...}
                               or {'id': None, 'name': None, 'role': None, 'score': 0.22, ...}

All PCM is 16-bit little-endian mono. Everything here is synchronous and thread-safe.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
VOICE_DIR = Path(os.environ.get("KIN_VOICEPRINTS", ROOT / "voiceprints"))

DEFAULT_MODEL = "nemo_en_titanet_small"
MODEL_PATH = Path(os.environ.get("KIN_SPEAKER_MODEL",
                                 Path.home() / ".cache" / "kin" / f"{DEFAULT_MODEL}.onnx"))
MODEL_NAME = MODEL_PATH.stem        # stored with each voiceprint; prints from another model are ignored
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             f"speaker-recongition-models/{MODEL_NAME}.onnx")

# Cosine score on unit embeddings. Calibrated with 10 distinct macOS `say` voices, 6 test sentences
# each, clean and mixed with noise / two other voices (babble) at 15, 10 and 5 dB SNR:
#   same voice:      mean 0.64-0.88, p5 0.35-0.78 (lowest in heavy noise)
#   different voice: mean 0.13-0.24, p99 0.41-0.58, max 0.64
# At 0.50: 0-5% false rejects (up to ~25% at 10 dB white noise), ~1% false accepts per pair.
# Top-1 among enrolled voices: 94-100% even at babble 5 dB. Tune with KIN_VOICE_THRESHOLD.
THRESHOLD = float(os.environ.get("KIN_VOICE_THRESHOLD", "0.50"))
ADAPT_MIN = THRESHOLD + 0.20     # adapt() only learns from clearly-confident matches (> any impostor seen)
OBSERVE_ADAPT_MIN = THRESHOLD + 0.10   # observe() refines a voice at this score...
MARGIN_MIN = 0.10                # ...when it is also this far ahead of the second-best voice
CAP_SAMPLES = 20                 # running average: one new clip always weighs >= 1/21
NEW_MIN_SPEECH_S = 1.5           # observe() learns a new voice only from clips with this much speech,
NEW_MIN_SPREAD_DB = 10.0         # that stand out from the room (see _quality),
ANON_THRESHOLD = float(os.environ.get("KIN_ANON_VOICE_THRESHOLD", "0.65"))  # stricter bar to match an
                                 # unnamed (auto-learned) voice: splitting one person in two is cheap
                                 # (name_voice merges), merging two people is not
ANON_ADAPT_MIN = ADAPT_MIN       # an unnamed voice only learns from clearly-same clips
AUTO_MERGE_MIN = 0.80            # an unnamed voice this close to another voice is folded into it
NEW_MAX_SCORE = 0.45             # that aren't borderline-similar to a known voice (0.45 up to the bar = unsure),
HALVES_MIN = 0.50                # and whose two halves sound like one person (clips >= 3 s)
MAX_ANON = int(os.environ.get("KIN_MAX_ANON_VOICES", "30"))   # least-recently-heard unnamed voices dropped
MIN_SPEECH_S = 1.0               # embed() returns None below this much speech
MAX_SPEECH_S = 20.0              # longer input is cut (keeps per-utterance latency bounded)
FRAME_S = 0.02

_model_lock = threading.Lock()
_extractor = None
_store_lock = threading.RLock()
_voices: dict[str, dict] | None = None
_voices_mtime = -1.0


# ---------------------------------------------------------------- model

def _download():
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODEL_PATH.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    if tmp.stat().st_size < 1_000_000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"speaker model download failed: {MODEL_URL}")
    tmp.rename(MODEL_PATH)


def _get_extractor():
    global _extractor
    if _extractor is None:
        with _model_lock:
            if _extractor is None:
                import sherpa_onnx
                if not MODEL_PATH.exists():
                    _download()
                cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(MODEL_PATH), num_threads=int(os.environ.get("KIN_SPEAKER_THREADS", "2")))
                if not cfg.validate():
                    raise RuntimeError(f"bad speaker model config: {MODEL_PATH}")
                _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    return _extractor


def warm_up() -> None:
    """Loads the model and runs it once so the first real utterance is fast."""
    rng = np.random.default_rng(0)
    t = np.arange(16000 * 2) / 16000
    x = (0.3 * np.sin(2 * np.pi * 180 * t) * (1 + np.sin(2 * np.pi * 3 * t)) + 0.05 * rng.normal(size=t.size))
    _embed_float(x.astype(np.float32), 16000)


# ---------------------------------------------------------------- audio

def _to_float(pcm: bytes) -> np.ndarray:
    if len(pcm) % 2:
        pcm = pcm[:-1]
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def _resample(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == 16000 or x.size == 0:
        return x
    n = int(round(x.size * 16000 / rate))
    return np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x).astype(np.float32)


def _speech(x: np.ndarray, rate: int = 16000) -> np.ndarray:
    """Drops silent frames (simple energy VAD) so pauses don't dilute the voiceprint."""
    f = int(rate * FRAME_S)
    n = x.size // f
    if n == 0:
        return x[:0]
    frames = x[: n * f].reshape(n, f)
    db = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-10)
    floor = np.percentile(db, 10)
    keep = (db > max(floor + 8.0, -55.0))
    # one frame of hangover on each side so word edges survive
    keep = keep | np.roll(keep, 1) | np.roll(keep, -1)
    return frames[keep].reshape(-1)


def speech_seconds(pcm: bytes, rate: int = 16000) -> float:
    """How much speech (not silence) is in the PCM. Handy for the onboarding page."""
    return _speech(_resample(_to_float(pcm), rate)).size / 16000


def _embed_float(x: np.ndarray, rate: int) -> np.ndarray | None:
    x = _speech(_resample(x, rate))
    if x.size < MIN_SPEECH_S * 16000:
        return None
    x = x[-int(MAX_SPEECH_S * 16000):]
    ext = _get_extractor()
    with _model_lock:           # one inference at a time; sherpa streams are cheap
        s = ext.create_stream()
        s.accept_waveform(16000, x)
        s.input_finished()
        if not ext.is_ready(s):
            return None
        e = np.asarray(ext.compute(s), dtype=np.float32)
    nrm = float(np.linalg.norm(e))
    return e / nrm if nrm > 0 else None


def embed(pcm: bytes, rate: int = 16000) -> list[float] | None:
    """Unit-length speaker embedding of 16-bit mono PCM, or None if < ~1 s of speech."""
    e = _embed_float(_to_float(pcm), rate)
    return None if e is None else e.tolist()



def _quality(x: np.ndarray, rate: int) -> tuple[float, float]:
    """(speech seconds, loudness spread in dB = p90 - p10 of 20 ms frame energy).

    Clean speech spreads ~23 dB; speech with two other talkers 5 dB down ~12 dB; under 10 dB the
    talker barely stands out from the room, so we don't learn a new voice from it."""
    x = _resample(x, rate)
    f = int(16000 * FRAME_S)
    n = x.size // f
    if n < 10:
        return 0.0, 0.0
    db = 10 * np.log10(np.mean(x[: n * f].reshape(n, f) ** 2, axis=1) + 1e-10)
    return _speech(x).size / 16000, float(np.percentile(db, 90) - np.percentile(db, 10))


# ---------------------------------------------------------------- storage
# One JSON per voice: voiceprints/<id>.json. id is the name's slug for enrolled voices and
# 'voice-N' for voices Kin learned on its own (name None until name_voice()). ids never change,
# so the app can keep e.g. a Deepgram-speaker -> voice id map.

def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "person"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _dir_mtime() -> float:
    try:
        return VOICE_DIR.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _load() -> dict[str, dict]:
    """All voiceprints keyed by id; re-read when the folder changes (another process wrote)."""
    global _voices, _voices_mtime
    with _store_lock:
        m = _dir_mtime()
        if _voices is None or m != _voices_mtime:
            v = {}
            for p in sorted(VOICE_DIR.glob("*.json")) if m else []:
                try:
                    d = json.loads(p.read_text())
                    if d.get("model", MODEL_NAME) != MODEL_NAME:
                        continue           # made with a different model: not comparable
                    d.setdefault("id", p.stem)
                    d["_vec"] = _unit(np.asarray(d["embedding"], dtype=np.float32))
                    v[d["id"]] = d
                except Exception:
                    continue
            _voices, _voices_mtime = v, m
        return _voices


def _save(d: dict) -> dict:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    out = {k: v for k, v in d.items() if not k.startswith("_")}
    p = VOICE_DIR / f"{d['id']}.json"
    tmp = p.with_suffix(".tmp")
    voices = _load()
    tmp.write_text(json.dumps(out))
    tmp.replace(p)
    voices[d["id"]] = dict(out, _vec=_unit(np.asarray(out["embedding"], dtype=np.float32)))
    _sync_mtime()
    return out


def _sync_mtime() -> None:
    """Our own writes don't need a re-read of the folder."""
    global _voices_mtime
    _voices_mtime = _dir_mtime()


def _delete(vid: str) -> None:
    voices = _load()
    (VOICE_DIR / f"{vid}.json").unlink(missing_ok=True)
    voices.pop(vid, None)
    _sync_mtime()


def _public(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "embedding" and not k.startswith("_")}


def _by_name(name: str) -> dict | None:
    key = name.strip().lower()
    return next((d for d in _load().values() if (d.get("name") or "").strip().lower() == key), None)


def _blend(d: dict, e: np.ndarray, count: int = 1) -> list[float]:
    """Running average of unit embeddings; old samples are capped at CAP_SAMPLES so new ones keep a say."""
    n = min(int(d.get("n_samples", 1)), CAP_SAMPLES)
    old = _unit(np.asarray(d["embedding"], dtype=np.float32))
    return _unit((old * n + e * count) / (n + count)).tolist()


def _next_anon_id() -> str:
    """'voice-N', never reusing a number (counter kept in voiceprints/next_voice)."""
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    f = VOICE_DIR / "next_voice"
    try:
        n = int(f.read_text().strip())
    except Exception:
        n = 1
    used = [int(k[6:]) for k in _load() if re.fullmatch(r"voice-\d+", k)]
    n = max([n] + [u + 1 for u in used])
    f.write_text(str(n + 1))
    return f"voice-{n}"


def _enroll_id(name: str) -> str:
    vid = _slug(name)
    if re.fullmatch(r"voice-\d+", vid) or vid in _load():
        vid = f"{vid}-{int(time.time())}"
    return vid


def enroll(name: str, pcm: bytes, role: str = "", rate: int = 16000) -> dict:
    """Explicit onboarding: adds a sample for `name` (averaged with earlier ones) and saves it.

    Returns the stored record without the embedding, plus 'speech_s'. Raises ValueError
    when there isn't enough speech (ask them to talk a bit longer)."""
    if not name or not name.strip():
        raise ValueError("name is required")
    e = _embed_float(_to_float(pcm), rate)
    if e is None:
        raise ValueError(f"not enough speech (need at least {MIN_SPEECH_S:.0f} s of talking)")
    with _store_lock:
        old = _by_name(name)
        if old:
            d = dict(old, embedding=_blend(old, e), n_samples=int(old.get("n_samples", 1)) + 1,
                     n_enrolled=int(old.get("n_enrolled", 0)) + 1, updated=_now(), last_seen=_now(),
                     role=role or old.get("role", ""), name=name.strip())
        else:
            d = {"id": _enroll_id(name), "name": name.strip(), "role": role, "embedding": e.tolist(),
                 "n_samples": 1, "n_enrolled": 1, "n_adapted": 0, "n_seen": 0, "model": MODEL_NAME,
                 "created": _now(), "updated": _now(), "last_seen": _now()}
        out = _save(d)
    res = _public(out)
    res["speech_s"] = round(speech_seconds(pcm, rate), 1)
    return res


def _ranked(e: np.ndarray) -> list[tuple[float, dict]]:
    return sorted(((float(e @ d["_vec"]), d) for d in _load().values()), key=lambda t: -t[0])


def _match(e: np.ndarray, th: float) -> dict:
    ranked = _ranked(e)
    if not ranked:
        return {"id": None, "name": None, "role": None, "score": 0.0, "is_wearer": False,
                "closest": None, "margin": 0.0}
    best, d = ranked[0]
    margin = best - ranked[1][0] if len(ranked) > 1 else best
    hit = best >= (th if d.get("name") else max(th, ANON_THRESHOLD))
    return {"id": d["id"] if hit else None, "name": d.get("name") if hit else None,
            "role": d.get("role", "") if hit else None, "score": round(best, 3),
            "is_wearer": hit and d.get("role") == "wearer", "closest": d["id"], "margin": round(margin, 3)}


def identify(pcm: bytes, rate: int = 16000, threshold: float | None = None) -> dict:
    """Best-matching known voice (enrolled or learned). Read-only: never creates or updates.

    {'id','name','role','score','is_wearer','closest','margin'}; id/name/role None when nothing scores
    above the threshold (score None when there is too little speech). A learned voice has name None."""
    e = _embed_float(_to_float(pcm), rate)
    if e is None:
        return {"id": None, "name": None, "role": None, "score": None, "is_wearer": False,
                "closest": None, "margin": 0.0}
    return _match(e, THRESHOLD if threshold is None else threshold)


def identify_embedding(embedding: list[float], threshold: float | None = None) -> dict:
    """Same as identify() for an embedding you already computed with embed()."""
    return _match(_unit(np.asarray(embedding, dtype=np.float32)), THRESHOLD if threshold is None else threshold)


def _halves_agree(x: np.ndarray, rate: int) -> bool:
    """For clips >= 3 s: both halves sound like the same person (catches two people in one clip).
    Same speaker scored 0.68-0.86 in calibration, two speakers <= 0.31."""
    if x.size < 3 * rate:
        return True
    h = x.size // 2
    a, b = _embed_float(x[:h], rate), _embed_float(x[h:], rate)
    return a is None or b is None or float(a @ b) >= HALVES_MIN


def observe(pcm: bytes, rate: int = 16000) -> dict:
    """Identify-and-learn, for every utterance the band hears.

    Matches against all known voices. On a confident match (score >= OBSERVE_ADAPT_MIN and clearly ahead of
    the runner-up) that voice's print is refined. With no match, a clean clip (>= 1.5 s of speech, not
    drowned in noise, one speaker, not borderline-similar to someone known) becomes a new anonymous
    voice 'voice-N'. Returns {'id','name','role','score','new','is_wearer','margin','reason'};
    id None when the clip was not good enough to match or learn from (see 'reason')."""
    x = _to_float(pcm)
    none = {"id": None, "name": None, "role": None, "score": None, "new": False, "is_wearer": False, "margin": 0.0}
    e = _embed_float(x, rate)
    if e is None:
        return dict(none, reason="too little speech")
    with _store_lock:
        m = _match(e, THRESHOLD)
        if m["id"]:
            d = _load()[m["id"]]
            upd = dict(d, n_seen=int(d.get("n_seen", 0)) + 1, last_seen=_now(), seen_at=time.time())
            bar = OBSERVE_ADAPT_MIN if d.get("name") else ANON_ADAPT_MIN
            adapted = m["score"] >= bar and m["margin"] >= MARGIN_MIN
            if adapted:
                upd.update(embedding=_blend(d, e), n_samples=int(d.get("n_samples", 1)) + 1,
                           n_adapted=int(d.get("n_adapted", 0)) + 1, updated=_now())
            _save(upd)
            res = {"id": m["id"], "name": m["name"], "role": m["role"], "score": m["score"], "new": False,
                   "is_wearer": m["is_wearer"], "margin": m["margin"],
                   "reason": "matched, learned" if adapted else "matched"}
            if adapted and not d.get("name"):
                into = _auto_merge(m["id"])
                if into:
                    res.update(id=into["id"], name=into.get("name"), role=into.get("role", ""),
                               is_wearer=into.get("role") == "wearer", merged_from=m["id"])
            return res
        out = dict(none, score=m["score"], margin=m["margin"])
        secs, spread = _quality(x, rate)
        if secs < NEW_MIN_SPEECH_S:
            return dict(out, reason="too short to learn a new voice")
        if spread < NEW_MIN_SPREAD_DB:
            return dict(out, reason="too noisy to learn a new voice")
        if m["score"] >= NEW_MAX_SCORE:
            return dict(out, reason="unsure: a bit like a known voice")
        if not _halves_agree(x, rate):
            return dict(out, reason="sounds like more than one person")
        anon = sorted((d for d in _load().values() if not d.get("name")), key=lambda d: d.get("seen_at", 0))
        for d in anon[: max(0, len(anon) - MAX_ANON + 1)]:
            _delete(d["id"])                    # forget the least-recently-heard unnamed voices
        vid = _next_anon_id()
        _save({"id": vid, "name": None, "role": "", "embedding": e.tolist(), "n_samples": 1, "n_enrolled": 0,
               "n_adapted": 0, "n_seen": 1, "model": MODEL_NAME, "created": _now(), "updated": _now(),
               "last_seen": _now(), "seen_at": time.time()})
        return dict(out, id=vid, new=True, reason="new voice")


def _auto_merge(vid: str) -> dict | None:
    """Folds unnamed voice `vid` into the closest other voice if they now sound the same (>= AUTO_MERGE_MIN).
    Two named voices are never merged here."""
    voices = _load()
    d = voices.get(vid)
    if d is None or d.get("name"):
        return None
    others = [(float(d["_vec"] @ o["_vec"]), o) for k, o in voices.items() if k != vid]
    if not others:
        return None
    score, o = max(others, key=lambda t: t[0])
    if score < AUTO_MERGE_MIN:
        return None
    return _merge(d, o)


def _merge(src: dict, dst: dict) -> dict:
    """src's print is averaged into dst (weighted by samples, capped); src is deleted; dst's id is kept."""
    n1, n2 = min(int(dst.get("n_samples", 1)), CAP_SAMPLES), min(int(src.get("n_samples", 1)), CAP_SAMPLES)
    emb = _unit(dst["_vec"] * n1 + src["_vec"] * n2).tolist()
    out = _save(dict(dst, embedding=emb, role=dst.get("role", "") or src.get("role", ""),
                     n_samples=int(dst.get("n_samples", 1)) + int(src.get("n_samples", 1)),
                     n_seen=int(dst.get("n_seen", 0)) + int(src.get("n_seen", 0)),
                     last_seen=max(dst.get("last_seen", ""), src.get("last_seen", "")),
                     seen_at=max(dst.get("seen_at", 0), src.get("seen_at", 0)), updated=_now()))
    _delete(src["id"])
    return out


def name_voice(voice_id: str, name: str, role: str = "", force: bool = False) -> dict:
    """Gives a voice a name (e.g. after "Hi Dad, it's Sarah"). If another voice already has that name,
    the two are merged (weighted by samples) into the existing one, whose id is kept; the result has
    'merged_from'. Refuses (ValueError) to rename or merge a voice that already has a different name
    unless force=True, so two named people are never merged by accident. Returns the voice record."""
    if not name or not name.strip():
        raise ValueError("name is required")
    with _store_lock:
        d = _load().get(voice_id)
        if d is None:
            raise KeyError(voice_id)
        cur = (d.get("name") or "").strip()
        if cur and cur.lower() != name.strip().lower() and not force:
            raise ValueError(f"{voice_id} is already {cur}; pass force=True to change it")
        other = _by_name(name)
        if other is None or other["id"] == voice_id:
            out = _save(dict(d, name=name.strip(), role=role or d.get("role", ""), updated=_now()))
            return _public(out)
        # merge d into the voice that already has this name
        if role:
            other = dict(other, role=role)
        out = _merge(d, other)
        return dict(_public(out), merged_from=voice_id)


def adapt(name: str, pcm: bytes | None = None, rate: int = 16000, embedding: list[float] | None = None) -> bool:
    """Nudges a voice (by name or id) toward this utterance, only if it is a confident match
    (score >= ADAPT_MIN and the best match is that voice). Returns True if updated.
    observe() already does this for you; adapt() is for callers that use identify()."""
    if embedding is not None:
        e = _unit(np.asarray(embedding, dtype=np.float32))
    elif pcm is not None:
        e = _embed_float(_to_float(pcm), rate)
    else:
        return False
    if e is None:
        return False
    with _store_lock:
        ranked = _ranked(e)
        if not ranked or ranked[0][0] < ADAPT_MIN:
            return False
        d = ranked[0][1]
        if name not in (d["id"], d.get("name")):
            return False
        _save(dict(d, embedding=_blend(d, e), n_samples=int(d.get("n_samples", 1)) + 1,
                   n_adapted=int(d.get("n_adapted", 0)) + 1, updated=_now(), last_seen=_now()))
    return True


def list_voices() -> list[dict]:
    """[{id, name (None for learned voices), role, n_samples, n_seen, last_seen, ...}] — no embeddings."""
    return [_public(d) for d in _load().values()]


def wearer() -> dict | None:
    """The enrolled wearer, if any."""
    return next((v for v in list_voices() if v.get("role") == "wearer"), None)


def forget(name_or_id: str) -> bool:
    """Deletes a voiceprint by id or name. Returns True if one existed."""
    with _store_lock:
        d = _load().get(name_or_id) or _by_name(name_or_id)
        if d is None:
            return False
        _delete(d["id"])
        return True
