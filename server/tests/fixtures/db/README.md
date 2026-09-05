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
| `v003_phase3.sqlite` | 3 | A real Phase 3 project file: everything `v002` holds, plus a **bible with all four of its tables populated** - three live entries and one soft-deleted one, an entry made by *Add to bible* (so an anchor, an entry, and a citation written in one transaction), links in a symmetric and a directed relation, and a **retcon** that left its dependent flagged. Captured before `004_chat.sql` was written. Both soft deletes are deliberate: migration 004 is tested against a file with D22's *and* D25's predicates already in play, and with a review queue that a migration must not clear. |

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

Three things are easy to miss when writing one:

- **The migration runner stamps its own `applied_at` from the wall clock.** Pinning only the rows
  the script writes leaves the file different on every run; `schema_version` has to be normalised
  too. (`capture_v001_phase1.py`, the earlier example, does not do this — its output is stable in
  content but not byte for byte.)
- **Renaming a document id breaks the rows pointing at it** for the length of the rename.
  `PRAGMA defer_foreign_keys = ON` inside the transaction is the tool: it re-checks at `COMMIT`,
  so the corrections land together and the file is never left inconsistent.
- **Pinning every column that holds a timestamp is not enough when a column holds a document.**
  `entry_revision.snapshot_json` embeds the entry's whole state, and the revision a *soft delete*
  writes carries a `deleted_at` straight off the wall clock - so `capture_v003_phase3.py`
  normalises inside the JSON with `json_set` as well as across the columns. This was found by
  running the hash check below and not by reading the script (phase-4 plan § 7, `A6`).

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

The committed fixtures' hashes, for that check:

| File | SHA-256 |
|---|---|
| `v003_phase3.sqlite` | `798BE639F1036F9EA3A2C6688D710605596D185B4F0E1B4C1C1DEDCBE3E1A23A` |

Then commit the file. Fixture databases are small and are meant to be committed - they are the
only record of what an older schema actually looked like.
