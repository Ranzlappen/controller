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
        "mouse:x1",
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
