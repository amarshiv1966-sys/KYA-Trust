"""Checks that a list of events follows docs/schema.md v1.

Malformed input raises SchemaError (the API returns an error, not a decision).
Sparse input is fine: evidence_status() says how much behaviour was seen.
"""

SCHEMA_VERSION = 1

REQUIRED_FIELDS = ["schema_version", "session_id", "event_id", "seq", "client_ts_ms",
                   "server_ts_ms", "type", "source", "page", "client", "data"]

EVENT_TYPES = ["page_view", "click", "keystroke", "form_submit", "api_call", "transaction",
               "pointer_move", "scroll", "decision_context"]

BEHAVIOUR_TYPES = ["click", "keystroke", "pointer_move"]


class SchemaError(ValueError):
    pass


def validate_events(events):
    """Raise SchemaError if the events are malformed. Returns None if they are fine."""
    if not isinstance(events, list) or len(events) == 0:
        raise SchemaError("events must be a non-empty list")

    last_seq = 0
    session_id = None
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise SchemaError(f"event {i} is not an object")
        for field in REQUIRED_FIELDS:
            if field not in ev:
                raise SchemaError(f"event {i} is missing '{field}'")
        if ev["schema_version"] != SCHEMA_VERSION:
            raise SchemaError(f"event {i} has schema_version {ev['schema_version']}, expected {SCHEMA_VERSION}")
        if ev["type"] not in EVENT_TYPES:
            raise SchemaError(f"event {i} has unknown type '{ev['type']}'")
        if not isinstance(ev["seq"], int) or ev["seq"] <= last_seq:
            raise SchemaError(f"event {i}: seq must be an integer and strictly increasing")
        last_seq = ev["seq"]
        if session_id is None:
            session_id = ev["session_id"]
        elif ev["session_id"] != session_id:
            raise SchemaError(f"event {i} belongs to another session")

        if ev["type"] == "transaction":
            data = ev["data"]
            for field in ["action", "amount_paise", "currency"]:
                if field not in data:
                    raise SchemaError(f"transaction event {i} is missing '{field}'")
            # bool is a subclass of int in Python, so rule it out explicitly
            if not isinstance(data["amount_paise"], int) or isinstance(data["amount_paise"], bool):
                raise SchemaError(f"transaction event {i}: amount_paise must be an integer")


def evidence_status(events):
    """How much behaviour the session shows: insufficient, partial or sufficient."""
    behaviour = sum(1 for ev in events if ev["type"] in BEHAVIOUR_TYPES)
    api_calls = sum(1 for ev in events if ev["type"] == "api_call")
    if behaviour == 0 and api_calls < 3:
        return "insufficient"
    if 0 < behaviour < 20:
        return "partial"
    if behaviour == 0:
        # API-only session with several calls: request timing is the evidence
        return "partial"
    return "sufficient"
