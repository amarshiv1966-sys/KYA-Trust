import pytest
from bots import common

ALL_SCENARIOS = ["agent_in_scope_compromise", "agent_legit_merchant", "agent_out_of_scope",
                 "agent_prompt_injection", "bot_malicious_transfer", "bot_mule", "bot_read_statement",
                 "bot_signed_billpay", "human_app_scam", "human_high_value", "human_new_payee",
                 "human_normal_transfer", "human_takeover", "unseen_attack"]


@pytest.mark.parametrize("name", ALL_SCENARIOS)
def test_scenario_families_exist_in_splits(name):
    # a typo in a scenario's family list would silently break the train/test separation
    scn = common.load_scenario(name)
    groups = set(common.load_splits()) | {"volunteers"}
    for fam in scn["families"]:
        assert fam in groups, f"{name}: {fam} not in splits.yaml"


def test_runner_families_exist_in_splits():
    assert set(common.FAMILIES) <= set(common.load_splits())


def test_label_row_is_valid():
    scn = common.load_scenario("bot_malicious_transfer")
    row = common.make_label_row(scn, "http_basic", "s_abc123abc123", 5)
    assert row["split"] == "train" and row["legit"] == 0 and row["channel"] == "api"
    assert list(row) == common.LABEL_COLUMNS


def test_test_only_family_is_test():
    assert common.load_splits()["pw_firefox_family"] == "test"


def test_impossible_row_rejected():
    bad = {"victim": 1, "actor": "scripted_bot", "legit": 0, "typology": "app_scam", "handover_seq": "",
           "authorized": 1, "unseen_framework": 0, "unseen_attack": 0, "group_id": "http_basic", "split": "train"}
    with pytest.raises(AssertionError):
        common.check_row(bad)
