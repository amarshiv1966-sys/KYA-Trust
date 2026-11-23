"""Join 0 check: run build_features() on every real log in data/raw and report problems.

  python -m bots.check_features

For each session: cut at the decision, take the bank's decision_context as context,
build the features, and check every value is a finite float. Prints a summary by
framework (from labels.csv) and lists any session that crashed.
"""
import csv
import json
import math
from collections import Counter, defaultdict

from bots.common import ROOT, LABELS_CSV
from kya.features import build_features
from kya.intent.features import find_transaction
from kya.schema import evidence_status

RAW = ROOT / "data" / "raw"


def load(path):
    return [json.loads(line) for line in open(path) if line.strip()]


def context_for(events):
    """The decision_context the bank froze right after the scored transaction."""
    tx = find_transaction(events)
    if tx is None:
        return None
    after = [e for e in events if e["type"] == "decision_context" and e["seq"] > tx["seq"]]
    return after[0]["data"] if after else None


def main():
    labels = {r["session_id"]: r for r in csv.DictReader(open(LABELS_CSV))} if LABELS_CSV.exists() else {}
    stats = defaultdict(Counter)
    crashes, bad_values, n_features = [], [], set()

    for path in sorted(RAW.glob("*.jsonl")):
        sid = path.stem
        group = labels[sid]["framework"] if sid in labels else "unlabelled"
        try:
            events = load(path)
            f = build_features(events, context_for(events))
        except Exception as err:
            crashes.append((sid, group, f"{type(err).__name__}: {err}"))
            stats[group]["crashed"] += 1
            continue
        n_features.add(len(f))
        odd = [k for k, v in f.items() if not isinstance(v, float) or not math.isfinite(v)]
        if odd:
            bad_values.append((sid, group, odd[:5]))
        stats[group]["ok"] += 1
        stats[group]["evidence_" + evidence_status(events)] += 1
        stats[group]["with_payment"] += find_transaction(events) is not None
        stats[group]["two_decisions"] += sum(e["type"] == "transaction" for e in events) > 1

    print(f"{'group':14} ok  crashed  payment  2-decisions  insufficient  partial  sufficient")
    for g, c in sorted(stats.items()):
        print(f"{g:14} {c['ok']:3} {c['crashed']:8} {c['with_payment']:8} {c['two_decisions']:12} "
              f"{c['evidence_insufficient']:13} {c['evidence_partial']:8} {c['evidence_sufficient']:10}")
    print(f"feature counts per session: {sorted(n_features)}")
    for sid, g, err in crashes:
        print(f"CRASH {sid} ({g}): {err}")
    for sid, g, keys in bad_values:
        print(f"NON-FINITE {sid} ({g}): {keys}")
    print("all good" if not crashes and not bad_values else "problems above")


if __name__ == "__main__":
    main()
