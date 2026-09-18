"""The tray's menu model and actions.

The pystray binding itself needs a desktop session and is not covered here;
everything that decides *what* the menu says and *what* a click does is plain
data and is covered exactly.
"""

from __future__ import annotations

from conftest import FakeController, make_state
from padmap.backends import RecordingBackend
from padmap.config import Profile, load_profile
from padmap.engine import Engine, EngineStatus
from padmap.tray import (
    PAUSE,
    PROFILE_PREFIX,
    QUIT,
    RELOAD,
    RESUME,
    apply_action,
    menu_model,
)


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


def labels(entries) -> list[str]:
    return [entry.label for entry in entries if not entry.is_separator]


# --- Menu model --------------------------------------------------------------


def test_the_first_row_summarises_state_without_being_clickable() -> None:
    entries = menu_model(a_status())
    assert entries[0].label == "padmap — Desktop"
    assert entries[0].enabled is False


def test_the_headline_reports_pausing_centring_and_layers() -> None:
    assert "paused" in menu_model(a_status(paused=True))[0].label
    assert "centring" in menu_model(a_status(settling=True))[0].label
    assert "layer nav" in menu_model(a_status(layers=("nav",)))[0].label


def test_pause_becomes_resume_when_paused() -> None:
    assert PAUSE in [e.action for e in menu_model(a_status())]
    assert RESUME in [e.action for e in menu_model(a_status(paused=True))]


def test_reload_is_hidden_when_there_is_nothing_to_reload_from() -> None:
    assert "Reload profile" in labels(menu_model(a_status(), can_reload=True))
    assert "Reload profile" not in labels(menu_model(a_status(), can_reload=False))


def test_profiles_become_switch_entries_with_the_current_one_ticked() -> None:
    entries = {e.action: e for e in menu_model(a_status(profile="Desktop"), ["desktop", "fps"])}
    assert entries[f"{PROFILE_PREFIX}desktop"].checked is True
    assert entries[f"{PROFILE_PREFIX}fps"].checked is False


def test_quit_is_always_last() -> None:
    assert menu_model(a_status(), ["desktop"])[-1].action == QUIT


def test_event_count_is_shown_with_thousands_separators() -> None:
    assert "12,345 events sent" in labels(menu_model(a_status(events=12345)))


# --- Actions -----------------------------------------------------------------


def engine_with(profile: str = "desktop", **kwargs) -> tuple[Engine, RecordingBackend]:
    backend = RecordingBackend()
    return Engine(load_profile(profile), FakeController(), backend, **kwargs), backend


def test_pause_and_resume_are_queued_not_applied_on_the_calling_thread() -> None:
    """A tray click must not mutate engine state mid-tick."""
    engine, _ = engine_with()
    apply_action(engine, PAUSE)
    assert engine.paused is False, "not applied until the loop picks it up"
    engine.tick(0.0, make_state())
    assert engine.paused is True

    apply_action(engine, RESUME)
    engine.tick(0.1, make_state())
    assert engine.paused is False


def test_quit_stops_the_engine() -> None:
    engine, _ = engine_with()
    engine.running = True
    apply_action(engine, QUIT)
    assert engine.running is False


def test_switching_profile_is_queued_and_then_adopted() -> None:
    engine, _ = engine_with("desktop")
    switched: list[str] = []

    def switch(name: str) -> None:
        switched.append(name)
        engine.request_profile(load_profile(name))

    apply_action(engine, f"{PROFILE_PREFIX}fps", switch)
    assert switched == ["fps"]
    engine.tick(0.0, make_state())
    assert engine.profile.name == "FPS"


def test_switching_profile_without_a_handler_does_nothing() -> None:
    engine, _ = engine_with("desktop")
    apply_action(engine, f"{PROFILE_PREFIX}fps")
    engine.tick(0.0, make_state())
    assert engine.profile.name == "Desktop"


def test_an_unknown_action_is_ignored_rather_than_raising() -> None:
    """A stray tray click is not worth taking down a session holding keys."""
    engine, _ = engine_with()
    apply_action(engine, "explode")
    apply_action(engine, "")
    assert engine.running is False


def test_reload_without_a_source_reports_that_it_cannot() -> None:
    engine, _ = engine_with()
    assert engine.can_reload is False
    assert engine.request_reload() is False
    apply_action(engine, RELOAD)


def test_reload_forces_a_source_that_offers_force() -> None:
    forced: list[bool] = []

    class Source:
        def force(self) -> None:
            forced.append(True)

        def __call__(self) -> Profile | None:
            return None

    engine, _ = engine_with(reload_source=Source())
    assert engine.can_reload is True
    assert engine.request_reload() is True
    assert forced == [True]


def test_adopting_a_profile_releases_what_was_held() -> None:
    engine, backend = engine_with("fps")
    engine.tick(0.0, make_state())
    engine.tick(0.01, make_state(a=True))
    assert backend.log() == ["key_down space"]
    engine.adopt_profile(load_profile("desktop"))
    assert backend.log()[-1] == "key_up space"
