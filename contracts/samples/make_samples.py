"""Writes the three hand-made sample logs in this folder.

Run:  python contracts/samples/make_samples.py

The logs follow docs/schema.md v1 so Prachi can build features before the bank
works. They are invented, not recorded. The signature headers in the agent
sample are placeholders; K8 regenerates them with real Ed25519 signatures.
"""

import json
import random
from pathlib import Path

HERE = Path(__file__).parent
T0 = 1795300000000  # a fixed start time (ms since epoch) so the files never change


class Log:
    """Builds one session's events with correct seq and timestamps."""

    def __init__(self, session_id, client, seed):
        self.session_id = session_id
        self.client = client
        self.events = []
        self.t = T0
        self.rng = random.Random(seed)

    def wait(self, ms):
        self.t += ms

    def add(self, type_, data, page=None, source="client"):
        seq = len(self.events) + 1
        self.events.append({
            "schema_version": 1,
            "session_id": self.session_id,
            "event_id": f"{self.session_id}-e{seq:04d}",
            "seq": seq,
            "client_ts_ms": self.t - 40 if source == "client" else None,  # browser clock runs a bit behind
            "server_ts_ms": self.t,
            "type": type_,
            "source": source,
            "page": page,
            "client": self.client,
            "data": data,
        })
        return seq

    def save(self, name):
        path = HERE / name
        with open(path, "w", newline="\n") as f:
            for ev in self.events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        print(f"wrote {path.name}: {len(self.events)} events")


def no_headers():
    return {"user_agent": None, "accept_language": None, "signature_input": None,
            "signature": None, "content_digest": None, "kya_mandate_id": None,
            "idempotency_key": None}


def browser_headers(ua):
    h = no_headers()
    h["user_agent"] = ua
    h["accept_language"] = "en-IN,en;q=0.9"
    return h


def history(count, median_paise, mad_paise, payees, categories):
    return {"payment_count": count, "median_amount_paise": median_paise,
            "mad_amount_paise": mad_paise, "payees_seen": payees,
            "categories_seen": categories, "last_payment_ts_ms": T0 - 3 * 86400000}


VERSIONS = {"policy_version": "p-0", "model_version": "fake-0"}
ISSUER_KEY = "SAMPLE_ISSUER_PUBLIC_KEY_PLACEHOLDER"


# ---------- 1. A human makes a normal transfer to a saved payee ----------

def human_transfer():
    client = {"device_id": "dv_7c21a0", "device_class": "laptop", "os_family": "windows",
              "browser_family": "chrome", "input_type": "mouse", "webdriver": False,
              "languages_count": 2, "timezone_offset_min": 330}
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"
    log = Log("s_a1b2c3d4e5f6", client, seed=1)
    r = log.rng

    def move(page, n):
        # a curved, uneven human pointer path
        x, y = r.randint(200, 900), r.randint(150, 500)
        pts, t = [], 0
        for _ in range(n):
            x += r.randint(-30, 40)
            y += r.randint(-20, 25)
            t += r.randint(35, 70)
            pts.append([t, x, y])
        log.add("pointer_move", {"points": pts}, page)
        log.wait(t)

    def click(page, target, w=120, h=36, centre_hit=False):
        ox = 0 if centre_hit else r.randint(-int(w / 3), int(w / 3))
        oy = 0 if centre_hit else r.randint(-int(h / 3), int(h / 3))
        log.add("click", {"target": target, "x": 500 + ox, "y": 300 + oy, "target_w": w,
                          "target_h": h, "offset_x": ox, "offset_y": oy,
                          "press_ms": r.randint(70, 140)}, page)
        log.wait(r.randint(150, 400))

    def type_text(page, target, classes):
        flight = None
        for kc in classes:
            log.add("keystroke", {"target": target, "key_class": kc,
                                  "dwell_ms": r.randint(60, 130), "flight_ms": flight}, page)
            flight = r.randint(80, 260)
            log.wait(flight)

    log.add("page_view", {"from_page": None, "viewport_w": 1440, "viewport_h": 820}, "login")
    log.wait(1800)
    move("login", 12)
    click("login", "login.username", w=280)
    type_text("login", "login.username", ["letter"] * 6 + ["digit"] * 2)
    # the password field produces no events at all
    log.wait(2600)
    move("login", 8)
    click("login", "login.submit")
    log.add("form_submit", {"form": "login.form", "fields_filled": 2,
                            "fields_without_keys": 0, "paste_count": 0}, "login")
    log.wait(120)
    log.add("api_call", {"method": "POST", "path": "/api/login", "query": "", "status": 200,
                         "channel": "browser", "headers": browser_headers(ua),
                         "body": {"username": "cust_0007"}}, None, "server")
    log.wait(600)
    log.add("page_view", {"from_page": "login", "viewport_w": 1440, "viewport_h": 820}, "home")
    log.wait(3200)
    move("home", 15)
    log.add("scroll", {"dx": 0, "dy": 240}, "home")
    log.wait(1500)
    move("home", 10)
    click("home", "nav.transfer", w=90, h=30)
    log.add("page_view", {"from_page": "home", "viewport_w": 1440, "viewport_h": 820}, "transfer")
    log.wait(2100)
    move("transfer", 9)
    click("transfer", "transfer.payee", w=280)
    log.wait(900)
    click("transfer", "transfer.payee", w=280, h=32)  # picks a payee from the dropdown
    move("transfer", 6)
    click("transfer", "transfer.amount", w=180)
    type_text("transfer", "transfer.amount", ["digit", "digit", "digit", "backspace", "digit", "digit"])
    log.wait(1400)
    move("transfer", 11)
    click("transfer", "transfer.submit")
    log.add("form_submit", {"form": "transfer.form", "fields_filled": 2,
                            "fields_without_keys": 1, "paste_count": 0}, "transfer")
    log.wait(90)
    api = log.add("api_call", {"method": "POST", "path": "/api/transfer", "query": "", "status": 202,
                               "channel": "browser", "headers": browser_headers(ua),
                               "body": {"payee_id": "py_000031", "amount_paise": 250000,
                                        "currency": "INR"}}, None, "server")
    tx = log.add("transaction", {"action": "transfer", "amount_paise": 250000, "currency": "INR",
                                 "payee_id": "py_000031", "new_payee": False,
                                 "merchant_category": None, "mandate_token": None,
                                 "mandate_id": None, "idempotency_key": None,
                                 "api_call_seq": api}, None, "server")
    log.add("decision_context", {
        "decision_seq": tx, "account_id": "ac_0007", "user_id": "cust_0007", "mandate": None,
        "history": history(42, 180000, 90000, ["py_000031", "py_000044", "mr_powergrid"],
                           ["utilities", "grocery"]),
        "provenance": {"device_accounts_before": 0, "agent": None},
        "issuer_public_key": ISSUER_KEY, "versions": VERSIONS}, None, "server")
    log.save("human_transfer.jsonl")


# ---------- 2. A signed LLM agent pays the mock shop inside its mandate ----------

def signed_agent_merchant():
    client = {"device_id": "dv_a90f13", "device_class": "desktop", "os_family": "linux",
              "browser_family": "chrome", "input_type": "unknown", "webdriver": True,
              "languages_count": 1, "timezone_offset_min": 330}
    ua = "Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/131.0"
    log = Log("s_b7e1f2a3c4d5", client, seed=2)

    def think(ms):
        # LLM rhythm: a long pause with no pointer movement
        log.wait(ms)

    def exact_click(page, target, w=120, h=36):
        log.add("click", {"target": target, "x": 640, "y": 360, "target_w": w, "target_h": h,
                          "offset_x": 0, "offset_y": 0, "press_ms": None}, page)
        log.wait(30)

    log.add("page_view", {"from_page": None, "viewport_w": 1280, "viewport_h": 720}, "shop")
    think(3400)
    exact_click("shop", "shop.item.sku101.add")
    think(2900)
    exact_click("shop", "shop.checkout")
    think(4100)
    exact_click("shop", "shop.pay")
    log.add("form_submit", {"form": "shop.cart", "fields_filled": 0,
                            "fields_without_keys": 0, "paste_count": 0}, "shop")
    log.wait(60)
    headers = browser_headers(ua)
    headers.update({
        "signature_input": 'sig1=("@method" "@path" "@query" "content-digest" "kya-mandate-id");'
                           'created=1795300010;nonce="n_5f2c9a";keyid="ag_shopper01";alg="ed25519"',
        "signature": "sig1=:SAMPLE_SIGNATURE_PLACEHOLDER:",
        "content_digest": "sha-256=:SAMPLE_DIGEST_PLACEHOLDER:",
        "kya_mandate_id": "md_00012",
        "idempotency_key": "ik_8812ac",
    })
    api = log.add("api_call", {"method": "POST", "path": "/api/merchant/pay", "query": "",
                               "status": 202, "channel": "browser", "headers": headers,
                               "body": {"merchant_id": "mr_kyashop", "amount_paise": 149900,
                                        "currency": "INR"}}, None, "server")
    tx = log.add("transaction", {"action": "merchant_payment", "amount_paise": 149900,
                                 "currency": "INR", "payee_id": "mr_kyashop", "new_payee": False,
                                 "merchant_category": "electronics",
                                 "mandate_token": "SAMPLE_MANDATE_JWT_PLACEHOLDER",
                                 "mandate_id": "md_00012", "idempotency_key": "ik_8812ac",
                                 "api_call_seq": api}, None, "server")
    log.add("decision_context", {
        "decision_seq": tx, "account_id": "ac_0012", "user_id": "cust_0012",
        "mandate": {"mandate_id": "md_00012", "status": "active", "consumed_paise": 300000,
                    "payments_today": 1},
        "history": history(57, 120000, 70000, ["mr_kyashop", "mr_grocermart", "py_000102"],
                           ["electronics", "grocery"]),
        "provenance": {"device_accounts_before": 0,
                       "agent": {"agent_id": "ag_shopper01",
                                 "public_key": "SAMPLE_AGENT_PUBLIC_KEY_PLACEHOLDER",
                                 "issuer": "acme-assistants", "past_incidents": 0}},
        "issuer_public_key": ISSUER_KEY, "versions": VERSIONS}, None, "server")
    log.save("signed_agent_merchant.jsonl")


# ---------- 3. An unsigned HTTP bot logs in and downloads a statement ----------

def http_bot_statement():
    client = {"device_id": "dv_33b0e8", "device_class": "unknown", "os_family": "other",
              "browser_family": "none", "input_type": "unknown", "webdriver": None,
              "languages_count": None, "timezone_offset_min": None}
    ua = "python-httpx/0.28"
    log = Log("s_c0ffee112233", client, seed=3)

    def call(method, path, query, body, status=200):
        h = no_headers()
        h["user_agent"] = ua
        seq = log.add("api_call", {"method": method, "path": path, "query": query,
                                   "status": status, "channel": "api", "headers": h,
                                   "body": body}, None, "server")
        log.wait(250)  # machine-regular gaps
        return seq

    call("POST", "/api/login", "", {"username": "cust_0021"})
    call("GET", "/api/balance", "", None)
    call("GET", "/api/statements", "range=30", None)
    api = call("GET", "/api/statements/download", "range=30", None)
    tx = log.add("transaction", {"action": "statement_download", "amount_paise": 0,
                                 "currency": "INR", "payee_id": None, "new_payee": False,
                                 "merchant_category": None, "mandate_token": None,
                                 "mandate_id": None, "idempotency_key": None,
                                 "api_call_seq": api}, None, "server")
    log.add("decision_context", {
        "decision_seq": tx, "account_id": "ac_0021", "user_id": "cust_0021", "mandate": None,
        "history": history(3, 90000, 40000, ["py_000210"], ["telecom"]),
        "provenance": {"device_accounts_before": 4, "agent": None},
        "issuer_public_key": ISSUER_KEY, "versions": VERSIONS}, None, "server")
    log.save("http_bot_statement.jsonl")


if __name__ == "__main__":
    human_transfer()
    signed_agent_merchant()
    http_bot_statement()
