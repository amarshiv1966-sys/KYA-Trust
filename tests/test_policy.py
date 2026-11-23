"""K11: the policy reads rules.yaml, reproduces the plan's worked example,
puts hard rules first, and caps trust."""

import pytest

from kya.environment.checks import environment_codes
from kya.policy.engine import POLICY_VERSION, RULES, cheapest, decide, expected_costs, trust_score


def test_worked_example_from_the_plan():
    # p = 2%: at Rs 1,000 allowing is cheapest; at Rs 10,000 a step-up is
    c1 = expected_costs(0.02, 1_000)
    assert c1 == pytest.approx({"allow": 20.0, "step_up": 25.6, "hold": 149.0, "block": 490.0})
    assert cheapest(0.02, 1_000) == "allow"
    c2 = expected_costs(0.02, 10_000)
    assert c2 == pytest.approx({"allow": 200.0, "step_up": 79.6, "hold": 167.0, "block": 490.0})
    assert cheapest(0.02, 10_000) == "step_up"


def test_high_risk_goes_to_hold_then_block():
    # Rs 10,000 at 10% risk: hold Rs 235 beats step-up 318, block 450, allow 1,000
    assert cheapest(0.1, 10_000) == "hold"
    # at 50% risk: block Rs 250 beats hold 575
    assert cheapest(0.5, 10_000) == "block"


def test_tie_goes_to_the_less_intrusive_action():
    # p = 0: allow costs 0, nothing is cheaper
    assert cheapest(0.0, 1_000_000) == "allow"


def test_hard_rules_come_first():
    args = dict(p_fraud=0.0, amount_paise=100, evidence_status="sufficient", action_type="transfer")
    assert decide("invalid", "within", **args)["action"] == "block"
    assert decide("replayed", "within", **args)["action"] == "block"
    assert decide("verified", "violated", mandate_codes=["R11"], **args) == \
        {"action": "hold", "policy_codes": ["R11"], "trust_cap": "R11"}
    assert decide("unknown_agent", "none", **args)["action"] == "step_up"
    low = dict(args, evidence_status="insufficient")
    assert decide("undeclared", "none", **low)["policy_codes"] == ["R50"]
    assert decide("verified", "within", **low)["action"] == "allow"     # identity stands in for behaviour


def test_trust_caps():
    assert trust_score(0.01, None) == (99, 99)
    assert trust_score(0.01, "R01") == (99, RULES["trust_caps"]["block"])
    assert trust_score(0.01, "R11") == (99, RULES["trust_caps"]["hold"])
    assert trust_score(0.01, "R50") == (99, RULES["trust_caps"]["step_up"])


def test_version_comes_from_the_file():
    assert POLICY_VERSION == RULES["version"] == "p-1"


def ev(source, type_, webdriver=None):
    return {"source": source, "type": type_, "client": {"webdriver": webdriver}}


def test_environment_codes():
    assert environment_codes([ev("server", "api_call"), ev("client", "click", webdriver=True)]) == ["R20"]
    assert environment_codes([ev("server", "api_call"), ev("server", "api_call")]) == ["R21"]
    assert environment_codes([ev("server", "api_call"), ev("client", "click", webdriver=False)]) == []
