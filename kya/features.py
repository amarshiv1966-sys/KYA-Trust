"""build_features: the function from kya/interfaces.py (Prachi's side of contract v1).

Cuts the session at the decision, then joins behaviour and intent features.
The whole session and the last 10 seconds are both computed (suffix _last10).
"""
from kya.behaviour.features import behaviour_features, BEHAVIOUR_TYPES
from kya.intent.features import intent_features, find_transaction
# one shared definition of evidence_status (docs/schema.md section 4); re-exported here
from kya.schema import evidence_status  # noqa: F401

WINDOW_MS = 10000


def cut_at_decision(events):
    # keep only events up to and including the scored transaction (plan section 2)
    tx = find_transaction(events)
    if tx is None:
        return events
    return [e for e in events if e["seq"] <= tx["seq"]]


def build_features(events, context):
    events = cut_at_decision(events)
    tx = find_transaction(events)
    f = behaviour_features(events)
    if tx is not None:
        recent = [e for e in events if e["server_ts_ms"] >= tx["server_ts_ms"] - WINDOW_MS]
        f.update(behaviour_features(recent, prefix="w10_"))
    f.update(intent_features(events, context))
    f["n_behaviour_events"] = float(sum(e["type"] in BEHAVIOUR_TYPES for e in events))   # how much to judge on
    return f


def device_fields(events):
    # Coarse device fields kept OUT of the model. Only eval/ uses them, for the device-only shortcut check.
    c = events[0]["client"] if events else {}
    return {k: c.get(k) for k in ("device_class", "os_family", "browser_family", "input_type")}
