# Test fixtures

Static inputs the suite reads. Nothing here is generated at run time except where a README in a
subdirectory says otherwise.

- `db/` - project files captured at a known schema version, for the migration tests (P1-3).
- `contract/` - JSON responses written by the backend suite and type-checked by the frontend
  suite, so a wire-shape change fails the tests rather than the browser (P1-8, not yet present).

Fakes - `FakeProvider`, `FakeEmbedder`, and friends - are code, not data, and live in
`tests/fakes/` (P1-8).
