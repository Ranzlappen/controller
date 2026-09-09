"""Shared fixtures.

Everything here exists so the mapping logic can be exercised without a
controller, a display, or any synthetic input reaching the machine running the
tests.
"""

from __future__ import annotations

import pytest

from padmap.backends import RecordingBackend
from padmap.config import Profile, load_profile
from padmap.devices import PadState, empty_state
from padmap.engine import Engine


def make_state(**inputs: bool | float) -> PadState:
    """Build a :class:`PadState` from named inputs, defaulting the rest to neutral.

    ``make_state(a=True, left_x=1.0, up=True)`` sets the A button, pushes the
    left stick fully right, and presses d-pad up.
    """
    neutral = empty_state()
    buttons = dict(neutral.buttons)
    axes = dict(neutral.axes)
    dpad = dict(neutral.dpad)
    for name, value in inputs.items():
        if name in buttons:
            buttons[name] = bool(value)
        elif name in axes:
            axes[name] = float(value)
        elif name in dpad:
            dpad[name] = bool(value)
        else:
            raise KeyError(f"unknown input {name!r}")
    return PadState(buttons=buttons, axes=axes, dpad=dpad)


class FakeController:
    """A controller whose state the test sets directly."""

    def __init__(self, state: PadState | None = None) -> None:
        self.name = "Fake Xbox Pad"
        self.state = state or empty_state()
        self.closed = False

    def poll(self) -> PadState:
        """Return whatever state the test last assigned."""
        return self.state

    def close(self) -> None:
        """Record that the engine released the device."""
        self.closed = True


@pytest.fixture
def controller() -> FakeController:
    """A fake controller sitting at rest."""
    return FakeController()


@pytest.fixture
def backend() -> RecordingBackend:
    """A backend that records instead of typing."""
    return RecordingBackend()


@pytest.fixture
def build_engine(controller: FakeController, backend: RecordingBackend):
    """Factory: build an engine around a bundled profile (or a given one)."""

    def _build(profile: str | Profile = "desktop") -> Engine:
        loaded = load_profile(profile) if isinstance(profile, str) else profile
        return Engine(loaded, controller, backend)

    return _build


def press(engine: Engine, states, start: float = 0.0, step: float = 0.01) -> None:
    """Feed a sequence of states to the engine at a fixed tick interval."""
    for index, state in enumerate(states):
        engine.tick(start + index * step, state)
