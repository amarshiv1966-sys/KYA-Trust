"""Run bots and append one row per session to data/labels.csv.

  python -m bots.run --scenario bot_read_statement --family http_basic --n 5 --seed 100
  python -m bots.run --scenario bot_malicious_transfer --family pw_basic --n 3 --headed

Start the bank first (see README). decision_seq is left empty here and filled from the
bank's log later by bots/finalize_labels.py.
"""
import argparse
import random
from bots import common


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--family", required=True)
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()

    scenario = common.load_scenario(a.scenario)
    common.check_family(a.scenario, scenario, a.family)
    fam = common.FAMILIES[a.family]

    for i in range(a.n):
        seed = a.seed + i
        rng = random.Random(seed)
        if fam["kind"] == "http":
            from bots import http_bot
            sid = http_bot.run(scenario, fam, rng)
        else:
            from bots import pw_bot
            sid = pw_bot.run(scenario, fam, rng, a.headed)
        common.write_label(common.make_label_row(scenario, a.family, sid, seed))
        print(f"{a.scenario} {a.family} seed={seed} -> {sid}")


if __name__ == "__main__":
    main()
