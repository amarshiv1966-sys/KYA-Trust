"""Volunteer mode: record a human session and write its labels.csv row.

Run by the team member sitting with the volunteer (never by the volunteer).
The bank must be running (uvicorn + npm run dev).

    python tools/volunteer.py next                          which ID to give the next new person
    python tools/volunteer.py start P07 normal_transfer     make P07's account, print the task card
    python tools/volunteer.py start P07 new_payee --phone   flags: --phone, --keyboard-only, --autofill
    python tools/volunteer.py finish                        find the session, write the label row
    python tools/volunteer.py cancel                        drop the current recording (no row)
    python tools/volunteer.py status                        sessions so far, by split

Tasks: normal_transfer, new_payee, high_value (scenarios in bots/scenarios/human_*.yaml).
app_scam and takeover need the scam chatbot and the takeover agent, built later.

Each volunteer gets one account (username = their ID in lower case, e.g. p07,
password demo1234) with three saved payees, used for all their sessions.
Before their first session they sign docs/consent_form.md.
"""

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bank.backend.db import connect, init_db, now_ms  # noqa: E402
from bank.backend.ingest import raw_dir  # noqa: E402
from bank.backend.seed import FIRST, LAST, PASSWORD, hash_password, seed_history  # noqa: E402
from bots.common import GENERATOR_VERSION, LABEL_COLUMNS, LABELS_CSV, check_row, load_scenario, load_splits, write_label  # noqa: E402

ACTIVE = ROOT / "data" / "volunteer_active.json"
TASKS = {"normal_transfer": "human_normal_transfer", "new_payee": "human_new_payee",
         "high_value": "human_high_value"}
LATER = {"app_scam": "the scam chatbot page", "takeover": "the takeover agent"}

CARDS = {
    "normal_transfer": [
        "Log in with the username and password above.",
        "Look at your balance on the home page.",
        "Go to Transfer and send Rs {amount} to {payee}.",
        "Use the bank the way you normally would. There is no rush.",
    ],
    "new_payee": [
        "Log in with the username and password above.",
        "Go to Payees and add a new payee: any name, a 12-digit account number, IFSC KYAB0001234.",
        "Then go to Transfer and send Rs {amount} to that new payee.",
        "Use the bank the way you normally would. There is no rush.",
    ],
    "high_value": [
        "Log in with the username and password above.",
        "This is a big payment, like rent or fees: go to Transfer and send Rs {amount} to {payee}.",
        "The bank may ask for an extra check. That is expected; just tell us what it says.",
        "Use the bank the way you normally would. There is no rush.",
    ],
}


def volunteer_ids():
    return sorted(k for k in load_splits() if k.startswith("P"))


def labelled_rows():
    if not LABELS_CSV.exists():
        return []
    import csv
    with open(LABELS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def human_rows():
    ids = set(volunteer_ids())
    return [r for r in labelled_rows() if r["group_id"] in ids]


# ---------- accounts ----------

def ensure_account(conn, vid):
    """One account per volunteer, made on first use: three saved payees."""
    user_id = f"vol_{vid.lower()}"
    if conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone():
        return user_id
    rng = random.Random(vid)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                     (user_id, vid.lower(), hash_password(PASSWORD), f"Volunteer {vid}"))
        account_id = f"ac_{vid.lower()}"
        conn.execute("INSERT INTO accounts VALUES (?, ?, ?)", (account_id, user_id, 250_000 * 100))
        mine = []
        for _ in range(3):
            n = conn.execute("SELECT COUNT(*) FROM payees").fetchone()[0] + 1
            mine.append(f"py_{n:06d}")
            conn.execute("INSERT INTO payees VALUES (?, ?, ?, ?, ?, ?)",
                         (mine[-1], account_id, f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                          str(rng.randint(10**11, 10**12 - 1)), f"KYAB000{rng.randint(1000, 9999)}",
                          now_ms() - rng.randint(120, 400) * 86_400_000))
        seed_history(conn, account_id, mine, rng, 250_000 * 100)   # 90 days of ordinary banking
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return user_id


# ---------- commands ----------

def cmd_next():
    splits = load_splits()
    used = {r["group_id"] for r in human_rows()}
    fresh = [v for v in volunteer_ids() if v not in used and v not in ("P01", "P02")]
    # train/dev first, so the early people feed the abstract's dev numbers;
    # test people are recorded too, later in the week
    order = [v for v in fresh if splits[v] != "test"] + [v for v in fresh if splits[v] == "test"]
    if not order:
        print("all volunteer IDs are in use")
        return
    print(f"next new person: {order[0]} ({splits[order[0]]})")
    print("P01 = Kartik, P02 = Prachi (always train)")


def cmd_start(vid, task, flags):
    if ACTIVE.exists():
        sys.exit(f"a recording is already running ({json.loads(ACTIVE.read_text())['volunteer']}): "
                 "finish or cancel it first")
    if task in LATER:
        sys.exit(f"{task} needs {LATER[task]}, which is not built yet")
    if task not in TASKS:
        sys.exit(f"task must be one of {list(TASKS)}")
    if vid not in volunteer_ids():
        sys.exit(f"{vid} is not in data/splits.yaml (P01..P25)")
    scenario = load_scenario(TASKS[task])
    conn = connect()
    init_db(conn)
    user_id = ensure_account(conn, vid)
    payees = [r["name"] for r in conn.execute(
        "SELECT p.name FROM payees p JOIN accounts a ON a.account_id = p.account_id WHERE a.user_id = ?",
        (user_id,))]
    rng = random.Random()
    low, high = scenario["amount_inr"]
    amount = rng.randint(low // 10, high // 10) * 10   # round tens, like a person would pick
    payee = rng.choice(payees)

    ACTIVE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE.write_text(json.dumps({"volunteer": vid, "task": task, "user_id": user_id, "started_ms": now_ms(),
                                  "flags": flags, "amount_inr": amount}))
    split = load_splits()[vid]
    print(f"\nRecording {vid} ({split}), task {task}. Account: username {vid.lower()}, password {PASSWORD}")
    if "--phone" in flags:
        print("Phone: open http://<this computer's IP>:5173 on the same Wi-Fi (start uvicorn with --host 0.0.0.0)")
    print("\n----- TASK CARD (show this to the volunteer) -----")
    print(f"Username: {vid.lower()}    Password: {PASSWORD}\n")
    for i, line in enumerate(CARDS[task], 1):
        print(f"{i}. {line.format(amount=f'{amount:,}', payee=payee)}")
    if "--keyboard-only" in flags:
        print("Please use only the keyboard this time (Tab, Enter, arrow keys), no mouse.")
    if "--autofill" in flags:
        print("Let the browser fill in the username and password if it offers to.")
    print("---------------------------------------------------")
    print("\nOpen a fresh browser window at http://localhost:5173 and hand over.")
    print("When they are done:  python tools/volunteer.py finish")


def find_session(active, action):
    """The volunteer's session since start: the one with a transaction of the
    task's kind. Returns (session_id, decision_seq, events) or None."""
    conn = connect()
    sids = [r[0] for r in conn.execute(
        "SELECT session_id FROM sessions WHERE user_id = ? ORDER BY created_ms", (active["user_id"],))]
    best = None
    for sid in sids:
        path = raw_dir() / f"{sid}.jsonl"
        if not path.exists():
            continue
        events = [json.loads(line) for line in open(path, encoding="utf-8")]
        txs = [e for e in events if e["type"] == "transaction" and e["data"]["action"] == action
               and e["server_ts_ms"] >= active["started_ms"]]   # paid after `start`, not an older session
        if txs:
            best = (sid, txs[-1]["seq"], events)
    return best


def cmd_finish():
    if not ACTIVE.exists():
        sys.exit("no recording is running")
    active = json.loads(ACTIVE.read_text())
    scenario = load_scenario(TASKS[active["task"]])
    found = find_session(active, scenario["action"])
    if found is None:
        sys.exit(f"no {scenario['action']} found for {active['volunteer']} since the start. "
                 "Did they press Send? (or: python tools/volunteer.py cancel)")
    sid, decision_seq, events = found
    client = next((e["client"] for e in events if e["source"] == "client"), {})
    flags = active["flags"]
    input_type = ("keyboard_only" if "--keyboard-only" in flags else
                  "touch" if "--phone" in flags else client.get("input_type") or "unknown")
    device = "phone" if "--phone" in flags else (client.get("device_class") or "unknown")
    l = scenario["labels"]
    vid = active["volunteer"]
    row = {
        "session_id": sid, "decision_seq": decision_seq,
        "actor": l["actor"], "legit": l["legit"], "authorized": l["authorized"], "victim": l["victim"],
        "handover_seq": "", "typology": l["typology"],
        "group_id": vid, "split": load_splits()[vid],
        "hard_mode": 0, "unseen_framework": 0, "unseen_attack": 0,
        "channel": "browser", "device_class": device, "input_type": input_type,
        "browser": client.get("browser_family") or "unknown",
        "framework": "none",
        "config_id": active["task"] + ("_autofill" if "--autofill" in flags else ""),
        "seed": "", "generator_version": GENERATOR_VERSION,
    }
    assert list(row) == LABEL_COLUMNS
    check_row(row)
    if any(r["session_id"] == sid for r in labelled_rows()):
        sys.exit(f"{sid} already has a label row")
    write_label(row)
    ACTIVE.unlink()
    behaviour = sum(e["type"] in ("click", "keystroke", "pointer_move", "scroll") for e in events)
    print(f"labelled {sid}: {vid} ({row['split']}), {active['task']}, decision at seq {decision_seq}, "
          f"{len(events)} events ({behaviour} behaviour)")
    if behaviour < 20:
        print("WARNING: very little behaviour recorded. Was telemetry running (npm run dev, not a cached page)?")


def cmd_cancel():
    if ACTIVE.exists():
        ACTIVE.unlink()
        print("cancelled; nothing written")
    else:
        print("no recording is running")


def cmd_status():
    rows = human_rows()
    by_split = {}
    for r in rows:
        by_split[r["split"]] = by_split.get(r["split"], 0) + 1
    people = sorted({r["group_id"] for r in rows})
    print(f"human sessions: {len(rows)}  " + "  ".join(f"{k} {v}" for k, v in sorted(by_split.items())))
    print(f"people: {len(people)}  ({', '.join(people) if people else 'none yet'})")
    tasks = {}
    for r in rows:
        tasks[r["config_id"]] = tasks.get(r["config_id"], 0) + 1
    if tasks:
        print("tasks: " + ", ".join(f"{k} {v}" for k, v in sorted(tasks.items())))
    if ACTIVE.exists():
        a = json.loads(ACTIVE.read_text())
        mins = (now_ms() - a["started_ms"]) / 60000
        print(f"recording now: {a['volunteer']} {a['task']} ({mins:.0f} min)")


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, rest = argv[0], argv[1:]
    flags = [a for a in rest if a.startswith("--")]
    args = [a for a in rest if not a.startswith("--")]
    if cmd == "next":
        cmd_next()
    elif cmd == "start" and len(args) == 2:
        cmd_start(args[0].upper(), args[1], flags)
    elif cmd == "finish":
        cmd_finish()
    elif cmd == "cancel":
        cmd_cancel()
    elif cmd == "status":
        cmd_status()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
