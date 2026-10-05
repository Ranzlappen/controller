"""Breakpoints: mapping different actions to different ranges of one analogue input.

A trigger is not a button. It reports how far it is pulled, and the interesting
thing to do with that is bind *ranges* of it — a light pull walks, a hard pull
runs, the last stretch does something else again. The same applies to how far a
stick is pushed in a given direction.

The one thing a range-based binding must get right is **hysteresis**. A trigger
resting exactly on a boundary jitters across it many times a second, and
without a margin that would machine-gun two different actions. Once a zone is
active it keeps a little territory beyond its own edges, so leaving it takes a
deliberate movement.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

__all__ = ["DEFAULT_HYSTERESIS", "Zone", "ZoneError", "ZoneSet"]

#: Default margin a zone holds beyond its own edges once active. Comfortably
#: larger than the jitter of a trigger held still, small enough that deliberate
#: movement crosses it without feeling sticky.
DEFAULT_HYSTERESIS = 0.03

MIN_ZONE_WIDTH = 0.02


class ZoneError(ValueError):
    """Raised when a set of zones could not work as written."""


@dataclass(frozen=True)
class Zone:
    """One range of an analogue input, and what it does while the input is in it."""

    low: float
    high: float
    #: Whatever the caller wants attached. :mod:`padmap.config` puts a
    #: ``Binding`` here; keeping it untyped is what lets this module stay free
    #: of the schema.
    payload: object = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.low < self.high <= 1.0:
            raise ZoneError(
                f"a zone needs 0 <= from < to <= 1, got from={self.low:g} to={self.high:g}"
            )
        if self.high - self.low < MIN_ZONE_WIDTH:
            raise ZoneError(
                f"zone {self.low:g}..{self.high:g} is only {self.high - self.low:g} wide — "
                f"too narrow to hold reliably (minimum {MIN_ZONE_WIDTH:g})"
            )

    def contains(self, value: float) -> bool:
        """Whether ``value`` falls in this zone."""
        return self.low <= value <= self.high

    def contains_with_margin(self, value: float, margin: float) -> bool:
        """Whether ``value`` is still in this zone allowing for hysteresis."""
        return self.low - margin <= value <= self.high + margin

    def __str__(self) -> str:
        return f"{self.low:g}..{self.high:g}"


@dataclass(frozen=True)
class ZoneSet:
    """An ordered set of zones over one analogue input, with hysteresis."""

    zones: tuple[Zone, ...] = ()
    hysteresis: float = DEFAULT_HYSTERESIS

    def __post_init__(self) -> None:
        if not self.zones:
            raise ZoneError("a zone set needs at least one zone")
        if not 0.0 <= self.hysteresis <= 0.25:
            raise ZoneError(f"hysteresis {self.hysteresis:g} is outside [0, 0.25]")

    @property
    def threshold(self) -> float:
        """Where the first zone starts — the point the input becomes live."""
        return self.zones[0].low

    def __len__(self) -> int:
        return len(self.zones)

    def __iter__(self) -> Iterator[Zone]:
        return iter(self.zones)

    def payloads(self) -> tuple[object, ...]:
        """Everything attached to these zones, in order."""
        return tuple(zone.payload for zone in self.zones)

    def active(self, value: float, current: int | None = None) -> int | None:
        """Index of the zone ``value`` falls in, or None.

        ``current`` is the index that was active last time. Passing it is what
        applies hysteresis: the zone keeps its margin and only gives way once
        the input has clearly moved on. Overlapping zones resolve to the first
        match, so order is meaningful.
        """
        if (
            current is not None
            and 0 <= current < len(self.zones)
            and self.zones[current].contains_with_margin(value, self.hysteresis)
        ):
            return current
        for index, zone in enumerate(self.zones):
            if zone.contains(value):
                return index
        return None

    def describe(self) -> str:
        """One-line summary for ``padmap validate``."""
        if len(self.zones) == 1:
            return f"past {self.threshold:g}"
        return " | ".join(str(zone) for zone in self.zones)


def build_zones(
    spans: Sequence[tuple[float, float, object]],
    hysteresis: float = DEFAULT_HYSTERESIS,
    path: str = "zones",
) -> ZoneSet:
    """Build a :class:`ZoneSet`, reporting problems against ``path``.

    Gaps between zones are allowed and useful — a dead stretch at the start of
    a trigger's travel is often exactly what you want. Fully-nested zones are
    not: the inner one could never win, which is a mistake rather than a style.
    """
    try:
        zones = tuple(Zone(low=low, high=high, payload=payload) for low, high, payload in spans)
    except ZoneError as exc:
        raise ZoneError(f"{path}: {exc}") from exc

    for index, zone in enumerate(zones):
        for earlier in zones[:index]:
            if earlier.low <= zone.low and zone.high <= earlier.high:
                raise ZoneError(
                    f"{path}: zone {zone} sits entirely inside {earlier}, so it could never "
                    "be reached — earlier zones win on overlap"
                )
    try:
        return ZoneSet(zones=zones, hysteresis=hysteresis)
    except ZoneError as exc:
        raise ZoneError(f"{path}: {exc}") from exc


@dataclass
class ZoneTracker:
    """Remembers which zone each input was in, so hysteresis has something to bite on."""

    current: dict[str, int | None] = field(default_factory=dict)

    def update(self, slot: str, zone_set: ZoneSet, value: float) -> int | None:
        """Resolve and remember the active zone for one input."""
        active = zone_set.active(value, self.current.get(slot))
        self.current[slot] = active
        return active

    def clear(self) -> None:
        """Forget everything (on pause, reload, or shutdown)."""
        self.current.clear()
