"""K8: agent signatures, nonces, the registry and bank-issued mandates.

Done when: a signed request verifies, an edited body fails (R01), and a
reused nonce fails (R02).
"""

import json
import random
from datetime import datetime

import jwt
import pytest
from fastapi.testclient import TestClient

from kya.identity.keys import new_private_key, public_key_b64
from kya.identity.mandates import IST, issue_mandate, ist_day_start_ms, verify_mandate
from kya.identity.signing import content_digest, sign_request, verify_request

NOW_S = 1_790_000_000   # a fixed moment in the past (Sep 2026)
NOW_MS = NOW_S * 1000
PATH = "/api/merchant/pay"


@pytest.fixture
def agent():
    key = new_private_key()
    return {"id": "agent_shopper", "key": key, "pub": public_key_b64(key)}


def body_bytes(amount=120_000):
    return json.dumps({"merchant_id": "mr_grocermart", "amount_paise": amount, "currency": "INR"}).encode()


def check(agent, headers, body, now_ms=NOW_MS, path=PATH):
    return verify_request("POST", path, "", headers,
                          lookup_key=lambda a: agent["pub"] if a == agent["id"] else None,
                          now_ms=now_ms, digest_ok=content_digest(body) == headers.get("Content-Digest"))


def signed(agent, body, **kw):
    return sign_request("POST", PATH, body, agent_id=agent["id"], private_key=agent["key"],
                        mandate_id=kw.pop("mandate_id", "md_000000000001"), created_s=NOW_S, **kw)


# ---------- signatures ----------

def test_signed_request_verifies(agent):
    b = body_bytes()
    r = check(agent, signed(agent, b), b)
    assert r.state == "verified" and r.agent_id == "agent_shopper" and r.nonce
    assert r.mandate_id == "md_000000000001"


def test_edited_body_is_r01(agent):
    h = signed(agent, body_bytes(120_000))
    r = check(agent, h, body_bytes(990_000))  # someone raised the amount after signing
    assert r.state == "invalid" and r.codes == ["R01"]


def test_edited_mandate_or_path_is_r01(agent):
    b = body_bytes()
    h = signed(agent, b)
    assert check(agent, {**h, "KYA-Mandate-Id": "md_someoneelse"}, b).state == "invalid"
    assert check(agent, h, b, path="/api/transfer").state == "invalid"


def test_other_key_is_r01(agent):
    b = body_bytes()
    thief = {**agent, "key": new_private_key()}  # claims to be agent_shopper, signs with its own key
    assert check(agent, signed(thief, b), b).codes == ["R01"]


def test_old_signature_is_r01(agent):
    b = body_bytes()
    assert check(agent, signed(agent, b), b, now_ms=NOW_MS + 301_000).state == "invalid"
    assert check(agent, signed(agent, b), b, now_ms=NOW_MS + 299_000).state == "verified"


def test_unknown_agent_is_r41(agent):
    b = body_bytes()
    stranger = {"id": "agent_nobody", "key": new_private_key(), "pub": None}
    h = sign_request("POST", PATH, b, agent_id="agent_nobody", private_key=stranger["key"], created_s=NOW_S)
    r = check(agent, h, b)
    assert r.state == "unknown_agent" and r.codes == ["R41"]


def test_no_signature_is_undeclared(agent):
    assert check(agent, {}, body_bytes()).state == "undeclared"


def test_same_answer_on_replay(agent):
    # judged at the arrival time from the log, the answer never changes later
    b = body_bytes()
    h = signed(agent, b)
    assert [check(agent, h, b).state for _ in range(3)] == ["verified"] * 3


# ---------- nonces and the registry (on a real database) ----------

@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("KYA_DB", str(tmp_path / "bank.sqlite3"))
    from bank.backend.db import connect, init_db
    c = connect()
    init_db(c)
    return c


def test_reused_nonce_is_r02(conn, agent):
    from kya.identity.nonces import consume_nonce
    b = body_bytes()
    first = check(agent, signed(agent, b, nonce="n-123"), b)
    again = check(agent, signed(agent, b, nonce="n-123"), b)
    assert first.state == again.state == "verified"          # both signatures are valid...
    assert consume_nonce(conn, agent["id"], first.nonce, NOW_MS) is True
    assert consume_nonce(conn, agent["id"], again.nonce, NOW_MS) is False   # ...the second is a replay (R02)
    assert consume_nonce(conn, "agent_other", "n-123", NOW_MS) is True      # nonces are per agent


def test_registry_refuses_key_takeover(conn, agent):
    from kya.identity.registry import RegistryError, get_agent, register_agent
    register_agent(conn, agent["id"], agent["pub"], "Demo Labs")
    register_agent(conn, agent["id"], agent["pub"], "Demo Labs")  # same key again: fine
    with pytest.raises(RegistryError):
        register_agent(conn, agent["id"], public_key_b64(new_private_key()), "Attacker")
    assert get_agent(conn, agent["id"])["public_key"] == agent["pub"]


# ---------- mandates ----------

@pytest.fixture
def issuer():
    key = new_private_key()
    return {"key": key, "pub": public_key_b64(key)}


def mandate(issuer, **over):
    args = dict(user_id="cust_0001", account_id="ac_0001", agent_id="agent_shopper",
                actions=["merchant_payment"], merchant_categories=["grocery"], payees=[],
                max_per_txn_paise=200_000, max_total_paise=500_000, max_txn_per_day=3,
                expires_in_s=86_400, issuer_key=issuer["key"], now_s=NOW_S)
    args.update(over)
    return issue_mandate(**args)[1]


def pay(**over):
    req = dict(agent_id="agent_shopper", account_id="ac_0001", action="merchant_payment",
               payee_id="mr_grocermart", merchant_category="grocery", amount_paise=120_000, currency="INR")
    req.update(over)
    return req


FRESH = {"revoked": False, "consumed_paise": 0, "payments_today": 0}


def verdict(issuer, token, request=None, usage=FRESH, now_ms=NOW_MS):
    return verify_mandate(token, issuer["pub"], request=request or pay(), usage=usage, now_ms=now_ms)


def test_mandate_within(issuer):
    r = verdict(issuer, mandate(issuer))
    assert r.state == "within" and r.codes == []


def test_mandate_limits(issuer):
    t = mandate(issuer)
    assert verdict(issuer, t, pay(amount_paise=250_000)).codes == ["R11"]                      # per payment
    assert verdict(issuer, t, usage={**FRESH, "consumed_paise": 400_000}).codes == ["R11"]     # total
    assert verdict(issuer, t, usage={**FRESH, "payments_today": 3}).codes == ["R13"]           # per day
    assert verdict(issuer, t, pay(merchant_category="crypto", payee_id="mr_coinswap")).codes == ["R12"]
    assert verdict(issuer, t, pay(action="transfer")).codes == ["R12"]


def test_mandate_payee_list(issuer):
    t = mandate(issuer, payees=["mr_grocermart"])
    assert verdict(issuer, t).state == "within"
    assert verdict(issuer, t, pay(payee_id="mr_quickbite")).codes == ["R12"]


def test_mandate_expired_and_revoked(issuer):
    t = mandate(issuer)
    assert verdict(issuer, t, now_ms=NOW_MS + 86_400_000).state == "expired"
    r = verdict(issuer, t, usage={**FRESH, "revoked": True})
    assert r.state == "expired" and r.codes == ["R10"]


def test_mandate_forged_or_edited(issuer):
    t = mandate(issuer)
    other_bank = {"key": new_private_key(), "pub": None}
    assert verdict(issuer, mandate(other_bank)).state == "unverifiable"         # not signed by our bank
    claims = jwt.decode(t, options={"verify_signature": False})
    widened = jwt.encode({**claims, "max_total_paise": 10**9}, "x" * 32, algorithm="HS256")
    assert verdict(issuer, widened).state == "unverifiable"                      # wrong algorithm
    head, payload, sig = t.split(".")
    assert verdict(issuer, f"{head}.{payload}x.{sig}").state == "unverifiable"   # tampered
    assert verdict(issuer, "not-a-token").state == "unverifiable"


def test_mandate_bound_to_agent_and_account(issuer):
    t = mandate(issuer)
    assert verdict(issuer, t, pay(agent_id="agent_other")).state == "unverifiable"
    assert verdict(issuer, t, pay(account_id="ac_0002")).state == "unverifiable"


def test_no_mandate():
    assert verify_mandate(None, "x", request=pay(), usage=FRESH, now_ms=NOW_MS).state == "none"


def test_day_boundary_is_midnight_ist():
    t = datetime(2026, 11, 24, 0, 30, tzinfo=IST)          # 00:30 IST = 19:00 UTC the day before
    start = ist_day_start_ms(int(t.timestamp() * 1000))
    assert datetime.fromtimestamp(start / 1000, IST) == datetime(2026, 11, 24, 0, 0, tzinfo=IST)


# ---------- the bank endpoints ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KYA_DB", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setenv("KYA_KEYS_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("KYA_RAW_DIR", str(tmp_path / "raw"))
    from bank.backend.db import connect
    from bank.backend.seed import seed
    from bank.backend.app import app
    seed(connect(), random.Random(7))
    return TestClient(app)


def test_issue_list_revoke_via_bank(client, agent):
    assert client.post("/api/agents", json={"agent_id": agent["id"], "public_key": agent["pub"],
                                            "issuer": "Demo Labs"}).status_code == 201
    client.post("/api/login", json={"username": "cust_0001", "password": "demo1234"})
    r = client.post("/api/mandates", json={"agent_id": agent["id"], "merchant_categories": ["grocery"],
                                           "payees": [], "max_per_txn_paise": 200_000, "max_total_paise": 500_000,
                                           "max_txn_per_day": 3, "expiry_days": 7})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["actions"] == ["merchant_payment"]

    issuer_pub = client.get("/api/issuer-key").json()["public_key"]
    account = jwt.decode(m["token"], options={"verify_signature": False})["account_id"]
    now = jwt.decode(m["token"], options={"verify_signature": False})["iat"] * 1000
    ok = verify_mandate(m["token"], issuer_pub, request=pay(account_id=account), usage=FRESH, now_ms=now)
    assert ok.state == "within"

    listed = client.get("/api/mandates").json()["mandates"]
    assert [x["status"] for x in listed] == ["active"]
    assert client.post(f"/api/mandates/{m['mandate_id']}/revoke").status_code == 200
    assert client.get("/api/mandates").json()["mandates"][0]["status"] == "revoked"


def test_mandate_needs_login_and_a_scope(client, agent):
    client.post("/api/agents", json={"agent_id": agent["id"], "public_key": agent["pub"], "issuer": "Demo Labs"})
    body = {"agent_id": agent["id"], "merchant_categories": [], "payees": [], "max_per_txn_paise": 100,
            "max_total_paise": 100, "max_txn_per_day": 1, "expiry_days": 1}
    assert client.post("/api/mandates", json=body).status_code == 401
    client.post("/api/login", json={"username": "cust_0001", "password": "demo1234"})
    assert client.post("/api/mandates", json=body).status_code == 422          # no scope: refused
    assert client.post("/api/mandates", json={**body, "merchant_categories": ["grocery"],
                                              "max_per_txn_paise": 200}).status_code == 422  # per > total


def test_api_call_records_digest_check(client, agent):
    sid = client.post("/api/login", json={"username": "cust_0001", "password": "demo1234"}).json()["session_id"]
    b = body_bytes()
    h = sign_request("POST", PATH, b, agent_id=agent["id"], private_key=agent["key"])
    client.post(PATH, content=b, headers={**h, "Content-Type": "application/json"})
    client.post(PATH, content=body_bytes(5), headers={**h, "Content-Type": "application/json"})
    from bank.backend.ingest import LOG
    calls = [e for e in LOG.read(sid) if e["type"] == "api_call" and e["data"]["path"] == PATH]
    assert [c["data"]["content_digest_ok"] for c in calls] == [True, False]
    assert calls[0]["data"]["headers"]["signature"]          # raw headers kept for replay


def test_mandate_token_is_signed(agent, issuer):
    b = body_bytes()
    token = mandate(issuer)
    h = sign_request("POST", PATH, b, agent_id=agent["id"], private_key=agent["key"],
                     mandate_token=token, created_s=NOW_S)
    r = check(agent, h, b)
    assert r.state == "verified" and r.mandate_token == token
    assert r.mandate_id == jwt.decode(token, options={"verify_signature": False})["mandate_id"]
    bigger = mandate(issuer, max_total_paise=900_000)            # a different, larger mandate
    assert check(agent, {**h, "KYA-Mandate": bigger}, b).state == "invalid"
