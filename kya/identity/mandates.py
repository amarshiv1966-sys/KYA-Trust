"""Mandates (K8): the customer's signed permission for one agent.

The customer chooses a scope on the bank's "Assistants" page. The bank then
signs a JWT with its ISSUER key (EdDSA only). The agent attaches the token to
its requests, but it cannot change it or make its own: only the bank's key
produces a valid one. Inspired by AP2 mandates; not AP2-compliant.

All amounts are integer paise. The day boundary for max_txn_per_day is
midnight IST.
"""

import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import jwt

from kya.identity.keys import load_issuer_key, public_key_from_b64

ISSUER = "kya-bank"
AUDIENCE = "kya-bank-payments"
ALGORITHM = "EdDSA"
IST = ZoneInfo("Asia/Kolkata")
ACTIONS = ("transfer", "merchant_payment")


def new_mandate_id():
    return "md_" + secrets.token_hex(6)


def ist_day_start_ms(ts_ms):
    """Midnight IST at or before ts_ms, in ms since the epoch."""
    t = datetime.fromtimestamp(ts_ms / 1000, IST)
    return int(t.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def _positive_int(name, value):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def issue_mandate(*, user_id, account_id, agent_id, actions, payees=(), merchant_categories=(),
                  max_per_txn_paise, max_total_paise, max_txn_per_day, expires_in_s,
                  currency="INR", issuer_key=None, now_s=None):
    """Sign a new mandate. Returns (mandate_id, token, claims)."""
    actions = sorted(set(actions))
    if not actions or any(a not in ACTIONS for a in actions):
        raise ValueError(f"actions must be some of {ACTIONS}")
    for name, value in (("max_per_txn_paise", max_per_txn_paise), ("max_total_paise", max_total_paise),
                        ("max_txn_per_day", max_txn_per_day), ("expires_in_s", expires_in_s)):
        _positive_int(name, value)
    if max_per_txn_paise > max_total_paise:
        raise ValueError("max_per_txn_paise cannot be above max_total_paise")
    now_s = int(time.time()) if now_s is None else now_s
    mandate_id = new_mandate_id()
    claims = {
        "iss": ISSUER, "aud": AUDIENCE, "iat": now_s, "exp": now_s + expires_in_s,
        "mandate_id": mandate_id,
        "user_id": user_id, "account_id": account_id, "agent_id": agent_id,
        "actions": actions,
        "payees": sorted(set(payees)),                            # empty = any payee in the categories
        "merchant_categories": sorted(set(merchant_categories)),  # empty = no category limit
        "currency": currency,
        "max_per_txn_paise": max_per_txn_paise,
        "max_total_paise": max_total_paise,
        "max_txn_per_day": max_txn_per_day,
    }
    token = jwt.encode(claims, issuer_key or load_issuer_key(), algorithm=ALGORITHM,
                       headers={"kid": "issuer-1"})
    return mandate_id, token, claims


@dataclass
class MandateCheck:
    state: str                     # a MANDATE_STATES value from kya/interfaces.py
    codes: list = field(default_factory=list)   # policy reason codes found
    claims: dict | None = None     # the decoded mandate, when its signature checked out
    detail: str = ""               # one line for logs and the dashboard


def verify_mandate(token, issuer_public_key_b64, *, request, usage, now_ms):
    """Check a mandate against one payment.

    request: {"agent_id", "account_id", "action", "payee_id",
              "merchant_category" (None for transfers), "amount_paise", "currency"}
             agent_id is the key that signed the request, never a value the
             agent typed into the body.
    usage:   the bank's own counters for this mandate at decision time:
             {"revoked": bool, "consumed_paise": int, "payments_today": int}
    now_ms:  the time to judge expiry at. Live: when the request arrived.
             Replay: the same value from the log, so the answer never changes.

    Order: signature, then expiry and revocation, then binding, then scope.
    """
    if not token:
        return MandateCheck("none")
    try:
        key = public_key_from_b64(issuer_public_key_b64)
        claims = jwt.decode(
            token, key, algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER,
            options={"require": ["exp", "iss", "aud", "mandate_id"], "verify_exp": False},
        )
    except (jwt.InvalidTokenError, ValueError) as err:
        # forged, edited, wrong algorithm, wrong issuer or audience, or not a JWT at all
        return MandateCheck("unverifiable", [], None, f"mandate signature does not check out: {err}")

    if usage.get("revoked"):
        return MandateCheck("expired", ["R10"], claims, "mandate was revoked by the customer")
    if now_ms >= claims["exp"] * 1000:
        return MandateCheck("expired", ["R10"], claims, "mandate has expired")

    # Binding: the mandate must belong to the agent that signed this request
    # and to the account the money leaves. A mandate copied to another agent
    # cannot be checked against the customer's consent.
    if claims.get("agent_id") != request.get("agent_id"):
        return MandateCheck("unverifiable", [], claims, "mandate was issued to a different agent")
    if request.get("account_id") is not None and claims.get("account_id") != request["account_id"]:
        return MandateCheck("unverifiable", [], claims, "mandate is for a different account")

    # Scope: every populated field must match
    codes, why = [], []
    if request.get("action") not in claims.get("actions", []):
        codes.append("R12"); why.append(f"action {request.get('action')} not allowed")
    if request.get("currency") != claims.get("currency"):
        codes.append("R12"); why.append("currency differs")
    payees = claims.get("payees") or []
    categories = claims.get("merchant_categories") or []
    if payees and request.get("payee_id") not in payees:
        codes.append("R12"); why.append("payee not on the list")
    if categories and request.get("merchant_category") not in categories:
        codes.append("R12"); why.append("merchant category not allowed")
    amount = request.get("amount_paise")
    if not isinstance(amount, int) or amount > claims["max_per_txn_paise"]:
        codes.append("R11"); why.append("amount above the per-payment limit")
    elif usage.get("consumed_paise", 0) + amount > claims["max_total_paise"]:
        codes.append("R11"); why.append("total budget would be exceeded")
    if usage.get("payments_today", 0) + 1 > claims["max_txn_per_day"]:
        codes.append("R13"); why.append("daily payment count reached")

    if codes:
        return MandateCheck("violated", sorted(set(codes)), claims, "; ".join(why))
    return MandateCheck("within", [], claims, "inside every limit")
