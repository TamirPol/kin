"""Kin's safety layer: scam detection and the guard-railed economic agent (Stripe test mode).

Public API (all synchronous, safe to call from worker threads):
  check_scam(lines)                         -> None | {'risk','reason','say'}
  purchase(item, merchant, amount_cents)    -> {'status','reason','say','stripe_id'}
  parse_purchase_request(text)              -> None | {'item','merchant','amount_cents'}
  tool_schemas()                            -> OpenAI function definitions (purchase)
  handle_tool_call(name, arguments)         -> dict result for a tool call from the voice agent
  purchase_summary()                        -> dashboard dict (spent today vs cap, last purchases, lock)
Helpers: scam_lock_active(), scam_lock_remaining(), clear_scam_lock(), spent_today_cents(),
         family_contact(), reset()

Design: every decision has a deterministic heuristic path, so Kin works with no keys.
An LLM (if OPENAI_API_KEY is set) only confirms / refines; it can never loosen the
spending guardrails, which are always enforced in plain Python below.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime

from . import config, memory

# ---------------------------------------------------------------- settings
APPROVED_MERCHANTS = ["Walgreens", "CVS", "Safeway", "Whole Foods", "Amazon Pharmacy"]
_MERCHANT_ALIASES = {
    "walgreens": "Walgreens", "walgreen": "Walgreens", "cvs": "CVS", "cvs pharmacy": "CVS",
    "safeway": "Safeway", "whole foods": "Whole Foods", "wholefoods": "Whole Foods",
    "whole foods market": "Whole Foods", "amazon pharmacy": "Amazon Pharmacy",
}
DAILY_CAP_MULTIPLIER = 3
SCAM_LOCK_SECONDS = 30 * 60
FAMILY_CONTACT = os.environ.get("KIN_FAMILY_CONTACT", "")   # optional override, e.g. "Sarah"
_CHILD_RX = re.compile(r"\b(?:daughter|son|child|kid)\b", re.I)   # "grandson" deliberately doesn't match

BLOCKED_CATEGORIES = {
    "gift card": r"gift ?cards?|itunes|google play|steam card|apple card|prepaid (?:debit |visa )?cards?|vanilla ?visa|green ?dot",
    "crypto": r"crypto(?:currency)?|bitcoin|btc|ethereum|usdt|tether|coinbase",
    "wire / money transfer": r"wire(?: transfer)?|western union|moneygram|money ?orders?|zelle|venmo|cash ?app|money transfer",
}

# Price table for the no-LLM parser: keyword regex -> (item name, cents, default merchant)
PRICE_TABLE = [
    (r"blood ?pressure|lisinopril|amlodipine", "blood pressure pills", 1299, "Walgreens"),
    (r"prescription|refill|pills|medication|medicine|meds\b", "prescription refill", 1500, "Walgreens"),
    (r"vitamins?", "vitamins", 999, "CVS"),
    (r"tooth ?paste", "toothpaste", 499, "CVS"),
    (r"tissues?|kleenex", "tissues", 399, "CVS"),
    (r"hearing aid batter", "hearing aid batteries", 1199, "Walgreens"),
    (r"batter(?:y|ies)", "batteries", 899, "CVS"),
    (r"band-?aids?|bandages?", "bandages", 599, "CVS"),
    (r"milk", "milk", 449, "Safeway"),
    (r"bread", "bread", 399, "Safeway"),
    (r"eggs", "eggs", 599, "Safeway"),
    (r"bananas?", "bananas", 199, "Safeway"),
    (r"coffee", "coffee", 1099, "Whole Foods"),
    (r"groceries", "groceries", 3500, "Safeway"),
]
_PHARMACY_DEFAULT = "Walgreens"

# ---------------------------------------------------------------- state
_state_lock = threading.RLock()
_scam_lock_until = 0.0
_scam_reason = ""


def scam_lock_active() -> bool:
    return time.time() < _scam_lock_until


def scam_lock_remaining() -> int:
    """Seconds left on the scam lock (0 if none)."""
    return max(0, int(_scam_lock_until - time.time()))


def set_scam_lock(reason: str, seconds: float = SCAM_LOCK_SECONDS) -> None:
    global _scam_lock_until, _scam_reason
    with _state_lock:
        _scam_lock_until = max(_scam_lock_until, time.time() + seconds)
        _scam_reason = reason


def clear_scam_lock() -> None:
    """For the family dashboard: 'it was fine, unlock purchases'."""
    global _scam_lock_until, _scam_reason
    with _state_lock:
        _scam_lock_until = 0.0
        _scam_reason = ""


def reset() -> None:
    """Tests only."""
    clear_scam_lock()


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def family_contact() -> str:
    """Who Kin tells the wearer it has let know: env override, else a daughter/son from memory, else 'your family'."""
    name = _clean_name(FAMILY_CONTACT)
    if name:
        return name
    try:                                                # an emergency contact from /setup comes first
        from . import settings
        name = _clean_name(settings.first_contact_name())
        if name:
            return name
    except Exception:
        pass
    try:
        for p in memory.people():                       # most recently seen first
            name = _clean_name((p or {}).get("name"))
            if name and _CHILD_RX.search((p or {}).get("relationship") or ""):
                return name
    except Exception:
        pass
    return "your family"


def _clean_name(name) -> str:
    """'  Sarah. ' -> 'Sarah'; '' / '.' / None -> ''."""
    return re.sub(r"\s+", " ", str(name or "")).strip(" \t.,;:!?'\"")


def _clean_say(text: str) -> str:
    """No doubled spaces, no space before punctuation, no empty '..' — always ends with a full stop."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"\s+([.,!?])", r"\1", t)
    t = re.sub(r"([.,!?])[.,]+", r"\1", t)
    return t if not t or t[-1] in ".!?" else t + "."


def _cap(name: str) -> str:
    """'your family' -> 'Your family' at the start of a sentence; names unchanged."""
    return name[:1].upper() + name[1:]


# ---------------------------------------------------------------- LLM helper
def _llm_json(system: str, user: str, schema: dict, name: str, timeout: float = 8.0) -> dict | None:
    """Structured-output call. Returns parsed dict, or None on any failure (caller falls back)."""
    if not config.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=timeout, max_retries=1)
        r = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": name, "strict": True, "schema": schema}},
        )
        return json.loads(r.choices[0].message.content or "null")
    except Exception as e:  # network, model name, bad JSON...
        print(f"[safety] LLM call failed, using heuristic: {e!r}")
        return None


# ================================================================ 1. scam detection
_P = lambda *xs: re.compile("|".join(xs), re.I)  # noqa: E731
SIGNALS = {
    # asks for money in hard-to-reverse forms
    "money": _P(r"gift ?cards?", r"itunes|google play|steam card", r"wire (?:the )?(?:money|transfer|it)|wire transfer",
                r"western union|moneygram", r"bitcoin|crypto|btc atm|bitcoin atm", r"\bbail\b",
                r"send (?:me |us |him |her )?(?:the )?(?:money|cash|\$?\d)", r"(?:pay|send).{0,30}(?:fee|fine|deposit)",
                r"zelle|venmo|cash ?app", r"money order", r"(?:\$|dollars?\b).{0,40}(?:right away|today|now)",
                r"withdraw (?:some )?(?:cash|money)", r"(?:take|get) out (?:some )?(?:cash|money)",
                r"(?:pay|cover).{0,20}(?:lawyer|attorney|hospital bill)",
                r"\$\s?\d[\d,]*(?:\.\d\d)? (?:processing |repair |release )?(?:fee|fine|deposit|charge)",
                r"green ?dot|prepaid (?:visa |debit )?card|vanilla ?(?:visa|card)", r"courier|pick (?:it|the money|the cash) up",
                r"(?:transfer|move) (?:all )?(?:your|the|my)? ?(?:savings|money|funds)", r"safe account", r"wallet address|to my wallet"),
    # asks for identity / account secrets
    "sensitive": _P(r"card number", r"credit card|debit card", r"social security number|\bssn\b|social security #",
                    r"bank account|account number|routing number", r"password",
                    r"(?:read|tell|give|say|need)\b.{0,20}\bpin\b|\bpin\b.{0,20}(?:to me|over the phone)|pin number",
                    r"verification code|security code|one[- ]time code|\bcvv\b", r"medicare (?:number|id)\b",
                    r"(?:read|give|tell) me (?:the |your )?(?:\w+[- ]digit )?code", r"code (?:we|i) (?:just )?(?:texted|sent)",
                    r"(?:read|give|confirm|verify) (?:me )?(?:your |the )?(?:medicare|social security|card|account) (?:number|card)",
                    r"take control|remote access|anydesk|teamviewer|screen ?share"),
    # pretends to be an authority or a relative in trouble
    "impersonation": _P(r"\birs\b|internal revenue", r"medicare", r"social security (?:administration|office)",
                        r"(?:this is|i'?m) (?:officer|detective|sergeant|agent)", r"police|sheriff|warrant",
                        r"(?:in|from) jail|arrested|lawyer|attorney|public defender",
                        r"grandson|granddaughter|grandma it'?s me|grandpa it'?s me|it'?s your grand",
                        r"tech(?:nical)? support|microsoft|apple support|your computer (?:has|is)|virus",
                        r"fraud department|suspicious (?:charges|activity)|(?:account|number) has been (?:suspended|compromised|hacked)",
                        r"pg&e|electric company|power (?:will be|is going to be) (?:shut|cut) off",
                        r"customer service|refunded you|customs|financial advisor|investment opportunity|once[- ]in[- ]a[- ]lifetime",
                        r"my darling|my love\b|i miss you so much",
                        r"you(?:'ve| have) won|lottery|sweepstakes|prize", r"your (?:bank|account) (?:has been|is) (?:locked|frozen|compromised)"),
    # urgency, secrecy, threats
    "pressure": _P(r"don'?t tell (?:anyone|anybody|mom|dad|my (?:mom|dad|parents))", r"keep (?:this|it) (?:between us|a secret|quiet)",
                   r"\bsecret\b", r"or (?:you'?ll|you will|they'?ll) (?:be (?:arrested|reported)|go to jail|lose)",
                   r"suspended|frozen|final notice|shut off|cut off|warrant", r"stay on the (?:line|phone)|don'?t hang up",
                   r"(?:it )?has to be today|you must pay|in the next (?:hour|\d+ minutes)|in (?:thirty|\d+) minutes"),
    # generic urgency words: weak on their own (TV news says "emergency ... right now" too)
    "urgency": _P(r"right now|right away|immediately|as soon as possible|\basap\b|hurry|urgent|emergency",
                  r"today only|within the hour|before (?:it'?s too late|tonight)"),
    # "now" / "today": only counts as a hook for an unknown voice that is also asking for money
    "timing": _P(r"\btoday\b|\bnow\b"),
}

# Lines that warn ABOUT scams (TV ads, a friend's advice) aren't scams themselves.
_WARNING_RX = re.compile(r"will never (?:call|ask|demand|email|text)|never (?:give|share|send) (?:anyone|anybody)|"
                         r"pretending to be|hang up and call|a message from the (?:ftc|fbi|aarp)|"
                         r"(?:is|was|sounds like|that'?s) (?:a|another) scam", re.I)
# ...unless that same line also asks the wearer for something (a scammer can say "someone is pretending to be you").
_REQUEST_RX = re.compile(r"\b(?:i|we) (?:need|have to|must)\b|\b(?:read|give|tell|send) me\b|\bgo (?:buy|get)\b|"
                         r"\byou (?:must|need to|have to)\b|\b(?:confirm|verify|provide)\b|\bcan you (?:send|read|give|buy)\b", re.I)


def _scan(lines: list[dict]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (signals from unknown speakers, signals from known people) -> {signal: [matched phrases]}."""
    unknown: dict[str, list[str]] = {}
    known: dict[str, list[str]] = {}
    wearer = (config.WEARER_NAME or "").strip().lower()
    for ln in lines:
        text = (ln.get("text") or "").strip()
        if not text:
            continue
        name = (ln.get("name") or "").strip()
        if name and name.lower() == wearer:
            continue  # the wearer talking about gift cards is not the threat
        if _WARNING_RX.search(text) and not _REQUEST_RX.search(text):
            continue
        bucket = known if name else unknown
        for sig, rx in SIGNALS.items():
            hits = [m.group(0) for m in rx.finditer(text)]
            if hits:
                bucket.setdefault(sig, []).extend(hits)
    return unknown, known


def _heuristic_risk(unknown: dict, known: dict) -> tuple[str | None, str]:
    def score(s: dict) -> str | None:
        ask = "money" in s or "sensitive" in s
        hook = "impersonation" in s or "pressure" in s or "urgency" in s or "timing" in s
        if ask and hook:
            return "high"
        if "sensitive" in s:
            return "high" if hook else "medium"
        if ask or ("impersonation" in s and "pressure" in s):
            return "medium"
        return None

    def describe(s: dict) -> str:
        parts = []
        for sig in ("money", "sensitive", "impersonation", "pressure", "urgency", "timing"):
            if sig in s:
                uniq = list(dict.fromkeys(h.lower() for h in s[sig]))[:3]
                parts.append(f"{sig}: {', '.join(uniq)}")
        return "; ".join(parts)

    r_unknown = score(unknown)
    # A known family member lowers risk, but money + urgency still flags.
    r_known = None
    if known:
        ask = "money" in known or "sensitive" in known
        rush = "pressure" in known or "urgency" in known
        if ask and rush and ("impersonation" in known or "sensitive" in known):
            r_known = "high"
        elif ask and rush:
            r_known = "medium"
    order = {None: 0, "medium": 1, "high": 2}
    if order[r_unknown] >= order[r_known]:
        return r_unknown, ("unknown caller — " + describe(unknown)) if r_unknown else ""
    return r_known, "known person but money + urgency — " + describe(known)


_SCAM_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["risk", "reason"],
    "properties": {
        "risk": {"type": "string", "enum": ["none", "medium", "high"]},
        "reason": {"type": "string", "description": "One short sentence for the family."},
    },
}
_SCAM_SYSTEM = (
    "You protect an older adult with early memory loss from scams. You get a short transcript of what "
    "people around them just said. Lines labelled with a name are family/friends the wearer knows; "
    "'unknown' is an unidentified voice (a phone caller, a stranger, or the TV/radio).\n"
    "Rate scam risk:\n"
    "- 'high': someone is steering the wearer to pay with gift cards, prepaid cards, wire/Western Union, "
    "crypto, cash pickup or a 'safe account'; or asking for card/bank/Social Security/Medicare numbers, "
    "passwords or texted codes, or remote access to a computer; or pretends to be a relative in trouble, "
    "the IRS, Social Security, Medicare, police, a utility, a bank fraud department, tech support, a "
    "lottery/prize, or a romantic partner who needs money. Secrecy ('don't tell anyone') or threats "
    "(arrest, shut-off) make it high.\n"
    "- 'medium': something is steering the wearer toward money or personal details and you can't tell if "
    "it is safe.\n"
    "- 'none': ordinary life. Examples of 'none': family paying each other back or lending small amounts; "
    "a grandchild borrowing the car; a pharmacy saying a refill is ready or a copay is due at pickup; a "
    "doctor's office confirming an appointment or asking the wearer to BRING their insurance/Medicare card; "
    "TV or radio news; a friend warning the wearer about scams; a gift card given as a present.\n"
    "If your reason would say it sounds routine, the risk is 'none'. Be decisive. The reason is one short, "
    "calm sentence for the family dashboard."
)


def check_scam(lines: list[dict]) -> dict | None:
    """Scan recent transcript lines. None if fine, else {'risk','reason','say'}.

    On 'high' risk: writes a 'scam' alert (once per lock window) and locks purchases for 30 min.
    """
    lines = [l for l in (lines or []) if isinstance(l, dict)][-30:]
    unknown, known = _scan(lines)
    risk, reason = _heuristic_risk(unknown, known)
    if risk is None:
        return None  # pre-filter: nothing scam-shaped, don't spend an LLM call

    if config.OPENAI_API_KEY:
        convo = "\n".join(f"[{(l.get('name') or 'unknown')}] {l.get('text', '')}" for l in lines)
        verdict = _llm_json(_SCAM_SYSTEM, f"Wearer: {config.WEARER_NAME}\nTranscript:\n{convo}",
                            _SCAM_SCHEMA, "scam_check")
        if verdict and verdict.get("risk") in ("none", "medium", "high"):
            llm_risk = verdict["risk"]
            # The LLM may downgrade, but an unknown caller asking for money + pressure stays at least medium.
            if llm_risk == "none" and risk == "high" and not known:
                llm_risk = "medium"
            if llm_risk == "none":
                return None
            risk, reason = llm_risk, (verdict.get("reason") or reason)

    who = family_contact()
    if risk == "high":
        say = (f"I think this might be a scam, so let's not give any money or numbers. "
               f"It's okay to just hang up, and I've let {who} know.")
        with _state_lock:
            first = not scam_lock_active()
            set_scam_lock(reason)
        if first:
            memory.add_alert("scam", f"Possible scam call ({reason}). Kin warned him not to send money.")
    else:
        say = f"Just a gentle reminder: if anyone asks for money or numbers, let's check with {who} first."
    return {"risk": risk, "reason": reason, "say": _clean_say(say)}


# ================================================================ 2. the economic agent
def _norm_merchant(merchant: str) -> str | None:
    m = re.sub(r"[^a-z ]", "", (merchant or "").lower().replace("'", "")).strip()
    m = re.sub(r"\s+", " ", m)
    if m in _MERCHANT_ALIASES:
        return _MERCHANT_ALIASES[m]
    for a in APPROVED_MERCHANTS:
        if m == a.lower():
            return a
    return None


def _blocked_category(item: str) -> str | None:
    for cat, rx in BLOCKED_CATEGORIES.items():
        if re.search(rf"\b(?:{rx})\b", item or "", re.I):
            return cat
    return None


def spent_today_cents() -> int:
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    rows = memory._rows("SELECT COALESCE(SUM(amount_cents),0) AS s FROM purchases "
                        "WHERE status='allowed' AND ts>=?", (midnight,))
    return int(rows[0]["s"])


def _stripe_client():
    """StripeClient for the installed stripe-python (v8+; v17 tested). Separate fn so tests can stub it."""
    from stripe import StripeClient
    return StripeClient(config.STRIPE_SECRET_KEY, max_network_retries=2)


def _charge(item: str, merchant: str, amount_cents: int, idempotency_key: str = "") -> str:
    """Create + confirm a Stripe test-mode PaymentIntent, or simulate when no key. Returns the id.

    Uses the test card pm_card_visa, so it only makes sense with an sk_test_ key; a live key is refused.
    The idempotency key makes Stripe's automatic network retries safe (never a double charge).
    """
    key = config.STRIPE_SECRET_KEY
    if not key:
        return "sim_" + uuid.uuid4().hex[:20]
    if not key.startswith(("sk_test_", "rk_test_")):
        raise RuntimeError("Kin only charges in Stripe test mode (need an sk_test_ key)")
    idem = idempotency_key or f"kin-{uuid.uuid4().hex}"
    pi = _stripe_client().v1.payment_intents.create(
        params={
            "amount": int(amount_cents),
            "currency": "usd",
            "payment_method": "pm_card_visa",
            "confirm": True,
            "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"},
            "description": f"Kin for {config.WEARER_NAME}: {item} from {merchant} ({_money(amount_cents)})"[:1000],
            "metadata": {
                "agent": "kin", "wearer": config.WEARER_NAME[:500], "item": item[:500], "merchant": merchant,
                "per_purchase_limit_cents": str(config.SPEND_LIMIT_CENTS),
                "daily_cap_cents": str(config.SPEND_LIMIT_CENTS * DAILY_CAP_MULTIPLIER),
                "spent_today_before_cents": str(spent_today_cents()),
                "guardrails": "approved merchant; under per-purchase limit and daily cap; no scam lock",
                "idempotency_key": idem,
            },
        },
        options={"idempotency_key": idem},
    )
    if pi.status not in ("succeeded", "processing", "requires_capture"):
        raise RuntimeError(f"payment status {pi.status}")
    return pi.id


def _block(item: str, merchant: str, amount_cents: int, reason: str, say: str) -> dict:
    memory.add_purchase(item, merchant, amount_cents, "blocked", reason)
    memory.add_alert("spending", f"Blocked: {item} from {merchant or '?'} for {_money(amount_cents)} — {reason}")
    return {"status": "blocked", "reason": reason, "say": _clean_say(say), "stripe_id": ""}


def purchase(item: str, merchant: str, amount_cents: int) -> dict:
    """Try to buy `item` from `merchant`. Guardrails are always enforced here, never by the LLM."""
    item = (item or "").strip() or "unspecified item"
    merchant_in = (merchant or "").strip()
    try:
        amount_cents = int(amount_cents)
    except (TypeError, ValueError):
        amount_cents = 0
    who = family_contact()
    limit = config.SPEND_LIMIT_CENTS

    with _state_lock:  # serialize so two threads can't both squeeze under the daily cap
        if scam_lock_active():
            mins = max(1, round(scam_lock_remaining() / 60))
            return _block(item, merchant_in, amount_cents, "scam lock active (recent suspicious call)",
                          f"Let's wait about {mins} minutes before ordering anything, just to be safe after that call. "
                          f"I've let {who} know, and your {item} can come right after.")
        cat = _blocked_category(item) or _blocked_category(merchant_in)
        if cat:
            what = {"gift card": "gift cards", "crypto": "crypto",
                    "wire / money transfer": "wire or money transfers"}.get(cat, cat)
            return _block(item, merchant_in, amount_cents, f"blocked category: {cat}",
                          f"I don't buy {what}, because scammers often ask for those. "
                          f"If someone asked you for one, let's check with {who} first.")
        canon = _norm_merchant(merchant_in)
        if not canon:
            return _block(item, merchant_in, amount_cents, f"merchant not approved: {merchant_in or '(none)'}",
                          f"I can only order from your usual stores, like Walgreens or Safeway. I'll ask {who} about this one.")
        if amount_cents <= 0:
            return _block(item, canon, amount_cents, "invalid amount",
                          "I wasn't sure what that costs, so I didn't order it yet. Could you tell me the price?")
        if amount_cents > limit:
            return _block(item, canon, amount_cents, f"over per-purchase limit ({_money(amount_cents)} > {_money(limit)})",
                          f"That's a bit more than your {_money(limit)} limit, so I've asked {who} to approve it.")
        spent = spent_today_cents()
        cap = limit * DAILY_CAP_MULTIPLIER
        if spent + amount_cents > cap:
            return _block(item, canon, amount_cents,
                          f"over daily cap ({_money(spent)} spent + {_money(amount_cents)} > {_money(cap)})",
                          f"You've done plenty of shopping today, so I've asked {who} about this one.")
        idem = f"kin-{uuid.uuid4().hex}"
        try:
            sid = _charge(item, canon, amount_cents, idem)
        except Exception as e:
            reason = f"payment failed: {type(e).__name__}: {e}"[:300]
            return _block(item, canon, amount_cents, reason,
                          f"Sorry, the payment didn't go through. I've let {who} know, so don't worry.")
        memory.add_purchase(item, canon, amount_cents, "allowed", "within guardrails", sid)
    return {"status": "allowed", "reason": "within guardrails",
            "say": _clean_say(f"Done. I ordered your {item} from {canon} for {_money(amount_cents)}."),
            "stripe_id": sid}


def purchase_summary(limit: int = 5) -> dict:
    """For the family dashboard: today's spend vs the cap, the scam lock, and the last purchases."""
    spent = spent_today_cents()
    cap = config.SPEND_LIMIT_CENTS * DAILY_CAP_MULTIPLIER
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    blocked_today = int(memory._rows("SELECT COUNT(*) AS n FROM purchases WHERE status='blocked' AND ts>=?",
                                     (midnight,))[0]["n"])
    last = [{"ts": p["ts"], "item": p["item"], "merchant": p["merchant"], "amount_cents": p["amount_cents"],
             "amount": _money(p["amount_cents"] or 0), "status": p["status"], "reason": p["reason"],
             "stripe_id": p["stripe_id"] or "", "live": (p["stripe_id"] or "").startswith("pi_")}
            for p in memory.purchases(limit)]
    return {
        "spent_today_cents": spent, "spent_today": _money(spent),
        "daily_cap_cents": cap, "daily_cap": _money(cap),
        "remaining_today_cents": max(0, cap - spent), "remaining_today": _money(max(0, cap - spent)),
        "per_purchase_limit_cents": config.SPEND_LIMIT_CENTS, "per_purchase_limit": _money(config.SPEND_LIMIT_CENTS),
        "pct_of_cap": round(100 * spent / cap) if cap else 0,
        "blocked_today": blocked_today,
        "scam_lock_active": scam_lock_active(), "scam_lock_remaining_s": scam_lock_remaining(),
        "scam_lock_reason": _scam_reason if scam_lock_active() else "",
        "approved_merchants": list(APPROVED_MERCHANTS),
        "stripe_mode": "test" if config.STRIPE_SECRET_KEY.startswith(("sk_test_", "rk_test_")) else
                       ("simulated" if not config.STRIPE_SECRET_KEY else "refused (not a test key)"),
        "family_contact": family_contact(),
        "last": last,
    }


# ================================================================ 3. parsing a spoken request
_BUY_RX = re.compile(r"\b(re-?order|order|buy|purchase|get me|pick up|refill|i need (?:more|some|new)|"
                     r"we(?:'re| are) out of|i(?:'m| am) out of|run out of|ran out of)\b", re.I)
_PRICE_RX = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*dollars?", re.I)

_PARSE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["is_purchase", "item", "merchant", "amount_cents"],
    "properties": {
        "is_purchase": {"type": "boolean"},
        "item": {"type": "string"},
        "merchant": {"type": "string", "description": "Store named, or the best usual store if none named."},
        "amount_cents": {"type": "integer", "description": "Stated price, or a realistic US estimate, in cents."},
    },
}


def _table_match(text: str) -> tuple[str, int, str] | None:
    for rx, name, price, dm in PRICE_TABLE:
        if re.search(rx, text or "", re.I):
            return name, price, dm
    return None


def _tidy_item(item: str) -> str:
    """'Blood pressure pills (prescription refill)' -> 'blood pressure pills' (it's spoken back as 'your ...')."""
    item = re.sub(r"\s*\([^)]*\)", "", item or "").strip(" .")
    item = re.sub(r"^(?:my|some|more|a|an|the)\s+", "", item, flags=re.I)
    return (item[:1].lower() + item[1:]) if item and not item[:2].isupper() else item


def _heuristic_parse(text: str) -> dict | None:
    t = text or ""
    if not _BUY_RX.search(t):
        return None
    # merchant: approved names first, then "from/at X"
    merchant = ""
    low = t.lower().replace("'", "")
    for alias in sorted(_MERCHANT_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            merchant = _MERCHANT_ALIASES[alias]
            break
    if not merchant:
        m = re.search(r"\b(?:from|at)\s+([A-Za-z][\w'&. ]{1,40}?)(?:\s+for\b|[.,!?]|$)", t)
        if m:
            merchant = m.group(1).strip()
    # item + price
    item, cents, default_merchant = "", 0, ""
    for rx, name, price, dm in PRICE_TABLE:
        if re.search(rx, t, re.I):
            item, cents, default_merchant = name, price, dm
            break
    if not item:
        m = re.search(_BUY_RX.pattern + r"\s+(?:me\s+)?(?:some\s+|more\s+|my\s+|a\s+|an\s+|the\s+)*(.+?)"
                      r"(?:\s+(?:from|at|for)\b|[.,!?]|$)", t, re.I)
        item = (m.group(2).strip() if m else "") or "item"
        if _blocked_category(item):
            cents = 10000
        else:
            cents = 1500
    pm = _PRICE_RX.search(t)
    if pm:
        cents = int(round(float(pm.group(1) or pm.group(2)) * 100))
    if not merchant:
        merchant = default_merchant or _PHARMACY_DEFAULT
    return {"item": item, "merchant": merchant, "amount_cents": cents}


def parse_purchase_request(text: str) -> dict | None:
    """'Kin, reorder my blood pressure pills from Walgreens' -> {'item','merchant','amount_cents'}."""
    if not (text or "").strip():
        return None
    if config.OPENAI_API_KEY:
        r = _llm_json(
            "Decide if the user is asking their assistant to buy/order something. If so, extract the item "
            "(a short lowercase phrase as the user would say it, e.g. 'blood pressure pills', no brackets), "
            f"the store (approved stores: {', '.join(APPROVED_MERCHANTS)}; if none named pick the usual one; "
            "keep any other named store verbatim), and the price in US cents (stated, or a realistic estimate). "
            "If not a purchase request, set is_purchase false and the other fields to empty / 0.",
            text, _PARSE_SCHEMA, "purchase_request")
        if r is not None:
            if not r.get("is_purchase"):
                return None
            try:
                out = {"item": _tidy_item(str(r["item"])) or "item", "merchant": str(r["merchant"]).strip(),
                       "amount_cents": int(r["amount_cents"])}
            except (KeyError, TypeError, ValueError):
                out = None
            if out:
                # Known household items keep their usual name + price (stable demo, no LLM price drift),
                # unless the wearer said a price out loud.
                known = _table_match(text)
                if known and not _PRICE_RX.search(text) and not _blocked_category(out["item"]):
                    out["amount_cents"] = known[1]
                    if known[0].lower() in text.lower():   # "...my blood pressure pills" -> exactly that
                        out["item"] = known[0]
                    out["merchant"] = out["merchant"] or known[2]
                out["merchant"] = out["merchant"] or _PHARMACY_DEFAULT
                return out
    return _heuristic_parse(text)


# ================================================================ 4. tool schema for the voice agent
def tool_schemas() -> list[dict]:
    return [{
        "type": "function",
        "function": {
            "name": "purchase",
            "description": (
                f"Buy something for {config.WEARER_NAME} with the family-approved card. Only call when the wearer "
                f"clearly asks. Approved stores: {', '.join(APPROVED_MERCHANTS)}. Limit {_money(config.SPEND_LIMIT_CENTS)} "
                "per purchase. Never for gift cards, crypto or wire transfers. The result has a 'say' field: "
                "speak it to the wearer."),
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "What to buy, e.g. 'blood pressure pills'."},
                    "merchant": {"type": "string", "enum": APPROVED_MERCHANTS + ["other"],
                                 "description": "Store to buy from."},
                    "amount_cents": {"type": "integer", "description": "Price in US cents (estimate if unknown)."},
                },
                "required": ["item", "merchant", "amount_cents"],
                "additionalProperties": False,
            },
        },
    }]


def handle_tool_call(name: str, arguments: str | dict) -> dict:
    """Dispatch a tool call from the voice agent. `arguments` may be a JSON string or dict."""
    if name != "purchase":
        return {"error": f"unknown tool {name}"}
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except Exception:
        return {"error": "bad arguments"}
    return purchase(args.get("item", ""), args.get("merchant", ""), args.get("amount_cents", 0))
