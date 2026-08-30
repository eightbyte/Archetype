"""``python -m archetype`` - run the development server (P1-1).

Binds to the configured host and port, which default to 127.0.0.1:8787 (D7).
"""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "archetype.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="debug" if settings.log_level == "trace" else settings.log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
