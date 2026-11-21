"""SQLite database for the mock bank.

Plain sqlite3, no ORM, so every query is visible. Money is always integer
paise (Rs 1 = 100 paise). The server is the only owner of balances.
"""

import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "bank.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,          -- cust_0001
    username       TEXT UNIQUE NOT NULL,
    password_hash  TEXT NOT NULL,             -- pbkdf2, never the password
    display_name   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id     TEXT PRIMARY KEY,          -- ac_0001
    user_id        TEXT NOT NULL REFERENCES users(user_id),
    balance_paise  INTEGER NOT NULL CHECK (balance_paise >= 0)
);

CREATE TABLE IF NOT EXISTS merchants (
    merchant_id    TEXT PRIMARY KEY,          -- mr_grocermart
    name           TEXT NOT NULL,
    category       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payees (
    payee_id       TEXT PRIMARY KEY,          -- py_000001
    account_id     TEXT NOT NULL REFERENCES accounts(account_id),  -- whose list it is on
    name           TEXT NOT NULL,
    account_number TEXT NOT NULL,
    ifsc           TEXT NOT NULL,
    created_ms     INTEGER NOT NULL
);

-- one row per money movement; amount is negative for money leaving the account
CREATE TABLE IF NOT EXISTS ledger (
    txn_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     TEXT NOT NULL REFERENCES accounts(account_id),
    ts_ms          INTEGER NOT NULL,
    action         TEXT NOT NULL,             -- transfer | merchant_payment | credit
    counterparty   TEXT NOT NULL,             -- payee_id or merchant_id
    category       TEXT,                      -- merchant category, NULL for transfers
    amount_paise   INTEGER NOT NULL,
    balance_after  INTEGER NOT NULL,
    session_id     TEXT,
    mandate_id     TEXT,
    nonce          TEXT,
    UNIQUE (mandate_id, nonce)                -- a signed request can pay only once
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,          -- s_ + 12 hex
    user_id        TEXT REFERENCES users(user_id),
    device_id      TEXT,
    channel        TEXT NOT NULL,             -- browser | api
    created_ms     INTEGER NOT NULL,
    ended_ms       INTEGER
);

-- filled in by K8 (identity), K9 (gate) and K15 (step-up)
CREATE TABLE IF NOT EXISTS agents (
    agent_id       TEXT PRIMARY KEY,
    public_key     TEXT NOT NULL,
    issuer         TEXT NOT NULL,
    past_incidents INTEGER NOT NULL DEFAULT 0,
    created_ms     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS mandates (
    mandate_id     TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    account_id     TEXT NOT NULL,
    agent_id       TEXT NOT NULL,
    token          TEXT NOT NULL,
    max_total_paise INTEGER NOT NULL,
    consumed_paise INTEGER NOT NULL DEFAULT 0,
    revoked        INTEGER NOT NULL DEFAULT 0,
    expires_ms     INTEGER NOT NULL,
    created_ms     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS nonces (
    agent_id       TEXT NOT NULL,
    nonce          TEXT NOT NULL,
    seen_ms        INTEGER NOT NULL,
    PRIMARY KEY (agent_id, nonce)
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id    TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    payee_id       TEXT NOT NULL,
    amount_paise   INTEGER NOT NULL,
    currency       TEXT NOT NULL,
    expires_ms     INTEGER NOT NULL,
    used           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS idempotency (
    key            TEXT PRIMARY KEY,
    response_json  TEXT NOT NULL,
    created_ms     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    session_id     TEXT NOT NULL,
    decision_seq   INTEGER NOT NULL,
    decision_json  TEXT NOT NULL,
    created_ms     INTEGER NOT NULL,
    PRIMARY KEY (session_id, decision_seq)
);
"""


def db_path():
    return Path(os.environ.get("KYA_DB", DEFAULT_DB))


def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: we write BEGIN / COMMIT ourselves, so it is clear
    # exactly which statements run together
    # check_same_thread=False: FastAPI may open the connection in one worker
    # thread and run the endpoint in another. Each request still gets its own
    # connection, so nothing is shared between requests.
    conn = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)


def now_ms():
    return int(time.time() * 1000)
