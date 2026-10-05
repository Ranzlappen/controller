"""Preflight: can this machine actually run padmap, and what will bite?

Every real padmap problem so far has been environmental rather than a bug —
Wayland refusing synthetic input, macOS withholding Accessibility, a pad the
kernel never bound. Those are cheap to detect and expensive to debug blind, so
they get checked up front and named.

The world is probed once into an :class:`Environment`, and :func:`evaluate`
turns that into verdicts. Keeping the judgement pure is what lets every verdict
— including the ones for platforms this machine is not — be tested.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from padmap.focus import FocusInfo

__all__ = ["FAIL", "OK", "WARN", "Check", "Environment", "evaluate", "probe", "worst"]

OK = "ok"
WARN = "warn"
FAIL = "fail"

#: Verdicts in increasing order of "you need to do something about this".
SEVERITY = {OK: 0, WARN: 1, FAIL: 2}

MINIMUM_PYTHON = (3, 10)


@dataclass(frozen=True)
class Check:
    """One verdict about the environment."""

    name: str
    status: str
    detail: str
    fix: str = ""

    @property
    def mark(self) -> str:
        """A single character for the status column."""
        return {OK: "✓", WARN: "!", FAIL: "✗"}[self.status]


@dataclass(frozen=True)
class Environment:
    """Raw facts about the machine, gathered once."""

    python: tuple[int, int] = sys.version_info[:2]
    platform: str = "linux"
    #: ``x11``, ``wayland``, ``win32``, ``darwin``, or ``headless``.
    session: str = "x11"
    controllers: tuple[str, ...] = ()
    #: Empty when the output backend started; the error text otherwise.
    backend_error: str = ""
    focus: FocusInfo | None = None
    focus_backend: str = "none"
    runtime_dir: str = ""
    runtime_writable: bool = True
    tray_available: bool = False
    extras: dict[str, str] = field(default_factory=dict)


def evaluate(env: Environment) -> list[Check]:
    """Turn gathered facts into an ordered list of verdicts."""
    return [
        _python(env),
        _session(env),
        _output(env),
        _controller(env),
        _focus(env),
        _background(env),
        _tray(env),
    ]


def worst(checks: list[Check]) -> str:
    """The most serious status in a list of checks."""
    return max((check.status for check in checks), key=lambda s: SEVERITY[s], default=OK)


def _python(env: Environment) -> Check:
    version = ".".join(str(part) for part in env.python)
    if env.python >= MINIMUM_PYTHON:
        return Check("Python", OK, f"{version}")
    needed = ".".join(str(part) for part in MINIMUM_PYTHON)
    return Check("Python", FAIL, f"{version} is too old", f"padmap needs Python {needed} or newer.")


def _session(env: Environment) -> Check:
    if env.session == "wayland":
        return Check(
            "Display session",
            FAIL,
            "Wayland",
            "Wayland compositors reject synthetic input from an ordinary process. "
            "Log into an X11/Xorg session at the login screen.",
        )
    if env.session == "headless":
        return Check(
            "Display session",
            FAIL,
            "no display",
            "padmap needs a graphical session to send input into. On Linux, set DISPLAY.",
        )
    return Check(
        "Display session",
        OK,
        {"x11": "X11", "win32": "Windows", "darwin": "macOS"}.get(env.session, env.session),
    )


def _output(env: Environment) -> Check:
    if not env.backend_error:
        return Check("Keyboard/mouse output", OK, "ready")
    if "not installed" in env.backend_error:
        fix = "Install padmap's dependencies with `pip install -e .`"
    elif env.platform == "darwin":
        fix = (
            "System Settings → Privacy & Security → Accessibility → enable your terminal, "
            "then restart it. The permission is read at launch."
        )
    elif env.session == "wayland":
        fix = "Log into an X11/Xorg session instead."
    elif env.session == "headless":
        fix = "There is no graphical session here to send input into. Set DISPLAY, or run padmap on your desktop."
    else:
        fix = "Install padmap's dependencies with `pip install -e .`"
    return Check("Keyboard/mouse output", FAIL, env.backend_error, fix)


def _controller(env: Environment) -> Check:
    if not env.controllers:
        return Check(
            "Controller",
            FAIL,
            "none detected",
            "Plug in or pair the pad, then re-run. On Linux check `lsmod | grep xpad` "
            "and that you are in the `input` group.",
        )
    if len(env.controllers) == 1:
        return Check("Controller", OK, env.controllers[0])
    return Check(
        "Controller",
        WARN,
        f"{len(env.controllers)} found: {', '.join(env.controllers)}",
        "Pin one with `device.match` in your profile, or `--device <index>`, so padmap "
        "does not pick a different pad next time.",
    )


def _focus(env: Environment) -> Check:
    if env.focus is not None and env.focus.known:
        return Check("Focused window", OK, str(env.focus))
    if env.focus_backend == "none":
        return Check(
            "Focused window",
            WARN,
            "cannot tell on this session",
            "Only a diagnostic — padmap injects at the OS level, so input still goes "
            "to whichever window has focus.",
        )
    hint = {
        "xprop": "Install x11-utils for `xprop` to enable this.",
        "wayland": "Wayland does not expose the focused window to ordinary processes.",
    }.get(env.focus_backend, "")
    return Check("Focused window", WARN, f"{env.focus_backend} reported nothing", hint)


def _background(env: Environment) -> Check:
    if env.runtime_writable:
        return Check("Background sessions", OK, f"state in {env.runtime_dir}")
    return Check(
        "Background sessions",
        WARN,
        f"cannot write {env.runtime_dir}",
        "`--detach`, `status` and `stop` need this directory. Point PADMAP_RUNTIME_DIR "
        "somewhere writable.",
    )


def _tray(env: Environment) -> Check:
    if env.tray_available:
        return Check("Tray icon", OK, "pystray and Pillow installed")
    return Check(
        "Tray icon",
        WARN,
        "not installed",
        "Optional. `pip install 'padmap[tray]'` if you want tray control.",
    )


# --- Probing -----------------------------------------------------------------


def detect_session() -> str:
    """Classify the graphical session this process is in."""
    if sys.platform == "win32":  # pragma: no cover - platform-specific
        return "win32"
    if sys.platform == "darwin":  # pragma: no cover - platform-specific
        return "darwin"
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "headless"


def probe() -> Environment:  # pragma: no cover - touches hardware and the desktop
    """Gather the facts :func:`evaluate` judges."""
    from padmap import runtime
    from padmap.focus import focus_backend_name, foreground_window

    controllers: tuple[str, ...] = ()
    try:
        from padmap.devices import list_devices

        controllers = tuple(device.name for device in list_devices())
    except Exception as exc:
        controllers = ()
        backend_note = str(exc)
    else:
        backend_note = ""

    backend_error = ""
    try:
        from padmap.backends import PynputBackend

        PynputBackend()
    except Exception as exc:
        backend_error = str(exc).split("\n")[0]

    tray_available = True
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
    except ImportError:
        tray_available = False

    runtime_dir = runtime.runtime_dir()
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        probe_file = runtime_dir / ".probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        writable = True
    except OSError:
        writable = False

    return Environment(
        python=sys.version_info[:2],
        platform=sys.platform,
        session=detect_session(),
        controllers=controllers,
        backend_error=backend_error,
        focus=foreground_window(),
        focus_backend=focus_backend_name(),
        runtime_dir=str(runtime_dir),
        runtime_writable=writable,
        tray_available=tray_available,
        extras={"devices": backend_note} if backend_note else {},
    )
