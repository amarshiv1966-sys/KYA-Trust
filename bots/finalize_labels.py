"""Fill decision_seq in data/labels.csv from the bank's raw logs (data/raw/<session_id>.jsonl).

decision_seq = seq of the session's transaction event (docs/schema.md). A read-only session
has no transaction, so it is scored once at its last event (plan section 2). Rows whose log
does not exist yet are left empty and counted, so you can re-run this later.
"""
import csv
import json
from bots.common import ROOT, LABELS_CSV, LABEL_COLUMNS


def decision_seq(session_id):
    path = ROOT / "data" / "raw" / f"{session_id}.jsonl"
    if not path.exists():
        return None
    last = None
    for line in open(path):
        if not line.strip():
            continue
        e = json.loads(line)
        if e["type"] == "transaction":
            return e["seq"]
        last = e["seq"]
    return last                     # read-only session: its last event


def main():
    rows = list(csv.DictReader(open(LABELS_CSV)))
    done = missing = 0
    for r in rows:
        if r["decision_seq"] == "":
            seq = decision_seq(r["session_id"])
            if seq is None:
                missing += 1
            else:
                r["decision_seq"] = seq
                done += 1
    with open(LABELS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"filled {done}, still missing {missing} (no log yet)")


if __name__ == "__main__":
    main()
