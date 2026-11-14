"""Run: .venv/bin/python -m pytest -q tests/test_safety.py"""
import os
import sys
from pathlib import Path

os.environ["KIN_DB"] = "/tmp/kin_safety_test.db"
if os.path.exists(os.environ["KIN_DB"]):
    os.remove(os.environ["KIN_DB"])
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from kin import config, memory, safety  # noqa: E402

REAL_STRIPE = config.STRIPE_SECRET_KEY
REAL_OPENAI = config.OPENAI_API_KEY


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    """Every test: no keys, empty purchases/alerts, no scam lock."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(config, "SPEND_LIMIT_CENTS", 5000)
    monkeypatch.setattr(safety, "FAMILY_CONTACT", "")
    memory._exec("DELETE FROM purchases")
    memory._exec("DELETE FROM alerts")
    memory._exec("DELETE FROM people")
    safety.reset()
    yield
    safety.reset()


def L(text, name=""):
    return {"speaker": "S1" if not name else "S0", "name": name, "text": text}


SCAM_CALL = [
    L("Hi Grandpa, it's me, your grandson. I'm in jail and I need help."),
    L("I need you to pay my bail right now. Please go buy gift cards, $500 worth."),
    L("And don't tell anyone, especially not Mom. Read me the numbers on the back."),
]


# ---------------- scam detection
def test_grandson_bail_gift_card_is_high_risk_and_locks_purchases():
    r = safety.check_scam(SCAM_CALL)
    assert r and r["risk"] == "high"
    assert "scam" in r["say"].lower()
    a = memory.alerts()
    assert len(a) == 1 and a[0]["kind"] == "scam"
    assert safety.scam_lock_active() and safety.scam_lock_remaining() > 29 * 60
    p = safety.purchase("blood pressure pills", "Walgreens", 1299)
    assert p["status"] == "blocked" and "scam lock" in p["reason"]
    assert memory.purchases()[0]["status"] == "blocked"
    # re-check during the lock doesn't spam alerts
    safety.check_scam(SCAM_CALL)
    assert len([x for x in memory.alerts() if x["kind"] == "scam"]) == 1
    safety.clear_scam_lock()
    assert safety.purchase("blood pressure pills", "Walgreens", 1299)["status"] == "allowed"


@pytest.mark.parametrize("lines", [
    [L("This is Officer Brown from the IRS. You owe back taxes and there is a warrant."),
     L("You must pay today with a wire transfer or you'll be arrested.")],
    [L("Hello, I'm calling from Medicare. To send your new card I need your Social Security number.")],
    [L("Your computer has a virus. This is Microsoft tech support. Buy bitcoin at the ATM right away.")],
    [L("Can you read me your card number and the security code on the back? It's urgent.")],
])
def test_other_classic_scams_are_high(lines):
    r = safety.check_scam(lines)
    assert r and r["risk"] == "high", r


def test_normal_family_chat_is_none():
    lines = [
        L("Hi Dad, how was your walk this morning?", "Sarah"),
        L("Don't forget we're having lunch with Tommy on Sunday.", "Sarah"),
        L("I'll pick up your prescription at Walgreens tomorrow.", "Sarah"),
        L("It was lovely, the roses are blooming.", config.WEARER_NAME),
        L("The weather is nice today, isn't it?"),
    ]
    assert safety.check_scam(lines) is None
    assert memory.alerts() == []
    assert not safety.scam_lock_active()


def test_wearer_talking_about_gift_cards_is_fine():
    assert safety.check_scam([L("I bought Tommy a gift card for his birthday, right away!", config.WEARER_NAME)]) is None


def test_known_family_lowers_risk_but_money_urgency_still_flags():
    calm = [L("Dad, can you send me twenty dollars for the pizza? No rush.", "Sarah")]
    assert safety.check_scam(calm) is None
    urgent = [L("Grandpa I need you to send money right now, wire it, it's an emergency.", "Tommy")]
    r = safety.check_scam(urgent)
    assert r and r["risk"] == "medium"
    assert not safety.scam_lock_active()
    # same words from an unknown voice -> high
    assert safety.check_scam([L(urgent[0]["text"])])["risk"] == "high"


def test_medium_does_not_lock():
    r = safety.check_scam([L("Have you heard about crypto?")])
    assert r and r["risk"] == "medium"
    assert not safety.scam_lock_active() and memory.alerts() == []


def test_empty_and_junk_input():
    assert safety.check_scam([]) is None
    assert safety.check_scam([{"text": ""}, {}, "bad"]) is None


def test_llm_can_confirm_or_downgrade(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-fake")
    monkeypatch.setattr(safety, "_llm_json", lambda *a, **k: {"risk": "high", "reason": "LLM: bail scam"})
    assert safety.check_scam([L("Have you heard about crypto?")])["reason"] == "LLM: bail scam"
    safety.reset()
    monkeypatch.setattr(safety, "_llm_json", lambda *a, **k: {"risk": "none", "reason": "fine"})
    assert safety.check_scam([L("Have you heard about crypto?")]) is None
    # but an unknown caller with money + pressure can't be fully cleared
    assert safety.check_scam(SCAM_CALL)["risk"] == "medium"
    # LLM failure -> heuristic
    monkeypatch.setattr(safety, "_llm_json", lambda *a, **k: None)
    assert safety.check_scam(SCAM_CALL)["risk"] == "high"


# ---------------- purchases
def test_small_pharmacy_purchase_allowed_simulated():
    r = safety.purchase("blood pressure pills", "Walgreens", 1299)
    assert r["status"] == "allowed" and r["stripe_id"].startswith("sim_")
    assert "Walgreens" in r["say"] and "$12.99" in r["say"]
    p = memory.purchases()[0]
    assert (p["status"], p["amount_cents"], p["stripe_id"]) == ("allowed", 1299, r["stripe_id"])
    assert memory.alerts() == []


def test_merchant_aliases():
    assert safety.purchase("vitamins", "cvs pharmacy", 999)["status"] == "allowed"
    assert safety.purchase("coffee", "whole foods market", 999)["status"] == "allowed"


def test_over_limit_blocked():
    r = safety.purchase("electric scooter", "Amazon Pharmacy", 50001)
    assert r["status"] == "blocked" and "limit" in r["reason"]
    assert memory.alerts()[0]["kind"] == "spending"
    assert memory.purchases()[0]["status"] == "blocked"


def test_unknown_merchant_blocked():
    r = safety.purchase("vitamins", "TotallyLegitPharma.ru", 999)
    assert r["status"] == "blocked" and "merchant" in r["reason"]
    assert memory.alerts()[0]["kind"] == "spending"


@pytest.mark.parametrize("item", ["Apple gift card", "Google Play cards", "bitcoin", "wire transfer to Tommy",
                                  "Western Union money order"])
def test_blocked_categories(item):
    r = safety.purchase(item, "CVS", 2500)
    assert r["status"] == "blocked" and "category" in r["reason"]


def test_daily_cap():
    for _ in range(3):
        assert safety.purchase("groceries", "Safeway", 4900)["status"] == "allowed"   # 147.00 of 150.00
    r = safety.purchase("milk", "Safeway", 449)
    assert r["status"] == "blocked" and "daily cap" in r["reason"]
    assert safety.purchase("bananas", "Safeway", 300)["status"] == "allowed"           # exactly 150.00
    assert safety.spent_today_cents() == 15000


def test_invalid_amount_blocked():
    assert safety.purchase("milk", "Safeway", 0)["status"] == "blocked"
    assert safety.purchase("milk", "Safeway", "abc")["status"] == "blocked"


def test_stripe_failure_is_blocked(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_bogus")
    def boom(*a, **k):
        raise RuntimeError("card declined")
    monkeypatch.setattr(safety, "_charge", boom)
    r = safety.purchase("milk", "Safeway", 449)
    assert r["status"] == "blocked" and "payment failed" in r["reason"]


def test_concurrent_purchases_respect_cap():
    import threading
    out = []
    ts = [threading.Thread(target=lambda: out.append(safety.purchase("groceries", "Safeway", 4000)))
          for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(r["status"] == "allowed" for r in out) == 3
    assert safety.spent_today_cents() == 12000


# ---------------- parsing + tools
def test_parse_purchase_request_heuristic():
    r = safety.parse_purchase_request("Kin, reorder my blood pressure pills from Walgreens")
    assert r == {"item": "blood pressure pills", "merchant": "Walgreens", "amount_cents": 1299}
    r = safety.parse_purchase_request("We're out of milk, can you order some?")
    assert r["item"] == "milk" and r["merchant"] == "Safeway"
    r = safety.parse_purchase_request("Buy me a $25 gift card")
    assert r["amount_cents"] == 2500 and "gift card" in r["item"]
    assert safety.purchase(**r)["status"] == "blocked"
    r = safety.parse_purchase_request("Order hearing aid batteries from CVS")
    assert r["item"] == "hearing aid batteries" and r["merchant"] == "CVS"
    assert safety.parse_purchase_request("Where did I put my glasses?") is None
    assert safety.parse_purchase_request("Sarah is coming on Sunday") is None
    assert safety.parse_purchase_request("") is None


def test_parse_end_to_end_allowed():
    r = safety.parse_purchase_request("Kin, reorder my blood pressure pills from Walgreens")
    assert safety.purchase(**r)["status"] == "allowed"


def test_parse_uses_llm_when_available(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-fake")
    monkeypatch.setattr(safety, "_llm_json", lambda *a, **k: {
        "is_purchase": True, "item": "lisinopril 10mg", "merchant": "CVS", "amount_cents": 1100})
    assert safety.parse_purchase_request("refill my lisinopril")["item"] == "lisinopril 10mg"
    monkeypatch.setattr(safety, "_llm_json", lambda *a, **k: {
        "is_purchase": False, "item": "", "merchant": "", "amount_cents": 0})
    assert safety.parse_purchase_request("Buy milk") is None
    monkeypatch.setattr(safety, "_llm_json", lambda *a, **k: None)        # LLM down -> heuristic
    assert safety.parse_purchase_request("Buy milk")["item"] == "milk"


def test_tool_schemas_and_dispatch():
    s = safety.tool_schemas()
    assert s[0]["type"] == "function" and s[0]["function"]["name"] == "purchase"
    assert set(s[0]["function"]["parameters"]["required"]) == {"item", "merchant", "amount_cents"}
    r = safety.handle_tool_call("purchase", '{"item":"vitamins","merchant":"CVS","amount_cents":999}')
    assert r["status"] == "allowed"
    assert "error" in safety.handle_tool_call("nope", "{}")


# ---------------- spoken lines: warm, short, never frightening, name a child if known
import re  # noqa: E402

SCARY = re.compile(r"\b(?:danger|dangerous|criminal|fraud|police|arrest|stolen|steal|emergency|warning|alert|"
                   r"urgent|immediately|threat|attack|hacked)\b", re.I)


def sentences(t):
    return [x for x in re.split(r"(?<=[.!?])\s+", t.strip()) if x]


def gentle(say):
    assert say and len(sentences(say)) <= 2, say
    assert not SCARY.search(say), say
    return True


def test_family_contact_prefers_daughter_or_son_over_grandchild():
    assert safety.family_contact() == "your family"
    memory.upsert_person("Bob", "friend")
    memory.upsert_person("Tommy", "grandson")            # "grandson" must NOT count as son
    assert safety.family_contact() == "your family"
    memory.upsert_person("Sarah", "daughter")
    assert safety.family_contact() == "Sarah"
    memory.upsert_person("Tommy", "grandson")            # seen more recently, still not chosen
    assert safety.family_contact() == "Sarah"


def test_family_contact_env_override(monkeypatch):
    memory.upsert_person("Sarah", "daughter")
    monkeypatch.setattr(safety, "FAMILY_CONTACT", "Mike")
    assert safety.family_contact() == "Mike"


def test_say_lines_are_gentle_and_name_family():
    memory.upsert_person("Sarah", "daughter")
    hi = safety.check_scam(SCAM_CALL)
    assert hi["risk"] == "high" and gentle(hi["say"]) and "Sarah" in hi["say"] and "hang up" in hi["say"]
    safety.reset()
    med = safety.check_scam([L("Have you heard about crypto?")])
    assert med["risk"] == "medium" and gentle(med["say"]) and "Sarah" in med["say"]
    blocked = [
        safety.purchase("Apple gift card", "CVS", 2500),
        safety.purchase("bitcoin", "CVS", 2500),
        safety.purchase("vitamins", "TotallyLegitPharma.ru", 999),
        safety.purchase("scooter", "Amazon Pharmacy", 50001),
        safety.purchase("milk", "Safeway", 0),
    ]
    for r in blocked:
        assert r["status"] == "blocked" and gentle(r["say"]), r
    assert all("Sarah" in r["say"] for r in blocked[:4])
    assert gentle(safety.purchase("milk", "Safeway", 449)["say"])


@pytest.mark.parametrize("env", ["", "   ", ".", " . "])
def test_blank_family_contact_falls_back_to_your_family(monkeypatch, env):
    monkeypatch.setattr(safety, "FAMILY_CONTACT", env)
    assert safety.family_contact() == "your family"
    say = safety.check_scam(SCAM_CALL)["say"]
    assert say.endswith("I've let your family know.") and not re.search(r"\s[.,]|\s{2}|\.\.|let\s+know", say), say


@pytest.mark.parametrize("rel", ["daughter", "Daughter", "child", "son", "my daughter", "daughter-in-law"])
def test_child_relationships_are_picked(rel):
    memory.upsert_person("Sarah. ", rel)
    assert safety.family_contact() == "Sarah"
    say = safety.check_scam(SCAM_CALL)["say"]
    assert say.endswith("I've let Sarah know.") and "  " not in say and " ." not in say


def test_blank_named_child_is_skipped():
    memory._exec("INSERT INTO people(name,relationship,last_seen,created) VALUES(' ', 'daughter', 9e9, 0)")
    assert safety.family_contact() == "your family"


# ---------------- the demo line, end to end
DEMO = "Kin, reorder my blood pressure pills from Walgreens"


def test_demo_reorder_end_to_end():
    memory.upsert_person("Sarah", "daughter")
    req = safety.parse_purchase_request(DEMO)
    assert req == {"item": "blood pressure pills", "merchant": "Walgreens", "amount_cents": 1299}
    r = safety.purchase(**req)
    assert r["status"] == "allowed" and r["say"] == "Done. I ordered your blood pressure pills from Walgreens for $12.99."
    assert gentle(r["say"])


def test_demo_reorder_with_llm_keeps_name_and_price(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-fake")
    monkeypatch.setattr(safety, "_llm_json", lambda *a, **k: {
        "is_purchase": True, "item": "Blood pressure pills (prescription refill)", "merchant": "Walgreens",
        "amount_cents": 2000})
    assert safety.parse_purchase_request(DEMO) == {
        "item": "blood pressure pills", "merchant": "Walgreens", "amount_cents": 1299}


def test_demo_reorder_refused_gently_during_scam_lock():
    memory.upsert_person("Sarah", "daughter")
    assert safety.check_scam(SCAM_CALL)["risk"] == "high"
    r = safety.purchase(**safety.parse_purchase_request(DEMO))
    assert r["status"] == "blocked" and "scam lock" in r["reason"]
    assert gentle(r["say"]) and "Sarah" in r["say"] and "blood pressure pills" in r["say"]
    assert "30 minutes" in r["say"] or "minutes" in r["say"]
    # tool path (voice agent) refuses the same way
    t = safety.handle_tool_call("purchase", {"item": "blood pressure pills", "merchant": "Walgreens",
                                             "amount_cents": 1299})
    assert t["status"] == "blocked" and t["say"] == r["say"]
    safety.clear_scam_lock()
    assert safety.purchase(**safety.parse_purchase_request(DEMO))["status"] == "allowed"


# ---------------- Stripe call shape (stubbed client, no network)
class _FakePI:
    def __init__(self, status="succeeded"):
        self.id, self.status = "pi_fake123", status


class _FakeClient:
    def __init__(self, status="succeeded"):
        self.calls = []
        outer = self

        class _PIs:
            def create(self, params, options=None):
                outer.calls.append((params, options))
                return _FakePI(status)

        class _V1:
            payment_intents = _PIs()

        self.v1 = _V1()


def test_charge_uses_stripe_client_v1_with_idempotency_and_metadata(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(safety, "_stripe_client", lambda: fake)
    r = safety.purchase("blood pressure pills", "Walgreens", 1299)
    assert r["status"] == "allowed" and r["stripe_id"] == "pi_fake123"
    (params, options), = fake.calls
    assert params["amount"] == 1299 and params["currency"] == "usd" and params["confirm"] is True
    assert params["payment_method"] == "pm_card_visa"
    assert params["automatic_payment_methods"] == {"enabled": True, "allow_redirects": "never"}
    assert params["description"] == f"Kin for {config.WEARER_NAME}: blood pressure pills from Walgreens ($12.99)"
    md = params["metadata"]
    assert md["agent"] == "kin" and md["merchant"] == "Walgreens" and md["item"] == "blood pressure pills"
    assert all(isinstance(v, str) and len(v) <= 500 for v in md.values()) and len(md) <= 50
    assert options["idempotency_key"].startswith("kin-") and md["idempotency_key"] == options["idempotency_key"]
    safety.purchase("vitamins", "CVS", 999)
    assert fake.calls[1][1]["idempotency_key"] != options["idempotency_key"]   # one key per purchase
    assert memory.purchases()[1]["stripe_id"] == "pi_fake123"


def test_live_mode_key_is_refused(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_live_nope")
    monkeypatch.setattr(safety, "_stripe_client", lambda: pytest.fail("must not call Stripe with a live key"))
    r = safety.purchase("milk", "Safeway", 449)
    assert r["status"] == "blocked" and "test mode" in r["reason"]


def test_unsuccessful_payment_status_blocks(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(safety, "_stripe_client", lambda: _FakeClient("requires_payment_method"))
    r = safety.purchase("milk", "Safeway", 449)
    assert r["status"] == "blocked" and "requires_payment_method" in r["reason"] and gentle(r["say"])


# ---------------- dashboard summary
def test_purchase_summary():
    s0 = safety.purchase_summary()
    assert s0["spent_today_cents"] == 0 and s0["daily_cap_cents"] == 15000 and s0["last"] == []
    assert s0["stripe_mode"] == "simulated" and not s0["scam_lock_active"]
    safety.purchase("blood pressure pills", "Walgreens", 1299)
    safety.purchase("Apple gift card", "CVS", 2500)
    s = safety.purchase_summary()
    assert s["spent_today_cents"] == 1299 and s["spent_today"] == "$12.99"
    assert s["remaining_today_cents"] == 15000 - 1299 and s["pct_of_cap"] == 9
    assert s["blocked_today"] == 1 and s["per_purchase_limit"] == "$50.00"
    assert [x["status"] for x in s["last"]] == ["blocked", "allowed"]
    assert s["last"][1]["amount"] == "$12.99" and s["last"][1]["live"] is False
    safety.check_scam(SCAM_CALL)
    s = safety.purchase_summary()
    assert s["scam_lock_active"] and s["scam_lock_remaining_s"] > 29 * 60 and s["scam_lock_reason"]
    import json
    json.dumps(s)   # dashboard-serialisable


# ---------------- live OpenAI (only with a real OPENAI_API_KEY in .env)
needs_openai = pytest.mark.skipif(not REAL_OPENAI, reason="no OPENAI_API_KEY in .env")


@needs_openai
def test_live_llm_scam_and_parse(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", REAL_OPENAI)
    assert safety.check_scam(SCAM_CALL)["risk"] == "high"
    safety.reset()
    assert safety.check_scam([L("Your refill is ready, the copay is five dollars when you pick it up.")]) is None
    assert safety.parse_purchase_request(DEMO) == {
        "item": "blood pressure pills", "merchant": "Walgreens", "amount_cents": 1299}
    assert safety.parse_purchase_request("Where did I leave my glasses?") is None


# ---------------- live Stripe test mode (runs automatically once an sk_test_ key is in .env)
@pytest.mark.skipif(not REAL_STRIPE.startswith("sk_test_"), reason="no STRIPE_SECRET_KEY sk_test_ in .env")
def test_live_stripe_test_payment(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", REAL_STRIPE)
    r = safety.purchase(**safety.parse_purchase_request(DEMO))
    assert r["status"] == "allowed", r
    assert r["stripe_id"].startswith("pi_")
    pi = safety._stripe_client().v1.payment_intents.retrieve(r["stripe_id"])
    assert pi.status == "succeeded" and pi.amount == 1299 and pi.currency == "usd" and not pi.livemode
    assert pi.metadata["merchant"] == "Walgreens" and pi.metadata["agent"] == "kin"
    assert "blood pressure pills from Walgreens" in pi.description
    assert safety.purchase_summary()["last"][0]["live"] is True
    # same idempotency key -> Stripe returns the same PaymentIntent, never a second charge
    key = f"kin-test-{r['stripe_id']}"
    a = safety._charge("milk", "Safeway", 449, key)
    b = safety._charge("milk", "Safeway", 449, key)
    assert a == b and a.startswith("pi_")
    # guardrails hold with real Stripe too
    assert safety.purchase("Apple gift card", "CVS", 2500)["status"] == "blocked"
