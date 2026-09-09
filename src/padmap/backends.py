"""Output backends — the half of padmap that presses keys and moves the mouse.

:class:`PynputBackend` is the real one. :class:`RecordingBackend` records what
*would* have happened, which powers both ``padmap run --dry-run`` and the test
suite: the engine can be driven end to end with no display, no controller and
no synthetic input reaching the desktop.

pynput is imported inside :meth:`PynputBackend.__init__` rather than at module
scope. On a headless Linux box importing it raises outright, and a dry run
should never need a display.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = ["BackendError", "Event", "OutputBackend", "PynputBackend", "RecordingBackend"]


class BackendError(RuntimeError):
    """Raised when the output backend cannot be started."""


class OutputBackend(Protocol):
    """Everything the engine needs to affect the desktop."""

    def key_down(self, keys: Sequence[str]) -> None:
        """Press each key in order (modifiers first for a combo)."""
        ...

    def key_up(self, keys: Sequence[str]) -> None:
        """Release each key in reverse order."""
        ...

    def type_text(self, text: str) -> None:
        """Type a literal string."""
        ...

    def mouse_down(self, button: str) -> None:
        """Press a mouse button."""
        ...

    def mouse_up(self, button: str) -> None:
        """Release a mouse button."""
        ...

    def mouse_move(self, dx: int, dy: int) -> None:
        """Move the pointer by a relative pixel delta."""
        ...

    def scroll(self, dx: int, dy: int) -> None:
        """Scroll by whole clicks; positive ``dy`` is up."""
        ...

    def close(self) -> None:
        """Release any resources held by the backend."""
        ...


@dataclass(frozen=True)
class Event:
    """One thing a backend was asked to do. Used by dry runs and tests."""

    kind: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.kind} {self.detail}".strip()


@dataclass
class RecordingBackend:
    """Records calls instead of performing them.

    ``on_event`` is called for every recorded event, which is how ``--dry-run``
    prints a live trace without the engine knowing anything about printing.
    """

    events: list[Event] = field(default_factory=list)
    on_event: Callable[[Event], None] | None = None

    def _record(self, kind: str, detail: str = "") -> None:
        event = Event(kind, detail)
        self.events.append(event)
        if self.on_event is not None:
            self.on_event(event)

    def key_down(self, keys: Sequence[str]) -> None:
        """Record a key press."""
        self._record("key_down", "+".join(keys))

    def key_up(self, keys: Sequence[str]) -> None:
        """Record a key release."""
        self._record("key_up", "+".join(keys))

    def type_text(self, text: str) -> None:
        """Record typed text."""
        self._record("type", text)

    def mouse_down(self, button: str) -> None:
        """Record a mouse button press."""
        self._record("mouse_down", button)

    def mouse_up(self, button: str) -> None:
        """Record a mouse button release."""
        self._record("mouse_up", button)

    def mouse_move(self, dx: int, dy: int) -> None:
        """Record a pointer move."""
        self._record("mouse_move", f"{dx},{dy}")

    def scroll(self, dx: int, dy: int) -> None:
        """Record a scroll."""
        self._record("scroll", f"{dx},{dy}")

    def close(self) -> None:
        """Record the shutdown."""
        self._record("close")

    def log(self) -> list[str]:
        """The recorded events as strings, handy in assertions."""
        return [str(event) for event in self.events]


class PynputBackend:  # pragma: no cover - drives the real desktop
    """Synthesises real keyboard and mouse input through pynput."""

    def __init__(self) -> None:
        try:
            from pynput import keyboard, mouse
        except ImportError as exc:
            raise BackendError(
                "pynput is not installed. Install padmap's dependencies with "
                "`pip install -e .` (or `pip install pynput`)."
            ) from exc
        except Exception as exc:
            # On Linux pynput resolves an X11/uinput backend at import time and
            # raises if there is no display to talk to.
            raise BackendError(
                f"pynput could not start ({exc}). On Linux, padmap needs an "
                "X11 session (or a uinput-capable backend) to send input."
            ) from exc

        self._keyboard_module = keyboard
        self._mouse_module = mouse
        self._keyboard = keyboard.Controller()
        self._mouse = mouse.Controller()
        self._key_cache: dict[str, Any] = {}

    def _key(self, name: str) -> Any:
        """Translate a padmap key name into a pynput key object."""
        cached = self._key_cache.get(name)
        if cached is not None:
            return cached
        keyboard = self._keyboard_module
        key = getattr(keyboard.Key, name, None)
        if key is None:
            key = keyboard.KeyCode.from_char(name)
        self._key_cache[name] = key
        return key

    def _button(self, name: str) -> Any:
        return getattr(self._mouse_module.Button, name)

    def key_down(self, keys: Sequence[str]) -> None:
        """Press a key or combo, modifiers first."""
        for name in keys:
            self._keyboard.press(self._key(name))

    def key_up(self, keys: Sequence[str]) -> None:
        """Release a key or combo, modifiers last."""
        for name in reversed(list(keys)):
            self._keyboard.release(self._key(name))

    def type_text(self, text: str) -> None:
        """Type a literal string."""
        self._keyboard.type(text)

    def mouse_down(self, button: str) -> None:
        """Press a mouse button."""
        self._mouse.press(self._button(button))

    def mouse_up(self, button: str) -> None:
        """Release a mouse button."""
        self._mouse.release(self._button(button))

    def mouse_move(self, dx: int, dy: int) -> None:
        """Move the pointer relative to where it is now."""
        self._mouse.move(dx, dy)

    def scroll(self, dx: int, dy: int) -> None:
        """Scroll by whole clicks."""
        self._mouse.scroll(dx, dy)

    def close(self) -> None:
        """Nothing to release — pynput controllers are stateless handles."""
