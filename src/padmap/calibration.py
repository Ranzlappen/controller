"""Per-axis calibration: what "centred" and "fully deflected" mean on *your* pad.

A deadzone alone cannot fix a drifting stick. A deadzone is centred on zero, so
a stick that rests at ``x = +0.12`` can only be silenced by a deadzone big
enough to swallow 0.12 — which throws away the same 0.12 of travel on the
*other* side, where there was nothing wrong. The fix is to measure where the
stick actually rests and subtract it, which is what this module is for.

Calibration also handles the other half of the problem: a worn stick that only
reaches 0.88 instead of 1.0 never gets to full speed. Rescaling to the measured
range gives the full range back.

Pure data and pure functions — no controller, no clock — so the whole thing is
unit-testable with synthetic readings.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from padmap.curves import clamp

__all__ = [
    "AxisCalibration",
    "Calibration",
    "CalibrationError",
    "CentreSampler",
    "RangeSampler",
    "STICK_AXES",
]

#: The axes calibration applies to. Triggers are excluded: they are already
#: normalised to 0..1 by `devices.normalize_trigger`, and a short-throw trigger
#: is handled by lowering its binding threshold instead.
STICK_AXES: tuple[str, ...] = ("left_x", "left_y", "right_x", "right_y")

#: A rest reading further from zero than this means the stick was being held
#: during the sample, not resting. Calibrating from that would be worse than
#: not calibrating at all.
MAX_PLAUSIBLE_CENTRE = 0.35

#: A resting stick that swings more than this across the sample is being moved.
MAX_PLAUSIBLE_SPREAD = 0.20

#: Refuse to rescale to a range narrower than this — it would amplify noise
#: into full-speed movement.
MIN_PLAUSIBLE_RANGE = 0.30


class CalibrationError(ValueError):
    """Raised when a measurement is too implausible to calibrate from."""


@dataclass(frozen=True)
class AxisCalibration:
    """Where one axis rests, and how far it travels either side of that."""

    centre: float = 0.0
    low: float = -1.0
    high: float = 1.0

    def __post_init__(self) -> None:
        if not self.low < self.centre < self.high:
            raise CalibrationError(
                f"calibration must satisfy low < centre < high, got "
                f"low={self.low}, centre={self.centre}, high={self.high}"
            )

    def apply(self, raw: float) -> float:
        """Map a raw reading onto a true-centred, full-range ``[-1, 1]``.

        Each side is rescaled independently, so an off-centre rest position
        does not cost travel on the side that was never wrong.
        """
        if raw >= self.centre:
            span = self.high - self.centre
            return clamp((raw - self.centre) / span) if span > 0 else 0.0
        span = self.centre - self.low
        return clamp((raw - self.centre) / span) if span > 0 else 0.0

    @property
    def is_identity(self) -> bool:
        """True when this calibration would leave every reading unchanged."""
        return (self.centre, self.low, self.high) == (0.0, -1.0, 1.0)

    def to_dict(self) -> dict[str, float]:
        """The profile-JSON form of this axis."""
        return {
            "centre": round(self.centre, 4),
            "low": round(self.low, 4),
            "high": round(self.high, 4),
        }


@dataclass(frozen=True)
class Calibration:
    """Calibration for every stick axis. Missing axes pass through untouched."""

    axes: Mapping[str, AxisCalibration] = field(default_factory=dict)

    def apply(self, name: str, raw: float) -> float:
        """Calibrate one named axis, or return it unchanged if uncalibrated."""
        axis = self.axes.get(name)
        return raw if axis is None else axis.apply(raw)

    @property
    def is_empty(self) -> bool:
        """True when nothing here would change a reading."""
        return all(axis.is_identity for axis in self.axes.values())

    def merged_with(self, other: Calibration) -> Calibration:
        """Overlay ``other`` on top of this one, per axis."""
        return Calibration(axes={**self.axes, **other.axes})

    def with_centres(self, centres: Mapping[str, float]) -> Calibration:
        """Replace just the rest positions, keeping each axis's measured range.

        This is what auto-centring at startup does: the range from a stored
        calibration is still good, but the rest position is re-measured every
        run because that is the part that drifts.
        """
        axes = dict(self.axes)
        for name, centre in centres.items():
            existing = axes.get(name, AxisCalibration())
            low = min(existing.low, centre - MIN_PLAUSIBLE_RANGE)
            high = max(existing.high, centre + MIN_PLAUSIBLE_RANGE)
            axes[name] = AxisCalibration(centre=centre, low=low, high=high)
        return Calibration(axes=axes)

    def to_dict(self) -> dict[str, dict[str, float]]:
        """The profile-JSON form of the whole block."""
        return {name: axis.to_dict() for name, axis in sorted(self.axes.items())}


@dataclass
class CentreSampler:
    """Measures where the sticks rest, and refuses when they clearly aren't.

    Feeding it readings while the user happens to be holding a stick would bake
    that deflection in as "centre" and make the pad permanently wrong, so a
    sample that looks held or moving is rejected rather than trusted.
    """

    samples: dict[str, list[float]] = field(default_factory=dict)

    def add(self, readings: Mapping[str, float]) -> None:
        """Record one poll's worth of axis readings."""
        for name, value in readings.items():
            self.samples.setdefault(name, []).append(float(value))

    @property
    def count(self) -> int:
        """How many polls have been recorded."""
        return max((len(values) for values in self.samples.values()), default=0)

    def centres(self) -> dict[str, float]:
        """The measured rest position per axis.

        Raises :class:`CalibrationError` if any axis looks like it was being
        held or moved while sampling.
        """
        if not self.samples:
            raise CalibrationError("no samples recorded")
        result: dict[str, float] = {}
        for name, values in self.samples.items():
            if not values:
                continue
            mean = sum(values) / len(values)
            spread = max(values) - min(values)
            if abs(mean) > MAX_PLAUSIBLE_CENTRE:
                raise CalibrationError(
                    f"{name} rests at {mean:+.2f} — that looks like the stick was "
                    "being held. Let go of both sticks and try again."
                )
            if spread > MAX_PLAUSIBLE_SPREAD:
                raise CalibrationError(
                    f"{name} moved {spread:.2f} while sampling — that looks like the "
                    "stick was being moved. Let go of both sticks and try again."
                )
            result[name] = mean
        return result


@dataclass
class RangeSampler:
    """Measures how far each axis actually travels, from a full stick sweep."""

    lows: dict[str, float] = field(default_factory=dict)
    highs: dict[str, float] = field(default_factory=dict)

    def add(self, readings: Mapping[str, float]) -> None:
        """Record one poll, widening each axis's observed range."""
        for name, raw in readings.items():
            value = float(raw)
            self.lows[name] = min(self.lows.get(name, value), value)
            self.highs[name] = max(self.highs.get(name, value), value)

    def build(self, centres: Mapping[str, float]) -> Calibration:
        """Combine the swept ranges with measured centres into a calibration.

        Raises :class:`CalibrationError` if an axis barely moved — rescaling a
        tiny range would turn stick noise into full-speed cursor movement.
        """
        axes: dict[str, AxisCalibration] = {}
        for name, centre in centres.items():
            low = self.lows.get(name)
            high = self.highs.get(name)
            if low is None or high is None:
                continue
            if centre - low < MIN_PLAUSIBLE_RANGE or high - centre < MIN_PLAUSIBLE_RANGE:
                raise CalibrationError(
                    f"{name} only swept {low:+.2f}..{high:+.2f} around {centre:+.2f} — "
                    "roll both sticks right around their edge a few times and try again."
                )
            axes[name] = AxisCalibration(centre=centre, low=low, high=high)
        if not axes:
            raise CalibrationError("no axes were swept")
        return Calibration(axes=axes)


def parse_calibration(
    data: Mapping[str, object], known_axes: Iterable[str] = STICK_AXES
) -> Calibration:
    """Build a :class:`Calibration` from a profile's ``calibration`` block.

    Raises :class:`CalibrationError` with the offending path on bad input;
    :mod:`padmap.config` turns that into a ``ProfileError``.
    """
    valid = set(known_axes)
    axes: dict[str, AxisCalibration] = {}
    for name, raw in data.items():
        if name not in valid:
            raise CalibrationError(
                f"unknown axis {name!r}. Calibratable axes: {', '.join(sorted(valid))}"
            )
        if not isinstance(raw, Mapping):
            raise CalibrationError(f"{name}: expected an object with centre/low/high")
        unknown = sorted(set(raw) - {"centre", "low", "high"})
        if unknown:
            raise CalibrationError(
                f"{name}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
                "Valid: centre, low, high"
            )
        values: dict[str, float] = {}
        for key in ("centre", "low", "high"):
            if key not in raw:
                continue
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CalibrationError(f"{name}.{key}: expected a number")
            if not -1.0 <= float(value) <= 1.0:
                raise CalibrationError(f"{name}.{key}: {value} is outside [-1, 1]")
            values[key] = float(value)
        axes[name] = AxisCalibration(**values)
    return Calibration(axes=axes)
