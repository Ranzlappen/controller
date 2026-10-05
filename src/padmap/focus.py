"""Which window currently has focus.

padmap does not need this to *send* input — it injects at the OS level, so
whatever it sends already goes wherever focus is. What this is for is telling
you so: the setup wizard reports the focused window live, which is how you
confirm that the thing you are about to control is the thing padmap is pointed
at, rather than the terminal you launched it from.

No new dependencies. Windows goes through ctypes, X11 and macOS shell out to
tools those platforms already ship. Every backend is allowed to fail — focus
detection is a diagnostic, never a prerequisite — so the whole module answers
``None`` rather than raising.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

__all__ = ["FocusInfo", "focus_backend_name", "foreground_window", "parse_wm_class"]

#: Shelling out is cheap but not free, and the wizard polls. Anything slower
#: than this is a broken environment, not a slow one.
TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class FocusInfo:
    """The focused window, as much as the platform will say."""

    app: str = ""
    title: str = ""

    def __str__(self) -> str:
        if self.app and self.title:
            return f"{self.app} — {self.title}"
        return self.app or self.title or "unknown"

    @property
    def known(self) -> bool:
        """Whether anything at all was identified."""
        return bool(self.app or self.title)


def focus_backend_name() -> str:
    """Which detection route applies on this machine."""
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "applescript"
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "xprop"
    return "none"


def parse_wm_class(output: str) -> str:
    """Pull the application name out of ``xprop WM_CLASS`` output.

    X11 reports a pair — instance and class — and the second is the one humans
    recognise (``"firefox", "Firefox"``). Kept separate from the subprocess
    call so the parsing is testable without an X server.
    """
    names = re.findall(r'"([^"]*)"', output)
    return names[-1] if names else ""


def parse_wm_name(output: str) -> str:
    """Pull the window title out of ``xprop _NET_WM_NAME`` / ``WM_NAME`` output."""
    match = re.search(r'=\s*"(.*)"\s*$', output.strip(), re.S)
    return match.group(1) if match else ""


def parse_active_window_id(output: str) -> str:
    """Pull the window id out of ``xprop -root _NET_ACTIVE_WINDOW`` output."""
    match = re.search(r"(0x[0-9a-fA-F]+)", output)
    return match.group(1) if match else ""


def _run(command: list[str]) -> str:  # pragma: no cover - shells out
    """Run a helper, returning its stdout or an empty string."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _xprop_window() -> FocusInfo | None:  # pragma: no cover - needs an X server
    if not shutil.which("xprop"):
        return None
    window = parse_active_window_id(_run(["xprop", "-root", "_NET_ACTIVE_WINDOW"]))
    if not window:
        return None
    app = parse_wm_class(_run(["xprop", "-id", window, "WM_CLASS"]))
    title = parse_wm_name(_run(["xprop", "-id", window, "_NET_WM_NAME"]))
    return FocusInfo(app=app, title=title)


def _macos_window() -> FocusInfo | None:  # pragma: no cover - needs macOS
    script = (
        'tell application "System Events" to get name of first '
        "application process whose frontmost is true"
    )
    app = _run(["osascript", "-e", script]).strip()
    return FocusInfo(app=app) if app else None


def _win32_window() -> FocusInfo | None:  # pragma: no cover - needs Windows
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    handle = user32.GetForegroundWindow()
    if not handle:
        return None

    length = user32.GetWindowTextLengthW(handle)
    title = ""
    if length:
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        title = buffer.value

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    app = ""
    if pid.value:
        process_query_limited_information = 0x1000
        process = kernel32.OpenProcess(process_query_limited_information, False, pid.value)
        if process:
            try:
                buffer = ctypes.create_unicode_buffer(512)
                size = wintypes.DWORD(len(buffer))
                if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                    app = os.path.basename(buffer.value)
            finally:
                kernel32.CloseHandle(process)
    return FocusInfo(app=app, title=title)


def foreground_window() -> FocusInfo | None:
    """The focused window, or None if this platform will not say.

    Never raises. A missing helper, a Wayland session or a locked-down machine
    all answer None, and the caller treats that as "cannot tell" rather than
    as a failure.
    """
    backend = focus_backend_name()
    try:
        if backend == "win32":
            return _win32_window()
        if backend == "applescript":
            return _macos_window()
        if backend == "xprop":
            return _xprop_window()
    except Exception:  # pragma: no cover - defensive; this is a diagnostic
        return None
    return None
