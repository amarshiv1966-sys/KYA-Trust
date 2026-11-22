"""The mock bank's API.

Run:  uvicorn bank.backend.app:app --reload

Browser sessions carry the cookie kya_sid. Our pages get it from
/api/session/start before login, so the login page's own behaviour lands in
the same session. API-only clients send the id in the header X-KYA-Session
(the login response returns it).

Every request with a known session is written to the session's timeline as an
api_call event (bank/backend/ingest.py), and telemetry.js sends its batches to
the WebSocket /ws/telemetry.

For now transfers and merchant payments go straight to the ledger. In K9 the
payment gate replaces execute_payment(): score first, then commit.
"""

import csv
import io
import secrets

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from bank.backend.db import connect, init_db, now_ms
from bank.backend.ingest import ingest_batch, log_api_call
from bank.backend.seed import check_password
from kya.identity.keys import load_issuer_key, public_key_b64
from kya.identity.mandates import issue_mandate
from kya.identity.registry import RegistryError, get_agent, list_agents, register_agent

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


class AgentBody(BaseModel):
    agent_id: str = Field(min_length=3, max_length=50)
    public_key: str = Field(min_length=40, max_length=60)
    issuer: str = Field(min_length=1, max_length=80)


class MandateBody(BaseModel):
    agent_id: str
    merchant_categories: list[str] = Field(default_factory=list, max_length=20)
    payees: list[str] = Field(default_factory=list, max_length=50)
    max_per_txn_paise: int = Field(gt=0, strict=True)
    max_total_paise: int = Field(gt=0, strict=True)
    max_txn_per_day: int = Field(gt=0, le=100, strict=True)
    expiry_days: int = Field(gt=0, le=90, strict=True)


# ---------- who is calling ----------

def session_id_of(request):
    return request.cookies.get(COOKIE) or request.headers.get(HEADER)


def open_session(conn, sid):
    """The session row if it exists and is not logged out (user may be None)."""
    if not sid:
        return None
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ? AND ended_ms IS NULL",
                       (sid,)).fetchone()
    return dict(row) if row else None


async def current_session(request: Request, conn=Depends(get_db)):
    """Find the logged-in session from the cookie or the header, or answer 401.
    Also writes this request to the session's timeline as an api_call event."""
    sid = session_id_of(request)
    row = None
    if sid:
        row = conn.execute(
            "SELECT s.session_id, s.user_id, a.account_id FROM sessions s "
            "JOIN accounts a ON a.user_id = s.user_id "
            "WHERE s.session_id = ? AND s.ended_ms IS NULL", (sid,)).fetchone()
    if row is None:
        raise HTTPException(401, "not logged in" if not sid else "session expired or unknown")
    sess = dict(row)
    log_api_call(sess["session_id"], request, await request.body())
    return sess


async def logged_if_session(request: Request, conn=Depends(get_db)):
    """For endpoints that don't need a login: still log the call if the
    caller has a session."""
    sess = open_session(conn, session_id_of(request))
    if sess:
        log_api_call(sess["session_id"], request, await request.body())
    return sess


# ---------- login ----------

@app.post("/api/session/start")
async def session_start(request: Request, response: Response, conn=Depends(get_db)):
    """Our pages call this on load: reuse the open session, or start an
    anonymous one (no user yet) so telemetry has somewhere to go."""
    sess = open_session(conn, request.cookies.get(COOKIE))
    if sess is None:
        sid = new_session_id()
        device_id = request.cookies.get("kya_dev")
        conn.execute("INSERT INTO sessions VALUES (?, NULL, ?, ?, ?, NULL)",
                     (sid, device_id, "browser" if device_id else "api", now_ms()))
        response.set_cookie(COOKIE, sid, httponly=True, samesite="strict")
    else:
        sid = sess["session_id"]
    log_api_call(sid, request, await request.body())
    return {"session_id": sid}


@app.post("/api/login")
async def login(body: LoginBody, request: Request, response: Response, conn=Depends(get_db)):
    # an anonymous session from /api/session/start becomes this user's session,
    # so the typing on the login page stays in the same timeline
    sess = open_session(conn, session_id_of(request))
    if sess and sess["user_id"] is None:
        log_api_call(sess["session_id"], request, await request.body())

    user = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
    if user is None or not check_password(body.password, user["password_hash"]):
        raise HTTPException(401, "wrong username or password")

    if sess and sess["user_id"] is None:
        sid = sess["session_id"]
        conn.execute("UPDATE sessions SET user_id = ? WHERE session_id = ?", (user["user_id"], sid))
    else:
        # our own pages send the device cookie; anything else counts as an API client
        device_id = request.cookies.get("kya_dev")
        sid = new_session_id()
        conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, NULL)",
                     (sid, user["user_id"], device_id, "browser" if device_id else "api", now_ms()))
        log_api_call(sid, request, await request.body())
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
def list_merchants(sess=Depends(logged_if_session), conn=Depends(get_db)):
    rows = conn.execute("SELECT merchant_id, name, category FROM merchants ORDER BY name").fetchall()
    return {"merchants": [dict(r) for r in rows]}


# ---------- agents and mandates (K8) ----------

@app.get("/api/issuer-key")
def issuer_key():
    """The bank's public mandate-issuer key, so anyone can check a mandate."""
    return {"issuer": "kya-bank", "alg": "EdDSA", "public_key": public_key_b64(load_issuer_key())}


@app.get("/api/agents")
def agents(sess=Depends(logged_if_session), conn=Depends(get_db)):
    return {"agents": list_agents(conn)}


@app.post("/api/agents", status_code=201)
def add_agent(body: AgentBody, sess=Depends(logged_if_session), conn=Depends(get_db)):
    """An agent's developer registers its public key. This grants nothing by
    itself: only a customer's mandate gives an agent any authority."""
    try:
        agent = register_agent(conn, body.agent_id, body.public_key, body.issuer)
    except RegistryError as err:
        raise HTTPException(409 if "already" in str(err) else 422, str(err)) from None
    return {"agent_id": agent["agent_id"], "issuer": agent["issuer"]}


def mandate_status(row, now):
    if row["revoked"]:
        return "revoked"
    return "expired" if now >= row["expires_ms"] else "active"


@app.get("/api/mandates")
def my_mandates(sess=Depends(current_session), conn=Depends(get_db)):
    now = now_ms()
    rows = conn.execute("SELECT * FROM mandates WHERE user_id = ? ORDER BY created_ms DESC",
                        (sess["user_id"],)).fetchall()
    out = []
    for r in rows:
        claims = jwt_claims(r["token"])
        out.append({"mandate_id": r["mandate_id"], "agent_id": r["agent_id"], "status": mandate_status(r, now),
                    "consumed_paise": r["consumed_paise"], "max_total_paise": r["max_total_paise"],
                    "max_per_txn_paise": claims["max_per_txn_paise"], "max_txn_per_day": claims["max_txn_per_day"],
                    "merchant_categories": claims["merchant_categories"], "payees": claims["payees"],
                    "expires_ms": r["expires_ms"], "token": r["token"]})
    return {"mandates": out}


def jwt_claims(token):
    # our own token from our own table: reading the claims needs no check here
    return jwt.decode(token, options={"verify_signature": False})


@app.post("/api/mandates", status_code=201)
def new_mandate(body: MandateBody, sess=Depends(current_session), conn=Depends(get_db)):
    """The logged-in customer gives one agent a limited permission. The bank
    signs it with its issuer key; the agent cannot make or widen one itself."""
    if get_agent(conn, body.agent_id) is None:
        raise HTTPException(404, "unknown agent")
    if not body.merchant_categories and not body.payees:
        raise HTTPException(422, "choose at least one category or payee")
    if body.max_per_txn_paise > body.max_total_paise:
        raise HTTPException(422, "the per-payment limit cannot be above the total")
    known_cats = {r[0] for r in conn.execute("SELECT DISTINCT category FROM merchants")}
    if set(body.merchant_categories) - known_cats:
        raise HTTPException(422, "unknown merchant category")
    merchants = {r[0] for r in conn.execute("SELECT merchant_id FROM merchants")}
    own_payees = {r[0] for r in conn.execute("SELECT payee_id FROM payees WHERE account_id = ?",
                                             (sess["account_id"],))}
    if set(body.payees) - merchants - own_payees:
        raise HTTPException(422, "payee is not a merchant or one of your payees")
    actions = []
    if body.merchant_categories or set(body.payees) & merchants:
        actions.append("merchant_payment")
    if set(body.payees) & own_payees:
        actions.append("transfer")
    mandate_id, token, claims = issue_mandate(
        user_id=sess["user_id"], account_id=sess["account_id"], agent_id=body.agent_id, actions=actions,
        payees=body.payees, merchant_categories=body.merchant_categories,
        max_per_txn_paise=body.max_per_txn_paise, max_total_paise=body.max_total_paise,
        max_txn_per_day=body.max_txn_per_day, expires_in_s=body.expiry_days * 86_400)
    conn.execute("INSERT INTO mandates (mandate_id, user_id, account_id, agent_id, token, max_total_paise, "
                 "consumed_paise, revoked, expires_ms, created_ms) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
                 (mandate_id, sess["user_id"], sess["account_id"], body.agent_id, token,
                  body.max_total_paise, claims["exp"] * 1000, now_ms()))
    return {"mandate_id": mandate_id, "token": token, "actions": actions, "expires_ms": claims["exp"] * 1000}


@app.post("/api/mandates/{mandate_id}/revoke")
def revoke_mandate(mandate_id: str, sess=Depends(current_session), conn=Depends(get_db)):
    cur = conn.execute("UPDATE mandates SET revoked = 1 WHERE mandate_id = ? AND user_id = ?",
                       (mandate_id, sess["user_id"]))
    if cur.rowcount == 0:
        raise HTTPException(404, "no such mandate on your account")
    return {"mandate_id": mandate_id, "status": "revoked"}


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


# ---------- telemetry ----------

@app.websocket("/ws/telemetry")
async def telemetry(ws: WebSocket):
    """telemetry.js sends {"batch_id": ..., "events": [...]} and waits for
    {"ack": batch_id, "kept": n} before a form is submitted."""
    conn = connect()
    try:
        sess = open_session(conn, ws.cookies.get(COOKIE))
    finally:
        conn.close()
    if sess is None:
        await ws.close(code=4401)  # no session: call /api/session/start first
        return
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_json()
            kept = ingest_batch(sess["session_id"], msg.get("events") if isinstance(msg, dict) else None)
            await ws.send_json({"ack": msg.get("batch_id") if isinstance(msg, dict) else None, "kept": kept})
    except WebSocketDisconnect:
        pass
