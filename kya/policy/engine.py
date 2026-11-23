"""decide(): hard rules first, then the lowest expected cost (plan section 10).

All numbers come from rules.yaml next to this file.

Expected cost of each action, with p = p_fraud and A = rupees at risk:
    allow    = p * A                     (fraud gets through)
    step_up  = 20 (1 - p) + 0.3 p A      (friction for good customers; some fraud still passes)
    hold     = 150 (1 - p) + 0.1 p A     (a good payment delayed for review)
    block    = 500 (1 - p)               (a good payment refused)
The cheapest wins; on a tie, the less intrusive action wins.
"""

from pathlib import Path

import yaml

RULES_FILE = Path(__file__).with_name("rules.yaml")


def load_rules(path=RULES_FILE):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


RULES = load_rules()
POLICY_VERSION = RULES["version"]
ORDER = RULES["order"]                                   # least to most intrusive
ADD_PAYEE_EXPOSURE_PAISE = RULES["add_payee_exposure_inr"] * 100
CAP_BLOCK = RULES["trust_caps"]["block"]
CAP_HOLD = RULES["trust_caps"]["hold"]
CAP_STEP_UP = RULES["trust_caps"]["step_up"]


def expected_costs(p, amount_rupees):
    return {act: c["legit"] * (1 - p) + c["fraud_share"] * p * amount_rupees
            for act, c in RULES["costs"].items()}


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
