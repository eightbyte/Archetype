"""Re-record ``tests/fixtures/providers/openai/cases.json`` against a chat-completions server.

Run from ``server/`` with the venv python, ``ARCHETYPE_OPENAI_API_KEY`` set, and
``ARCHETYPE_LLM_BASE_URL`` pointed at whichever server is being captured - which is the whole
point of the corpus's ``local_server_streamed`` case. It makes real, billed requests.

    .\\.venv\\Scripts\\python.exe tests/fixtures/providers/capture_openai.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _capture import capture  # noqa: E402 - the path above is what makes this importable

if __name__ == "__main__":
    capture("openai")
