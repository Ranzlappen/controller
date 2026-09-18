"""Running padmap as a background process, and talking to one that is running.

A remapper that needs a terminal window kept open is not really usable: the
terminal it was launched from is the focused window, so the first thing it does
is type into itself, and closing that window kills it. This module is what lets
`padmap run --detach` hand the session off and get out of the way.

Stopping a detached session is done through a **file**, not a signal. Signals
are the obvious mechanism and the wrong one here: Windows has no usable SIGTERM
for another process, and the engine already polls at over 100 Hz, so noticing a
file costs nothing and behaves identically on every platform.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = [
    "SessionState",
    "clear_state",
    "clear_stop",
    "process_alive",
    "read_state",
    "request_stop",
    "runtime_dir",
    "state_path",
    "stop_requested",
    "write_state",
]

#: Overrides the runtime directory. Mostly here so the tests never touch the
#: real one, but it is a legitimate escape hatch on a locked-down machine.
RUNTIME_DIR_ENV = "PADMAP_RUNTIME_DIR"


def runtime_dir() -> Path:
    """Where padmap keeps its session state, per platform convention."""
    override = os.environ.get(RUNTIME_DIR_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":  # pragma: no cover - platform-specific
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "padmap"
    if sys.platform == "darwin":  # pragma: no cover - platform-specific
        return Path.home() / "Library" / "Application Support" / "padmap"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:  # pragma: no cover - depends on the session manager
        return Path(runtime) / "padmap"
    return Path.home() / ".local" / "state" / "padmap"  # pragma: no cover


def state_path() -> Path:
    """The file describing the running session, if there is one."""
    return runtime_dir() / "session.json"


def stop_path() -> Path:
    """The file whose existence asks a running session to stop."""
    return runtime_dir() / "stop"


def log_path() -> Path:
    """Where a detached session writes its output."""
    return runtime_dir() / "padmap.log"


@dataclass(frozen=True)
class SessionState:
    """What a running session records about itself for `padmap status`."""

    pid: int
    profile: str
    started_at: float
    detached: bool = False
    log: str = ""

    @property
    def uptime(self) -> float:
        """Seconds since this session started."""
        return max(0.0, time.time() - self.started_at)

    @property
    def alive(self) -> bool:
        """Whether the recorded process still exists."""
        return process_alive(self.pid)


def write_state(state: SessionState) -> Path:
    """Record the running session, creating the runtime directory if needed."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    return path


def read_state() -> SessionState | None:
    """Read the recorded session, or None if there is no usable record.

    A corrupt or half-written file is treated as "no session" rather than an
    error: it is a cache, and refusing to start because of it would be worse
    than ignoring it.
    """
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return SessionState(
            pid=int(data["pid"]),
            profile=str(data.get("profile", "")),
            started_at=float(data.get("started_at", 0.0)),
            detached=bool(data.get("detached", False)),
            log=str(data.get("log", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def clear_state() -> None:
    """Forget the recorded session. Safe to call when there isn't one."""
    state_path().unlink(missing_ok=True)


def process_alive(pid: int) -> bool:
    """Whether a process with this id exists.

    Signal 0 performs the existence and permission check without delivering
    anything. A process we are not allowed to signal still counts as alive —
    it exists, which is the question being asked.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":  # pragma: no cover - platform-specific
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def request_stop() -> None:
    """Ask the running session to shut down at its next control poll."""
    path = stop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def stop_requested() -> bool:
    """Whether a stop has been requested since the last :func:`clear_stop`."""
    return stop_path().exists()


def clear_stop():  # noqa: ANN201
    """Drop a pending stop request, so the next session starts clean."""
    stop_path().unlink(missing_ok=True)


def stale_session() -> SessionState | None:
    """A recorded session whose process is gone, if any.

    Worth distinguishing from "no session": it means the last run died rather
    than exiting cleanly, and the log is probably worth reading.
    """
    state = read_state()
    return state if state is not None and not state.alive else None
