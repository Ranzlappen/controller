"""The action grammar: what a profile is allowed to say."""

from __future__ import annotations

import pytest

from padmap.actions import NOOP, Action, ActionError, parse_action, resolve_key


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("key:w", Action(kind="key", keys=("w",), source="key:w")),
        ("mouse:left", Action(kind="mouse", button="left", source="mouse:left")),
        ("scroll:up", Action(kind="scroll", direction="up", source="scroll:up")),
        ("special:quit", Action(kind="special", command="quit", source="special:quit")),
    ],
)
def test_parses_each_kind(spec: str, expected: Action) -> None:
    assert parse_action(spec) == expected


@pytest.mark.parametrize("spec", [None, "", "  ", "noop", "none", "NOOP"])
def test_blank_specs_mean_do_nothing(spec: str | None) -> None:
    assert parse_action(spec).is_noop


def test_key_combo_keeps_modifier_order() -> None:
    assert parse_action("key:ctrl+shift+s").keys == ("ctrl", "shift", "s")


def test_lone_plus_is_the_plus_character() -> None:
    """`key:+` is the key, not an empty combo — the obvious parser bug to avoid."""
    assert parse_action("key:+").keys == ("+",)


def test_text_preserves_whitespace() -> None:
    assert parse_action("text: hello world ").text == " hello world "


def test_aliases_resolve_to_canonical_names() -> None:
    assert resolve_key("PgUp") == "page_up"
    assert resolve_key("escape") == "esc"
    assert resolve_key("win") == "cmd"


def test_side_mouse_buttons_are_accepted_as_less_portable() -> None:
    """pynput names these differently per backend; the backend ignores what it can't map."""
    assert parse_action("mouse:x1").button == "x1"
    assert parse_action("mouse:x2").button == "x2"


def test_move_nudges_the_pointer_by_pixels() -> None:
    action = parse_action("move:20,-15")
    assert (action.dx, action.dy) == (20, -15)
    assert action.is_repeatable, "holding a nudge should keep nudging"


def test_macro_references_a_named_macro() -> None:
    assert parse_action("macro:copy-paste").macro == "copy-paste"


def test_held_and_repeatable_classification() -> None:
    assert parse_action("key:a").is_held
    assert parse_action("mouse:left").is_held
    assert not parse_action("scroll:up").is_held
    assert parse_action("scroll:up").is_repeatable
    assert not parse_action("text:hi").is_held
    assert NOOP.is_noop


@pytest.mark.parametrize(
    "spec",
    [
        "key:nope",
        "key:",
        "key:a++b",
        "scroll:sideways",
        "special:selfdestruct",
        "wat:1",
        "justtext",
    ],
)
def test_bad_specs_are_rejected(spec: str) -> None:
    with pytest.raises(ActionError):
        parse_action(spec)


def test_non_string_is_rejected() -> None:
    with pytest.raises(ActionError):
        parse_action(42)  # type: ignore[arg-type]


def test_error_names_the_offending_value() -> None:
    with pytest.raises(ActionError, match="ctrl_alt_del"):
        parse_action("key:ctrl_alt_del")
