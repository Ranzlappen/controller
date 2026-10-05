"""Macros: a named sequence of actions, played out over time.

A macro cannot simply be executed when its button is pressed — it contains
waits, and sleeping inside the mapping loop would freeze every other input on
the pad for the duration. So a running macro is *state*: the engine advances it
a little on each tick, and :class:`MacroRunner` is where that state lives.

Every step is reduced at parse time to one of four primitives — ``down``,
``up``, ``fire``, ``wait`` — which makes the runner small enough to reason
about. A bare action string becomes ``down`` + a short ``wait`` + ``up``,
because a zero-length keypress is missed by a surprising number of
applications.

Anything a macro still holds when it ends is released. A macro that latches a
modifier down with no way back up is precisely the stuck-key bug this project
treats as its worst failure, so the runner refuses to leave one behind.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from padmap.actions import Action, ActionError, parse_action

__all__ = [
    "DOWN",
    "FIRE",
    "Macro",
    "MacroError",
    "MacroRunner",
    "MacroSink",
    "MacroStep",
    "UP",
    "WAIT",
    "parse_macro",
]

DOWN = "down"
UP = "up"
FIRE = "fire"
WAIT = "wait"

#: How long a bare action string in a macro is held before being released.
#: Long enough that applications notice the keypress, short enough to feel
#: instant at human timescales.
DEFAULT_TAP_SECONDS = 0.02

#: Guard rails. A macro longer than this is a program, and padmap is not a
#: scripting host; a wait longer than this is almost certainly a typo.
MAX_STEPS = 100
MAX_WAIT_SECONDS = 30.0


class MacroError(ValueError):
    """Raised when a macro definition is malformed."""


@dataclass(frozen=True)
class MacroStep:
    """One primitive of a macro: press, release, fire-and-forget, or wait."""

    kind: str
    action: Action | None = None
    seconds: float = 0.0

    def __str__(self) -> str:
        if self.kind == WAIT:
            return f"wait {self.seconds * 1000:.0f}ms"
        return f"{self.kind} {self.action}"


@dataclass(frozen=True)
class Macro:
    """A named, ordered sequence of steps."""

    name: str
    steps: tuple[MacroStep, ...] = ()
    #: When true, releasing the button cuts the macro short instead of letting
    #: it finish. Useful for long sequences; off by default, because "it ran
    #: half of my macro" is a worse surprise than "it finished".
    interruptible: bool = False

    @property
    def duration(self) -> float:
        """Total time the macro spends waiting, in seconds."""
        return sum(step.seconds for step in self.steps if step.kind == WAIT)

    def describe(self) -> str:
        """One-line summary for ``padmap validate``."""
        return f"{len(self.steps)} steps, {self.duration * 1000:.0f}ms" + (
            ", interruptible" if self.interruptible else ""
        )


class MacroSink(Protocol):
    """What a runner needs in order to make a macro happen.

    Implemented by the engine, so macros never touch an output backend
    directly and a test can watch exactly what a macro would do.
    """

    def press(self, action: Action) -> None:
        """Hold an action down."""
        ...

    def release(self, action: Action) -> None:
        """Let an action back up."""
        ...

    def fire(self, action: Action) -> None:
        """Perform a one-shot action (text, scroll, pointer nudge)."""
        ...


# --- Parsing -----------------------------------------------------------------


def _action(spec: Any, path: str) -> Action:
    try:
        action = parse_action(spec)
    except ActionError as exc:
        raise MacroError(f"{path}: {exc}") from exc
    if action.kind == "macro":
        raise MacroError(f"{path}: a macro cannot call another macro")
    if action.kind == "special":
        raise MacroError(
            f"{path}: a macro cannot contain a special ({action}). Pausing or switching "
            "layers part-way through a sequence has no sensible meaning."
        )
    return action


def _seconds(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MacroError(f"{path}: expected a number of seconds")
    seconds = float(value)
    if not 0.0 < seconds <= MAX_WAIT_SECONDS:
        raise MacroError(f"{path}: {seconds:g}s is outside (0, {MAX_WAIT_SECONDS:g}]")
    return seconds


def _expand(entry: Any, path: str, tap_seconds: float) -> list[MacroStep]:
    """Turn one written step into primitives."""
    if isinstance(entry, str):
        action = _action(entry, path)
        if not action.is_held:
            # text / scroll / move have no press-release pair to split.
            return [MacroStep(kind=FIRE, action=action)]
        return [
            MacroStep(kind=DOWN, action=action),
            MacroStep(kind=WAIT, seconds=tap_seconds),
            MacroStep(kind=UP, action=action),
        ]

    if not isinstance(entry, Mapping):
        raise MacroError(f"{path}: expected a string or an object, got {type(entry).__name__}")

    unknown = sorted(set(entry) - {"wait", "down", "up"})
    if unknown:
        raise MacroError(
            f"{path}: unknown key(s) {', '.join(repr(k) for k in unknown)}. Valid: wait, down, up"
        )
    if len(entry) != 1:
        raise MacroError(f"{path}: give exactly one of wait, down or up per step")

    if "wait" in entry:
        return [MacroStep(kind=WAIT, seconds=_seconds(entry["wait"], f"{path}.wait"))]

    kind = DOWN if "down" in entry else UP
    action = _action(entry[kind], f"{path}.{kind}")
    if not action.is_held:
        raise MacroError(
            f"{path}.{kind}: {action} cannot be held — it has no press and release. "
            "Write it as a plain step instead."
        )
    return [MacroStep(kind=kind, action=action)]


def parse_macro(name: str, raw: Any, path: str = "") -> Macro:
    """Build a :class:`Macro` from its profile-JSON form."""
    path = path or f"macros.{name}"
    interruptible = False
    tap_seconds = DEFAULT_TAP_SECONDS

    if isinstance(raw, Mapping):
        unknown = sorted(set(raw) - {"steps", "interruptible", "tap"})
        if unknown:
            raise MacroError(
                f"{path}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
                "Valid: steps, interruptible, tap"
            )
        if "steps" not in raw:
            raise MacroError(f"{path}: needs a 'steps' list")
        entries = raw["steps"]
        if "interruptible" in raw:
            if not isinstance(raw["interruptible"], bool):
                raise MacroError(f"{path}.interruptible: expected true or false")
            interruptible = raw["interruptible"]
        if "tap" in raw:
            tap_seconds = _seconds(raw["tap"], f"{path}.tap")
    else:
        entries = raw

    if not isinstance(entries, Sequence) or isinstance(entries, str):
        raise MacroError(f"{path}: expected a list of steps")
    if not entries:
        raise MacroError(f"{path}: has no steps")

    steps: list[MacroStep] = []
    for index, entry in enumerate(entries):
        steps.extend(_expand(entry, f"{path}[{index}]", tap_seconds))
    if len(steps) > MAX_STEPS:
        raise MacroError(f"{path}: {len(steps)} steps exceeds the {MAX_STEPS}-step limit")

    return Macro(name=name, steps=tuple(steps), interruptible=interruptible)


def parse_macros(raw: Mapping[str, Any]) -> dict[str, Macro]:
    """Validate a whole ``macros`` section."""
    return {
        name.lower(): parse_macro(name.lower(), value, f"macros.{name}")
        for name, value in raw.items()
    }


# --- Running -----------------------------------------------------------------


@dataclass
class _Run:
    """One in-flight playthrough of a macro."""

    macro: Macro
    index: int = 0
    resume_at: float = 0.0
    held: list[Action] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.index >= len(self.macro.steps)


@dataclass
class MacroRunner:
    """Advances every in-flight macro a little on each tick."""

    runs: dict[str, _Run] = field(default_factory=dict)

    @property
    def active(self) -> tuple[str, ...]:
        """Names of the macros currently playing."""
        return tuple(sorted(self.runs))

    def is_running(self, name: str) -> bool:
        """Whether this macro is already in flight."""
        return name in self.runs

    def start(self, macro: Macro, now: float) -> bool:
        """Begin a macro. Returns False if it was already playing.

        Re-triggering does not restart: mashing the button during a sequence
        would otherwise interleave two copies of it.
        """
        if macro.name in self.runs:
            return False
        self.runs[macro.name] = _Run(macro=macro, resume_at=now)
        return True

    def advance(self, now: float, sink: MacroSink) -> None:
        """Run every macro forward to wherever ``now`` has got to."""
        for name in list(self.runs):
            run = self.runs.get(name)
            if run is None:
                continue
            self._advance_one(run, now, sink)
            if run.finished:
                self._finish(run, sink)

    def _advance_one(self, run: _Run, now: float, sink: MacroSink) -> None:
        while not run.finished and now >= run.resume_at:
            step = run.macro.steps[run.index]
            run.index += 1
            if step.kind == WAIT:
                run.resume_at = now + step.seconds
                continue
            if step.action is None:  # pragma: no cover - parser guarantees this
                continue
            if step.kind == DOWN:
                sink.press(step.action)
                run.held.append(step.action)
            elif step.kind == UP:
                sink.release(step.action)
                if step.action in run.held:
                    run.held.remove(step.action)
            else:
                sink.fire(step.action)

    def _finish(self, run: _Run, sink: MacroSink) -> None:
        """Retire a run, letting go of anything it still holds."""
        for action in reversed(run.held):
            sink.release(action)
        run.held.clear()
        self.runs.pop(run.macro.name, None)

    def cancel(self, name: str, sink: MacroSink) -> None:
        """Cut one macro short, releasing whatever it holds."""
        run = self.runs.get(name)
        if run is not None:
            self._finish(run, sink)

    def cancel_interruptible(self, names: Iterable[str], sink: MacroSink) -> None:
        """Cut short the named macros, but only those that allow it."""
        for name in list(names):
            run = self.runs.get(name)
            if run is not None and run.macro.interruptible:
                self._finish(run, sink)

    def release_all(self, sink: MacroSink) -> None:
        """Abandon every macro and release everything they hold."""
        for name in list(self.runs):
            self.cancel(name, sink)
