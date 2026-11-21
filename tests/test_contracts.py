"""Contract v1 checks: the sample logs follow the schema, and the validator
rejects malformed input."""

import copy
import json
from pathlib import Path

import pytest

from kya.reason_codes import REASON_CODES, GROUP_ORDER
from kya.schema import SchemaError, evidence_status, validate_events

SAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "samples"


def load(name):
    with open(SAMPLES / name) as f:
        return [json.loads(line) for line in f]


@pytest.mark.parametrize("name", ["human_transfer.jsonl", "signed_agent_merchant.jsonl",
                                  "http_bot_statement.jsonl"])
def test_samples_are_valid(name):
    events = load(name)
    validate_events(events)
    # the last two events are always the transaction and its decision_context
    assert events[-2]["type"] == "transaction"
    assert events[-1]["type"] == "decision_context"
    assert events[-1]["data"]["decision_seq"] == events[-2]["seq"]


def test_evidence_levels():
    assert evidence_status(load("human_transfer.jsonl")) == "sufficient"
    assert evidence_status(load("signed_agent_merchant.jsonl")) == "partial"
    assert evidence_status(load("http_bot_statement.jsonl")) == "partial"
    assert evidence_status(load("http_bot_statement.jsonl")[:2]) == "insufficient"


def test_no_keys_or_passwords_recorded():
    for ev in load("human_transfer.jsonl"):
        if ev["type"] == "keystroke":
            assert set(ev["data"]) == {"target", "key_class", "dwell_ms", "flight_ms"}
        assert ev["data"].get("target") != "login.password"


def test_malformed_input_is_rejected():
    good = load("human_transfer.jsonl")

    with pytest.raises(SchemaError):
        validate_events([])

    bad = copy.deepcopy(good)
    del bad[3]["seq"]
    with pytest.raises(SchemaError):
        validate_events(bad)

    bad = copy.deepcopy(good)
    bad[5]["type"] = "mouse_dance"
    with pytest.raises(SchemaError):
        validate_events(bad)

    bad = copy.deepcopy(good)
    bad[6]["seq"] = bad[5]["seq"]  # seq must strictly increase
    with pytest.raises(SchemaError):
        validate_events(bad)

    bad = copy.deepcopy(good)
    bad[-2]["data"]["amount_paise"] = 2500.0  # rupees as a float, not integer paise
    with pytest.raises(SchemaError):
        validate_events(bad)

    bad = copy.deepcopy(good)
    bad[0]["schema_version"] = 2
    with pytest.raises(SchemaError):
        validate_events(bad)


def test_reason_codes_are_well_formed():
    for code, (group, text) in REASON_CODES.items():
        assert code.startswith("R") and len(code) == 3
        assert group in GROUP_ORDER
        assert text
