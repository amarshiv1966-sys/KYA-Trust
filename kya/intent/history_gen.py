"""Customer payment history generator (P2).

Every customer, good or bad, gets history from this same function.
Malice comes only from the scenario, never from how history was built.

Amounts come from PaySim (non-fraud PAYMENT/TRANSFER rows) scaled to rupees.
If the PaySim CSV is missing, a lognormal fallback is used and the output is
marked source=fallback. Do not report fallback runs as PaySim-based.

Usage:
  python -m kya.intent.history_gen --customers 200 --seed 1 \
      --paysim data/paysim.csv --out data/history.csv
"""
import argparse
import os
import numpy as np
import pandas as pd

TARGET_MEDIAN_INR = 1500   # PaySim median is rescaled to this (record in docs/assumptions.md)
DAYS = 60
CATEGORIES = ["groceries", "utilities", "food", "travel", "shopping", "education"]


def load_amount_pool(paysim_path):
    # returns (amounts in rupees, source label)
    if paysim_path and os.path.exists(paysim_path):
        df = pd.read_csv(paysim_path, usecols=["type", "amount", "isFraud"])
        df = df[(df["isFraud"] == 0) & (df["type"].isin(["PAYMENT", "TRANSFER"]))]
        df = df[df["amount"] > 0]
        scale = TARGET_MEDIAN_INR / df["amount"].median()
        return (df["amount"] * scale).to_numpy(), "paysim"
    rng = np.random.default_rng(0)
    return rng.lognormal(mean=np.log(TARGET_MEDIAN_INR), sigma=1.0, size=100000), "fallback"


def make_customer(cid, pool, rng):
    # how active this customer is (cold-start customers have few payments)
    n_pay = int(rng.choice([2, 4, 8, 15, 30, 50], p=[0.1, 0.1, 0.2, 0.3, 0.2, 0.1]))
    n_payees = max(1, min(n_pay, int(rng.integers(1, 8))))
    payees = [f"{cid}_payee{i}" for i in range(n_payees)]
    fav_cats = rng.choice(CATEGORIES, size=int(rng.integers(1, 4)), replace=False)
    rows = []
    for _ in range(n_pay):
        amount = float(rng.choice(pool))
        rows.append({
            "customer_id": cid,
            "days_ago": int(rng.integers(1, DAYS + 1)),
            "hour": int(np.clip(rng.normal(14, 4), 0, 23)),
            "amount_paise": int(round(amount * 100)),
            "payee_id": str(rng.choice(payees)),
            "merchant_category": str(rng.choice(fav_cats)),
        })
    return rows


def summarise(rows, now_ms):
    """Turn one customer's rows into the `history` object that decision_context carries
    (docs/schema.md section 2: payment_count, median/mad amount, payees_seen, categories_seen, last_payment_ts_ms)."""
    amounts = sorted(r["amount_paise"] for r in rows)
    if not amounts:
        return {"payment_count": 0, "median_amount_paise": 0, "mad_amount_paise": 0,
                "payees_seen": [], "categories_seen": [], "last_payment_ts_ms": None}
    median = float(np.median(amounts))
    mad = float(np.median([abs(a - median) for a in amounts]))
    last_days_ago = min(r["days_ago"] for r in rows)
    return {
        "payment_count": len(rows),
        "median_amount_paise": int(median),
        "mad_amount_paise": int(mad),
        "payees_seen": sorted({r["payee_id"] for r in rows}),
        "categories_seen": sorted({r["merchant_category"] for r in rows}),
        "last_payment_ts_ms": int(now_ms - last_days_ago * 86400 * 1000),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--paysim", default="data/paysim.csv")
    ap.add_argument("--out", default="data/history.csv")
    a = ap.parse_args()

    rng = np.random.default_rng(a.seed)
    pool, source = load_amount_pool(a.paysim)
    rows = []
    for i in range(a.customers):
        rows += make_customer(f"c{i:04d}", pool, rng)
    out = pd.DataFrame(rows)
    out["source"] = source
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    out.to_csv(a.out, index=False)
    print(f"{a.customers} customers, {len(out)} payments, source={source} -> {a.out}")


if __name__ == "__main__":
    main()
