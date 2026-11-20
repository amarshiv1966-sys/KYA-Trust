"""Clicks through the bank pages using only data-kya-id selectors.

Start the bank first (two terminals):
    uvicorn bank.backend.app:app
    cd bank/frontend && npm run dev
Then:
    python tools/smoke_ui.py            (add --headed to watch it)

If this passes, Prachi's bots can drive the pages by element id alone.
"""

import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5173"


def by_id(kya_id):
    return f'[data-kya-id="{kya_id}"]'


def main(headed):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        page.goto(BASE + "/login")
        page.fill(by_id("login.username"), "cust_0001")
        page.fill(by_id("login.password"), "demo1234")
        page.click(by_id("login.submit"))
        page.wait_for_selector(by_id("home.balance"))
        page.wait_for_function("!document.querySelector('[data-kya-id=\"home.balance\"]').innerText.includes('…')")
        print("balance:", page.inner_text(by_id("home.balance")))

        page.click(by_id("nav.transfer"))
        page.wait_for_selector(by_id("transfer.payee") + " option:nth-child(2)", state="attached")
        page.select_option(by_id("transfer.payee"), index=1)
        page.fill(by_id("transfer.amount"), "2500")
        page.click(by_id("transfer.submit"))
        page.wait_for_selector(".ok")
        print("transfer:", page.inner_text(".ok"))

        page.click(by_id("nav.merchant"))
        page.wait_for_selector(by_id("merchant.merchant") + " option:nth-child(2)", state="attached")
        page.select_option(by_id("merchant.merchant"), "mr_grocermart")
        page.fill(by_id("merchant.amount"), "450.50")
        page.click(by_id("merchant.submit"))
        page.wait_for_selector(".ok")
        print("merchant:", page.inner_text(".ok"))

        page.click(by_id("nav.logout"))
        page.wait_for_selector(by_id("login.submit"))
        print("logged out: OK")
        browser.close()


if __name__ == "__main__":
    main("--headed" in sys.argv)
