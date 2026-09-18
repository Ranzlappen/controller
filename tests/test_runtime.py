"""Background-session bookkeeping: state files and the stop protocol."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from padmap import runtime


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path: Path, monkeypatch) -> Path:
    """Never touch the real runtime directory from a test."""
    monkeypatch.setenv(runtime.RUNTIME_DIR_ENV, str(tmp_path / "rt"))
    return tmp_path / "rt"


def a_session(**overrides) -> runtime.SessionState:
    defaults = {
        "pid": os.getpid(),
        "profile": "desktop",
        "started_at": time.time(),
        "detached": False,
        "log": "",
    }
    return runtime.SessionState(**{**defaults, **overrides})


def test_runtime_dir_honours_the_override(isolated_runtime: Path) -> None:
    assert runtime.runtime_dir() == isolated_runtime


def test_state_round_trips(isolated_runtime: Path) -> None:
    runtime.write_state(a_session(profile="fps", detached=True))
    state = runtime.read_state()
    assert state is not None
    assert (state.profile, state.detached, state.pid) == ("fps", True, os.getpid())


def test_writing_state_creates_the_directory(isolated_runtime: Path) -> None:
    assert not isolated_runtime.exists()
    runtime.write_state(a_session())
    assert runtime.state_path().exists()


def test_no_state_reads_as_none() -> None:
    assert runtime.read_state() is None


@pytest.mark.parametrize("content", ["not json at all", "[1, 2, 3]", '{"profile": "x"}'])
def test_unusable_state_reads_as_none_rather_than_raising(content: str) -> None:
    """The state file is a cache. A corrupt one must not stop padmap starting."""
    runtime.state_path().parent.mkdir(parents=True, exist_ok=True)
    runtime.state_path().write_text(content, encoding="utf-8")
    assert runtime.read_state() is None


def test_clear_state_is_safe_when_there_is_none() -> None:
    runtime.clear_state()
    runtime.clear_state()
    assert runtime.read_state() is None


def test_uptime_counts_from_the_recorded_start() -> None:
    assert a_session(started_at=time.time() - 90).uptime == pytest.approx(90, abs=2)


def test_this_process_is_alive_and_a_made_up_one_is_not() -> None:
    assert runtime.process_alive(os.getpid())
    assert not runtime.process_alive(2**30)
    assert not runtime.process_alive(0)
    assert not runtime.process_alive(-1)


def test_a_session_for_a_dead_process_is_not_alive() -> None:
    assert not a_session(pid=2**30).alive


# --- The stop protocol -------------------------------------------------------


def test_stop_is_requested_and_cleared() -> None:
    assert not runtime.stop_requested()
    runtime.request_stop()
    assert runtime.stop_requested()
    runtime.clear_stop()
    assert not runtime.stop_requested()


def test_requesting_stop_creates_the_directory(isolated_runtime: Path) -> None:
    assert not isolated_runtime.exists()
    runtime.request_stop()
    assert runtime.stop_requested()


def test_clear_stop_is_safe_when_nothing_is_pending() -> None:
    runtime.clear_stop()
    assert not runtime.stop_requested()


def test_stale_session_spots_a_session_whose_process_died() -> None:
    runtime.write_state(a_session(pid=2**30))
    stale = runtime.stale_session()
    assert stale is not None and stale.pid == 2**30


def test_stale_session_is_none_while_the_process_lives() -> None:
    runtime.write_state(a_session())
    assert runtime.stale_session() is None


def test_state_file_is_readable_json() -> None:
    """Someone debugging a wedged session should be able to just cat it."""
    runtime.write_state(a_session(profile="fps"))
    assert json.loads(runtime.state_path().read_text(encoding="utf-8"))["profile"] == "fps"
