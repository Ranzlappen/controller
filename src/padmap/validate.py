"""Primitives for validating one value out of a profile, with its path.

Split out of :mod:`padmap.config` so the schema there reads as schema. Every
function takes the dotted path of the value it is checking and puts it in the
message, because "expected a number" is useless and
``sticks.left.curve: expected a number`` is not.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ProfileError", "boolean", "mapping", "number", "reject_unknown", "text"]


class ProfileError(ValueError):
    """Raised when a profile is malformed, or names something that doesn't exist."""


def mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileError(f"{path}: expected an object, got {type(value).__name__}")
    return value


def reject_unknown(data: dict[str, Any], allowed: set[str], path: str, hint: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ProfileError(
            f"{path}: unknown {hint} {', '.join(repr(k) for k in unknown)}. "
            f"Valid: {', '.join(sorted(allowed))}"
        )


def number(value: Any, path: str, low: float, high: float, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{path}: expected a number, got {type(value).__name__}")
    number = float(value)
    if not low <= number <= high:
        raise ProfileError(f"{path}: {number} is out of range [{low}, {high}]")
    return number


def boolean(value: Any, path: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ProfileError(f"{path}: expected true or false, got {type(value).__name__}")
    return value


def text(value: Any, path: str, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ProfileError(f"{path}: expected a string, got {type(value).__name__}")
    return value
