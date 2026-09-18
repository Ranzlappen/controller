"""Analogue-stick maths: deadzones, response curves, sub-pixel accumulation.

Pure functions and one tiny stateful accumulator — no controller, no output
backend, no clock. Stick feel is the part of a remapper people tune most, so it
lives on its own where it can be unit-tested exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "Accelerator",
    "Smoother",
    "SubPixel",
    "apply_deadzone",
    "clamp",
    "normalize_trigger",
    "response_curve",
    "stick_vector",
]

#: Smoothing strength 1.0 corresponds to this time constant, in seconds. Chosen
#: so the top of the range still feels attached to your thumb: much beyond
#: ~150 ms and the pointer reads as laggy rather than steady.
SMOOTHING_TAU_SECONDS = 0.14

#: Below this, a smoothed value on its way to rest is snapped to zero. An
#: exponential decay never actually reaches zero, and a pointer that keeps
#: creeping a pixel every few seconds after you let go is exactly the bug
#: smoothing was added to fix.
SMOOTHING_SNAP = 0.002


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    """Constrain ``value`` to ``[low, high]``."""
    return max(low, min(high, value))


def apply_deadzone(value: float, deadzone: float, outer: float = 1.0) -> float:
    """Rescale a single axis so the deadzone edge is 0.0 and ``outer`` is 1.0.

    Without the rescale, a 0.2 deadzone means the stick jumps straight from
    nothing to 20% speed the moment it crosses the threshold. Rescaling keeps
    fine control available right at the edge of the deadzone.

    ``outer`` is the deflection that should count as fully pushed. Lowering it
    below 1.0 lets a worn stick that can only reach, say, 0.9 still hit full
    speed; calibration is the better fix, but this works without measuring.
    """
    deadzone = clamp(deadzone, 0.0, 0.99)
    outer = clamp(outer, deadzone + 0.01, 1.0)
    magnitude = abs(value)
    if magnitude <= deadzone:
        return 0.0
    scaled = (magnitude - deadzone) / (outer - deadzone)
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
    outer: float = 1.0,
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

    shaped = response_curve(apply_deadzone(magnitude, deadzone, outer), curve)
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


@dataclass
class Smoother:
    """Exponential smoothing over the stick vector, to kill ADC jitter.

    A stick sitting still still reports small random wobble, and past the
    deadzone that wobble goes straight to the pointer — which is most of what
    "the cursor won't hold still" actually is. Averaging over a short window
    removes it at the cost of a little lag.

    The coefficient is recomputed from the real elapsed time each tick, so the
    feel is the same at 60 Hz and at 250 Hz, and a stalled poll does not cause
    a lurch.
    """

    strength: float = 0.0
    x: float = field(default=0.0)
    y: float = field(default=0.0)

    def update(self, target_x: float, target_y: float, dt: float) -> tuple[float, float]:
        """Fold a new reading in and return the smoothed vector."""
        strength = clamp(self.strength, 0.0, 1.0)
        if strength <= 0.0 or dt <= 0.0:
            self.x, self.y = target_x, target_y
            return (self.x, self.y)

        tau = strength * SMOOTHING_TAU_SECONDS
        alpha = 1.0 - math.exp(-dt / tau)
        self.x += alpha * (target_x - self.x)
        self.y += alpha * (target_y - self.y)

        # Let go of the stick and the pointer must actually stop, not decay
        # towards zero forever.
        if target_x == 0.0 and abs(self.x) < SMOOTHING_SNAP:
            self.x = 0.0
        if target_y == 0.0 and abs(self.y) < SMOOTHING_SNAP:
            self.y = 0.0
        return (self.x, self.y)

    def reset(self) -> None:
        """Forget the history (used when output pauses or the profile reloads)."""
        self.x = 0.0
        self.y = 0.0


@dataclass
class Accelerator:
    """Ramps pointer speed up while the stick is held out near its edge.

    This is what lets one stick be both precise and fast. A flat speed forces a
    choice: low enough to click a checkbox means crawling across the screen,
    fast enough to cross the screen means overshooting everything. Holding the
    stick out is an unambiguous "I am travelling", so speed builds; easing off
    drops it back immediately.

    Decay is deliberately quicker than the ramp, so a brief correction returns
    you to precision instead of staying in travel mode.
    """

    factor: float = 1.0
    ramp_seconds: float = 0.6
    threshold: float = 0.7
    decay_multiplier: float = 3.0
    elapsed: float = field(default=0.0)

    def update(self, magnitude: float, dt: float) -> float:
        """Advance the ramp for this tick and return the speed multiplier."""
        if dt > 0.0:
            if magnitude >= self.threshold:
                self.elapsed = min(self.elapsed + dt, self.ramp_seconds)
            else:
                self.elapsed = max(0.0, self.elapsed - dt * self.decay_multiplier)
        if self.factor <= 1.0 or self.ramp_seconds <= 0.0:
            return 1.0
        progress = self.elapsed / self.ramp_seconds
        return 1.0 + (self.factor - 1.0) * clamp(progress, 0.0, 1.0)

    def reset(self) -> None:
        """Drop back to unaccelerated speed."""
        self.elapsed = 0.0
