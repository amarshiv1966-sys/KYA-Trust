"""Offline replay: score a recorded session again, from its log alone.

    python -m kya.replay data/raw/s_xxxx.jsonl            every decision in the log
    python -m kya.replay data/raw/s_xxxx.jsonl --seq 41   just the one at seq 41
    python -m kya.replay data/raw/s_xxxx.jsonl --check    and compare with what the bank decided live

Needs no network and no running bank. It runs the same score_session() as
the live gate, and never writes anything. --check only reads the bank's
decisions table (opened read-only). latency_ms is the one field that differs.
"""

import argparse
import json
import sqlite3
import sys

from kya.score import score_session


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def live_decision(session_id, decision_seq):
    from bank.backend.db import db_path
    path = db_path()
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT decision_json FROM decisions WHERE session_id = ? AND decision_seq = ?",
                           (session_id, decision_seq)).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else None


def strip(decision):
    return {k: v for k, v in decision.items() if k != "latency_ms"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score a recorded session again, offline.")
    ap.add_argument("log")
    ap.add_argument("--seq", type=int, help="decision_seq of one transaction")
    ap.add_argument("--check", action="store_true", help="compare with the live decision")
    args = ap.parse_args(argv)

    events = load(args.log)
    seqs = [args.seq] if args.seq else [e["seq"] for e in events if e["type"] == "transaction"] or [None]
    all_match = True
    for seq in seqs:
        d = score_session(events, decision_seq=seq)
        codes = ", ".join(r["code"] for r in d["reason_codes"])
        print(f"seq {d['decision_seq']:>4}  {d['action']:<8} trust {d['trust_score']:>3}  "
              f"{d['agent_class']:<12} identity {d['identity_state']:<10} mandate {d['mandate_state']:<9} [{codes}]")
        if args.check:
            live = live_decision(d["session_id"], d["decision_seq"])
            if live is None:
                print("          no live decision stored for this one")
            elif strip(live) == strip(d):
                print("          MATCH: same as the live decision")
            else:
                all_match = False
                diff = [k for k in strip(d) if strip(d)[k] != live.get(k)]
                print(f"          DIFFERENT from the live decision in: {', '.join(diff)}")
    return 0 if all_match else 1


if __name__ == "__main__":
    sys.exit(main())
