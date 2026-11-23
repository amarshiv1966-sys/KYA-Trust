"""Signed API bot (P6): an agent that signs its own requests and carries a mandate.

Steps per session, the same ones as tools/agent_example.py:
  1. log in as a customer (the human's side)
  2. the customer gives the agent a mandate for one merchant category
  3. the agent signs one merchant payment with its own key and sends it

Needs the bank running on this machine and the agent keys made once, see
ensure_agents(). Families differ in which agent signs, how long it waits and what
user agent it sends, so the model learns "signed bot", not one script.
"""
import json
import time
import httpx
from bots.common import API_BASE, PASSWORD, pick_customer, pick_amount_paise

ISSUERS = {"agent_billpay_a": "Billwise Labs", "agent_billpay_b": "Billwise Labs",
           "agent_billpay_c": "Payloop Systems", "agent_billpay_d": "Payloop Systems"}


def ensure_agents(agent_ids):
    """Make the key file and the registry row for each agent (safe to repeat)."""
    from bank.backend.db import connect, init_db
    from kya.identity.registry import new_demo_agent
    conn = connect()
    init_db(conn)
    for a in agent_ids:
        new_demo_agent(conn, a, ISSUERS.get(a, "Demo Labs"))
    conn.commit()


def run(scenario, fam, rng):
    from kya.identity.keys import agent_key_path, load_private_key
    from kya.identity.signing import sign_request

    agent_id = rng.choice(fam["agents"])
    ensure_agents([agent_id])
    key = load_private_key(agent_key_path(agent_id))
    wait = fam["pause_s"]

    c = httpx.Client(base_url=API_BASE, headers={"User-Agent": fam["user_agent"]}, timeout=10)
    r = c.post("/api/login", json={"username": pick_customer(rng), "password": PASSWORD})
    r.raise_for_status()
    sid = r.json()["session_id"]
    c.headers["X-KYA-Session"] = sid
    c.cookies.clear()                       # an API client: the session travels in the header only
    balance = c.get("/api/balance").json()["balance_paise"]
    time.sleep(wait)

    # a merchant the mandate allows (the scenario says "allowed")
    merchants = c.get("/api/merchants").json()["merchants"]
    allowed = [m for m in merchants if m["category"] in fam["categories"]]
    merchant = rng.choice(allowed)
    amount = pick_amount_paise(scenario, rng, balance)

    r = c.post("/api/mandates", json={
        "agent_id": agent_id, "merchant_categories": [merchant["category"]], "payees": [],
        "max_per_txn_paise": max(amount * 2, 500_000), "max_total_paise": max(amount * 4, 2_000_000),
        "max_txn_per_day": 3, "expiry_days": 7})
    r.raise_for_status()
    token = r.json()["token"]
    time.sleep(wait)

    path = "/api/merchant/pay"
    body = json.dumps({"merchant_id": merchant["merchant_id"], "amount_paise": amount, "currency": "INR"}).encode()
    headers = sign_request("POST", path, body, agent_id=agent_id, private_key=key, mandate_token=token)
    r = c.post(path, content=body, headers={**headers, "Content-Type": "application/json"})
    print(f"  {agent_id} paid {merchant['merchant_id']} {amount/100:.0f} INR -> {r.status_code} {r.text[:120]}")
    return sid
