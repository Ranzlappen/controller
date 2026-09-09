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
    """Build an engine from an inline profile document."""
    backend = backend or RecordingBackend()
    controller = FakeController()
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
        {"sticks": {"left": {"mode": "mouse", "speed": 1000, "deadzone": 0.1, "curve": 1.0}}}
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
        {"sticks": {"left": {"mode": "mouse", "speed": 500, "deadzone": 0.0, "curve": 1.0}}}
    )
    engine.tick(0.0, make_state())
    engine.tick(0.1, make_state(left_y=-1.0))
    assert backend.log() == ["mouse_move 0,-50"], "negative dy is up on screen"


def test_stick_in_scroll_mode_scrolls_up_when_pushed_up() -> None:
    engine, backend, _ = engine_for(
        {"sticks": {"right": {"mode": "scroll", "speed": 10, "deadzone": 0.0, "curve": 1.0}}}
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
        {"sticks": {"left": {"mode": "mouse", "speed": 1000, "deadzone": 0.0, "curve": 1.0}}}
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
