"""Join 0 (plan, 25 Nov): one real browser transfer and one signed-agent
payment are scored live, then replayed offline with the network off. The
replayed answers must be identical, and the bank's database must not change.

Part 1, with the bank running (uvicorn + npm run dev) and the agent made once
(python -m kya.identity.registry new agent_shopper "Demo Labs"):
    python tools/join0.py live
Part 2, with Wi-Fi OFF (the bank may keep running; it is not used):
    python tools/join0.py replay
"""

import hashlib
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bank.backend.db import db_path  # noqa: E402
from bank.backend.ingest import raw_dir  # noqa: E402

STATE = ROOT / "data" / "join0.json"
BASE = "http://localhost:5173"
BANK = "http://127.0.0.1:8000"


# ---------- part 1: live ----------

def person_transfer():
    """A person-like browser session: mouse moves, typing with gaps, Rs 1,200 transfer."""
    from playwright.sync_api import sync_playwright

    def sel(i):
        return f'[data-kya-id="{i}"]'

    def click(page, i):
        box = page.locator(sel(i)).bounding_box()
        page.mouse.move(box["x"] + box["width"] * random.uniform(0.3, 0.7),
                        box["y"] + box["height"] * random.uniform(0.3, 0.7), steps=random.randint(10, 25))
        page.mouse.down(); time.sleep(random.uniform(0.07, 0.13)); page.mouse.up()

    def type_(page, text):
        for ch in text:
            page.keyboard.down(ch); time.sleep(random.uniform(0.05, 0.12))
            page.keyboard.up(ch); time.sleep(random.uniform(0.08, 0.3))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.goto(BASE + "/login")
        page.wait_for_selector(sel("login.username"))
        click(page, "login.username"); type_(page, "cust_0004")
        click(page, "login.password"); type_(page, "demo1234")
        click(page, "login.submit"); page.wait_for_selector(sel("home.balance"))
        time.sleep(1)
        click(page, "nav.transfer")
        page.wait_for_selector(sel("transfer.payee") + " option:nth-child(2)", state="attached")
        click(page, "transfer.payee"); page.select_option(sel("transfer.payee"), index=1)
        click(page, "transfer.amount"); type_(page, "1200")
        with page.expect_response(lambda r: r.url.endswith("/api/transfer")) as resp:
            click(page, "transfer.submit")
        answer = resp.value.json()
        time.sleep(1)
        browser.close()
    return answer


def agent_payment():
    """agent_shopper pays Rs 1,200 at GrocerMart under a fresh mandate from cust_0005."""
    import httpx
    from kya.identity.keys import agent_key_path, load_private_key
    from kya.identity.signing import sign_request

    key_file = agent_key_path("agent_shopper")
    if not key_file.exists():
        sys.exit('make the agent first:  python -m kya.identity.registry new agent_shopper "Demo Labs"')
    key = load_private_key(key_file)
    with httpx.Client(base_url=BANK) as bank:
        sid = bank.post("/api/login", json={"username": "cust_0005", "password": "demo1234"}).json()["session_id"]
        bank.get("/api/balance")
        token = bank.post("/api/mandates", json={
            "agent_id": "agent_shopper", "merchant_categories": ["grocery"], "payees": [],
            "max_per_txn_paise": 200_000, "max_total_paise": 500_000, "max_txn_per_day": 3,
            "expiry_days": 7}).json()["token"]
        body = json.dumps({"merchant_id": "mr_grocermart", "amount_paise": 120_000, "currency": "INR"}).encode()
        headers = sign_request("POST", "/api/merchant/pay", body, agent_id="agent_shopper",
                               private_key=key, mandate_token=token)
        bank.cookies.clear()
        return bank.post("/api/merchant/pay", content=body,
                         headers={**headers, "Content-Type": "application/json", "X-KYA-Session": sid}).json()


def live():
    results = {}
    for label, run in (("browser transfer", person_transfer), ("signed agent", agent_payment)):
        r = run()
        d = r["decision"]
        print(f"{label:<17} {r['status']:<9} trust {d['trust_score']:>3}  {d['agent_class']:<12} "
              f"identity {d['identity_state']}, mandate {d['mandate_state']}  (session {d['session_id']})")
        results[label] = {"session_id": d["session_id"], "decision_seq": d["decision_seq"]}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(results, indent=2))
    print(f"\nSaved to {STATE.relative_to(ROOT)}. Now turn Wi-Fi OFF and run:  python tools/join0.py replay")


# ---------- part 2: replay ----------

def db_contents():
    conn = sqlite3.connect(f"file:{db_path().as_posix()}?mode=ro", uri=True)
    try:
        return hashlib.sha256("\n".join(conn.iterdump()).encode()).hexdigest()
    finally:
        conn.close()


def online():
    import socket
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close()
        return True
    except OSError:
        return False


def replay():
    from kya.replay import live_decision, load, strip
    from kya.score import score_session

    if not STATE.exists():
        sys.exit("run  python tools/join0.py live  first")
    if online():
        print("WARNING: this machine is online. For the real Join 0 check, turn Wi-Fi off and run again.\n")
    sessions = json.loads(STATE.read_text())
    before = db_contents()
    ok = True
    for label, s in sessions.items():
        events = load(raw_dir() / f"{s['session_id']}.jsonl")
        replayed = score_session(events, decision_seq=s["decision_seq"])
        live_d = live_decision(s["session_id"], s["decision_seq"])
        same = live_d is not None and strip(live_d) == strip(replayed)
        ok &= same
        print(f"{label:<17} replayed {replayed['action']:<8} trust {replayed['trust_score']:>3}  "
              f"{'IDENTICAL to live' if same else 'DIFFERENT from live'}")
    unchanged = db_contents() == before
    ok &= unchanged
    print(f"bank database      {'unchanged' if unchanged else 'CHANGED'}")
    print("\nJOIN 0 PASSED" if ok else "\nJOIN 0 FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("live", "replay"):
        sys.exit("usage: python tools/join0.py live | replay")
    sys.exit(live() if sys.argv[1] == "live" else (replay() or 0))
