"""Fake predict() and rank_reasons() (K9), same shapes as kya/interfaces.py.

They let the gate, policy and replay run before Prachi's models exist. The
numbers are fixed per kind of session, so a decision is easy to predict in a
demo or a test. Model version "fake-0" in every output says so plainly.
"""

from kya.reason_codes import GROUP_ORDER, reason

MODEL_VERSION = "fake-0"


def predict(features, identity_state="undeclared"):
    """Fixed outputs: a verified agent looks like an LLM agent, a session with
    no behaviour looks like a script, anything else looks human."""
    if identity_state == "verified":
        probs, p = {"human": 0.03, "scripted_bot": 0.05, "llm_agent": 0.92}, 0.005
    elif features.get("n_behaviour_events", 0) == 0:
        probs, p = {"human": 0.05, "scripted_bot": 0.80, "llm_agent": 0.15}, 0.05
    else:
        probs, p = {"human": 0.90, "scripted_bot": 0.05, "llm_agent": 0.05}, 0.002
    # With the plan's cost rule these allow payments up to about Rs 14,000
    # (human), Rs 5,700 (verified agent) and Rs 570 (no behaviour at all).
    return {"class_probs": probs, "p_fraud": p, "contribs": {"actor": {}, "risk": {}}}


def rank_reasons(contribs, policy_codes, extra_codes=()):
    """Policy codes first (in the order given), then the rest by group order.
    Never empty: R00 when nothing else applies."""
    out, seen = [], set()
    for code in list(policy_codes):
        if code not in seen:
            out.append(reason(code)); seen.add(code)
    rest = [c for c in extra_codes if c not in seen]
    rest.sort(key=lambda c: GROUP_ORDER.index(reason(c)["group"]))
    for code in rest:
        out.append(reason(code)); seen.add(code)
    return out or [reason("R00")]
