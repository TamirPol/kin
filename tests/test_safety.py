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
    memory._exec("DELETE FROM purchases")
    memory._exec("DELETE FROM alerts")
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


# ---------------- live Stripe test mode (only with a real sk_test_ key in .env)
@pytest.mark.skipif(not REAL_STRIPE.startswith("sk_test_"), reason="no STRIPE_SECRET_KEY sk_test_ in .env")
def test_live_stripe_test_payment(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", REAL_STRIPE)
    r = safety.purchase("blood pressure pills", "Walgreens", 1299)
    assert r["status"] == "allowed", r
    assert r["stripe_id"].startswith("pi_")
    import stripe
    pi = stripe.PaymentIntent.retrieve(r["stripe_id"], api_key=REAL_STRIPE)
    assert pi.status == "succeeded" and pi.metadata["merchant"] == "Walgreens"
