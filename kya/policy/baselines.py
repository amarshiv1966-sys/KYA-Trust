"""The three baselines (K12, plan section 15). Same facts, same output shape
as our policy, so eval scores every policy on exactly the same rows.

    allow_all    allow everything (required by the brief)
    simple_rule  block if the browser says it is automated or there are API
                 calls with no page activity; hold a new payee over Rs 10,000;
                 otherwise allow (required by the brief)
    fair         OUR hard rules (signature, replay, mandate, unknown agent),
                 plus hold a new payee over Rs 10,000; otherwise allow.
                 The headline comparison is our policy against this one:
                 beating allow-all proves little.

Each takes the dict from kya.score.session_facts() and returns
{"action", "policy_codes"}.
"""

NEW_PAYEE_LIMIT_PAISE = 10_000 * 100


def allow_all(f):
    return {"action": "allow", "policy_codes": []}


def simple_rule(f):
    if f["action_type"] == "statement_download":
        return {"action": "allow", "policy_codes": []}
    if "R20" in f["env_codes"] or "R21" in f["env_codes"]:
        return {"action": "block", "policy_codes": [c for c in f["env_codes"] if c in ("R20", "R21")]}
    if f["new_payee"] and f["amount_paise"] > NEW_PAYEE_LIMIT_PAISE:
        return {"action": "hold", "policy_codes": ["R14"]}
    return {"action": "allow", "policy_codes": []}


def fair(f):
    if f["action_type"] == "statement_download":
        return {"action": "allow", "policy_codes": []}
    if f["identity_state"] == "invalid":
        return {"action": "block", "policy_codes": ["R01"]}
    if f["identity_state"] == "replayed":
        return {"action": "block", "policy_codes": ["R02"]}
    if f["mandate_state"] in ("violated", "expired"):
        return {"action": "hold", "policy_codes": list(f["mandate_codes"]) or ["R12"]}
    if f["identity_state"] == "unknown_agent" or f["mandate_state"] == "unverifiable":
        return {"action": "step_up", "policy_codes": ["R41"] if f["identity_state"] == "unknown_agent" else []}
    if f["new_payee"] and f["amount_paise"] > NEW_PAYEE_LIMIT_PAISE:
        return {"action": "hold", "policy_codes": ["R14"]}
    return {"action": "allow", "policy_codes": []}


BASELINES = {"allow_all": allow_all, "simple_rule": simple_rule, "fair": fair}


def realised_cost(action, legit, amount_paise, costs=None):
    """Rupees this decision cost, given the TRUE label (the brief's matrix).
    Legit: fixed friction cost. Fraud: the share of the amount that is lost."""
    from kya.policy.engine import RULES
    c = (costs or RULES["costs"])[action]
    return float(c["legit"]) if legit else c["fraud_share"] * amount_paise / 100
