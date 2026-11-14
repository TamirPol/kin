"""Tests for kin.vision. Gemini is mocked except in test_real_gemini (runs only with a real key)."""
import os
import time
from pathlib import Path

DB = "/tmp/kin_vision_test.db"
if not os.environ.get("KIN_DB", "").startswith("/tmp/"):   # another test module may already have set a test DB
    os.environ["KIN_DB"] = DB
    if os.path.exists(DB):
        os.remove(DB)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from kin import config, memory, vision  # noqa: E402

assert str(config.DB_PATH).startswith("/tmp/")   # never the real kin.db


def jpeg(color=(200, 200, 200), square=None, noise=0, size=60, shape=(240, 320)) -> bytes:
    img = np.full((*shape, 3), color, np.uint8)
    if square:
        x, y = square
        cv2.rectangle(img, (x, y), (x + size, y + size), (20, 20, 160), -1)
    if noise:
        img = np.clip(img.astype(int) + np.random.randint(-noise, noise + 1, img.shape), 0, 255).astype(np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


class ListSource(vision.FrameSource):
    def __init__(self, frames):
        self.frames = list(frames)

    def read(self):
        return self.frames.pop(0) if self.frames else None


class FakeDescribe:
    """Returns the scripted answers in order; records how often it was called."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, jpeg_bytes):
        self.calls += 1
        return self.answers.pop(0) if self.answers else []


@pytest.fixture(autouse=True)
def fresh_db():
    memory._exec("DELETE FROM items")
    yield


def make(frames, describe, tmp_path, **kw):
    kw.setdefault("settle", 0)          # the older tests check change detection alone; settling is tested below
    return vision.VisionWatcher(ListSource(frames), describe=describe, snapshot_dir=tmp_path / "snapshots", **kw)


# ---------- change detection ----------
def test_identical_and_noisy_frames_are_skipped(tmp_path):
    base = jpeg(square=(50, 50))
    fake = FakeDescribe()
    w = make([base, base, jpeg(square=(50, 50), noise=4)], fake, tmp_path)
    for _ in range(3):
        w.step()
    assert fake.calls == 1
    assert w.stats["skipped"] == 2


def test_changed_frame_is_described(tmp_path):
    fake = FakeDescribe()
    w = make([jpeg(square=(20, 20)), jpeg(square=(220, 150))], fake, tmp_path)
    w.step(); w.step()
    assert fake.calls == 2


def test_small_item_appearing_counts_as_change(tmp_path):
    # keys-sized thing (~3% of the width) appearing in a 1280x720 webcam frame
    empty = jpeg(shape=(720, 1280), noise=4)
    with_keys = jpeg(square=(600, 400), size=40, shape=(720, 1280), noise=4)
    fake = FakeDescribe()
    w = make([empty, jpeg(shape=(720, 1280), noise=4), with_keys], fake, tmp_path)
    w.step(); w.step(); w.step()
    assert fake.calls == 2          # noise skipped, keys noticed


def test_force_every_rechecks_static_scene(tmp_path):
    base = jpeg()
    fake = FakeDescribe()
    w = make([base, base, base], fake, tmp_path, force_every=0.05)
    w.step(); w.step()
    time.sleep(0.06)
    w.step()
    assert fake.calls == 2


def test_frame_difference_scale():
    a = vision.frame_signature(jpeg((0, 0, 0)))
    b = vision.frame_signature(jpeg((255, 255, 255)))
    assert vision.frame_difference(a, a) == 0.0
    assert vision.frame_difference(a, b) > 0.9
    assert vision.frame_difference(None, a) == 1.0


# ---------- de-duplication, snapshots, memory ----------
KEYS_TABLE = {"item": "keys", "location": "on the kitchen table next to the fruit bowl", "confidence": 0.9}


def test_new_item_saves_snapshot_and_logs_memory(tmp_path):
    seen = []
    w = make([jpeg(square=(20, 20))], FakeDescribe([KEYS_TABLE]), tmp_path, on_item=seen.append)
    logged = w.step()
    assert len(logged) == 1 and seen == logged
    snap = Path(logged[0]["snapshot"])
    if not snap.is_absolute():
        snap = config.ROOT / snap
    assert snap.exists() and snap.parent == tmp_path / "snapshots" and snap.name.endswith("_keys.jpg")
    assert snap.read_bytes()[:2] == b"\xff\xd8"
    row = memory.find_item("keys")
    assert row["location"] == KEYS_TABLE["location"] and row["source"] == "vision"
    assert row["snapshot"] == logged[0]["snapshot"]


def test_same_item_same_place_is_not_relogged(tmp_path):
    rephrased = {"item": "Keys", "location": "by the fruit bowl on the kitchen table", "confidence": 0.8}
    w = make([jpeg(square=(20, 20)), jpeg(square=(220, 150))], FakeDescribe([KEYS_TABLE], [rephrased]), tmp_path)
    w.step(); w.step()
    assert len(memory.items()) == 1
    assert len(list((tmp_path / "snapshots").glob("*.jpg"))) == 1


def test_moved_item_is_logged_again(tmp_path):
    moved = {"item": "keys", "location": "on the hook by the front door", "confidence": 0.9}
    w = make([jpeg(square=(20, 20)), jpeg(square=(220, 150))], FakeDescribe([KEYS_TABLE], [moved]), tmp_path)
    w.step(); w.step()
    assert memory.find_item("keys")["location"] == moved["location"]
    assert len(memory.items()) == 2


def test_duplicates_in_one_frame_and_low_confidence(tmp_path):
    answer = [KEYS_TABLE, {**KEYS_TABLE, "confidence": 0.4},
              {"item": "glasses", "location": "on the sofa", "confidence": 0.2}]
    w = make([jpeg()], FakeDescribe(answer), tmp_path)
    logged = w.step()
    assert [d["item"] for d in logged] == ["keys"]


def test_restart_does_not_relog_what_memory_already_has(tmp_path):
    memory.add_item("keys", KEYS_TABLE["location"], source="vision")
    w = make([jpeg()], FakeDescribe([KEYS_TABLE]), tmp_path)
    assert w.step() == []
    assert len(memory.items()) == 1


def test_look_now_ignores_change_detection(tmp_path):
    base = jpeg()
    fake = FakeDescribe([KEYS_TABLE], [KEYS_TABLE])
    w = make([base, base], fake, tmp_path)
    assert w.look_now()[0]["item"] == "keys"
    assert w.look_now()[0]["item"] == "keys"     # same frame, still asked: user explicitly requested
    assert fake.calls == 2
    assert len(memory.items()) == 1               # but not logged twice


def test_same_place():
    assert vision.same_place("on the kitchen table", "on the kitchen table next to the fruit bowl")
    assert vision.same_place("on the arm of the blue sofa", "on the blue sofa armrest")
    assert not vision.same_place("on the coffee table", "on the kitchen table")
    assert not vision.same_place("on the kitchen table", "on the kitchen counter")


def test_thread_start_stop(tmp_path):
    frames = [jpeg(square=(20 + 30 * i, 20)) for i in range(5)]
    fake = FakeDescribe([KEYS_TABLE])
    w = make(frames, fake, tmp_path, interval=0.05)
    w.start()
    deadline = time.time() + 3
    while fake.calls < 5 and time.time() < deadline:
        time.sleep(0.02)
    w.stop()
    assert not w.running
    assert fake.calls == 5
    assert memory.find_item("keys")


def test_no_key_returns_empty(monkeypatch, caplog):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(vision, "_warned_no_key", False)
    with caplog.at_level("WARNING", logger="kin.vision"):
        assert vision.describe_frame(jpeg()) == []
        assert vision.describe_frame(jpeg()) == []
    assert sum("GEMINI_API_KEY" in r.message for r in caplog.records) == 1


# ---------- settling: wait until the scene is still ----------
def test_person_walking_through_costs_no_gemini_calls(tmp_path):
    empty = jpeg()
    walking = [jpeg(square=(10 + 50 * i, 40), size=120) for i in range(5)]     # big thing moving each tick
    fake = FakeDescribe()
    w = make([empty, empty] + walking + [empty, empty], fake, tmp_path, settle=1)
    for _ in range(9):
        w.step()
    # first still frame described once; while walking: nothing; back to the same empty scene: skipped
    assert fake.calls == 1
    assert w.stats["moving"] >= 5


def test_item_put_down_is_described_once_it_is_still(tmp_path):
    empty, hand = jpeg(), jpeg(square=(100, 60), size=120)
    keys = jpeg(square=(150, 150), size=25)
    fake = FakeDescribe([], [KEYS_TABLE])
    w = make([empty, empty, hand, keys, keys, keys], fake, tmp_path, settle=1)
    logged = [w.step() for _ in range(6)]
    assert fake.calls == 2
    assert [len(x) for x in logged] == [0, 0, 0, 0, 1, 0]     # logged on the first still frame with keys
    assert len(memory.items()) == 1


# ---------- Gemini back-off ----------
class Busy(Exception):
    code = 429


def test_gemini_429_backs_off_and_retries_frame(tmp_path, monkeypatch):
    calls = []

    def fake_generate(parts, schema=None, temperature=0.1):
        calls.append(1)
        if len(calls) == 1:
            raise vision._note_busy(Busy("429 RESOURCE_EXHAUSTED"))
        return '[{"item": "car keys", "location": "on the desk next to the laptop", "confidence": 0.9}]'

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(vision, "_generate", fake_generate)
    monkeypatch.setattr(vision, "_busy_delay", 0.0)
    frame = jpeg(square=(40, 40))
    w = vision.VisionWatcher(ListSource([frame] * 4), settle=0, snapshot_dir=tmp_path / "s")
    assert w.step() == [] and w.stats["busy"] == 1
    assert 0 < vision.busy_for() <= vision.BACKOFF_START
    assert w.step() == [] and len(calls) == 1          # still backing off: no call made
    monkeypatch.setattr(vision, "_busy_until", 0.0)
    logged = w.step()                                  # same frame retried (it was never marked as seen)
    assert [d["item"] for d in logged] == ["keys"]
    assert w.step() == []                              # and now it is seen


def test_busy_error_detection():
    assert vision._is_busy_error(Busy("x"))
    assert vision._is_busy_error(Exception("503 UNAVAILABLE. model overloaded"))
    assert not vision._is_busy_error(ValueError("bad json"))


def test_backoff_grows_and_caps(monkeypatch):
    monkeypatch.setattr(vision, "_busy_delay", 0.0)
    delays = [vision._note_busy(Busy()).retry_in for _ in range(7)]
    assert delays[0] == vision.BACKOFF_START and delays[1] == 2 * vision.BACKOFF_START
    assert delays[-1] == vision.BACKOFF_MAX
    monkeypatch.setattr(vision, "_busy_until", 0.0)


# ---------- names ----------
@pytest.mark.parametrize("raw,canon", [
    ("car keys", "keys"), ("Keys", "keys"), ("key", "keys"), ("my keyring", "keys"), ("set of keys", "keys"),
    ("eyeglasses", "glasses"), ("reading glasses", "glasses"), ("Glasses.", "glasses"),
    ("sunglasses", "sunglasses"), ("black leather wallet", "wallet"), ("iPhone", "phone"),
    ("cell phone", "phone"), ("pill bottle", "pills"), ("bottle of pills", "pills"), ("medication", "pills"),
    ("TV remote", "tv remote"), ("remote control", "tv remote"), ("hearing aid", "hearing aids"),
    ("walking stick", "cane"), ("keys on a ring", "keys"), ("books", "book"), ("glasses case", "glasses case"),
    ("", ""),
])
def test_normalize_item(raw, canon):
    assert vision.normalize_item(raw) == canon


def test_where_is_finds_vision_item_by_any_name(tmp_path):
    w = make([jpeg()], FakeDescribe([{"item": "car keys", "location": "on the desk", "confidence": 0.9},
                                     {"item": "reading glasses", "location": "on the sofa", "confidence": 0.9}]),
             tmp_path)
    w.step()
    assert {i["item"] for i in memory.items()} == {"keys", "glasses"}
    assert memory.find_item("keys")["snapshot"]                  # "where are my keys?" works as-is
    assert vision.where_is("my car keys")["location"] == "on the desk"
    assert vision.where_is("eyeglasses")["location"] == "on the sofa"
    assert vision.where_is("umbrella") is None


def test_same_place_same_surface():
    assert vision.same_place("on the desk next to the laptop", "on the wooden desk in front of the keyboard")
    assert not vision.same_place("on the desk next to the laptop", "on the kitchen counter by the sink")


# ---------- "what do you see?" ----------
def test_describe_scene_one_sentence(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(vision, "_generate",
                        lambda parts, schema=None, temperature=0.1: '"You are at your desk with your keys. Also a mug."')
    assert vision.describe_scene(jpeg()) == "You are at your desk with your keys."


def test_describe_scene_no_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert vision.describe_scene(jpeg()) == ""


def test_what_do_you_see(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "describe_scene", lambda j: "Your keys are on the kitchen table.")
    w = make([jpeg()], FakeDescribe([KEYS_TABLE]), tmp_path)
    r = w.what_do_you_see()
    assert r["sentence"] == "Your keys are on the kitchen table."
    assert r["items"][0]["item"] == "keys" and r["snapshot"][:2] == b"\xff\xd8"
    assert w.what_do_you_see()["snapshot"]          # source empty now: falls back to the last frame


# ---------- faces (optional) ----------
def test_enroll_and_recognise_faces(tmp_path, monkeypatch):
    faces = tmp_path / "faces"
    vision.enroll_face("Sarah Cohen", jpeg((10, 10, 10)), faces)
    vision.enroll_face("Sarah Cohen", jpeg((20, 20, 20)), faces)
    vision.enroll_face("David", jpeg((30, 30, 30)), faces)
    got = vision.enrolled_faces(faces)
    assert set(got) == {"Sarah Cohen", "David"} and len(got["Sarah Cohen"]) == 2
    seen = {}

    def fake_generate(parts, schema=None, temperature=0.1):
        seen["parts"] = parts
        return '["sarah cohen", "Stranger"]'

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(vision, "_generate", fake_generate)
    assert vision.who_is_in_frame(jpeg(), faces) == ["Sarah Cohen"]     # only enrolled names come back
    assert sum(isinstance(p, str) and p.startswith("Enrolled person") for p in seen["parts"]) == 2
    assert vision.who_is_in_frame(jpeg(), tmp_path / "nobody") == []
    with pytest.raises(ValueError):
        vision.enroll_face(" ", jpeg(), faces)


# ---------- FolderSource ----------
def test_folder_source_replays_in_order(tmp_path):
    for i, c in enumerate([(10, 10, 10), (120, 120, 120), (250, 250, 250)]):
        (tmp_path / f"{i:02d}.jpg").write_bytes(jpeg(c))
    (tmp_path / "notes.txt").write_text("ignore me")
    src = vision.FolderSource(tmp_path, loop=False)
    frames = [src.read() for _ in range(4)]
    assert frames[3] is None
    assert frames[0] == (tmp_path / "00.jpg").read_bytes() and frames[2] == (tmp_path / "02.jpg").read_bytes()
    looping = vision.FolderSource(tmp_path)
    assert [looping.read() for _ in range(4)][3] == frames[0]


# ---------- real Gemini (only with a real key) ----------
def keys_on_table_jpeg() -> bytes:
    """A simple drawn scene: brown wooden table, a fruit bowl, and a ring of keys."""
    img = np.full((480, 640, 3), (225, 235, 240), np.uint8)
    cv2.rectangle(img, (0, 260), (640, 480), (40, 75, 120), -1)                  # table top
    cv2.ellipse(img, (450, 270), (110, 45), 0, 0, 180, (180, 180, 190), -1)       # bowl
    for x, c in [(400, (0, 60, 220)), (460, (0, 200, 240)), (510, (40, 160, 40))]:
        cv2.circle(img, (x, 240), 30, c, -1)                                      # fruit
    cv2.circle(img, (200, 360), 28, (60, 60, 60), 4)                              # key ring
    for dx in (0, 12):
        cv2.rectangle(img, (220 + dx, 360), (330 + dx, 372), (40, 190, 220), -1)  # brass keys
        cv2.circle(img, (220 + dx, 366), 16, (40, 190, 220), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


@pytest.mark.skipif(not config.GEMINI_API_KEY, reason="no real GEMINI_API_KEY in .env")
def test_real_gemini():
    photo = Path(__file__).parent / "fixtures" / "keys_on_table.jpg"
    data = photo.read_bytes() if photo.exists() else keys_on_table_jpeg()
    out = vision.describe_frame(data)
    print(out)
    assert isinstance(out, list)
    assert all(set(d) == {"item", "location", "confidence"} for d in out)
    assert any(d["item"] == "keys" for d in out)
    sentence = vision.describe_scene(data)
    print(sentence)
    assert sentence and len(sentence.split()) <= 40
