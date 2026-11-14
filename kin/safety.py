"""Kin's safety layer: scam detection and the guard-railed economic agent (Stripe test mode).

Public API (all synchronous, safe to call from worker threads):
  check_scam(lines)                         -> None | {'risk','reason','say'}
  purchase(item, merchant, amount_cents)    -> {'status','reason','say','stripe_id'}
  parse_purchase_request(text)              -> None | {'item','merchant','amount_cents'}
  tool_schemas()                            -> OpenAI function definitions (purchase)
  handle_tool_call(name, arguments)         -> dict result for a tool call from the voice agent
Helpers: scam_lock_active(), scam_lock_remaining(), clear_scam_lock(), spent_today_cents(), reset()

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
FAMILY_CONTACT = os.environ.get("KIN_FAMILY_CONTACT", "your family")   # e.g. "Sarah"

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
                r"withdraw (?:some )?(?:cash|money)", r"(?:pay|cover).{0,20}(?:lawyer|attorney|hospital bill)"),
    # asks for identity / account secrets
    "sensitive": _P(r"card number", r"credit card|debit card", r"social security number|\bssn\b|social security #",
                    r"bank account|account number|routing number", r"\bpin\b", r"password",
                    r"verification code|security code|one[- ]time code|\bcvv\b", r"medicare (?:number|card|id)"),
    # pretends to be an authority or a relative in trouble
    "impersonation": _P(r"\birs\b|internal revenue", r"medicare", r"social security (?:administration|office)",
                        r"(?:this is|i'?m) (?:officer|detective|sergeant|agent)", r"police|sheriff|warrant",
                        r"(?:in|from) jail|arrested|lawyer|attorney|public defender",
                        r"grandson|granddaughter|grandma it'?s me|grandpa it'?s me|it'?s your grand",
                        r"tech support|microsoft|apple support|your computer (?:has|is)|virus",
                        r"you(?:'ve| have) won|lottery|sweepstakes|prize", r"your (?:bank|account) (?:has been|is) (?:locked|frozen|compromised)"),
    # urgency, secrecy, threats
    "pressure": _P(r"don'?t tell (?:anyone|anybody|mom|dad|my (?:mom|dad|parents))", r"keep (?:this|it) (?:between us|a secret|quiet)",
                   r"\bsecret\b", r"right now|right away|immediately|as soon as possible|\basap\b|hurry|urgent|emergency",
                   r"today only|within the hour|in the next (?:hour|\d+ minutes)|before (?:it'?s too late|tonight)",
                   r"or (?:you'?ll|you will|they'?ll) (?:be arrested|go to jail|lose)", r"suspended|frozen|final notice",
                   r"stay on the (?:line|phone)|don'?t hang up"),
}


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
        bucket = known if name else unknown
        for sig, rx in SIGNALS.items():
            hits = [m.group(0) for m in rx.finditer(text)]
            if hits:
                bucket.setdefault(sig, []).extend(hits)
    return unknown, known


def _heuristic_risk(unknown: dict, known: dict) -> tuple[str | None, str]:
    def score(s: dict) -> str | None:
        ask = "money" in s or "sensitive" in s
        hook = "impersonation" in s or "pressure" in s
        if ask and hook:
            return "high"
        if "sensitive" in s:
            return "high" if "impersonation" in s or "pressure" in s else "medium"
        if ask or ("impersonation" in s and "pressure" in s):
            return "medium"
        return None

    def describe(s: dict) -> str:
        parts = []
        for sig in ("money", "sensitive", "impersonation", "pressure"):
            if sig in s:
                uniq = list(dict.fromkeys(h.lower() for h in s[sig]))[:3]
                parts.append(f"{sig}: {', '.join(uniq)}")
        return "; ".join(parts)

    r_unknown = score(unknown)
    # A known family member lowers risk, but money + urgency still flags.
    r_known = None
    if known:
        ask = "money" in known or "sensitive" in known
        if ask and "pressure" in known and ("impersonation" in known or "sensitive" in known):
            r_known = "high"
        elif ask and "pressure" in known:
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
    "You protect an older adult with early dementia from scams. You get a short transcript of what "
    "people around them said. Lines labelled with a known name are family/friends the wearer knows; "
    "'unknown' means an unidentified voice (often a phone caller). Rate scam risk: 'high' = someone is "
    "pressuring the wearer to pay in gift cards / wire / crypto / cash, give card numbers, SSN, bank or "
    "Medicare details, or pretends to be a relative in trouble, the IRS, Medicare, police or tech support; "
    "'medium' = suspicious but unclear; 'none' = normal conversation (a family member mentioning a "
    "pharmacy or groceries is normal). Be decisive."
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

    if risk == "high":
        say = ("This sounds like a scam. Please don't buy anything or give any numbers. "
               f"It's okay to hang up. I've told {FAMILY_CONTACT}.")
        with _state_lock:
            first = not scam_lock_active()
            set_scam_lock(reason)
        if first:
            memory.add_alert("scam", f"Possible scam call ({reason}). Purchases locked for 30 minutes.")
    else:
        say = "Be careful. If anyone asks for money or numbers, let's check with your family first."
    return {"risk": risk, "reason": reason, "say": say}


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


def _charge(item: str, merchant: str, amount_cents: int) -> str:
    """Create + confirm a Stripe test-mode PaymentIntent, or simulate. Returns the id."""
    if not config.STRIPE_SECRET_KEY:
        return "sim_" + uuid.uuid4().hex[:20]
    import stripe
    pi = stripe.PaymentIntent.create(
        api_key=config.STRIPE_SECRET_KEY,
        amount=int(amount_cents), currency="usd",
        payment_method="pm_card_visa", confirm=True,
        automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
        description=f"Kin for {config.WEARER_NAME}: {item} from {merchant}",
        metadata={"item": item[:200], "merchant": merchant, "agent": "kin"},
    )
    if pi.status not in ("succeeded", "processing", "requires_capture"):
        raise RuntimeError(f"payment status {pi.status}")
    return pi.id


def _block(item: str, merchant: str, amount_cents: int, reason: str, say: str) -> dict:
    memory.add_purchase(item, merchant, amount_cents, "blocked", reason)
    memory.add_alert("spending", f"Blocked: {item} from {merchant or '?'} for {_money(amount_cents)} — {reason}")
    return {"status": "blocked", "reason": reason, "say": say, "stripe_id": ""}


def purchase(item: str, merchant: str, amount_cents: int) -> dict:
    """Try to buy `item` from `merchant`. Guardrails are always enforced here, never by the LLM."""
    item = (item or "").strip() or "unspecified item"
    merchant_in = (merchant or "").strip()
    try:
        amount_cents = int(amount_cents)
    except (TypeError, ValueError):
        amount_cents = 0
    who = FAMILY_CONTACT
    limit = config.SPEND_LIMIT_CENTS

    with _state_lock:  # serialize so two threads can't both squeeze under the daily cap
        if scam_lock_active():
            return _block(item, merchant_in, amount_cents, "scam lock active (recent suspicious call)",
                          f"I've paused all purchases for a little while to keep you safe. I'll check with {who}.")
        cat = _blocked_category(item) or _blocked_category(merchant_in)
        if cat:
            return _block(item, merchant_in, amount_cents, f"blocked category: {cat}",
                          f"I can't buy {cat}s — that's a common scam. I've let {who} know."
                          if cat == "gift card" else f"I can't do {cat} payments. I've let {who} know.")
        canon = _norm_merchant(merchant_in)
        if not canon:
            return _block(item, merchant_in, amount_cents, f"merchant not approved: {merchant_in or '(none)'}",
                          f"I can only order from your usual stores, like Walgreens or Safeway. I'll ask {who}.")
        if amount_cents <= 0:
            return _block(item, canon, amount_cents, "invalid amount",
                          "I'm not sure what that costs, so I didn't buy it.")
        if amount_cents > limit:
            return _block(item, canon, amount_cents, f"over per-purchase limit ({_money(amount_cents)} > {_money(limit)})",
                          f"That's more than your family's limit of {_money(limit)}. I've asked {who} to approve it.")
        spent = spent_today_cents()
        cap = limit * DAILY_CAP_MULTIPLIER
        if spent + amount_cents > cap:
            return _block(item, canon, amount_cents,
                          f"over daily cap ({_money(spent)} spent + {_money(amount_cents)} > {_money(cap)})",
                          f"You've done enough shopping for today. I've asked {who} about this one.")
        try:
            sid = _charge(item, canon, amount_cents)
        except Exception as e:
            reason = f"payment failed: {e}"[:300]
            return _block(item, canon, amount_cents, reason,
                          "Sorry, the payment didn't go through. I'll let your family know.")
        memory.add_purchase(item, canon, amount_cents, "allowed", "within guardrails", sid)
    return {"status": "allowed", "reason": "within guardrails",
            "say": f"Done. I ordered your {item} from {canon} for {_money(amount_cents)}.",
            "stripe_id": sid}


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
            "Decide if the user is asking their assistant to buy/order something. If so, extract the item, "
            f"the store (approved stores: {', '.join(APPROVED_MERCHANTS)}; if none named pick the usual one; "
            "keep any other named store verbatim), and the price in US cents (stated, or a realistic estimate). "
            "If not a purchase request, set is_purchase false and the other fields to empty / 0.",
            text, _PARSE_SCHEMA, "purchase_request")
        if r is not None:
            if not r.get("is_purchase"):
                return None
            try:
                return {"item": str(r["item"]).strip() or "item", "merchant": str(r["merchant"]).strip(),
                        "amount_cents": int(r["amount_cents"])}
            except (KeyError, TypeError, ValueError):
                pass
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
