"""score_session(events) -> decision. The single entry point (plan section 4).

The same function runs in four places: the live payment gate, POST /score,
the offline replay (python -m kya.replay) and the evaluation script. It only
reads its input. It never touches the bank's database, so a replay cannot
change anything.

Steps, in order:
  1. validate the input (malformed -> SchemaError, no decision)
  2. find the decision: the last transaction event (or the one asked for),
     cut the events at it, and take its decision_context
  3. identity: re-verify the request signature from the raw headers in the
     log, using the agent key frozen in the context
  4. mandate: check the token against the payment and the frozen counters
  5. features -> model (fake for now) -> policy -> reasons
Everything time-related uses the times in the log, never the clock, so the
same log gives the same answer today and next month. Only latency_ms differs.
"""

import time

import jwt

from kya.features import build_features
from kya.fusion import fake
from kya.identity.mandates import verify_mandate
from kya.identity.signing import verify_request
from kya.policy.engine import POLICY_VERSION, decide, trust_score
from kya.schema import SCHEMA_VERSION, SchemaError, evidence_status, validate_events


def _headers_of(api_call):
    h = api_call["data"]["headers"]
    return {"signature-input": h.get("signature_input"), "signature": h.get("signature"),
            "content-digest": h.get("content_digest"), "kya-mandate": h.get("kya_mandate"),
            "kya-mandate-id": h.get("kya_mandate_id")}


def check_identity(api_call, context):
    """The signature, re-verified from the log. Returns a SignatureCheck."""
    agent = (context.get("provenance") or {}).get("agent") if context else None
    frozen = {agent["agent_id"]: agent["public_key"]} if agent else {}
    d = api_call["data"]
    sig = verify_request(d["method"], d["path"], d["query"], _headers_of(api_call),
                         lookup_key=frozen.get, now_ms=api_call["server_ts_ms"],
                         digest_ok=d.get("content_digest_ok"))
    if sig.state == "verified" and context and context.get("nonce_reused"):
        sig.state, sig.codes, sig.detail = "replayed", ["R02"], "this signed request was already used"
    return sig


def check_mandate(sig, tx, context):
    """The mandate, only when a verified agent presented one."""
    if not sig.mandate_token:
        return None
    if sig.state not in ("verified", "unknown_agent"):
        return None  # the signature already failed; that decides
    try:
        claimed = jwt.decode(sig.mandate_token, options={"verify_signature": False}).get("mandate_id")
    except jwt.InvalidTokenError:
        claimed = None
    m = context.get("mandate") or {}
    usage = {"revoked": m.get("status") == "revoked", "consumed_paise": m.get("consumed_paise", 0),
             "payments_today": m.get("payments_today", 0)}
    d = tx["data"]
    result = verify_mandate(
        sig.mandate_token, context.get("issuer_public_key"), now_ms=tx["server_ts_ms"], usage=usage,
        request={"agent_id": sig.agent_id, "account_id": context.get("account_id"), "action": d["action"],
                 "payee_id": d["payee_id"], "merchant_category": d["merchant_category"],
                 "amount_paise": d["amount_paise"], "currency": d["currency"]})
    if result.state != "unverifiable" and claimed != sig.mandate_id:
        result.state, result.codes, result.detail = "unverifiable", [], "mandate id header does not match the token"
    return result


def score_session(events, decision_seq=None):
    started = time.perf_counter()
    validate_events(events)

    txs = [e for e in events if e["type"] == "transaction"]
    if decision_seq is not None:
        txs = [e for e in txs if e["seq"] == decision_seq]
        if not txs:
            raise SchemaError(f"no transaction event at seq {decision_seq}")
    tx = txs[-1] if txs else None

    if tx is None:
        # read-only session: scored once, at its last event, always allowed
        cut, context, action_type = events, None, "statement_download"
        decision_seq = events[-1]["seq"]
    else:
        decision_seq = tx["seq"]
        cut = [e for e in events if e["seq"] <= decision_seq]
        ctx_events = [e for e in events if e["type"] == "decision_context"
                      and e["data"].get("decision_seq") == decision_seq]
        context = ctx_events[0]["data"] if ctx_events else None
        action_type = tx["data"]["action"]

    evidence = evidence_status(cut)

    identity_state, mandate_state, mandate_codes, extra = "undeclared", "none", [], []
    if tx is not None:
        calls = [e for e in cut if e["seq"] == tx["data"].get("api_call_seq") and e["type"] == "api_call"]
        if calls:
            sig = check_identity(calls[0], context or {})
            identity_state = sig.state
            if context is not None:
                m = check_mandate(sig, tx, context)
                if m is not None:
                    mandate_state, mandate_codes = m.state, m.codes
                    if m.state == "within" and identity_state == "verified":
                        extra.append("R60")

    features = build_features(cut, context)
    model = fake.predict(features, identity_state)
    amount = tx["data"]["amount_paise"] if tx else 0
    policy = decide(identity_state, mandate_state, model["p_fraud"], amount, evidence, action_type,
                    mandate_codes=mandate_codes)
    if evidence != "sufficient" and "R50" not in policy["policy_codes"] and identity_state != "verified":
        extra.append("R50")
    reasons = fake.rank_reasons(model["contribs"], policy["policy_codes"], extra)
    base, score = trust_score(model["p_fraud"], policy["trust_cap"])
    agent_class = max(model["class_probs"], key=model["class_probs"].get)

    return {
        "session_id": events[0]["session_id"],
        "decision_seq": decision_seq,
        "agent_class": agent_class,
        "class_probs": model["class_probs"],
        "p_fraud": model["p_fraud"],
        "base_trust": base,
        "trust_score": score,
        "trust_cap": policy["trust_cap"],
        "action": policy["action"],
        "reason_codes": reasons,
        "identity_state": identity_state,
        "mandate_state": mandate_state,
        "evidence_status": evidence,
        "schema_version": SCHEMA_VERSION,
        "model_version": fake.MODEL_VERSION,
        "policy_version": POLICY_VERSION,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def hold_decision(session_id, decision_seq, why):
    """Fail closed: what the gate returns when scoring itself breaks."""
    return {
        "session_id": session_id, "decision_seq": decision_seq, "agent_class": None, "class_probs": None,
        "p_fraud": None, "base_trust": None, "trust_score": 0, "trust_cap": None, "action": "hold",
        "reason_codes": [{"code": "ERR", "group": "policy", "text": f"Scoring failed, held for review: {why}"}],
        "identity_state": None, "mandate_state": None, "evidence_status": None,
        "schema_version": SCHEMA_VERSION, "model_version": fake.MODEL_VERSION,
        "policy_version": POLICY_VERSION, "latency_ms": None,
    }
