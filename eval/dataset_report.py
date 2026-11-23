"""Dataset report (K16): what we have, whether it is usable, whether it is balanced.

Run after every collection day:
    python eval/dataset_report.py
    python eval/dataset_report.py --md data/dataset_report.md      also write the tables as Markdown
Merging both laptops' data (copy Prachi's labels.csv and raw/ folder over first):
    python eval/dataset_report.py --labels data/labels.csv data/labels_mac.csv --raw data/raw data/raw_mac

A session is USABLE when its log exists, it is valid under docs/schema.md, and
its decision_seq points at a transaction event (or the last event for a
read-only session). Everything else is listed with the reason, so it can be
fixed or re-recorded.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bank.backend.ingest import raw_dir  # noqa: E402
from bots.common import LABELS_CSV, load_splits  # noqa: E402
from kya.schema import SchemaError, validate_events  # noqa: E402

GATE = {"usable sessions": 1000, "human sessions": 50}      # 6 Dec gate (plan)
TARGETS = {"human": 110, "scripted_bot": 380, "llm_agent": 330}
MIN_BEHAVIOUR_HUMAN = 20


def check_session(row, raw_dirs):
    """(usable, reason, n_events, n_behaviour)"""
    path = next((d / f"{row.session_id}.jsonl" for d in raw_dirs if (d / f"{row.session_id}.jsonl").exists()), None)
    if path is None:
        return False, "no log file", 0, 0
    try:
        events = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        validate_events(events)
    except (SchemaError, ValueError) as err:
        return False, f"invalid log: {str(err)[:60]}", 0, 0
    behaviour = sum(e["type"] in ("click", "keystroke", "pointer_move", "scroll") for e in events)
    seq = str(row.decision_seq).strip()
    if seq in ("", "nan"):
        return False, "decision_seq empty", len(events), behaviour
    at = [e for e in events if e["seq"] == int(float(seq))]
    if not at:
        return False, "decision_seq not in log", len(events), behaviour
    if at[0]["type"] != "transaction" and int(float(seq)) != events[-1]["seq"]:
        return False, "decision_seq is not a transaction", len(events), behaviour
    return True, "", len(events), behaviour


def to_md(t):
    """A DataFrame as a Markdown table (no extra package needed)."""
    t = t.reset_index()
    head = [" / ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
    rows = [[str(v) for v in r] for r in t.itertuples(index=False)]
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                     + ["| " + " | ".join(r) + " |" for r in rows])


def table(df, index, columns):
    if df.empty:
        return pd.DataFrame()
    t = pd.crosstab([df[c] for c in index], [df[c] for c in columns], margins=True, margins_name="total")
    return t


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", nargs="+", default=[str(LABELS_CSV)])
    ap.add_argument("--raw", nargs="+", default=[str(raw_dir())])
    ap.add_argument("--md", help="also write the tables to this Markdown file")
    args = ap.parse_args(argv)

    frames = [pd.read_csv(p, dtype=str, keep_default_na=False) for p in args.labels if Path(p).exists()]
    if not frames:
        sys.exit(f"no labels found in {args.labels}")
    df = pd.concat(frames, ignore_index=True)
    raw_dirs = [Path(d) for d in args.raw]

    dupes = df[df.duplicated("session_id", keep=False)]
    df = df.drop_duplicates("session_id", keep="first").copy()
    checks = [check_session(r, raw_dirs) for r in df.itertuples()]
    df["usable"] = [c[0] for c in checks]
    df["problem"] = [c[1] for c in checks]
    df["n_behaviour"] = [c[3] for c in checks]

    splits = load_splits()
    df["split_ok"] = [splits.get(g) == s for g, s in zip(df.group_id, df.split)]

    ok = df[df.usable]
    humans = ok[ok.actor == "human"]
    out = []

    def show(title, obj):
        text = obj if isinstance(obj, str) else obj.to_string()
        print(f"\n== {title}\n{text}")
        out.append(f"### {title}\n\n" + (obj if isinstance(obj, str) else to_md(obj)) + "\n")

    show("Totals", f"labelled {len(df)}, usable {len(ok)}, not usable {len(df) - len(ok)}"
                   + (f", duplicate rows {len(dupes)}" if len(dupes) else ""))
    show("Usable sessions: actor x legit x split", table(ok, ["actor", "legit"], ["split"]))
    show("Independent groups (people, scripts, agent configs) per actor and split",
         ok.groupby(["actor", "split"]).group_id.nunique().unstack(fill_value=0))
    show("Usable sessions by typology", ok.groupby(["typology", "legit"]).size().unstack(fill_value=0))
    show("Usable sessions by channel and device", table(ok, ["channel"], ["device_class"]))
    if not humans.empty:
        show("Humans", f"{len(humans)} sessions from {humans.group_id.nunique()} people "
                       f"({', '.join(sorted(humans.group_id.unique()))}); "
                       f"tasks: {humans.config_id.value_counts().to_dict()}")

    flags = []
    for col in ("hard_mode", "unseen_framework", "unseen_attack"):
        part = ok[ok[col] == "1"]
        if len(part):
            flags.append(f"{col}: {len(part)} (legit {int((part.legit == '1').sum())}, "
                         f"malicious {int((part.legit == '0').sum())})")
    show("Reporting slices", "; ".join(flags) or "none yet")

    # ---- checks against the plan
    progress = [f"{a}: {int((ok.actor == a).sum())} of {t}" for a, t in TARGETS.items()]
    gate = [f"{k}: {v} needed, have {len(ok) if k.startswith('usable') else len(humans)}"
            for k, v in GATE.items()]
    show("Progress toward the plan's counts", "\n".join(progress))
    show("6 Dec gate", "\n".join(gate))

    warnings = []
    bad_split = df[~df.split_ok]
    if len(bad_split):
        warnings.append(f"{len(bad_split)} rows have a split that disagrees with data/splits.yaml: "
                        + ", ".join(bad_split.session_id.head(5)))
    thin = humans[humans.n_behaviour < MIN_BEHAVIOUR_HUMAN]
    if len(thin):
        warnings.append(f"{len(thin)} human sessions with under {MIN_BEHAVIOUR_HUMAN} behaviour events: "
                        + ", ".join(thin.session_id.head(5)))
    for split in ("train", "dev", "test"):
        part = ok[ok.split == split]
        if len(part) and part.legit.nunique() < 2:
            warnings.append(f"{split} has only one class of legit ({part.legit.iloc[0]}): ROC-AUC impossible there")
    if len(dupes):
        warnings.append(f"duplicate session_ids: {', '.join(dupes.session_id.unique()[:5])}")
    bad = df[~df.usable]
    if len(bad):
        warnings.append("not usable: " + "; ".join(f"{r.session_id} ({r.problem})" for r in bad.head(10).itertuples())
                        + (" ..." if len(bad) > 10 else ""))
    show("Warnings", "\n".join(warnings) or "none")

    if args.md:
        Path(args.md).write_text("# Dataset report\n\n" + "\n".join(out), encoding="utf-8")
        print(f"\nwrote {args.md}")


if __name__ == "__main__":
    main()
