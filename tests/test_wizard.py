"""Setup wizard: the decisions, not the prompting."""

from __future__ import annotations

import json

import pytest

from conftest import FakeController, make_state
from padmap.calibration import AxisCalibration, Calibration
from padmap.config import Profile
from padmap.wizard import (
    IDENTIFY_ORDER,
    Measurements,
    assemble_profile,
    detect_axis_move,
    detect_press,
    layout_overrides,
    sample_axes,
    suggest,
    trigger_warnings,
    unmapped_buttons,
)

CALIBRATED = Calibration({"left_x": AxisCalibration(centre=0.18, low=-0.95, high=0.9)})


# --- Identifying inputs ------------------------------------------------------


def test_a_single_rising_edge_is_the_button() -> None:
    assert detect_press([0, 0, 0], [0, 1, 0]) == 1


def test_two_buttons_at_once_is_refused_rather_than_guessed() -> None:
    """Recording the wrong raw index is worse than asking the user again."""
    assert detect_press([0, 0, 0], [1, 1, 0]) is None


def test_an_already_held_button_is_not_a_press() -> None:
    assert detect_press([0, 1], [0, 1]) is None


def test_a_release_is_not_a_press() -> None:
    assert detect_press([1, 0], [0, 0]) is None


def test_a_pad_reporting_more_buttons_than_the_baseline_is_handled() -> None:
    assert detect_press([0], [0, 1]) == 1


def test_axis_move_finds_the_furthest_travelled() -> None:
    assert detect_axis_move([0.0, -1.0, -1.0], [0.0, -1.0, 0.9]) == (2, 0.9)


def test_axis_move_ignores_jitter() -> None:
    assert detect_axis_move([0.0, 0.0], [0.02, -0.01]) is None


def test_identify_order_covers_the_face_buttons_first() -> None:
    names = [name for name, _ in IDENTIFY_ORDER]
    assert names[:4] == ["a", "b", "x", "y"]
    assert "guide" in names


# --- Suggestions -------------------------------------------------------------


def test_a_calibrated_pad_gets_a_small_deadzone() -> None:
    """The headline consequence of calibrating: the deadzone only clears noise."""
    measured = Measurements(drift=0.18, noise=0.012, calibration=CALIBRATED)
    assert suggest(measured).deadzone <= 0.08


def test_an_uncalibrated_pad_still_needs_a_deadzone_over_its_drift() -> None:
    measured = Measurements(drift=0.18, noise=0.012)
    chosen = suggest(measured)
    assert chosen.deadzone > 0.18
    assert "drift" in chosen.reasons["deadzone"]


def test_a_noisy_pad_gets_more_smoothing() -> None:
    assert (
        suggest(Measurements(noise=0.05)).smoothing > suggest(Measurements(noise=0.005)).smoothing
    )


def test_the_trigger_threshold_clears_a_resting_pull() -> None:
    measured = Measurements(trigger_rest={"lt": 0.22, "rt": 0.0})
    assert suggest(measured).trigger_threshold > 0.22


def test_gaming_turns_acceleration_off_and_raises_the_poll_rate() -> None:
    """Aim should stay linear; pointing should not."""
    gaming = suggest(Measurements(), gaming=True)
    desktop = suggest(Measurements(), gaming=False)
    assert gaming.accel == 1.0
    assert desktop.accel > 1.0
    assert gaming.poll_hz > desktop.poll_hz


def test_every_suggestion_comes_with_a_reason() -> None:
    for setting, _value, reason in suggest(Measurements()).rows():
        assert reason, f"{setting} is proposed without saying why"


def test_deadzone_is_bounded_even_for_a_wrecked_stick() -> None:
    assert suggest(Measurements(drift=0.9, noise=0.4)).deadzone <= 0.3


# --- Measurements ------------------------------------------------------------


def test_trigger_travel_is_the_worst_of_the_two() -> None:
    measured = Measurements(
        trigger_rest={"lt": 0.0, "rt": 0.0}, trigger_full={"lt": 1.0, "rt": 0.4}
    )
    assert measured.trigger_travel == pytest.approx(0.4)


def test_trigger_travel_with_nothing_measured_is_zero() -> None:
    assert Measurements().trigger_travel == 0.0


def test_a_short_trigger_sweep_is_called_out() -> None:
    measured = Measurements(trigger_rest={"lt": 0.0}, trigger_full={"lt": 0.2})
    assert any("travelled" in note for note in trigger_warnings(measured))


def test_a_trigger_resting_high_is_called_out() -> None:
    measured = Measurements(
        trigger_rest={"lt": 0.3, "rt": 0.0}, trigger_full={"lt": 1.0, "rt": 1.0}
    )
    notes = trigger_warnings(measured)
    assert any("trigger_mode" in note for note in notes)


def test_a_trigger_never_seen_is_called_out() -> None:
    assert any("never saw it move" in note for note in trigger_warnings(Measurements()))


def test_healthy_triggers_produce_no_noise() -> None:
    measured = Measurements(
        trigger_rest={"lt": 0.0, "rt": 0.0}, trigger_full={"lt": 1.0, "rt": 1.0}
    )
    assert trigger_warnings(measured) == []


# --- Layout ------------------------------------------------------------------


def test_only_indices_that_differ_are_pinned() -> None:
    """Redundant overrides are noise, and they pin what could have adapted."""
    assert layout_overrides({"a": 0, "b": 1, "x": 7}) == {"x": 7}


def test_unknown_names_are_not_pinned() -> None:
    assert layout_overrides({"paddle": 12}) == {}


def test_buttons_never_seen_are_reported() -> None:
    missing = unmapped_buttons({"a": 0, "b": 1})
    assert "guide" in missing
    assert "a" not in missing


# --- Assembled profile -------------------------------------------------------


@pytest.mark.parametrize("gaming", [False, True])
def test_the_generated_profile_loads(gaming: bool) -> None:
    """Whatever the wizard writes must survive `padmap validate`."""
    measured = Measurements(
        drift=0.18,
        noise=0.012,
        calibration=CALIBRATED,
        trigger_rest={"lt": 0.0, "rt": 0.0},
        trigger_full={"lt": 1.0, "rt": 1.0},
        layout={"x": 7},
    )
    document = assemble_profile("Mine", measured, suggest(measured, gaming), "Xbox", gaming)
    profile = Profile.from_dict(json.loads(json.dumps(document)))
    assert profile.name == "Mine"
    assert profile.binding_count > 10


def test_the_generated_profile_always_offers_a_pause_button() -> None:
    document = assemble_profile("Mine", Measurements(), suggest(Measurements()))
    profile = Profile.from_dict(document)
    commands = {binding.action.command for binding in profile.buttons.values()}
    assert "toggle_pause" in commands


def test_measured_calibration_and_layout_reach_the_profile() -> None:
    measured = Measurements(calibration=CALIBRATED, layout={"x": 7})
    document = assemble_profile("Mine", measured, suggest(measured), "Xbox One Controller")
    profile = Profile.from_dict(document)
    assert profile.device.calibration.axes["left_x"].centre == pytest.approx(0.18)
    assert profile.device.layout.buttons["x"] == 7
    assert profile.device.match == "Xbox One Controller"


def test_an_unmeasured_pad_produces_a_profile_with_no_calibration_block() -> None:
    document = assemble_profile("Mine", Measurements(), suggest(Measurements()))
    assert "calibration" not in document["device"]
    assert "layout" not in document["device"]


def test_the_desktop_profile_gets_the_nav_layer_and_the_gaming_one_does_not() -> None:
    desktop = assemble_profile("D", Measurements(), suggest(Measurements()), gaming=False)
    gaming = assemble_profile("G", Measurements(), suggest(Measurements(), True), gaming=True)
    assert "layers" in desktop
    assert "layers" not in gaming
    assert gaming["sticks"]["left"]["mode"] == "keys"


# --- Sampling ----------------------------------------------------------------


def test_sample_axes_polls_for_the_window_it_was_given() -> None:
    controller = FakeController(make_state(left_x=0.2))
    now = [0.0]
    seen: list[dict] = []
    polls = sample_axes(
        controller,
        0.1,
        seen.append,
        clock=lambda: now[0],
        sleep=lambda _s: now.__setitem__(0, now[0] + 0.01),
    )
    assert polls == pytest.approx(10, abs=1)
    assert seen[0]["left_x"] == pytest.approx(0.2)
