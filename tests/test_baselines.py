"""K12: the three baselines follow the plan's rules exactly."""

from kya.policy.baselines import allow_all, fair, realised_cost, simple_rule


def facts(**over):
    f = {"action_type": "transfer", "amount_paise": 500_000, "new_payee": False, "env_codes": [],
         "identity_state": "undeclared", "mandate_state": "none", "mandate_codes": []}
    f.update(over)
    return f


def test_allow_all():
    assert allow_all(facts(identity_state="invalid"))["action"] == "allow"


def test_simple_rule():
    assert simple_rule(facts())["action"] == "allow"
    assert simple_rule(facts(env_codes=["R20"]))["action"] == "block"          # automated browser
    assert simple_rule(facts(env_codes=["R21"]))["action"] == "block"          # API with no page
    assert simple_rule(facts(new_payee=True, amount_paise=1_500_000))["action"] == "hold"
    assert simple_rule(facts(new_payee=True, amount_paise=900_000))["action"] == "allow"
    assert simple_rule(facts(identity_state="invalid"))["action"] == "allow"   # it knows nothing of signatures


def test_fair_uses_our_hard_rules():
    assert fair(facts(identity_state="invalid"))["action"] == "block"
    assert fair(facts(identity_state="replayed"))["action"] == "block"
    assert fair(facts(mandate_state="violated", mandate_codes=["R11"])) == {"action": "hold", "policy_codes": ["R11"]}
    assert fair(facts(identity_state="unknown_agent"))["action"] == "step_up"
    assert fair(facts(new_payee=True, amount_paise=1_500_000))["action"] == "hold"
    assert fair(facts(env_codes=["R20"]))["action"] == "allow"                 # automation alone is not fraud


def test_read_only_is_always_allowed():
    for policy in (simple_rule, fair):
        assert policy(facts(action_type="statement_download", env_codes=["R21"]))["action"] == "allow"


def test_realised_cost_matches_the_brief():
    assert realised_cost("allow", True, 1_000_00) == 0
    assert realised_cost("block", True, 1_000_00) == 500
    assert realised_cost("allow", False, 1_000_00) == 1000      # fraud allowed: the whole amount
    assert realised_cost("step_up", False, 1_000_00) == 300
    assert realised_cost("hold", False, 1_000_00) == 100
    assert realised_cost("block", False, 1_000_00) == 0
