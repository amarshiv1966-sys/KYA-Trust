"""The session timeline (K6): every event of a session, in the order the server
received it, in data/raw/<session_id>.jsonl.

Two kinds of events come in:
- client events from telemetry.js over the WebSocket (page_view, click, ...)
- server events written by the bank itself (api_call now, transaction and
  decision_context from K9)

The server, never the browser, sets seq, server_ts_ms, session_id, source and
schema_version. Client events are cleaned to the fields in docs/schema.md, so
nothing else (typed text, page content) can reach the log.
"""

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = 1
MAX_BATCH_EVENTS = 500

# Fields a client may send for each event type. Anything else is dropped.
CLIENT_FIELDS = {
    "page_view": ["from_page", "viewport_w", "viewport_h"],
    "pointer_move": ["points"],
    "click": ["target", "x", "y", "target_w", "target_h", "offset_x", "offset_y", "press_ms"],
    "keystroke": ["target", "key_class", "dwell_ms", "flight_ms"],
    "scroll": ["dx", "dy"],
    "form_submit": ["form", "fields_filled", "fields_without_keys", "paste_count"],
}
CLIENT_KEYS = ["device_id", "device_class", "os_family", "browser_family", "input_type",
               "webdriver", "languages_count", "timezone_offset_min"]
KEY_CLASSES = ["letter", "digit", "space", "backspace", "enter", "tab", "punct", "other"]

# Element ids look like "transfer.amount" (contracts/element_ids.md)
ELEMENT_ID = re.compile(r"^[a-z_]+(\.[a-z0-9_]+)+$")
PAGE_ID = re.compile(r"^[a-z_]+$")
# Secret fields: never any event for these, even if a client sends one
SECRET_TARGETS = {"login.password", "stepup.pin"}

# Request headers kept on api_call events (schema.md, api_call)
KEPT_HEADERS = {
    "user_agent": "user-agent",
    "accept_language": "accept-language",
    "signature_input": "signature-input",
    "signature": "signature",
    "content_digest": "content-digest",
    "kya_mandate_id": "kya-mandate-id",
    "idempotency_key": "idempotency-key",
}
# Body fields that are free text or personal: removed before logging
DROPPED_BODY_FIELDS = {"password", "name", "account_number", "ifsc", "note", "pin"}


def raw_dir():
    return Path(os.environ.get("KYA_RAW_DIR", ROOT / "data" / "raw"))


def now_ms():
    return int(time.time() * 1000)


class EventLog:
    """Appends events to per-session JSONL files with server-assigned seq.

    One lock for the whole log keeps it simple: the bank runs as a single
    process, and an append takes microseconds.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.last_seq = {}      # session_id -> last seq written
        self.seen_ids = {}      # session_id -> event_ids already written (drops retried batches)
        self.last_client = {}   # session_id -> latest client object from telemetry.js

    def path(self, session_id):
        return raw_dir() / f"{session_id}.jsonl"

    def _load(self, session_id):
        # first touch of a session (also after a restart): read what is on disk
        if session_id in self.last_seq:
            return
        last, seen = 0, set()
        p = self.path(session_id)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                for line in f:
                    ev = json.loads(line)
                    last = ev["seq"]
                    seen.add(ev["event_id"])
        self.last_seq[session_id] = last
        self.seen_ids[session_id] = seen

    def append(self, session_id, events):
        """Write events in order. Returns the list actually written (with seq)."""
        written = []
        with self.lock:
            self._load(session_id)
            p = self.path(session_id)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8", newline="\n") as f:
                for ev in events:
                    if ev["event_id"] in self.seen_ids[session_id]:
                        continue  # a retried batch: already written once
                    self.last_seq[session_id] += 1
                    ev["seq"] = self.last_seq[session_id]
                    ev["server_ts_ms"] = now_ms()
                    ev["session_id"] = session_id
                    ev["schema_version"] = SCHEMA_VERSION
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                    self.seen_ids[session_id].add(ev["event_id"])
                    written.append(ev)
        return written

    def read(self, session_id, up_to_seq=None):
        """All events of a session in seq order, optionally only up to a seq."""
        p = self.path(session_id)
        if not p.exists():
            return []
        with open(p, encoding="utf-8") as f:
            events = [json.loads(line) for line in f]
        if up_to_seq is not None:
            events = [e for e in events if e["seq"] <= up_to_seq]
        return events


LOG = EventLog()


# ---------- cleaning client events ----------

def clean_client(client):
    """Keep only the coarse device fields from schema.md section 3."""
    if not isinstance(client, dict):
        return {k: None for k in CLIENT_KEYS}
    return {k: client.get(k) for k in CLIENT_KEYS}


def clean_client_event(ev):
    """Return the event reduced to its allowed fields, or None to drop it."""
    if not isinstance(ev, dict):
        return None
    type_ = ev.get("type")
    if type_ not in CLIENT_FIELDS:
        return None  # clients may not send api_call, transaction or decision_context
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    data = {k: data.get(k) for k in CLIENT_FIELDS[type_]}

    target = data.get("target") or data.get("form")
    if target is not None:
        if not isinstance(target, str) or not ELEMENT_ID.match(target):
            return None  # only allowlisted elements are recorded
        if target in SECRET_TARGETS:
            return None
    if type_ == "keystroke" and data.get("key_class") not in KEY_CLASSES:
        return None
    if type_ == "pointer_move":
        pts = data.get("points")
        if not isinstance(pts, list) or len(pts) > 50:
            return None

    page = ev.get("page")
    if page is not None and (not isinstance(page, str) or not PAGE_ID.match(page)):
        page = None
    event_id = ev.get("event_id")
    if not isinstance(event_id, str) or not (1 <= len(event_id) <= 64):
        return None
    client_ts = ev.get("client_ts_ms")
    if not isinstance(client_ts, int) or isinstance(client_ts, bool):
        client_ts = None

    return {
        "schema_version": SCHEMA_VERSION, "session_id": None, "event_id": event_id,
        "seq": None, "client_ts_ms": client_ts, "server_ts_ms": None, "type": type_,
        "source": "client", "page": page, "client": clean_client(ev.get("client")), "data": data,
    }


def ingest_batch(session_id, batch):
    """Clean and write one telemetry batch. Returns how many events were kept."""
    if not isinstance(batch, list):
        return 0
    cleaned = [c for c in (clean_client_event(ev) for ev in batch[:MAX_BATCH_EVENTS]) if c]
    if cleaned:
        LOG.last_client[session_id] = cleaned[-1]["client"]
    return len(LOG.append(session_id, cleaned))


# ---------- server events ----------

def guess_client(request):
    """Client object for a server event: the session's last telemetry client
    if the browser sent one, otherwise coarse values from the request."""
    ua = (request.headers.get("user-agent") or "").lower()
    if "edg/" in ua:
        browser = "edge"
    elif "chrome" in ua:
        browser = "chrome"
    elif "firefox" in ua:
        browser = "firefox"
    elif "safari" in ua:
        browser = "safari"
    elif ua.startswith("mozilla"):
        browser = "other"
    else:
        browser = "none"
    if "windows" in ua:
        os_family = "windows"
    elif "mac os" in ua:
        os_family = "macos"
    elif "android" in ua:
        os_family = "android"
    elif "iphone" in ua or "ipad" in ua:
        os_family = "ios"
    elif "linux" in ua:
        os_family = "linux"
    else:
        os_family = "other"
    return {"device_id": request.cookies.get("kya_dev"), "device_class": "unknown",
            "os_family": os_family, "browser_family": browser, "input_type": "unknown",
            "webdriver": None, "languages_count": None, "timezone_offset_min": None}


def server_event(session_id, type_, data, request):
    """Write one server event and return it (with its seq)."""
    client = LOG.last_client.get(session_id) or guess_client(request)
    ev = {
        "schema_version": SCHEMA_VERSION, "session_id": session_id,
        "event_id": "srv_" + secrets.token_hex(8), "seq": None, "client_ts_ms": None,
        "server_ts_ms": None, "type": type_, "source": "server", "page": None,
        "client": client, "data": data,
    }
    return LOG.append(session_id, [ev])[0]


def clean_body(body):
    """Request body with free-text and personal fields removed."""
    if not isinstance(body, dict):
        return None
    return {k: v for k, v in body.items() if k not in DROPPED_BODY_FIELDS}


def log_api_call(session_id, request, body_bytes):
    """Write the api_call event for a request, when it arrives (before the
    endpoint runs), so a later transaction event can point back to it."""
    try:
        body = json.loads(body_bytes) if body_bytes else None
    except ValueError:
        body = None
    headers = {k: request.headers.get(h) for k, h in KEPT_HEADERS.items()}
    data = {
        "method": request.method,
        "path": request.url.path,
        "query": request.url.query,
        "status": None,  # not known yet: the event is written before the response
        "channel": "browser" if request.cookies.get("kya_dev") else "api",
        "headers": headers,
        "body": clean_body(body),
    }
    return server_event(session_id, "api_call", data, request)
