"""Intent features: is THIS payment risky for THIS customer? (transaction, history, provenance, mandate facts)

Uses the transaction event and the decision_context data (context). All floats.
"""
import math

COLD_START_MIN = 5                 # fewer past payments than this -> population values + R34
POP_MEDIAN_PAISE = 150000          # population median payment (Rs 1,500), same scale as history_gen
POP_MAD_PAISE = 150000
MIN_SPREAD_PAISE = 10000           # floor so a tiny spread cannot blow up the z-score
IST_OFFSET_S = 19800


def find_transaction(events):
    tx = [e for e in events if e["type"] == "transaction"]
    return tx[-1] if tx else None


def intent_features(events, context):
    f = {}
    tx = find_transaction(events)
    if tx is None:
        return f
    d = tx["data"]
    ctx = context or {}
    hist = ctx.get("history") or {}
    prov = ctx.get("provenance") or {}
    mandate = ctx.get("mandate")

    # ---- the payment itself
    amount = d["amount_paise"]
    f["amount_inr"] = amount / 100.0                          # size of the payment
    f["amount_log"] = math.log1p(amount / 100.0)              # size on a log scale
    f["new_payee"] = 1.0 if d["new_payee"] else 0.0           # first payment to this payee
    for a in ("transfer", "merchant_payment", "add_payee", "statement_download"):
        f["action_" + a] = 1.0 if d["action"] == a else 0.0   # which kind of action

    # ---- history of this customer
    count = hist.get("payment_count", 0)
    cold = count < COLD_START_MIN
    f["hist_count"] = float(count)                            # how much history exists
    f["hist_cold_start"] = 1.0 if cold else 0.0               # too little history to trust (R34)
    median = POP_MEDIAN_PAISE if cold else hist.get("median_amount_paise", POP_MEDIAN_PAISE)
    mad = POP_MAD_PAISE if cold else hist.get("mad_amount_paise", POP_MAD_PAISE)
    spread = max(1.4826 * mad, 0.25 * median, MIN_SPREAD_PAISE)
    f["amount_z"] = (amount - median) / spread                # how unusual vs this customer's normal (R31)
    f["amount_ratio"] = amount / median if median else 0.0    # amount as a multiple of the usual
    f["payee_seen_before"] = 1.0 if d["payee_id"] in (hist.get("payees_seen") or []) else 0.0
    cat = d["merchant_category"]
    f["category_never_used"] = 1.0 if (cat and cat not in (hist.get("categories_seen") or [])) else 0.0   # (R33)
    last = hist.get("last_payment_ts_ms")
    f["hours_since_last_payment"] = (tx["server_ts_ms"] - last) / 3.6e6 if last else -1.0

    # ---- time
    ist_hour = int(((tx["server_ts_ms"] / 1000) + IST_OFFSET_S) // 3600) % 24
    f["hour_ist"] = float(ist_hour)                           # hour of day, India time
    f["night_payment"] = 1.0 if ist_hour < 5 else 0.0
    login = [e for e in events if e["type"] == "api_call" and e["data"]["path"] == "/api/login"]
    start = login[0]["server_ts_ms"] if login else events[0]["server_ts_ms"]
    f["secs_login_to_payment"] = (tx["server_ts_ms"] - start) / 1000.0   # payment right after login is a risk (R32)

    # ---- provenance
    f["device_accounts_before"] = float(prov.get("device_accounts_before", 0))   # device used on many accounts (R40)
    agent = prov.get("agent")
    f["agent_present"] = 1.0 if agent else 0.0
    f["agent_past_incidents"] = float(agent["past_incidents"]) if agent else 0.0  # (R41)

    # ---- mandate facts (grouped with prefix mandate_ for the marginal-value rerun)
    f["mandate_present"] = 1.0 if mandate else 0.0
    f["mandate_active"] = 1.0 if (mandate and mandate.get("status") == "active") else 0.0
    f["mandate_payments_today"] = float(mandate["payments_today"]) if mandate else 0.0
    f["mandate_consumed_inr"] = mandate["consumed_paise"] / 100.0 if mandate else 0.0
    return {k: float(v) for k, v in f.items()}
