"""Builds tests/fixtures/desk_demo/*.jpg: a replayable desk scene for FolderSource demos without a camera.

Sequence (1 frame per second at --interval 1): empty desk -> a hand puts keys down -> keys rest ->
a person walks through the frame -> keys rest -> glasses are put down -> rest.
    .venv/bin/python tests/fixtures/make_desk_demo.py
    .venv/bin/python -m kin.vision --folder tests/fixtures/desk_demo --interval 1
"""
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).parent / "desk_demo"
rng = np.random.default_rng(0)


def desk():
    img = np.full((720, 1280, 3), (200, 215, 225), np.uint8)                 # wall
    cv2.rectangle(img, (0, 380), (1280, 720), (45, 90, 140), -1)              # wooden desk
    for y in range(400, 720, 40):
        cv2.line(img, (0, y), (1280, y + 8), (40, 80, 125), 2)                # wood grain
    pts = np.array([[480, 420], [800, 420], [830, 560], [450, 560]])
    cv2.fillPoly(img, [pts], (70, 70, 75))                                    # laptop base
    cv2.rectangle(img, (490, 180), (790, 420), (40, 40, 45), -1)              # laptop screen
    cv2.rectangle(img, (505, 195), (775, 405), (180, 140, 90), -1)
    cv2.ellipse(img, (1050, 440), (55, 20), 0, 0, 360, (230, 230, 230), -1)   # mug
    cv2.rectangle(img, (995, 340), (1105, 440), (230, 230, 230), -1)
    return img


def keys(img):
    cv2.circle(img, (300, 560), 30, (60, 60, 60), 5)
    for dx, dy in ((0, 0), (14, 10)):
        cv2.rectangle(img, (322 + dx, 556 + dy), (430 + dx, 570 + dy), (40, 190, 220), -1)
        cv2.circle(img, (322 + dx, 563 + dy), 18, (40, 190, 220), -1)
        for tx in range(360, 430, 14):
            cv2.rectangle(img, (tx + dx, 570 + dy), (tx + 6 + dx, 578 + dy), (40, 190, 220), -1)
    return img


def glasses(img):
    for cx in (930, 1030):
        cv2.ellipse(img, (cx, 600), (42, 30), 0, 0, 360, (20, 20, 20), 6)
    cv2.line(img, (972, 595), (988, 595), (20, 20, 20), 6)
    cv2.line(img, (888, 595), (850, 570), (20, 20, 20), 5)
    cv2.line(img, (1072, 595), (1110, 570), (20, 20, 20), 5)
    return img


def hand(img, x, y):
    cv2.ellipse(img, (x, y), (90, 60), 0, 0, 360, (120, 160, 210), -1)
    cv2.rectangle(img, (x - 40, 0), (x + 40, y), (120, 160, 210), -1)
    return img


def person(img, x):
    cv2.ellipse(img, (x, 200), (70, 90), 0, 0, 360, (110, 150, 200), -1)    # head
    cv2.rectangle(img, (x - 160, 280), (x + 160, 720), (140, 60, 40), -1)   # body
    return img


def noise(img):
    return np.clip(img.astype(int) + rng.integers(-3, 4, img.shape), 0, 255).astype(np.uint8)


frames = [desk() for _ in range(3)]
frames += [hand(desk(), 360, 560), hand(keys(desk()), 380, 420)]
frames += [keys(desk()) for _ in range(4)]
frames += [person(keys(desk()), x) for x in (150, 450, 750, 1050)]
frames += [keys(desk()) for _ in range(3)]
frames += [hand(keys(desk()), 980, 600), hand(glasses(keys(desk())), 1000, 450)]
frames += [glasses(keys(desk())) for _ in range(4)]

OUT.mkdir(exist_ok=True)
for f in OUT.glob("*.jpg"):
    f.unlink()
for i, f in enumerate(frames):
    cv2.imwrite(str(OUT / f"{i:02d}.jpg"), noise(f), [cv2.IMWRITE_JPEG_QUALITY, 85])
print(f"{len(frames)} frames -> {OUT}")
