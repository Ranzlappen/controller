"""Analogue-stick maths: deadzones, response curves, sub-pixel accumulation.

Pure functions and one tiny stateful accumulator — no controller, no output
backend, no clock. Stick feel is the part of a remapper people tune most, so it
lives on its own where it can be unit-tested exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "SubPixel",
    "apply_deadzone",
    "clamp",
    "normalize_trigger",
    "response_curve",
    "stick_vector",
]


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    """Constrain ``value`` to ``[low, high]``."""
    return max(low, min(high, value))


def apply_deadzone(value: float, deadzone: float) -> float:
    """Rescale a single axis so the deadzone edge is 0.0 and the rail stays 1.0.

    Without the rescale, a 0.2 deadzone means the stick jumps straight from
    nothing to 20% speed the moment it crosses the threshold. Rescaling keeps
    fine control available right at the edge of the deadzone.
    """
    deadzone = clamp(deadzone, 0.0, 0.99)
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    scaled = (magnitude - deadzone) / (1.0 - deadzone)
    return math.copysign(min(scaled, 1.0), value)


def response_curve(magnitude: float, exponent: float) -> float:
    """Shape a 0..1 magnitude.

    ``exponent`` 1.0 is linear. Above 1.0 gives a slow, precise centre with a
    fast outer range — the usual choice for pointing a mouse. Below 1.0 makes
    the stick twitchier near centre.
    """
    magnitude = clamp(magnitude, 0.0, 1.0)
    if exponent <= 0:
        raise ValueError(f"curve exponent must be > 0, got {exponent}")
    return magnitude**exponent


def stick_vector(
    x: float,
    y: float,
    deadzone: float = 0.15,
    curve: float = 2.0,
    invert_x: bool = False,
    invert_y: bool = False,
) -> tuple[float, float]:
    """Turn a raw stick reading into a shaped unit vector.

    Uses a *radial* deadzone (magnitude of the pair) rather than a per-axis
    one. A per-axis deadzone leaves a cross-shaped dead area that makes
    diagonals feel like they snap to the nearest axis.

    Returns ``(dx, dy)`` in ``[-1, 1]``, already curve-shaped, with SDL's
    y-up-is-negative convention preserved: pushing the stick up yields a
    negative ``dy``, which is also "up" in screen coordinates.
    """
    magnitude = math.hypot(x, y)
    if magnitude <= 0.0:
        return (0.0, 0.0)

    shaped = response_curve(apply_deadzone(magnitude, deadzone), curve)
    if shaped == 0.0:
        return (0.0, 0.0)

    # Re-project the shaped magnitude back onto the original direction.
    unit_x, unit_y = x / magnitude, y / magnitude
    dx = clamp(unit_x * shaped)
    dy = clamp(unit_y * shaped)
    if invert_x:
        dx = -dx
    if invert_y:
        dy = -dy
    return (dx, dy)


def normalize_trigger(raw: float, signed: bool = True) -> float:
    """Map a trigger axis onto ``[0, 1]``.

    SDL reports the Xbox triggers as ``-1`` (released) to ``1`` (pulled) on
    most drivers, but a few report ``0`` to ``1``. ``signed`` selects which;
    :mod:`padmap.devices` detects it at startup from the resting value.
    """
    value = (raw + 1.0) / 2.0 if signed else raw
    return clamp(value, 0.0, 1.0)


@dataclass
class SubPixel:
    """Carries fractional pixels between polls.

    At 120 Hz a gentle stick nudge is worth well under one pixel per tick.
    Truncating each tick independently would round all of that to zero and the
    cursor would simply refuse to move slowly. Keeping the remainder makes slow
    movement work at any poll rate.
    """

    remainder_x: float = field(default=0.0)
    remainder_y: float = field(default=0.0)

    def take(self, dx: float, dy: float) -> tuple[int, int]:
        """Add ``(dx, dy)`` to the carry and return the whole-pixel part."""
        self.remainder_x += dx
        self.remainder_y += dy
        whole_x = int(self.remainder_x)
        whole_y = int(self.remainder_y)
        self.remainder_x -= whole_x
        self.remainder_y -= whole_y
        return (whole_x, whole_y)

    def reset(self) -> None:
        """Drop any carried fraction (used when output is paused or stopped)."""
        self.remainder_x = 0.0
        self.remainder_y = 0.0
