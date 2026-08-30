# Database fixtures

One database file per schema version, used by the migration tests (P1-3, D20).

Every migration ships with a test that runs it against a fixture database captured at the
**previous** version. That is what makes forward-only migrations safe to trust: the test proves
the migration works on a file that predates it, not just on one this build created.

| File | Version | What it is |
|---|---|---|
| `v000_empty.sqlite` | 0 | A zero-byte file. SQLite treats it as a valid, empty database - which is exactly the state a project file is in before `001_init.sql` runs. |

## Capturing the next one

Before writing migration `00N`, capture the current schema as `v<N-1 zero-padded>_<slug>.sqlite`:

```powershell
# from server/, with the venv active
python -c "from pathlib import Path; from archetype.projects import open_migrated; open_migrated(Path('tests/fixtures/db/v001_phase1.sqlite')).close()"
```

Add a few representative rows by hand if the migration touches data rather than only structure,
then commit the file. Fixture databases are small and are meant to be committed - they are the
only record of what an older schema actually looked like.
