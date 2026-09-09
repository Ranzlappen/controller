"""The command line: argument handling, output, and exit codes.

Only the commands that need no hardware are exercised here — `devices`,
`monitor` and a live `run` need a real controller and a real desktop.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from padmap.backends import Event
from padmap.cli import (
    EXIT_ERROR,
    EXIT_OK,
    _DryRunPrinter,
    _find_pause_button,
    _with_poll_hz,
    build_parser,
    main,
)
from padmap.config import Profile, ProfileError, load_profile


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


def test_find_pause_button() -> None:
    assert _find_pause_button(load_profile("desktop")) == "back"
    assert _find_pause_button(Profile.from_dict({"buttons": {"a": "key:w"}})) is None


def test_dry_run_printer_prints_discrete_events(capsys) -> None:
    printer = _DryRunPrinter(clock=lambda: 0.0)
    printer(Event("key_down", "w"))
    assert capsys.readouterr().out.strip() == "key_down w"


def test_dry_run_printer_collapses_pointer_motion(capsys) -> None:
    """Per-tick motion would flood the terminal, so it is summarised on an interval."""
    now = [0.0]
    printer = _DryRunPrinter(motion_interval=1.0, clock=lambda: now[0])
    printer(Event("mouse_move", "5,0"))  # prints immediately
    printer(Event("mouse_move", "5,0"))  # inside the interval — accumulates
    printer(Event("mouse_move", "5,0"))
    first = capsys.readouterr().out.strip().splitlines()
    assert len(first) == 1

    now[0] = 2.0
    printer(Event("mouse_move", "1,0"))
    assert "+11,+0" in capsys.readouterr().out
