"""Environment verdicts. The probing needs a machine; the judging does not."""

from __future__ import annotations

import pytest

from padmap.doctor import (
    FAIL,
    OK,
    WARN,
    Check,
    Environment,
    detect_session,
    evaluate,
    worst,
)
from padmap.focus import FocusInfo

HEALTHY = Environment(
    python=(3, 12),
    platform="linux",
    session="x11",
    controllers=("Xbox One Controller",),
    backend_error="",
    focus=FocusInfo(app="firefox", title="Inbox"),
    focus_backend="xprop",
    runtime_dir="/run/user/1000/padmap",
    runtime_writable=True,
    tray_available=True,
)


def named(checks: list[Check], name: str) -> Check:
    return next(check for check in checks if check.name == name)


def test_a_healthy_machine_passes_everything() -> None:
    checks = evaluate(HEALTHY)
    assert worst(checks) == OK
    assert all(check.status == OK for check in checks)


def test_every_check_has_a_fix_when_it_is_not_passing() -> None:
    """A verdict with no remedy is just bad news."""
    broken = Environment(session="wayland", backend_error="no display", runtime_writable=False)
    for check in evaluate(broken):
        if check.status != OK:
            assert check.fix, f"{check.name} offers no way forward"


def test_old_python_fails_with_the_version_it_needs() -> None:
    check = named(evaluate(Environment(python=(3, 8))), "Python")
    assert check.status == FAIL
    assert "3.10" in check.fix


def test_wayland_fails_and_says_why() -> None:
    check = named(evaluate(Environment(session="wayland")), "Display session")
    assert check.status == FAIL
    assert "X11" in check.fix


def test_headless_fails() -> None:
    assert named(evaluate(Environment(session="headless")), "Display session").status == FAIL


@pytest.mark.parametrize(
    ("session", "shown"), [("x11", "X11"), ("win32", "Windows"), ("darwin", "macOS")]
)
def test_known_sessions_are_named_in_plain_english(session: str, shown: str) -> None:
    check = named(evaluate(Environment(session=session)), "Display session")
    assert check.detail == shown


def test_a_missing_package_and_a_missing_display_get_different_advice() -> None:
    """Telling someone to install what they already have is the least useful answer."""
    missing = named(
        evaluate(Environment(backend_error="pynput is not installed.")), "Keyboard/mouse output"
    )
    assert "pip install" in missing.fix

    headless = named(
        evaluate(Environment(session="headless", backend_error="could not start on this session")),
        "Keyboard/mouse output",
    )
    assert "pip install" not in headless.fix
    assert "DISPLAY" in headless.fix


def test_macos_output_failure_points_at_accessibility() -> None:
    check = named(
        evaluate(Environment(platform="darwin", session="darwin", backend_error="denied")),
        "Keyboard/mouse output",
    )
    assert "Accessibility" in check.fix


def test_no_controller_fails_with_platform_advice() -> None:
    check = named(evaluate(Environment()), "Controller")
    assert check.status == FAIL
    assert "xpad" in check.fix


def test_several_controllers_warn_about_ambiguity() -> None:
    check = named(evaluate(Environment(controllers=("Pad A", "Pad B"))), "Controller")
    assert check.status == WARN
    assert "device.match" in check.fix


def test_focus_detection_is_only_ever_a_warning() -> None:
    """padmap injects at the OS level, so focus detection is never a prerequisite."""
    for backend in ("none", "wayland", "xprop"):
        check = named(evaluate(Environment(focus_backend=backend)), "Focused window")
        assert check.status == WARN


def test_a_known_focused_window_passes_and_is_shown() -> None:
    check = named(evaluate(HEALTHY), "Focused window")
    assert check.status == OK
    assert "firefox" in check.detail


def test_an_unwritable_runtime_dir_warns_about_detach() -> None:
    check = named(
        evaluate(Environment(runtime_writable=False, runtime_dir="/nope")), "Background sessions"
    )
    assert check.status == WARN
    assert "PADMAP_RUNTIME_DIR" in check.fix


def test_the_tray_is_optional() -> None:
    assert named(evaluate(Environment(tray_available=False)), "Tray icon").status == WARN
    assert named(evaluate(HEALTHY), "Tray icon").status == OK


def test_worst_picks_the_most_serious() -> None:
    assert worst([Check("a", OK, ""), Check("b", WARN, "")]) == WARN
    assert worst([Check("a", WARN, ""), Check("b", FAIL, "")]) == FAIL
    assert worst([]) == OK


def test_marks_are_distinct() -> None:
    marks = {status: Check("x", status, "").mark for status in (OK, WARN, FAIL)}
    assert len(set(marks.values())) == 3


def test_session_detection_reads_the_environment(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert detect_session() == "headless"

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert detect_session() == "wayland"

    monkeypatch.setenv("DISPLAY", ":0")
    assert detect_session() == "x11", "X11 wins when both are set — Xwayland works"
