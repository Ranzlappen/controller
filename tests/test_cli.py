"""The command line: argument handling, output, and exit codes.

Only the commands that need no hardware are exercised here — `devices`,
`monitor` and a live `run` need a real controller and a real desktop.
"""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pytest

from padmap import runtime
from padmap.backends import Event
from padmap.calibration import AxisCalibration, Calibration
from padmap.cli import (
    EXIT_ERROR,
    EXIT_OK,
    ProfileWatcher,
    _find_layer_buttons,
    _find_special_button,
    _with_poll_hz,
    build_parser,
    detached_argv,
    main,
    merge_calibration_into_file,
    sample_axes,
)
from padmap.config import Profile, ProfileError, load_profile
from padmap.display import DryRunPrinter, StatusLine, format_duration, render_status
from padmap.engine import EngineStatus


def test_no_command_prints_help(capsys) -> None:
    assert main([]) == EXIT_OK
    assert "usage: padmap" in capsys.readouterr().out


def test_version_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == EXIT_OK
    assert "padmap" in capsys.readouterr().out


def test_profiles_lists_the_bundled_set(capsys) -> None:
    assert main(["profiles"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "desktop" in out
    assert "fps" in out
    assert "padmap init" in out


def test_validate_describes_a_bundled_profile(capsys) -> None:
    assert main(["validate", "fps"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("OK —")
    assert "buttons.a: key:space" in out


def test_validate_reports_a_bad_profile_on_stderr(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"buttons": {"a": "key:nonsense"}}), encoding="utf-8")
    assert main(["validate", str(bad)]) == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "padmap: buttons.a" in captured.err


def test_validate_reports_an_unknown_profile_name(capsys) -> None:
    assert main(["validate", "nope"]) == EXIT_ERROR
    assert "Bundled profiles" in capsys.readouterr().err


def test_init_writes_a_profile_that_validates(tmp_path: Path, capsys) -> None:
    target = tmp_path / "nested" / "mine.json"
    assert main(["init", str(target)]) == EXIT_OK
    assert target.exists()
    assert "Wrote" in capsys.readouterr().out
    # The written file must round-trip through the loader.
    assert main(["validate", str(target)]) == EXIT_OK


def test_init_refuses_to_clobber_without_force(tmp_path: Path, capsys) -> None:
    target = tmp_path / "mine.json"
    target.write_text("keep me", encoding="utf-8")
    assert main(["init", str(target)]) == EXIT_ERROR
    assert "already exists" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "keep me"


def test_init_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "mine.json"
    target.write_text("old", encoding="utf-8")
    assert main(["init", str(target), "--force"]) == EXIT_OK
    assert "padmap" in target.read_text(encoding="utf-8")


# --- Parser ------------------------------------------------------------------


def test_run_defaults_to_the_desktop_profile() -> None:
    args = build_parser().parse_args(["run"])
    assert args.profile == "desktop"
    assert args.dry_run is False


def test_run_accepts_the_documented_flags() -> None:
    args = build_parser().parse_args(
        [
            "run",
            "-p",
            "fps",
            "--device",
            "2",
            "--match",
            "xbox",
            "--poll-hz",
            "60",
            "--dry-run",
            "-q",
        ]
    )
    assert (args.profile, args.device, args.match, args.poll_hz) == ("fps", 2, "xbox", 60.0)
    assert args.dry_run and args.quiet


# --- Helpers -----------------------------------------------------------------


def test_poll_hz_override_replaces_the_profile_value() -> None:
    profile = _with_poll_hz(load_profile("desktop"), 60)
    assert profile.poll_hz == 60


def test_poll_hz_override_is_range_checked() -> None:
    with pytest.raises(ProfileError, match="out of range"):
        _with_poll_hz(load_profile("desktop"), 5)


def test_find_special_button() -> None:
    assert _find_special_button(load_profile("desktop"), "toggle_pause") == "back"
    assert _find_special_button(load_profile("desktop"), "precision") == "lb"
    assert _find_special_button(Profile.from_dict({"buttons": {"a": "key:w"}}), "quit") is None


def test_find_layer_buttons() -> None:
    assert _find_layer_buttons(load_profile("desktop")) == {"nav": "rb"}
    assert _find_layer_buttons(Profile.from_dict({"buttons": {"a": "key:w"}})) == {}


def test_dry_run_printer_prints_discrete_events(capsys) -> None:
    printer = DryRunPrinter(clock=lambda: 0.0)
    printer(Event("key_down", "w"))
    assert capsys.readouterr().out.strip() == "key_down w"


def test_dry_run_printer_collapses_pointer_motion(capsys) -> None:
    """Per-tick motion would flood the terminal, so it is summarised on an interval."""
    now = [0.0]
    printer = DryRunPrinter(motion_interval=1.0, clock=lambda: now[0])
    printer(Event("mouse_move", "5,0"))  # prints immediately
    printer(Event("mouse_move", "5,0"))  # inside the interval — accumulates
    printer(Event("mouse_move", "5,0"))
    first = capsys.readouterr().out.strip().splitlines()
    assert len(first) == 1

    now[0] = 2.0
    printer(Event("mouse_move", "1,0"))
    assert "+11,+0" in capsys.readouterr().out


# --- Hot reload --------------------------------------------------------------


def _write(path: Path, name: str) -> None:
    path.write_text(json.dumps({"name": name, "buttons": {"a": "key:w"}}), encoding="utf-8")


def test_watcher_is_quiet_until_the_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    _write(path, "First")
    watcher = ProfileWatcher(path)
    assert watcher() is None


def test_watcher_returns_the_edited_profile(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    _write(path, "First")
    watcher = ProfileWatcher(path)
    _write(path, "Second")
    reloaded = watcher()
    assert reloaded is not None
    assert reloaded.name == "Second"
    assert watcher() is None, "the same change is only reported once"


def test_a_broken_edit_keeps_the_running_profile(tmp_path: Path) -> None:
    """Losing control of the keyboard over a stray comma would be a poor lesson."""
    path = tmp_path / "p.json"
    _write(path, "First")
    errors: list[str] = []
    watcher = ProfileWatcher(path, on_error=errors.append)
    path.write_text('{"buttons": {"a": "key:nonsense"}}', encoding="utf-8")
    assert watcher() is None
    assert errors and "not reloaded" in errors[0]


def test_watcher_tolerates_a_deleted_file(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    _write(path, "First")
    watcher = ProfileWatcher(path)
    path.unlink()
    assert watcher() is None


def test_watch_without_a_file_to_watch_is_refused(capsys) -> None:
    """`--watch` on a bundled profile has nothing to watch; say so usefully."""
    assert main(["run", "-p", "desktop", "--watch", "--dry-run"]) == EXIT_ERROR
    assert "padmap init" in capsys.readouterr().err


# --- Calibration plumbing ----------------------------------------------------


def test_sample_axes_polls_for_the_requested_window() -> None:
    from conftest import FakeController, make_state

    controller = FakeController(make_state(left_x=0.2))
    now = [0.0]
    collected: list[dict] = []
    polls = sample_axes(
        controller,
        0.1,
        collected.append,
        clock=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + 0.01),
    )
    assert polls == pytest.approx(10, abs=1), "roughly one poll per interval"
    assert collected[0]["left_x"] == pytest.approx(0.2)


def test_merge_calibration_writes_a_profile_that_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    _write(path, "First")
    calibration = Calibration({"left_x": AxisCalibration(centre=0.12, low=-0.9, high=0.88)})
    merge_calibration_into_file(path, calibration)

    reloaded = load_profile(str(path))
    assert reloaded.device.calibration.axes["left_x"].centre == pytest.approx(0.12)
    assert reloaded.buttons["a"].action.keys == ("w",), "existing bindings survive the merge"


def test_merge_calibration_preserves_other_device_options(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"device": {"match": "xbox"}}), encoding="utf-8")
    merge_calibration_into_file(path, Calibration({"left_x": AxisCalibration(centre=0.1)}))
    assert load_profile(str(path)).device.match == "xbox"


def test_merge_calibration_rejects_a_file_that_is_not_a_profile(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ProfileError, match="JSON object"):
        merge_calibration_into_file(path, Calibration())


def test_merge_calibration_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="cannot read"):
        merge_calibration_into_file(tmp_path / "absent.json", Calibration())


# --- Status line -------------------------------------------------------------


def a_status(**overrides) -> EngineStatus:
    defaults = {
        "profile": "Desktop",
        "paused": False,
        "layers": (),
        "precision": False,
        "events": 0,
        "drift": {},
        "settling": False,
    }
    return EngineStatus(**{**defaults, **overrides})


def test_status_line_reports_the_running_profile() -> None:
    assert "Desktop" in render_status(a_status())


def test_status_line_calls_out_pause_loudly() -> None:
    assert "PAUSED" in render_status(a_status(paused=True))


def test_status_line_shows_centring_and_nothing_else() -> None:
    """During the startup measurement nothing is being sent, so say only that."""
    line = render_status(a_status(settling=True, events=5))
    assert "centring" in line
    assert "events" not in line


def test_status_line_surfaces_layer_precision_and_drift() -> None:
    line = render_status(
        a_status(layers=("nav",), precision=True, drift={"left_x": 0.18}, events=1234)
    )
    assert "layer nav" in line
    assert "precision" in line
    assert "drift 0.18 corrected" in line
    assert "1,234 events" in line


def test_status_line_hides_drift_too_small_to_care_about() -> None:
    assert "drift" not in render_status(a_status(drift={"left_x": 0.001}))


def test_status_line_truncates_to_the_terminal_width() -> None:
    line = render_status(a_status(layers=("nav",), precision=True, events=999999), width=20)
    assert len(line) <= 20
    assert line.endswith("…")


def test_status_line_writes_in_place_and_erases_leftovers() -> None:
    stream = io.StringIO()
    line = StatusLine(stream=stream, enabled=True)
    line(a_status(events=1234567))
    long = stream.getvalue()
    line(a_status(events=0))
    written = stream.getvalue()[len(long) :]
    assert written.startswith("\r")
    assert written.rstrip().endswith("events"), "shorter line must blank the old tail"


def test_status_line_stays_silent_when_there_is_no_terminal() -> None:
    """A detached session logs to a file; thousands of near-identical lines is noise."""
    stream = io.StringIO()
    StatusLine(stream=stream, enabled=False)(a_status())
    assert stream.getvalue() == ""


def test_status_line_clear_resets_the_row() -> None:
    stream = io.StringIO()
    line = StatusLine(stream=stream, enabled=True)
    line(a_status())
    line.clear()
    assert stream.getvalue().endswith("\r")


def test_status_line_autodetects_a_non_tty() -> None:
    assert StatusLine(stream=io.StringIO()).enabled is False


# --- Detached argv -----------------------------------------------------------


def test_detached_argv_rebuilds_the_run_command_without_detach() -> None:
    args = build_parser().parse_args(["run", "-p", "fps", "--detach", "--watch"])
    argv = detached_argv(args, executable="/usr/bin/python3")
    assert argv[:5] == ["/usr/bin/python3", "-m", "padmap", "run", "-p"]
    assert "--watch" in argv
    assert "--detach" not in argv and "-d" not in argv


def test_detached_argv_carries_the_device_selection() -> None:
    args = build_parser().parse_args(
        ["run", "--device", "2", "--match", "xbox", "--poll-hz", "90", "--dry-run"]
    )
    argv = detached_argv(args, executable="py")
    for expected in ("--device", "2", "--match", "xbox", "--poll-hz", "90.0", "--dry-run"):
        assert expected in argv


def test_detached_argv_omits_flags_that_were_not_given() -> None:
    argv = detached_argv(build_parser().parse_args(["run"]), executable="py")
    assert "--device" not in argv and "--dry-run" not in argv and "--watch" not in argv


# --- status / stop -----------------------------------------------------------


@pytest.fixture
def isolated_runtime(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv(runtime.RUNTIME_DIR_ENV, str(tmp_path / "rt"))
    return tmp_path / "rt"


def test_status_says_nothing_is_running(isolated_runtime: Path, capsys) -> None:
    assert main(["status"]) == EXIT_OK
    assert "not running" in capsys.readouterr().out


def test_status_describes_a_live_session(isolated_runtime: Path, capsys) -> None:
    runtime.write_state(
        runtime.SessionState(
            pid=os.getpid(), profile="Desktop", started_at=time.time() - 75, detached=True
        )
    )
    assert main(["status"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "is running" in out
    assert "Desktop" in out
    assert "1m 15s" in out
    assert "detached: yes" in out


def test_status_clears_a_session_whose_process_died(isolated_runtime: Path, capsys) -> None:
    runtime.write_state(runtime.SessionState(pid=2**30, profile="Desktop", started_at=time.time()))
    assert main(["status"]) == EXIT_OK
    assert "exited" in capsys.readouterr().out
    assert runtime.read_state() is None, "the stale record should be tidied away"


def test_stop_with_nothing_running_is_not_an_error(isolated_runtime: Path, capsys) -> None:
    assert main(["stop"]) == EXIT_OK
    assert "not running" in capsys.readouterr().out


def test_stop_on_a_dead_session_tidies_up(isolated_runtime: Path) -> None:
    runtime.write_state(runtime.SessionState(pid=2**30, profile="x", started_at=time.time()))
    assert main(["stop"]) == EXIT_OK
    assert runtime.read_state() is None
    assert not runtime.stop_requested()


def test_stop_reports_a_session_that_will_not_exit(isolated_runtime: Path, capsys) -> None:
    """This process never honours the stop file, standing in for a wedged session."""
    runtime.write_state(runtime.SessionState(pid=os.getpid(), profile="x", started_at=time.time()))
    assert main(["stop", "--timeout", "0.2"]) == EXIT_ERROR
    assert "did not exit" in capsys.readouterr().err
    assert runtime.stop_requested(), "the request stands so the session can still notice it"


@pytest.mark.parametrize(
    ("seconds", "expected"), [(5, "5s"), (75, "1m 15s"), (3700, "1h 01m"), (0, "0s")]
)
def test_duration_formatting(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected
