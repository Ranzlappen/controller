"""Macros: parsing, and playing out over time without blocking the loop."""

from __future__ import annotations

import pytest

from padmap.actions import Action
from padmap.macros import (
    DEFAULT_TAP_SECONDS,
    DOWN,
    FIRE,
    MAX_STEPS,
    UP,
    WAIT,
    MacroError,
    MacroRunner,
    parse_macro,
    parse_macros,
)


class Sink:
    """Records what a macro asked for, in order."""

    def __init__(self) -> None:
        self.log: list[str] = []

    def press(self, action: Action) -> None:
        self.log.append(f"down {action}")

    def release(self, action: Action) -> None:
        self.log.append(f"up {action}")

    def fire(self, action: Action) -> None:
        self.log.append(f"fire {action}")


def play(runner: MacroRunner, sink: Sink, times: list[float]) -> None:
    for moment in times:
        runner.advance(moment, sink)


# --- Parsing -----------------------------------------------------------------


def test_a_bare_action_becomes_press_wait_release() -> None:
    """A zero-length keypress is missed by a surprising number of applications."""
    macro = parse_macro("m", ["key:a"])
    assert [step.kind for step in macro.steps] == [DOWN, WAIT, UP]
    assert macro.steps[1].seconds == DEFAULT_TAP_SECONDS


def test_one_shot_actions_are_fired_not_held() -> None:
    for spec in ("text:hi", "scroll:up", "move:10,0"):
        macro = parse_macro("m", [spec])
        assert [step.kind for step in macro.steps] == [FIRE], spec


def test_explicit_down_and_up_pass_through() -> None:
    macro = parse_macro("m", [{"down": "key:shift"}, "key:a", {"up": "key:shift"}])
    assert [step.kind for step in macro.steps] == [DOWN, DOWN, WAIT, UP, UP]


def test_waits_are_kept_and_totalled() -> None:
    macro = parse_macro("m", [{"wait": 0.25}, {"wait": 0.5}])
    assert macro.duration == pytest.approx(0.75)


def test_the_object_form_carries_options() -> None:
    macro = parse_macro("m", {"steps": ["key:a"], "interruptible": True, "tap": 0.1})
    assert macro.interruptible
    assert macro.steps[1].seconds == 0.1


def test_describe_summarises() -> None:
    assert "steps" in parse_macro("m", ["key:a"]).describe()
    assert (
        "interruptible" in parse_macro("m", {"steps": ["key:a"], "interruptible": True}).describe()
    )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "no steps"),
        ("key:a", "list of steps"),
        ([{"wait": 0}], "outside"),
        ([{"wait": 999}], "outside"),
        ([{"wait": "soon"}], "number of seconds"),
        ([{"down": "key:a", "up": "key:b"}], "exactly one"),
        ([{"sleep": 1}], "unknown key"),
        ([{"down": "text:hi"}], "cannot be held"),
        ([42], "string or an object"),
        (["macro:other"], "cannot call another macro"),
        (["special:quit"], "cannot contain a special"),
        (["key:nonsense"], "unknown key"),
        ({"interruptible": True}, "needs a 'steps' list"),
        ({"steps": ["key:a"], "nope": 1}, "unknown key"),
        ({"steps": ["key:a"], "interruptible": "yes"}, "true or false"),
    ],
)
def test_bad_macros_are_rejected(raw: object, message: str) -> None:
    with pytest.raises(MacroError, match=message):
        parse_macro("m", raw)


def test_a_runaway_macro_is_rejected() -> None:
    with pytest.raises(MacroError, match="step limit"):
        parse_macro("m", ["key:a"] * (MAX_STEPS // 2))


def test_parse_macros_lowercases_names() -> None:
    assert set(parse_macros({"Copy-Paste": ["key:a"]})) == {"copy-paste"}


# --- Running -----------------------------------------------------------------


def test_a_macro_plays_out_across_ticks_rather_than_all_at_once() -> None:
    runner, sink = MacroRunner(), Sink()
    runner.start(parse_macro("m", ["key:a", {"wait": 0.1}, "key:b"]), 0.0)

    runner.advance(0.0, sink)
    assert sink.log == ["down key:a"], "the loop must not block on the wait"

    play(runner, sink, [0.03, 0.05, 0.14, 0.17])
    assert sink.log == ["down key:a", "up key:a", "down key:b", "up key:b"]
    assert runner.active == (), "and it retires when finished"


def test_waits_are_honoured_not_skipped() -> None:
    runner, sink = MacroRunner(), Sink()
    runner.start(parse_macro("m", [{"down": "key:a"}, {"wait": 1.0}, {"up": "key:a"}]), 0.0)
    play(runner, sink, [0.0, 0.1, 0.5, 0.9])
    assert sink.log == ["down key:a"], "still waiting"
    runner.advance(1.1, sink)
    assert sink.log == ["down key:a", "up key:a"]


def test_a_stalled_loop_stretches_a_macro_rather_than_compressing_it() -> None:
    """A wait is measured from when it is reached, so a stall delays the rest.

    The alternative — catching up by firing every remaining step at once — would
    turn a hiccup into a burst of input, which is far worse than being late.
    """
    runner, sink = MacroRunner(), Sink()
    runner.start(parse_macro("m", ["key:a", {"wait": 0.5}, "key:b"]), 0.0)

    runner.advance(100.0, sink)
    assert sink.log == ["down key:a"], "one step, then it honours the tap wait"
    assert runner.active == ("m",)

    # It completes over the following ticks, each wait still a real wait.
    for moment in (100.1, 100.7, 100.8):
        runner.advance(moment, sink)
    assert sink.log == ["down key:a", "up key:a", "down key:b", "up key:b"]
    assert runner.active == ()


def test_retriggering_does_not_start_a_second_copy() -> None:
    """Mashing the button would otherwise interleave two playthroughs."""
    runner = MacroRunner()
    macro = parse_macro("m", ["key:a", {"wait": 0.5}, "key:b"])
    assert runner.start(macro, 0.0) is True
    assert runner.start(macro, 0.01) is False
    assert runner.active == ("m",)


def test_an_unbalanced_hold_is_released_when_the_macro_ends() -> None:
    """A macro that latches a modifier with no way up is the stuck-key bug."""
    runner, sink = MacroRunner(), Sink()
    runner.start(parse_macro("m", [{"down": "key:shift"}]), 0.0)
    runner.advance(0.0, sink)
    assert sink.log == ["down key:shift", "up key:shift"]


def test_cancel_releases_what_a_macro_holds() -> None:
    runner, sink = MacroRunner(), Sink()
    runner.start(parse_macro("m", [{"down": "key:shift"}, {"wait": 5.0}, {"up": "key:shift"}]), 0.0)
    runner.advance(0.0, sink)
    runner.cancel("m", sink)
    assert sink.log == ["down key:shift", "up key:shift"]
    assert runner.active == ()


def test_cancelling_an_unknown_macro_is_harmless() -> None:
    MacroRunner().cancel("nope", Sink())


def test_only_interruptible_macros_are_cut_short_on_release() -> None:
    steps = [{"down": "key:shift"}, {"wait": 5.0}, {"up": "key:shift"}]
    stubborn, sink = MacroRunner(), Sink()
    stubborn.start(parse_macro("m", steps), 0.0)
    stubborn.advance(0.0, sink)
    stubborn.cancel_interruptible(["m"], sink)
    assert stubborn.active == ("m",), "default is to finish"

    yielding, sink2 = MacroRunner(), Sink()
    yielding.start(parse_macro("m", {"steps": steps, "interruptible": True}), 0.0)
    yielding.advance(0.0, sink2)
    yielding.cancel_interruptible(["m"], sink2)
    assert yielding.active == ()
    assert sink2.log == ["down key:shift", "up key:shift"]


def test_release_all_abandons_everything() -> None:
    runner, sink = MacroRunner(), Sink()
    for name in ("one", "two"):
        runner.start(parse_macro(name, [{"down": "key:shift"}, {"wait": 5.0}]), 0.0)
    runner.advance(0.0, sink)
    runner.release_all(sink)
    assert runner.active == ()
    assert sink.log.count("up key:shift") == 2


def test_two_macros_run_concurrently() -> None:
    runner, sink = MacroRunner(), Sink()
    runner.start(parse_macro("one", ["key:a"]), 0.0)
    runner.start(parse_macro("two", ["key:b"]), 0.0)
    assert runner.active == ("one", "two")
    play(runner, sink, [0.0, 0.05])
    assert sorted(sink.log) == ["down key:a", "down key:b", "up key:a", "up key:b"]


def test_is_running_reports_in_flight_macros() -> None:
    runner = MacroRunner()
    runner.start(parse_macro("m", [{"wait": 1.0}]), 0.0)
    assert runner.is_running("m")
    assert not runner.is_running("other")
