"""Calibration — the part that actually fixes stick drift."""

from __future__ import annotations

import pytest

from padmap.calibration import (
    AxisCalibration,
    Calibration,
    CalibrationError,
    CentreSampler,
    RangeSampler,
    parse_calibration,
)

# --- The core claim ----------------------------------------------------------


def test_a_drifting_stick_reads_exactly_zero_at_rest() -> None:
    """The whole point: a stick resting at +0.12 must report nothing at all."""
    axis = AxisCalibration(centre=0.12, low=-0.95, high=0.88)
    assert axis.apply(0.12) == 0.0


def test_calibration_keeps_full_travel_on_both_sides() -> None:
    """Unlike a fat deadzone, calibration costs no range on the good side."""
    axis = AxisCalibration(centre=0.12, low=-0.95, high=0.88)
    assert axis.apply(0.88) == pytest.approx(1.0)
    assert axis.apply(-0.95) == pytest.approx(-1.0)


def test_each_side_is_scaled_independently() -> None:
    """Half-way to the high rail is 0.5 even though the rails aren't symmetric."""
    axis = AxisCalibration(centre=0.0, low=-0.5, high=1.0)
    assert axis.apply(0.5) == pytest.approx(0.5)
    assert axis.apply(-0.25) == pytest.approx(-0.5)


def test_readings_beyond_the_measured_range_are_clamped() -> None:
    axis = AxisCalibration(centre=0.0, low=-0.8, high=0.8)
    assert axis.apply(1.0) == 1.0
    assert axis.apply(-1.0) == -1.0


def test_an_uncalibrated_axis_passes_straight_through() -> None:
    assert Calibration().apply("left_x", 0.42) == 0.42
    assert Calibration().is_empty


def test_identity_calibration_is_recognised() -> None:
    assert AxisCalibration().is_identity
    assert not AxisCalibration(centre=0.05).is_identity


def test_nonsensical_bounds_are_rejected() -> None:
    with pytest.raises(CalibrationError, match="low < centre < high"):
        AxisCalibration(centre=0.5, low=0.6, high=0.9)


def test_merging_overlays_per_axis() -> None:
    base = Calibration(
        {"left_x": AxisCalibration(centre=0.1), "left_y": AxisCalibration(centre=0.2)}
    )
    overlay = Calibration({"left_y": AxisCalibration(centre=0.3)})
    merged = base.merged_with(overlay)
    assert merged.axes["left_x"].centre == 0.1
    assert merged.axes["left_y"].centre == 0.3


def test_with_centres_keeps_the_measured_range() -> None:
    """Re-centring at startup must not throw away a stored range measurement."""
    stored = Calibration({"left_x": AxisCalibration(centre=0.0, low=-0.9, high=0.85)})
    recentred = stored.with_centres({"left_x": 0.05})
    assert recentred.axes["left_x"].centre == 0.05
    assert recentred.axes["left_x"].low == -0.9
    assert recentred.axes["left_x"].high == 0.85


def test_with_centres_widens_bounds_when_it_has_to() -> None:
    """A centre near a rail must not produce an invalid low < centre < high."""
    recentred = Calibration().with_centres({"left_x": 0.9})
    axis = recentred.axes["left_x"]
    assert axis.low < axis.centre < axis.high


# --- Sampling ----------------------------------------------------------------


def test_centre_sampler_averages_the_rest_position() -> None:
    sampler = CentreSampler()
    for value in (0.10, 0.12, 0.14, 0.12):
        sampler.add({"left_x": value})
    assert sampler.centres()["left_x"] == pytest.approx(0.12)
    assert sampler.count == 4


def test_centre_sampler_refuses_a_held_stick() -> None:
    """Baking a held deflection in as 'centre' would break the pad permanently."""
    sampler = CentreSampler()
    for _ in range(10):
        sampler.add({"left_x": 0.9})
    with pytest.raises(CalibrationError, match="being held"):
        sampler.centres()


def test_centre_sampler_refuses_a_moving_stick() -> None:
    sampler = CentreSampler()
    for value in (-0.3, 0.3, -0.3, 0.3):
        sampler.add({"left_x": value})
    with pytest.raises(CalibrationError, match="being moved"):
        sampler.centres()


def test_centre_sampler_needs_samples() -> None:
    with pytest.raises(CalibrationError, match="no samples"):
        CentreSampler().centres()


def test_range_sampler_tracks_the_extremes() -> None:
    sampler = RangeSampler()
    for value in (0.0, 0.9, -0.85, 0.4):
        sampler.add({"left_x": value})
    calibration = sampler.build({"left_x": 0.0})
    assert calibration.axes["left_x"].high == pytest.approx(0.9)
    assert calibration.axes["left_x"].low == pytest.approx(-0.85)


def test_range_sampler_refuses_a_stick_that_barely_moved() -> None:
    """Rescaling a tiny sweep would turn noise into full-speed movement."""
    sampler = RangeSampler()
    for value in (-0.05, 0.05):
        sampler.add({"left_x": value})
    with pytest.raises(CalibrationError, match="roll both sticks"):
        sampler.build({"left_x": 0.0})


def test_range_sampler_needs_an_axis() -> None:
    with pytest.raises(CalibrationError, match="no axes"):
        RangeSampler().build({})


# --- Parsing -----------------------------------------------------------------


def test_parse_accepts_a_partial_block() -> None:
    calibration = parse_calibration({"left_x": {"centre": 0.1}})
    assert calibration.axes["left_x"].centre == 0.1
    assert calibration.axes["left_x"].low == -1.0


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ({"paddle": {"centre": 0.0}}, "unknown axis"),
        ({"left_x": {"middle": 0.0}}, "unknown key"),
        ({"left_x": {"centre": 5}}, "outside"),
        ({"left_x": {"centre": "middle"}}, "expected a number"),
        ({"left_x": {"centre": True}}, "expected a number"),
        ({"left_x": 0.1}, "expected an object"),
    ],
)
def test_parse_rejects_bad_blocks(block: dict, message: str) -> None:
    with pytest.raises(CalibrationError, match=message):
        parse_calibration(block)


def test_round_trips_through_to_dict() -> None:
    original = Calibration({"left_x": AxisCalibration(centre=0.125, low=-0.9, high=0.875)})
    assert parse_calibration(original.to_dict()).axes["left_x"] == original.axes["left_x"]
