"""Focused-window detection. The parsing is testable; the platform calls are not."""

from __future__ import annotations

import pytest

from padmap.focus import (
    FocusInfo,
    focus_backend_name,
    foreground_window,
    parse_active_window_id,
    parse_wm_class,
    parse_wm_name,
)


def test_wm_class_prefers_the_human_readable_half() -> None:
    """X11 reports instance and class; the second is the one people recognise."""
    assert parse_wm_class('WM_CLASS(STRING) = "navigator", "Firefox"') == "Firefox"


def test_wm_class_handles_a_single_name() -> None:
    assert parse_wm_class('WM_CLASS(STRING) = "xterm"') == "xterm"


def test_wm_class_of_nothing_is_empty() -> None:
    assert parse_wm_class("WM_CLASS:  not found.") == ""
    assert parse_wm_class("") == ""


def test_wm_name_extracts_the_title() -> None:
    assert parse_wm_name('_NET_WM_NAME(UTF8_STRING) = "Inbox — Mail"') == "Inbox — Mail"


def test_wm_name_of_nothing_is_empty() -> None:
    assert parse_wm_name("_NET_WM_NAME:  not found.") == ""


def test_active_window_id_is_extracted() -> None:
    assert (
        parse_active_window_id("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3e00007") == "0x3e00007"
    )


def test_no_active_window_id_is_empty() -> None:
    assert parse_active_window_id("_NET_ACTIVE_WINDOW:  not found.") == ""


def test_focus_info_renders_readably() -> None:
    assert str(FocusInfo(app="firefox.exe", title="Inbox")) == "firefox.exe — Inbox"
    assert str(FocusInfo(app="Terminal")) == "Terminal"
    assert str(FocusInfo(title="Untitled")) == "Untitled"
    assert str(FocusInfo()) == "unknown"


def test_focus_info_knows_when_it_knows_nothing() -> None:
    assert FocusInfo(app="x").known
    assert not FocusInfo().known


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("win32", {}, "win32"),
        ("darwin", {}, "applescript"),
        ("linux", {"DISPLAY": ":0"}, "xprop"),
        ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
        ("linux", {}, "none"),
    ],
)
def test_backend_is_chosen_per_session(
    platform: str, env: dict, expected: str, monkeypatch
) -> None:
    monkeypatch.setattr("sys.platform", platform)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert focus_backend_name() == expected


def test_an_unsupported_session_answers_none_rather_than_raising(monkeypatch) -> None:
    """Focus detection is a diagnostic; it must never be the thing that crashes."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert foreground_window() is None


def test_a_raising_backend_is_swallowed(monkeypatch) -> None:
    monkeypatch.setattr("padmap.focus.focus_backend_name", lambda: "xprop")
    monkeypatch.setattr(
        "padmap.focus._xprop_window", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert foreground_window() is None
