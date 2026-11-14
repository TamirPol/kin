"""Kin's brain: decides what in a conversation is worth remembering, and saves it.

Every chunk of transcript (a pause in the conversation, or ~30 s of talk) goes to
`digest(lines)`. It scores the lines 0-3 and pulls out people, facts, to-dos and item
locations into memory. With no OpenAI key it falls back to simple rules so the app
still works end to end.

Importance:
  0  drop (greetings, small talk, strangers' transactions, TV)
  1  keep 24 h in the transcript only
  2  keep long-term (facts about people, where things are)
  3  act now (plans/promises -> to-do, health, money/safety)
"""
from __future__ import annotations

import json
import logging
import re

from . import config, memory

log = logging.getLogger("kin.brain")

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["importance", "category", "speaker_names", "people", "facts", "todos", "items"],
    "properties": {
        "importance": {"type": "integer", "description": "0-3 for the chunk as a whole"},
        "category": {"type": "string", "enum": ["small_talk", "transaction", "person_fact", "plan",
                                                "item_location", "health", "money_safety", "emotional", "other"]},
        "speaker_names": {"type": "array", "description": "Speaker labels this chunk lets us name",
                          "items": {"type": "object", "additionalProperties": False,
                                    "required": ["speaker", "name"],
                                    "properties": {"speaker": {"type": "string"}, "name": {"type": "string"}}}},
        "people": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["name", "relationship"],
                                              "properties": {"name": {"type": "string"},
                                                             "relationship": {"type": "string"}}}},
        "facts": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["about", "text", "category"],
                                             "properties": {"about": {"type": "string", "description": "person name or ''"},
                                                            "text": {"type": "string"},
                                                            "category": {"type": "string"}}}},
        "todos": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["text", "due"],
                                             "properties": {"text": {"type": "string"}, "due": {"type": "string"}}}},
        "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["item", "location"],
                                             "properties": {"item": {"type": "string"}, "location": {"type": "string"}}}},
    },
}

PROMPT = """You are the memory of {wearer}, a person with early memory loss who wears a listening wristband.
Below is a short piece of conversation heard by the band. "wearer" is {wearer}; other speakers are
labelled "speaker N", with a name when we already know who they are.

Decide what is worth remembering FOR {wearer}. Be strict: most everyday talk is not important.
importance: 0 = greetings, small talk, weather, a cashier/waiter asking for an order, TV or background;
1 = mildly useful for today only; 2 = worth remembering long-term (facts about people in their life,
where they put things); 3 = needs action or is about health, medicine, money or safety.
Known family/friends lower the bar; strangers raise it (except money or safety, which always count).

Also extract:
- speaker_names: if someone introduces themselves or is clearly named ("Hi Dad, it's Sarah"), map
  their speaker label to the name.
- people: real people in {wearer}'s life who are NAMED (a first name, or a family title like "Mom").
  relationship = one or two words relative to {wearer} ("daughter", "grandson", "neighbor", "friend",
  "doctor") or "" if unknown. Never add speaker labels ("speaker 1"), unnamed or unknown people,
  strangers, or anyone who might be a scammer (asking for money, gift cards, bail, secrecy) as people.
- facts: short, plain sentences {wearer} would want recalled ("Sarah is moving to Oakland next week"),
  with `about` = the person's name or "".
- todos: plans or promises {wearer} made or must remember ("Call the dentist", due "tomorrow").
  Never turn a suspicious request (money, gift cards, bail, secrecy) into a to-do.
- items: where {wearer} put things ("keys" -> "kitchen drawer"), only from what was said.
Return empty lists when nothing qualifies. Never invent facts.

Known people: {known}

Conversation:
{lines}"""


def _fmt(lines: list[dict]) -> str:
    out = []
    for l in lines:
        who = l.get("name") or l.get("speaker") or "?"
        if l.get("speaker") and l.get("name") and l["speaker"] != "wearer":
            who = f"{l['name']} ({l['speaker']})"
        out.append(f"{who}: {l['text']}")
    return "\n".join(out)


def _llm(lines: list[dict]) -> dict:
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    known = ", ".join(f"{p['name']} ({p['relationship'] or '?'})" for p in memory.people()) or "none yet"
    prompt = PROMPT.format(wearer=config.WEARER_NAME, known=known, lines=_fmt(lines))
    r = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "memory", "strict": True, "schema": SCHEMA}},
    )
    return json.loads(r.choices[0].message.content)


# ---------- rule-based fallback (no key, or the API failed) ----------
SMALL_TALK = re.compile(r"^\W*(hi|hello|hey|thanks|thank you|bye|good (morning|night|afternoon)|how are you|"
                        r"what (can i get|would you like)|paper or plastic|have a (nice|good) day)\b", re.I)
INTRO = re.compile(r"\b(?i:it'?s|i'?m|this is|my name is)\s+([A-Z][a-z]+)\b")   # the name must be capitalised
NOT_NAMES = {"Moving", "Going", "Just", "Here", "Fine", "Good", "Back", "Sorry", "Not", "So", "Really", "Okay",
             "Coming", "Leaving", "Getting", "Home", "Me", "Your", "The", "A", "Very", "Still", "Gonna", "Happy"}
REL = re.compile(r"\b(?:hi|hey|hello)\s+(dad|mom|grandpa|grandma|uncle|auntie?)\b", re.I)
REL_MAP = {"dad": "child", "mom": "child", "grandpa": "grandchild", "grandma": "grandchild",
           "uncle": "niece/nephew", "aunt": "niece/nephew", "auntie": "niece/nephew"}
ITEM = re.compile(r"\b(?:i(?:'m| am)? (?:put|putting|left|leaving|set|setting)|i'?ll put)\s+(?:my |the )?"
                  r"([a-z ]{2,20}?)\s+(on|in|under|next to|by|behind|inside)\s+(?:the |my )?([a-z ]{2,30})", re.I)
PLAN = re.compile(r"\b(i(?:'ll| will| need to| have to| should)|remind me to|don'?t forget to)\s+(.{4,80})", re.I)
DUE = re.compile(r"\b(today|tonight|tomorrow|next week|on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", re.I)
HEALTH = re.compile(r"\b(pill|pills|medicine|medication|doctor|dentist|appointment|blood pressure|insulin)\b", re.I)
MONEY = re.compile(r"\b(gift card|wire|bank|password|social security|credit card|bail|lawyer)\b", re.I)


def _rules(lines: list[dict]) -> dict:
    res = {"importance": 0, "category": "small_talk", "speaker_names": [], "people": [],
           "facts": [], "todos": [], "items": []}
    for l in lines:
        t, spk = l["text"], l.get("speaker", "")
        m = INTRO.search(t)
        if m and spk and spk != "wearer" and m.group(1) not in NOT_NAMES:
            name = m.group(1).capitalize()
            rel = REL.search(t)
            res["speaker_names"].append({"speaker": spk, "name": name})
            res["people"].append({"name": name, "relationship": REL_MAP.get(rel.group(1).lower(), "") if rel else ""})
            res["importance"] = max(res["importance"], 1)
        if (m := ITEM.search(t)):
            res["items"].append({"item": m.group(1).strip(), "location": f"{m.group(2)} the {m.group(3).strip()}"})
            res["importance"], res["category"] = max(res["importance"], 2), "item_location"
        if spk == "wearer" and (m := PLAN.search(t)):
            due = DUE.search(t)
            res["todos"].append({"text": m.group(2).rstrip(".!"), "due": due.group(1) if due else ""})
            res["importance"], res["category"] = 3, "plan"
        if MONEY.search(t):
            res["importance"], res["category"] = 3, "money_safety"
        elif HEALTH.search(t):
            res["importance"] = max(res["importance"], 3)
            res["category"] = res["category"] if res["category"] != "small_talk" else "health"
        if (spk != "wearer" and not SMALL_TALK.search(t) and len(t.split()) > 5
                and not ITEM.search(t) and not MONEY.search(t)):
            about = l.get("name") or next((s["name"] for s in res["speaker_names"] if s["speaker"] == spk), "")
            if about and re.search(r"\b(i'?m|i am|we'?re|i got|we got|i have|we have|my)\b", t, re.I):
                res["facts"].append({"about": about, "text": f"{about}: {t.strip()}", "category": "person_fact"})
                res["importance"] = max(res["importance"], 2)
                if res["category"] == "small_talk":
                    res["category"] = "person_fact"
    return res


def digest(lines: list[dict]) -> dict:
    """Scores and stores one chunk of transcript. `lines` are memory.transcript rows."""
    if not lines:
        return {}
    res = None
    if config.OPENAI_API_KEY:
        try:
            res = _llm(lines)
        except Exception as e:                      # keep listening even if the API fails
            log.warning("LLM digest failed, using rules: %s", e)
    if res is None:
        res = _rules(lines)
    if res.get("items") or res.get("facts") or res.get("todos"):
        res["importance"] = max(int(res.get("importance", 0)), 2)   # anything stored is worth keeping
    save(res, lines)
    return res


FAKE_NAME = re.compile(r"^(speaker\b|unnamed|unknown|caller|wearer|someone|stranger|the )", re.I)


def _real_name(name: str) -> bool:
    n = (name or "").strip()
    return bool(n) and not FAKE_NAME.match(n) and n.lower() != config.WEARER_NAME.lower() and len(n) <= 30


def save(res: dict, lines: list[dict]) -> None:
    scam = res.get("category") == "money_safety"
    if not scam:                                     # a scammer never becomes a known person
        for s in res.get("speaker_names", []):
            if _real_name(s.get("name")) and s.get("speaker") and s["speaker"] != "wearer":
                memory.upsert_person(s["name"], speaker=s["speaker"])
        for p in res.get("people", []):
            if _real_name(p.get("name")):
                rel = (p.get("relationship") or "").strip()
                rel = "" if len(rel) > 25 or "unknown" in rel.lower() else rel
                memory.upsert_person(p["name"], relationship=rel)
    for f in res.get("facts", []):
        pid = None
        if f.get("about") and _real_name(f["about"]) and not scam:
            p = memory.find_person(f["about"])
            pid = p["id"] if p else memory.upsert_person(f["about"])
        memory.add_fact(f["text"], pid, f.get("category", ""), max(2, res.get("importance", 2)))
    for t in ([] if scam else res.get("todos", [])):    # never a to-do from a scam call
        memory.add_todo(t["text"], t.get("due", ""))
    for i in res.get("items", []):
        from .vision import normalize_item              # "car keys" and "keys" are the same thing
        memory.add_item(normalize_item(i["item"]) or i["item"], i["location"], source="voice")
    memory.rate_lines([l["id"] for l in lines if "id" in l], int(res.get("importance", 0)), res.get("category", ""))
