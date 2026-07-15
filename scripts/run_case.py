#!/usr/bin/env python3
"""Run the local aircraft cash-flow package without installing it."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aircraft_cashflow.__main__ import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

