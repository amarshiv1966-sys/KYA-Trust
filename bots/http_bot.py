"""API-only bot (httpx). No browser, no page views: straight to the API."""
import time
import httpx
from bots.common import API_BASE, PASSWORD, pick_customer, pick_amount_paise

NAMES = ["Rahul Kapoor", "Sneha Rao", "Imran Khan", "Divya Menon", "Karan Bhatt"]


def run(scenario, fam, rng):
    wait = fam["pause_s"]
    c = httpx.Client(base_url=API_BASE, headers={"User-Agent": fam["user_agent"]}, timeout=10)

    r = c.post("/api/login", json={"username": pick_customer(rng), "password": PASSWORD})
    r.raise_for_status()
    sid = r.json()["session_id"]
    c.headers["X-KYA-Session"] = sid
    time.sleep(wait)

    balance = c.get("/api/balance").json()["balance_paise"]
    time.sleep(wait)

    if scenario["action"] == "read_only":
        c.get("/api/statements", params={"range": 30})
        time.sleep(wait)
        c.get("/api/statements/download", params={"range": 30})
        return sid

    # transfer to a payee this account has not paid before
    if scenario["payee"] == "new":
        acct = str(rng.randint(10**11, 10**12 - 1))
        r = c.post("/api/payees", json={"name": rng.choice(NAMES), "account_number": acct,
                                        "ifsc": f"KYAB0{rng.randint(100000, 999999)}"})
        r.raise_for_status()
        payee_id = r.json()["payee_id"]
    else:
        payee_id = c.get("/api/payees").json()["payees"][0]["payee_id"]
    time.sleep(wait)

    amount = pick_amount_paise(scenario, rng, balance)
    r = c.post("/api/transfer", json={"payee_id": payee_id, "amount_paise": amount, "currency": "INR"})
    r.raise_for_status()
    return sid
