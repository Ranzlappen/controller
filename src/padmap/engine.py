"""The mapping loop: controller state in, keyboard and mouse events out.

:meth:`Engine.tick` is deliberately a pure-ish step — hand it a timestamp and a
:class:`~padmap.devices.PadState` and it emits the right calls on the backend.
:meth:`Engine.run` is the thin loop around it. That split is what lets the whole
mapping behaviour (edges, turbo, toggles, sub-pixel motion) be tested with a
:class:`~padmap.backends.RecordingBackend` and no hardware at all.

The one rule that outranks everything here: **never leave a key stuck down.**
Anything that stops output — pausing, quitting, a crash, Ctrl-C — goes through
:meth:`release_all` first.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator

from padmap.actions import Action
from padmap.backends import OutputBackend
from padmap.config import Binding, Profile, StickConfig
from padmap.curves import SubPixel, stick_vector
from padmap.devices import DPAD_NAMES, ControllerSource, PadState

__all__ = ["Engine"]

#: Ceiling on the time delta used for analogue motion. Without it, a stalled
#: poll (a laptop waking from sleep, say) would fling the cursor across the
#: screen in one tick.
MAX_TICK_SECONDS = 0.1


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
    ) -> None:
        self.profile = profile
        self.controller = controller
        self.backend = backend
        self._clock = clock
        self._sleep = sleep
        self._on_status = on_status

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
        self._last_tick: float | None = None

    # --- Public API ----------------------------------------------------------

    def run(self) -> None:
        """Poll and map until :meth:`stop` is called or the loop is interrupted."""
        self.running = True
        period = 1.0 / self.profile.poll_hz
        try:
            while self.running:
                started = self._clock()
                self.tick(started)
                remaining = period - (self._clock() - started)
                if remaining > 0:
                    self._sleep(remaining)
        finally:
            self.release_all()
            self.running = False

    def stop(self) -> None:
        """Ask :meth:`run` to finish after the current tick."""
        self.running = False

    def tick(self, now: float, state: PadState | None = None) -> None:
        """Process exactly one poll of the controller."""
        if state is None:
            state = self.controller.poll()

        delta = 0.0 if self._last_tick is None else min(now - self._last_tick, MAX_TICK_SECONDS)
        self._last_tick = now

        for slot, binding, is_down in self._digital_inputs(state):
            self._apply_binding(slot, binding, is_down, now)

        if not self.paused:
            self._apply_analogue(state, delta)

    def release_all(self) -> None:
        """Let go of every held key and mouse button. Safe to call twice."""
        for slot in list(self._active):
            self._release(slot)
        self._latched.clear()
        self._next_pulse.clear()
        for carry in self._carry.values():
            carry.reset()

    def set_paused(self, paused: bool) -> None:
        """Pause or resume output, releasing anything held on the way in."""
        if paused == self.paused:
            return
        self.paused = paused
        if paused:
            self.release_all()
        self._status("paused — output suppressed" if paused else "resumed")

    # --- Input decomposition -------------------------------------------------

    def _digital_inputs(self, state: PadState) -> Iterator[tuple[str, Binding, bool]]:
        """Yield every on/off input the profile binds, with its current state."""
        for name, binding in self.profile.buttons.items():
            yield f"button.{name}", binding, state.button(name)

        for name, binding in self.profile.dpad.items():
            yield f"dpad.{name}", binding, state.dpad.get(name, False)

        for name, trigger in self.profile.triggers.items():
            yield f"trigger.{name}", trigger.binding, state.axis(name) >= trigger.threshold

        for stick_name, stick in self.profile.sticks.items():
            if stick.mode != "keys":
                continue
            for direction, is_down in _stick_directions(stick, state, stick_name).items():
                binding = stick.directions.get(direction)
                if binding is not None:
                    yield f"stick.{stick_name}.{direction}", binding, is_down

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
            if pressed:
                self._run_special(action)
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
        """Keep an action down for exactly as long as the input is down."""
        if effective and slot not in self._active:
            self._press(action)
            self._active[slot] = action
        elif not effective and slot in self._active:
            self._release(slot)

    def _fire_once(self, action: Action) -> None:
        if action.kind == "text":
            self.backend.type_text(action.text)
        elif action.kind == "scroll":
            dx, dy = _scroll_step(action.direction)
            self.backend.scroll(dx, dy)

    def _press(self, action: Action) -> None:
        if action.kind == "key":
            self.backend.key_down(action.keys)
        elif action.kind == "mouse":
            self.backend.mouse_down(action.button)

    def _unpress(self, action: Action) -> None:
        if action.kind == "key":
            self.backend.key_up(action.keys)
        elif action.kind == "mouse":
            self.backend.mouse_up(action.button)

    def _release(self, slot: str) -> None:
        action = self._active.pop(slot, None)
        if action is not None:
            self._unpress(action)

    def _run_special(self, action: Action) -> None:
        if action.command == "toggle_pause":
            self.set_paused(not self.paused)
        elif action.command == "quit":
            self._status("quit requested from the controller")
            self.stop()

    # --- Analogue handling ---------------------------------------------------

    def _apply_analogue(self, state: PadState, delta: float) -> None:
        """Turn stick deflection into pointer motion and scrolling."""
        if delta <= 0:
            return
        for name, stick in self.profile.sticks.items():
            if stick.mode not in ("mouse", "scroll"):
                continue
            x, y = stick_vector(
                state.axis(f"{name}_x"),
                state.axis(f"{name}_y"),
                deadzone=stick.deadzone,
                curve=stick.curve,
                invert_x=stick.invert_x,
                invert_y=stick.invert_y,
            )
            if x == 0.0 and y == 0.0:
                self._carry.setdefault(name, SubPixel()).reset()
                continue

            carry = self._carry.setdefault(name, SubPixel())
            if stick.mode == "mouse":
                dx, dy = carry.take(x * stick.speed * delta, y * stick.speed * delta)
                if dx or dy:
                    self.backend.mouse_move(dx, dy)
            else:
                # pynput scrolls with positive y meaning "up", the opposite of
                # the stick's y-up-is-negative convention.
                dx, dy = carry.take(x * stick.speed * delta, -y * stick.speed * delta)
                if dx or dy:
                    self.backend.scroll(dx, dy)

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


def _stick_directions(stick: StickConfig, state: PadState, name: str) -> dict[str, bool]:
    """Which of up/down/left/right a stick currently counts as pressing."""
    x, y = stick_vector(
        state.axis(f"{name}_x"),
        state.axis(f"{name}_y"),
        deadzone=stick.deadzone,
        curve=1.0,  # Thresholding wants the raw magnitude, not a shaped one.
        invert_x=stick.invert_x,
        invert_y=stick.invert_y,
    )
    threshold = stick.threshold
    active = {
        "up": y <= -threshold,
        "down": y >= threshold,
        "left": x <= -threshold,
        "right": x >= threshold,
    }
    return {direction: active[direction] for direction in DPAD_NAMES}
