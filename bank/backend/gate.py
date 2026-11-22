"""The payment gate (K9): the only code that moves money or adds a payee.

For every sensitive action:
  1. a repeated Idempotency-Key returns the first answer, nothing runs twice
  2. write the `transaction` event (its seq is the decision_seq)
  3. freeze the bank's state in a `decision_context` event: the mandate's
     counters, the account's history, the device and agent facts, the issuer key
  4. score_session() on the log up to here (read-only, same code as replay)
  5. act on the decision:
       allow    -> commit in one BEGIN IMMEDIATE transaction: re-check the
                   mandate budget and revocation, consume the nonce, write
                   exactly one ledger row, update the counters
       step_up  -> a single-use approval for exactly this payee, amount and
                   currency, valid 5 minutes (confirming it comes later)
       hold / block -> nothing moves
Fail closed: if scoring raises or the commit cannot get the lock, the answer
is hold, never allow.
"""

import json
import secrets
import sqlite3
import statistics

import jwt
from fastapi import HTTPException

from bank.backend.db import now_ms
from bank.backend.ingest import LOG, server_event
from kya.identity.keys import load_issuer_key, public_key_b64
from kya.identity.mandates import ist_day_start_ms
from kya.identity.nonces import consume_nonce, nonce_seen
from kya.identity.registry import get_agent
from kya.identity.signing import verify_request
from kya.policy.engine import POLICY_VERSION
from kya.fusion.fake import MODEL_VERSION
from kya.score import hold_decision, score_session

APPROVAL_TTL_MS = 5 * 60 * 1000
STATUS = {"allow": "executed", "step_up": "step_up", "hold": "held", "block": "blocked"}


# ---------- reading the bank's state ----------

def mandate_state(conn, token, at_ms):
    """Counters for the mandate a request presents, or None."""
    if not token:
        return None
    try:
        mandate_id = jwt.decode(token, options={"verify_signature": False}).get("mandate_id")
    except jwt.InvalidTokenError:
        return None
    row = conn.execute("SELECT * FROM mandates WHERE mandate_id = ?", (mandate_id,)).fetchone()
    if row is None:
        return {"mandate_id": mandate_id, "status": "unknown", "consumed_paise": 0, "payments_today": 0}
    today = conn.execute("SELECT COUNT(*) FROM ledger WHERE mandate_id = ? AND ts_ms >= ?",
                         (mandate_id, ist_day_start_ms(at_ms))).fetchone()[0]
    status = "revoked" if row["revoked"] else ("expired" if at_ms >= row["expires_ms"] else "active")
    return {"mandate_id": mandate_id, "status": status, "consumed_paise": row["consumed_paise"],
            "payments_today": today}


def account_history(conn, account_id, session_id):
    """The account's payments before this session."""
    rows = conn.execute(
        "SELECT ts_ms, counterparty, category, -amount_paise AS amt FROM ledger "
        "WHERE account_id = ? AND amount_paise < 0 AND (session_id IS NULL OR session_id != ?) ORDER BY ts_ms",
        (account_id, session_id)).fetchall()
    amounts = [r["amt"] for r in rows]
    median = int(statistics.median(amounts)) if amounts else 0
    mad = int(statistics.median([abs(a - median) for a in amounts])) if amounts else 0
    return {
        "payment_count": len(rows),
        "median_amount_paise": median,
        "mad_amount_paise": mad,
        "payees_seen": sorted({r["counterparty"] for r in rows}),
        "categories_seen": sorted({r["category"] for r in rows if r["category"]}),
        "last_payment_ts_ms": rows[-1]["ts_ms"] if rows else None,
    }


def device_accounts_before(conn, device_id, user_id, at_ms):
    """Other accounts this device logged into before now (earlier activity only)."""
    if not device_id:
        return 0
    return conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM sessions WHERE device_id = ? AND user_id IS NOT NULL "
        "AND user_id != ? AND created_ms < ?", (device_id, user_id, at_ms)).fetchone()[0]


def peek_signature(conn, api_call):
    """Who signed (if anyone) and is the nonce already used. The scorer
    re-verifies everything itself from the log; this only tells the gate
    which agent and nonce to freeze into the context."""
    d = api_call["data"]
    h = d["headers"]

    def registry_key(agent_id):
        agent = get_agent(conn, agent_id)
        return agent["public_key"] if agent else None

    return verify_request(d["method"], d["path"], d["query"],
                          {"signature-input": h.get("signature_input"), "signature": h.get("signature"),
                           "content-digest": h.get("content_digest"), "kya-mandate": h.get("kya_mandate"),
                           "kya-mandate-id": h.get("kya_mandate_id")},
                          lookup_key=registry_key, now_ms=api_call["server_ts_ms"],
                          digest_ok=d.get("content_digest_ok"))


# ---------- the gate ----------

def run_gate(conn, request, sess, *, action, payee_id, category, amount_paise, currency, execute):
    """execute(conn, mandate_id, nonce) does the actual change inside the
    commit transaction and returns a dict for the response."""
    idem = request.headers.get("idempotency-key")
    idem_key = f"{sess['account_id']}:{idem}" if idem else None
    if idem_key:
        row = conn.execute("SELECT response_json FROM idempotency WHERE key = ?", (idem_key,)).fetchone()
        if row:
            return json.loads(row["response_json"])

    sid = sess["session_id"]
    api_call = request.state.api_call
    sig = peek_signature(conn, api_call)
    token = request.headers.get("kya-mandate") if sig.state == "verified" else None
    at = api_call["server_ts_ms"]

    new_payee = conn.execute("SELECT 1 FROM ledger WHERE account_id = ? AND counterparty = ? LIMIT 1",
                             (sess["account_id"], payee_id)).fetchone() is None
    tx = server_event(sid, "transaction", {
        "action": action, "amount_paise": amount_paise, "currency": currency, "payee_id": payee_id,
        "new_payee": new_payee, "merchant_category": category,
        "mandate_token": request.headers.get("kya-mandate"), "mandate_id": request.headers.get("kya-mandate-id"),
        "idempotency_key": idem, "api_call_seq": api_call["seq"],
    }, request)

    agent = get_agent(conn, sig.agent_id) if sig.agent_id else None
    mandate = mandate_state(conn, token, at)
    server_event(sid, "decision_context", {
        "decision_seq": tx["seq"],
        "account_id": sess["account_id"],
        "user_id": sess["user_id"],
        "mandate": mandate,
        "history": account_history(conn, sess["account_id"], sid),
        "provenance": {
            "device_accounts_before": device_accounts_before(conn, request.cookies.get("kya_dev"),
                                                             sess["user_id"], at),
            "agent": ({"agent_id": agent["agent_id"], "public_key": agent["public_key"],
                       "issuer": agent["issuer"], "past_incidents": agent["past_incidents"]} if agent else None),
        },
        "nonce_reused": bool(sig.state == "verified" and nonce_seen(conn, sig.agent_id, sig.nonce)),
        "issuer_public_key": public_key_b64(load_issuer_key()),
        "versions": {"policy_version": POLICY_VERSION, "model_version": MODEL_VERSION},
    }, request)

    try:
        decision = score_session(LOG.read(sid), decision_seq=tx["seq"])
    except Exception as err:  # fail closed
        decision = hold_decision(sid, tx["seq"], type(err).__name__)

    verified = sig.state == "verified" and decision["identity_state"] == "verified"
    nonce = sig.nonce if verified else None
    mandate_id = mandate["mandate_id"] if (verified and mandate) else None
    result = {}

    if decision["action"] == "allow":
        try:
            result = commit(conn, decision, token, mandate_id, sig.agent_id, nonce, amount_paise, execute)
        except sqlite3.OperationalError:  # lock timeout
            decision = hold_decision(sid, tx["seq"], "database busy")
    elif nonce:
        consume_nonce(conn, sig.agent_id, nonce, now_ms())  # a later copy is a replay

    if decision["action"] == "step_up":
        approval_id = "ap_" + secrets.token_hex(6)
        conn.execute("INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, 0)",
                     (approval_id, sid, payee_id, amount_paise, currency, now_ms() + APPROVAL_TTL_MS))
        result["approval_id"] = approval_id

    conn.execute("INSERT OR REPLACE INTO decisions VALUES (?, ?, ?, ?)",
                 (sid, decision["decision_seq"], json.dumps(decision), now_ms()))
    response = {"status": STATUS[decision["action"]], **result, "decision": decision}
    if idem_key:
        conn.execute("INSERT OR IGNORE INTO idempotency VALUES (?, ?, ?)", (idem_key, json.dumps(response), now_ms()))
    return response


def commit(conn, decision, token, mandate_id, agent_id, nonce, amount_paise, execute):
    """One transaction: re-check, consume, write, or nothing at all.
    May change decision["action"] to hold/block if a re-check fails."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if mandate_id:
            claims = jwt.decode(token, options={"verify_signature": False})
            row = conn.execute("SELECT revoked, consumed_paise FROM mandates WHERE mandate_id = ?",
                               (mandate_id,)).fetchone()
            today = conn.execute("SELECT COUNT(*) FROM ledger WHERE mandate_id = ? AND ts_ms >= ?",
                                 (mandate_id, ist_day_start_ms(now_ms()))).fetchone()[0]
            # state may have changed since scoring (revoked, or a parallel payment spent the budget)
            if row is None or row["revoked"] or row["consumed_paise"] + amount_paise > claims["max_total_paise"] \
                    or today + 1 > claims["max_txn_per_day"]:
                conn.execute("ROLLBACK")
                _override(decision, "hold", "R11" if row and not row["revoked"] else "R10")
                return {}
        if nonce and not consume_nonce(conn, agent_id, nonce, now_ms()):
            conn.execute("ROLLBACK")
            _override(decision, "block", "R02")
            return {}
        result = execute(conn, mandate_id, nonce)
        if mandate_id:
            conn.execute("UPDATE mandates SET consumed_paise = consumed_paise + ? WHERE mandate_id = ?",
                         (amount_paise, mandate_id))
        conn.execute("COMMIT")
        return result
    except HTTPException:
        conn.execute("ROLLBACK")
        raise
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def _override(decision, action, code):
    """A re-check inside the commit changed the outcome; say why."""
    from kya.policy.engine import CAPS
    from kya.reason_codes import reason
    decision["action"] = action
    decision["trust_cap"] = code
    decision["trust_score"] = min(decision["trust_score"], CAPS[code])
    decision["reason_codes"] = [reason(code)] + [r for r in decision["reason_codes"] if r["code"] != code]
