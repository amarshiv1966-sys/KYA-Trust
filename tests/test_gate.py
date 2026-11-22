"""K9: the payment gate, score_session and replay.

Each test runs the real bank on a fresh database and checks two things:
what the gate decided, and what actually happened to the money.
"""

import hashlib
import json
import random

import pytest
from fastapi.testclient import TestClient

from kya.identity.keys import new_private_key, public_key_b64
from kya.identity.signing import sign_request

PAY = "/api/merchant/pay"


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("KYA_DB", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setenv("KYA_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("KYA_KEYS_DIR", str(tmp_path / "keys"))
    from bank.backend.db import connect
    from bank.backend.seed import seed
    from bank.backend.app import app
    seed(connect(), random.Random(7))
    return TestClient(app), tmp_path


def login(client, user="cust_0001"):
    return client.post("/api/login", json={"username": user, "password": "demo1234"}).json()["session_id"]


def behave(sid, n=30):
    """Write n person-like clicks and keys into the session, as telemetry.js would."""
    from bank.backend.ingest import ingest_batch
    events = []
    for i in range(n):
        if i % 3 == 0:
            data = {"target": "transfer.submit", "x": 300 + i, "y": 400, "target_w": 70, "target_h": 37,
                    "offset_x": 12.5 - i % 7, "offset_y": 3.0, "press_ms": 90 + i % 20}
            events.append({"event_id": f"c{i}", "type": "click", "page": "transfer", "data": data})
        else:
            data = {"target": "transfer.amount", "key_class": "digit", "dwell_ms": 80 + i % 30, "flight_ms": 150 + i % 50}
            events.append({"event_id": f"k{i}", "type": "keystroke", "page": "transfer", "data": data})
    for e in events:
        e["client_ts_ms"] = 0
        e["client"] = {"device_id": None, "device_class": "desktop", "os_family": "windows",
                       "browser_family": "chrome", "input_type": "mouse", "webdriver": False,
                       "languages_count": 2, "timezone_offset_min": 330}
    ingest_batch(sid, events)


def db_contents(path):
    """Every row of every table, as text. (Not the file's bytes: SQLite's
    write-ahead log moves data into the file at its own moments.)"""
    import sqlite3
    c = sqlite3.connect(path)
    try:
        return hashlib.sha256("\n".join(c.iterdump()).encode()).hexdigest()
    finally:
        c.close()


def balance(client):
    return client.get("/api/balance").json()["balance_paise"]


def ledger_rows(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "bank.sqlite3")
    # only payments made during the test, not the seeded 90-day history
    return c.execute("SELECT counterparty, amount_paise, mandate_id, nonce FROM ledger "
                     "WHERE session_id IS NOT NULL").fetchall()


# ---------- a person ----------

def test_human_transfer_allowed_and_logged(bank):
    client, tmp = bank
    sid = login(client)
    payee = client.get("/api/payees").json()["payees"][0]["payee_id"]
    behave(sid)
    before = balance(client)
    r = client.post("/api/transfer", json={"payee_id": payee, "amount_paise": 250_000}).json()
    assert r["status"] == "executed", r["decision"]
    assert r["balance_paise"] == before - 250_000
    d = r["decision"]
    assert d["action"] == "allow" and d["agent_class"] == "human" and d["evidence_status"] == "sufficient"

    from bank.backend.ingest import LOG
    log = LOG.read(sid)
    tx = [e for e in log if e["type"] == "transaction"][-1]
    ctx = [e for e in log if e["type"] == "decision_context"][-1]
    assert d["decision_seq"] == tx["seq"] and ctx["data"]["decision_seq"] == tx["seq"]
    assert tx["data"]["amount_paise"] == 250_000 and tx["data"]["payee_id"] == payee
    call = [e for e in log if e["seq"] == tx["data"]["api_call_seq"]][0]
    assert call["type"] == "api_call" and call["data"]["path"] == "/api/transfer"


def test_large_payment_steps_up_and_moves_nothing(bank):
    client, tmp = bank
    sid = login(client)
    payee = client.get("/api/payees").json()["payees"][0]["payee_id"]
    behave(sid)
    before = balance(client)
    r = client.post("/api/transfer", json={"payee_id": payee, "amount_paise": 5_000_000}).json()   # Rs 50,000
    assert r["status"] == "step_up" and r["approval_id"].startswith("ap_")
    assert [c["code"] for c in r["decision"]["reason_codes"]][0] == "R14"
    assert balance(client) == before


def test_api_only_with_little_evidence_steps_up(bank):
    client, _ = bank
    login(client)
    r = client.post(PAY, json={"merchant_id": "mr_grocermart", "amount_paise": 10_000}).json()
    assert r["status"] == "step_up" and r["decision"]["reason_codes"][0]["code"] == "R50"


# ---------- a signed agent ----------

@pytest.fixture
def agent_setup(bank):
    """cust_0001 gives agent_shopper a grocery mandate: Rs 2,000 each, Rs 5,000 total, 3 a day."""
    client, tmp = bank
    key = new_private_key()
    client.post("/api/agents", json={"agent_id": "agent_shopper", "public_key": public_key_b64(key),
                                     "issuer": "Demo Labs"})
    sid = login(client)
    m = client.post("/api/mandates", json={"agent_id": "agent_shopper", "merchant_categories": ["grocery"],
                                           "payees": [], "max_per_txn_paise": 200_000, "max_total_paise": 500_000,
                                           "max_txn_per_day": 3, "expiry_days": 7}).json()
    client.cookies.clear()  # the agent is an API client: session by header, no browser cookie

    def send(amount=120_000, merchant="mr_grocermart", headers=None, body=None, tamper=None):
        b = body or json.dumps({"merchant_id": merchant, "amount_paise": amount, "currency": "INR"}).encode()
        h = headers or sign_request("POST", PAY, b, agent_id="agent_shopper", private_key=key,
                                    mandate_token=m["token"])
        sent = tamper(b) if tamper else b     # tamper: change the body after signing
        r = client.post(PAY, content=sent, headers={**h, "Content-Type": "application/json",
                                                    "X-KYA-Session": sid})
        return r.json(), h, b

    return client, tmp, sid, m, send


def test_agent_inside_mandate_is_allowed(agent_setup):
    client, tmp, sid, m, send = agent_setup
    r, h, _ = send()
    d = r["decision"]
    assert r["status"] == "executed", d
    assert (d["identity_state"], d["mandate_state"], d["agent_class"]) == ("verified", "within", "llm_agent")
    assert "R60" in [c["code"] for c in d["reason_codes"]]
    rows = ledger_rows(tmp)
    assert len(rows) == 1 and rows[0][2] == m["mandate_id"] and rows[0][3]      # mandate and nonce recorded
    client.post("/api/login", json={"username": "cust_0001", "password": "demo1234"})
    listed = client.get("/api/mandates").json()["mandates"][0]
    assert listed["consumed_paise"] == 120_000


def test_replayed_request_is_blocked(agent_setup):
    client, tmp, sid, m, send = agent_setup
    first, h, b = send()
    again, _, _ = send(headers=h, body=b)            # the exact same signed request, sent twice
    assert first["status"] == "executed"
    assert again["status"] == "blocked" and again["decision"]["reason_codes"][0]["code"] == "R02"
    assert again["decision"]["trust_score"] <= 5
    assert len(ledger_rows(tmp)) == 1                 # paid once


def test_edited_body_is_blocked(agent_setup):
    client, tmp, sid, m, send = agent_setup
    # the agent signs Rs 1,200; someone changes it to Rs 1,900 on the way
    r, _, _ = send(amount=120_000, tamper=lambda b: b.replace(b"120000", b"190000"))
    assert r["status"] == "blocked" and r["decision"]["reason_codes"][0]["code"] == "R01"
    assert ledger_rows(tmp) == []


def test_over_the_limit_is_held(agent_setup):
    client, tmp, sid, m, send = agent_setup
    r, _, _ = send(amount=300_000)                    # above Rs 2,000 per payment
    assert r["status"] == "held" and r["decision"]["reason_codes"][0]["code"] == "R11"
    r, _, _ = send(merchant="mr_coinswap")            # crypto is not in the mandate
    assert r["status"] == "held" and r["decision"]["reason_codes"][0]["code"] == "R12"
    assert ledger_rows(tmp) == []


def test_revoked_mandate_is_held(agent_setup):
    client, tmp, sid, m, send = agent_setup
    client.post("/api/mandates/" + m["mandate_id"] + "/revoke", headers={"X-KYA-Session": sid})
    r, _, _ = send()
    assert r["status"] == "held" and r["decision"]["reason_codes"][0]["code"] == "R10"
    assert ledger_rows(tmp) == []


def test_budget_runs_out(agent_setup):
    client, tmp, sid, m, send = agent_setup
    results = [send(amount=200_000)[0]["status"] for _ in range(3)]     # Rs 2,000 x 3 against Rs 5,000
    assert results == ["executed", "executed", "held"]
    assert sum(-r[1] for r in ledger_rows(tmp)) == 400_000


# ---------- failing safe ----------

def test_scoring_error_holds(bank, monkeypatch):
    client, tmp = bank
    import bank.backend.gate as gate

    def broken(*a, **k):
        raise RuntimeError("model file missing")
    monkeypatch.setattr(gate, "score_session", broken)
    sid = login(client)
    behave(sid)
    r = client.post(PAY, json={"merchant_id": "mr_grocermart", "amount_paise": 10_000}).json()
    assert r["status"] == "held" and r["decision"]["reason_codes"][0]["code"] == "ERR"
    assert ledger_rows(tmp) == []


def test_idempotency_key_runs_once(bank):
    client, tmp = bank
    sid = login(client)
    behave(sid)
    body = {"merchant_id": "mr_grocermart", "amount_paise": 10_000}
    a = client.post(PAY, json=body, headers={"Idempotency-Key": "order-42"}).json()
    b = client.post(PAY, json=body, headers={"Idempotency-Key": "order-42"}).json()
    assert a == b and a["status"] == "executed"
    assert len(ledger_rows(tmp)) == 1


# ---------- replay: same answer, bank untouched ----------

def test_replay_gives_the_same_decision_and_changes_nothing(agent_setup):
    client, tmp, sid, m, send = agent_setup
    live, _, _ = send()
    from bank.backend.ingest import LOG
    from kya.score import score_session

    db = tmp / "bank.sqlite3"
    before = db_contents(db)
    replayed = score_session(LOG.read(sid), decision_seq=live["decision"]["decision_seq"])
    after = db_contents(db)

    strip = lambda d: {k: v for k, v in d.items() if k != "latency_ms"}
    assert strip(replayed) == strip(live["decision"])
    assert before == after


def test_score_endpoint_is_read_only_and_rejects_junk(bank):
    client, tmp = bank
    from pathlib import Path
    sample = Path(__file__).resolve().parents[1] / "contracts" / "samples" / "human_transfer.jsonl"
    events = [json.loads(line) for line in open(sample, encoding="utf-8")]
    before = db_contents(tmp / "bank.sqlite3")
    r = client.post("/score", json=events)
    assert r.status_code == 200 and r.json()["action"] in ("allow", "step_up", "hold", "block")
    assert db_contents(tmp / "bank.sqlite3") == before
    assert client.post("/score", json=[{"type": "click"}]).status_code == 422
