"""Behaviour features: HOW the session acted (timing, pointer, clicks, keys, API rhythm).

Input: the session's events already cut at the decision (seq <= decision_seq).
Every feature is a plain float. Missing evidence is a value (0 or -1), never a crash.
Each feature has a one-line comment saying what it measures.
"""
import math
import statistics

BEHAVIOUR_TYPES = ("click", "keystroke", "pointer_move", "scroll")   # counted as behaviour evidence
ACTION_TYPES = ("click", "keystroke", "form_submit", "page_view", "scroll")


def _median(xs):
    return statistics.median(xs) if xs else 0.0


def _std(xs):
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def _cv(xs):
    # spread relative to the mean; 0 for machine-regular timing
    if len(xs) < 2:
        return -1.0
    m = statistics.mean(xs)
    return _std(xs) / m if m > 0 else -1.0


def _gaps(times):
    times = sorted(times)
    return [b - a for a, b in zip(times, times[1:])]


def _is_exact_centre(c):
    return abs(c["data"]["offset_x"]) <= 1 and abs(c["data"]["offset_y"]) <= 1


def behaviour_features(events, prefix=""):
    f = {}
    clicks = [e for e in events if e["type"] == "click"]
    keys = [e for e in events if e["type"] == "keystroke"]
    moves = [e for e in events if e["type"] == "pointer_move"]
    scrolls = [e for e in events if e["type"] == "scroll"]
    submits = [e for e in events if e["type"] == "form_submit"]
    views = [e for e in events if e["type"] == "page_view"]
    apis = [e for e in events if e["type"] == "api_call"]
    client_events = [e for e in events if e["source"] == "client"]

    # ---- counts (how much evidence there is)
    f["n_clicks"] = len(clicks)
    f["n_keystrokes"] = len(keys)
    f["n_pointer_events"] = len(moves)
    f["n_scrolls"] = len(scrolls)
    f["n_api_calls"] = len(apis)
    f["api_only"] = 1.0 if not client_events else 0.0   # no browser telemetry at all

    # ---- timing between actions (client clock, only between client events)
    action_ts = [e["client_ts_ms"] for e in events
                 if e["type"] in ACTION_TYPES and e["client_ts_ms"] is not None]
    gaps = _gaps(action_ts)
    f["gap_median_ms"] = _median(gaps)                 # typical pause between actions
    f["gap_cv"] = _cv(gaps)                            # near 0 = machine-regular rhythm
    span = (max(action_ts) - min(action_ts)) if len(action_ts) > 1 else 0
    f["idle_fraction"] = (sum(g for g in gaps if g > 2000) / span) if span > 0 else 0.0  # share of time spent idle
    f["n_bursts"] = float(sum(1 for g in gaps if g < 30))  # actions faster than a human can do

    # ---- pointer
    straight, speeds, peak_pos = [], [], []
    for m in moves:
        pts = m["data"]["points"]
        if len(pts) < 3:
            continue
        path, seg_speed = 0.0, []
        for a, b in zip(pts, pts[1:]):
            d = math.hypot(b[1] - a[1], b[2] - a[2])
            dt = max(b[0] - a[0], 1)
            path += d
            seg_speed.append(d / dt)
        net = math.hypot(pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2])
        if path > 0:
            straight.append(net / path)                # 1.0 = perfectly straight line
        speeds += seg_speed
        peak_pos.append(seg_speed.index(max(seg_speed)) / (len(seg_speed) - 1))
    f["ptr_straightness"] = statistics.mean(straight) if straight else -1.0   # humans curve, scripts go straight
    f["ptr_speed_cv"] = _cv(speeds)                    # speed variation along the path
    f["ptr_peak_pos"] = statistics.mean(peak_pos) if peak_pos else -1.0       # human speed peaks mid-move (~0.5)

    # share of clicks that had pointer movement before them since the previous click
    prev_seq, moved = 0, 0
    for c in clicks:
        if any(prev_seq < m["seq"] < c["seq"] for m in moves):
            moved += 1
        prev_seq = c["seq"]
    f["click_after_move_frac"] = moved / len(clicks) if clicks else -1.0

    # ---- clicks
    f["click_exact_centre_frac"] = (sum(_is_exact_centre(c) for c in clicks) / len(clicks)) if clicks else -1.0  # scripts hit the centre
    f["click_offset_mean"] = (statistics.mean(math.hypot(c["data"]["offset_x"], c["data"]["offset_y"]) for c in clicks)
                              if clicks else -1.0)     # average distance from button centre, px
    presses = [c["data"]["press_ms"] for c in clicks if c["data"]["press_ms"] is not None]
    f["click_no_press_frac"] = (1 - len(presses) / len(clicks)) if clicks else -1.0   # click with no mouse-down/up (script)
    f["click_press_median_ms"] = _median(presses) if presses else -1.0                # how long a button is held
    f["click_interval_cv"] = _cv(_gaps([c["client_ts_ms"] for c in clicks if c["client_ts_ms"] is not None]))  # regular clicking

    # ---- keys (key class and timing only)
    dwell = [k["data"]["dwell_ms"] for k in keys]
    flight = [k["data"]["flight_ms"] for k in keys if k["data"]["flight_ms"] is not None]
    f["key_dwell_median_ms"] = _median(dwell) if dwell else -1.0   # how long keys are held
    f["key_dwell_std_ms"] = _std(dwell) if dwell else -1.0
    f["key_flight_median_ms"] = _median(flight) if flight else -1.0  # gap between keys
    f["key_flight_std_ms"] = _std(flight) if flight else -1.0        # humans vary, scripts do not
    f["key_backspace_rate"] = (sum(k["data"]["key_class"] == "backspace" for k in keys) / len(keys)) if keys else -1.0  # humans fix typos

    # ---- how forms were filled
    f["paste_count"] = float(sum(s["data"]["paste_count"] for s in submits))              # pasted fields
    f["fields_filled"] = float(sum(s["data"]["fields_filled"] for s in submits))
    f["fields_without_keys"] = float(sum(s["data"]["fields_without_keys"] for s in submits))  # filled with no typing
    f["no_key_fill_frac"] = (f["fields_without_keys"] / f["fields_filled"]) if f["fields_filled"] else -1.0
    f["whole_form_at_once"] = 1.0 if any(s["data"]["fields_filled"] > 0 and
                                         s["data"]["fields_without_keys"] == s["data"]["fields_filled"]
                                         for s in submits) else 0.0   # whole form set by code in one go

    # ---- LLM rhythm: a 1-5 s pause with no pointer movement, then an exact click
    llm_pauses = 0
    for c in clicks:
        if not _is_exact_centre(c) or c["client_ts_ms"] is None:
            continue
        before = [e for e in events if e["seq"] < c["seq"] and e["type"] in ACTION_TYPES
                  and e["client_ts_ms"] is not None]
        if not before:
            continue
        last = max(before, key=lambda e: e["seq"])
        pause = c["client_ts_ms"] - last["client_ts_ms"]
        moved_between = any(last["seq"] < m["seq"] < c["seq"] for m in moves)
        if 1000 <= pause <= 5000 and not moved_between:
            llm_pauses += 1
    f["llm_pause_then_exact"] = float(llm_pauses)

    # ---- navigation
    view_ts = [v["client_ts_ms"] for v in views if v["client_ts_ms"] is not None]
    f["page_dwell_median_ms"] = _median(_gaps(view_ts)) if len(view_ts) > 1 else -1.0   # time on each page
    others = [e["client_ts_ms"] for e in events if e["type"] in ("click", "keystroke") and e["client_ts_ms"] is not None]
    f["first_action_delay_ms"] = (min(others) - min(view_ts)) if (others and view_ts) else -1.0  # load to first action
    f["api_per_page_view"] = (len(apis) / len(views)) if views else float(len(apis))  # many API calls per page = no browsing

    # ---- API-only rhythm (server clock)
    api_ts = [a["server_ts_ms"] for a in apis]
    api_gaps = _gaps(api_ts)
    f["api_gap_median_ms"] = _median(api_gaps) if api_gaps else -1.0   # time between requests
    f["api_gap_cv"] = _cv(api_gaps)                                    # near 0 = timer-driven client
    f["api_no_page_frac"] = (sum(a["data"]["channel"] == "api" for a in apis) / len(apis)) if apis else -1.0  # requests with no page
    uas = {a["data"]["headers"].get("user_agent") for a in apis}
    f["api_user_agents"] = float(len(uas))                             # one client, one user agent
    f["api_signed_frac"] = (sum(bool(a["data"]["headers"].get("signature")) for a in apis) / len(apis)) if apis else -1.0

    # ---- environment flags (only the ones the plan lists; no OS or device class)
    c0 = events[0]["client"] if events else {}
    wd = c0.get("webdriver")
    f["env_webdriver"] = 1.0 if wd else 0.0              # browser says it is automated
    f["env_webdriver_known"] = 0.0 if wd is None else 1.0
    lc = c0.get("languages_count")
    f["env_languages_count"] = -1.0 if lc is None else float(lc)   # headless browsers often report 0
    f["env_no_browser"] = 1.0 if c0.get("browser_family") == "none" else 0.0

    return {prefix + k: float(v) for k, v in f.items()}
