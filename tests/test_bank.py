"""K4: the bank skeleton works end to end on a fresh database."""

import random

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    # These tests check the bank's mechanics, not the decision: every
    # payment scores as low risk so the gate lets it through.
    from kya.fusion import fake
    monkeypatch.setattr(fake, "predict", lambda features, identity_state="undeclared": {
        "class_probs": {"human": 1.0, "scripted_bot": 0.0, "llm_agent": 0.0}, "p_fraud": 0.0,
        "contribs": {"actor": {}, "risk": {}}})
    monkeypatch.setenv("KYA_DB", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setenv("KYA_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("KYA_KEYS_DIR", str(tmp_path / "keys"))
    from bank.backend.db import connect
    from bank.backend.seed import seed
    from bank.backend.app import app
    seed(connect(), random.Random(7))
    return TestClient(app)


def login(client, user="cust_0001"):
    r = client.post("/api/login", json={"username": user, "password": "demo1234"})
    assert r.status_code == 200
    return r.json()["session_id"]


def test_login_and_balance(client):
    assert client.get("/api/balance").status_code == 401
    login(client)
    r = client.get("/api/balance")
    assert r.status_code == 200
    assert isinstance(r.json()["balance_paise"], int)


def test_wrong_password(client):
    r = client.post("/api/login", json={"username": "cust_0001", "password": "nope"})
    assert r.status_code == 401


def test_header_session(client):
    sid = login(client)
    client.cookies.clear()
    assert client.get("/api/balance").status_code == 401
    assert client.get("/api/balance", headers={"X-KYA-Session": sid}).status_code == 200


def test_add_payee_then_transfer(client):
    login(client)
    before = client.get("/api/balance").json()["balance_paise"]
    r = client.post("/api/payees", json={"name": "New Friend", "account_number": "123456789012",
                                         "ifsc": "KYAB0001234"})
    assert r.status_code == 202 and r.json()["status"] == "executed"
    payee_id = r.json()["payee_id"]

    r = client.post("/api/transfer", json={"payee_id": payee_id, "amount_paise": 250000})
    assert r.status_code == 202 and r.json()["status"] == "executed"
    assert r.json()["balance_paise"] == before - 250000

    rows = client.get("/api/statements").json()["rows"]
    assert rows[0]["amount_paise"] == -250000


def test_merchant_payment_records_category(client):
    login(client)
    client.get("/api/balance")  # with only login + pay, the gate asks for a step-up (R50: too little evidence)
    r = client.post("/api/merchant/pay", json={"merchant_id": "mr_kyashop", "amount_paise": 149900})
    assert r.status_code == 202
    assert client.get("/api/statements").json()["rows"][0]["category"] == "electronics"


def test_bad_amounts_rejected(client):
    login(client)
    payee_id = client.get("/api/payees").json()["payees"][0]["payee_id"]
    for bad in [2500.0, "2500", -100, 0]:
        r = client.post("/api/transfer", json={"payee_id": payee_id, "amount_paise": bad})
        assert r.status_code == 422, bad
    r = client.post("/api/transfer", json={"payee_id": payee_id, "amount_paise": 10**12})
    assert r.status_code == 400  # more than the balance


def test_cannot_pay_someone_elses_payee(client):
    login(client, "cust_0002")
    other = client.get("/api/payees").json()["payees"][0]["payee_id"]
    client.post("/api/logout")
    login(client, "cust_0001")
    r = client.post("/api/transfer", json={"payee_id": other, "amount_paise": 100})
    assert r.status_code == 404


def test_statement_download_is_csv(client):
    login(client)
    r = client.get("/api/statements/download?range=30")
    assert r.status_code == 200
    assert r.text.startswith("txn_id,")
