"""The mapping loop.

These tests are the behavioural spec for padmap: press a button, get an event.
They run on a fake controller and a recording backend, so nothing reaches the
machine running them.
"""

from __future__ import annotations

import pytest

from conftest import FakeController, make_state
from padmap.backends import RecordingBackend
from padmap.config import Profile, load_profile
from padmap.engine import MAX_TICK_SECONDS, Engine


def run_states(engine: Engine, states, step: float = 0.01, start: float = 0.0) -> None:
    """Feed states to the engine one tick apart."""
    for index, state in enumerate(states):
        engine.tick(start + index * step, state)


def engine_for(profile_data: dict, backend: RecordingBackend | None = None) -> tuple:
    """Build an engine from an inline profile document.

    Auto-centring is switched off unless the test supplies its own ``device``
    block. It suppresses pointer motion for the first 0.4 s while it measures
    where the sticks rest, which would otherwise silently swallow the opening
    ticks of every test about pointer maths. The tests that are *about*
    auto-centring pass their own device block and get the real behaviour.
    """
    backend = backend or RecordingBackend()
    controller = FakeController()
    profile_data = {"device": {"auto_centre": False}, **profile_data}
    return Engine(Profile.from_dict(profile_data), controller, backend), backend, controller


# --- Buttons -----------------------------------------------------------------


def test_holding_a_button_holds_the_key() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": "key:w"}})
    run_states(engine, [make_state(), make_state(a=True), make_state(a=True), make_state()])
    assert backend.log() == ["key_down w", "key_up w"]


def test_a_key_combo_presses_modifiers_first_and_releases_them_last() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": "key:ctrl+shift+s"}})
    run_states(engine, [make_state(), make_state(a=True), make_state()])
    assert backend.log() == ["key_down ctrl+shift+s", "key_up ctrl+shift+s"]


def test_mouse_buttons_press_and_release() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": "mouse:left"}})
    run_states(engine, [make_state(), make_state(a=True), make_state()])
    assert backend.log() == ["mouse_down left", "mouse_up left"]


def test_a_noop_binding_emits_nothing() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": "noop"}})
    run_states(engine, [make_state(), make_state(a=True), make_state()])
    assert backend.log() == []


def test_text_fires_once_per_press_not_once_per_tick() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": "text:gg"}})
    run_states(engine, [make_state(), *[make_state(a=True)] * 5, make_state()])
    assert backend.log() == ["type gg"]


def test_dpad_maps_to_keys() -> None:
    engine, backend, _ = engine_for({"dpad": {"up": "key:up"}})
    run_states(engine, [make_state(), make_state(up=True), make_state()])
    assert backend.log() == ["key_down up", "key_up up"]


# --- Turbo and toggle --------------------------------------------------------


def test_turbo_taps_at_the_configured_rate() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": {"action": "key:x", "turbo": 10}}})
    engine.tick(0.0, make_state())
    for tick in range(1, 21):  # 1.0 s of holding, 20 ticks
        engine.tick(tick * 0.05, make_state(a=True))
    taps = backend.log().count("key_down x")
    assert taps == pytest.approx(10, abs=1)
    # Every tap is matched by a release — turbo must not leave the key down.
    assert backend.log().count("key_up x") == taps


def test_turbo_stops_when_the_button_is_released() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": {"action": "key:x", "turbo": 20}}})
    run_states(engine, [make_state(), make_state(a=True), make_state()], step=0.1)
    before = len(backend.events)
    run_states(engine, [make_state()] * 5, start=1.0, step=0.1)
    assert len(backend.events) == before


def test_toggle_latches_on_and_off_across_presses() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": {"action": "key:shift", "toggle": True}}})
    run_states(engine, [make_state(), make_state(a=True), make_state(), make_state()])
    assert backend.log() == ["key_down shift"], "still held after release"
    run_states(engine, [make_state(a=True), make_state()], start=1.0)
    assert backend.log() == ["key_down shift", "key_up shift"]


# --- Triggers ----------------------------------------------------------------


def test_a_trigger_fires_only_past_its_threshold() -> None:
    engine, backend, _ = engine_for(
        {"triggers": {"rt": {"action": "mouse:left", "threshold": 0.6}}}
    )
    run_states(engine, [make_state(), make_state(rt=0.4)])
    assert backend.log() == []
    engine.tick(0.5, make_state(rt=0.9))
    assert backend.log() == ["mouse_down left"]
    engine.tick(0.6, make_state(rt=0.1))
    assert backend.log() == ["mouse_down left", "mouse_up left"]


# --- Sticks ------------------------------------------------------------------


def test_stick_in_mouse_mode_moves_the_pointer_at_the_configured_speed() -> None:
    engine, backend, _ = engine_for(
        {
            "sticks": {
                "left": {
                    "mode": "mouse",
                    "speed": 1000,
                    "deadzone": 0.1,
                    "curve": 1.0,
                    "smoothing": 0,
                }
            }
        }
    )
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(left_x=1.0))
    # 1000 px/s for 0.1 s, minus the deadzone rescale of a full-deflection stick.
    assert backend.log() == ["mouse_move 100,0"]


def test_pointer_motion_is_zero_inside_the_deadzone() -> None:
    engine, backend, _ = engine_for({"sticks": {"left": {"mode": "mouse", "deadzone": 0.3}}})
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(left_x=0.2))
    assert backend.log() == []


def test_stick_up_moves_the_pointer_up() -> None:
    engine, backend, _ = engine_for(
        {
            "sticks": {
                "left": {
                    "mode": "mouse",
                    "speed": 500,
                    "deadzone": 0.0,
                    "curve": 1.0,
                    "smoothing": 0,
                }
            }
        }
    )
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(left_y=-1.0))
    assert backend.log() == ["mouse_move 0,-50"], "negative dy is up on screen"


def test_stick_in_scroll_mode_scrolls_up_when_pushed_up() -> None:
    engine, backend, _ = engine_for(
        {
            "sticks": {
                "right": {
                    "mode": "scroll",
                    "speed": 10,
                    "deadzone": 0.0,
                    "curve": 1.0,
                    "smoothing": 0,
                }
            }
        }
    )
    engine.tick(0.0, make_state())
    for tick in range(1, 11):  # 10 clicks/s over 1.0 s
        engine.tick(tick * 0.1, make_state(right_y=-1.0))

    steps = [int(event.detail.split(",")[1]) for event in backend.events]
    assert steps, "the stick should have scrolled"
    assert all(step > 0 for step in steps), "pynput scrolls up with a positive dy"
    assert sum(steps) == pytest.approx(10, abs=1)


def test_stick_in_keys_mode_presses_direction_keys() -> None:
    engine, backend, _ = engine_for(
        {
            "sticks": {
                "left": {
                    "mode": "keys",
                    "threshold": 0.5,
                    "deadzone": 0.1,
                    "up": "key:w",
                    "down": "key:s",
                }
            }
        }
    )
    run_states(engine, [make_state(), make_state(left_y=-1.0), make_state()])
    assert backend.log() == ["key_down w", "key_up w"]


def test_keys_mode_ignores_deflection_below_the_threshold() -> None:
    engine, backend, _ = engine_for(
        {"sticks": {"left": {"mode": "keys", "threshold": 0.8, "deadzone": 0.0, "up": "key:w"}}}
    )
    run_states(engine, [make_state(), make_state(left_y=-0.5)])
    assert backend.log() == []


def test_an_off_stick_does_nothing() -> None:
    engine, backend, _ = engine_for({"sticks": {"left": {"mode": "off"}}})
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(left_x=1.0))
    assert backend.log() == []


def test_a_stalled_poll_does_not_fling_the_pointer() -> None:
    """A big gap between ticks is clamped, so waking from sleep doesn't teleport the cursor."""
    engine, backend, _ = engine_for(
        {
            "sticks": {
                "left": {
                    "mode": "mouse",
                    "speed": 1000,
                    "deadzone": 0.0,
                    "curve": 1.0,
                    "smoothing": 0,
                }
            }
        }
    )
    engine.tick(0.0, make_state())
    engine.tick(60.0, make_state(left_x=1.0))
    assert backend.log() == [f"mouse_move {int(1000 * MAX_TICK_SECONDS)},0"]


def test_the_first_tick_moves_nothing() -> None:
    """There is no previous timestamp to measure against, so no motion is invented."""
    engine, backend, _ = engine_for({"sticks": {"left": {"mode": "mouse", "speed": 1000}}})
    engine.tick(0.0, make_state(left_x=1.0))
    assert backend.log() == []


# --- Pause, quit and release safety -----------------------------------------


def test_pause_suppresses_output_and_resume_restores_it() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": "key:w", "back": "special:toggle_pause"}})
    run_states(engine, [make_state(), make_state(back=True), make_state()])
    assert engine.paused is True

    run_states(engine, [make_state(a=True), make_state()], start=1.0)
    assert backend.log() == [], "nothing may be emitted while paused"

    run_states(engine, [make_state(back=True), make_state()], start=2.0)
    assert engine.paused is False
    run_states(engine, [make_state(a=True), make_state()], start=3.0)
    assert backend.log() == ["key_down w", "key_up w"]


def test_pausing_releases_whatever_was_held() -> None:
    """Pausing mid-press must not leave the key down for the rest of the session."""
    engine, backend, _ = engine_for({"buttons": {"a": "key:w", "back": "special:toggle_pause"}})
    run_states(engine, [make_state(), make_state(a=True), make_state(a=True, back=True)])
    assert backend.log() == ["key_down w", "key_up w"]


def test_pause_does_not_move_the_pointer() -> None:
    engine, backend, _ = engine_for(
        {
            "buttons": {"back": "special:toggle_pause"},
            "sticks": {"left": {"mode": "mouse", "speed": 1000, "deadzone": 0.0}},
        }
    )
    run_states(engine, [make_state(), make_state(back=True)], step=0.1)
    engine.tick(0.5, make_state(left_x=1.0))
    assert backend.log() == []


def test_the_quit_special_stops_the_loop() -> None:
    engine, _, _ = engine_for({"buttons": {"start": "special:quit"}})
    engine.running = True
    run_states(engine, [make_state(), make_state(start=True)])
    assert engine.running is False


def test_release_all_lets_go_of_everything() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": "key:w", "b": "mouse:left"}})
    run_states(engine, [make_state(), make_state(a=True, b=True)])
    engine.release_all()
    assert sorted(backend.log()[-2:]) == ["key_up w", "mouse_up left"]


def test_release_all_is_safe_to_call_twice() -> None:
    engine, backend, _ = engine_for({"buttons": {"a": "key:w"}})
    run_states(engine, [make_state(), make_state(a=True)])
    engine.release_all()
    before = len(backend.events)
    engine.release_all()
    assert len(backend.events) == before


def test_status_messages_report_pause_state() -> None:
    messages: list[str] = []
    controller, backend = FakeController(), RecordingBackend()
    engine = Engine(load_profile("desktop"), controller, backend, on_status=messages.append)
    run_states(engine, [make_state(), make_state(back=True), make_state(), make_state(back=True)])
    assert messages == ["paused — output suppressed", "resumed"]


def test_set_paused_is_idempotent() -> None:
    messages: list[str] = []
    controller, backend = FakeController(), RecordingBackend()
    engine = Engine(load_profile("desktop"), controller, backend, on_status=messages.append)
    engine.set_paused(False)
    assert messages == []


# --- The run loop ------------------------------------------------------------


def test_run_polls_the_controller_and_releases_on_exit() -> None:
    controller, backend = FakeController(), RecordingBackend()
    profile = Profile.from_dict({"poll_hz": 100, "buttons": {"a": "key:w"}})
    ticks = iter(range(200))
    slept: list[float] = []

    engine = Engine(
        profile,
        controller,
        backend,
        clock=lambda: next(ticks) * 0.001,
        sleep=slept.append,
    )

    polls = {"count": 0}
    real_poll = controller.poll

    def counting_poll():
        polls["count"] += 1
        controller.state = make_state(a=True) if polls["count"] == 2 else make_state()
        if polls["count"] >= 4:
            engine.stop()
        return real_poll()

    controller.poll = counting_poll  # type: ignore[method-assign]
    engine.run()

    assert polls["count"] == 4
    assert backend.log() == ["key_down w", "key_up w"]
    assert engine.running is False
    assert slept, "the loop should sleep between polls to honour poll_hz"


# --- Calibration and drift ---------------------------------------------------

DRIFTING = {
    "device": {"auto_centre": False, "calibration": {"left_x": {"centre": 0.12}}},
    "sticks": {"left": {"mode": "mouse", "speed": 1000, "deadzone": 0.05, "smoothing": 0}},
}


def test_a_calibrated_drifting_stick_does_not_move_the_pointer() -> None:
    """The headline fix: a stick resting at +0.12 must not creep the cursor."""
    engine, backend, _ = engine_for(DRIFTING)
    engine.tick(0.0, make_state(left_x=0.12))
    for tick in range(1, 20):
        engine.tick(tick * 0.05, make_state(left_x=0.12))
    assert backend.log() == []


def test_the_same_drift_without_calibration_does_creep() -> None:
    """Proves the test above is actually testing calibration, not the deadzone."""
    engine, backend, _ = engine_for(
        {
            "device": {"auto_centre": False},
            "sticks": {"left": {"mode": "mouse", "speed": 1000, "deadzone": 0.05, "smoothing": 0}},
        }
    )
    engine.tick(0.0, make_state(left_x=0.12))
    for tick in range(1, 20):
        engine.tick(tick * 0.05, make_state(left_x=0.12))
    assert backend.log() != []


def test_calibration_still_reaches_full_speed_the_other_way() -> None:
    """Calibration must not cost travel on the side that was never drifting."""
    engine, backend, _ = engine_for(DRIFTING)
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(left_x=-1.0))
    assert backend.log() == ["mouse_move -100,0"]


def test_auto_centring_measures_rest_and_suppresses_motion_while_it_does() -> None:
    engine, backend, _ = engine_for(
        {
            "device": {"auto_centre": True},
            "sticks": {"left": {"mode": "mouse", "speed": 1000, "deadzone": 0.05, "smoothing": 0}},
        }
    )
    # A stick resting off-centre for the whole sampling window.
    for tick in range(40):
        engine.tick(tick * 0.02, make_state(left_x=0.12))
    assert backend.log() == [], "no motion while measuring"
    assert engine.calibration.axes["left_x"].centre == pytest.approx(0.12, abs=0.01)

    # And now that drift is gone for good.
    for tick in range(40, 80):
        engine.tick(tick * 0.02, make_state(left_x=0.12))
    assert backend.log() == []


def test_auto_centring_refuses_a_held_stick_and_says_so() -> None:
    messages: list[str] = []
    controller, backend = FakeController(), RecordingBackend()
    profile = Profile.from_dict({"device": {"auto_centre": True}, "buttons": {"a": "key:w"}})
    engine = Engine(profile, controller, backend, on_status=messages.append)
    for tick in range(40):
        engine.tick(tick * 0.02, make_state(left_x=0.95))
    assert any("auto-centre skipped" in message for message in messages)
    assert engine.calibration.is_empty


def test_buttons_still_work_while_auto_centring() -> None:
    """Only pointer motion waits for the measurement; buttons respond at once."""
    engine, backend, _ = engine_for({"device": {"auto_centre": True}, "buttons": {"a": "key:w"}})
    engine.tick(0.0, make_state())
    engine.tick(0.01, make_state(a=True))
    assert backend.log() == ["key_down w"]


# --- Smoothing and acceleration ----------------------------------------------


def test_smoothing_ramps_the_pointer_up_instead_of_jumping() -> None:
    engine, backend, _ = engine_for(
        {"sticks": {"left": {"mode": "mouse", "speed": 1000, "deadzone": 0.0, "curve": 1.0}}}
    )
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(left_x=1.0))
    first = int(backend.events[0].detail.split(",")[0])
    assert 0 < first < 100, "smoothed motion starts below the flat-out rate"


def test_acceleration_makes_a_sustained_push_faster_than_a_brief_one() -> None:
    profile = {
        "sticks": {
            "left": {
                "mode": "mouse",
                "speed": 500,
                "deadzone": 0.0,
                "curve": 1.0,
                "smoothing": 0,
                "accel": 4.0,
                "accel_time": 0.5,
            }
        }
    }
    engine, backend, _ = engine_for(profile)
    engine.tick(0.0, make_state())
    for tick in range(1, 21):
        engine.tick(tick * 0.05, make_state(left_x=1.0))
    moves = [int(event.detail.split(",")[0]) for event in backend.events]
    assert moves[-1] > moves[0] * 2, "speed should build while the stick is held out"


def test_precision_modifier_slows_the_pointer_while_held() -> None:
    profile = {
        "buttons": {"lb": "special:precision"},
        "sticks": {
            "left": {
                "mode": "mouse",
                "speed": 1000,
                "deadzone": 0.0,
                "curve": 1.0,
                "smoothing": 0,
                "precision": 0.25,
            }
        },
    }
    engine, backend, _ = engine_for(profile)
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(left_x=1.0))
    full = int(backend.events[-1].detail.split(",")[0])

    engine.tick(0.2, make_state(left_x=1.0, lb=True))
    assert engine.precision_held
    slowed = int(backend.events[-1].detail.split(",")[0])
    assert slowed == pytest.approx(full * 0.25, abs=1)

    engine.tick(0.3, make_state(left_x=1.0))
    assert not engine.precision_held


# --- Layers ------------------------------------------------------------------

LAYERED = {
    "device": {"auto_centre": False},
    "buttons": {"lb": "special:layer:media", "a": "mouse:left"},
    "layers": {"media": {"buttons": {"a": "key:media_play_pause"}}},
}


def test_a_layer_overrides_only_what_it_names() -> None:
    engine, backend, _ = engine_for(LAYERED)
    engine.tick(0.0, make_state())
    engine.tick(0.01, make_state(a=True))
    assert backend.log() == ["mouse_down left"]

    engine.tick(0.02, make_state())
    engine.tick(0.03, make_state(lb=True))
    assert engine.active_layers == ("media",)
    engine.tick(0.04, make_state(lb=True, a=True))
    assert backend.log()[-1] == "key_down media_play_pause"


def test_releasing_the_layer_button_closes_the_layer() -> None:
    engine, _, _ = engine_for(LAYERED)
    engine.tick(0.0, make_state())
    engine.tick(0.01, make_state(lb=True))
    assert engine.active_layers == ("media",)
    engine.tick(0.02, make_state())
    assert engine.active_layers == ()


def test_switching_layers_mid_hold_releases_the_outgoing_key() -> None:
    """Otherwise the old binding stays down with nothing left to release it."""
    engine, backend, _ = engine_for(LAYERED)
    engine.tick(0.0, make_state())
    engine.tick(0.01, make_state(a=True))
    assert backend.log() == ["mouse_down left"]

    engine.tick(0.02, make_state(a=True, lb=True))
    assert "mouse_up left" in backend.log(), "the base binding must be let go"
    assert backend.log()[-1] == "key_down media_play_pause"


def test_a_layer_can_bind_an_input_the_base_leaves_alone() -> None:
    engine, backend, _ = engine_for(
        {
            "device": {"auto_centre": False},
            "buttons": {"lb": "special:layer:extra"},
            "layers": {"extra": {"buttons": {"y": "key:f5"}}},
        }
    )
    engine.tick(0.0, make_state())
    engine.tick(0.01, make_state(y=True))
    assert backend.log() == [], "unbound in the base profile"
    engine.tick(0.02, make_state(lb=True, y=True))
    assert backend.log() == ["key_down f5"]


def test_a_layer_can_replace_a_whole_stick() -> None:
    engine, backend, _ = engine_for(
        {
            "device": {"auto_centre": False},
            "buttons": {"lb": "special:layer:scrollmode"},
            "sticks": {"left": {"mode": "mouse", "speed": 1000, "smoothing": 0, "deadzone": 0.0}},
            "layers": {
                "scrollmode": {
                    "sticks": {
                        "left": {"mode": "scroll", "speed": 10, "smoothing": 0, "deadzone": 0.0}
                    }
                }
            },
        }
    )
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(left_y=-1.0))
    assert backend.events[-1].kind == "mouse_move"
    engine.tick(0.2, make_state(left_y=-1.0, lb=True))
    engine.tick(0.3, make_state(left_y=-1.0, lb=True))
    assert backend.events[-1].kind == "scroll"


def test_releasing_everything_clears_the_layer_state() -> None:
    engine, _, _ = engine_for(LAYERED)
    engine.tick(0.0, make_state())
    engine.tick(0.01, make_state(lb=True, a=True))
    engine.release_all()
    assert engine._active == {}


# --- Hot reload --------------------------------------------------------------


def test_a_reloaded_profile_takes_effect_and_releases_what_was_held() -> None:
    controller, backend = FakeController(), RecordingBackend()
    messages: list[str] = []
    replacement = Profile.from_dict(
        {"name": "Second", "device": {"auto_centre": False}, "buttons": {"a": "key:z"}}
    )
    pending = [replacement]

    engine = Engine(
        Profile.from_dict(
            {"name": "First", "device": {"auto_centre": False}, "buttons": {"a": "key:w"}}
        ),
        controller,
        backend,
        on_status=messages.append,
        reload_source=lambda: pending.pop() if pending else None,
    )
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(a=True))
    assert backend.log() == ["key_down w"]

    # The reload check is rate-limited, so step past its interval.
    engine.tick(1.0, make_state(a=True))
    assert "key_up w" in backend.log(), "the old binding must not stay held"
    assert engine.profile.name == "Second"
    assert any("reloaded profile" in message for message in messages)

    engine.tick(1.1, make_state(a=True))
    assert backend.log()[-1] == "key_down z"


def test_reload_is_rate_limited_not_checked_every_tick() -> None:
    calls = {"count": 0}

    def source() -> Profile | None:
        calls["count"] += 1
        return None

    engine = Engine(
        Profile.from_dict({"device": {"auto_centre": False}}),
        FakeController(),
        RecordingBackend(),
        reload_source=source,
    )
    for tick in range(100):
        engine.tick(tick * 0.01)
    assert calls["count"] < 10, "should stat the file a couple of times a second, not 100"


def test_reload_keeps_the_centres_measured_at_startup() -> None:
    """The file changed; the hardware did not. Re-measuring would need idle thumbs."""
    controller, backend = FakeController(), RecordingBackend()
    replacement = Profile.from_dict({"name": "Second", "buttons": {"a": "key:z"}})
    pending = [replacement]
    engine = Engine(
        Profile.from_dict({"name": "First", "device": {"auto_centre": True}}),
        controller,
        backend,
        reload_source=lambda: pending.pop() if pending else None,
    )
    for tick in range(40):
        engine.tick(tick * 0.02, make_state(left_x=0.12))
    measured = engine.calibration.axes["left_x"].centre
    assert measured == pytest.approx(0.12, abs=0.01)

    engine.tick(5.0, make_state(left_x=0.12))
    assert engine.profile.name == "Second"
    assert engine.calibration.axes["left_x"].centre == pytest.approx(measured)
