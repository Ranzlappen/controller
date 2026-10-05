"""Breakpoint zones, and the hysteresis that makes them usable."""

from __future__ import annotations

import pytest

from padmap.zones import DEFAULT_HYSTERESIS, Zone, ZoneError, ZoneSet, ZoneTracker, build_zones


def walk_run() -> ZoneSet:
    return build_zones([(0.1, 0.5, "walk"), (0.5, 1.0, "run")])


def test_a_zone_knows_what_it_contains() -> None:
    zone = Zone(low=0.2, high=0.6, payload="x")
    assert zone.contains(0.4)
    assert not zone.contains(0.7)
    assert zone.contains_with_margin(0.65, 0.05)


@pytest.mark.parametrize(
    ("low", "high", "message"),
    [
        (0.5, 0.1, "from < to"),
        (-0.1, 0.5, "from < to"),
        (0.5, 1.5, "from < to"),
        (0.3, 0.31, "too narrow"),
    ],
)
def test_impossible_zones_are_rejected(low: float, high: float, message: str) -> None:
    with pytest.raises(ZoneError, match=message):
        Zone(low=low, high=high)


def test_a_zone_set_needs_a_zone() -> None:
    with pytest.raises(ZoneError, match="at least one"):
        ZoneSet(zones=())


def test_out_of_range_hysteresis_is_rejected() -> None:
    with pytest.raises(ZoneError, match="hysteresis"):
        ZoneSet(zones=(Zone(0.1, 0.9),), hysteresis=0.9)


def test_a_fully_nested_zone_is_rejected() -> None:
    """It could never win, since earlier zones take precedence — that's a mistake."""
    with pytest.raises(ZoneError, match="entirely inside"):
        build_zones([(0.1, 1.0, "outer"), (0.3, 0.6, "inner")])


def test_gaps_between_zones_are_allowed() -> None:
    """A dead stretch at the start of a trigger's travel is often the point."""
    zones = build_zones([(0.1, 0.3, "a"), (0.6, 1.0, "b")])
    assert zones.active(0.45) is None


def test_the_threshold_is_where_the_first_zone_starts() -> None:
    assert walk_run().threshold == 0.1


def test_values_below_every_zone_select_nothing() -> None:
    assert walk_run().active(0.05) is None


def test_zones_select_by_value() -> None:
    zones = walk_run()
    assert zones.zones[zones.active(0.3)].payload == "walk"
    assert zones.zones[zones.active(0.8)].payload == "run"


def test_hysteresis_holds_the_zone_you_arrived_from() -> None:
    """A trigger resting on a boundary must not machine-gun two actions."""
    zones = walk_run()
    # Arriving at the boundary from below stays below.
    assert zones.active(0.52, current=0) == 0
    # Arriving from above stays above.
    assert zones.active(0.48, current=1) == 1
    # Moving decisively does switch.
    assert zones.active(0.7, current=0) == 1
    assert zones.active(0.3, current=1) == 0


def test_hysteresis_of_zero_switches_at_the_boundary() -> None:
    zones = build_zones([(0.1, 0.5, "a"), (0.5, 1.0, "b")], hysteresis=0.0)
    assert zones.active(0.51, current=0) == 1


def test_a_stale_current_index_is_ignored() -> None:
    assert walk_run().active(0.3, current=99) == 0


def test_overlapping_zones_resolve_to_the_first() -> None:
    zones = build_zones([(0.1, 0.6, "first"), (0.5, 1.0, "second")])
    assert zones.zones[zones.active(0.55)].payload == "first"


def test_describe_reads_usefully() -> None:
    assert walk_run().describe() == "0.1..0.5 | 0.5..1"
    assert build_zones([(0.3, 1.0, "x")]).describe() == "past 0.3"


def test_iteration_and_payloads() -> None:
    zones = walk_run()
    assert len(zones) == 2
    assert zones.payloads() == ("walk", "run")
    assert [zone.payload for zone in zones] == ["walk", "run"]


def test_build_errors_name_their_path() -> None:
    with pytest.raises(ZoneError, match=r"triggers\.rt\.zones"):
        build_zones([(0.5, 0.1, "x")], path="triggers.rt.zones")


# --- The tracker -------------------------------------------------------------


def test_the_tracker_remembers_per_slot() -> None:
    zones = walk_run()
    tracker = ZoneTracker()
    assert tracker.update("rt", zones, 0.3) == 0
    assert tracker.update("lt", zones, 0.8) == 1
    # Each slot keeps its own history, so one trigger's position cannot drag
    # the other's hysteresis around.
    assert tracker.update("rt", zones, 0.52) == 0
    assert tracker.update("lt", zones, 0.48) == 1


def test_a_full_sweep_up_and_down_is_stable() -> None:
    zones = walk_run()
    tracker = ZoneTracker()
    up = [tracker.update("rt", zones, value / 100) for value in range(0, 101, 4)]
    switches = sum(1 for a, b in zip(up, up[1:], strict=False) if a != b)
    assert switches == 2, "none -> walk -> run, and no chatter in between"


def test_clearing_the_tracker_forgets_hysteresis() -> None:
    zones = walk_run()
    tracker = ZoneTracker()
    tracker.update("rt", zones, 0.8)
    tracker.clear()
    assert tracker.update("rt", zones, 0.48) == 0, "no history to stick to"


def test_default_hysteresis_is_wider_than_trigger_jitter() -> None:
    assert DEFAULT_HYSTERESIS > 0.01
