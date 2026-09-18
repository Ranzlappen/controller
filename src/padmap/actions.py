"""The action grammar: what a controller input is allowed to *do*.

Every binding in a profile is written as a short string — ``"key:w"``,
``"mouse:left"``, ``"scroll:up"``, ``"text:gg"``, ``"special:toggle_pause"``.
This module parses those strings into :class:`Action` values and validates
them, so a typo in a profile fails at load time with a useful message instead
of silently doing nothing an hour into a session.

Nothing here imports pynput. The name tables below are the contract between a
profile and :mod:`padmap.backends`; keeping them import-free is what lets the
whole grammar be unit-tested on a headless machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "Action",
    "ActionError",
    "MOUSE_BUTTONS",
    "NOOP",
    "SCROLL_DIRECTIONS",
    "SPECIAL_COMMANDS",
    "parse_action",
    "resolve_key",
]


class ActionError(ValueError):
    """Raised when an action string cannot be parsed or names something unknown."""


# --- Name tables -------------------------------------------------------------

#: Named keys that exist as ``pynput.keyboard.Key`` members. Anything not in
#: here (and not a single printable character) is rejected at parse time.
SPECIAL_KEYS: frozenset[str] = frozenset(
    {
        "alt",
        "alt_gr",
        "alt_l",
        "alt_r",
        "backspace",
        "caps_lock",
        "cmd",
        "cmd_l",
        "cmd_r",
        "ctrl",
        "ctrl_l",
        "ctrl_r",
        "delete",
        "down",
        "end",
        "enter",
        "esc",
        "home",
        "insert",
        "left",
        "media_next",
        "media_play_pause",
        "media_previous",
        "media_volume_down",
        "media_volume_mute",
        "media_volume_up",
        "menu",
        "num_lock",
        "page_down",
        "page_up",
        "pause",
        "print_screen",
        "right",
        "scroll_lock",
        "shift",
        "shift_l",
        "shift_r",
        "space",
        "tab",
        "up",
        *(f"f{n}" for n in range(1, 21)),
    }
)

#: Friendly spellings people actually type, mapped onto the canonical name.
KEY_ALIASES: dict[str, str] = {
    "capslock": "caps_lock",
    "control": "ctrl",
    "del": "delete",
    "escape": "esc",
    "ins": "insert",
    "meta": "cmd",
    "mute": "media_volume_mute",
    "numlock": "num_lock",
    "pagedown": "page_down",
    "pageup": "page_up",
    "pgdn": "page_down",
    "pgup": "page_up",
    "playpause": "media_play_pause",
    "printscreen": "print_screen",
    "return": "enter",
    "scrolllock": "scroll_lock",
    "super": "cmd",
    "voldown": "media_volume_down",
    "volup": "media_volume_up",
    "win": "cmd",
}

#: Mouse buttons that exist on every platform pynput supports. Side buttons
#: (x1/x2) are deliberately excluded — they are named differently per backend
#: and would make a profile non-portable.
MOUSE_BUTTONS: frozenset[str] = frozenset({"left", "middle", "right"})

SCROLL_DIRECTIONS: frozenset[str] = frozenset({"up", "down", "left", "right"})

#: Commands handled by the engine itself rather than by an output backend.
#: ``layer`` takes an argument (``special:layer:shift``); the rest do not.
SPECIAL_COMMANDS: frozenset[str] = frozenset({"toggle_pause", "quit", "precision", "layer"})

#: Specials that act while held rather than firing once on press. These never
#: reach an output backend — the engine consumes them.
MODIFIER_COMMANDS: frozenset[str] = frozenset({"precision", "layer"})

#: Specials that take a ``:argument`` suffix.
PARAMETERISED_COMMANDS: frozenset[str] = frozenset({"layer"})

# Action kinds.
KEY = "key"
MOUSE = "mouse"
SCROLL = "scroll"
TEXT = "text"
SPECIAL = "special"
NOOP_KIND = "noop"


# --- The action value --------------------------------------------------------


@dataclass(frozen=True)
class Action:
    """A single thing an input can do.

    Exactly one payload field is meaningful per ``kind``; the rest stay empty.
    Frozen so a parsed profile can be shared freely across the engine.
    """

    kind: str
    keys: tuple[str, ...] = field(default=())
    button: str = ""
    direction: str = ""
    text: str = ""
    command: str = ""
    argument: str = ""
    source: str = ""

    @property
    def is_noop(self) -> bool:
        """True when this action deliberately does nothing."""
        return self.kind == NOOP_KIND

    @property
    def is_held(self) -> bool:
        """True when the action has press/release semantics.

        Held actions go down when the input goes down and — importantly — come
        back up when it is released or when padmap exits. One-shot actions
        (``text``, ``special``) fire once per press instead.
        """
        return self.kind in (KEY, MOUSE)

    @property
    def is_repeatable(self) -> bool:
        """True when holding the input should keep re-firing the action."""
        return self.kind == SCROLL

    @property
    def is_modifier(self) -> bool:
        """True for specials that apply while held (``precision``, ``layer``).

        The engine tracks these itself; they never reach an output backend, and
        unlike other specials they act on release as well as on press.
        """
        return self.kind == SPECIAL and self.command in MODIFIER_COMMANDS

    def __str__(self) -> str:
        return self.source or self.kind


NOOP = Action(kind=NOOP_KIND, source="noop")


# --- Parsing -----------------------------------------------------------------


def resolve_key(name: str) -> str:
    """Normalise one key name, or raise :class:`ActionError`.

    Accepts a canonical name (``"page_up"``), a friendly alias (``"pgup"``),
    or any single printable character (``"w"``, ``"/"``).
    """
    cleaned = name.strip().lower()
    if not cleaned:
        raise ActionError("empty key name")
    canonical = KEY_ALIASES.get(cleaned, cleaned)
    if canonical in SPECIAL_KEYS:
        return canonical
    if len(cleaned) == 1 and cleaned.isprintable():
        return cleaned
    raise ActionError(
        f"unknown key {name!r}. Use a single character (e.g. 'w'), or one of: "
        f"{', '.join(sorted(SPECIAL_KEYS))}"
    )


def _parse_key(payload: str, source: str) -> Action:
    # A bare "+" is the plus character, not an empty combo.
    parts = [payload] if len(payload) == 1 else payload.split("+")
    if any(not part.strip() for part in parts):
        raise ActionError(f"malformed key combo {source!r} — empty segment around '+'")
    return Action(kind=KEY, keys=tuple(resolve_key(part) for part in parts), source=source)


def _parse_member(payload: str, allowed: frozenset[str], label: str, source: str) -> str:
    value = payload.strip().lower()
    if value not in allowed:
        raise ActionError(
            f"unknown {label} {payload!r} in {source!r}. Valid values: {', '.join(sorted(allowed))}"
        )
    return value


def _parse_special(payload: str, source: str) -> Action:
    """Parse a special, which may carry an argument (``special:layer:shift``)."""
    command, _, argument = payload.partition(":")
    command = _parse_member(command, SPECIAL_COMMANDS, "special command", source)
    argument = argument.strip()

    if command in PARAMETERISED_COMMANDS:
        if not argument:
            raise ActionError(
                f"{source!r} needs a name, e.g. 'special:{command}:shift'. The same "
                f"name is the key under the profile's 'layers' section."
            )
        if not all(ch.isalnum() or ch in "_-" for ch in argument):
            raise ActionError(
                f"invalid {command} name {argument!r} in {source!r} — use letters, "
                "digits, '-' or '_'."
            )
    elif argument:
        raise ActionError(f"special command {command!r} takes no argument, got {argument!r}")

    return Action(kind=SPECIAL, command=command, argument=argument.lower(), source=source)


def parse_action(spec: str | None) -> Action:
    """Parse one action string into an :class:`Action`.

    ``None``, an empty string, ``"noop"`` and ``"none"`` all mean "do nothing",
    which is how a profile switches an input off without deleting the line.
    """
    if spec is None:
        return NOOP
    if not isinstance(spec, str):
        raise ActionError(f"action must be a string, got {type(spec).__name__}")

    source = spec.strip()
    if not source or source.lower() in ("noop", "none"):
        return NOOP

    # Partition the *raw* spec, not the stripped one: a `text:` payload's
    # trailing whitespace is content, and stripping it here would eat it.
    kind, separator, payload = spec.partition(":")
    kind = kind.strip().lower()
    if not separator:
        raise ActionError(
            f"missing ':' in action {source!r} — expected '<kind>:<value>', "
            "e.g. 'key:w' or 'mouse:left'"
        )
    if not payload.strip() and kind != TEXT:
        raise ActionError(f"action {source!r} has no value after ':'")

    if kind == KEY:
        return _parse_key(payload.strip(), source)
    if kind == MOUSE:
        return Action(
            kind=MOUSE,
            button=_parse_member(payload, MOUSE_BUTTONS, "mouse button", source),
            source=source,
        )
    if kind == SCROLL:
        return Action(
            kind=SCROLL,
            direction=_parse_member(payload, SCROLL_DIRECTIONS, "scroll direction", source),
            source=source,
        )
    if kind == TEXT:
        # Whitespace is meaningful here, so the raw payload is kept as typed.
        return Action(kind=TEXT, text=payload, source=source)
    if kind == SPECIAL:
        return _parse_special(payload.strip(), source)

    raise ActionError(
        f"unknown action kind {kind!r} in {source!r}. "
        f"Valid kinds: key, mouse, scroll, text, special, noop"
    )
