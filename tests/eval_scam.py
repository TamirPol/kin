"""Scores Kin's scam detector (kin/safety.check_scam) on realistic transcript snippets.

    .venv/bin/python tests/eval_scam.py            # LLM (if OPENAI_API_KEY in .env) + heuristic-only columns
    .venv/bin/python tests/eval_scam.py --no-llm   # heuristic only, no network
    .venv/bin/python tests/eval_scam.py -v         # also print reasons and spoken lines

Each snippet is fed line by line, exactly as the app does (check_scam after every heard sentence on the
recent window), and the case's risk is the highest risk returned at any point. A scam passes when it is
flagged high or medium; normal talk passes only when it is never flagged. Exit code 1 on any failure.
Runs on a temporary database, so kin.db is never touched.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["KIN_DB"] = os.path.join(tempfile.mkdtemp(prefix="kin_scam_eval_"), "eval.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kin import config, memory, safety  # noqa: E402

U = ""  # unknown voice (phone caller, TV, stranger)

# (label, kind, [(name, text), ...]); kind is "scam" or "ok"
CASES = [
    # ---------------------------------------------------------------- scams
    ("grandparent bail", "scam", [
        (U, "Grandpa? It's me, your grandson. I'm in trouble, I got arrested after a car accident."),
        (U, "I need $2,000 for bail and the lawyer says it has to be today."),
        (U, "Please don't tell Mom and Dad, they'll kill me. Can you get gift cards from Walgreens?")]),
    ("grandparent courier", "scam", [
        (U, "Hi Grandpa, it's me. I can't talk long, I'm at the police station."),
        (U, "Can you take out some cash? A courier will come by your house to pick it up in an hour."),
        (U, "And please keep this between us, okay?")]),
    ("IRS warrant", "scam", [
        (U, "This is Officer Daniels with the Internal Revenue Service. There is a warrant out for your arrest for unpaid taxes."),
        (U, "To resolve this you must pay $3,400 today. Stay on the line and do not hang up.")]),
    ("Medicare card", "scam", [
        (U, "Hello, I'm calling from Medicare about your new plastic benefits card."),
        (U, "Before we mail it I just need to confirm your Medicare number and your date of birth.")]),
    ("Social Security suspended", "scam", [
        (U, "This is the Social Security Administration. Your Social Security number has been suspended due to suspicious activity."),
        (U, "To reactivate it, please verify the number with me now or your benefits will be stopped.")]),
    ("tech support", "scam", [
        (U, "Hi, this is Microsoft technical support. Your computer has sent us an alert, it's infected with a virus."),
        (U, "I need you to go to the website I give you so I can take control and fix it. There's a $299 fee for the repair.")]),
    ("romance", "scam", [
        (U, "My darling, I miss you so much. I can't wait to finally hold you."),
        (U, "But they're holding me at customs in Ghana and I need $1,800 to pay the fee."),
        (U, "Could you send it by Western Union? I promise I'll pay you back the moment I land.")]),
    ("lottery prize", "scam", [
        (U, "Congratulations! You've won $1.5 million in the national sweepstakes!"),
        (U, "To release your prize, you just need to pay a small $499 processing fee with a prepaid Visa card.")]),
    ("bank fraud dept", "scam", [
        (U, "This is the fraud department at Wells Fargo. We've detected suspicious charges on your account."),
        (U, "To protect your money, please read me the six-digit code we just texted you.")]),
    ("bank safe account", "scam", [
        (U, "Your bank account has been compromised by hackers."),
        (U, "You need to move your savings into a safe account today. I'll give you the account number to transfer it to.")]),
    ("crypto investment", "scam", [
        (U, "I'm a financial advisor and I have a once-in-a-lifetime opportunity for you."),
        (U, "Bitcoin is going to double this week. If you transfer your savings to my wallet now, you'll be rich by Friday.")]),
    ("utility shutoff", "scam", [
        (U, "This is PG&E. Your power will be shut off in thirty minutes because of an overdue bill."),
        (U, "You can pay right now with a Green Dot card from the drugstore.")]),
    ("identity theft twist", "scam", [
        (U, "This is your bank's security team. Someone is pretending to be you and using your debit card."),
        (U, "We need your card number and PIN to block it before they empty your account.")]),
    ("Amazon refund", "scam", [
        (U, "Hello, this is Amazon customer service. We accidentally refunded you $5,000 instead of $50."),
        (U, "You need to send back the difference with Target gift cards or you'll be reported to the police.")]),

    # ---------------------------------------------------------------- normal family / daily life
    ("dinner payback", "ok", [
        ("Sarah", "Dad, I'll pay you back for dinner on Friday, it was forty dollars."),
        (config.WEARER_NAME, "Oh don't worry about it, sweetheart.")]),
    ("pharmacist refill", "ok", [
        (U, "Hi Joe, this is Maria from the Walgreens pharmacy."),
        (U, "Your blood pressure refill is ready for pickup. The copay is five dollars, you can pay when you come in.")]),
    ("borrow the car", "ok", [
        ("Tommy", "Grandpa, can I borrow the car tonight? I'll have it back by ten, I promise."),
        ("Tommy", "I'll fill up the gas too.")]),
    ("doctor appointment", "ok", [
        (U, "Hi, this is Dr. Patel's office calling to confirm your appointment Tuesday at ten."),
        (U, "Please bring your Medicare card and a list of your medications.")]),
    ("daughter paid bill", "ok", [
        ("Sarah", "Dad, I paid the electric bill online for you, so that's all taken care of."),
        ("Sarah", "And I'll pick up your prescription at CVS tomorrow.")]),
    ("birthday gift card", "ok", [
        ("Tommy", "Happy birthday Grandpa! There's a gift card for the coffee shop in your card."),
        ("Tommy", "Now you can get your cappuccino on me.")]),
    ("TV news", "ok", [
        (U, "Police say a man was arrested downtown after a high-speed chase."),
        (U, "Emergency crews are on the scene right now. Back to you in the studio.")]),
    ("friend warns about scam", "ok", [
        ("Bob", "Did you hear Martha got a call from someone pretending to be the IRS?"),
        ("Bob", "They wanted her to pay in gift cards! Never give anybody your bank account number, Joe.")]),
    ("grandson lunch money", "ok", [
        ("Tommy", "Grandpa, can you spot me twenty bucks for lunch? I'll Venmo you back next week."),
        (config.WEARER_NAME, "Of course, take it from my wallet.")]),
    # these two get past the keyword pre-filter, so they exercise the LLM's judgement
    ("bank teller PIN", "ok", [
        (U, "Good morning! Here's your withdrawal, two hundred in twenties."),
        (U, "Just enter your PIN on the keypad there, please.")]),
    ("TV scam-awareness ad", "ok", [
        (U, "Seniors: the IRS will never call you and demand payment with gift cards."),
        (U, "If that happens, just hang up and call your family. A message from the FTC.")]),
    ("plumber", "ok", [
        ("Sarah", "The plumber is coming at nine tomorrow."),
        ("Sarah", "I left a check on the counter for him, so you don't need to pay anything.")]),
]

ORDER = {None: 0, "medium": 1, "high": 2}


def run_case(lines):
    """Feed lines one at a time like the app; return (max_risk, first result at that risk)."""
    safety.reset()
    seen, best, best_r = [], None, None
    for name, text in lines:
        seen.append({"speaker": "S0" if name else "S1", "name": name, "text": text, "ts": time.time()})
        r = safety.check_scam(list(seen))
        risk = r["risk"] if r else None
        if ORDER[risk] > ORDER[best]:
            best, best_r = risk, r
    safety.reset()
    return best, best_r


def evaluate(use_llm, verbose=False):
    real = config.OPENAI_API_KEY
    if not use_llm:
        config.OPENAI_API_KEY = ""
    out = []
    try:
        for label, kind, lines in CASES:
            t0 = time.time()
            risk, r = run_case(lines)
            ok = (risk in ("high", "medium")) if kind == "scam" else (risk is None)
            out.append((label, kind, risk, ok, time.time() - t0, r))
    finally:
        config.OPENAI_API_KEY = real
    return out


def main():
    args = sys.argv[1:]
    verbose = "-v" in args
    modes = [("heuristic", False)]
    if config.OPENAI_API_KEY and "--no-llm" not in args:
        modes.insert(0, (f"LLM ({config.OPENAI_MODEL})", True))
    memory.upsert_person("Sarah", "daughter")
    memory.upsert_person("Tommy", "grandson")
    memory.upsert_person("Bob", "friend")

    results = {name: evaluate(use, verbose) for name, use in modes}
    names = [m for m, _ in modes]
    print(f"\n{'case':26} {'kind':5} " + " ".join(f"{n:>22}" for n in names))
    print("-" * (33 + 23 * len(names)))
    for i, (label, kind, _) in enumerate(CASES):
        cells = []
        for n in names:
            _, _, risk, ok, dt, _ = results[n][i]
            cells.append(f"{(risk or 'none') + (' ok' if ok else ' FAIL'):>17} {dt:4.1f}s")
        print(f"{label:26} {kind:5} " + " ".join(f"{c:>22}" for c in cells))
    print()
    failed = False
    for n in names:
        rs = results[n]
        scams = [r for r in rs if r[1] == "scam"]
        oks = [r for r in rs if r[1] == "ok"]
        caught = sum(r[3] for r in scams)
        high = sum(r[2] == "high" for r in scams)
        fa = sum(not r[3] for r in oks)
        print(f"{n}: caught {caught}/{len(scams)} scams ({high} high), false alarms {fa}/{len(oks)}")
        failed |= caught < len(scams) or fa > 0
    if verbose:
        print()
        for label, kind, risk, ok, dt, r in results[names[0]]:
            if r:
                print(f"[{label}] {risk}: {r['reason']}\n    say: {r['say']}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
