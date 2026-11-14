"""Scores Kin's memory brain on the test conversations from docs/PLAN.md.

    .venv/bin/python tests/eval_brain.py          # all cases
    .venv/bin/python tests/eval_brain.py 3 7      # only cases 3 and 7
    .venv/bin/python tests/eval_brain.py -v       # also print what was stored

Uses the OpenAI brain when OPENAI_API_KEY is set in .env, else the rule fallback.
Each case runs on a fresh temporary database, so nothing touches kin.db.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (name, lines, checks). Lines: (speaker, text). Checks are functions of the stored memory.
def has_person(name, rel_words=()):
    def f(m):
        p = next((p for p in m["people"] if p["name"].lower() == name.lower()), None)
        if not p:
            return f"no person '{name}'"
        if rel_words and not any(w in (p["relationship"] or "").lower() for w in rel_words):
            return f"{name} relationship is '{p['relationship']}', wanted one of {rel_words}"
    return f


def fact_mentions(*words):
    def f(m):
        facts = [x["text"].lower() for p in m["people"] for x in p["facts"]] + [x.lower() for x in m["loose_facts"]]
        if not any(all(w in t for w in words) for t in facts):
            return f"no fact mentioning {words}"
    return f


def todo_mentions(*words, due=None):
    def f(m):
        t = next((t for t in m["todos"] if all(w in t["text"].lower() for w in words)), None)
        if not t:
            return f"no to-do mentioning {words}"
        if due and due not in (t["due"] or "").lower():
            return f"to-do due '{t['due']}', wanted '{due}'"
    return f


def item_at(item, *where):
    def f(m):
        i = next((i for i in m["items"] if item in i["item"]), None)
        if not i:
            return f"no item '{item}'"
        if not all(w in i["location"].lower() for w in where):
            return f"{item} at '{i['location']}', wanted {where}"
    return f


def importance(lo, hi=None):
    hi = lo if hi is None else hi
    def f(m):
        if not (lo <= m["importance"] <= hi):
            return f"importance {m['importance']}, wanted {lo}-{hi}"
    return f


def nothing_stored(m):
    if m["people"] or m["todos"] or m["items"] or m["loose_facts"]:
        return "stored something: " + str({k: len(v) for k, v in m.items() if isinstance(v, list) and v})


def no_person(name):
    def f(m):
        if any(p["name"].lower() == name.lower() for p in m["people"]):
            return f"invented person '{name}'"
    return f


CASES = [
    ("family intro",
     [("speaker 1", "Hi Dad, it's Sarah!"), ("wearer", "Oh hi sweetheart."),
      ("speaker 1", "I'm moving to Oakland next week for my new job.")],
     [has_person("Sarah", ("daughter", "child")), fact_mentions("oakland"), importance(2, 3)]),
    ("pure small talk",
     [("speaker 2", "Hi, how are you?"), ("wearer", "Fine thanks."), ("speaker 2", "Nice weather today.")],
     [importance(0), nothing_stored]),
    ("cashier",
     [("speaker 2", "Hi, what would you like to order?"), ("wearer", "A small coffee please."),
      ("speaker 2", "That's four fifty.")],
     [importance(0), nothing_stored]),
    ("item placement",
     [("wearer", "I'm putting my glasses on the nightstand.")],
     [item_at("glasses", "nightstand"), importance(2, 3)]),
    ("plan",
     [("wearer", "I'll call the dentist tomorrow morning.")],
     [todo_mentions("dentist", due="tomorrow"), importance(3)]),
    ("health",
     [("speaker 1", "Dad, the doctor said take the new pill with food, twice a day.")],
     [fact_mentions("food"), importance(3)]),
    ("grandchild news",
     [("speaker 3", "Hi Grandpa, it's Leo!"), ("speaker 3", "I got into Berkeley!"),
      ("wearer", "That's wonderful!")],
     [has_person("Leo", ("grand",)), fact_mentions("berkeley"), importance(2, 3)]),
    ("neighbor favor",
     [("speaker 2", "Hey Joe, it's Mike from next door. Can you water my plants on Saturday?"),
      ("wearer", "Sure, I'll do it.")],
     [has_person("Mike", ("neighbor", "neighbour")), todo_mentions("plants", due="saturday")]),
    ("name without intro",
     [("speaker 1", "Mom says she'll visit on Sunday.")],
     [fact_mentions("sunday"), no_person("speaker 1")]),
    ("small talk + one fact",
     [("speaker 1", "How's your knee?"), ("wearer", "Better."),
      ("speaker 1", "By the way, Emma had her baby, a girl named Lily.")],
     [fact_mentions("lily")]),
    ("scam",
     [("speaker 2", "Grandpa, it's your grandson. I'm in jail and need bail. Buy gift cards and don't tell Mom.")],
     [importance(3)]),
    ("background TV",
     [("speaker 2", "On TV tonight, the weather will be sunny with a high of seventy.")],
     [importance(0), nothing_stored]),
]


def run_case(lines):
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    os.environ["KIN_DB"] = db
    for mod in [m for m in list(sys.modules) if m.startswith("kin")]:
        del sys.modules[mod]
    from kin import brain, memory
    rows = [dict(id=memory.add_line(s, t), speaker=s, text=t, name="") for s, t in lines]
    res = brain.digest(rows)
    m = {"people": memory.people(), "todos": memory.todos(), "items": memory.items(),
         "loose_facts": [r["text"] for r in memory._rows("SELECT text FROM facts WHERE person_id IS NULL")],
         "importance": int(res.get("importance", -1)), "category": res.get("category", "")}
    os.unlink(db)
    return m


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv
    pick = {int(a) for a in args}
    from kin import config
    print(f"brain: {'OpenAI ' + config.OPENAI_MODEL if config.OPENAI_API_KEY else 'rule fallback (no OpenAI key)'}\n")
    passed = 0
    chosen = [(i, c) for i, c in enumerate(CASES, 1) if not pick or i in pick]
    for i, (name, lines, checks) in chosen:
        try:
            m = run_case(lines)
            fails = [r for r in (c(m) for c in checks) if r]
        except Exception as e:
            m, fails = None, [f"crashed: {e}"]
        ok = not fails
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {i:2}. {name}" + ("" if ok else "  -> " + "; ".join(fails)))
        if verbose and m:
            print(f"        importance={m['importance']} {m['category']} | people="
                  f"{[(p['name'], p['relationship'], [f['text'] for f in p['facts']]) for p in m['people']]}"
                  f" | todos={[(t['text'], t['due']) for t in m['todos']]} | items="
                  f"{[(x['item'], x['location']) for x in m['items']]} | other facts={m['loose_facts']}")
    print(f"\n{passed}/{len(chosen)} passed")


if __name__ == "__main__":
    main()
