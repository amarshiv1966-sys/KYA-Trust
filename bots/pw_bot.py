"""Browser bot (Playwright). Uses only data-kya-id selectors from contracts/element_ids.md."""
import re
from playwright.sync_api import sync_playwright
from bots.common import BASE, PASSWORD, pick_customer, pick_amount_paise

NAMES = ["Rahul Kapoor", "Sneha Rao", "Imran Khan", "Divya Menon", "Karan Bhatt"]


def by_id(kya_id):
    return f'[data-kya-id="{kya_id}"]'


def put(page, kya_id, text, fam):
    """Fill a field. 'fill' sets the value at once (no key events); 'keys' types it with a fixed delay."""
    sel = by_id(kya_id)
    if fam["typing"] == "fill":
        page.fill(sel, text)
    else:
        page.click(sel)
        page.locator(sel).press_sequentially(text, delay=fam["key_delay_ms"])


def run(scenario, fam, rng, headed=False):
    pause = fam["pause_ms"]
    with sync_playwright() as p:
        browser = getattr(p, fam["browser"]).launch(headless=not headed)
        page = browser.new_page()

        page.goto(BASE + "/login")
        put(page, "login.username", pick_customer(rng), fam)
        put(page, "login.password", PASSWORD, fam)
        page.click(by_id("login.submit"))
        page.wait_for_selector(by_id("home.balance"))
        page.wait_for_function("!document.querySelector('[data-kya-id=\"home.balance\"]').innerText.includes('…')")
        sid = [c["value"] for c in page.context.cookies() if c["name"] == "kya_sid"][0]
        balance_text = page.inner_text(by_id("home.balance"))          # like "₹1,23,456.00"
        balance_paise = int(float(re.sub(r"[^\d.]", "", balance_text)) * 100)
        page.wait_for_timeout(pause)

        if scenario["action"] == "read_only":
            page.click(by_id("nav.statements"))
            page.wait_for_timeout(pause)
            page.click(by_id("statements.view"))
            page.wait_for_timeout(pause)
            with page.expect_download():
                page.click(by_id("statements.download"))
        else:
            payee_id = None
            if scenario["payee"] == "new":
                page.click(by_id("nav.payees"))
                put(page, "payees.name", rng.choice(NAMES), fam)
                put(page, "payees.account", str(rng.randint(10**11, 10**12 - 1)), fam)
                put(page, "payees.ifsc", f"KYAB0{rng.randint(100000, 999999)}", fam)
                page.click(by_id("payees.submit"))
                page.wait_for_selector(".ok")
                payee_id = re.search(r"py_\d+", page.inner_text(".ok")).group(0)   # "Payee added (py_000042)"
                page.wait_for_timeout(pause)
            page.click(by_id("nav.transfer"))
            page.wait_for_selector(by_id("transfer.payee") + " option:nth-child(2)", state="attached")
            if payee_id:
                page.select_option(by_id("transfer.payee"), payee_id)
            else:
                page.select_option(by_id("transfer.payee"), index=1)
            amount = pick_amount_paise(scenario, rng, balance_paise) // 100
            put(page, "transfer.amount", str(amount), fam)
            page.wait_for_timeout(pause)
            page.click(by_id("transfer.submit"))
            page.wait_for_selector(".ok")

        page.click(by_id("nav.logout"))
        page.wait_for_selector(by_id("login.submit"))
        browser.close()
    return sid
