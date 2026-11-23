"""P9: generate scripted-bot sessions in bulk, reproducibly, with no LLM.

  python -m bots.generate --dry-run              # show what would run
  python -m bots.generate                        # run the default plan
  python -m bots.generate --scale 3              # three times the default counts
  python -m bots.generate --only http_basic      # one family only

Start the bank and the pages first. Every (scenario, family) has its own seed block, so a
session is defined by its seed alone and the whole set can be regenerated. Runs already in
data/labels.csv are skipped, so it is safe to stop (Ctrl-C) and run again later.
At the end it fills decision_seq (bots/finalize_labels.py).

Do not run an agent batch (bots/agents/run_agent.py) at the same time.
"""
import argparse
import csv
import random
import time
import traceback

from bots import common

# (scenario, family, sessions at scale 1). Only families whose runner exists today.
PLAN = [
    ("bot_read_statement", "http_basic", 10),
    ("bot_read_statement", "http_variant2", 10),
    ("bot_read_statement", "pw_basic", 10),
    ("bot_read_statement", "pw_variant2", 10),
    ("bot_read_statement", "pw_firefox_family", 5),
    ("bot_malicious_transfer", "http_basic", 10),
    ("bot_malicious_transfer", "http_variant2", 10),
    ("bot_malicious_transfer", "pw_basic", 10),
    ("bot_malicious_transfer", "pw_variant2", 10),
    ("bot_malicious_transfer", "pw_firefox_family", 5),
    ("bot_signed_billpay", "http_signed", 10),
    ("bot_signed_billpay", "http_signed_v2", 10),
]
RUNNABLE_KINDS = ("http", "http_signed", "playwright")
SEED_BASE = 100_000          # far above the seeds used by hand so far
BLOCK = 10_000               # seeds per (scenario, family)


def seed_block(index):
    return SEED_BASE + index * BLOCK


def build_jobs(scale=1.0, only=None):
    """[(scenario, family, seed)] for the plan, in a fixed order."""
    jobs = []
    for i, (scenario, family, n) in enumerate(PLAN):
        if only and family != only:
            continue
        if common.FAMILIES[family]["kind"] not in RUNNABLE_KINDS:
            continue
        start = seed_block(i)
        jobs += [(scenario, family, start + k) for k in range(max(1, round(n * scale)))]
    return jobs


def done_keys():
    """(family, seed) pairs already in labels.csv."""
    if not common.LABELS_CSV.exists():
        return set()
    return {(r["config_id"], int(r["seed"])) for r in csv.DictReader(open(common.LABELS_CSV)) if r["seed"]}


def run_one(scenario_name, family, seed, headed=False):
    scenario = common.load_scenario(scenario_name)
    common.check_family(scenario_name, scenario, family)
    fam = common.FAMILIES[family]
    rng = random.Random(seed)
    if fam["kind"] == "http":
        from bots import http_bot
        sid = http_bot.run(scenario, fam, rng)
    elif fam["kind"] == "http_signed":
        from bots import signed_bot
        sid = signed_bot.run(scenario, fam, rng)
    else:
        from bots import pw_bot
        sid = pw_bot.run(scenario, fam, rng, headed)
    common.write_label(common.make_label_row(scenario, family, sid, seed))
    return sid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--only", help="run one family only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--max-errors", type=int, default=5, help="stop after this many errors in a row")
    a = ap.parse_args()

    done = done_keys()
    jobs = [j for j in build_jobs(a.scale, a.only) if (j[1], j[2]) not in done]
    print(f"{len(jobs)} sessions to run ({len(done)} rows already in labels.csv)")
    if a.dry_run:
        for scenario, family, seed in jobs:
            print(f"  {scenario:24} {family:18} seed={seed}")
        return

    ok = errors = streak = 0
    start = time.time()
    for n, (scenario, family, seed) in enumerate(jobs, 1):
        try:
            sid = run_one(scenario, family, seed, a.headed)
            ok += 1
            streak = 0
            print(f"[{n}/{len(jobs)}] {scenario} {family} seed={seed} -> {sid}")
        except KeyboardInterrupt:
            print("stopped; run again to continue where it left off")
            break
        except Exception:
            errors += 1
            streak += 1
            print(f"[{n}/{len(jobs)}] {scenario} {family} seed={seed} FAILED")
            traceback.print_exc(limit=2)
            if streak >= a.max_errors:
                print(f"{streak} errors in a row: is the bank running? Stopping.")
                break
    print(f"done: {ok} ok, {errors} failed, {time.time() - start:.0f}s")

    from bots import finalize_labels
    finalize_labels.main()


if __name__ == "__main__":
    main()
