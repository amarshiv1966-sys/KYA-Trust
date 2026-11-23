"""Checks K7 end to end: drives the bank twice, once like a person (mouse
moves, typing with gaps, a typo fixed) and once like a simple bot (instant
fills, clicks at the exact centre), then prints what telemetry recorded.

Start the bank first (two terminals):
    uvicorn bank.backend.app:app
    cd bank/frontend && npm run dev
Then:
    python tools/check_telemetry.py            (add --headed to watch it)

You should see the person with off-centre clicks, ~100 ms presses and key
timings, and the bot with centre clicks, 1-2 ms presses and no keys.
"""

import json
import random
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bank.backend.ingest import raw_dir  # noqa: E402
from kya.behaviour.features import behaviour_features  # noqa: E402
from kya.schema import evidence_status, validate_events  # noqa: E402

BASE = "http://localhost:5173"
SHOW = ["n_clicks", "click_offset_mean", "click_press_median_ms", "key_flight_median_ms",
        "fields_without_keys", "env_webdriver"]


def sel(kya_id):
    return f'[data-kya-id="{kya_id}"]'


def person_click(page, kya_id):
    box = page.locator(sel(kya_id)).bounding_box()
    x = box["x"] + box["width"] * random.uniform(0.25, 0.75)
    y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
    page.mouse.move(x, y, steps=random.randint(10, 25))
    page.mouse.down()
    time.sleep(random.uniform(0.07, 0.13))
    page.mouse.up()


def person_type(page, text):
    for ch in text:
        key = "Space" if ch == " " else ch
        page.keyboard.down(key)
        time.sleep(random.uniform(0.05, 0.12))
        page.keyboard.up(key)
        time.sleep(random.uniform(0.08, 0.3))


def run_person(page):
    page.goto(BASE + "/login")
    page.wait_for_selector(sel("login.username"))
    person_click(page, "login.username")
    person_type(page, "cust_0002")
    person_click(page, "login.password")
    person_type(page, "demo1234")
    person_click(page, "login.submit")
    page.wait_for_selector(sel("home.balance"))
    time.sleep(0.8)
    person_click(page, "nav.transfer")
    page.wait_for_selector(sel("transfer.payee") + " option:nth-child(2)", state="attached")
    person_click(page, "transfer.payee")
    page.select_option(sel("transfer.payee"), index=1)
    person_click(page, "transfer.amount")
    person_type(page, "12")
    person_type(page, "o")       # a typo...
    page.keyboard.press("Backspace")  # ...fixed
    person_type(page, "0")
    person_click(page, "transfer.submit")
    page.wait_for_selector(".ok, .error")


def run_bot(page):
    page.goto(BASE + "/login")
    page.fill(sel("login.username"), "cust_0003")
    page.fill(sel("login.password"), "demo1234")
    page.click(sel("login.submit"))
    page.wait_for_selector(sel("home.balance"))
    page.click(sel("nav.transfer"))
    page.wait_for_selector(sel("transfer.payee") + " option:nth-child(2)", state="attached")
    page.select_option(sel("transfer.payee"), index=1)
    page.fill(sel("transfer.amount"), "120")
    page.click(sel("transfer.submit"))
    page.wait_for_selector(".ok, .error")


def newest_session(before):
    new = [p for p in raw_dir().glob("s_*.jsonl") if p not in before]
    new.sort(key=lambda p: p.stat().st_size, reverse=True)
    return new[0] if new else None


def report(label, path):
    events = [json.loads(line) for line in open(path, encoding="utf-8")]
    validate_events(events)
    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    f = behaviour_features(events)
    print(f"\n{label}: {path.name} ({len(events)} events, evidence {evidence_status(events)})")
    print("  events:", counts)
    for k in SHOW:
        print(f"  {k:<24} {f[k]:.1f}")


def main(headed):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        for label, run in (("PERSON-LIKE", run_person), ("BOT-LIKE", run_bot)):
            before = set(raw_dir().glob("s_*.jsonl"))
            page = browser.new_context().new_page()
            run(page)
            time.sleep(1.5)  # let the last telemetry batch arrive
            page.close()
            path = newest_session(before)
            if path is None:
                sys.exit(f"{label}: no new session file in {raw_dir()} (is uvicorn running from the repo folder?)")
            report(label, path)
        browser.close()
    print("\nOK: telemetry is recording. (env_webdriver is 1 for both: Playwright says so.)")


if __name__ == "__main__":
    main("--headed" in sys.argv)
