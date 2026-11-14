"""kin.voiceprint: enrollment, identification (clean and in a noisy room), storage, latency.

Speech comes from macOS `say` (different system voices = different speakers); skipped elsewhere.
"""
import json
import shutil
import subprocess
import threading
import time
import wave

import numpy as np
import pytest

from kin import voiceprint as vp

pytestmark = pytest.mark.skipif(shutil.which("say") is None, reason="needs macOS `say`")

ENROLL = ("Hi Kin, this is me. I'm setting up my voice so you can recognize me. I live here with my cat, "
          "I like gardening in the morning, and I usually call my daughter on Sundays after lunch.")
LINES = ["Did you remember to buy milk today?",
         "The doctor's appointment is on Tuesday at three.",
         "Sarah is coming over this weekend with the kids."]


@pytest.fixture(scope="module")
def speech(tmp_path_factory):
    d = tmp_path_factory.mktemp("say")
    cache = {}

    def get(voice, text):
        k = (voice, text)
        if k not in cache:
            p = d / f"{len(cache)}.wav"
            subprocess.run(["say", "-v", voice, "--data-format=LEI16@16000", "-o", str(p), text], check=True)
            with wave.open(str(p)) as w:
                cache[k] = w.readframes(w.getnframes())
        return cache[k]
    vp.warm_up()
    return get


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "VOICE_DIR", tmp_path / "voiceprints")
    monkeypatch.setattr(vp, "_voices", None)
    return tmp_path / "voiceprints"


def mix(a: bytes, b: bytes, snr_db: float) -> bytes:
    """a with b looped under it, b at snr_db below a (a crowded room)."""
    x = np.frombuffer(a, np.int16).astype(np.float32)
    y = np.resize(np.frombuffer(b, np.int16).astype(np.float32), x.size)
    y *= np.sqrt(np.mean(x ** 2) / (np.mean(y ** 2) + 1e-9)) / 10 ** (snr_db / 20)
    return np.clip(x + y, -32768, 32767).astype(np.int16).tobytes()


def test_embed_needs_speech(speech):
    assert vp.embed(b"") is None
    assert vp.embed(bytes(16000 * 2 * 3)) is None                     # 3 s of silence
    assert vp.embed(speech("Samantha", "Hi.")) is None                 # well under a second
    e = vp.embed(speech("Samantha", LINES[0]))
    assert e is not None and abs(np.linalg.norm(e) - 1) < 1e-4


def test_embed_other_rate(speech):
    x = np.frombuffer(speech("Daniel", LINES[1]), np.int16).astype(np.float32)
    up = np.interp(np.linspace(0, x.size - 1, x.size * 3), np.arange(x.size), x).astype(np.int16).tobytes()
    a, b = np.array(vp.embed(speech("Daniel", LINES[1]))), np.array(vp.embed(up, rate=48000))
    assert a @ b > 0.9


def test_enroll_identify(store, speech):
    r = vp.enroll("Ruth", speech("Samantha", ENROLL), role="wearer")
    assert r["name"] == "Ruth" and r["role"] == "wearer" and r["n_samples"] == 1 and "embedding" not in r
    assert r["speech_s"] > 5
    vp.enroll("Sarah", speech("Karen", ENROLL), role="daughter")
    vp.enroll("Tom", speech("Daniel", ENROLL), role="son")
    for voice, who in [("Samantha", "Ruth"), ("Karen", "Sarah"), ("Daniel", "Tom")]:
        for line in LINES:
            m = vp.identify(speech(voice, line))
            assert m["name"] == who, (voice, line, m)
            assert m["score"] >= vp.THRESHOLD
    m = vp.identify(speech("Samantha", LINES[2]))
    assert m["is_wearer"] and m["role"] == "wearer"
    assert vp.wearer()["name"] == "Ruth"


def test_stranger_not_matched(store, speech):
    vp.enroll("Ruth", speech("Samantha", ENROLL), role="wearer")
    vp.enroll("Tom", speech("Daniel", ENROLL), role="son")
    for voice in ["Rishi", "Fred", "Tessa"]:
        m = vp.identify(speech(voice, LINES[0]))
        assert m["name"] is None and m["score"] < vp.THRESHOLD, (voice, m)
        assert not m["is_wearer"]


def test_noisy_room(store, speech):
    """Wearer speaks with two other people talking 10 dB quieter (and white noise 20 dB down)."""
    vp.enroll("Ruth", speech("Samantha", ENROLL), role="wearer")
    vp.enroll("Tom", speech("Daniel", ENROLL), role="son")
    babble = mix(speech("Rishi", ENROLL), speech("Tessa", ENROLL), 0)
    rng = np.random.default_rng(1)
    for line in LINES:
        noisy = mix(mix(speech("Samantha", line), babble, 10),
                    rng.normal(0, 3000, 16000 * 8).astype(np.int16).tobytes(), 20)
        m = vp.identify(noisy)
        assert m["name"] == "Ruth", (line, m)
    # the son, in the same room
    m = vp.identify(mix(speech("Daniel", LINES[0]), babble, 10))
    assert m["name"] == "Tom", m


def test_storage_averages_and_has_no_audio(store, speech):
    vp.enroll("Ruth", speech("Samantha", ENROLL), role="wearer")
    r = vp.enroll("ruth", speech("Samantha", LINES[0] + " " + LINES[1]))     # same slug, role kept
    assert r["n_samples"] == 2 and r["role"] == "wearer"
    files = list(store.glob("*.json"))
    assert [f.name for f in files] == ["ruth.json"]
    d = json.loads(files[0].read_text())
    assert set(d) >= {"name", "role", "embedding", "n_samples", "created", "model"}
    assert len(d["embedding"]) < 1024 and files[0].stat().st_size < 40_000      # an embedding, not audio
    assert [v["name"] for v in vp.list_voices()] == ["ruth"]
    assert vp.forget("Ruth") and not vp.forget("Ruth")
    assert vp.list_voices() == [] and vp.identify(speech("Samantha", LINES[0]))["name"] is None


def test_enroll_rejects_too_little_speech(store, speech):
    with pytest.raises(ValueError):
        vp.enroll("Ruth", speech("Samantha", "Hi."))
    with pytest.raises(ValueError):
        vp.enroll("", speech("Samantha", ENROLL))


def test_adapt_only_when_confident(store, speech):
    vp.enroll("Ruth", speech("Samantha", ENROLL), role="wearer")
    vp.enroll("Tom", speech("Daniel", ENROLL), role="son")
    assert not vp.adapt("Ruth", speech("Daniel", LINES[0]))          # that's Tom, not Ruth
    assert not vp.adapt("Ruth", speech("Rishi", LINES[0]))           # a stranger
    e = vp.embed(speech("Samantha", LINES[1]))
    if vp.identify_embedding(e)["score"] >= vp.ADAPT_MIN:
        assert vp.adapt("Ruth", embedding=e)
        assert [v for v in vp.list_voices() if v["name"] == "Ruth"][0]["n_adapted"] == 1
    assert vp.identify(speech("Samantha", LINES[2]))["name"] == "Ruth"


def test_latency_and_threads(store, speech):
    vp.enroll("Ruth", speech("Samantha", ENROLL), role="wearer")
    three_s = (speech("Samantha", LINES[0] + " " + LINES[1]) * 2)[: 16000 * 2 * 3]
    times = []
    for _ in range(5):
        t = time.perf_counter()
        vp.identify(three_s)
        times.append(time.perf_counter() - t)
    assert sorted(times)[2] < 0.15, times
    out, errs = [], []

    def work():
        try:
            out.append(vp.identify(three_s)["name"])
        except Exception as e:      # pragma: no cover
            errs.append(e)
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and out == ["Ruth"] * 8


# ---------------------------------------------------------------- learning voices without enrollment

FIRST = "Good morning, did you remember to buy milk at the shop today?"     # ~3 s: enough to learn a voice


def reload_store():
    """Simulates a restart (next week): drop the in-memory cache, read voiceprints/ again."""
    vp._voices = None


def test_observe_learns_and_recognizes_later(store, speech):
    r = vp.observe(speech("Daniel", FIRST))
    assert r["new"] and r["id"] == "voice-1" and r["name"] is None, r
    r = vp.observe(speech("Daniel", LINES[1]))
    assert r["id"] == "voice-1" and not r["new"], r
    reload_store()
    r = vp.observe(speech("Daniel", LINES[2]))
    assert r["id"] == "voice-1" and not r["new"], r
    v = vp.list_voices()
    assert len(v) == 1 and v[0]["name"] is None and v[0]["n_seen"] == 3 and v[0]["n_samples"] >= 2
    assert vp.identify(speech("Daniel", "Could you tell me who that man was at the door?"))["id"] == "voice-1"


def test_two_voices_stay_separate(store, speech):
    a = vp.observe(speech("Daniel", FIRST))
    b = vp.observe(speech("Samantha", FIRST))
    assert a["new"] and b["new"] and a["id"] != b["id"], (a, b)
    for line in LINES[1:]:
        assert vp.observe(speech("Daniel", line))["id"] == a["id"]
        assert vp.observe(speech("Samantha", line))["id"] == b["id"]
    assert len(vp.list_voices()) == 2


def test_name_voice(store, speech):
    vid = vp.observe(speech("Daniel", FIRST))["id"]
    r = vp.name_voice(vid, "Tom", role="son")
    assert r["id"] == vid and r["name"] == "Tom" and r["role"] == "son"
    reload_store()
    m = vp.observe(speech("Daniel", LINES[1]))
    assert m["id"] == vid and m["name"] == "Tom" and m["role"] == "son", m
    assert vp.identify(speech("Daniel", LINES[2]))["name"] == "Tom"
    # a named person is never silently renamed / merged
    with pytest.raises(ValueError):
        vp.name_voice(vid, "Sarah")
    assert vp.name_voice(vid, "tom")["name"] == "tom"           # same name, different case: fine


def test_name_voice_merges_into_enrolled(store, speech):
    anon = vp.observe(speech("Tessa", FIRST))
    assert anon["new"]
    vp.enroll("Sarah", speech("Tessa", ENROLL), role="daughter")
    vp.enroll("Ruth", speech("Samantha", ENROLL), role="wearer")
    assert len(vp.list_voices()) == 3
    r = vp.name_voice(anon["id"], "Sarah")
    assert r["merged_from"] == anon["id"] and r["id"] == "sarah" and r["role"] == "daughter"
    assert r["n_samples"] == 2
    ids = sorted(v["id"] for v in vp.list_voices())
    assert ids == ["ruth", "sarah"]
    m = vp.observe(speech("Tessa", LINES[1]))
    assert m["name"] == "Sarah" and not m["new"]
    assert vp.observe(speech("Samantha", LINES[1]))["is_wearer"]


def test_observe_guards(store, speech, monkeypatch):
    assert vp.observe(speech("Daniel", "Okay."))["id"] is None              # too little speech
    r = vp.observe(speech("Daniel", "Yes, I think so."))                    # ~1 s: not enough to learn from
    assert r["id"] is None and not r["new"]
    loud = mix(speech("Daniel", LINES[0]), np.random.default_rng(0).normal(0, 3000, 16000 * 4).astype(np.int16).tobytes(), 0)
    r = vp.observe(loud)                                                    # speech as loud as the noise
    assert not r["new"], r
    two = speech("Daniel", LINES[0] + " " + LINES[1]) + speech("Samantha", LINES[2] + " " + LINES[0])
    r = vp.observe(two)                                                     # two people in one clip
    assert not r["new"] and r["reason"] == "sounds like more than one person", r
    assert vp.list_voices() == []
    # cap: the least-recently-heard unnamed voice is dropped, named voices never are
    monkeypatch.setattr(vp, "MAX_ANON", 2)
    vp.enroll("Ruth", speech("Samantha", ENROLL), role="wearer")
    first = vp.observe(speech("Daniel", FIRST))["id"]
    second = vp.observe(speech("Rishi", FIRST))["id"]
    third = vp.observe(speech("Fred", FIRST))["id"]
    assert len({first, second, third}) == 3
    ids = {v["id"] for v in vp.list_voices()}
    assert ids == {"ruth", second, third}
    assert vp.observe(speech("Albert", FIRST))["id"] not in (first, second, third)   # ids never reused
