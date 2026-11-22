"""Creates a fresh demo bank: customers, accounts, merchants and saved payees.

Run:  python -m bank.backend.seed        (wipes data/bank.sqlite3 first)

Every customer's password is "demo1234". All names are invented.
"""

import hashlib
import os
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from bank.backend.db import connect, db_path, init_db, now_ms

PASSWORD = "demo1234"

MERCHANTS = [
    ("mr_grocermart", "GrocerMart", "grocery"),
    ("mr_powergrid", "PowerGrid Electricity", "utilities"),
    ("mr_netfibre", "NetFibre Broadband", "telecom"),
    ("mr_quickbite", "QuickBite", "food_delivery"),
    ("mr_gadgethub", "GadgetHub", "electronics"),
    ("mr_railgo", "RailGo Tickets", "travel"),
    ("mr_streambox", "StreamBox", "entertainment"),
    ("mr_learnly", "Learnly", "education"),
    ("mr_giftzone", "GiftZone", "gift_cards"),
    ("mr_coinswap", "CoinSwap", "crypto_exchange"),
    ("mr_kyashop", "KYA Mock Shop", "electronics"),
]

FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Vivaan", "Anaya", "Arjun", "Saanvi",
         "Dev", "Myra", "Ira", "Reyansh", "Tara", "Vihaan", "Nisha", "Yash", "Pooja", "Neel"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Gupta", "Rao", "Mehta", "Singh", "Das", "Joshi"]

N_CUSTOMERS = 20
IST = ZoneInfo("Asia/Kolkata")


def hash_password(password, salt=None):
    """pbkdf2 from the standard library: no extra package needed."""
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${digest}"


def check_password(password, stored):
    salt, _ = stored.split("$")
    return hash_password(password, salt) == stored


def seed_history(conn, account_id, payee_ids, rng, end_balance_paise, days=90):
    """90 days of ordinary banking for one account, so Home and Statements
    look real and the model's history features have something to read:
    salary, rent, bills, groceries, food, travel and transfers to saved payees.
    Rows have no session (they happened before the study). The running
    balance never goes below zero; the account ends near end_balance_paise.
    Must run inside the caller's transaction."""
    day_ms = 86_400_000
    today = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    t0 = int(today.timestamp() * 1000) - days * day_ms   # midnight IST, `days` ago
    ev = []  # (ts, action, counterparty, category, signed paise)

    def at(day, hour_lo=9, hour_hi=22):
        return t0 + day * day_ms + rng.randint(hour_lo, hour_hi) * 3_600_000 + rng.randint(0, 3_599_999)

    def rs(lo, hi, step=1):
        return rng.randrange(lo, hi + 1, step) * 100

    salary = rs(35_000, 140_000, 500)
    rent_payee = payee_ids[0] if payee_ids and rng.random() < 0.6 else None
    rent = rs(7_000, 25_000, 500)
    stream = rng.choice([149, 199, 499, 649]) * 100
    for day in range(days):
        date = datetime.fromtimestamp((t0 + day * day_ms) / 1000, IST)
        if date.day == 1:
            ev.append((at(day, 6, 9), "credit", "employer", "salary", salary))
            if rent_payee:
                ev.append((at(day), "transfer", rent_payee, None, -rent))
        if date.day == 5:
            ev.append((at(day), "merchant_payment", "mr_powergrid", "utilities", -rs(700, 3_800, 10)))
        if date.day == 8:
            ev.append((at(day), "merchant_payment", "mr_netfibre", "telecom", -rng.choice([499, 699, 999]) * 100))
        if date.day == 12:
            ev.append((at(day), "merchant_payment", "mr_streambox", "entertainment", -stream))
        if date.weekday() == rng.choice([5, 6]) and rng.random() < 0.85:
            ev.append((at(day), "merchant_payment", "mr_grocermart", "grocery", -rs(450, 3_600, 10)))
        if rng.random() < 0.35:
            ev.append((at(day, 12, 23), "merchant_payment", "mr_quickbite", "food_delivery", -rs(140, 900)))
        if rng.random() < 0.025:
            ev.append((at(day), "merchant_payment", "mr_railgo", "travel", -rs(400, 3_200, 5)))
        if payee_ids and rng.random() < 0.06:
            ev.append((at(day), "transfer", rng.choice(payee_ids), None, -rs(300, 6_000, 50)))
        if rng.random() < 0.01:
            ev.append((at(day), "merchant_payment", "mr_learnly", "education", -rs(499, 4_999)))
    ev = sorted(e for e in ev if e[0] < now_ms())

    total = sum(e[4] for e in ev)
    start = end_balance_paise - total
    running, low = start, start
    for e in ev:
        running += e[4]
        low = min(low, running)
    if low < 0:
        start -= low  # top up the start so the balance never dips below zero
    bal = start
    for ts, action, cp, cat, amt in ev:
        bal += amt
        conn.execute("INSERT INTO ledger (account_id, ts_ms, action, counterparty, category, amount_paise, "
                     "balance_after) VALUES (?, ?, ?, ?, ?, ?, ?)", (account_id, ts, action, cp, cat, amt, bal))
    conn.execute("UPDATE accounts SET balance_paise = ? WHERE account_id = ?", (bal, account_id))
    return bal


def seed(conn, rng):
    init_db(conn)
    t = now_ms()
    pw = hash_password(PASSWORD)  # one hash reused: seeding 20 users stays fast

    conn.execute("BEGIN")
    conn.executemany("INSERT INTO merchants VALUES (?, ?, ?)", MERCHANTS)

    payee_no = 0
    for i in range(1, N_CUSTOMERS + 1):
        user_id = f"cust_{i:04d}"
        account_id = f"ac_{i:04d}"
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        balance = rng.randint(20_000, 300_000) * 100  # Rs 20,000 to Rs 3,00,000
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (user_id, user_id, pw, name))
        conn.execute("INSERT INTO accounts VALUES (?, ?, ?)", (account_id, user_id, balance))

        # two or three saved payees each
        mine = []
        for _ in range(rng.randint(2, 3)):
            payee_no += 1
            mine.append(f"py_{payee_no:06d}")
            conn.execute(
                "INSERT INTO payees VALUES (?, ?, ?, ?, ?, ?)",
                (mine[-1], account_id, f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                 f"{rng.randint(10**11, 10**12 - 1)}", f"KYAB000{rng.randint(1000, 9999)}",
                 t - rng.randint(120, 400) * 86_400_000),
            )
        seed_history(conn, account_id, mine, rng, balance)
    conn.execute("COMMIT")
    # Past payment history for the features comes from Prachi's PaySim
    # generator (P2), not from here.


def main():
    path = db_path()
    for suffix in ["", "-wal", "-shm"]:
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()
    conn = connect()
    seed(conn, random.Random(7))
    print(f"seeded {N_CUSTOMERS} customers into {path}")
    print(f"log in as cust_0001 .. cust_{N_CUSTOMERS:04d}, password {PASSWORD}")


if __name__ == "__main__":
    main()
