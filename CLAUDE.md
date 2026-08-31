# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Archetype** — a browser-based workspace for writing and maintaining a long narrative, with an
AI agent that assists rather than authors. A rich-text manuscript editor sits in the center; an
outline panel (table of contents, narrative timeline, character interaction chart, story bible)
sits on one side; an agentic AI chat panel sits on the other. The writer selects text and asks
questions about it; the agent reads the manuscript, maintains a structured story bible, checks
continuity, and reports findings.

React + TypeScript frontend, Python (FastAPI) backend, one SQLite file per project holding
relational data plus keyword and vector indexes. Single user, localhost, Windows 11 primary.

Python package: `archetype`. Config/env namespace: `ARCHETYPE_`. The repository directory is
`WritingAssistant` — a path, not the product name.

**Current state: Phase 1 complete (2026-08-30); Phase 2 in progress — Group A (P2-1 → P2-4)
delivered.** All twenty-four decisions are resolved and binding: the writer ruled D21–D24 on
2026-08-30 as recommended, which also settles backlog `Q1` and `Q5`.

The app is a place you can write: create a project, add chapters, write formatted prose that
saves itself and survives a reload, and move around the manuscript by its headings. What exists
on the server: configuration and the secret guard, the project file schema at **version 2** with
its migration runner, the ID generator, the project store, the whole Phase 1 REST surface with
its uniform error envelope and structured request logging, the save protocol with the D19 version
guard, the text projection, the static mount that lets one process serve both the API and the
built app, and — new in Group A — **chapter reorder, soft delete, and restore; snapshots with
capture, history, and restore-through-the-save-path; and the `anchor` and `snapshot` tables.** On
the client: the three-region workspace with resizable keyboard-accessible dividers, the three
contexts and their pure reducers, the TipTap editor over a closed schema with autosave, the live
table of contents with jump-to-heading, the project picker, and error boundaries per region.

Every Phase 1 exit criterion is met, including the acceptance script run by hand against the
single-process build; the results are in [specs/phase-1-plan.md](specs/phase-1-plan.md) § 6.

**Group A is store-level and spec-level only. There are no new routes and no new UI**, which is
where the plan puts them: the chapter and snapshot routes arrive with the surfaces that use them
(`P2-11`, `P2-12`), so `web/` is untouched and the wire schemas are still Phase 1-shaped.
`specs/anchors.md` (`P2-4`) is written, in full, **before** the resolver it governs.

**Next: Group B (P2-5 → P2-8) — the block index, the resolver, the anchor store and its routes,
and the anchor test corpus.** There is no AI, no bible, and no search; there is an `anchor` table
and a status vocabulary, but **nothing resolves an anchor yet** — that is `P2-6`.

One thing that run surfaced, worth carrying forward: **the editor's visible failure states are
hard to reach from the app.** Stopping the server mid-edit did not produce a failed save the
writer could see — the retry loop absorbed the outage and the save landed when the server
returned. *Save failed*, the backoff ladder, and the `409` reload prompt are therefore exercised
only by `web/src/__tests__/editor.test.tsx` through the fake client. A regression in them will not
show up by using the app, so those tests are the only thing standing under them.

## The specs are the contract

- [specs/project-outline.md](specs/project-outline.md) — the root document: vision, architecture,
  phase list, testing strategy, risks. **Read this first.**
- [specs/development-phases.md](specs/development-phases.md) — the **authoritative decision
  register** (D1–D24) and the work breakdown across all phases. Cite these IDs.
- [specs/phase-1-plan.md](specs/phase-1-plan.md) — Phase 1 work items (`P1-1` … `P1-15`), exit
  criteria, and the as-built deviations table.
- [specs/phase-2-plan.md](specs/phase-2-plan.md) — Phase 2 work items (`P2-1` … `P2-15`). Its § 2
  is **ruled** (D21–D24, 2026-08-30). Group A's seven as-built deviations are in its § 7 and are
  worth reading before Group B — three of them change something the plan's later items assume.
- [specs/backlog.md](specs/backlog.md) — deferred features and open questions, each with the
  phase it must be settled by. `Q1` and `Q5` are promoted and closed; `Q2`, `Q3`, `Q4`, and `Q6`
  are open.
- [specs/data-model.md](specs/data-model.md) — storage as built at schema version 2: the project
  file, the four tables, the projection rules, the soft-delete predicate, and the migration
  discipline. Its § 7 sketches later phases and is **not** binding; the rest is a bug if it
  disagrees with the code.
- [specs/api-contract.md](specs/api-contract.md) — every route that exists, what it promises, and
  what it refuses. The generated OpenAPI schema is authoritative for types; this is authoritative
  for behaviour.
- [specs/anchors.md](specs/anchors.md) — what an anchor stores, the two coordinate systems and
  the block index, the matching ladder with its exact thresholds, the whitespace normal form, the
  suggestion protocol, and **what an anchor does not promise**. Written in `P2-4` before the code
  it governs; `P2-8`'s corpus is written from it, not from the implementation. Read it before
  touching anything in `manuscript/anchors/`.
- `specs/agent-tools.md` — written as its phase begins (Phase 6).

Work items carry stable IDs (`P3-4`) that commits and code comments reference. IDs are never
renumbered — a dropped item is marked **withdrawn**, not deleted.

## Rules

### Strongly Type All Variables and Parameters

- All variables in code must be typed, avoiding the use of super classes like `any` or `object` (unless strictly required).

### Present Options to User

- There may be mistakes in requirements or requests. Inform and ask for guiadance offering alternatives, and explaining why another method might be best. The user has final say in all matters.

### Keep the documents current

- **Any change to scope, architecture, phase boundaries, the data model, or a `D<n>` decision is
  recorded in `specs/project-outline.md` first**, then in the decision register, then in the
  affected phase plan, then here. Bump the version and date in a spec's header on every
  substantive edit.
- **Phase plans record as-built deviations.** When the code has to diverge from the plan, write
  down what actually happened and why — in that phase plan's deviations table, in the same
  change. A spec that describes something the code no longer does is a bug.
- **This file must describe the project as it currently is, never as it was planned.** When a
  phase completes, a dependency is added, a command changes, or an invariant is established,
  update `CLAUDE.md` in the same change.

### Testing

- Every phase adds tests. The suite must be green at every phase boundary, and a work item is
  not done without them.
- **A failing test is fixed before any other work continues — including a test the current work
  "shouldn't have touched."** Unrelated is a hypothesis, not an excuse; a failure means an
  assumption broke somewhere.
- **Never delete, skip, or loosen a test to get a green suite.** If a test genuinely asserts the
  wrong thing, fixing it is a deliberate change: correct the test and record what changed and
  why in the current phase plan.
- Unit tests never touch the network, a real LLM, or a real API key. A `FakeProvider` and
  `FakeEmbedder` back the backend suite; the frontend tests against a hand-written fake API
  client. Tests that require a live provider are marked `@pytest.mark.live` and excluded by
  default.
- Contract fixtures are shared JSON: the backend writes them, the frontend type-checks against
  them, so a wire-shape change fails the suite rather than the browser.
- AI *output quality* is not automatically tested in 1.0 — it is assessed by hand against
  scripted scenarios recorded in the phase plan.

### Design invariants

- **The writer owns the words.** The agent never mutates manuscript text or accepted bible
  records directly. It emits proposals and findings the user accepts, edits, or rejects, and a
  proposed text edit always shows an explicit before/after (D5, D12).
- **Every AI feature has a manual path first**, and the agent drives the same API the UI does.
- **No AI call outside the provider port.** No provider SDK is imported outside `llm/adapters/`;
  nothing above the port knows which provider is in play.
- **The agent never receives the whole manuscript.** Context is composed from an explicit
  selection, requested ranges, retrieval results, and bible entries, within token budgets, and
  the composed context is recorded on the run record.
- **Token spend is always a deliberate user act** (D13). No background AI work in 1.0.
- **Anchors are load-bearing.** A stored text reference keeps its quote plus surrounding context
  and is re-verified on load; an unresolvable anchor becomes `stale` and is surfaced, never
  silently re-pointed at the wrong passage.
- **The server owns the authoritative text projection** — `text_plain`, word count, and headings
  are derived server-side on save (D18). The client may mirror it for liveness, but the server
  answer wins.
- **Secrets are server-side only** (D8). API keys come from the environment, are never returned
  by any route, and never reach the browser or Git.
- **Wire and storage schemas are extension-only.** Add fields; never repurpose or remove one
  without a migration and a note in the phase plan. Migrations are numbered and forward-only,
  each shipping with a test that runs it against a fixture database from the previous version
  (D20).
- Keep the dependency surface small — every package must earn its place. No CSS framework, no
  component library, no state library (D10), no ORM.
- IDs are prefixed short tokens (`prj_`, `doc_`, `anc_`, `ent_`, `run_`); timestamps are UTC
  ISO-8601 everywhere, formatted only at the display edge.

## Commands

Real as of `P1-15`, and verified from a clean clone on Windows 11.

```powershell
# bootstrap (once)
cd server; python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd web; npm install

# run — two processes, two terminals. Hot reload; use this while developing.
cd server; .\.venv\Scripts\python.exe -m archetype     # API on 127.0.0.1:8787
cd web; npm run dev                                    # app on 127.0.0.1:5173, /api proxied

# run — one process. The shape the product ships in (P1-14, D7).
cd web; npm run build                                  # writes web/dist
cd server; .\.venv\Scripts\python.exe -m archetype     # API *and* app on 127.0.0.1:8787

# test and lint
cd server; .\.venv\Scripts\python.exe -m pytest
cd server; .\.venv\Scripts\python.exe -m ruff check .; .\.venv\Scripts\python.exe -m ruff format .
cd web; npm test; npm run typecheck; npm run build
```

The single-process mount is driven by `ARCHETYPE_WEB_DIST` (default `<repo>/web/dist`): it
installs when that directory holds an `index.html`, and is skipped with a log line when it does
not. Set it empty to never mount one — which is what the test suite does, so that no test's
behaviour depends on whether `npm run build` has been run.

Built and tested on Python 3.14 and Node 24; the declared floors are 3.11 and 20.

Settings layer defaults < `config.yaml` < `ARCHETYPE_*` env vars, env winning. Keys are
documented in the README; `ARCHETYPE_CONFIG_FILE` relocates the YAML layer, which is how the
suite keeps a developer's real config out of its way.

## Where things live

| Path | What |
|---|---|
| `server/archetype/config.py` | Settings layering and the `SecretStr` guard (`P1-2`, D8) |
| `server/archetype/ids.py` | Prefixed short-token IDs and `random_token` (`P1-3`) |
| `server/archetype/projects/db.py` | Connections, pragmas, explicit transactions, `utc_now` |
| `server/archetype/projects/migrations.py` | The forward-only migration runner (D20) |
| `server/archetype/projects/migrations/*.sql` | Numbered schema migrations |
| `server/archetype/projects/store.py` | `ProjectStore`, `ProjectHandle`, the directory scan (D17) |
| `server/archetype/manuscript/projection.py` | The pure text projection: rules, `text_plain`, headings, word count (`P1-7`, D18) |
| `server/archetype/manuscript/documents.py` | `DocumentStore` — the only path by which manuscript text changes (`P1-6`, D19), plus reorder, soft delete, and restore (`P2-2`, D22) |
| `server/archetype/manuscript/snapshots.py` | `SnapshotStore` — capture, history, and restore-as-an-ordinary-save (`P2-3`, D23) |
| `server/archetype/manuscript/anchors/status.py` | The anchor status vocabulary and the one rule that derives `orphaned` (`P2-1`, D22) |
| `server/archetype/manuscript/locator.py` | Resolves a bare document id to the project file holding it |
| `server/archetype/api/routes.py` | The `/api` router (`P1-5`) |
| `server/archetype/api/logging.py` | Request logging: one line per request, with a request id (`P1-13`) |
| `server/archetype/api/schemas.py` | Wire shapes, mirrored in `web/src/api/types.ts` |
| `server/archetype/api/static.py` | The single-process static mount and the `web_not_built` notice (`P1-14`) |
| `server/archetype/api/errors.py` | The uniform error envelope and its exception handlers |
| `server/archetype/app.py` | `create_app()`; builds the store and locator onto `app.state` |
| `server/tests/fixtures/db/` | Databases captured at a known schema version, with their README and the script that captured `v001_phase1.sqlite` |
| `server/tests/fixtures/projection/` | The shared projection cases — read by **both** suites (`P1-7`) |
| `server/tests/fixtures/contract/` | API responses written by pytest, type-checked by vitest (`P1-8`) |
| `server/tests/fakes/` | `FakeProvider` and `FakeEmbedder` land here in Phases 4 and 5 |
| `web/src/api/` | The typed client, its interface, and the mirrored wire types |
| `web/src/state/` | The three contexts and their pure reducers, plus toasts and `localStorage` (`P1-9`, D10) |
| `web/src/shell/` | The workspace frame, the split dividers, the editor region, error boundaries, toasts |
| `web/src/panels/` | The outline panel and its tabs, the table of contents, the agent placeholder, the picker |
| `web/src/editor/extensions.ts` | The closed TipTap schema — a change here is a spec change (`P1-10`, D1) |
| `web/src/editor/autosave.ts` | `SaveScheduler` — *when* a save happens, with no React in it (`P1-10`) |
| `web/src/editor/projection.ts` | The client mirror of the projection, held to the server by shared fixtures |
| `web/src/format.ts` | The display edge: the only place a UTC timestamp becomes words |
| `web/src/__tests__/fakes/` | The hand-written typed fake API client (`P1-8`) |
| `web/src/__tests__/harness.tsx` | The real provider stack with a fake client and a hurried autosave |
| `server/tests/test_static.py` | The run-mode tests; each builds its own miniature `dist` in `tmp_path` |
| `server/tests/test_chapters.py` | Reorder, delete, restore, and the soft-delete predicate across all four read paths (`P2-2`) |
| `server/tests/test_snapshots.py` | Capture, dedupe, retention, and restore (`P2-3`) |

**Invariants established in Phase 1's Groups A, B, and C, and in Phase 2's Group A**, beyond
those already listed above:

- **Transaction control is explicit.** Connections open with `isolation_level=None`; `BEGIN` and
  `COMMIT` are written, never implied. A migration carries its transaction *inside* the script
  text, because `executescript` commits whatever transaction is already open.
- **Looking at a project never changes it.** The directory scan and the document locator open
  files read-only; migrations run only on an explicit open. Reads made *through* an opened project
  use an ordinary connection — by then the file has been migrated deliberately, and a read-only
  handle cannot recover a write-ahead log left behind by an unclean shutdown.
- **A bad file in the projects directory is reported, not fatal.** `scan()` returns readable
  projects alongside skipped ones with a reason.
- **Secrets are unwritable, not just untested.** A `SecretStr` settings field that is not declared
  `Field(exclude=True)` raises at class-definition time, and the YAML layer refuses to supply one.
- **`DocumentStore.save_content` is the only path by which manuscript text changes.** Routes,
  tests, restoring a snapshot, and the agent's accepted proposals (D12) all go through it, which
  is what makes "the writer owns the words" structural rather than aspirational. Its `before_write`
  hook runs inside the save's transaction, after the version guard and before the row is
  overwritten; it exists so a `pre-restore` snapshot and the write it protects are one atomic act,
  and it is **not** a second way to write text.
- **A rejected save has written nothing.** Validation, the size check, and the projection all run
  before the transaction opens; the version guard is re-read under the write lock inside it.
- **A rename does not bump `version`, and neither does a reorder, a delete, or a restore.** None
  of them is a text edit, and invalidating an in-flight autosave over one would cost the writer a
  keystroke. A reorder does not move any document's `updated_at` either — the order belongs to the
  project, not to a chapter.
- **Deleting a chapter is a soft delete, and `deleted_at IS NULL` is the whole of it.** The row,
  its text, its snapshots, and its anchors all stay. Every read filters on that one predicate —
  `list_meta`, `get`, `outline`, and the project summary's counts — and one test asserts absence
  from all four together, because a query that forgets it surfaces as a wrong word count and gets
  reported as a different bug. The summary's copy is version-gated: the scan reads unmigrated
  files, and a version-1 file has no such column.
- **`orphaned` is derived from `deleted_at`, never stored.** `anchor.status` holds the resolver's
  text answer only (`ok` or `stale`), and `effective_status` refuses a stored `orphaned` rather
  than passing it through. A soft delete changes no text, so delete and restore write nothing at
  all to anchor rows and a restored chapter's anchors are exactly as they were.
- **A reorder must present the complete live set.** That comparison *is* the concurrency guard,
  which is why no project-level version column exists: a client on a stale chapter list cannot
  produce a complete set, so it cannot reorder a chapter out of existence.
- **Automatic snapshots are deduplicated and pruned; deliberate ones are not.** `handover` is the
  only one nobody asked for. A `manual` mark carries a label, and a `pre-*` snapshot is a recovery
  guarantee rather than a history entry — deduplicating one against a `handover` would leave the
  only copy of destroyed text in the prunable pool.
- **A `pre-*` snapshot is written inside the transaction of the thing it protects against**, so a
  refused delete or a restore refused as stale leaves nothing behind — not even the snapshot that
  was about to protect it.
- **Routes carry no domain logic and stores carry no HTTP.** Domain exceptions are translated to
  the envelope by handlers in `api/errors.py`, so the same store serves a request and an agent run.
- **The projection is one specification, two implementations.** The rules live in the docstring of
  `manuscript/projection.py`; `server/tests/fixtures/projection/cases.json` drives both, so drift
  fails a test rather than confusing a table of contents.
- **The contract fixtures are generated, normalised, and committed.** `pytest` rewrites them with
  ids and timestamps replaced by placeholders, so a run that changed no shape produces no diff and
  a run that did shows exactly what changed — and the frontend suite type-checks the same files.
- **The editor schema is a closed list, and a test enforces it.** `web/src/editor/extensions.ts`
  declares every node and mark, and `schema.test.ts` compares that declaration to the schema
  TipTap actually built. Adding a node is a spec change — amend the P1-10 list and the constant
  together — because each one is a case anchors, chunking, and Markdown export must each handle.
- **Nothing switches chapters over unsaved work.** `openDocument` flushes first and, if the flush
  did not leave the document clean, refuses to switch and says so. A failed save keeps the
  content and retries with backoff; a `409` stops the loop and offers the server's copy — it
  never merges, and typing on does not sneak past it (D19).
- **The save loop reads a ref; the screen reads the reducer.** Both are advanced by the same pure
  reducer through one function in `DocumentContext`, because a `useReducer` state is not readable
  synchronously after a dispatch and a save presenting a stale `version` would be refused as a
  conflict the client itself caused.
- **Reducers are pure and hold no `localStorage`, no client, and no DOM.** Persistence is an
  effect in the provider, so every rule P1-9 cares about is testable without a browser.
- **Every value read back from `localStorage` is validated field by field.** A layout, an open
  project, or a recent-projects list that cannot be read is forgotten, never repaired — none of
  it is manuscript data, and none of it is worth failing over.
- **Jump-to-heading resolves by ordinal, and only by ordinal — permanently.** Phase 2 adds
  anchors *alongside* it and does not replace it. A heading is a structural position the
  projection already numbers exactly and re-derives on every save; anchors are for cited passages
  that no derived structure names. Minting an anchor row per heading on every save, to reproduce
  an answer that is already free, is what the earlier "seam Phase 2 replaces" reading would have
  cost (phase-2-plan § 2, ruling 1).
- **Each region has its own error boundary.** A panel that cannot draw takes itself down and
  leaves the editor — which may be holding the only copy of a sentence — working.
- **Every request is logged once, with a request id**, and that id is the only thing a `500`
  tells the browser. The traceback stays in the log.
- **The static mount is registered last, and the API can never be shadowed.** Starlette matches
  routes in order, so a bundle holding `api/health` loses to the route of the same name — asserted
  by a test, because it is the kind of thing that works by accident until someone reorders
  `create_app`. A path under the mount that matches no file returns the 404 envelope, never
  `index.html`: the client has no router, so a fallback would turn a typo into a blank page.
- **No test's behaviour depends on whether the frontend has been built.** The shared `settings`
  fixture pins `web_dist=None`, and `test_static.py` builds its own miniature bundle in `tmp_path`.
  A stale real `web/dist` must not be able to make a passing test lie.
