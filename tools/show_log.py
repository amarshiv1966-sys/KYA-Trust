"""Prints a session's timeline, one line per event.

    python tools/show_log.py                 (the newest session in data/raw)
    python tools/show_log.py s_1a2b3c4d5e6f
"""

import json
import sys
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def main():
    if len(sys.argv) > 1:
        path = RAW / f"{sys.argv[1]}.jsonl"
    else:
        files = sorted(RAW.glob("s_*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not files:
            print("no sessions in", RAW)
            return
        path = files[-1]
    print(path.name)
    t0 = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            ev = json.loads(line)
            t0 = t0 or ev["server_ts_ms"]
            d = ev["data"]
            detail = d.get("target") or d.get("form") or d.get("path") or d.get("action") or ""
            if ev["type"] == "keystroke":
                detail += f" {d['key_class']}"
            print(f"{ev['seq']:>4}  +{(ev['server_ts_ms'] - t0) / 1000:7.2f}s  {ev['source']:<6} "
                  f"{ev['type']:<16} {ev['page'] or '':<10} {detail}")


if __name__ == "__main__":
    main()
