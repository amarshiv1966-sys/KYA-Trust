"""Shared pieces for the bots: scenarios, splits, picking amounts, writing labels.csv."""
import csv
import os
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = os.environ.get("KYA_BASE", "http://localhost:5173")        # pages (Vite proxies /api)
API_BASE = os.environ.get("KYA_API", "http://127.0.0.1:8000")     # API-only bots talk straight to FastAPI
PASSWORD = "demo1234"
N_CUSTOMERS = 20
GENERATOR_VERSION = "g-0.1"
LABELS_CSV = ROOT / "data" / "labels.csv"

# column order = docs/labels.md
LABEL_COLUMNS = [
    "session_id", "decision_seq", "actor", "legit", "authorized", "victim", "handover_seq",
    "typology", "group_id", "split", "hard_mode", "unseen_framework", "unseen_attack",
    "channel", "device_class", "input_type", "browser",
    "framework", "config_id", "seed", "generator_version",
]

# Script families. "kind" picks the runner; the rest changes how the script behaves,
# so each family looks different on the wire.
FAMILIES = {
    "http_basic":    {"kind": "http", "user_agent": "python-httpx/0.28", "pause_s": 0.0},
    "http_variant2": {"kind": "http", "user_agent": "curl/8.4.0", "pause_s": 0.4},
    "pw_basic":      {"kind": "playwright", "browser": "chromium", "typing": "fill", "key_delay_ms": 0, "pause_ms": 0},
    "pw_variant2":   {"kind": "playwright", "browser": "chromium", "typing": "keys", "key_delay_ms": 80, "pause_ms": 250},
    "pw_firefox_family": {"kind": "playwright", "browser": "firefox", "typing": "keys", "key_delay_ms": 40, "pause_ms": 120},
}
# scenarios these runners can do today (signed bots wait for Kartik's K8; mule needs many accounts)
SUPPORTED = ["bot_read_statement", "bot_malicious_transfer"]


def load_scenario(name):
    return yaml.safe_load(open(ROOT / "bots" / "scenarios" / f"{name}.yaml"))


def load_splits():
    """{group_id: split} from data/splits.yaml (all groups, humans included)."""
    raw = yaml.safe_load(open(ROOT / "data" / "splits.yaml"))
    out = {}
    for section in ("humans", "scripted_bots", "llm_agents", "unseen"):
        out.update(raw[section])
    return out


def check_family(scenario_name, scenario, family):
    if scenario_name not in SUPPORTED:
        raise SystemExit(f"{scenario_name} is not built yet. Supported: {SUPPORTED}")
    if family not in FAMILIES:
        raise SystemExit(f"unknown family {family}. Known: {list(FAMILIES)}")
    if family not in scenario["families"]:
        raise SystemExit(f"{scenario_name} is not meant for family {family}: {scenario['families']}")
    if family not in load_splits():
        raise SystemExit(f"{family} is missing from data/splits.yaml")


def pick_customer(rng):
    return f"cust_{rng.randint(1, N_CUSTOMERS):04d}"


def pick_amount_paise(scenario, rng, balance_paise):
    low, high = scenario["amount_inr"]
    amount = rng.randint(low, high) * 100
    if amount >= balance_paise:          # never ask for more than the account has
        amount = (balance_paise // 200) * 100
    return max(amount, 100)


def make_label_row(scenario, family, sid, seed):
    fam = FAMILIES[family]
    l = scenario["labels"]
    is_browser = fam["kind"] == "playwright"
    row = {
        "session_id": sid, "decision_seq": "",          # decision_seq is filled from the log later
        "actor": l["actor"], "legit": l["legit"], "authorized": l["authorized"], "victim": l["victim"],
        "handover_seq": "", "typology": l["typology"],
        "group_id": family, "split": load_splits()[family],
        "hard_mode": 0, "unseen_framework": 0, "unseen_attack": 0,
        "channel": "browser" if is_browser else "api",
        "device_class": "desktop" if is_browser else "unknown",
        "input_type": "unknown",
        "browser": {"chromium": "chrome", "firefox": "firefox"}[fam["browser"]] if is_browser else "none",
        "framework": "playwright" if is_browser else "httpx",
        "config_id": family, "seed": seed, "generator_version": GENERATOR_VERSION,
    }
    check_row(row)
    return row


def check_row(r):
    """The consistency checks from docs/labels.md. Raises if a row is impossible."""
    if r["victim"] == 1:
        assert r["actor"] == "human" and r["legit"] == 0 and r["typology"] == "app_scam", "bad victim row"
    if r["typology"] == "takeover":
        assert r["handover_seq"] != "", "takeover needs handover_seq"
    if r["typology"] == "in_scope_compromise":
        assert r["authorized"] == 1 and r["legit"] == 0, "bad in_scope row"
    if r["unseen_framework"] == 1 or r["unseen_attack"] == 1:
        assert r["split"] == "test", "unseen slices are test only"
    assert r["group_id"] in load_splits(), "group_id not in splits.yaml"
    assert r["split"] == load_splits()[r["group_id"]], "split must come from splits.yaml"


def write_label(row):
    LABELS_CSV.parent.mkdir(parents=True, exist_ok=True)
    new_file = not LABELS_CSV.exists()
    with open(LABELS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_COLUMNS)
        if new_file:
            w.writeheader()
        w.writerow(row)
