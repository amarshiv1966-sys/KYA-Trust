import json
import pathlib
import pytest
from kya.features import build_features, evidence_status, cut_at_decision

SAMPLES = pathlib.Path(__file__).resolve().parent.parent / "contracts" / "samples"


def load(name):
    events = [json.loads(l) for l in open(SAMPLES / name)]
    ctx = [e for e in events if e["type"] == "decision_context"]
    return events, (ctx[0]["data"] if ctx else None)


@pytest.mark.parametrize("name,status", [
    ("human_transfer.jsonl", "sufficient"),
    ("signed_agent_merchant.jsonl", "partial"),
    ("http_bot_statement.jsonl", "partial"),
])
def test_features_run_and_evidence(name, status):
    events, ctx = load(name)
    f = build_features(events, ctx)
    assert all(isinstance(v, float) for v in f.values())
    assert evidence_status(cut_at_decision(events)) == status


def test_human_vs_agent_signals():
    h, hc = load("human_transfer.jsonl")
    a, ac = load("signed_agent_merchant.jsonl")
    fh, fa = build_features(h, hc), build_features(a, ac)
    assert fh["click_exact_centre_frac"] < fa["click_exact_centre_frac"]
    assert fa["env_webdriver"] == 1.0 and fh["env_webdriver"] == 0.0
    assert fh["n_keystrokes"] > 0


def test_cut_drops_later_events():
    events, ctx = load("human_transfer.jsonl")
    tx_seq = [e for e in events if e["type"] == "transaction"][0]["seq"]
    assert max(e["seq"] for e in cut_at_decision(events)) == tx_seq


def test_no_events_after_cut_used():
    events, ctx = load("http_bot_statement.jsonl")
    assert build_features(events, ctx)["api_only"] == 1.0
