"""A signed agent, end to end (K8). Also the template for Prachi's signed bots (P6).

Steps:
  1. the customer gives agent_shopper a mandate (here through the API, as a
     shortcut; normally on the Assistants page)
  2. the agent signs a merchant payment with its own key and attaches the mandate
  3. we read the session log and re-check the signature AND the mandate from
     the logged headers alone, the way the offline replay will

Start the bank first (uvicorn bank.backend.app:app), make the agent once:
    python -m kya.identity.registry new agent_shopper "Demo Labs"
then:
    python tools/agent_example.py

Until K9 the bank pays without checking; the gate that acts on these checks
comes next. The agent also borrows the customer's API session for now.
"""

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bank.backend.db import connect  # noqa: E402
from bank.backend.ingest import LOG  # noqa: E402
from kya.identity.registry import get_agent  # noqa: E402
from kya.identity.keys import agent_key_path, load_private_key  # noqa: E402
from kya.identity.mandates import verify_mandate  # noqa: E402
from kya.identity.signing import sign_request, verify_request  # noqa: E402

BANK = "http://127.0.0.1:8000"
AGENT = "agent_shopper"
PATH = "/api/merchant/pay"


def main():
    key_file = agent_key_path(AGENT)
    if not key_file.exists():
        sys.exit(f'no key for {AGENT}: run  python -m kya.identity.registry new {AGENT} "Demo Labs"')
    agent_key = load_private_key(key_file)

    with httpx.Client(base_url=BANK) as bank:
        # 1. the customer's side (shortcut for the Assistants page)
        sid = bank.post("/api/login", json={"username": "cust_0001", "password": "demo1234"}).json()["session_id"]
        r = bank.post("/api/mandates", json={
            "agent_id": AGENT, "merchant_categories": ["grocery"], "payees": [],
            "max_per_txn_paise": 200_000, "max_total_paise": 500_000, "max_txn_per_day": 3, "expiry_days": 7})
        r.raise_for_status()
        token = r.json()["token"]
        print("1. mandate issued:", r.json()["mandate_id"])

        # 2. the agent's side: exact body bytes, signed, sent as-is
        body = json.dumps({"merchant_id": "mr_grocermart", "amount_paise": 120_000, "currency": "INR"}).encode()
        headers = sign_request("POST", PATH, body, agent_id=AGENT, private_key=agent_key, mandate_token=token)
        bank.cookies.clear()  # an API client: session by header, no browser cookie
        r = bank.post(PATH, content=body, headers={**headers, "Content-Type": "application/json",
                                                   "X-KYA-Session": sid})
        print("2. signed payment sent:", r.status_code, r.json())
        issuer_pub = bank.get("/api/issuer-key").json()["public_key"]

    # 3. re-check from the log alone
    call = [e for e in LOG.read(sid) if e["type"] == "api_call" and e["data"]["path"] == PATH][-1]
    d = call["data"]
    raw = {"signature-input": d["headers"]["signature_input"], "signature": d["headers"]["signature"],
           "content-digest": d["headers"]["content_digest"], "kya-mandate": d["headers"]["kya_mandate"],
           "kya-mandate-id": d["headers"]["kya_mandate_id"]}
    conn = connect()

    def registry_key(agent_id):  # the public key the bank's registry holds
        agent = get_agent(conn, agent_id)
        return agent["public_key"] if agent else None

    sig = verify_request(d["method"], d["path"], d["query"], raw, lookup_key=registry_key,
                         now_ms=call["server_ts_ms"], digest_ok=d["content_digest_ok"])
    m = verify_mandate(sig.mandate_token, issuer_pub, now_ms=call["server_ts_ms"],
                       request={"agent_id": sig.agent_id, "account_id": None, "action": "merchant_payment",
                                "payee_id": d["body"]["merchant_id"], "merchant_category": "grocery",
                                "amount_paise": d["body"]["amount_paise"], "currency": d["body"]["currency"]},
                       usage={"revoked": False, "consumed_paise": 0, "payments_today": 0})
    print(f"3. from the log (seq {call['seq']}): identity {sig.state} ({sig.agent_id}), mandate {m.state}")
    print(f"   nonce {sig.nonce} -> the K9 gate consumes it; a second use is a replay (R02)")


if __name__ == "__main__":
    main()
