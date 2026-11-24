"""P8: Model A, who is acting (human, scripted_bot or llm_agent), from behaviour alone.

  python -m kya.behaviour.model_a            # grouped cross-validation on train + dev, then fit and save

Train and dev groups only; test groups are never read here. Folds are by group_id
(GroupKFold), so one script family or one volunteer is never on both sides of a fold.
Inputs are the behaviour features (whole session and last 10 s) and nothing about the
payment, the device class or the labels.
"""
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

from kya.behaviour.features import behaviour_features
from kya.features import build_features
from kya.interfaces import AGENT_CLASSES

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
LABELS = ROOT / "data" / "labels.csv"
MODEL_DIR = ROOT / "models"
MODEL_FILE = MODEL_DIR / "model_a.txt"
COLUMNS_FILE = MODEL_DIR / "model_a_columns.json"
MISSING = -1.0                      # the feature code's own marker for "not measured"

PARAMS = {"objective": "multiclass", "num_class": len(AGENT_CLASSES), "learning_rate": 0.05,
          "num_leaves": 15, "min_data_in_leaf": 5, "feature_fraction": 0.8, "verbose": -1, "seed": 7}
ROUNDS = 200


def actor_columns():
    """Model A's inputs: behaviour features, the last-10-seconds copies, and the evidence count."""
    names = sorted(behaviour_features([]))
    return names + ["w10_" + n for n in names] + ["n_behaviour_events"]


def load_events(session_id):
    path = RAW / f"{session_id}.jsonl"
    return [json.loads(line) for line in open(path) if line.strip()] if path.exists() else None


def cut(events, decision_seq):
    return [e for e in events if e["seq"] <= decision_seq]


def row(features, columns):
    return [float(features.get(c, MISSING)) for c in columns]


def load_dataset(splits=("train", "dev")):
    """X, y, groups and session ids for labelled sessions in the given splits."""
    columns = actor_columns()
    X, y, groups, sids = [], [], [], []
    for r in csv.DictReader(open(LABELS)):
        if r["split"] not in splits or r["actor"] not in AGENT_CLASSES or r["decision_seq"] == "":
            continue
        events = load_events(r["session_id"])
        if events is None:
            continue
        f = build_features(cut(events, int(r["decision_seq"])), None)
        X.append(row(f, columns))
        y.append(AGENT_CLASSES.index(r["actor"]))
        groups.append(r["group_id"])
        sids.append(r["session_id"])
    return np.array(X, dtype=float), np.array(y), np.array(groups), sids, columns


def cross_validate(X, y, groups, n_splits=5):
    """Out-of-fold class probabilities, grouped by group_id."""
    import lightgbm as lgb
    from sklearn.model_selection import GroupKFold
    k = min(n_splits, len(set(groups)))
    if k < 2:
        raise SystemExit("need at least 2 groups for grouped cross-validation")
    oof = np.zeros((len(y), len(AGENT_CLASSES)))
    for tr, te in GroupKFold(n_splits=k).split(X, y, groups):
        booster = lgb.train(PARAMS, lgb.Dataset(X[tr], y[tr]), ROUNDS)
        oof[te] = booster.predict(X[te])
    return oof


def report(y, oof):
    from sklearn.metrics import confusion_matrix, f1_score
    pred = oof.argmax(1)
    present = sorted(set(y) | set(pred))
    print(f"development, {len(y)} sessions, grouped {len(AGENT_CLASSES)}-class cross-validation")
    print("classes:", {AGENT_CLASSES[c]: n for c, n in sorted(Counter(y).items())})
    print(f"macro F1: {f1_score(y, pred, average='macro'):.3f}")
    print("confusion (rows = true, cols = predicted):", [AGENT_CLASSES[c] for c in present])
    print(confusion_matrix(y, pred, labels=present))


def fit_and_save(X, y, columns):
    import lightgbm as lgb
    MODEL_DIR.mkdir(exist_ok=True)
    booster = lgb.train(PARAMS, lgb.Dataset(X, y, feature_name=columns), ROUNDS)
    booster.save_model(str(MODEL_FILE))
    COLUMNS_FILE.write_text(json.dumps(columns))
    return booster


_BOOSTER = None


def load():
    global _BOOSTER
    if _BOOSTER is None:
        import lightgbm as lgb
        _BOOSTER = lgb.Booster(model_file=str(MODEL_FILE))
    return _BOOSTER, json.loads(COLUMNS_FILE.read_text())


def predict_actor(features, booster=None, columns=None):
    """{"class_probs": {...}, "contribs": {feature: value}} for one session.

    contribs come from pred_contrib for the chosen class, bias column dropped, and only
    the features that pushed toward that class (positive values) are kept.
    """
    if booster is None:
        booster, columns = load()
    x = np.array([row(features, columns)])
    probs = booster.predict(x)[0]
    chosen = int(probs.argmax())
    width = len(columns) + 1                               # features + bias, per class
    contrib = booster.predict(x, pred_contrib=True)[0][chosen * width:(chosen + 1) * width - 1]
    return {"class_probs": {c: float(p) for c, p in zip(AGENT_CLASSES, probs)},
            "contribs": {c: float(v) for c, v in zip(columns, contrib) if v > 0}}


def main():
    X, y, groups, sids, columns = load_dataset()
    if len(set(y)) < 2:
        raise SystemExit(f"only {len(y)} sessions with one class so far; need at least two classes")
    oof = cross_validate(X, y, groups)
    report(y, oof)
    fit_and_save(X, y, columns)
    print(f"saved {MODEL_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
