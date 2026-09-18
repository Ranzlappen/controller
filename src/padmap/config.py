"""Profile schema: loading, validating and describing a mapping.

A profile is plain JSON so it can be edited without touching Python. Validation
is deliberately strict — unknown keys are rejected rather than ignored, because
a silently-ignored typo in a remapper looks exactly like broken hardware.

Every error carries the path of the offending value (``sticks.left.curve``) so
the message points straight at the line to fix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from padmap.actions import Action, ActionError, parse_action
from padmap.calibration import Calibration, CalibrationError, parse_calibration
from padmap.devices import (
    BUTTON_NAMES,
    DPAD_NAMES,
    STICK_NAMES,
    TRIGGER_MODES,
    TRIGGER_NAMES,
    DeviceError,
    Layout,
)

__all__ = [
    "Binding",
    "DeviceConfig",
    "Layer",
    "Profile",
    "ProfileError",
    "StickConfig",
    "TriggerConfig",
    "bundled_profile_names",
    "load_profile",
    "load_profile_file",
    "starter_profile_json",
]

STICK_MODES: frozenset[str] = frozenset({"mouse", "scroll", "keys", "off"})

DEFAULT_POLL_HZ = 120.0
DEFAULT_DEADZONE = 0.15
DEFAULT_CURVE = 2.0
DEFAULT_MOUSE_SPEED = 900.0
DEFAULT_SCROLL_SPEED = 12.0
DEFAULT_STICK_THRESHOLD = 0.6
DEFAULT_TRIGGER_THRESHOLD = 0.5
DEFAULT_SCROLL_REPEAT_HZ = 15.0

# Smoothing defaults to *on*. A raw stick reading carries enough jitter to make
# the pointer visibly unsteady, and nobody wants that; 0.35 takes the wobble out
# while still feeling attached to your thumb. Set "smoothing": 0 for the raw feel.
DEFAULT_SMOOTHING = 0.35
# Acceleration defaults to *off*, because it changes the feel enough that it
# should be a choice. The bundled profiles opt in.
DEFAULT_ACCEL = 1.0
DEFAULT_ACCEL_TIME = 0.6
DEFAULT_OUTER_DEADZONE = 1.0
# How much a held `special:precision` binding slows this stick.
DEFAULT_PRECISION = 0.25


class ProfileError(ValueError):
    """Raised when a profile is malformed, or names something that doesn't exist."""


# --- Validation helpers ------------------------------------------------------


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileError(f"{path}: expected an object, got {type(value).__name__}")
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], path: str, hint: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ProfileError(
            f"{path}: unknown {hint} {', '.join(repr(k) for k in unknown)}. "
            f"Valid: {', '.join(sorted(allowed))}"
        )


def _number(value: Any, path: str, low: float, high: float, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{path}: expected a number, got {type(value).__name__}")
    number = float(value)
    if not low <= number <= high:
        raise ProfileError(f"{path}: {number} is out of range [{low}, {high}]")
    return number


def _boolean(value: Any, path: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ProfileError(f"{path}: expected true or false, got {type(value).__name__}")
    return value


def _text(value: Any, path: str, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ProfileError(f"{path}: expected a string, got {type(value).__name__}")
    return value


# --- Schema ------------------------------------------------------------------


@dataclass(frozen=True)
class Binding:
    """One action plus how holding the input should behave."""

    action: Action
    #: Auto-fire rate in presses per second while held. 0 disables turbo.
    turbo_hz: float = 0.0
    #: When true, a press latches the action on and the next press releases it.
    toggle: bool = False
    #: Re-fire rate for repeatable actions (scroll) while the input is held.
    repeat_hz: float = DEFAULT_SCROLL_REPEAT_HZ

    @property
    def is_noop(self) -> bool:
        """True when this binding does nothing."""
        return self.action.is_noop

    @classmethod
    def parse(cls, raw: Any, path: str) -> Binding:
        """Build a binding from either ``"key:w"`` or ``{"action": "key:w", ...}``."""
        if raw is None or isinstance(raw, str):
            return cls(action=_parse_action(raw, path))

        data = _mapping(raw, path)
        _reject_unknown(data, {"action", "turbo", "toggle", "repeat"}, path, "option")
        binding = cls(
            action=_parse_action(data.get("action"), f"{path}.action"),
            turbo_hz=_number(data.get("turbo"), f"{path}.turbo", 0.0, 100.0, 0.0),
            toggle=_boolean(data.get("toggle"), f"{path}.toggle"),
            repeat_hz=_number(
                data.get("repeat"), f"{path}.repeat", 0.1, 200.0, DEFAULT_SCROLL_REPEAT_HZ
            ),
        )
        if binding.turbo_hz and binding.toggle:
            raise ProfileError(f"{path}: 'turbo' and 'toggle' cannot both be set")
        return binding


def _parse_action(raw: Any, path: str) -> Action:
    try:
        return parse_action(raw)
    except ActionError as exc:
        raise ProfileError(f"{path}: {exc}") from exc


@dataclass(frozen=True)
class TriggerConfig:
    """An analogue trigger treated as a button past a pull threshold."""

    binding: Binding
    threshold: float = DEFAULT_TRIGGER_THRESHOLD

    @classmethod
    def parse(cls, raw: Any, path: str) -> TriggerConfig:
        """Build from ``"mouse:left"`` or ``{"action": ..., "threshold": 0.5}``."""
        if raw is None or isinstance(raw, str):
            return cls(binding=Binding.parse(raw, path))
        data = _mapping(raw, path)
        threshold = _number(
            data.get("threshold"), f"{path}.threshold", 0.05, 1.0, DEFAULT_TRIGGER_THRESHOLD
        )
        binding_data = {k: v for k, v in data.items() if k != "threshold"}
        return cls(binding=Binding.parse(binding_data, path), threshold=threshold)


@dataclass(frozen=True)
class StickConfig:
    """How one analogue stick behaves.

    ``mouse`` moves the cursor, ``scroll`` scrolls, ``keys`` emits directional
    key presses past a threshold (the WASD case), ``off`` ignores the stick.
    """

    mode: str = "off"
    deadzone: float = DEFAULT_DEADZONE
    outer_deadzone: float = DEFAULT_OUTER_DEADZONE
    curve: float = DEFAULT_CURVE
    speed: float = DEFAULT_MOUSE_SPEED
    smoothing: float = DEFAULT_SMOOTHING
    accel: float = DEFAULT_ACCEL
    accel_time: float = DEFAULT_ACCEL_TIME
    precision: float = DEFAULT_PRECISION
    invert_x: bool = False
    invert_y: bool = False
    threshold: float = DEFAULT_STICK_THRESHOLD
    directions: dict[str, Binding] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        """True when the stick does anything at all."""
        return self.mode != "off"

    @classmethod
    def parse(cls, raw: Any, path: str) -> StickConfig:
        """Build a stick config, defaulting speed to suit the chosen mode."""
        data = _mapping(raw, path)
        allowed = {
            "mode",
            "deadzone",
            "outer_deadzone",
            "curve",
            "speed",
            "smoothing",
            "accel",
            "accel_time",
            "precision",
            "invert_x",
            "invert_y",
            "threshold",
        }
        _reject_unknown(data, allowed | set(DPAD_NAMES), path, "option")

        mode = _text(data.get("mode"), f"{path}.mode", "off").lower()
        if mode not in STICK_MODES:
            raise ProfileError(
                f"{path}.mode: unknown mode {mode!r}. Valid: {', '.join(sorted(STICK_MODES))}"
            )

        default_speed = DEFAULT_SCROLL_SPEED if mode == "scroll" else DEFAULT_MOUSE_SPEED
        directions = {
            name: Binding.parse(data[name], f"{path}.{name}") for name in DPAD_NAMES if name in data
        }
        if mode == "keys" and not directions:
            raise ProfileError(
                f"{path}: mode 'keys' needs at least one of {', '.join(DPAD_NAMES)} bound"
            )

        deadzone = _number(data.get("deadzone"), f"{path}.deadzone", 0.0, 0.95, DEFAULT_DEADZONE)
        outer = _number(
            data.get("outer_deadzone"),
            f"{path}.outer_deadzone",
            0.1,
            1.0,
            DEFAULT_OUTER_DEADZONE,
        )
        if outer <= deadzone:
            raise ProfileError(
                f"{path}.outer_deadzone: {outer:g} must be greater than "
                f"deadzone ({deadzone:g}) — there would be no travel between them"
            )

        return cls(
            mode=mode,
            deadzone=deadzone,
            outer_deadzone=outer,
            curve=_number(data.get("curve"), f"{path}.curve", 0.1, 6.0, DEFAULT_CURVE),
            speed=_number(data.get("speed"), f"{path}.speed", 0.0, 10000.0, default_speed),
            smoothing=_number(
                data.get("smoothing"), f"{path}.smoothing", 0.0, 1.0, DEFAULT_SMOOTHING
            ),
            accel=_number(data.get("accel"), f"{path}.accel", 1.0, 10.0, DEFAULT_ACCEL),
            accel_time=_number(
                data.get("accel_time"), f"{path}.accel_time", 0.05, 5.0, DEFAULT_ACCEL_TIME
            ),
            precision=_number(
                data.get("precision"), f"{path}.precision", 0.01, 1.0, DEFAULT_PRECISION
            ),
            invert_x=_boolean(data.get("invert_x"), f"{path}.invert_x"),
            invert_y=_boolean(data.get("invert_y"), f"{path}.invert_y"),
            threshold=_number(
                data.get("threshold"), f"{path}.threshold", 0.05, 1.0, DEFAULT_STICK_THRESHOLD
            ),
            directions=directions,
        )


@dataclass(frozen=True)
class DeviceConfig:
    """Which controller to open, and how to read it."""

    match: str | None = None
    index: int | None = None
    layout: Layout = field(default_factory=lambda: _default_layout())
    calibration: Calibration = field(default_factory=Calibration)
    #: Re-measure the sticks' rest position at startup. On by default: where a
    #: stick rests is the part that drifts with wear, and measuring it costs a
    #: fraction of a second. Set false to trust the stored calibration only.
    auto_centre: bool = True

    @classmethod
    def parse(cls, raw: Any, path: str = "device") -> DeviceConfig:
        """Build from the profile's ``device`` block."""
        if raw is None:
            return cls()
        data = _mapping(raw, path)
        _reject_unknown(
            data,
            {"match", "index", "trigger_mode", "layout", "calibration", "auto_centre"},
            path,
            "option",
        )

        index = data.get("index")
        if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
            raise ProfileError(f"{path}.index: expected an integer, got {type(index).__name__}")

        trigger_mode = _text(data.get("trigger_mode"), f"{path}.trigger_mode", "auto").lower()
        if trigger_mode not in TRIGGER_MODES:
            raise ProfileError(
                f"{path}.trigger_mode: unknown mode {trigger_mode!r}. "
                f"Valid: {', '.join(sorted(TRIGGER_MODES))}"
            )

        overrides = data.get("layout")
        if overrides is not None:
            overrides = _mapping(overrides, f"{path}.layout")
            for name, value in overrides.items():
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ProfileError(f"{path}.layout.{name}: expected an integer index")
        try:
            layout = _default_layout(trigger_mode).with_overrides(overrides)
        except DeviceError as exc:
            raise ProfileError(f"{path}.layout: {exc}") from exc

        try:
            calibration = parse_calibration(
                _mapping(data.get("calibration") or {}, f"{path}.calibration")
            )
        except CalibrationError as exc:
            raise ProfileError(f"{path}.calibration.{exc}") from exc

        return cls(
            match=_text(data.get("match"), f"{path}.match") or None,
            index=index,
            layout=layout,
            calibration=calibration,
            auto_centre=_boolean(data.get("auto_centre"), f"{path}.auto_centre", True),
        )


def _default_layout(trigger_mode: str = "auto") -> Layout:
    from padmap.devices import DEFAULT_LAYOUT

    return Layout(
        buttons=dict(DEFAULT_LAYOUT.buttons),
        axes=dict(DEFAULT_LAYOUT.axes),
        trigger_mode=trigger_mode,
        dpad_axes=DEFAULT_LAYOUT.dpad_axes,
    )


def _parse_sections(
    data: dict[str, Any], prefix: str, allow_specials: bool
) -> tuple[
    dict[str, Binding], dict[str, Binding], dict[str, TriggerConfig], dict[str, StickConfig]
]:
    """Parse the four binding sections shared by the base profile and layers.

    ``allow_specials`` is False inside a layer. Specials are always resolved
    from the base profile so that "which layer am I in" can never itself depend
    on which layer you are in — an ordering knot with no good answer. Rejecting
    them at load time is friendlier than silently ignoring them at runtime.
    """
    buttons_raw = _mapping(data.get("buttons") or {}, f"{prefix}buttons")
    _reject_unknown(buttons_raw, set(BUTTON_NAMES), f"{prefix}buttons", "button")

    dpad_raw = _mapping(data.get("dpad") or {}, f"{prefix}dpad")
    _reject_unknown(dpad_raw, set(DPAD_NAMES), f"{prefix}dpad", "direction")

    triggers_raw = _mapping(data.get("triggers") or {}, f"{prefix}triggers")
    _reject_unknown(triggers_raw, set(TRIGGER_NAMES), f"{prefix}triggers", "trigger")

    sticks_raw = _mapping(data.get("sticks") or {}, f"{prefix}sticks")
    _reject_unknown(sticks_raw, set(STICK_NAMES), f"{prefix}sticks", "stick")

    buttons = {n: Binding.parse(v, f"{prefix}buttons.{n}") for n, v in buttons_raw.items()}
    dpad = {n: Binding.parse(v, f"{prefix}dpad.{n}") for n, v in dpad_raw.items()}
    triggers = {n: TriggerConfig.parse(v, f"{prefix}triggers.{n}") for n, v in triggers_raw.items()}
    sticks = {n: StickConfig.parse(v, f"{prefix}sticks.{n}") for n, v in sticks_raw.items()}

    if not allow_specials:
        for label, bindings in (("buttons", buttons), ("dpad", dpad)):
            for name, binding in bindings.items():
                if binding.action.kind == "special":
                    raise ProfileError(
                        f"{prefix}{label}.{name}: a layer cannot contain a special "
                        f"({binding.action}). Bind specials in the base profile so layer "
                        "switching never depends on the active layer."
                    )
        for name, trigger in triggers.items():
            if trigger.binding.action.kind == "special":
                raise ProfileError(
                    f"{prefix}triggers.{name}: a layer cannot contain a special "
                    f"({trigger.binding.action}). Bind specials in the base profile."
                )

    return buttons, dpad, triggers, sticks


@dataclass(frozen=True)
class Layer:
    """An alternate set of bindings, active while its button is held.

    This is the "shift set" idea: an Xbox pad has ten buttons, which runs out
    fast. Holding one of them to reach a second full set of bindings is the
    cheapest way to get more without adding hardware.

    Only the inputs a layer names are overridden; everything else keeps doing
    what the base profile says.
    """

    name: str
    buttons: dict[str, Binding] = field(default_factory=dict)
    dpad: dict[str, Binding] = field(default_factory=dict)
    triggers: dict[str, TriggerConfig] = field(default_factory=dict)
    sticks: dict[str, StickConfig] = field(default_factory=dict)
    description: str = ""

    @classmethod
    def parse(cls, name: str, raw: Any, path: str) -> Layer:
        """Validate one entry of the profile's ``layers`` section."""
        data = _mapping(raw, path)
        _reject_unknown(
            data, {"description", "buttons", "dpad", "triggers", "sticks"}, path, "section"
        )
        buttons, dpad, triggers, sticks = _parse_sections(data, f"{path}.", allow_specials=False)
        if not (buttons or dpad or triggers or sticks):
            raise ProfileError(f"{path}: layer binds nothing — give it at least one binding")
        return cls(
            name=name,
            buttons=buttons,
            dpad=dpad,
            triggers=triggers,
            sticks=sticks,
            description=_text(data.get("description"), f"{path}.description"),
        )

    @property
    def binding_count(self) -> int:
        """How many inputs this layer overrides."""
        return (
            sum(1 for b in self.buttons.values() if not b.is_noop)
            + sum(1 for b in self.dpad.values() if not b.is_noop)
            + sum(1 for t in self.triggers.values() if not t.binding.is_noop)
            + sum(1 for s in self.sticks.values() if s.active)
        )


@dataclass(frozen=True)
class Profile:
    """A complete mapping: what every input on the pad does."""

    name: str = "Untitled"
    description: str = ""
    poll_hz: float = DEFAULT_POLL_HZ
    device: DeviceConfig = field(default_factory=DeviceConfig)
    buttons: dict[str, Binding] = field(default_factory=dict)
    dpad: dict[str, Binding] = field(default_factory=dict)
    triggers: dict[str, TriggerConfig] = field(default_factory=dict)
    sticks: dict[str, StickConfig] = field(default_factory=dict)
    layers: dict[str, Layer] = field(default_factory=dict)
    source: str = ""

    @classmethod
    def from_dict(cls, data: Any, source: str = "") -> Profile:
        """Validate a parsed JSON object into a :class:`Profile`."""
        data = _mapping(data, "profile")
        _reject_unknown(
            data,
            {
                "name",
                "description",
                "poll_hz",
                "device",
                "buttons",
                "dpad",
                "triggers",
                "sticks",
                "layers",
            },
            "profile",
            "section",
        )

        buttons, dpad, triggers, sticks = _parse_sections(data, "", allow_specials=True)

        layers_raw = _mapping(data.get("layers") or {}, "layers")
        layers = {
            name.lower(): Layer.parse(name.lower(), raw, f"layers.{name}")
            for name, raw in layers_raw.items()
        }

        profile = cls(
            name=_text(data.get("name"), "profile.name", "Untitled"),
            description=_text(data.get("description"), "profile.description"),
            poll_hz=_number(data.get("poll_hz"), "profile.poll_hz", 10.0, 1000.0, DEFAULT_POLL_HZ),
            device=DeviceConfig.parse(data.get("device")),
            buttons=buttons,
            dpad=dpad,
            triggers=triggers,
            sticks=sticks,
            layers=layers,
            source=source,
        )
        _check_layer_references(profile)
        return profile

    @property
    def binding_count(self) -> int:
        """How many inputs this profile actually binds — the summary line's number."""
        total = sum(1 for b in self.buttons.values() if not b.is_noop)
        total += sum(1 for b in self.dpad.values() if not b.is_noop)
        total += sum(1 for t in self.triggers.values() if not t.binding.is_noop)
        total += sum(1 for s in self.sticks.values() if s.active)
        total += sum(layer.binding_count for layer in self.layers.values())
        return total

    def describe(self) -> list[str]:
        """Human-readable lines summarising the mapping, for ``padmap validate``."""
        lines = [f"{self.name} — {self.description}" if self.description else self.name]
        lines.append(f"  poll: {self.poll_hz:g} Hz")
        for label, bindings in (("buttons", self.buttons), ("dpad", self.dpad)):
            for input_name, binding in sorted(bindings.items()):
                if not binding.is_noop:
                    lines.append(f"  {label}.{input_name}: {binding.action}{_extras(binding)}")
        for name, trigger in sorted(self.triggers.items()):
            if not trigger.binding.is_noop:
                lines.append(
                    f"  trigger.{name}: {trigger.binding.action} "
                    f"(past {trigger.threshold:g}){_extras(trigger.binding)}"
                )
        for name, stick in sorted(self.sticks.items()):
            if stick.active:
                detail = (
                    f"past {stick.threshold:g}"
                    if stick.mode == "keys"
                    else f"speed {stick.speed:g}"
                )
                lines.append(f"  stick.{name}: {stick.mode} ({detail})")
                for direction, binding in sorted(stick.directions.items()):
                    lines.append(f"    {direction}: {binding.action}")
        for layer_name, layer in sorted(self.layers.items()):
            suffix = f" — {layer.description}" if layer.description else ""
            lines.append(f"  layer '{layer_name}'{suffix}")
            lines.extend(f"  {line}" for line in _describe_layer(layer))
        return lines


def _describe_layer(layer: Layer) -> list[str]:
    """The indented body of one layer, for :meth:`Profile.describe`."""
    lines: list[str] = []
    for label, bindings in (("buttons", layer.buttons), ("dpad", layer.dpad)):
        for name, binding in sorted(bindings.items()):
            if not binding.is_noop:
                lines.append(f"  {label}.{name}: {binding.action}{_extras(binding)}")
    for name, trigger in sorted(layer.triggers.items()):
        if not trigger.binding.is_noop:
            lines.append(f"  trigger.{name}: {trigger.binding.action} (past {trigger.threshold:g})")
    for name, stick in sorted(layer.sticks.items()):
        if stick.active:
            lines.append(f"  stick.{name}: {stick.mode}")
    return lines


def _check_layer_references(profile: Profile) -> None:
    """Fail on a layer switch that names a layer that does not exist.

    Catching this at load time matters more here than usual: at runtime a
    dangling layer switch is silent — the button simply does nothing — which is
    indistinguishable from a broken button.
    """
    referenced: dict[str, str] = {}
    for label, bindings in (("buttons", profile.buttons), ("dpad", profile.dpad)):
        for name, binding in bindings.items():
            if binding.action.command == "layer":
                referenced[binding.action.argument] = f"{label}.{name}"
    for name, trigger in profile.triggers.items():
        if trigger.binding.action.command == "layer":
            referenced[trigger.binding.action.argument] = f"triggers.{name}"

    for layer_name, where in referenced.items():
        if layer_name not in profile.layers:
            known = ", ".join(sorted(profile.layers)) or "none defined"
            raise ProfileError(
                f"{where}: switches to layer {layer_name!r}, which has no entry under "
                f"'layers'. Defined layers: {known}"
            )

    for layer_name in profile.layers:
        if layer_name not in referenced:
            raise ProfileError(
                f"layers.{layer_name}: nothing switches to this layer. Bind a button to "
                f"'special:layer:{layer_name}' in the base profile, or remove the layer."
            )


def _extras(binding: Binding) -> str:
    parts = []
    if binding.turbo_hz:
        parts.append(f"turbo {binding.turbo_hz:g}Hz")
    if binding.toggle:
        parts.append("toggle")
    return f" [{', '.join(parts)}]" if parts else ""


# --- Loading -----------------------------------------------------------------


def _profiles_dir():
    return resources.files("padmap") / "profiles"


def bundled_profile_names() -> list[str]:
    """Names of the profiles shipped inside the package."""
    return sorted(
        entry.name.removesuffix(".json")
        for entry in _profiles_dir().iterdir()
        if entry.name.endswith(".json")
    )


def load_profile(reference: str) -> Profile:
    """Load a profile by bundled name (``desktop``) or by file path.

    A path is tried first so a local ``desktop.json`` in the working directory
    wins over the bundled profile of the same name — the least surprising
    behaviour when someone copies a bundled profile out to edit it.
    """
    path = Path(reference)
    if path.suffix == ".json" or path.exists():
        return load_profile_file(path)

    available = bundled_profile_names()
    if reference not in available:
        raise ProfileError(
            f"unknown profile {reference!r}. Bundled profiles: {', '.join(available)}. "
            "Pass a path to a .json file to use your own."
        )
    text = (_profiles_dir() / f"{reference}.json").read_text(encoding="utf-8")
    return _from_json(text, source=f"bundled:{reference}")


def load_profile_file(path: Path) -> Profile:
    """Load and validate a profile from a filesystem path."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"cannot read profile {str(path)!r}: {exc}") from exc
    return _from_json(text, source=str(path))


def _from_json(text: str, source: str) -> Profile:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{source}: invalid JSON on line {exc.lineno}: {exc.msg}") from exc
    return Profile.from_dict(data, source=source)


def starter_profile_json() -> str:
    """The commented starting point ``padmap init`` writes out."""
    return (_profiles_dir() / "starter.json").read_text(encoding="utf-8")
