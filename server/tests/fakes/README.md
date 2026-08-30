# Test fakes

Code that stands in for a collaborator the suite must not reach for real (outline § 8).

**Empty in Phase 1, deliberately.** Phase 1 has no collaborator to fake: SQLite runs for real
against `tmp_path`, and there is no provider, no embedder, and no network. The package exists now
so the later phases have an obvious home rather than inventing one under time pressure.

| Arrives | What | Why here |
|---|---|---|
| Phase 4 | `FakeProvider` — scripted completions and tool calls | Unit tests never touch a real model or a real API key |
| Phase 5 | `FakeEmbedder` — deterministic vectors | Same, and it makes retrieval assertions exact |

A fake is **code**; it lives here. Static data — database files at a known schema version, the
shared projection cases, the contract fixtures — is **data**, and lives in `../fixtures/`.

Two rules keep a fake honest:

- it implements the same port as the real adapter, so a test that passes against it is testing
  the real interface;
- it is scripted, never random, so a failure is reproducible from the test alone.
