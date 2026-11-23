"""Phone sessions: taps and scrolls, few pointer moves. They must not look like scripts."""
from kya.behaviour.features import behaviour_features


def ev(seq, typ, ts, data, source="client", client=None):
    return {"seq": seq, "type": typ, "source": source, "client_ts_ms": ts, "server_ts_ms": ts,
            "data": data, "client": client or {"device_class": "phone", "input_type": "touch"}}


def tap(seq, ts, press=90, ox=6.0, oy=-4.0):
    return ev(seq, "click", ts, {"offset_x": ox, "offset_y": oy, "press_ms": press})


def test_phone_taps_with_no_pointer_moves_are_unknown_not_script_like():
    events = [ev(1, "page_view", 0, {}), tap(2, 1500), ev(3, "scroll", 2500, {"dx": 0, "dy": 300}),
              tap(4, 4000), tap(5, 6500)]
    f = behaviour_features(events)
    assert f["click_after_move_frac"] == -1.0        # unknown, not 0.0
    assert f["ptr_straightness"] == -1.0             # no pointer paths: missing, not a crash
    assert f["click_no_press_frac"] == 0.0           # taps have a press
    assert f["click_exact_centre_frac"] == 0.0


def test_script_click_with_no_press_still_counts_as_no_movement():
    script = lambda seq, ts: ev(seq, "click", ts, {"offset_x": 0, "offset_y": 0, "press_ms": None},
                                client={"webdriver": True})
    f = behaviour_features([ev(1, "page_view", 0, {}), script(2, 1000), script(3, 2000)])
    assert f["click_after_move_frac"] == 0.0         # el.click() with no movement is still a script signal


def test_mouse_user_with_moves_before_clicks_is_measured():
    move = lambda seq, ts: ev(seq, "pointer_move", ts, {"points": [[0, 0, 0], [50, 40, 10], [100, 90, 30]]},
                              client={"device_class": "desktop", "input_type": "mouse"})
    events = [ev(1, "page_view", 0, {}), move(2, 500), tap(3, 900), move(4, 1500), tap(5, 2000)]
    f = behaviour_features(events)
    assert f["click_after_move_frac"] == 1.0
