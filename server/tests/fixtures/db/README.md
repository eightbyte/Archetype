# Database fixtures

One database file per schema version, used by the migration tests (P1-3, D20).

Every migration ships with a test that runs it against a fixture database captured at the
**previous** version. That is what makes forward-only migrations safe to trust: the test proves
the migration works on a file that predates it, not just on one this build created.

| File | Version | What it is |
|---|---|---|
| `v000_empty.sqlite` | 0 | A zero-byte file. SQLite treats it as a valid, empty database - which is exactly the state a project file is in before `001_init.sql` runs. |
| `v001_phase1.sqlite` | 1 | A real Phase 1 project file: one project, two written chapters with headings, prose, derived projections, and a version of 3. Captured before `002_anchors_and_snapshots.sql` was written, which is the whole point of it. |
| `v002_phase2.sqlite` | 2 | A real Phase 2 project file: two live chapters with **anchors in both**, one **soft-deleted** chapter that also carries an anchor, a `manual` snapshot, and the `pre-delete` snapshot the soft delete wrote inside its own transaction. Captured before `003_bible.sql` was written. The deleted chapter is deliberate: it means migration 003 is tested against a file with the D22 predicate already in play, and against an anchor whose *effective* status is `orphaned` while its stored status is not. |

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
being an opaque binary. `capture_v002_phase2.py` is the worked example: it refuses to run unless
the code is at the version it claims to capture, builds its manuscript **through the real stores**
so the derived columns are the ones the code actually produces, then normalises ids and timestamps
to fixed values, and folds the write-ahead log back in so what lands is a single self-contained
database.

Two things are easy to miss when writing one:

- **The migration runner stamps its own `applied_at` from the wall clock.** Pinning only the rows
  the script writes leaves the file different on every run; `schema_version` has to be normalised
  too. (`capture_v001_phase1.py`, the earlier example, does not do this — its output is stable in
  content but not byte for byte.)
- **Renaming a document id breaks the rows pointing at it** for the length of the rename.
  `PRAGMA defer_foreign_keys = ON` inside the transaction is the tool: it re-checks at `COMMIT`,
  so the corrections land together and the file is never left inconsistent.

Re-running a capture script and getting the same bytes is the check that it is deterministic:

```powershell
$a = (Get-FileHash tests/fixtures/db/vNNN_slug.sqlite).Hash
python tests/fixtures/db/capture_vNNN_slug.py
(Get-FileHash tests/fixtures/db/vNNN_slug.sqlite).Hash -eq $a
```

```powershell
# from server/, with the venv active, before writing the new migration
python tests/fixtures/db/capture_vNNN_slug.py
```

Then commit the file. Fixture databases are small and are meant to be committed - they are the
only record of what an older schema actually looked like.
