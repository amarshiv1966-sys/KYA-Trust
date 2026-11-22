"""decide(): hard rules first, then the lowest expected cost (plan section 10).

K9 version: the numbers are constants here. K11 moves them to rules.yaml,
adds the worked-example test and the reason-code merge.

Expected cost of each action, with p = p_fraud and A = rupees at risk:
    allow    = p * A                     (fraud gets through)
    step_up  = 20 (1 - p) + 0.3 p A      (friction for good customers; some fraud still passes)
    hold     = 150 (1 - p) + 0.1 p A     (a good payment delayed for review)
    block    = 500 (1 - p)               (a good payment refused)
The cheapest wins; on a tie, the less intrusive action wins.
"""

POLICY_VERSION = "p-0"
ADD_PAYEE_EXPOSURE_PAISE = 1_000_000          # Rs 10,000 at risk when a payee is added
ORDER = ["allow", "step_up", "hold", "block"]   # least to most intrusive

# trust caps: a hard rule limits how high trust_score can be
CAP_BLOCK, CAP_HOLD, CAP_STEP_UP = 5, 20, 40


def expected_costs(p, amount_rupees):
    a = amount_rupees
    return {
        "allow": p * a,
        "step_up": 20 * (1 - p) + 0.3 * p * a,
        "hold": 150 * (1 - p) + 0.1 * p * a,
        "block": 500 * (1 - p),
    }


def cheapest(p, amount_rupees):
    costs = expected_costs(p, amount_rupees)
    return min(ORDER, key=lambda act: (round(costs[act], 9), ORDER.index(act)))


def decide(identity_state, mandate_state, p_fraud, amount_paise, evidence_status, action_type,
           mandate_codes=()):
    """Returns {"action", "policy_codes", "trust_cap"} (contract in kya/interfaces.py).

    mandate_codes: the R10-R13 codes verify_mandate found, so a violation
    says exactly which limit was crossed.
    """
    # Read-only actions are never stopped (plan: scored once, always allowed).
    if action_type == "statement_download":
        return {"action": "allow", "policy_codes": [], "trust_cap": None}

    # ---- hard rules, strongest first
    if identity_state == "invalid":
        return {"action": "block", "policy_codes": ["R01"], "trust_cap": "R01"}
    if identity_state == "replayed":
        return {"action": "block", "policy_codes": ["R02"], "trust_cap": "R02"}
    if mandate_state in ("violated", "expired"):
        codes = list(mandate_codes) or (["R10"] if mandate_state == "expired" else ["R12"])
        return {"action": "hold", "policy_codes": codes, "trust_cap": codes[0]}
    if identity_state == "unknown_agent" or mandate_state == "unverifiable":
        # someone claims agent authority we cannot confirm: ask the customer
        return {"action": "step_up", "policy_codes": ["R41"] if identity_state == "unknown_agent" else [],
                "trust_cap": "R41" if identity_state == "unknown_agent" else None}
    verified_in_scope = identity_state == "verified" and mandate_state == "within"
    if evidence_status == "insufficient" and not verified_in_scope:
        # too little behaviour to judge who is acting; a verified agent inside
        # its mandate is judged on its identity instead
        return {"action": "step_up", "policy_codes": ["R50"], "trust_cap": "R50"}

    # ---- lowest expected cost
    exposure = ADD_PAYEE_EXPOSURE_PAISE if action_type == "add_payee" else amount_paise
    action = cheapest(p_fraud, exposure / 100)
    return {"action": action, "policy_codes": ["R14"] if action == "step_up" else [], "trust_cap": None}


CAPS = {"R01": CAP_BLOCK, "R02": CAP_BLOCK, "R10": CAP_HOLD, "R11": CAP_HOLD, "R12": CAP_HOLD,
        "R13": CAP_HOLD, "R41": CAP_STEP_UP, "R50": CAP_STEP_UP}


def trust_score(p_fraud, trust_cap):
    base = round(100 * (1 - p_fraud))
    return base, (min(base, CAPS[trust_cap]) if trust_cap else base)
