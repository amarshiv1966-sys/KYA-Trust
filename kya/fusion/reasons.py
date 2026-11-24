"""P8: the fixed feature-to-code table and rank_reasons() (contract in kya/interfaces.py).

Order in a decision: policy codes (as given), then risk codes ranked by Model B's
contribution toward fraud, then actor codes ranked by Model A's contribution toward the
chosen class, then evidence codes. Contributions are only used to order codes; they are
never shown as numbers. Never empty: R00 when nothing else applies.
"""
from kya.reason_codes import reason

# feature (whole session or its w10_ copy) -> actor code
ACTOR_CODES = {
    "env_webdriver": "R20", "env_no_browser": "R20",
    "api_only": "R21", "api_no_page_frac": "R21", "api_per_page_view": "R21",
    "gap_cv": "R22", "api_gap_cv": "R22", "click_interval_cv": "R22", "n_bursts": "R22",
    "click_exact_centre_frac": "R23", "click_offset_mean": "R23", "click_no_press_frac": "R23",
    "llm_pause_then_exact": "R24", "idle_fraction": "R24", "first_action_delay_ms": "R24",
    "fields_without_keys": "R25", "no_key_fill_frac": "R25", "whole_form_at_once": "R25",
    "api_signed_frac": "R60",
}

# Model B feature -> risk code
RISK_CODES = {
    "new_payee": "R30", "payee_seen_before": "R30",
    "amount_ratio": "R31", "amount_z": "R31",
    "secs_login_to_payment": "R32",
    "category_never_used": "R33",
    "device_accounts_before": "R40",
    "agent_past_incidents": "R41",
}

# evidence codes are added from facts, not from contributions
EVIDENCE_FEATURES = {"hist_cold_start": "R34"}

# R60 only makes sense when the agent is verified and inside its mandate
NEEDS_VERIFIED = {"R60"}


def code_for(feature, table):
    return table.get(feature[4:] if feature.startswith("w10_") else feature, table.get(feature))


def ranked(contribs, table):
    """Codes ordered by their largest positive contribution, each code once."""
    best = {}
    for feature, value in (contribs or {}).items():
        code = code_for(feature, table)
        if code and value > 0:
            best[code] = max(best.get(code, 0.0), value)
    return sorted(best, key=lambda c: -best[c])


def rank_reasons(contribs, policy_codes, features=None, evidence_status=None, verified_within=False):
    """contribs: {"actor": {...}, "risk": {...}} from predict(). Returns [{"code","group","text"}, ...]."""
    codes = list(dict.fromkeys(policy_codes))
    codes += ranked(contribs.get("risk"), RISK_CODES)
    codes += [c for c in ranked(contribs.get("actor"), ACTOR_CODES)
              if c not in NEEDS_VERIFIED or verified_within]
    for feature, code in EVIDENCE_FEATURES.items():
        if (features or {}).get(feature, 0) > 0:
            codes.append(code)
    if evidence_status == "insufficient":
        codes.append("R50")
    out = [reason(c) for c in dict.fromkeys(codes)]
    return out or [reason("R00")]
