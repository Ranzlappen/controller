"""Guided setup: `padmap setup`.

Everything padmap needs to know about a particular pad is measurable, and
asking someone to discover it by editing JSON and guessing is the wrong way
round. This walks the environment checks, the device choice, the raw-index
identification, both calibrations and the focus/background probe in order, then
proposes a complete profile from what it measured.

The decisions are pure functions — :func:`detect_press`, :func:`suggest`,
:func:`assemble_profile` — so the part of setup that can be wrong is tested.
Only the prompting needs a person with a controller in their hands.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from padmap.calibration import STICK_AXES, Calibration
from padmap.config import (
    DEFAULT_ACCEL,
    DEFAULT_ACCEL_TIME,
    DEFAULT_MOUSE_SPEED,
    DEFAULT_POLL_HZ,
    DEFAULT_PRECISION,
    DEFAULT_SCROLL_SPEED,
    DEFAULT_SMOOTHING,
)
from padmap.devices import BUTTON_NAMES, TRIGGER_NAMES

__all__ = [
    "IDENTIFY_ORDER",
    "run_setup",
    "sample_axes",
    "Measurements",
    "Suggestions",
    "assemble_profile",
    "detect_axis_move",
    "detect_press",
    "suggest",
]

#: The order buttons are asked for, with the prompt label each gets. Face
#: buttons first because they are unambiguous; the stick clicks last because
#: they are the ones people fumble.
IDENTIFY_ORDER: tuple[tuple[str, str], ...] = (
    ("a", "A (bottom face button)"),
    ("b", "B (right face button)"),
    ("x", "X (left face button)"),
    ("y", "Y (top face button)"),
    ("lb", "LB (left bumper)"),
    ("rb", "RB (right bumper)"),
    ("back", "Back / View"),
    ("start", "Start / Menu"),
    ("ls", "left stick click"),
    ("rs", "right stick click"),
    ("guide", "Xbox / Guide button"),
)

#: A trigger must travel at least this far for the sweep to count as real.
MIN_TRIGGER_TRAVEL = 0.4


def detect_press(before: Sequence[float], after: Sequence[float]) -> int | None:
    """Which raw button index just went from released to pressed.

    Only rising edges count, and only one per call: if two buttons appear to go
    down in the same poll the answer is None rather than a guess, because
    recording the wrong index is worse than asking again.
    """
    risen = [
        index
        for index, value in enumerate(after)
        if value and not (before[index] if index < len(before) else 0)
    ]
    return risen[0] if len(risen) == 1 else None


def detect_axis_move(
    baseline: Sequence[float], now: Sequence[float], threshold: float = 0.5
) -> tuple[int, float] | None:
    """Which raw axis moved furthest from its baseline, if any moved enough.

    Used to identify the triggers, whose raw index and resting value both vary
    by driver. Returns the index and its current reading.
    """
    best: tuple[int, float] | None = None
    best_delta = threshold
    for index, value in enumerate(now):
        start = baseline[index] if index < len(baseline) else 0.0
        delta = abs(value - start)
        if delta >= best_delta:
            best, best_delta = (index, value), delta
    return best


@dataclass(frozen=True)
class Measurements:
    """What the wizard actually observed, as opposed to what it will suggest."""

    #: Largest rest-position offset across the stick axes.
    drift: float = 0.0
    #: Largest sample-to-sample spread while the sticks were at rest.
    noise: float = 0.0
    calibration: Calibration = field(default_factory=Calibration)
    #: Resting and fully-pulled readings per trigger name.
    trigger_rest: Mapping[str, float] = field(default_factory=dict)
    trigger_full: Mapping[str, float] = field(default_factory=dict)
    layout: Mapping[str, int] = field(default_factory=dict)
    focus_works: bool = False
    background_works: bool = True

    @property
    def trigger_travel(self) -> float:
        """The smallest travel seen on any trigger."""
        if not self.trigger_full:
            return 0.0
        return min(
            abs(self.trigger_full[name] - self.trigger_rest.get(name, 0.0))
            for name in self.trigger_full
        )


@dataclass(frozen=True)
class Suggestions:
    """Proposed settings, each with a reason the wizard can print."""

    deadzone: float = 0.1
    smoothing: float = DEFAULT_SMOOTHING
    accel: float = DEFAULT_ACCEL
    accel_time: float = DEFAULT_ACCEL_TIME
    precision: float = DEFAULT_PRECISION
    speed: float = DEFAULT_MOUSE_SPEED
    scroll_speed: float = DEFAULT_SCROLL_SPEED
    poll_hz: float = DEFAULT_POLL_HZ
    trigger_threshold: float = 0.15
    reasons: Mapping[str, str] = field(default_factory=dict)

    def rows(self) -> list[tuple[str, str, str]]:
        """``(setting, value, reason)`` rows for the summary table."""
        values = {
            "deadzone": f"{self.deadzone:.2f}",
            "smoothing": f"{self.smoothing:.2f}",
            "accel": f"{self.accel:.1f}",
            "precision": f"{self.precision:.2f}",
            "speed": f"{self.speed:g} px/s",
            "poll_hz": f"{self.poll_hz:g} Hz",
            "trigger threshold": f"{self.trigger_threshold:.2f}",
        }
        return [(name, value, self.reasons.get(name, "")) for name, value in values.items()]


def suggest(measured: Measurements, gaming: bool = False) -> Suggestions:
    """Propose settings from what was measured.

    The deadzone is the interesting one. Because calibration has already
    removed the rest offset, the deadzone no longer has to hide drift — it only
    has to clear the *noise* around the new centre, which is a far smaller
    number. That is why a calibrated pad can run a 0.08 deadzone where an
    uncalibrated one needed 0.2.
    """
    reasons: dict[str, str] = {}

    deadzone = min(0.3, max(0.05, round(measured.noise * 3.0, 2)))
    if measured.calibration.is_empty and measured.drift > 0.0:
        # Nothing was stored, so the deadzone still has to cover the drift.
        deadzone = min(0.3, max(deadzone, round(measured.drift + measured.noise * 2, 2)))
        reasons["deadzone"] = f"covers {measured.drift:.2f} drift (uncalibrated)"
    else:
        reasons["deadzone"] = f"clears {measured.noise:.3f} noise; calibration handles the drift"

    smoothing = DEFAULT_SMOOTHING
    if measured.noise > 0.02:
        smoothing = 0.5
        reasons["smoothing"] = f"raised — {measured.noise:.3f} noise is on the high side"
    else:
        reasons["smoothing"] = "steadies the pointer without feeling laggy"

    rest = max(measured.trigger_rest.values(), default=0.0)
    threshold = min(0.5, max(0.08, round(rest + max(0.08, measured.noise * 3), 2)))
    reasons["trigger threshold"] = f"clear of a {rest:.2f} resting pull"

    accel = DEFAULT_ACCEL if gaming else 2.5
    reasons["accel"] = (
        "off — aim should stay linear" if gaming else "lets one stick be precise and fast"
    )
    reasons["precision"] = "hold the precision button for fine work"
    reasons["speed"] = "a middling default; raise it if the pointer feels slow"
    reasons["poll_hz"] = "200 Hz for games" if gaming else "plenty for pointing"

    return Suggestions(
        deadzone=deadzone,
        smoothing=smoothing,
        accel=accel,
        precision=DEFAULT_PRECISION,
        speed=1400.0 if gaming else DEFAULT_MOUSE_SPEED,
        poll_hz=200.0 if gaming else DEFAULT_POLL_HZ,
        trigger_threshold=threshold,
        reasons=reasons,
    )


def assemble_profile(
    name: str,
    measured: Measurements,
    chosen: Suggestions,
    device_name: str = "",
    gaming: bool = False,
) -> dict:
    """Build the profile document the wizard writes out.

    Deliberately a complete profile rather than a minimal one: the file is also
    the documentation someone edits next, and an explicit value is easier to
    change than an absent one is to discover.
    """
    device: dict = {"auto_centre": True}
    if device_name:
        device["match"] = device_name
    if measured.layout:
        device["layout"] = dict(sorted(measured.layout.items()))
    if not measured.calibration.is_empty:
        device["calibration"] = measured.calibration.to_dict()

    triggers = {
        trigger: {
            "action": action,
            "threshold": chosen.trigger_threshold,
        }
        for trigger, action in (
            ("lt", "mouse:right" if gaming else "key:page_up"),
            ("rt", "mouse:left" if gaming else "key:page_down"),
        )
    }
    if not gaming:
        for trigger in triggers.values():
            trigger["turbo"] = 6

    left_stick: dict = {
        "mode": "keys" if gaming else "mouse",
        "deadzone": chosen.deadzone,
    }
    if gaming:
        left_stick.update(
            {"threshold": 0.5, "up": "key:w", "down": "key:s", "left": "key:a", "right": "key:d"}
        )
    else:
        left_stick.update(
            {
                "speed": chosen.speed,
                "curve": 2.0,
                "smoothing": chosen.smoothing,
                "accel": chosen.accel,
                "accel_time": chosen.accel_time,
                "precision": chosen.precision,
            }
        )

    right_stick: dict = {
        "mode": "mouse" if gaming else "scroll",
        "deadzone": chosen.deadzone,
        "smoothing": chosen.smoothing,
        "precision": chosen.precision,
    }
    right_stick["speed"] = chosen.speed if gaming else chosen.scroll_speed
    if gaming:
        right_stick.update({"curve": 2.2, "accel": DEFAULT_ACCEL})

    return {
        "name": name,
        "description": f"Written by `padmap setup` for {device_name or 'this controller'}.",
        "poll_hz": chosen.poll_hz,
        "device": device,
        "buttons": {
            "a": "key:space" if gaming else "mouse:left",
            "b": "key:ctrl" if gaming else "mouse:right",
            "x": "key:r" if gaming else "key:enter",
            "y": "key:e" if gaming else "key:esc",
            "lb": "key:q" if gaming else "special:precision",
            "rb": "key:f" if gaming else "special:layer:nav",
            "back": "special:toggle_pause",
            "start": "key:esc" if gaming else "key:cmd",
            "ls": {"action": "key:shift", "toggle": True} if gaming else "mouse:middle",
            "rs": "key:v" if gaming else "key:space",
        },
        "dpad": (
            {"up": "key:1", "down": "key:2", "left": "key:3", "right": "key:4"}
            if gaming
            else {
                "up": {"action": "key:up", "turbo": 12},
                "down": {"action": "key:down", "turbo": 12},
                "left": {"action": "key:left", "turbo": 12},
                "right": {"action": "key:right", "turbo": 12},
            }
        ),
        "triggers": triggers,
        "sticks": {"left": left_stick, "right": right_stick},
        **(
            {}
            if gaming
            else {
                "layers": {
                    "nav": {
                        "description": "media and browser navigation",
                        "buttons": {
                            "a": "key:media_play_pause",
                            "b": "key:media_volume_mute",
                            "x": "key:media_next",
                            "y": "key:media_previous",
                        },
                        "dpad": {
                            "up": {"action": "key:media_volume_up", "turbo": 8},
                            "down": {"action": "key:media_volume_down", "turbo": 8},
                            "left": "key:alt+left",
                            "right": "key:alt+right",
                        },
                    }
                }
            }
        ),
    }


def layout_overrides(learned: Mapping[str, int]) -> dict[str, int]:
    """Keep only the learned indices that differ from the SDL defaults.

    A profile full of redundant overrides is noise, and worse, it pins indices
    that would otherwise adapt if the driver changed.
    """
    from padmap.devices import DEFAULT_LAYOUT

    return {
        name: index
        for name, index in learned.items()
        if name in DEFAULT_LAYOUT.buttons and DEFAULT_LAYOUT.buttons[name] != index
    }


def unmapped_buttons(learned: Mapping[str, int]) -> tuple[str, ...]:
    """Buttons the wizard asked about but never saw pressed."""
    return tuple(name for name in BUTTON_NAMES if name not in learned)


def trigger_warnings(measured: Measurements) -> list[str]:
    """Anything about the triggers worth saying out loud before writing a profile."""
    notes = []
    for name in TRIGGER_NAMES:
        rest = measured.trigger_rest.get(name)
        if rest is None:
            notes.append(f"{name}: never saw it move — binding it may not work")
        elif rest > 0.15:
            notes.append(
                f"{name}: rests at {rest:.2f} rather than 0 — the threshold allows for it, "
                "but check `device.trigger_mode` if it feels half-pressed"
            )
    if measured.trigger_full and measured.trigger_travel < MIN_TRIGGER_TRAVEL:
        notes.append(
            f"triggers only travelled {measured.trigger_travel:.2f} — pull them fully next time "
            "so the threshold is based on their real range"
        )
    return notes


def stick_axis_names() -> tuple[str, ...]:
    """The axes the wizard calibrates, for prompting."""
    return STICK_AXES


# --- Polling helpers ---------------------------------------------------------


def sample_axes(
    controller: object,
    seconds: float,
    consume: object,
    clock: object = None,
    sleep: object = None,
    interval: float = 0.01,
) -> int:
    """Poll a controller for ``seconds``, handing each axis reading to ``consume``.

    Split from the prompting so the sampling loop can be driven by a fake
    controller and a fake clock in tests.
    """
    import time as _time

    clock = clock or _time.monotonic
    sleep = sleep or _time.sleep
    deadline = clock() + seconds
    polls = 0
    while clock() < deadline:
        state = controller.poll()
        consume({name: state.axis(name) for name in STICK_AXES})
        polls += 1
        sleep(interval)
    return polls


def _ask(prompt: str, default: str = "") -> str:  # pragma: no cover - needs a person
    """Read one line, falling back to ``default`` on Enter or a closed stdin."""
    try:
        answer = input(prompt).strip()
    except EOFError:
        return default
    return answer or default


def _yes(prompt: str, default: bool = True) -> bool:  # pragma: no cover - needs a person
    suffix = "[Y/n]" if default else "[y/N]"
    answer = _ask(f"{prompt} {suffix} ").lower()
    if not answer:
        return default
    return answer.startswith("y")


def run_setup(path, force: bool = False, name: str = "") -> int:  # pragma: no cover - interactive
    """Walk every setup phase and write a profile. Returns an exit code."""
    import json
    import time

    from padmap.calibration import CalibrationError, CentreSampler, RangeSampler
    from padmap.devices import DEFAULT_LAYOUT, TRIGGER_NAMES, list_devices, open_controller
    from padmap.doctor import FAIL, evaluate, probe
    from padmap.focus import foreground_window

    print("padmap setup — guided configuration\n")

    # --- 1. Environment ---
    print("Step 1/6  Environment")
    checks = evaluate(probe())
    for check in checks:
        print(f"  {check.mark} {check.name:<22} {check.detail}")
        if check.fix and check.status != "ok":
            print(f"      → {check.fix}")
    if any(check.status == FAIL for check in checks) and not _yes(
        "\n  Some checks failed. Carry on anyway?", default=False
    ):
        return 1

    # --- 2. Device ---
    print("\nStep 2/6  Controller")
    devices = list_devices()
    if not devices:
        print("  No controller detected. Plug one in and re-run `padmap setup`.")
        return 1
    for index, device in enumerate(devices, start=1):
        print(
            f"  {index}) {device.name}  ({device.axes} axes, "
            f"{device.buttons} buttons, {device.hats} hats)"
        )
    chosen_index = 0
    if len(devices) > 1:
        answer = _ask(f"  Which controller? [1-{len(devices)}, default 1] ", "1")
        chosen_index = max(0, min(len(devices) - 1, int(answer) - 1 if answer.isdigit() else 0))
    device = devices[chosen_index]
    print(f"  Using: {device.name}")

    controller = open_controller(index=device.index)
    try:
        gaming = _yes("\n  Mostly for games (WASD + aim) rather than the desktop?", default=False)

        # --- 3. Identify the buttons ---
        print("\nStep 3/6  Identify the buttons")
        print("  Press each button when asked. Wait 4s to skip one you don't have.\n")
        learned: dict[str, int] = {}
        for button, label in IDENTIFY_ORDER:
            baseline, _, _ = controller.poll_raw()
            print(f"    {label:<28}", end="", flush=True)
            found = None
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                buttons, _, _ = controller.poll_raw()
                found = detect_press(baseline, buttons)
                if found is not None:
                    break
                baseline = buttons
                time.sleep(0.02)
            if found is None:
                print("skipped")
                continue
            learned[button] = found
            default = DEFAULT_LAYOUT.buttons.get(button)
            note = "" if default == found else f"  (differs from the usual {default})"
            print(f"raw button {found}{note}")
            while True:  # wait for release, so the next prompt starts clean
                buttons, _, _ = controller.poll_raw()
                if not (found < len(buttons) and buttons[found]):
                    break
                time.sleep(0.02)

        overrides = layout_overrides(learned)
        missing = unmapped_buttons(learned)
        if overrides:
            print(f"\n  Layout differs from the default — pinning: {overrides}")
        if missing:
            print(f"  Never saw: {', '.join(missing)} (left on the default index)")

        # --- 4. Sticks ---
        print("\nStep 4/6  Stick calibration")
        print("  Let go of both sticks...", end="", flush=True)
        centres = CentreSampler()
        sample_axes(controller, 2.0, centres.add)
        try:
            rest = centres.centres()
        except CalibrationError as exc:
            print(f" refused.\n  {exc}")
            return 1
        noise = _spread(centres)
        drift = max((abs(value) for value in rest.values()), default=0.0)
        print(f" rest measured (worst drift {drift:.3f}, noise {noise:.3f})")

        print("  Now roll both sticks right around their edge, repeatedly...", end="", flush=True)
        ranges = RangeSampler()
        sample_axes(controller, 8.0, ranges.add)
        try:
            calibration = ranges.build(rest)
            print(" travel measured")
        except CalibrationError as exc:
            calibration = None
            print(f" refused.\n  {exc}\n  Carrying on without a stored range.")

        # --- 5. Triggers ---
        print("\nStep 5/6  Triggers")
        print("  Let go of both triggers...", end="", flush=True)
        trigger_rest: dict[str, float] = {}
        for _ in range(60):
            state = controller.poll()
            for trigger in TRIGGER_NAMES:
                trigger_rest[trigger] = state.axis(trigger)
            time.sleep(0.02)
        print("  " + "  ".join(f"{k}={v:.2f}" for k, v in sorted(trigger_rest.items())))

        print("  Now pull both triggers all the way in...", end="", flush=True)
        trigger_full = dict(trigger_rest)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            state = controller.poll()
            for trigger in TRIGGER_NAMES:
                trigger_full[trigger] = max(trigger_full[trigger], state.axis(trigger))
            time.sleep(0.02)
        print("  " + "  ".join(f"{k}={v:.2f}" for k, v in sorted(trigger_full.items())))

        # --- 6. Focus and background ---
        print("\nStep 6/6  Focus and background")
        before = foreground_window()
        print(f"  Focused window now: {before or 'cannot tell on this session'}")
        focus_works = False
        if before is not None and before.known:
            print("  Switch to another window within 8s...", end="", flush=True)
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                current = foreground_window()
                if current is not None and current.known and current != before:
                    print(f" now: {current}")
                    focus_works = True
                    break
                time.sleep(0.25)
            if not focus_works:
                print(" no change seen")
        print(
            "  Focus tracking: "
            + (
                "working"
                if focus_works
                else "unavailable (a diagnostic only — input still goes to the focused window)"
            )
        )
    finally:
        controller.close()

    measured = Measurements(
        drift=drift,
        noise=noise,
        calibration=calibration or Calibration(),
        trigger_rest=trigger_rest,
        trigger_full=trigger_full,
        layout=overrides,
        focus_works=focus_works,
    )
    for note in trigger_warnings(measured):
        print(f"  ! {note}")

    # --- Suggestions ---
    chosen = suggest(measured, gaming=gaming)
    print("\nSuggested settings")
    for setting, value, reason in chosen.rows():
        print(f"  {setting:<18} {value:<12} {reason}")
    if not _yes("\nWrite a profile with these?"):
        print("Nothing written.")
        return 0

    document = assemble_profile(
        name or ("Gaming" if gaming else "Desktop"),
        measured,
        chosen,
        device_name=device.name,
        gaming=gaming,
    )
    target = path
    if target.exists() and not force:
        print(f"padmap: {target} already exists (re-run with --force to overwrite)")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print(f"\nWrote {target}")
    print(f"  check it:  padmap validate {target}")
    print(f"  run it:    padmap run -w -p {target}")
    print("  background: padmap run --detach -p " + str(target))
    return 0


def _spread(sampler: object) -> float:
    """Largest sample-to-sample spread the centre sampler saw."""
    spreads = [
        max(values) - min(values) for values in getattr(sampler, "samples", {}).values() if values
    ]
    return max(spreads, default=0.0)
