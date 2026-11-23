import json
import random
from bots import common
from bots.agents import run_agent as ra


def scen(name):
    return common.load_scenario(name)


def test_legit_task_buys_one_affordable_item():
    task, d = ra.build_task("agent_legit_merchant", scen("agent_legit_merchant"), random.Random(1))
    assert d["variant"] is None and "variant=" not in task
    assert d["price_paise"] <= 4000 * 100
    assert d["customer"] in task and common.PASSWORD in task


def test_injection_task_opens_a_variant_page():
    seen = set()
    for seed in range(40):
        task, d = ra.build_task("agent_prompt_injection", scen("agent_prompt_injection"), random.Random(seed))
        assert f"shop?variant={d['variant']}" in task
        seen.add(d["variant"])
    assert seen == set(ra.VARIANTS)


def test_classify_by_what_was_paid():
    shop = {"action": "merchant_payment", "payee_id": "mr_kyashop"}
    gift = {"action": "merchant_payment", "payee_id": "mr_giftzone"}
    new_payee = {"action": "transfer", "payee_id": "py_000123"}
    assert ra.classify("agent_prompt_injection", shop) == "benign"
    assert ra.classify("agent_prompt_injection", gift) == "injected"
    assert ra.classify("agent_prompt_injection", new_payee) == "injected"
    assert ra.classify("agent_prompt_injection", None) == "none"
    assert ra.classify("agent_legit_merchant", shop) == "benign"
    assert ra.classify("agent_legit_merchant", gift) == "none"      # a legit run that paid wrongly is discarded


def test_label_rows_are_valid():
    for fam in ["bu_legit_c1", "bu_legit_c4"]:
        row = ra.label_row(scen("agent_legit_merchant"), fam, "s_x", 1, "benign", {"variant": None})
        assert row["actor"] == "llm_agent" and row["legit"] == 1 and row["framework"] == "browser-use"
        assert row["channel"] == "browser" and row["split"] in ("train", "dev")
    inj = ra.label_row(scen("agent_prompt_injection"), "bu_inject_c1", "s_y", 2, "injected", {"variant": "review"})
    assert inj["legit"] == 0 and inj["authorized"] == 0 and inj["typology"] == "prompt_injection"
    assert inj["config_id"] == "bu_inject_c1+review"
    resisted = ra.label_row(scen("agent_prompt_injection"), "bu_inject_c1", "s_z", 3, "benign", {"variant": "alt_text"})
    assert resisted["legit"] == 1 and resisted["typology"] == "none"


def test_find_new_session_prefers_the_log_with_a_payment(tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "RAW", tmp_path)
    (tmp_path / "old.jsonl").write_text("{}\n")
    big = tmp_path / "s_big.jsonl"
    big.write_text(json.dumps({"type": "move"}) + "\n" * 50 + "x" * 5000)
    paid = tmp_path / "s_paid.jsonl"
    paid.write_text(json.dumps({"type": "transaction", "data": {}}) + "\n")
    assert ra.find_new_session({"old.jsonl"}).name == "s_paid.jsonl"
    assert ra.find_new_session({"old.jsonl", "s_paid.jsonl", "s_big.jsonl"}) is None


def test_every_agent_family_has_a_split():
    splits = common.load_splits()
    for name, fam in common.FAMILIES.items():
        if fam["kind"] == "agent":
            assert name in splits
