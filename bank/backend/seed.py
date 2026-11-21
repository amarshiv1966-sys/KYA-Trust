"""Creates a fresh demo bank: customers, accounts, merchants and saved payees.

Run:  python -m bank.backend.seed        (wipes data/bank.sqlite3 first)

Every customer's password is "demo1234". All names are invented.
"""

import hashlib
import os
import random

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


def hash_password(password, salt=None):
    """pbkdf2 from the standard library: no extra package needed."""
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${digest}"


def check_password(password, stored):
    salt, _ = stored.split("$")
    return hash_password(password, salt) == stored


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
        for _ in range(rng.randint(2, 3)):
            payee_no += 1
            conn.execute(
                "INSERT INTO payees VALUES (?, ?, ?, ?, ?, ?)",
                (f"py_{payee_no:06d}", account_id, f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                 f"{rng.randint(10**11, 10**12 - 1)}", f"KYAB000{rng.randint(1000, 9999)}",
                 t - rng.randint(30, 300) * 86_400_000),
            )
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
