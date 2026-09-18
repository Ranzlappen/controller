"""System-tray control for a running session.

A background process with no visible control surface is awkward: you cannot
tell whether it is running, and pausing it means finding a terminal. This is
that control surface.

The menu is built as plain data by :meth:`TrayApp.menu_model` and acted on by
:func:`apply_action`, both of which are ordinary testable functions. Only the
thin layer that converts those entries into pystray objects needs a desktop,
and that part is deliberately tiny.

pystray and Pillow are an optional extra (``pip install padmap[tray]``) so the
core install stays at two dependencies.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from padmap.engine import Engine, EngineStatus

__all__ = ["MenuEntry", "TrayApp", "TrayUnavailableError", "apply_action", "menu_model"]

PAUSE = "pause"
RESUME = "resume"
RELOAD = "reload"
QUIT = "quit"
PROFILE_PREFIX = "profile:"

#: Tray icon colours by state, as RGB.
RUNNING_COLOUR = (64, 160, 96)
PAUSED_COLOUR = (200, 150, 40)


class TrayUnavailableError(RuntimeError):
    """Raised when the tray extra is not installed, or there is no tray to sit in."""


@dataclass(frozen=True)
class MenuEntry:
    """One row of the tray menu, as data rather than as a toolkit object."""

    label: str
    action: str = ""
    enabled: bool = True
    checked: bool | None = None

    @property
    def is_separator(self) -> bool:
        """True for the divider rows."""
        return self.label == "-"


SEPARATOR = MenuEntry(label="-", enabled=False)


def menu_model(
    status: EngineStatus, profiles: Sequence[str] = (), can_reload: bool = True
) -> list[MenuEntry]:
    """Build the tray menu for the engine's current state.

    The first row is a non-clickable summary — the same text the terminal
    status line shows — so hovering the tray answers "is it working?" without
    opening anything.
    """
    headline = f"padmap — {status.profile}"
    if status.settling:
        headline += " (centring…)"
    elif status.paused:
        headline += " (paused)"
    elif status.layers:
        headline += f" (layer {'+'.join(status.layers)})"

    entries = [
        MenuEntry(label=headline, enabled=False),
        MenuEntry(
            label=f"{status.events:,} event" + ("" if status.events == 1 else "s") + " sent",
            enabled=False,
        ),
        SEPARATOR,
        MenuEntry(
            label="Resume" if status.paused else "Pause",
            action=RESUME if status.paused else PAUSE,
            checked=status.paused,
        ),
    ]
    if can_reload:
        entries.append(MenuEntry(label="Reload profile", action=RELOAD))
    for name in profiles:
        entries.append(
            MenuEntry(
                label=f"Switch to {name}",
                action=f"{PROFILE_PREFIX}{name}",
                # Bundled profiles are named by their lowercase id ("desktop")
                # but carry a display name ("Desktop"); match on either.
                checked=name.casefold() == status.profile.casefold(),
            )
        )
    entries.extend([SEPARATOR, MenuEntry(label="Quit", action=QUIT)])
    return entries


def apply_action(
    engine: Engine,
    action: str,
    switch_profile: Callable[[str], None] | None = None,
) -> None:
    """Carry out one menu action against a running engine.

    Pause and profile changes go through the engine's request API rather than
    being applied here, because this runs on the tray's thread. Unknown actions
    are ignored rather than raising: a stray tray click is not worth taking
    down a session that is holding keys.
    """
    if action == PAUSE:
        engine.request_pause(True)
    elif action == RESUME:
        engine.request_pause(False)
    elif action == QUIT:
        engine.stop()
    elif action == RELOAD:
        engine.request_reload()
    elif action.startswith(PROFILE_PREFIX) and switch_profile is not None:
        switch_profile(action[len(PROFILE_PREFIX) :])


def make_image(
    colour: tuple[int, int, int], size: int = 64
) -> Any:  # pragma: no cover - needs Pillow
    """A simple round icon in the state colour."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise TrayUnavailableError(
            "the tray needs Pillow. Install it with: pip install 'padmap[tray]'"
        ) from exc

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, size - 3, size - 3), fill=(*colour, 255))
    # A small notch so the icon reads as a gamepad rather than a dot.
    draw.rounded_rectangle(
        (size * 0.28, size * 0.42, size * 0.72, size * 0.62), radius=6, fill=(255, 255, 255, 230)
    )
    return image


class TrayApp:  # pragma: no cover - needs a desktop session
    """Runs the engine on a worker thread and the tray on the main thread.

    That split is not a preference: on macOS the tray must own the main thread,
    and pystray's run loop never returns until the icon stops.
    """

    def __init__(
        self,
        engine: Engine,
        profiles: Sequence[str] = (),
        switch_profile: Callable[[str], None] | None = None,
    ) -> None:
        self.engine = engine
        self.profiles = list(profiles)
        self.switch_profile = switch_profile
        self._icon: Any = None
        self._thread: threading.Thread | None = None

    def _pystray(self) -> Any:
        try:
            import pystray
        except ImportError as exc:
            raise TrayUnavailableError(
                "the tray needs pystray. Install it with: pip install 'padmap[tray]'"
            ) from exc
        return pystray

    def _build_menu(self, pystray: Any) -> Any:
        items = []
        for entry in menu_model(self.engine.status(), self.profiles, self.engine.can_reload):
            if entry.is_separator:
                items.append(pystray.Menu.SEPARATOR)
                continue
            items.append(
                pystray.MenuItem(
                    entry.label,
                    self._make_handler(entry.action),
                    enabled=entry.enabled,
                    checked=(lambda _item, value=entry.checked: value)
                    if entry.checked is not None
                    else None,
                )
            )
        return pystray.Menu(*items)

    def _make_handler(self, action: str) -> Any:
        def handler(_icon: Any = None, _item: Any = None) -> None:
            apply_action(self.engine, action, self.switch_profile)
            if action == QUIT and self._icon is not None:
                self._icon.stop()
            elif self._icon is not None:
                self._icon.menu = self._build_menu(self._pystray())
                self._icon.update_menu()

        return handler

    def on_frame(self, status: EngineStatus) -> None:
        """Keep the icon's colour and tooltip in step with the engine."""
        if self._icon is None:
            return
        self._icon.icon = make_image(PAUSED_COLOUR if status.paused else RUNNING_COLOUR)
        self._icon.title = f"padmap — {status.profile}" + (" (paused)" if status.paused else "")

    def run(self) -> None:
        """Start the engine thread and block on the tray loop."""
        pystray = self._pystray()
        self._icon = pystray.Icon(
            "padmap",
            make_image(RUNNING_COLOUR),
            "padmap",
            menu=self._build_menu(pystray),
        )
        self._thread = threading.Thread(target=self.engine.run, name="padmap-engine", daemon=True)
        self._thread.start()
        try:
            self._icon.run()
        finally:
            self.engine.stop()
            self._thread.join(timeout=2.0)
            self.engine.release_all()
