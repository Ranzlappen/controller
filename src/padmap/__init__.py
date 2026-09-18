"""padmap — map an Xbox controller to keyboard keys and mouse movement.

The package is import-light on purpose: nothing here pulls in pygame or
pynput. Those land only when :mod:`padmap.devices` / :mod:`padmap.backends`
actually open hardware, which keeps ``import padmap`` cheap and keeps the
pure-logic modules testable on a headless machine.
"""

from __future__ import annotations

__version__ = "0.3.0"

__all__ = ["__version__"]
