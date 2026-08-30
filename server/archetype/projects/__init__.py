"""Project files: connections, migrations, and the project store (P1-3, P1-4)."""

from .db import BUSY_TIMEOUT_MS, connect, transaction, utc_now
from .migrations import (
    MIGRATIONS_DIR,
    Migration,
    MigrationError,
    current_version,
    latest_version,
    load_migrations,
    migrate,
    open_migrated,
)
from .store import (
    PROJECT_FILE_SUFFIX,
    ProjectHandle,
    ProjectNotFoundError,
    ProjectStore,
    ProjectStoreError,
    ProjectSummary,
    ScanResult,
    SkippedFile,
    slugify,
)

__all__ = [
    "BUSY_TIMEOUT_MS",
    "MIGRATIONS_DIR",
    "PROJECT_FILE_SUFFIX",
    "Migration",
    "MigrationError",
    "ProjectHandle",
    "ProjectNotFoundError",
    "ProjectStore",
    "ProjectStoreError",
    "ProjectSummary",
    "ScanResult",
    "SkippedFile",
    "connect",
    "current_version",
    "latest_version",
    "load_migrations",
    "migrate",
    "open_migrated",
    "slugify",
    "transaction",
    "utc_now",
]
