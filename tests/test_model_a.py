import numpy as np

from kya.behaviour import model_a
from kya.fusion.reasons import rank_reasons
from kya.reason_codes import REASON_CODES


def test_columns_are_behaviour_only():
    cols = model_a.actor_columns()
    assert len(cols) == len(set(cols))
    for banned in ("amount_inr", "new_payee", "hist_count", "device_accounts_before", "mandate_present"):
        assert banned not in cols


def test_train_and_predict_on_synthetic_groups():
    import lightgbm as lgb
    cols = model_a.actor_columns()
    rng = np.random.default_rng(0)
    X = rng.normal(size=(90, len(cols)))
    y = np.repeat([0, 1, 2], 30)
    X[:, 0] += y * 3                                     # one informative column
    groups = np.repeat([f"g{i}" for i in range(9)], 10)
    oof = model_a.cross_validate(X, y, groups, n_splits=3)
    assert oof.shape == (90, 3) and np.allclose(oof.sum(1), 1)
    booster = lgb.train(model_a.PARAMS, lgb.Dataset(X, y, feature_name=cols), 30)
    out = model_a.predict_actor(dict(zip(cols, X[70])), booster, cols)
    assert abs(sum(out["class_probs"].values()) - 1) < 1e-6
    assert all(v > 0 for v in out["contribs"].values())
    assert cols[0] in out["contribs"]


def test_reasons_order_and_fallback():
    out = rank_reasons({"risk": {"new_payee": 0.4, "amount_z": 0.9}, "actor": {"w10_api_only": 0.5,
                        "api_signed_frac": 0.7}}, ["R12"])
    codes = [r["code"] for r in out]
    assert codes == ["R12", "R31", "R30", "R21"]          # policy, risk by size, actor; R60 needs verified
    assert all(c in REASON_CODES for c in codes)
    assert [r["code"] for r in rank_reasons({}, [])] == ["R00"]
    assert [r["code"] for r in rank_reasons({}, [], evidence_status="insufficient")] == ["R50"]
