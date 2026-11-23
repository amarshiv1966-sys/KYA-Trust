"""K16: the dataset report finds usable sessions and names the broken ones."""

import csv
import shutil
from pathlib import Path

from bots.common import LABEL_COLUMNS

SAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "samples"


def row(sid, seq, actor, legit, group, split, **kw):
    r = dict.fromkeys(LABEL_COLUMNS, "")
    r.update(session_id=sid, decision_seq=seq, actor=actor, legit=legit, authorized=legit, victim="0",
             typology="none", group_id=group, split=split, hard_mode="0", unseen_framework="0",
             unseen_attack="0", channel="browser", device_class="desktop", input_type="mouse",
             browser="chrome", framework="none", config_id="t", seed="", generator_version="t")
    r.update(kw)
    return r


def test_report(tmp_path, capsys):
    raw = tmp_path / "raw"
    raw.mkdir()
    import json
    human = [json.loads(l) for l in open(SAMPLES / "human_transfer.jsonl")]
    sid = human[0]["session_id"]
    shutil.copy(SAMPLES / "human_transfer.jsonl", raw / f"{sid}.jsonl")   # logs are named by session id
    tx = [e["seq"] for e in human if e["type"] == "transaction"][0]
    from bots.common import load_splits
    splits = load_splits()
    labels = tmp_path / "labels.csv"
    with open(labels, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
        w.writeheader()
        w.writerow(row(sid, tx, "human", "1", "P04", splits["P04"]))
        w.writerow(row("s_missing00001", 5, "scripted_bot", "0", "P04", splits["P04"]))   # no log
        w.writerow(row(sid, tx, "human", "1", "P04", splits["P04"]))                       # duplicate
        w.writerow(row(sid.replace("a", "b"), "", "human", "1", "P06", "test"))            # wrong split, no log
    from eval.dataset_report import main
    main(["--labels", str(labels), "--raw", str(raw), "--md", str(tmp_path / "r.md")])
    out = capsys.readouterr().out
    assert "usable 1" in out and "duplicate rows 2" in out
    assert "s_missing00001 (no log file)" in out
    assert "disagrees with data/splits.yaml" in out
    assert (tmp_path / "r.md").read_text().startswith("# Dataset report")
