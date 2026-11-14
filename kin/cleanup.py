"""Careful transcript cleanup: fixes clear speech-to-text mistakes using the conversation so far.

Deepgram is good but noisy rooms and wrist mics produce slips like "eight at donuts" for "I ate donuts" or
"Granson" for "grandson". Each finished sentence goes to a fast model with the last few lines as context.
It may only fix words that were clearly misheard (sound-alikes, split or merged words, known names); it must
not rephrase, summarise, add or remove meaning. A fix is applied only when the model is confident AND the
change is small, otherwise the original words are kept.

    cleanup.clean("eight at donuts", recent=[...]) -> ("I ate donuts", True)
"""
from __future__ import annotations

import difflib
import json
import logging
import os

from . import config, memory

log = logging.getLogger("kin.cleanup")
ENABLED = os.environ.get("KIN_CLEANUP", "on").lower() not in ("off", "0", "false")
MIN_CONFIDENCE = 0.8
MAX_CHANGE = 0.45          # at most this share of the words may change

PROMPT = """You fix speech-to-text mistakes in ONE sentence heard by a wristband worn by {wearer}.
Known people: {people}. Other known words: Kin (the assistant's name).
Recent conversation (for context):
{recent}

Sentence to check: "{text}"

Only fix words that were clearly misheard: sound-alikes ("eight" -> "ate", "their" -> "there"), split or merged
words, misspelled known names ("Granson" -> "grandson", "Hakan" -> "Kin" only if context makes it obvious).
Never rephrase, never add or remove meaning, never complete an unfinished sentence, keep the speaker's style.
If nothing is clearly wrong, return the sentence unchanged with confidence 1.
Reply as JSON: {{"text": "...", "confidence": 0.0-1.0}}"""


def _people() -> str:
    try:
        ps = memory.people()
        return ", ".join(f"{p['name']} ({p['relationship']})" if p["relationship"] else p["name"] for p in ps[:15]) or "none yet"
    except Exception:
        return "none yet"


def _changed_share(a: str, b: str) -> float:
    aw, bw = a.lower().split(), b.lower().split()
    if not aw:
        return 1.0
    sm = difflib.SequenceMatcher(None, aw, bw)
    same = sum(bl.size for bl in sm.get_matching_blocks())
    return 1 - same / max(len(aw), len(bw))


def clean(text: str, recent: list[str] | None = None) -> tuple[str, bool]:
    """Returns (text, changed). Never raises; falls back to the original."""
    t = (text or "").strip()
    if not ENABLED or not config.OPENAI_API_KEY or len(t.split()) < 2:
        return t, False
    try:
        from openai import OpenAI
        r = OpenAI(api_key=config.OPENAI_API_KEY, timeout=4).chat.completions.create(
            model=config.OPENAI_MODEL, reasoning_effort="none", response_format={"type": "json_object"},
            messages=[{"role": "user", "content": PROMPT.format(
                wearer=config.WEARER_NAME, people=_people(), recent="\n".join((recent or [])[-6:]) or "(none)",
                text=t.replace('"', "'"))}])
        out = json.loads(r.choices[0].message.content)
        new, conf = str(out.get("text", "")).strip(), float(out.get("confidence", 0))
    except Exception as e:
        log.debug("cleanup skipped: %s", e)
        return t, False
    if not new or new == t or conf < MIN_CONFIDENCE or _changed_share(t, new) > MAX_CHANGE:
        return t, False
    return new, True
