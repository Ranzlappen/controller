"""Profile loading and validation.

Strictness is the point here: a remapper that silently ignores a typo is
indistinguishable from broken hardware, so every one of these rejections is a
deliberate feature.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from padmap.config import (
    Binding,
    Profile,
    ProfileError,
    bundled_profile_names,
    load_profile,
    starter_profile_json,
)

MINIMAL = {"name": "Test", "buttons": {"a": "mouse:left"}}


def build(**overrides) -> Profile:
    """Build a profile from the minimal valid document plus overrides."""
    return Profile.from_dict({**MINIMAL, **overrides})


# --- Bundled profiles --------------------------------------------------------


def test_every_bundled_profile_loads() -> None:
    names = bundled_profile_names()
    assert {"desktop", "fps", "starter"} <= set(names)
    for name in names:
        assert load_profile(name).binding_count > 0


def test_the_starter_profile_is_itself_valid() -> None:
    """`padmap init` must never write a file that `padmap validate` rejects."""
    Profile.from_dict(json.loads(starter_profile_json()))


def test_bundled_profiles_all_offer_a_pause_button() -> None:
    """Every shipped profile needs a way to stop output without reaching for the keyboard."""
    for name in bundled_profile_names():
        commands = {b.action.command for b in load_profile(name).buttons.values()}
        assert "toggle_pause" in commands, name


def test_unknown_profile_name_lists_the_alternatives() -> None:
    with pytest.raises(ProfileError, match="Bundled profiles"):
        load_profile("nonexistent-profile")


# --- Loading from disk -------------------------------------------------------


def test_load_from_a_path(tmp_path: Path) -> None:
    path = tmp_path / "mine.json"
    path.write_text(json.dumps(MINIMAL), encoding="utf-8")
    profile = load_profile(str(path))
    assert profile.name == "Test"
    assert profile.source == str(path)


def test_a_local_file_wins_over_a_bundled_name(tmp_path: Path, monkeypatch) -> None:
    """Copying `desktop.json` out to edit should shadow the bundled one."""
    monkeypatch.chdir(tmp_path)
    Path("desktop.json").write_text(json.dumps({**MINIMAL, "name": "Mine"}), encoding="utf-8")
    assert load_profile("desktop.json").name == "Mine"


def test_missing_file_reports_the_path(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="cannot read profile"):
        load_profile(str(tmp_path / "absent.json"))


def test_invalid_json_reports_the_line(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"name": "x",\n  oops}', encoding="utf-8")
    with pytest.raises(ProfileError, match="line 2"):
        load_profile(str(path))


# --- Schema strictness -------------------------------------------------------


def test_unknown_section_is_rejected() -> None:
    with pytest.raises(ProfileError, match="unknown section"):
        build(rumble={"enabled": True})


def test_unknown_button_is_rejected_with_the_valid_list() -> None:
    with pytest.raises(ProfileError, match="unknown button"):
        Profile.from_dict({"buttons": {"turbo": "key:a"}})


def test_unknown_stick_is_rejected() -> None:
    with pytest.raises(ProfileError, match="unknown stick"):
        build(sticks={"middle": {"mode": "mouse"}})


def test_unknown_binding_option_is_rejected() -> None:
    with pytest.raises(ProfileError, match="unknown option"):
        Profile.from_dict({"buttons": {"a": {"action": "key:a", "trubo": 5}}})


def test_a_bad_action_error_names_its_path() -> None:
    with pytest.raises(ProfileError, match="buttons.a:"):
        Profile.from_dict({"buttons": {"a": "key:nonsense"}})


def test_out_of_range_number_is_rejected() -> None:
    with pytest.raises(ProfileError, match="out of range"):
        build(poll_hz=100000)


def test_wrong_type_is_rejected() -> None:
    with pytest.raises(ProfileError, match="expected a number"):
        build(poll_hz="fast")
    with pytest.raises(ProfileError, match="expected an object"):
        Profile.from_dict([1, 2, 3])


def test_booleans_are_not_numbers() -> None:
    """`True` is an int in Python; a profile saying `"poll_hz": true` is still wrong."""
    with pytest.raises(ProfileError, match="expected a number"):
        build(poll_hz=True)


# --- Bindings ----------------------------------------------------------------


def test_binding_accepts_a_bare_string_or_an_object() -> None:
    assert Binding.parse("key:w", "x").action.keys == ("w",)
    binding = Binding.parse({"action": "key:w", "turbo": 10}, "x")
    assert binding.turbo_hz == 10


def test_turbo_and_toggle_together_are_rejected() -> None:
    with pytest.raises(ProfileError, match="cannot both be set"):
        Binding.parse({"action": "key:w", "turbo": 5, "toggle": True}, "buttons.a")


def test_noop_binding_is_allowed_and_counts_for_nothing() -> None:
    profile = Profile.from_dict({"buttons": {"a": "noop", "b": "key:x"}})
    assert profile.binding_count == 1


# --- Sticks and triggers -----------------------------------------------------


def test_stick_defaults_depend_on_the_mode() -> None:
    mouse = build(sticks={"left": {"mode": "mouse"}}).sticks["left"]
    scroll = build(sticks={"right": {"mode": "scroll"}}).sticks["right"]
    assert mouse.speed > scroll.speed


def test_keys_mode_needs_at_least_one_direction() -> None:
    with pytest.raises(ProfileError, match="needs at least one"):
        build(sticks={"left": {"mode": "keys"}})


def test_unknown_stick_mode_is_rejected() -> None:
    with pytest.raises(ProfileError, match="unknown mode"):
        build(sticks={"left": {"mode": "teleport"}})


def test_stick_off_by_default() -> None:
    assert not build().sticks


def test_trigger_accepts_a_string_or_an_object() -> None:
    assert build(triggers={"rt": "mouse:left"}).triggers["rt"].threshold == 0.5
    detailed = build(triggers={"rt": {"action": "mouse:left", "threshold": 0.25}})
    assert detailed.triggers["rt"].threshold == 0.25


# --- Device block ------------------------------------------------------------


def test_device_layout_override_lands_on_the_layout() -> None:
    profile = build(device={"match": "xbox", "layout": {"a": 3}})
    assert profile.device.layout.buttons["a"] == 3
    assert profile.device.match == "xbox"


def test_device_layout_rejects_an_unknown_input() -> None:
    with pytest.raises(ProfileError, match="unknown input"):
        build(device={"layout": {"paddle_1": 11}})


def test_device_layout_rejects_a_non_integer_index() -> None:
    with pytest.raises(ProfileError, match="expected an integer index"):
        build(device={"layout": {"a": "first"}})


def test_device_index_must_be_an_integer() -> None:
    with pytest.raises(ProfileError, match="expected an integer"):
        build(device={"index": "1"})


def test_unknown_trigger_mode_is_rejected() -> None:
    with pytest.raises(ProfileError, match="unknown mode"):
        build(device={"trigger_mode": "bipolar"})


def test_trigger_mode_reaches_the_layout() -> None:
    assert build(device={"trigger_mode": "unipolar"}).device.layout.trigger_mode == "unipolar"


# --- describe() --------------------------------------------------------------


def test_describe_covers_every_bound_input() -> None:
    text = "\n".join(load_profile("fps").describe())
    assert "buttons.a: key:space" in text
    assert "trigger.rt: mouse:left" in text
    assert "stick.left: keys" in text
    assert "up: key:w" in text
    assert "[toggle]" in text


def test_describe_shows_turbo_rate() -> None:
    assert "turbo 12Hz" in "\n".join(load_profile("desktop").describe())


def test_describe_omits_unbound_inputs() -> None:
    assert "buttons.x" not in "\n".join(build().describe())
