"""Stick maths — the part people notice immediately when it is wrong."""

from __future__ import annotations

import math

import pytest

from padmap.curves import (
    Accelerator,
    Smoother,
    SubPixel,
    apply_deadzone,
    clamp,
    normalize_trigger,
    response_curve,
    stick_vector,
)


def test_clamp_bounds() -> None:
    assert clamp(5.0) == 1.0
    assert clamp(-5.0) == -1.0
    assert clamp(0.5, 0.0, 1.0) == 0.5


def test_deadzone_suppresses_drift_and_rescales_the_rest() -> None:
    assert apply_deadzone(0.1, 0.2) == 0.0
    # The edge of the deadzone maps to zero, the rail still maps to one.
    assert apply_deadzone(0.2, 0.2) == 0.0
    assert apply_deadzone(1.0, 0.2) == 1.0
    assert apply_deadzone(0.6, 0.2) == pytest.approx(0.5)


def test_deadzone_preserves_sign() -> None:
    assert apply_deadzone(-0.6, 0.2) == pytest.approx(-0.5)


def test_response_curve_shapes_the_middle_only() -> None:
    assert response_curve(0.0, 2.0) == 0.0
    assert response_curve(1.0, 2.0) == 1.0
    assert response_curve(0.5, 2.0) == pytest.approx(0.25)
    assert response_curve(0.5, 1.0) == pytest.approx(0.5)


def test_response_curve_rejects_a_useless_exponent() -> None:
    with pytest.raises(ValueError, match="curve exponent"):
        response_curve(0.5, 0.0)


def test_stick_at_rest_produces_nothing() -> None:
    assert stick_vector(0.0, 0.0) == (0.0, 0.0)
    assert stick_vector(0.05, 0.05, deadzone=0.15) == (0.0, 0.0)


def test_stick_up_is_negative_y_like_the_screen() -> None:
    _, dy = stick_vector(0.0, -1.0, deadzone=0.1, curve=1.0)
    assert dy == pytest.approx(-1.0)


def test_deadzone_is_radial_not_per_axis() -> None:
    """A diagonal just past the deadzone must survive; a per-axis deadzone eats it."""
    dx, dy = stick_vector(0.14, 0.14, deadzone=0.15, curve=1.0)
    assert math.hypot(dx, dy) > 0.0


def test_stick_keeps_its_direction_after_shaping() -> None:
    dx, dy = stick_vector(0.6, 0.6, deadzone=0.1, curve=2.0)
    assert dx == pytest.approx(dy)


def test_stick_inversion() -> None:
    dx, dy = stick_vector(1.0, 1.0, deadzone=0.0, curve=1.0, invert_x=True, invert_y=True)
    assert dx < 0 and dy < 0


def test_stick_output_never_exceeds_the_rail() -> None:
    dx, dy = stick_vector(1.0, 1.0, deadzone=0.0, curve=0.5)
    assert abs(dx) <= 1.0 and abs(dy) <= 1.0


@pytest.mark.parametrize(
    ("raw", "signed", "expected"),
    [(-1.0, True, 0.0), (0.0, True, 0.5), (1.0, True, 1.0), (0.0, False, 0.0), (1.0, False, 1.0)],
)
def test_trigger_normalisation(raw: float, signed: bool, expected: float) -> None:
    assert normalize_trigger(raw, signed) == pytest.approx(expected)


def test_subpixel_carries_fractions_so_slow_movement_still_moves() -> None:
    carry = SubPixel()
    emitted = [carry.take(0.4, 0.0)[0] for _ in range(5)]
    assert emitted == [0, 0, 1, 0, 1]
    assert sum(emitted) == 2


def test_subpixel_handles_negative_deltas() -> None:
    carry = SubPixel()
    assert [carry.take(-0.6, 0.0)[0] for _ in range(2)] == [0, -1]


def test_subpixel_reset_drops_the_carry() -> None:
    carry = SubPixel()
    carry.take(0.9, 0.9)
    carry.reset()
    assert carry.take(0.2, 0.2) == (0, 0)


# --- Smoothing ---------------------------------------------------------------


def test_smoothing_off_passes_the_value_straight_through() -> None:
    smoother = Smoother(strength=0.0)
    assert smoother.update(0.7, -0.2, 1 / 120) == (0.7, -0.2)


def test_smoothing_approaches_the_target_without_overshooting() -> None:
    smoother = Smoother(strength=0.5)
    values = [smoother.update(1.0, 0.0, 1 / 120)[0] for _ in range(40)]
    assert values == sorted(values), "should rise monotonically"
    assert all(value <= 1.0 for value in values), "must never overshoot"
    assert values[-1] == pytest.approx(1.0, abs=0.05)


def test_smoothing_settles_to_exactly_zero_on_release() -> None:
    """An exponential decay never reaches zero — so the pointer would creep forever."""
    smoother = Smoother(strength=0.9)
    smoother.update(1.0, 1.0, 0.5)
    for _ in range(500):
        smoother.update(0.0, 0.0, 1 / 120)
    assert (smoother.x, smoother.y) == (0.0, 0.0)


def test_smoothing_is_frame_rate_independent() -> None:
    """Same elapsed time, same result — whatever the poll rate in between."""
    fast = Smoother(strength=0.5)
    for _ in range(40):
        fast.update(1.0, 0.0, 0.005)
    slow = Smoother(strength=0.5)
    for _ in range(10):
        slow.update(1.0, 0.0, 0.02)
    assert fast.x == pytest.approx(slow.x, abs=0.01)


def test_smoothing_survives_a_zero_delta() -> None:
    smoother = Smoother(strength=0.5)
    assert smoother.update(1.0, 0.0, 0.0) == (1.0, 0.0)


def test_smoothing_reset_clears_history() -> None:
    smoother = Smoother(strength=0.5)
    smoother.update(1.0, 1.0, 0.1)
    smoother.reset()
    assert (smoother.x, smoother.y) == (0.0, 0.0)


# --- Acceleration ------------------------------------------------------------


def test_acceleration_off_is_always_unity() -> None:
    accelerator = Accelerator(factor=1.0)
    assert [accelerator.update(1.0, 0.1) for _ in range(10)] == [1.0] * 10


def test_acceleration_ramps_to_the_factor_and_stops_there() -> None:
    accelerator = Accelerator(factor=3.0, ramp_seconds=0.6)
    values = [accelerator.update(1.0, 0.1) for _ in range(10)]
    assert values[0] < values[3] < 3.0
    assert values[-1] == pytest.approx(3.0)


def test_acceleration_only_builds_past_the_threshold() -> None:
    """Small deflections are 'aiming', not 'travelling' — they must stay precise."""
    accelerator = Accelerator(factor=3.0, threshold=0.7)
    assert [accelerator.update(0.3, 0.1) for _ in range(10)][-1] == 1.0


def test_acceleration_decays_faster_than_it_builds() -> None:
    """A brief correction should drop you back to precision, not stay in travel mode."""
    accelerator = Accelerator(factor=3.0, ramp_seconds=0.6, decay_multiplier=3.0)
    for _ in range(10):
        accelerator.update(1.0, 0.1)
    assert accelerator.update(0.0, 0.1) < 3.0
    assert accelerator.update(0.0, 0.2) == 1.0


def test_acceleration_reset() -> None:
    accelerator = Accelerator(factor=3.0)
    for _ in range(10):
        accelerator.update(1.0, 0.1)
    accelerator.reset()
    assert accelerator.update(1.0, 0.0) == 1.0


# --- Outer deadzone ----------------------------------------------------------


def test_outer_deadzone_lets_a_short_stick_reach_full_speed() -> None:
    assert apply_deadzone(0.9, 0.15, outer=0.9) == pytest.approx(1.0)


def test_outer_deadzone_defaults_to_the_full_rail() -> None:
    assert apply_deadzone(0.9, 0.15) == apply_deadzone(0.9, 0.15, outer=1.0)


def test_outer_deadzone_cannot_collapse_onto_the_inner_one() -> None:
    """An outer below the inner would divide by ~zero; it is clamped apart instead."""
    assert apply_deadzone(0.5, 0.5, outer=0.1) == 0.0, "on the deadzone edge is still dead"
    assert apply_deadzone(0.6, 0.5, outer=0.1) == pytest.approx(1.0)
