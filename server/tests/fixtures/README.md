# Test fixtures

Static inputs the suite reads. **Data, not code** — fakes are code and live in `../fakes/`.

| Directory | What | Written by |
|---|---|---|
| `db/` | Project files captured at a known schema version, for the migration tests (P1-3, D20) | By hand, once, and committed |
| `projection/` | The shared projection cases both suites run against (P1-7, D18) | By hand — they are the specification |
| `contract/` | Representative API responses, type-checked by the frontend suite (P1-8) | `tests/test_contract.py`, on every run |

## `projection/cases.json`

Read by `tests/test_projection.py` here **and** by `web/src/__tests__/projection.test.ts` in the
browser suite. Both implementations must agree on every case, so a rule that changes on one side
and not the other fails a test instead of quietly disagreeing in a writer's table of contents
(D18).

Expected values are hand-written. They are what the projection is *supposed* to do, not a
recording of what it currently does — a fixture regenerated from the implementation could not
catch the implementation being wrong.

## `contract/`

Written by `tests/test_contract.py`: it drives the real routes, replaces ids and timestamps with
fixed placeholders, and writes the result. So:

- running `pytest` regenerates them, and `git diff` shows exactly what the wire shape did;
- a run that changed no shape produces **no diff at all**, because the varying parts are
  normalised away;
- `web/src/__tests__/contract.test.ts` reads the same files and checks them against the client's
  TypeScript types, which is what makes a backend shape change fail the suite rather than the
  browser.

Do not edit these by hand. Change the route or the schema, run the suite, commit the diff.
