"""Finding and reading profiles — from the bundle, or from a path.

Split from :mod:`padmap.config`, which is the schema. This module is the only
part of padmap that knows profiles live in files at all, which is what lets the
whole schema be exercised from dictionaries in tests.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from padmap.config import Profile
from padmap.validate import ProfileError

__all__ = [
    "bundled_profile_names",
    "load_profile",
    "load_profile_file",
    "starter_profile_json",
]


def _profiles_dir():
    return resources.files("padmap") / "profiles"


def bundled_profile_names() -> list[str]:
    """Names of the profiles shipped inside the package."""
    return sorted(
        entry.name.removesuffix(".json")
        for entry in _profiles_dir().iterdir()
        if entry.name.endswith(".json")
    )


def load_profile(reference: str) -> Profile:
    """Load a profile by bundled name (``desktop``) or by file path.

    A path is tried first so a local ``desktop.json`` in the working directory
    wins over the bundled profile of the same name — the least surprising
    behaviour when someone copies a bundled profile out to edit it.
    """
    path = Path(reference)
    if path.suffix == ".json" or path.exists():
        return load_profile_file(path)

    available = bundled_profile_names()
    if reference not in available:
        raise ProfileError(
            f"unknown profile {reference!r}. Bundled profiles: {', '.join(available)}. "
            "Pass a path to a .json file to use your own."
        )
    text = (_profiles_dir() / f"{reference}.json").read_text(encoding="utf-8")
    return _from_json(text, source=f"bundled:{reference}")


def load_profile_file(path: Path) -> Profile:
    """Load and validate a profile from a filesystem path."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"cannot read profile {str(path)!r}: {exc}") from exc
    return _from_json(text, source=str(path))


def _from_json(text: str, source: str) -> Profile:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{source}: invalid JSON on line {exc.lineno}: {exc.msg}") from exc
    return Profile.from_dict(data, source=source)


def starter_profile_json() -> str:
    """The commented starting point ``padmap init`` writes out."""
    return (_profiles_dir() / "starter.json").read_text(encoding="utf-8")
