"""Command line interface.

``padmap run`` is the one people use daily; the rest exist to make authoring a
profile possible without guessing — ``devices`` says what is attached,
``monitor`` shows which raw index each physical button really is, ``validate``
explains a profile, and ``init`` writes one to edit.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from padmap import __version__, runtime
from padmap.actions import ActionError
from padmap.backends import BackendError, RecordingBackend
from padmap.calibration import (
    STICK_AXES,
    Calibration,
    CalibrationError,
    CentreSampler,
    RangeSampler,
)
from padmap.config import (
    Profile,
    ProfileError,
    bundled_profile_names,
    load_profile,
    load_profile_file,
    starter_profile_json,
)
from padmap.devices import DeviceError
from padmap.display import (
    RUNNING,
    DryRunPrinter,
    StatusLine,
    format_duration,
)
from padmap.engine import Engine

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


def detached_argv(args: argparse.Namespace, executable: str = "") -> list[str]:
    """The command line that re-runs this `run` without `--detach`.

    Rebuilt explicitly from the parsed arguments rather than filtered out of
    sys.argv, so it stays correct whichever spelling of a flag was typed.
    """
    argv = [executable or sys.executable, "-m", "padmap", "run", "-p", args.profile]
    if args.device is not None:
        argv += ["--device", str(args.device)]
    if args.match:
        argv += ["--match", args.match]
    if args.poll_hz:
        argv += ["--poll-hz", str(args.poll_hz)]
    if args.dry_run:
        argv.append("--dry-run")
    if args.watch:
        argv.append("--watch")
    return argv


def spawn_detached(argv: list[str], log: Path) -> int:  # pragma: no cover - spawns a process
    """Start padmap in its own session, with its output going to a log file."""
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("ab", buffering=0)
    kwargs: dict[str, Any] = {
        "stdout": handle,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        # DETACHED_PROCESS drops the console; a new process group keeps the
        # parent terminal's Ctrl-C from reaching it.
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    # argv is built by detached_argv() from already-parsed arguments and runs
    # without a shell, so there is no injection surface here.
    return subprocess.Popen(argv, **kwargs).pid  # noqa: S603


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
    run.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="reload the profile whenever the file changes — tune it while it runs",
    )
    run.add_argument(
        "-d",
        "--detach",
        action="store_true",
        help="run in the background, freeing this terminal (stop it with `padmap stop`)",
    )
    run.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="wait this many seconds before sending anything, so you can focus another window",
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

    tray = subcommands.add_parser(
        "tray", help="run with a system-tray icon (needs: pip install 'padmap[tray]')"
    )
    tray.add_argument("-p", "--profile", default="desktop", help="profile name or .json path")
    tray.add_argument("--device", type=int, default=None, help="controller index")
    tray.add_argument("--match", default=None, help="substring of the controller name")
    tray.add_argument("--poll-hz", type=float, default=None, help="override the poll rate")
    tray.add_argument("--dry-run", action="store_true", help="print instead of sending")
    tray.add_argument("-w", "--watch", action="store_true", help="reload the profile on change")
    tray.set_defaults(handler=_cmd_tray)

    status = subcommands.add_parser("status", help="is a padmap session running?")
    status.set_defaults(handler=_cmd_status)

    stop = subcommands.add_parser("stop", help="stop the running session")
    stop.add_argument(
        "--timeout", type=float, default=5.0, help="seconds to wait for it to exit (default: 5)"
    )
    stop.set_defaults(handler=_cmd_stop)

    calibrate = subcommands.add_parser(
        "calibrate", help="measure stick drift and travel, and write it into a profile"
    )
    calibrate.add_argument("--device", type=int, default=None, help="controller index to measure")
    calibrate.add_argument("--match", default=None, help="substring of the controller name")
    calibrate.add_argument(
        "--write", type=Path, default=None, help="merge the result into this profile file"
    )
    calibrate.add_argument(
        "--rest-seconds", type=float, default=2.0, help="how long to watch the resting sticks"
    )
    calibrate.add_argument(
        "--sweep-seconds", type=float, default=8.0, help="how long to watch you sweep the sticks"
    )
    calibrate.set_defaults(handler=_cmd_calibrate)

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
    except (ProfileError, ActionError, DeviceError, BackendError, CalibrationError) as exc:
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


def sample_axes(
    controller: Any,
    seconds: float,
    consume: Any,
    clock: Any = time.monotonic,
    sleep: Any = time.sleep,
    interval: float = 0.01,
) -> int:
    """Poll a controller for ``seconds`` and hand each reading to ``consume``.

    Split out from the interactive command so the sampling loop can be tested
    against a fake controller — the prompts around it are the only part that
    genuinely needs a person and a pad.
    """
    deadline = clock() + seconds
    polls = 0
    while clock() < deadline:
        state = controller.poll()
        consume({name: state.axis(name) for name in STICK_AXES})
        polls += 1
        sleep(interval)
    return polls


def merge_calibration_into_file(path: Path, calibration: Calibration) -> None:
    """Write a measured calibration into an existing profile's device block.

    The file is re-validated after the merge, so a bad write is caught here
    rather than the next time the profile is run.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProfileError(f"cannot read {str(path)!r}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{path}: invalid JSON on line {exc.lineno}: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise ProfileError(f"{path}: expected a JSON object at the top level")

    device = data.setdefault("device", {})
    if not isinstance(device, dict):
        raise ProfileError(f"{path}: 'device' must be an object")
    device["calibration"] = calibration.to_dict()

    Profile.from_dict(data, source=str(path))
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _cmd_tray(args: argparse.Namespace) -> int:  # pragma: no cover - needs a desktop session
    """Run the engine with a tray icon as its control surface."""
    from padmap.tray import TrayApp, TrayUnavailableError

    profile = load_profile(args.profile)
    if args.poll_hz:
        profile = _with_poll_hz(profile, args.poll_hz)

    report = lambda message: print(f"padmap: {message}")  # noqa: E731
    watcher = None
    if args.watch and profile.source and not profile.source.startswith("bundled:"):
        watcher = ProfileWatcher(Path(profile.source), on_error=report)

    backend, _ = _make_backend(dry_run=args.dry_run)
    controller = _open_controller(profile, args)
    runtime.clear_stop()

    engine = Engine(
        profile,
        controller,
        backend,
        on_status=report,
        reload_source=watcher,
        stop_check=runtime.stop_requested,
    )

    def switch(name: str) -> None:
        """Load a profile by name from the tray menu, reporting failures."""
        try:
            engine.request_profile(load_profile(name))
        except ProfileError as exc:
            report(f"could not switch to {name}: {exc}")

    app = TrayApp(engine, profiles=bundled_profile_names(), switch_profile=switch)
    engine.on_frame = app.on_frame

    runtime.write_state(
        runtime.SessionState(
            pid=os.getpid(), profile=profile.name, started_at=time.time(), detached=False
        )
    )
    try:
        app.run()
    except TrayUnavailableError as exc:
        print(f"padmap: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        engine.release_all()
        controller.close()
        backend.close()
        runtime.clear_state()
        runtime.clear_stop()
    return EXIT_OK


def _cmd_status(_args: argparse.Namespace) -> int:
    """Report on the running session, if there is one."""
    state = runtime.read_state()
    if state is None:
        print("padmap is not running.")
        return EXIT_OK
    if not state.alive:
        print(f"padmap is not running (last session, pid {state.pid}, exited).")
        if state.log:
            print(f"  log: {state.log}")
        runtime.clear_state()
        return EXIT_OK

    print(f"{RUNNING} padmap is running")
    print(f"  pid:      {state.pid}")
    print(f"  profile:  {state.profile}")
    print(f"  uptime:   {format_duration(state.uptime)}")
    print(f"  detached: {'yes' if state.detached else 'no'}")
    if state.log:
        print(f"  log:      {state.log}")
    print("\nStop it with:  padmap stop")
    return EXIT_OK


def _cmd_stop(args: argparse.Namespace) -> int:
    """Ask the running session to shut down, and wait for it to."""
    state = runtime.read_state()
    if state is None or not state.alive:
        print("padmap is not running.")
        runtime.clear_state()
        runtime.clear_stop()
        return EXIT_OK

    runtime.request_stop()
    print(f"Asked pid {state.pid} to stop...", end="", flush=True)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if not state.alive:
            print(" stopped.")
            runtime.clear_state()
            runtime.clear_stop()
            return EXIT_OK
        time.sleep(0.1)

    print(" still running.")
    print(
        f"padmap: pid {state.pid} did not exit within {args.timeout:g}s. It releases every held "
        "key before exiting, so give it a moment; if it is wedged, kill it by pid.",
        file=sys.stderr,
    )
    return EXIT_ERROR


def _cmd_calibrate(args: argparse.Namespace) -> int:  # pragma: no cover - needs hardware
    """Measure this pad's drift and travel, and optionally store the result."""
    from padmap.devices import open_controller

    controller = open_controller(match=args.match, index=args.device)
    try:
        print(f"Calibrating {controller.name}.\n")

        print(f"1/2  Let go of both sticks. Measuring for {args.rest_seconds:g}s...")
        centre_sampler = CentreSampler()
        sample_axes(controller, args.rest_seconds, centre_sampler.add)
        centres = centre_sampler.centres()
        worst = max(abs(value) for value in centres.values())
        print(f"     rest position: {_format_axes(centres)}")
        print(f"     worst drift:   {worst:.3f}\n")

        print(
            f"2/2  Now roll both sticks right around their edge, repeatedly, for {args.sweep_seconds:g}s."
        )
        range_sampler = RangeSampler()
        sample_axes(controller, args.sweep_seconds, range_sampler.add)
        calibration = range_sampler.build(centres)
        print(f"     travel: {_format_ranges(calibration)}\n")
    finally:
        controller.close()

    print("Calibration:")
    print(json.dumps({"device": {"calibration": calibration.to_dict()}}, indent=2))

    if args.write:
        merge_calibration_into_file(args.write, calibration)
        print(f"\nWritten into {args.write}. Run it with:  padmap run -p {args.write}")
    else:
        print(
            "\nPaste that 'device' block into your profile, or re-run with --write <profile.json>."
        )
    return EXIT_OK


def _format_axes(values: dict[str, float]) -> str:
    """One-line rendering of a per-axis reading."""
    return "  ".join(f"{name}={value:+.3f}" for name, value in sorted(values.items()))


def _format_ranges(calibration: Calibration) -> str:
    """One-line rendering of each axis's measured travel."""
    return "  ".join(
        f"{name}={axis.low:+.2f}..{axis.high:+.2f}"
        for name, axis in sorted(calibration.axes.items())
    )


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

    report = (lambda message: None) if args.quiet else lambda message: print(f"padmap: {message}")

    # Settle every argument question before opening hardware, so a typo fails
    # instantly instead of after grabbing the pad and the input backend.
    watcher = None
    if args.watch:
        if not profile.source or profile.source.startswith("bundled:"):
            raise ProfileError(
                "--watch needs a profile file to watch. Copy one out first: "
                "`padmap init mine.json`, then `padmap run -w -p mine.json`."
            )
        watcher = ProfileWatcher(Path(profile.source), on_error=report)

    if args.detach:
        log = runtime.log_path()
        pid = spawn_detached(detached_argv(args), log)
        runtime.clear_stop()
        runtime.write_state(
            runtime.SessionState(
                pid=pid,
                profile=profile.name,
                started_at=time.time(),
                detached=True,
                log=str(log),
            )
        )
        print(f"padmap running in the background (pid {pid}).")
        print(f"  log:   {log}")
        print("  stop:  padmap stop")
        return EXIT_OK

    backend, describe_backend = _make_backend(dry_run=args.dry_run)
    controller = _open_controller(profile, args)

    # A stop file left behind by a previous session would kill this one on its
    # first control poll.
    runtime.clear_stop()
    status_line = StatusLine(enabled=False if args.quiet else None)

    engine = Engine(
        profile,
        controller,
        backend,
        on_status=lambda message: (status_line.clear(), report(message)),
        reload_source=watcher,
        stop_check=runtime.stop_requested,
        on_frame=status_line,
    )
    _install_signal_handlers(engine)

    if not args.quiet:
        _print_banner(profile, controller.name, describe_backend, watching=bool(watcher))
    if args.delay > 0:
        _countdown(args.delay, quiet=args.quiet)

    runtime.write_state(
        runtime.SessionState(
            pid=os.getpid(), profile=profile.name, started_at=time.time(), detached=False
        )
    )
    try:
        engine.run()
    except KeyboardInterrupt:  # pragma: no cover - depends on a real signal
        pass
    finally:
        engine.release_all()
        controller.close()
        backend.close()
        status_line.clear()
        runtime.clear_state()
        runtime.clear_stop()
    if not args.quiet:
        print("padmap: stopped, all keys released")
    return EXIT_OK


def _countdown(seconds: float, quiet: bool = False, sleep: Any = time.sleep) -> None:
    """Pause before the first synthetic event, so you can focus another window.

    Without this, the window with focus when padmap starts is the terminal you
    started it from — so the first thing a mouse-mode profile does is fling the
    pointer around your own shell.
    """
    remaining = int(seconds)
    while remaining > 0 and not quiet:
        print(
            f"\rpadmap: starting in {remaining}... (focus the window you want to control)  ",
            end="",
            flush=True,
        )
        sleep(1.0)
        remaining -= 1
    if not quiet:
        print("\r" + " " * 70 + "\r", end="", flush=True)
    leftover = seconds - int(seconds)
    if leftover > 0:
        sleep(leftover)


def _with_poll_hz(profile: Profile, poll_hz: float) -> Profile:
    """Return the profile with its poll rate overridden from the command line."""
    from dataclasses import replace

    if not 10.0 <= poll_hz <= 1000.0:
        raise ProfileError(f"--poll-hz {poll_hz:g} is out of range [10, 1000]")
    return replace(profile, poll_hz=poll_hz)


def _make_backend(dry_run: bool) -> tuple[Any, str]:
    """Pick the real backend or the recording one used by ``--dry-run``."""
    if dry_run:
        return RecordingBackend(on_event=DryRunPrinter()), "dry run (nothing is sent)"
    from padmap.backends import PynputBackend

    return PynputBackend(), "live (keys and mouse are really sent)"


def _open_controller(profile: Profile, args: argparse.Namespace) -> Any:  # pragma: no cover
    from padmap.devices import open_controller

    return open_controller(
        match=args.match or profile.device.match,
        index=args.device if args.device is not None else profile.device.index,
        layout=profile.device.layout,
    )


def _print_banner(
    profile: Profile, controller_name: str, backend_description: str, watching: bool = False
) -> None:
    """Say what is about to happen before any synthetic input is sent."""
    print(f"padmap {__version__}")
    print(f"  profile:    {profile.name} ({profile.binding_count} bindings)")
    print(f"  controller: {controller_name}")
    print(f"  output:     {backend_description}")
    print(f"  poll:       {profile.poll_hz:g} Hz")
    for label, command in (("pause", "toggle_pause"), ("precision", "precision")):
        button = _find_special_button(profile, command)
        if button:
            print(f"  {label + ':':<11} hold {button.upper()} on the pad")
    for name, button in _find_layer_buttons(profile).items():
        layer = profile.layers[name]
        detail = f" — {layer.description}" if layer.description else ""
        print(f"  layer:      hold {button.upper()} for '{name}'{detail}")
    if watching:
        print("  watching:   edits to the profile file apply live")
    print("  stop:       Ctrl-C\n")


def _find_special_button(profile: Profile, command: str) -> str | None:
    """Which button, if any, is bound to the given engine special."""
    for name, binding in profile.buttons.items():
        if binding.action.kind == "special" and binding.action.command == command:
            return name
    return None


def _find_layer_buttons(profile: Profile) -> dict[str, str]:
    """Map each layer name onto the button that opens it."""
    found: dict[str, str] = {}
    for name, binding in profile.buttons.items():
        if binding.action.command == "layer" and binding.action.argument in profile.layers:
            found.setdefault(binding.action.argument, name)
    return found


class ProfileWatcher:
    """Hands the engine a reloaded profile when the file on disk changes.

    A bad edit must not stop the session: the error is reported and the profile
    already running stays in force. Losing control of your keyboard because you
    fat-fingered a comma would be a poor way to learn about JSON.
    """

    def __init__(self, path: Path, on_error: Any = None) -> None:
        self.path = path
        self._on_error = on_error
        self._stamp = self._read_stamp()

    def _read_stamp(self) -> tuple[int, int] | None:
        try:
            info = self.path.stat()
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size)

    def force(self) -> None:
        """Make the next poll reload even if the file has not changed.

        Forgetting the stamp is enough: the next read sees a stamp that differs
        from "no stamp at all" and reloads.
        """
        self._stamp = None

    def __call__(self) -> Profile | None:
        """Return a reloaded profile, or None if nothing usable changed."""
        stamp = self._read_stamp()
        if stamp is None or stamp == self._stamp:
            return None
        self._stamp = stamp
        try:
            return load_profile_file(self.path)
        except ProfileError as exc:
            if self._on_error is not None:
                self._on_error(f"profile not reloaded — {exc}")
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
