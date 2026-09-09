"""Controller discovery and polling.

The vocabulary of input names (``a``, ``lb``, ``left_x``, ``rt`` …) lives here
because it is device knowledge: a *layout* is the mapping from those names onto
the raw SDL indices a particular driver happens to expose.

pygame is imported lazily, inside the functions that actually touch hardware,
so ``import padmap.devices`` stays cheap and the pure translation helpers
(:func:`build_state`, :func:`hat_to_dpad`, :class:`Layout`) are testable with
no controller and no display attached.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from padmap.curves import normalize_trigger

__all__ = [
    "AXIS_NAMES",
    "BUTTON_NAMES",
    "DEFAULT_LAYOUT",
    "DPAD_NAMES",
    "DeviceError",
    "DeviceInfo",
    "Layout",
    "PadState",
    "PygameController",
    "STICK_NAMES",
    "TRIGGER_NAMES",
    "build_state",
    "hat_to_dpad",
    "list_devices",
    "open_controller",
]


class DeviceError(RuntimeError):
    """Raised when no usable controller can be opened."""


#: Face buttons, bumpers and stick clicks, in the SDL order an Xbox pad reports.
BUTTON_NAMES: tuple[str, ...] = (
    "a",
    "b",
    "x",
    "y",
    "lb",
    "rb",
    "back",
    "start",
    "ls",
    "rs",
    "guide",
)

#: Analogue axes. Triggers are axes on an Xbox pad, not buttons.
AXIS_NAMES: tuple[str, ...] = ("left_x", "left_y", "right_x", "right_y", "lt", "rt")

DPAD_NAMES: tuple[str, ...] = ("up", "down", "left", "right")
STICK_NAMES: tuple[str, ...] = ("left", "right")
TRIGGER_NAMES: tuple[str, ...] = ("lt", "rt")

#: Every name a profile may bind, for validation error messages.
INPUT_NAMES: frozenset[str] = frozenset(BUTTON_NAMES) | frozenset(AXIS_NAMES)

TRIGGER_MODES: frozenset[str] = frozenset({"auto", "signed", "unipolar"})


@dataclass(frozen=True)
class Layout:
    """Which raw SDL index each named input lives at.

    The defaults are the standard SDL2 Xbox mapping, which covers the wired and
    wireless Xbox One pads on Windows (XInput), Linux (``xpad``) and macOS. A
    profile can override any entry when a driver disagrees — run
    ``padmap monitor`` to see what your pad actually reports.
    """

    buttons: dict[str, int]
    axes: dict[str, int]
    trigger_mode: str = "auto"
    #: Axis pair some Linux drivers use for the d-pad when it is not a hat.
    dpad_axes: tuple[int, int] = (6, 7)

    def with_overrides(self, overrides: dict[str, int] | None) -> Layout:
        """Return a copy with ``name -> index`` overrides applied."""
        if not overrides:
            return self
        buttons = dict(self.buttons)
        axes = dict(self.axes)
        for name, index in overrides.items():
            if name in buttons:
                buttons[name] = index
            elif name in axes:
                axes[name] = index
            else:
                raise DeviceError(
                    f"unknown input {name!r} in device.layout. Valid names: "
                    f"{', '.join(sorted(INPUT_NAMES))}"
                )
        return replace(self, buttons=buttons, axes=axes)


DEFAULT_LAYOUT = Layout(
    buttons={
        "a": 0,
        "b": 1,
        "x": 2,
        "y": 3,
        "lb": 4,
        "rb": 5,
        "back": 6,
        "start": 7,
        "ls": 8,
        "rs": 9,
        "guide": 10,
    },
    axes={"left_x": 0, "left_y": 1, "lt": 2, "right_x": 3, "right_y": 4, "rt": 5},
)


@dataclass(frozen=True)
class DeviceInfo:
    """What ``padmap devices`` prints about one attached controller."""

    index: int
    name: str
    guid: str
    axes: int
    buttons: int
    hats: int


@dataclass(frozen=True)
class PadState:
    """One snapshot of the controller.

    ``axes`` holds sticks in ``[-1, 1]`` (y negative = up, SDL's convention)
    and triggers already normalised to ``[0, 1]``.
    """

    buttons: dict[str, bool]
    axes: dict[str, float]
    dpad: dict[str, bool]

    def button(self, name: str) -> bool:
        """Read a button, defaulting to "not pressed" if the pad lacks it."""
        return self.buttons.get(name, False)

    def axis(self, name: str) -> float:
        """Read an axis, defaulting to centred if the pad lacks it."""
        return self.axes.get(name, 0.0)


def empty_state() -> PadState:
    """A neutral state — every button up, every axis centred."""
    return PadState(
        buttons=dict.fromkeys(BUTTON_NAMES, False),
        axes=dict.fromkeys(AXIS_NAMES, 0.0),
        dpad=dict.fromkeys(DPAD_NAMES, False),
    )


def hat_to_dpad(hat: tuple[int, int]) -> dict[str, bool]:
    """Convert an SDL hat reading to named d-pad directions.

    SDL hats are ``(x, y)`` with ``y = 1`` meaning up — the opposite sign to
    the sticks, which is exactly the sort of thing worth pinning in a test.
    """
    x, y = hat
    return {"up": y > 0, "down": y < 0, "left": x < 0, "right": x > 0}


def axes_to_dpad(x: float, y: float, threshold: float = 0.5) -> dict[str, bool]:
    """Convert a d-pad-as-axis-pair reading (some Linux drivers) to directions.

    Unlike a hat, these axes follow the stick convention: ``y = -1`` is up.
    """
    return {
        "up": y <= -threshold,
        "down": y >= threshold,
        "left": x <= -threshold,
        "right": x >= threshold,
    }


def build_state(
    raw_buttons: Sequence[float],
    raw_axes: Sequence[float],
    raw_hats: Sequence[tuple[int, int]],
    layout: Layout = DEFAULT_LAYOUT,
    signed_triggers: bool = True,
) -> PadState:
    """Translate raw SDL readings into a named :class:`PadState`.

    Indices the attached pad does not expose are reported as released/centred
    rather than raising, so a third-party pad with fewer axes still works for
    every input it does have.
    """
    buttons = {
        name: bool(raw_buttons[index]) if 0 <= index < len(raw_buttons) else False
        for name, index in layout.buttons.items()
    }

    axes: dict[str, float] = {}
    for name, index in layout.axes.items():
        if not 0 <= index < len(raw_axes):
            # A pad that does not expose this axis reads as centred / released.
            axes[name] = 0.0
        elif name in TRIGGER_NAMES:
            axes[name] = normalize_trigger(float(raw_axes[index]), signed_triggers)
        else:
            axes[name] = float(raw_axes[index])

    if raw_hats:
        dpad = hat_to_dpad(raw_hats[0])
    else:
        hat_x, hat_y = layout.dpad_axes
        dpad = axes_to_dpad(
            float(raw_axes[hat_x]) if 0 <= hat_x < len(raw_axes) else 0.0,
            float(raw_axes[hat_y]) if 0 <= hat_y < len(raw_axes) else 0.0,
        )

    return PadState(buttons=buttons, axes=axes, dpad=dpad)


class ControllerSource(Protocol):
    """What the engine needs from an input source — one poll and a close."""

    name: str

    def poll(self) -> PadState:
        """Return the controller's current state."""
        ...  # pragma: no cover

    def close(self) -> None:
        """Release the device."""
        ...  # pragma: no cover


def _pygame() -> Any:  # pragma: no cover - thin import shim, needs the real package
    """Import pygame on demand with a friendly message if it is missing."""
    try:
        import pygame
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise DeviceError(
            "pygame is not installed. Install padmap's dependencies with "
            "`pip install -e .` (or `pip install pygame`)."
        ) from exc
    return pygame


def _init_joystick() -> Any:  # pragma: no cover - needs the real package
    """Bring up just the joystick subsystem, with no video window."""
    pygame = _pygame()
    # A remapper never opens a window; the dummy driver keeps SDL from trying.
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    pygame.joystick.init()
    return pygame


def list_devices() -> list[DeviceInfo]:  # pragma: no cover - needs hardware
    """Enumerate every controller SDL can see."""
    pygame = _init_joystick()
    found: list[DeviceInfo] = []
    for index in range(pygame.joystick.get_count()):
        stick = pygame.joystick.Joystick(index)
        stick.init()
        found.append(
            DeviceInfo(
                index=index,
                name=stick.get_name(),
                guid=stick.get_guid(),
                axes=stick.get_numaxes(),
                buttons=stick.get_numbuttons(),
                hats=stick.get_numhats(),
            )
        )
    return found


def select_device(
    devices: Sequence[DeviceInfo], match: str | None, index: int | None
) -> DeviceInfo:
    """Pick one device by explicit index, by name substring, or the first one."""
    if not devices:
        raise DeviceError(
            "no controller detected. Plug in the pad (or pair it), then run `padmap devices`."
        )
    if index is not None:
        for device in devices:
            if device.index == index:
                return device
        raise DeviceError(f"no controller at index {index}. Run `padmap devices` to list them.")
    if match:
        needle = match.lower()
        for device in devices:
            if needle in device.name.lower():
                return device
        names = ", ".join(repr(d.name) for d in devices)
        raise DeviceError(f"no controller matching {match!r}. Attached: {names}")
    return devices[0]


class PygameController:  # pragma: no cover - exercised only with real hardware
    """A single opened controller, polled through pygame/SDL2."""

    def __init__(self, joystick: Any, pygame_module: Any, layout: Layout = DEFAULT_LAYOUT) -> None:
        self._joystick = joystick
        self._pygame = pygame_module
        self.layout = layout
        self.name: str = joystick.get_name()
        self.index: int = joystick.get_instance_id()
        self._signed_triggers = layout.trigger_mode != "unipolar"
        if layout.trigger_mode == "auto":
            self._signed_triggers = self._detect_signed_triggers()

    def _detect_signed_triggers(self) -> bool:
        """Decide whether the triggers rest at -1 (signed) or 0 (unipolar).

        Sampled at rest, before the user has touched anything. A driver that
        rests at -1 is signed; one that rests at 0 is not. Pin it explicitly in
        the profile (``device.trigger_mode``) if a pad guesses wrong.
        """
        self._pygame.event.pump()
        resting = []
        for name in TRIGGER_NAMES:
            index = self.layout.axes.get(name)
            if index is not None and 0 <= index < self._joystick.get_numaxes():
                resting.append(self._joystick.get_axis(index))
        return bool(resting) and min(resting) <= -0.5

    def poll(self) -> PadState:
        """Pump SDL's queue and read every input."""
        self._pygame.event.pump()
        buttons = [self._joystick.get_button(i) for i in range(self._joystick.get_numbuttons())]
        axes = [self._joystick.get_axis(i) for i in range(self._joystick.get_numaxes())]
        hats = [self._joystick.get_hat(i) for i in range(self._joystick.get_numhats())]
        return build_state(buttons, axes, hats, self.layout, self._signed_triggers)

    def poll_raw(self) -> tuple[list[float], list[float], list[tuple[int, int]]]:
        """Raw readings, for ``padmap monitor`` to display while authoring a layout."""
        self._pygame.event.pump()
        return (
            [self._joystick.get_button(i) for i in range(self._joystick.get_numbuttons())],
            [self._joystick.get_axis(i) for i in range(self._joystick.get_numaxes())],
            [self._joystick.get_hat(i) for i in range(self._joystick.get_numhats())],
        )

    def close(self) -> None:
        """Release the joystick and shut the subsystem down."""
        self._joystick.quit()
        self._pygame.joystick.quit()
        self._pygame.quit()


def open_controller(
    match: str | None = None,
    index: int | None = None,
    layout: Layout = DEFAULT_LAYOUT,
) -> PygameController:  # pragma: no cover - needs hardware
    """Open the controller a profile asks for."""
    pygame = _init_joystick()
    device = select_device(list_devices(), match, index)
    joystick = pygame.joystick.Joystick(device.index)
    joystick.init()
    return PygameController(joystick, pygame, layout)
