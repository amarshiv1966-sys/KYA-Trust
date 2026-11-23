"""Our policy against the three baselines, on the same labelled sessions (K12).

    python eval/compare_policies.py                       all usable sessions
    python eval/compare_policies.py --split dev           one split only
    python eval/compare_policies.py --md data/policy_comparison.md

For each policy: the actions it took, how many fraud sessions it stopped
(not allowed) and how many legitimate ones it got in the way of, and the
expected cost per 1,000 sessions under the brief's cost matrix. The cost uses
the true label, the chosen action and the actual amount. Sessions that only
add a payee (no money moved) are counted separately, as the plan says.

This is a development tool. The final numbers come from Prachi's
eval/run_all.py on the test split, run once on 11 Dec.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bank.backend.ingest import raw_dir  # noqa: E402
from bots.common import LABELS_CSV  # noqa: E402
from kya.policy.baselines import BASELINES, realised_cost  # noqa: E402
from kya.score import score_session, session_facts  # noqa: E402

ACTIONS = ["allow", "step_up", "hold", "block"]


def load_rows(labels, raws, split):
    df = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in labels if Path(p).exists()])
    df = df.drop_duplicates("session_id")
    if split:
        df = df[df.split == split]
    out = []
    for r in df.itertuples():
        path = next((Path(d) / f"{r.session_id}.jsonl" for d in raws if (Path(d) / f"{r.session_id}.jsonl").exists()), None)
        if path is None or r.decision_seq.strip() == "":
            continue
        events = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        out.append((r, events, int(float(r.decision_seq))))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Our policy against the baselines")
    ap.add_argument("--labels", nargs="+", default=[str(LABELS_CSV)])
    ap.add_argument("--raw", nargs="+", default=[str(raw_dir())])
    ap.add_argument("--split")
    ap.add_argument("--md")
    args = ap.parse_args(argv)

    rows = load_rows(args.labels, args.raw, args.split)
    if not rows:
        sys.exit("no usable labelled sessions found")

    records = []
    for r, events, seq in rows:
        tx_seq = seq if any(e["seq"] == seq and e["type"] == "transaction" for e in events) else None
        facts = session_facts(events, tx_seq)
        ours = score_session(events, tx_seq)
        actions = {"ours": ours["action"]} | {name: fn(facts)["action"] for name, fn in BASELINES.items()}
        for policy, action in actions.items():
            records.append({"policy": policy, "action": action, "legit": r.legit == "1",
                            "amount_paise": facts["amount_paise"], "action_type": facts["action_type"],
                            "cost": realised_cost(action, r.legit == "1", facts["amount_paise"])})
    df = pd.DataFrame(records)
    money = df[df.action_type != "add_payee"]
    n = money.groupby("policy").size().iloc[0]

    lines = []
    order = ["ours", "fair", "simple_rule", "allow_all"]
    for p in order:
        part = money[money.policy == p]
        fraud, legit = part[~part.legit], part[part.legit]
        stopped = (fraud.action != "allow").mean() if len(fraud) else float("nan")
        friction = (legit.action != "allow").mean() if len(legit) else float("nan")
        lines.append({
            "policy": p, **{a: int((part.action == a).sum()) for a in ACTIONS},
            "fraud stopped": f"{stopped:.0%}" if len(fraud) else "-",
            "legit slowed": f"{friction:.0%}" if len(legit) else "-",
            "cost per 1,000 (Rs)": round(part.cost.sum() / len(part) * 1000),
        })
    table = pd.DataFrame(lines).set_index("policy")
    n_fraud = int((~money[money.policy == "ours"].legit).sum())
    head = (f"{n} payment sessions ({n_fraud} fraud, {n - n_fraud} legitimate)"
            + (f", split {args.split}" if args.split else "") + ". Development numbers, not the final test.")
    print(head)
    print(table.to_string())
    payee_only = df[(df.action_type == "add_payee") & (df.policy == "ours")]
    if len(payee_only):
        print(f"\n{len(payee_only)} add-payee-only sessions reported separately (no money moved).")
    if args.md:
        md = table.reset_index()
        cols = list(md.columns)
        text = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n" + "\n".join(
            "| " + " | ".join(str(v) for v in row) + " |" for row in md.itertuples(index=False))
        Path(args.md).write_text(f"# Policy comparison\n\n{head}\n\n{text}\n", encoding="utf-8")
        print(f"\nwrote {args.md}")


if __name__ == "__main__":
    main()
