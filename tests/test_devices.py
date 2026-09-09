"""Raw SDL readings translated into named inputs."""

from __future__ import annotations

import pytest

from padmap.devices import (
    DEFAULT_LAYOUT,
    DeviceError,
    DeviceInfo,
    axes_to_dpad,
    build_state,
    empty_state,
    hat_to_dpad,
    select_device,
)

FULL_BUTTONS = [0] * 11
FULL_AXES = [0.0, 0.0, -1.0, 0.0, 0.0, -1.0]


def test_empty_state_is_neutral() -> None:
    state = empty_state()
    assert not any(state.buttons.values())
    assert not any(state.dpad.values())
    assert set(state.axes.values()) == {0.0}


def test_build_state_names_the_raw_indices() -> None:
    buttons = list(FULL_BUTTONS)
    buttons[0] = 1  # A
    buttons[5] = 1  # RB
    state = build_state(buttons, [0.5, -0.25, -1.0, 0.0, 0.0, -1.0], [])
    assert state.button("a") is True
    assert state.button("rb") is True
    assert state.button("b") is False
    assert state.axis("left_x") == 0.5
    assert state.axis("left_y") == -0.25


def test_triggers_are_normalised_to_zero_one() -> None:
    state = build_state(FULL_BUTTONS, [0, 0, -1.0, 0, 0, 1.0], [])
    assert state.axis("lt") == 0.0
    assert state.axis("rt") == 1.0


def test_unipolar_triggers_are_read_as_given() -> None:
    state = build_state(FULL_BUTTONS, [0, 0, 0.4, 0, 0, 0.0], [], signed_triggers=False)
    assert state.axis("lt") == pytest.approx(0.4)
    assert state.axis("rt") == 0.0


def test_a_pad_with_fewer_axes_reads_as_released_not_half_pulled() -> None:
    """A missing trigger axis must be 0.0, not the 0.5 a naive signed read gives."""
    state = build_state([1], [0.3, 0.1], [])
    assert state.axis("lt") == 0.0
    assert state.axis("rt") == 0.0
    assert state.axis("left_x") == pytest.approx(0.3)


def test_missing_button_index_reads_as_released() -> None:
    assert build_state([1], FULL_AXES, []).button("guide") is False


@pytest.mark.parametrize(
    ("hat", "expected"),
    [
        ((0, 1), "up"),
        ((0, -1), "down"),
        ((-1, 0), "left"),
        ((1, 0), "right"),
    ],
)
def test_hat_uses_sdl_sign_convention(hat: tuple[int, int], expected: str) -> None:
    """SDL hats are y-up-positive — the opposite of the sticks."""
    directions = hat_to_dpad(hat)
    assert directions[expected] is True
    assert sum(directions.values()) == 1


def test_hat_diagonal_sets_two_directions() -> None:
    assert hat_to_dpad((1, 1)) == {"up": True, "down": False, "left": False, "right": True}


def test_dpad_falls_back_to_axes_when_the_pad_has_no_hat() -> None:
    axes = [0.0] * 8
    axes[7] = -1.0  # dpad-as-axis, y-up-is-negative
    assert build_state(FULL_BUTTONS, axes, []).dpad["up"] is True


def test_axes_to_dpad_respects_the_threshold() -> None:
    assert axes_to_dpad(0.4, 0.0)["right"] is False
    assert axes_to_dpad(0.6, 0.0)["right"] is True


def test_layout_overrides_a_single_index() -> None:
    layout = DEFAULT_LAYOUT.with_overrides({"a": 2, "left_x": 3})
    assert layout.buttons["a"] == 2
    assert layout.axes["left_x"] == 3
    # The original is untouched.
    assert DEFAULT_LAYOUT.buttons["a"] == 0


def test_layout_override_of_an_unknown_name_is_rejected() -> None:
    with pytest.raises(DeviceError, match="unknown input"):
        DEFAULT_LAYOUT.with_overrides({"turbo_button": 3})


def test_layout_with_no_overrides_returns_itself() -> None:
    assert DEFAULT_LAYOUT.with_overrides(None) is DEFAULT_LAYOUT


DEVICES = [
    DeviceInfo(0, "Generic Gamepad", "guid-0", 4, 10, 0),
    DeviceInfo(1, "Xbox One Controller", "guid-1", 6, 11, 1),
]


def test_select_device_prefers_an_explicit_index() -> None:
    assert select_device(DEVICES, None, 1).name == "Xbox One Controller"


def test_select_device_matches_on_name_substring() -> None:
    assert select_device(DEVICES, "xbox", None).index == 1


def test_select_device_defaults_to_the_first() -> None:
    assert select_device(DEVICES, None, None).index == 0


def test_select_device_errors_are_actionable() -> None:
    with pytest.raises(DeviceError, match="no controller detected"):
        select_device([], None, None)
    with pytest.raises(DeviceError, match="padmap devices"):
        select_device(DEVICES, None, 7)
    with pytest.raises(DeviceError, match="Attached"):
        select_device(DEVICES, "dualshock", None)
