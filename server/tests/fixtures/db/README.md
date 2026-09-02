# Database fixtures

One database file per schema version, used by the migration tests (P1-3, D20).

Every migration ships with a test that runs it against a fixture database captured at the
**previous** version. That is what makes forward-only migrations safe to trust: the test proves
the migration works on a file that predates it, not just on one this build created.

| File | Version | What it is |
|---|---|---|
| `v000_empty.sqlite` | 0 | A zero-byte file. SQLite treats it as a valid, empty database - which is exactly the state a project file is in before `001_init.sql` runs. |
| `v001_phase1.sqlite` | 1 | A real Phase 1 project file: one project, two written chapters with headings, prose, derived projections, and a version of 3. Captured before `002_anchors_and_snapshots.sql` was written, which is the whole point of it. |

## Capturing the next one

Before writing migration `00N`, capture the current schema as `v<N-1 zero-padded>_<slug>.sqlite`
**while the code is still at version `N-1`** - a fixture captured afterwards proves nothing,
because it was made by the code the migration is supposed to be tested against.

A structural-only migration can be tested against an empty file:

```powershell
# from server/, with the venv active
python -c "from pathlib import Path; from archetype.projects import open_migrated; open_migrated(Path('tests/fixtures/db/vNNN_slug.sqlite')).close()"
```

A migration that touches data needs representative rows, and those are worth generating from a
committed script rather than by hand, so the fixture can be rebuilt and reviewed rather than
being an opaque binary. `capture_v001_phase1.py` is the worked example: it refuses to run unless
the code is at the version it claims to capture, writes fixed ids and timestamps so a re-run
produces the same file, and folds the write-ahead log back in so what lands is a single
self-contained database.

```powershell
# from server/, with the venv active, before writing the new migration
python tests/fixtures/db/capture_vNNN_slug.py
```

Then commit the file. Fixture databases are small and are meant to be committed - they are the
only record of what an older schema actually looked like.
