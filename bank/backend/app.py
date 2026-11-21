"""The mock bank's API (K4 skeleton).

Run:  uvicorn bank.backend.app:app --reload

Browser sessions carry the cookie kya_sid. API-only clients send the same id
in the header X-KYA-Session (the login response returns it).

For now transfers and merchant payments go straight to the ledger. In K9 the
payment gate replaces execute_payment(): score first, then commit.
"""

import csv
import io
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from bank.backend.db import connect, init_db, now_ms
from bank.backend.seed import check_password

app = FastAPI(title="KYA-Trust mock bank")

COOKIE = "kya_sid"
HEADER = "X-KYA-Session"
DAY_MS = 86_400_000


def get_db():
    conn = connect()
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def new_session_id():
    return "s_" + secrets.token_hex(6)


# ---------- request bodies (pydantic rejects floats, negatives and junk) ----------

class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PayeeBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    account_number: str = Field(pattern=r"^\d{9,18}$")
    ifsc: str = Field(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")


class TransferBody(BaseModel):
    payee_id: str
    amount_paise: int = Field(gt=0, strict=True)
    currency: str = "INR"


class MerchantPayBody(BaseModel):
    merchant_id: str
    amount_paise: int = Field(gt=0, strict=True)
    currency: str = "INR"


# ---------- who is calling ----------

def current_session(request: Request, conn=Depends(get_db)):
    """Find the logged-in session from the cookie or the header, or answer 401."""
    sid = request.cookies.get(COOKIE) or request.headers.get(HEADER)
    if not sid:
        raise HTTPException(401, "not logged in")
    row = conn.execute(
        "SELECT s.session_id, s.user_id, a.account_id FROM sessions s "
        "JOIN accounts a ON a.user_id = s.user_id "
        "WHERE s.session_id = ? AND s.ended_ms IS NULL", (sid,)).fetchone()
    if row is None:
        raise HTTPException(401, "session expired or unknown")
    return dict(row)


# ---------- login ----------

@app.post("/api/login")
def login(body: LoginBody, request: Request, response: Response, conn=Depends(get_db)):
    user = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    if user is None or not check_password(body.password, user["password_hash"]):
        raise HTTPException(401, "wrong username or password")

    # our own pages send the device cookie; anything else counts as an API client
    device_id = request.cookies.get("kya_dev")
    channel = "browser" if device_id else "api"
    sid = new_session_id()
    conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, NULL)",
                 (sid, user["user_id"], device_id, channel, now_ms()))
    response.set_cookie(COOKIE, sid, httponly=True, samesite="strict")
    return {"session_id": sid, "user_id": user["user_id"], "name": user["display_name"]}


@app.post("/api/logout")
def logout(response: Response, sess=Depends(current_session), conn=Depends(get_db)):
    conn.execute("UPDATE sessions SET ended_ms = ? WHERE session_id = ?",
                 (now_ms(), sess["session_id"]))
    response.delete_cookie(COOKIE)
    return {"ok": True}


# ---------- read-only ----------

@app.get("/api/balance")
def balance(sess=Depends(current_session), conn=Depends(get_db)):
    row = conn.execute("SELECT balance_paise FROM accounts WHERE account_id = ?",
                       (sess["account_id"],)).fetchone()
    return {"account_id": sess["account_id"], "balance_paise": row["balance_paise"], "currency": "INR"}


def statement_rows(conn, account_id, days):
    since = now_ms() - days * DAY_MS
    rows = conn.execute(
        "SELECT txn_id, ts_ms, action, counterparty, category, amount_paise, balance_after "
        "FROM ledger WHERE account_id = ? AND ts_ms >= ? ORDER BY txn_id DESC",
        (account_id, since)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/statements")
def statements(range: int = 30, sess=Depends(current_session), conn=Depends(get_db)):
    if range not in (30, 60, 90):
        raise HTTPException(422, "range must be 30, 60 or 90")
    return {"range_days": range, "rows": statement_rows(conn, sess["account_id"], range)}


@app.get("/api/statements/download")
def statements_download(range: int = 30, sess=Depends(current_session), conn=Depends(get_db)):
    if range not in (30, 60, 90):
        raise HTTPException(422, "range must be 30, 60 or 90")
    rows = statement_rows(conn, sess["account_id"], range)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["txn_id", "ts_ms", "action", "counterparty", "category", "amount_paise", "balance_after"])
    for r in rows:
        writer.writerow([r["txn_id"], r["ts_ms"], r["action"], r["counterparty"], r["category"],
                         r["amount_paise"], r["balance_after"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=statement_{range}d.csv"})


@app.get("/api/payees")
def list_payees(sess=Depends(current_session), conn=Depends(get_db)):
    rows = conn.execute("SELECT payee_id, name, ifsc FROM payees WHERE account_id = ? ORDER BY name",
                        (sess["account_id"],)).fetchall()
    return {"payees": [dict(r) for r in rows]}


@app.get("/api/merchants")
def list_merchants(conn=Depends(get_db)):
    rows = conn.execute("SELECT merchant_id, name, category FROM merchants ORDER BY name").fetchall()
    return {"merchants": [dict(r) for r in rows]}


# ---------- sensitive actions ----------

@app.post("/api/payees")
def add_payee(body: PayeeBody, sess=Depends(current_session), conn=Depends(get_db)):
    count = conn.execute("SELECT COUNT(*) FROM payees").fetchone()[0]
    payee_id = f"py_{count + 1:06d}"
    conn.execute("INSERT INTO payees VALUES (?, ?, ?, ?, ?, ?)",
                 (payee_id, sess["account_id"], body.name, body.account_number, body.ifsc, now_ms()))
    return {"payee_id": payee_id}


def execute_payment(conn, sess, action, counterparty, category, amount_paise):
    """Move money out of the session's account. One ledger row, all or nothing.

    BEGIN IMMEDIATE takes the write lock before reading the balance, so two
    payments at the same moment cannot both spend the same money.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        bal = conn.execute("SELECT balance_paise FROM accounts WHERE account_id = ?",
                           (sess["account_id"],)).fetchone()["balance_paise"]
        if amount_paise > bal:
            conn.execute("ROLLBACK")
            raise HTTPException(400, "insufficient balance")
        new_bal = bal - amount_paise
        conn.execute("UPDATE accounts SET balance_paise = ? WHERE account_id = ?",
                     (new_bal, sess["account_id"]))
        cur = conn.execute(
            "INSERT INTO ledger (account_id, ts_ms, action, counterparty, category, amount_paise, "
            "balance_after, session_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sess["account_id"], now_ms(), action, counterparty, category, -amount_paise, new_bal,
             sess["session_id"]))
        conn.execute("COMMIT")
    except HTTPException:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"status": "executed", "txn_id": cur.lastrowid, "balance_paise": new_bal}


@app.post("/api/transfer", status_code=202)
def transfer(body: TransferBody, sess=Depends(current_session), conn=Depends(get_db)):
    if body.currency != "INR":
        raise HTTPException(422, "only INR is supported")
    payee = conn.execute("SELECT payee_id FROM payees WHERE payee_id = ? AND account_id = ?",
                         (body.payee_id, sess["account_id"])).fetchone()
    if payee is None:
        raise HTTPException(404, "payee not on this account")
    return execute_payment(conn, sess, "transfer", body.payee_id, None, body.amount_paise)


@app.post("/api/merchant/pay", status_code=202)
def merchant_pay(body: MerchantPayBody, sess=Depends(current_session), conn=Depends(get_db)):
    if body.currency != "INR":
        raise HTTPException(422, "only INR is supported")
    merchant = conn.execute("SELECT category FROM merchants WHERE merchant_id = ?",
                            (body.merchant_id,)).fetchone()
    if merchant is None:
        raise HTTPException(404, "unknown merchant")
    return execute_payment(conn, sess, "merchant_payment", body.merchant_id, merchant["category"],
                           body.amount_paise)
