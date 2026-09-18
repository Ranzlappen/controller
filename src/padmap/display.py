"""Terminal presentation: the live status line and the dry-run trace.

Kept apart from :mod:`padmap.cli` so that what padmap *does* and how it *reads*
stay separable — and so the wording of anything a user sees is pinned by tests
rather than eyeballed. Nothing here touches hardware or the engine's internals;
it renders an :class:`~padmap.engine.EngineStatus` and nothing more.
"""

from __future__ import annotations

import sys
import time
from typing import Any

from padmap.backends import Event
from padmap.engine import EngineStatus

__all__ = ["DryRunPrinter", "StatusLine", "format_duration", "render_status"]

SPINNER = "◌"
RUNNING = "●"
PAUSED = "⏸"


def render_status(status: EngineStatus, width: int = 0) -> str:
    """One line describing what the engine is doing right now.

    Pure, so the wording is pinned by tests rather than eyeballed. Kept short
    enough to sit on one terminal line next to a prompt.
    """
    if status.settling:
        return f"{SPINNER} {status.profile} │ centring sticks…"

    parts = (
        [f"{PAUSED} {status.profile} │ PAUSED"]
        if status.paused
        else [f"{RUNNING} {status.profile}"]
    )
    if not status.paused:
        if status.layers:
            parts.append("layer " + "+".join(status.layers))
        if status.precision:
            parts.append("precision")
        if status.worst_drift >= 0.02:
            parts.append(f"drift {status.worst_drift:.2f} corrected")
        parts.append(f"{status.events:,} event" + ("" if status.events == 1 else "s"))
    line = " │ ".join(parts)
    return line[: width - 1] + "…" if width and len(line) > width else line


class StatusLine:
    """Redraws a single status line in place, when there is a terminal to draw on.

    Falls back to silence rather than scrolling: a detached session's log would
    otherwise fill with thousands of near-identical lines, and the log is where
    the useful messages live.
    """

    def __init__(self, stream: Any = None, enabled: bool | None = None) -> None:
        self.stream = stream if stream is not None else sys.stdout
        if enabled is None:
            enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self.enabled = enabled
        self._painted = 0

    def __call__(self, status: EngineStatus) -> None:
        """Render one frame."""
        if not self.enabled:
            return
        text = render_status(status)
        self.stream.write("\r" + text + " " * max(0, self._painted - len(text)))
        self.stream.flush()
        self._painted = len(text)

    def clear(self) -> None:
        """Wipe the line so ordinary output starts clean."""
        if self.enabled and self._painted:
            self.stream.write("\r" + " " * self._painted + "\r")
            self.stream.flush()
            self._painted = 0


class DryRunPrinter:
    """Prints dry-run events, collapsing pointer motion so it stays readable."""

    def __init__(self, motion_interval: float = 0.25, clock: Any = time.monotonic) -> None:
        self._motion_interval = motion_interval
        self._clock = clock
        self._motion = [0, 0]
        self._next_motion_print = 0.0

    def __call__(self, event: Event) -> None:
        if event.kind != "mouse_move":
            print(f"  {event}")
            return
        dx, dy = (int(part) for part in event.detail.split(","))
        self._motion[0] += dx
        self._motion[1] += dy
        now = self._clock()
        if now >= self._next_motion_print:
            print(f"  mouse_move {self._motion[0]:+d},{self._motion[1]:+d} (since last line)")
            self._motion = [0, 0]
            self._next_motion_print = now + self._motion_interval


def format_duration(seconds: float) -> str:
    """A short human duration: 45s, 3m 20s, 2h 05m."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m"
