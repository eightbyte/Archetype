"""Re-record ``tests/fixtures/providers/anthropic/cases.json`` against the real Messages API.

Run from ``server/`` with the venv python and ``ARCHETYPE_ANTHROPIC_API_KEY`` set. It makes real,
billed requests - the only thing in this repository that does. ``README.md`` beside this file says
what it rewrites and what it deliberately leaves alone.

    .\\.venv\\Scripts\\python.exe tests/fixtures/providers/capture_anthropic.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _capture import capture  # noqa: E402 - the path above is what makes this importable

if __name__ == "__main__":
    capture("anthropic")
