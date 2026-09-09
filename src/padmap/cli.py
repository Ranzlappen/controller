"""Command line interface.

``padmap run`` is the one people use daily; the rest exist to make authoring a
profile possible without guessing — ``devices`` says what is attached,
``monitor`` shows which raw index each physical button really is, ``validate``
explains a profile, and ``init`` writes one to edit.
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import sys
import time
from pathlib import Path
from typing import Any

from padmap import __version__
from padmap.actions import ActionError
from padmap.backends import BackendError, Event, RecordingBackend
from padmap.config import (
    Profile,
    ProfileError,
    bundled_profile_names,
    load_profile,
    starter_profile_json,
)
from padmap.devices import DeviceError
from padmap.engine import Engine

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (kept separate so tests can introspect it)."""
    parser = argparse.ArgumentParser(
        prog="padmap",
        description="Map an Xbox controller to keyboard keys and mouse movement.",
        epilog="Run `padmap monitor` first if you are unsure what your pad reports.",
    )
    parser.add_argument("--version", action="version", version=f"padmap {__version__}")
    subcommands = parser.add_subparsers(dest="command", metavar="<command>")

    run = subcommands.add_parser("run", help="start mapping (the main command)")
    run.add_argument(
        "-p",
        "--profile",
        default="desktop",
        help="bundled profile name or path to a .json profile (default: desktop)",
    )
    run.add_argument(
        "--device", type=int, default=None, help="controller index from `padmap devices`"
    )
    run.add_argument("--match", default=None, help="substring of the controller name to open")
    run.add_argument("--poll-hz", type=float, default=None, help="override the profile's poll rate")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be sent instead of sending it — safe to try anywhere",
    )
    run.add_argument("-q", "--quiet", action="store_true", help="suppress the startup summary")
    run.set_defaults(handler=_cmd_run)

    devices = subcommands.add_parser("devices", help="list attached controllers")
    devices.set_defaults(handler=_cmd_devices)

    monitor = subcommands.add_parser(
        "monitor", help="print raw button/axis indices as you press them"
    )
    monitor.add_argument("--device", type=int, default=None, help="controller index to watch")
    monitor.add_argument("--match", default=None, help="substring of the controller name to watch")
    monitor.set_defaults(handler=_cmd_monitor)

    profiles = subcommands.add_parser("profiles", help="list bundled profiles")
    profiles.set_defaults(handler=_cmd_profiles)

    validate = subcommands.add_parser("validate", help="check a profile and describe its mapping")
    validate.add_argument("profile", help="bundled profile name or path to a .json profile")
    validate.set_defaults(handler=_cmd_validate)

    init = subcommands.add_parser("init", help="write a starter profile you can edit")
    init.add_argument("path", type=Path, help="where to write the new profile")
    init.add_argument("-f", "--force", action="store_true", help="overwrite an existing file")
    init.set_defaults(handler=_cmd_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "handler", None) is None:
        parser.print_help()
        return EXIT_OK
    try:
        return int(args.handler(args))
    except (ProfileError, ActionError, DeviceError, BackendError) as exc:
        print(f"padmap: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover - depends on a real signal
        print("\npadmap: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


# --- Commands ----------------------------------------------------------------


def _cmd_profiles(_args: argparse.Namespace) -> int:
    """List the profiles shipped inside the package."""
    for name in bundled_profile_names():
        profile = load_profile(name)
        print(f"{name:<10} {profile.description}")
    print("\nCopy one to edit:  padmap init my-profile.json")
    return EXIT_OK


def _cmd_validate(args: argparse.Namespace) -> int:
    """Load a profile, report problems, and print what it maps."""
    profile = load_profile(args.profile)
    print(f"OK — {profile.source or args.profile} ({profile.binding_count} bindings)")
    print("\n".join(profile.describe()))
    return EXIT_OK


def _cmd_init(args: argparse.Namespace) -> int:
    """Write the starter profile to a path for the user to edit."""
    path: Path = args.path
    if path.exists() and not args.force:
        print(f"padmap: {path} already exists (use --force to overwrite)", file=sys.stderr)
        return EXIT_ERROR
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(starter_profile_json(), encoding="utf-8")
    print(f"Wrote {path}")
    print(f"Edit it, then run:  padmap run -p {path}")
    return EXIT_OK


def _cmd_devices(_args: argparse.Namespace) -> int:  # pragma: no cover - needs hardware
    """List every controller SDL can see."""
    from padmap.devices import list_devices

    found = list_devices()
    if not found:
        print("No controllers detected. Plug in or pair the pad and try again.")
        return EXIT_ERROR
    print(f"{'idx':<4} {'name':<36} {'axes':>4} {'btns':>5} {'hats':>5}")
    for device in found:
        print(
            f"{device.index:<4} {device.name[:36]:<36} {device.axes:>4} {device.buttons:>5} {device.hats:>5}"
        )
    return EXIT_OK


def _cmd_monitor(args: argparse.Namespace) -> int:  # pragma: no cover - needs hardware
    """Print raw indices as inputs change, for working out a layout."""
    from padmap.devices import open_controller

    controller = open_controller(match=args.match, index=args.device)
    print(f"Watching {controller.name}. Press inputs to see their raw index. Ctrl-C to stop.\n")
    previous: tuple[Any, ...] | None = None
    try:
        while True:
            buttons, axes, hats = controller.poll_raw()
            current = (tuple(buttons), tuple(round(a, 2) for a in axes), tuple(hats))
            if previous is not None and current != previous:
                for line in _describe_changes(previous, current):
                    print(line)
            previous = current
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nStopped.")
        return EXIT_OK
    finally:
        controller.close()


def _describe_changes(before: tuple[Any, ...], after: tuple[Any, ...]) -> list[str]:
    """Diff two raw readings into human-readable change lines."""
    lines: list[str] = []
    for index, (was, now) in enumerate(zip(before[0], after[0], strict=True)):
        if was != now:
            lines.append(f"button {index:<2} {'pressed' if now else 'released'}")
    for index, (was, now) in enumerate(zip(before[1], after[1], strict=True)):
        if abs(was - now) >= 0.08:
            lines.append(f"axis   {index:<2} {now:+.2f}")
    for index, (was, now) in enumerate(zip(before[2], after[2], strict=True)):
        if was != now:
            lines.append(f"hat    {index:<2} {now}")
    return lines


def _cmd_run(args: argparse.Namespace) -> int:
    """Load a profile, open the controller, and map until interrupted."""
    profile = load_profile(args.profile)
    if args.poll_hz:
        profile = _with_poll_hz(profile, args.poll_hz)

    backend, describe_backend = _make_backend(dry_run=args.dry_run)
    controller = _open_controller(profile, args)

    engine = Engine(
        profile,
        controller,
        backend,
        on_status=None if args.quiet else lambda message: print(f"padmap: {message}"),
    )
    _install_signal_handlers(engine)

    if not args.quiet:
        _print_banner(profile, controller.name, describe_backend)

    try:
        engine.run()
    except KeyboardInterrupt:  # pragma: no cover - depends on a real signal
        pass
    finally:
        engine.release_all()
        controller.close()
        backend.close()
    if not args.quiet:
        print("padmap: stopped, all keys released")
    return EXIT_OK


def _with_poll_hz(profile: Profile, poll_hz: float) -> Profile:
    """Return the profile with its poll rate overridden from the command line."""
    from dataclasses import replace

    if not 10.0 <= poll_hz <= 1000.0:
        raise ProfileError(f"--poll-hz {poll_hz:g} is out of range [10, 1000]")
    return replace(profile, poll_hz=poll_hz)


def _make_backend(dry_run: bool) -> tuple[Any, str]:
    """Pick the real backend or the recording one used by ``--dry-run``."""
    if dry_run:
        return RecordingBackend(on_event=_DryRunPrinter()), "dry run (nothing is sent)"
    from padmap.backends import PynputBackend

    return PynputBackend(), "live (keys and mouse are really sent)"


def _open_controller(profile: Profile, args: argparse.Namespace) -> Any:  # pragma: no cover
    from padmap.devices import open_controller

    return open_controller(
        match=args.match or profile.device.match,
        index=args.device if args.device is not None else profile.device.index,
        layout=profile.device.layout,
    )


class _DryRunPrinter:
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


def _print_banner(profile: Profile, controller_name: str, backend_description: str) -> None:
    """Say what is about to happen before any synthetic input is sent."""
    print(f"padmap {__version__}")
    print(f"  profile:    {profile.name} ({profile.binding_count} bindings)")
    print(f"  controller: {controller_name}")
    print(f"  output:     {backend_description}")
    print(f"  poll:       {profile.poll_hz:g} Hz")
    pause = _find_pause_button(profile)
    if pause:
        print(f"  pause:      press {pause.upper()} on the pad")
    print("  stop:       Ctrl-C\n")


def _find_pause_button(profile: Profile) -> str | None:
    """Which button, if any, is bound to the pause toggle."""
    for name, binding in profile.buttons.items():
        if binding.action.kind == "special" and binding.action.command == "toggle_pause":
            return name
    return None


def _install_signal_handlers(engine: Engine) -> None:
    """Stop cleanly on SIGINT/SIGTERM so nothing is left held down."""

    def handle(_signum: int, _frame: Any) -> None:  # pragma: no cover - signal path
        engine.stop()

    for name in ("SIGINT", "SIGTERM"):
        received = getattr(signal, name, None)
        if received is not None:
            # signal.signal() only works on the main thread; anywhere else the
            # engine still stops via Ctrl-C reaching run()'s finally block.
            with contextlib.suppress(ValueError):
                signal.signal(received, handle)
