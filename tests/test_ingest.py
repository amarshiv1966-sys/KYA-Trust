"""K6: the session timeline — server order, no duplicates, nothing secret."""

import json
import random

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("KYA_DB", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setenv("KYA_RAW_DIR", str(tmp_path / "raw"))
    from bank.backend import ingest
    monkeypatch.setattr(ingest, "LOG", ingest.EventLog())  # fresh in-memory state per test
    from bank.backend.db import connect
    from bank.backend.seed import seed
    from bank.backend.app import app
    seed(connect(), random.Random(7))
    client = TestClient(app)
    client.cookies.set("kya_dev", "dv_test01")  # behave like our own pages
    return client, ingest, tmp_path / "raw"


def read(raw, sid):
    with open(raw / f"{sid}.jsonl") as f:
        return [json.loads(line) for line in f]


def ev(event_id, type_, data, page="login"):
    return {"event_id": event_id, "type": type_, "page": page, "client_ts_ms": 1,
            "client": {"device_id": "dv_test01", "browser_family": "chrome", "secret": "x"},
            "data": data}


def send(client, sid, batch_id, events):
    with client.websocket_connect("/ws/telemetry", headers={"cookie": f"kya_sid={sid}"}) as ws:
        ws.send_json({"batch_id": batch_id, "events": events})
        return ws.receive_json()


def test_login_page_behaviour_stays_in_the_logged_in_session(env):
    client, _, raw = env
    sid = client.post("/api/session/start").json()["session_id"]
    ack = send(client, sid, "b1", [
        ev("e1", "click", {"target": "login.username", "x": 1, "y": 2}),
        ev("e2", "keystroke", {"target": "login.username", "key_class": "letter", "dwell_ms": 80}),
    ])
    assert ack == {"ack": "b1", "kept": 2}
    r = client.post("/api/login", json={"username": "cust_0001", "password": "demo1234"})
    assert r.json()["session_id"] == sid
    client.get("/api/balance")

    log = read(raw, sid)
    assert [e["seq"] for e in log] == list(range(1, len(log) + 1))
    types = [e["type"] for e in log]
    assert types == ["api_call", "click", "keystroke", "api_call", "api_call"]
    assert log[3]["data"]["path"] == "/api/login"
    assert "password" not in log[3]["data"]["body"]
    assert log[4]["data"]["channel"] == "browser"


def test_retried_batch_is_not_written_twice(env):
    client, _, raw = env
    sid = client.post("/api/session/start").json()["session_id"]
    batch = [ev("e1", "scroll", {"dx": 0, "dy": 100}), ev("e2", "scroll", {"dx": 0, "dy": 50})]
    send(client, sid, "b1", batch)
    assert send(client, sid, "b1", batch)["kept"] == 0
    assert len(read(raw, sid)) == 3  # session/start api_call + 2 scrolls


def test_secret_and_unknown_events_are_dropped(env):
    client, _, raw = env
    sid = client.post("/api/session/start").json()["session_id"]
    ack = send(client, sid, "b1", [
        ev("e1", "keystroke", {"target": "login.password", "key_class": "letter", "dwell_ms": 80}),
        ev("e2", "transaction", {"action": "transfer", "amount_paise": 100}),   # clients can't send this
        ev("e3", "click", {"target": "div#random-thing", "x": 1}),               # not an allowlisted id
        ev("e4", "keystroke", {"target": "login.username", "key_class": "a"}),  # a real key, not a class
        ev("e5", "click", {"target": "login.submit", "x": 5, "typed_text": "hello"}),
    ])
    assert ack["kept"] == 1
    kept = read(raw, sid)[-1]
    assert kept["data"]["target"] == "login.submit"
    assert "typed_text" not in kept["data"]
    assert "secret" not in kept["client"]
    assert kept["source"] == "client"


def test_server_sets_seq_and_session_not_the_client(env):
    client, _, raw = env
    sid = client.post("/api/session/start").json()["session_id"]
    bad = ev("e1", "scroll", {"dx": 0, "dy": 1})
    bad.update({"seq": 999, "session_id": "s_someoneelse", "source": "server"})
    send(client, sid, "b1", [bad])
    last = read(raw, sid)[-1]
    assert last["seq"] == 2 and last["session_id"] == sid and last["source"] == "client"


def test_api_client_calls_are_logged_with_headers(env):
    client, _, raw = env
    client.cookies.clear()  # an API-only bot: no device cookie
    sid = client.post("/api/login", json={"username": "cust_0002", "password": "demo1234"}).json()["session_id"]
    h = {"X-KYA-Session": sid, "User-Agent": "python-httpx/0.28", "Idempotency-Key": "ik_1"}
    client.post("/api/payees", headers=h, json={"name": "Someone", "account_number": "123456789012",
                                                 "ifsc": "KYAB0001234"})
    log = read(raw, sid)
    payee_calls = [e for e in log if e["type"] == "api_call" and e["data"]["path"] == "/api/payees"]
    call = payee_calls[-1]["data"]
    assert call["channel"] == "api"
    assert call["headers"]["user_agent"] == "python-httpx/0.28"
    assert call["headers"]["idempotency_key"] == "ik_1"
    assert call["body"] == {}  # name, account number and IFSC removed
    assert payee_calls[-1]["client"]["browser_family"] == "none"


def test_websocket_needs_a_session(env):
    client, _, _ = env
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/telemetry", headers={"cookie": "kya_sid=s_000000000000"}) as ws:
            ws.receive_json()


def test_seq_continues_after_a_restart(env):
    client, ingest, raw = env
    sid = client.post("/api/session/start").json()["session_id"]
    send(client, sid, "b1", [ev("e1", "scroll", {"dx": 0, "dy": 1})])
    ingest.LOG.__init__()  # forget everything, as if the server restarted
    send(client, sid, "b2", [ev("e1", "scroll", {"dx": 0, "dy": 1}), ev("e2", "scroll", {"dx": 0, "dy": 2})])
    assert [e["seq"] for e in read(raw, sid)] == [1, 2, 3]  # e1 not repeated, e2 gets 3
