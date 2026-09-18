"""The mapping loop: controller state in, keyboard and mouse events out.

:meth:`Engine.tick` is deliberately a pure-ish step — hand it a timestamp and a
:class:`~padmap.devices.PadState` and it emits the right calls on the backend.
:meth:`Engine.run` is the thin loop around it. That split is what lets the whole
mapping behaviour (edges, turbo, toggles, layers, sub-pixel motion) be tested
with a :class:`~padmap.backends.RecordingBackend` and no hardware at all.

The one rule that outranks everything here: **never leave a key stuck down.**
Anything that stops output — pausing, quitting, a crash, Ctrl-C, a profile
reload — goes through :meth:`release_all` first.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from padmap.actions import Action
from padmap.backends import OutputBackend
from padmap.calibration import STICK_AXES, Calibration, CalibrationError, CentreSampler
from padmap.config import Binding, Layer, Profile, StickConfig
from padmap.curves import Accelerator, Smoother, SubPixel, stick_vector
from padmap.devices import DPAD_NAMES, ControllerSource, PadState

__all__ = ["Engine", "EngineStatus"]

#: Ceiling on the time delta used for analogue motion. Without it, a stalled
#: poll (a laptop waking from sleep, say) would fling the cursor across the
#: screen in one tick.
MAX_TICK_SECONDS = 0.1

#: How long to watch the resting sticks at startup before trusting the reading.
#: Long enough to average out noise, short enough that nobody notices.
AUTO_CENTRE_SECONDS = 0.4

#: How often to ask whether the profile file changed on disk, or whether a
#: stop has been requested. Cheap either way, but there is no reason to stat a
#: file 120 times a second.
CONTROL_INTERVAL_SECONDS = 0.5

#: How often the status callback fires. Fast enough to feel live, slow enough
#: that redrawing a terminal line is not a measurable cost.
STATUS_INTERVAL_SECONDS = 0.125


@dataclass(frozen=True)
class EngineStatus:
    """A snapshot of what the engine is doing, for status displays.

    Returned by value so a display can render it without reaching into engine
    internals, and so the render can happen on another thread.
    """

    profile: str
    paused: bool
    layers: tuple[str, ...]
    precision: bool
    events: int
    drift: dict[str, float]
    settling: bool

    @property
    def worst_drift(self) -> float:
        """The largest rest-position offset being corrected for."""
        return max((abs(value) for value in self.drift.values()), default=0.0)


class Engine:
    """Runs one profile against one controller."""

    def __init__(
        self,
        profile: Profile,
        controller: ControllerSource,
        backend: OutputBackend,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        on_status: Callable[[str], None] | None = None,
        reload_source: Callable[[], Profile | None] | None = None,
        stop_check: Callable[[], bool] | None = None,
        on_frame: Callable[[EngineStatus], None] | None = None,
    ) -> None:
        self.profile = profile
        self.controller = controller
        self.backend = backend
        self._clock = clock
        self._sleep = sleep
        self._on_status = on_status
        self._reload_source = reload_source
        self._stop_check = stop_check
        #: Called with an :class:`EngineStatus` a few times a second. Public so
        #: a display that needs the engine to exist first can attach later.
        self.on_frame = on_frame
        # Requests from other threads (the tray) land here and are applied by
        # the loop itself. Mutating engine state from a menu callback while the
        # loop is mid-tick would race against keys being pressed.
        self._pending_pause: bool | None = None
        self._pending_profile: Profile | None = None
        self._events = 0
        self._next_status = 0.0

        self.running = False
        self.paused = False

        # slot id -> the action currently pressed down for that slot
        self._active: dict[str, Action] = {}
        # slot ids whose toggle latch is currently on
        self._latched: set[str] = set()
        # slot id -> whether the raw input was down on the previous tick
        self._was_down: dict[str, bool] = {}
        # slot id -> monotonic time the next turbo/repeat pulse is due
        self._next_pulse: dict[str, float] = {}
        # stick name -> carried fractional pixels / scroll clicks
        self._carry: dict[str, SubPixel] = {}
        self._smoothers: dict[str, Smoother] = {}
        self._accelerators: dict[str, Accelerator] = {}
        self._last_tick: float | None = None

        # Held modifiers: which slots currently request precision, and which
        # layer each layer-slot is holding open.
        self._precision_slots: set[str] = set()
        self._layer_slots: dict[str, str] = {}
        #: Layer names in the order they were activated; the last one wins.
        self._active_layers: list[str] = []

        self._calibration = profile.device.calibration
        self._measured_centres: dict[str, float] = {}
        self._centre_sampler: CentreSampler | None = None
        self._centre_deadline: float | None = None
        self._next_control_check: float | None = None

    # --- Public API ----------------------------------------------------------

    def run(self) -> None:
        """Poll and map until :meth:`stop` is called or the loop is interrupted."""
        self.running = True
        try:
            while self.running:
                started = self._clock()
                self.tick(started)
                self._emit_status(started)
                remaining = (1.0 / self.profile.poll_hz) - (self._clock() - started)
                if remaining > 0:
                    self._sleep(remaining)
        finally:
            self.release_all()
            self.running = False

    def stop(self) -> None:
        """Ask :meth:`run` to finish after the current tick."""
        self.running = False

    def request_reload(self) -> bool:
        """Re-read the profile at the next control poll, changed or not.

        The reload source normally only reports an *edited* file, which is the
        right default for a watcher but wrong for someone clicking "Reload".
        Sources may offer a ``force()`` to override that; ones that do not
        simply re-check, and this returns False so a caller can say as much.
        """
        if self._reload_source is None:
            return False
        force = getattr(self._reload_source, "force", None)
        if callable(force):
            force()
        self._next_control_check = 0.0
        return True

    def request_pause(self, paused: bool) -> None:
        """Ask for pause/resume from another thread; applied on the next tick."""
        self._pending_pause = paused

    def request_profile(self, profile: Profile) -> None:
        """Ask for a profile swap from another thread; applied on the next tick."""
        self._pending_profile = profile

    def _apply_pending(self) -> None:
        """Carry out anything another thread asked for, on the loop's own thread."""
        pending_pause, self._pending_pause = self._pending_pause, None
        if pending_pause is not None:
            self.set_paused(pending_pause)
        pending_profile, self._pending_profile = self._pending_profile, None
        if pending_profile is not None:
            self.adopt_profile(pending_profile)

    @property
    def can_reload(self) -> bool:
        """Whether this session has anywhere to reload a profile from."""
        return self._reload_source is not None

    def tick(self, now: float, state: PadState | None = None) -> None:
        """Process exactly one poll of the controller."""
        if state is None:
            state = self.controller.poll()

        self._apply_pending()
        self._poll_control(now)

        delta = 0.0 if self._last_tick is None else min(now - self._last_tick, MAX_TICK_SECONDS)
        self._last_tick = now

        settling = self._sample_centres(now, state)

        # Specials run first and are always read from the base profile, so that
        # "which layer am I in" never depends on which layer is active.
        for slot, binding, is_down in self._special_inputs(state):
            self._apply_binding(slot, binding, is_down, now)

        for slot, binding, is_down in self._layered_inputs(state):
            self._apply_binding(slot, binding, is_down, now)

        if not self.paused and not settling:
            self._apply_analogue(state, delta)

    def release_all(self) -> None:
        """Let go of every held key and mouse button. Safe to call twice."""
        for slot in list(self._active):
            self._release(slot)
        self._latched.clear()
        self._next_pulse.clear()
        for carry in self._carry.values():
            carry.reset()
        for smoother in self._smoothers.values():
            smoother.reset()
        for accelerator in self._accelerators.values():
            accelerator.reset()

    def set_paused(self, paused: bool) -> None:
        """Pause or resume output, releasing anything held on the way in."""
        if paused == self.paused:
            return
        self.paused = paused
        if paused:
            self.release_all()
        self._status("paused — output suppressed" if paused else "resumed")

    def status(self) -> EngineStatus:
        """A by-value snapshot of what the engine is currently doing."""
        return EngineStatus(
            profile=self.profile.name,
            paused=self.paused,
            layers=tuple(self._active_layers),
            precision=self.precision_held,
            events=self._events,
            drift=dict(self._measured_centres),
            settling=self._centre_deadline is not None and self._centre_deadline != 0.0,
        )

    def _emit_status(self, now: float) -> None:
        """Hand a snapshot to the display, at most a few times a second."""
        if self.on_frame is None or now < self._next_status:
            return
        self._next_status = now + STATUS_INTERVAL_SECONDS
        self.on_frame(self.status())

    @property
    def active_layers(self) -> tuple[str, ...]:
        """Layer names currently held open, in activation order."""
        return tuple(self._active_layers)

    @property
    def precision_held(self) -> bool:
        """True while a ``special:precision`` binding is held."""
        return bool(self._precision_slots)

    @property
    def calibration(self) -> Calibration:
        """The calibration in force, including anything measured at startup."""
        return self._calibration

    # --- Calibration ---------------------------------------------------------

    def axis(self, state: PadState, name: str) -> float:
        """Read one axis with calibration applied."""
        return self._calibration.apply(name, state.axis(name))

    def _sample_centres(self, now: float, state: PadState) -> bool:
        """Measure where the sticks rest, once, at startup.

        Returns True while still sampling, which suppresses pointer motion for
        that fraction of a second — moving the cursor from readings we are in
        the middle of deciding are wrong would be silly.
        """
        if not self.profile.device.auto_centre or self._centre_deadline == 0.0:
            return False

        if self._centre_deadline is None:
            self._centre_sampler = CentreSampler()
            self._centre_deadline = now + AUTO_CENTRE_SECONDS

        if self._centre_sampler is None:
            return False

        if now < self._centre_deadline:
            self._centre_sampler.add({name: state.axis(name) for name in STICK_AXES})
            return True

        self._finish_centring()
        return False

    def _finish_centring(self) -> None:
        """Adopt the sampled rest positions, or explain why they were refused."""
        sampler, self._centre_sampler = self._centre_sampler, None
        self._centre_deadline = 0.0
        if sampler is None:
            return
        try:
            centres = sampler.centres()
        except CalibrationError as exc:
            self._status(f"auto-centre skipped: {exc}")
            return

        self._measured_centres = centres
        self._calibration = self._calibration.with_centres(centres)
        worst = max((abs(value) for value in centres.values()), default=0.0)
        if worst >= 0.02:
            offsets = ", ".join(f"{name} {value:+.3f}" for name, value in sorted(centres.items()))
            self._status(f"auto-centred (drift corrected: {offsets})")

    # --- Hot reload ----------------------------------------------------------

    def _poll_control(self, now: float) -> None:
        """Check the out-of-band controls: has a stop been asked for, or an edit?

        Both are rate-limited together. They are the two things that reach in
        from outside the process, and neither is worth a filesystem call on
        every one of a hundred-plus ticks a second.
        """
        if self._reload_source is None and self._stop_check is None:
            return
        if self._next_control_check is None:
            # Nothing can have changed between building the engine and its
            # first tick, so the first check is one interval away, not now.
            self._next_control_check = now + CONTROL_INTERVAL_SECONDS
            return
        if now < self._next_control_check:
            return
        self._next_control_check = now + CONTROL_INTERVAL_SECONDS

        if self._stop_check is not None and self._stop_check():
            self._status("stop requested")
            self.stop()
            return

        if self._reload_source is None:
            return
        replacement = self._reload_source()
        if replacement is None:
            return
        self.adopt_profile(replacement)
        self._status(f"reloaded profile: {replacement.name} ({replacement.binding_count} bindings)")

    def adopt_profile(self, profile: Profile) -> None:
        """Swap in a different profile, letting go of everything held first.

        Must run on the loop's thread — :meth:`request_profile` is the way in
        from anywhere else.
        """
        self.release_all()
        self._precision_slots.clear()
        self._layer_slots.clear()
        self._active_layers.clear()
        self._was_down.clear()
        self._smoothers.clear()
        self._accelerators.clear()
        self._carry.clear()

        self.profile = profile
        # Keep the rest positions measured at startup — the profile changed,
        # the hardware did not, and re-centring mid-session would need the user
        # to take their thumbs off at exactly the wrong moment.
        self._calibration = profile.device.calibration.with_centres(self._measured_centres)

    # --- Input decomposition -------------------------------------------------

    def _special_inputs(self, state: PadState) -> Iterator[tuple[str, Binding, bool]]:
        """Yield the base profile's special bindings only."""
        for name, binding in self.profile.buttons.items():
            if binding.action.kind == "special":
                yield f"button.{name}", binding, state.button(name)
        for name, binding in self.profile.dpad.items():
            if binding.action.kind == "special":
                yield f"dpad.{name}", binding, state.dpad.get(name, False)
        for name, trigger in self.profile.triggers.items():
            if trigger.binding.action.kind == "special":
                yield (
                    f"trigger.{name}",
                    trigger.binding,
                    self.axis(state, name) >= trigger.threshold,
                )

    def _layered_inputs(self, state: PadState) -> Iterator[tuple[str, Binding, bool]]:
        """Yield every non-special input, resolved through the active layers."""
        for name in self._input_names("buttons"):
            binding = self._resolve("buttons", name)
            if binding is not None and binding.action.kind != "special":
                yield f"button.{name}", binding, state.button(name)

        for name in self._input_names("dpad"):
            binding = self._resolve("dpad", name)
            if binding is not None and binding.action.kind != "special":
                yield f"dpad.{name}", binding, state.dpad.get(name, False)

        for name in self._input_names("triggers"):
            trigger = self._resolve("triggers", name)
            if trigger is not None and trigger.binding.action.kind != "special":
                yield (
                    f"trigger.{name}",
                    trigger.binding,
                    self.axis(state, name) >= trigger.threshold,
                )

        for name in self._input_names("sticks"):
            stick = self._resolve("sticks", name)
            if stick is None or stick.mode != "keys":
                continue
            for direction, is_down in self._stick_directions(stick, state, name).items():
                binding = stick.directions.get(direction)
                if binding is not None:
                    yield f"stick.{name}.{direction}", binding, is_down

    def _input_names(self, section: str) -> list[str]:
        """Every input name bound by the base profile or any active layer."""
        names = dict.fromkeys(getattr(self.profile, section))
        for layer_name in self._active_layers:
            layer = self.profile.layers.get(layer_name)
            if layer is not None:
                names.update(dict.fromkeys(getattr(layer, section)))
        return list(names)

    def _resolve(self, section: str, name: str) -> Any:
        """Find the binding for one input, newest active layer winning."""
        for layer_name in reversed(self._active_layers):
            layer: Layer | None = self.profile.layers.get(layer_name)
            if layer is not None:
                found = getattr(layer, section).get(name)
                if found is not None:
                    return found
        return getattr(self.profile, section).get(name)

    # --- Digital handling ----------------------------------------------------

    def _apply_binding(self, slot: str, binding: Binding, is_down: bool, now: float) -> None:
        was_down = self._was_down.get(slot, False)
        self._was_down[slot] = is_down
        pressed = is_down and not was_down

        action = binding.action
        if action.is_noop:
            return

        # Specials run even while paused — otherwise the pause button could
        # never un-pause, which is the one thing it exists to do.
        if action.kind == "special":
            self._run_special(slot, action, is_down, pressed)
            return

        if self.paused:
            return

        if binding.toggle:
            if pressed:
                if slot in self._latched:
                    self._latched.discard(slot)
                else:
                    self._latched.add(slot)
            effective = slot in self._latched
        else:
            effective = is_down

        if binding.turbo_hz > 0:
            self._pulse(slot, action, effective, now, binding.turbo_hz)
        elif action.is_repeatable:
            self._pulse(slot, action, effective, now, binding.repeat_hz)
        elif action.is_held:
            self._hold(slot, action, effective)
        elif pressed:
            # One-shot actions (text) fire on the press edge only.
            self._fire_once(action)

    def _pulse(
        self, slot: str, action: Action, effective: bool, now: float, rate_hz: float
    ) -> None:
        """Fire an action repeatedly while the input is held."""
        if not effective:
            self._next_pulse.pop(slot, None)
            self._release(slot)
            return

        due = self._next_pulse.get(slot)
        if due is not None and now < due:
            return
        self._next_pulse[slot] = now + 1.0 / rate_hz

        if action.is_held:
            # A turbo tap is a press and release in the same tick.
            self._press(action)
            self._unpress(action)
        else:
            self._fire_once(action)

    def _hold(self, slot: str, action: Action, effective: bool) -> None:
        """Keep an action down for exactly as long as the input is down.

        If a layer switch changes what this input means while it is held, the
        old action is released before the new one is pressed — otherwise the
        outgoing key would stay down with nothing left to release it.
        """
        current = self._active.get(slot)
        if effective:
            if current == action:
                return
            if current is not None:
                self._release(slot)
            self._press(action)
            self._active[slot] = action
        elif current is not None:
            self._release(slot)

    def _fire_once(self, action: Action) -> None:
        if action.kind == "text":
            self._events += 1
            self.backend.type_text(action.text)
        elif action.kind == "scroll":
            dx, dy = _scroll_step(action.direction)
            self._events += 1
            self.backend.scroll(dx, dy)

    def _press(self, action: Action) -> None:
        if action.kind == "key":
            self._events += 1
            self.backend.key_down(action.keys)
        elif action.kind == "mouse":
            self._events += 1
            self.backend.mouse_down(action.button)

    def _unpress(self, action: Action) -> None:
        if action.kind == "key":
            self._events += 1
            self.backend.key_up(action.keys)
        elif action.kind == "mouse":
            self._events += 1
            self.backend.mouse_up(action.button)

    def _release(self, slot: str) -> None:
        action = self._active.pop(slot, None)
        if action is not None:
            self._unpress(action)

    def _run_special(self, slot: str, action: Action, is_down: bool, pressed: bool) -> None:
        """Handle an engine-level special.

        Modifiers (``precision``, ``layer``) track the button's held state, so
        they act on release as well as press; the rest fire once on press.
        """
        if action.command == "precision":
            if is_down:
                self._precision_slots.add(slot)
            else:
                self._precision_slots.discard(slot)
            return

        if action.command == "layer":
            self._set_layer_slot(slot, action.argument if is_down else None)
            return

        if not pressed:
            return
        if action.command == "toggle_pause":
            self.set_paused(not self.paused)
        elif action.command == "quit":
            self._status("quit requested from the controller")
            self.stop()

    def _set_layer_slot(self, slot: str, layer_name: str | None) -> None:
        """Open or close one layer, keeping activation order stable."""
        previous = self._layer_slots.get(slot)
        if previous == layer_name:
            return
        if previous is not None:
            self._layer_slots.pop(slot, None)
            if previous not in self._layer_slots.values():
                self._active_layers.remove(previous)
        if layer_name is not None:
            self._layer_slots[slot] = layer_name
            if layer_name not in self._active_layers:
                self._active_layers.append(layer_name)

    # --- Analogue handling ---------------------------------------------------

    def _apply_analogue(self, state: PadState, delta: float) -> None:
        """Turn stick deflection into pointer motion and scrolling."""
        if delta <= 0:
            return
        precision = self.precision_held
        for name in self._input_names("sticks"):
            stick: StickConfig | None = self._resolve("sticks", name)
            if stick is None or stick.mode not in ("mouse", "scroll"):
                continue
            self._drive_stick(name, stick, state, delta, precision)

    def _drive_stick(
        self, name: str, stick: StickConfig, state: PadState, delta: float, precision: bool
    ) -> None:
        """Run one stick's full pipeline for this tick.

        Order matters: calibrate, then deadzone and curve, then smooth, then
        scale by speed. Smoothing after the curve means it smooths the value
        that actually drives the pointer; smoothing the raw axis instead would
        also smear the deadzone edge and make the stick feel mushy to start.
        """
        target = stick_vector(
            self.axis(state, f"{name}_x"),
            self.axis(state, f"{name}_y"),
            deadzone=stick.deadzone,
            curve=stick.curve,
            invert_x=stick.invert_x,
            invert_y=stick.invert_y,
            outer=stick.outer_deadzone,
        )

        smoother = self._smoothers.setdefault(name, Smoother())
        smoother.strength = stick.smoothing
        x, y = smoother.update(target[0], target[1], delta)

        accelerator = self._accelerators.setdefault(name, Accelerator())
        accelerator.factor = stick.accel
        accelerator.ramp_seconds = stick.accel_time
        magnitude = max(abs(target[0]), abs(target[1]))
        speed = stick.speed * accelerator.update(magnitude, delta)
        if precision:
            speed *= stick.precision

        carry = self._carry.setdefault(name, SubPixel())
        if x == 0.0 and y == 0.0:
            carry.reset()
            return

        if stick.mode == "mouse":
            dx, dy = carry.take(x * speed * delta, y * speed * delta)
            if dx or dy:
                self._events += 1
                self.backend.mouse_move(dx, dy)
        else:
            # pynput scrolls with positive y meaning "up", the opposite of
            # the stick's y-up-is-negative convention.
            dx, dy = carry.take(x * speed * delta, -y * speed * delta)
            if dx or dy:
                self._events += 1
                self.backend.scroll(dx, dy)

    def _stick_directions(
        self, stick: StickConfig, state: PadState, name: str
    ) -> Mapping[str, bool]:
        """Which of up/down/left/right a stick currently counts as pressing."""
        x, y = stick_vector(
            self.axis(state, f"{name}_x"),
            self.axis(state, f"{name}_y"),
            deadzone=stick.deadzone,
            curve=1.0,  # Thresholding wants the raw magnitude, not a shaped one.
            invert_x=stick.invert_x,
            invert_y=stick.invert_y,
            outer=stick.outer_deadzone,
        )
        threshold = stick.threshold
        active = {
            "up": y <= -threshold,
            "down": y >= threshold,
            "left": x <= -threshold,
            "right": x >= threshold,
        }
        return {direction: active[direction] for direction in DPAD_NAMES}

    # --- Misc ----------------------------------------------------------------

    def _status(self, message: str) -> None:
        if self._on_status is not None:
            self._on_status(message)


def _scroll_step(direction: str) -> tuple[int, int]:
    """One scroll click in the named direction, in pynput's (dx, dy) terms."""
    return {
        "up": (0, 1),
        "down": (0, -1),
        "left": (-1, 0),
        "right": (1, 0),
    }[direction]
