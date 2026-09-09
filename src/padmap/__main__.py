"""Entry point for ``python -m padmap``."""

from __future__ import annotations

import sys

from padmap.cli import main

if __name__ == "__main__":
    sys.exit(main())
