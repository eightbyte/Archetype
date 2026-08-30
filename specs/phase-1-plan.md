# Phase 1 — Skeleton & Editor

**Status:** In progress — **Group A (P1-1 → P1-4) complete** · **Version:** 1.1 · **Date:** 2026-08-29
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1

---

## 1. What this phase is for

Phase 1 makes Archetype a place you can actually write. At the end of it you can create a
project, add chapters, write and format prose that saves itself and survives a reload, and move
around the manuscript by its headings. There is no AI in this phase, no bible, and no anchors.

That restraint is the point. The three hardest things in this project — anchors, retrieval, the
agent loop — all sit on top of the document store, the text projection, and the editor. Phase 1
is where those foundations get built carefully, with tests, while they are still small enough to
change cheaply.

**The load-bearing choices in this phase** are the document record shape, the text projection
(D18), and the save protocol (D19). Anchors in Phase 2 rebase against positions in the editor
document; chunking in Phase 5 chunks the projection; the agent in Phase 6 reads both. Getting
these wrong is expensive later, so they get more test attention than their size suggests.

### Non-goals for Phase 1

Named explicitly, because each is a plausible thing to drift into:

- **No anchors.** Jump-to-heading uses heading identity, not stored ranges (P1-11). The anchor
  record does not exist yet.
- **No chapter reorder or delete.** Create, rename, and open only. Reorder, delete, and snapshots
  are Phase 2, where they arrive together with the snapshot safety net that makes deletion safe.
- **No bible, no search, no LLM, no WebSocket.** Not even a stub route.
- **No production packaging.** A static-file mount exists (P1-14) so a built frontend can be
  served from one process, but installers, service registration, and the "clean clone in 15
  minutes" bar are Phase 9.
- **No styling investment beyond legibility.** A writing surface must be pleasant to look at, so
  typography gets real attention; everything else stays plain until Phase 9.

---

## 2. Confirm before code

These are the D17–D20 rulings derived at Phase 0 close-out, plus the small conventions that are
awkward to change once files exist. Overriding any of them now costs nothing; overriding them in
Phase 3 is a migration.

| | Ruling | Where it bites if wrong |
|---|---|---|
| **D17** | Projects are discovered by scanning `data/projects/*.sqlite` — no registry file | The picker and project-creation flow (P1-4, P1-12) |
| **D18** | The server owns the authoritative text projection and heading list | The TOC, and every later consumer of `text_plain` (P1-7) |
| **D19** | Documents carry a `version`; a stale save gets a `409` | The save protocol and the autosave client (P1-6, P1-10) |
| **D20** | Forward-only numbered SQL migrations, no ORM | Every schema change from here on (P1-3) |
| — | Package `archetype`, env prefix `ARCHETYPE_`, default port **8787** | Config keys, imports, docs |
| — | Python **3.11+**, Node **20+** | Toolchain |
| — | Content is stored as **TipTap/ProseMirror JSON**, not HTML or Markdown | The document record; Markdown is an import/export format only (D15) |

---

## 3. Work Items

Fifteen items in four groups. Each is independently reviewable. The **Done when** line is the
acceptance bar — an item without its tests is not done (outline § 8).

### Group A — Foundations (P1-1 → P1-4)

---

**P1-1 · Repository scaffold and toolchain**

Create the two-sided layout from outline § 10: `server/` (Python package `archetype`) and `web/`
(Vite + React 18 + TypeScript). Add `.gitignore` covering `data/`, `config.yaml`, `__pycache__/`,
`.venv/`, `node_modules/`, and `dist/`. Add a README with the bootstrap and run commands.

Dependency budget, held deliberately tight (outline § 1):

| Side | Runtime | Dev / test |
|---|---|---|
| server | `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `pyyaml` | `pytest`, `pytest-asyncio`, `httpx` (test client), `ruff` |
| web | `react`, `react-dom`, `@tiptap/react`, `@tiptap/starter-kit` | `vite`, `typescript`, `vitest`, `@testing-library/react`, `@testing-library/user-event`, `jsdom` |

No CSS framework, no component library, no state library (D10), no ORM (D20). Anything not on
this list is an argument to be made in review, not a default.

*Done when:* a clean clone reaches a running server and a running dev frontend by the documented
commands, and both empty test suites run green.

---

**P1-2 · Configuration and secrets**

`archetype/config.py` — a `pydantic-settings` model layering **defaults < `config.yaml` < `ARCHETYPE_*`
environment variables**, with env winning so a shell can always override a file.

Phase 1 keys: `data_dir`, `host` (default `127.0.0.1`), `port` (default `8787`), `log_level`.
Provider and embedding keys arrive in Phases 4 and 5, but the secrets *discipline* is established
now: **secret-valued settings are read from the environment only, are excluded from every
serialization of the settings object, and are never exposed by any route** (D8). Add a test that
asserts a secret-typed field does not appear in the settings dump — the guard exists before there
is a secret to guard, so Phase 4 cannot quietly regress it.

Binding to `127.0.0.1` is the default and is documented as a deliberate posture, not an oversight
(D7).

*Done when:* layering resolves in the documented precedence with tests at each layer; the
secret-exclusion test passes; every key is documented in the README.

---

**P1-3 · Project file, schema, and migration runner**

One SQLite file per project (D3). A migration runner applies numbered, forward-only SQL migrations
on open and records them in `schema_version` (D20).

Migration `001_init.sql` creates only what Phase 1 needs:

```
schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)

project(id TEXT PRIMARY KEY,          -- prj_…
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,     -- UTC ISO-8601
        updated_at TEXT NOT NULL,
        settings_json TEXT NOT NULL DEFAULT '{}')

document(id TEXT PRIMARY KEY,         -- doc_…
         project_id TEXT NOT NULL REFERENCES project(id),
         order_index INTEGER NOT NULL,
         title TEXT NOT NULL,
         kind TEXT NOT NULL DEFAULT 'chapter',
         content_json TEXT NOT NULL,
         text_plain TEXT NOT NULL,     -- derived, D18
         headings_json TEXT NOT NULL,  -- derived, D18
         word_count INTEGER NOT NULL,
         version INTEGER NOT NULL,     -- concurrency guard, D19
         created_at TEXT NOT NULL,
         updated_at TEXT NOT NULL)
```

Connection handling: `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout`. Later phases
add tables; they never repurpose these columns (outline § 7).

Also here: the ID generator — prefixed short tokens (`prj_`, `doc_`) from a collision-resistant
alphabet, with a test for prefix correctness and uniqueness across a large batch.

*Done when:* a fresh file migrates to current; re-opening is a no-op; a fixture database at
version 0 migrates forward in a test (the pattern every later migration follows); IDs are tested.

---

**P1-4 · Project store and project-scoped access**

The repository layer over the project file: create a project (file + `project` row), open one,
list all by scanning `data/projects/` and reading each project row (D17), with a resolved handle
that every later service takes as its scope.

Project files are named from a slug of the title plus a short suffix for uniqueness, so the
directory is human-readable and a file copy is a portable project.

*Done when:* create / open / list are tested against `tmp_path`, including a directory holding
a non-Archetype `.sqlite` file (skipped, not crashed) and a project file from a copied-in backup
(listed correctly).

---

### Group B — API and text projection (P1-5 → P1-8)

---

**P1-5 · Project and document REST routes**

FastAPI app with a `/api` router, pydantic request/response models, and a uniform error envelope
`{"error": {"code", "message", "detail"}}`.

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/projects` | List — id, title, chapter count, word count, `updated_at` |
| `POST` | `/api/projects` | Create |
| `GET` | `/api/projects/{pid}` | One project with its document list |
| `GET` | `/api/projects/{pid}/documents` | Ordered metadata **without** `content_json` |
| `POST` | `/api/projects/{pid}/documents` | Create a chapter, appended at the end |
| `GET` | `/api/documents/{did}` | Full document including content |
| `PUT` | `/api/documents/{did}/content` | Save (P1-6) |
| `PATCH` | `/api/documents/{did}` | Rename |
| `GET` | `/api/projects/{pid}/outline` | The stitched TOC across all chapters (P1-7) |

The document-list route deliberately omits content: the outline panel must never pull the whole
manuscript to draw a chapter list, and that discipline starts here.

*Done when:* every route has a happy-path and a not-found test; the error envelope is uniform;
OpenAPI generates cleanly.

---

**P1-6 · The save protocol**

`PUT /api/documents/{did}/content` takes `{content_json, version}` and, in one transaction:
validates the payload, derives the projection (P1-7), increments `version`, writes, and returns
the new `version` plus the derived `word_count` and headings.

If the presented `version` is not the stored one, it writes nothing and returns **`409`** with the
current version and `updated_at` (D19). The client warns and offers reload; it never merges.

This route is the only path by which manuscript text changes, which is what makes "the writer owns
the words" enforceable rather than aspirational — the constraint is structural, and D12 later
rides on it.

*Done when:* a correct save increments the version and returns the derived fields; a stale save
returns `409` and leaves the row untouched (asserted by reading it back); an oversized or
malformed payload is rejected before any write.

---

**P1-7 · Text projection and heading extraction**

A pure module — ProseMirror document JSON in, `(text_plain, headings, word_count)` out — with no
database or framework imports. This is the most-reused code in the project (D18): the TOC reads
it now, chunking reads it in Phase 5, and agent context composition reads it in Phase 6.

- `text_plain` — block-aware plain text with paragraph separation preserved, so later chunking
  can split on real boundaries rather than guessing.
- `headings` — an ordered list of `{level, text, ordinal}`, where `ordinal` is the index of the
  heading among all headings in the document, giving jump-to-heading a stable target before
  anchors exist (P1-11).
- `word_count` — one definition, used everywhere, documented in the docstring.

The client has a small mirror of this for live TOC updates on the open document; the server
answer wins on save (D18). A shared fixture set drives both implementations so drift shows up as
a test failure rather than a confusing TOC.

*Done when:* the pure function is tested against fixtures covering nesting, empty documents,
formatting marks inside headings, blockquotes, lists, and scene-break rules; the client mirror
agrees with the server on every shared fixture.

---

**P1-8 · Test harness, both sides**

The scaffolding every later phase builds on — worth doing properly once.

- **Backend:** `conftest.py` with a `tmp_path` project fixture, a migrated-database fixture, an
  `httpx`-based API client fixture, and factory helpers (`make_project`, `make_document`).
  `tests/fakes/` and `tests/fixtures/` exist with a README explaining what belongs in each.
- **Frontend:** Vitest + RTL + jsdom, plus a **hand-written typed fake API client** implementing
  the same interface as the real one (outline § 8 — no MSW, no extra dependency).
- **Contract fixtures:** a pytest test serializes representative responses to
  `tests/fixtures/contract/*.json`; a Vitest test loads the same files and type-checks them
  against the client types. A backend shape change then fails the frontend suite rather than the
  browser. This is small in Phase 1 and load-bearing from Phase 4.

*Done when:* both suites run green from the documented commands; the fake client backs at least
one real component test; the contract fixtures round-trip.

---

### Group C — The application (P1-9 → P1-13)

---

**P1-9 · Application shell and state**

Three resizable regions — outline panel, editor, agent panel — with hand-rolled split dividers
(keyboard-accessible, not mouse-only), collapse/expand, and pane widths persisted to
`localStorage`. The agent panel renders a "coming in Phase 4" placeholder; the region exists now
so the layout is never retrofitted around it.

State is React context + `useReducer` (D10), split by lifetime rather than by screen:
`ProjectContext` (current project, document list), `DocumentContext` (open document, dirty state,
save status), `UiContext` (pane sizes, active outline tab). Reducers are pure and unit-tested
apart from React.

*Done when:* panes resize, collapse, and persist across reload; reducers have direct tests;
layout holds at 1280px and at 1920px.

---

**P1-10 · Editor integration and autosave**

TipTap with a deliberately narrow schema (D1): paragraph, headings 1–3, bold, italic, blockquote,
bullet and ordered lists, horizontal rule as scene break, undo/redo. Nothing else — every node
type is a case that anchors, chunking, and Markdown export must each handle, so the schema stays
small until something earns its way in.

Autosave, which is where a writer either trusts the app or does not:

- debounced save after ~1.5s idle, and on blur;
- a **forced flush before switching documents, before navigating, and on `beforeunload`** —
  switching chapters with unsaved changes must be impossible, and this gets an explicit test;
- a visible status indicator: *saving* / *saved* / *unsaved changes* / *save failed*;
- failure is loud and non-destructive — the editor keeps the content, retries with backoff, and
  says so; a `409` (D19) surfaces a reload prompt rather than a silent overwrite.

*Done when:* the formatting set round-trips through save and reload; a document switch with
pending edits flushes first (tested); a simulated save failure preserves content and shows the
failed state; a simulated `409` prompts rather than clobbers.

---

**P1-11 · Table of contents and jump-to-heading**

The Contents tab: chapters in order, each expanding to its heading tree, with word counts. It is
built from `GET /api/projects/{pid}/outline`, so it spans the whole manuscript while only one
document is loaded (D2). For the open document it updates live from the client mirror (P1-7).

Clicking a heading in another chapter opens that document (flushing any pending save first) and
scrolls to the heading; clicking within the open document scrolls immediately. Targets resolve by
heading `ordinal` — anchors do not exist yet (P1-11 is explicitly pre-anchor), and this is the
seam that Phase 2 replaces.

*Done when:* the TOC renders across multiple chapters; a cross-chapter jump loads and scrolls
correctly; the TOC updates as headings are typed in the open document.

---

**P1-12 · Project picker and creation**

The entry screen (D6): existing projects with title, chapter count, word count, and last-modified,
plus create-a-project and a recent-projects shortcut. Creating a project seeds it with one empty
chapter, so a new project opens into a writable editor rather than an empty state.

*Done when:* create → opens into an editor with one chapter; the list reflects a project created
outside the app (a copied file); a corrupt or unreadable file is reported without taking down the
list.

---

**P1-13 · Error surfaces and logging**

Server: structured request logging at the configured level, an exception handler producing the
uniform envelope, and no stack traces in responses. Client: an error boundary around each region
so one failing panel does not blank the workspace, plus a small toast for transient failures.

Modest by design — Phase 9 hardens this properly — but a Phase 1 without it debugs by guesswork.

*Done when:* an unhandled server exception returns the envelope and logs a traceback server-side;
a thrown render error in one panel leaves the other two usable.

---

### Group D — Close-out (P1-14 → P1-15)

---

**P1-14 · Dev and single-process run modes**

Dev is two processes: `uvicorn` on 8787, Vite on 5173 with `/api` proxied. Also add an optional
static mount so a built `web/dist` is served by the same FastAPI process at
`http://127.0.0.1:8787` — the real target shape (D7), verified early rather than discovered in
Phase 9. Both paths documented in the README with copy-pasteable Windows commands.

*Done when:* both modes work from a clean clone on Windows 11; the built app loads and saves
through the single-process path.

---

**P1-15 · Documentation and phase close-out**

- `CLAUDE.md` — fill in the real bootstrap, run, test, and lint commands (its Commands section is
  a placeholder until this item lands), record Phase 1 as complete, and note any invariant this
  phase established.
- `specs/data-model.md` — created here, documenting the Phase 1 tables as implemented and the
  rest as planned.
- `specs/api-contract.md` — created here, covering the Phase 1 routes.
- **As-built deviations** — anything that diverged from this plan is written into § 6 below in
  the same change that diverged (outline § 13). A spec describing something the code no longer
  does is a bug.

*Done when:* all four documents match the code; a reader who has never seen the project can go
from clone to writing using only the README.

---

## 4. Exit Criteria

Phase 1 is done when **all** of these hold:

1. Create a project, add three chapters, write formatted prose in each, close the browser, reopen
   — everything is exactly as it was left.
2. The TOC shows all three chapters with their headings; clicking any heading navigates there,
   including across chapters.
3. Switching chapters with unsaved changes never loses a keystroke.
4. A stale save is refused with a `409` and a reload prompt, not a silent overwrite (D19).
5. `pytest` and `vitest` are both green, and the projection module (P1-7) and save protocol (P1-6)
   have tests covering their edge cases, not just their happy paths.
6. Both run modes work from a clean clone on Windows 11 by the documented commands.
7. `CLAUDE.md`, `README.md`, `specs/data-model.md`, and `specs/api-contract.md` describe the code
   as built.

**Manual acceptance script** (run by hand at the phase boundary, results recorded in § 6):
create project "Test Manuscript" → three chapters with H1/H2 headings and mixed formatting →
type ~2000 words across them → reload mid-sentence → jump between chapters via the TOC → rename a
chapter → stop the server mid-edit and confirm the failure state is honest and non-destructive.

---

## 5. Risks in this phase

| Risk | Mitigation |
|---|---|
| **TipTap schema grows by accident.** Every node type is a case anchors, chunking, and export must handle. | The P1-10 schema is a closed list. Adding a node is a spec change, not a commit. |
| **Autosave loses work on a document switch.** The single most damaging Phase 1 bug. | Forced flush before switch/navigate/unload, with an explicit test (P1-10). |
| **The projection drifts between client and server**, so the TOC disagrees with the stored text. | One shared fixture set drives both implementations (P1-7). |
| **Scope leaks toward anchors** because jump-to-heading feels one step away. | P1-11 resolves by heading ordinal only. The anchor record does not exist until Phase 2. |
| **Windows path and encoding trouble** (SQLite paths, UTF-8, CRLF) surfaces late. | Windows 11 is the primary target; tests run there from P1-1, and text handling is UTF-8 end to end. |

---

## 6. As-Built Deviations

*Every divergence from this plan is recorded here in the same change that makes it, with what
happened and why (outline § 13).*

### Group A (P1-1 → P1-4), 2026-08-29

| Item | Planned | As built | Why |
|---|---|---|---|
| P1-1 | Web dependency budget lists `react`, `react-dom`, `@tiptap/react`, `@tiptap/starter-kit` | Added `@tiptap/pm` | A required peer dependency of `@tiptap/react` v2 — ProseMirror itself. Declared explicitly rather than left to npm's peer auto-install, so the lockfile is honest about it. |
| P1-1 | Web dev budget lists `vite`, `typescript`, `vitest`, `@testing-library/react`, `@testing-library/user-event`, `jsdom` | Added `@vitejs/plugin-react`, `@types/react`, `@types/react-dom`, `@testing-library/dom` | The plugin is how Vite compiles JSX and does React fast refresh; without it React + Vite does not build. The two `@types` packages are the type surface of runtime dependencies already budgeted. `@testing-library/dom` is a required peer of `@testing-library/react` v16. All four are tooling for budgeted choices, not new capability. |
| P1-1 | Vitest, unversioned | Vitest 3 with Vite 6 | Vitest 2 pins Vite 5 and installs a second copy of Vite, which breaks `tsc` on the config's `test` block. Matching majors keeps one Vite in the tree. |
| P1-1 | The FastAPI app is P1-5 | A minimal `archetype/app.py` with `create_app()` and `GET /api/health` landed in Group A | "A clean clone reaches a running server" is P1-1's acceptance bar and is not checkable without an app to run. The `/api` router, the pydantic models, and the uniform error envelope remain P1-5; the static mount remains P1-14. |
| P1-1 | — | The Group A frontend calls `GET /api/health` and reports the result | Proves the toolchain end to end — Vite's `/api` proxy actually reaches uvicorn. It is not the typed API client; that is P1-8, and this call is deliberately a single function with a locally stubbed `fetch` in its test. |
| P1-2 | D8 permits secrets in a gitignored `config.yaml`; P1-2 says environment only | Environment only, enforced: the YAML source strips any key naming a `SecretStr` field | P1-2 is the stricter reading of a permission D8 grants but does not require, so no decision changes. Recorded because the two documents can be read as differing. |
| P1-2 | "Add a test that asserts a secret-typed field does not appear in the settings dump" | Also a build-time guard: a `SecretStr` field not declared `Field(exclude=True)` raises `TypeError` at class definition | A test catches the regression; the guard makes it unwritable. Phase 4 adds provider keys to this class, which is exactly when a quiet regression would happen. |
| P1-3 | The `001_init.sql` DDL as listed | Added `CREATE INDEX idx_document_project_order ON document(project_id, order_index)` | The document list and the outline both read one project's chapters in order. Deliberately not `UNIQUE`: Phase 2 reorder needs to move rows through transient duplicate indices. |
| P1-3 | "A migration runner applies numbered, forward-only SQL migrations" | Each migration's `BEGIN`/`COMMIT` is written into the script text rather than issued around it | `sqlite3.Cursor.executescript` commits any open transaction before it runs, so a transaction opened outside the script would be closed by the very call it was meant to protect — the migration would apply statement by statement and could half-land. |
| P1-3 | ID generator | Added `random_token(length)` beside `new_id(prefix)` | The project filename suffix is a disambiguator, not an identity. Keeping it out of `new_id` lets IDs keep their 8-character minimum instead of relaxing it for a filename. |
| P1-4 | "list all by scanning `data/projects/`" | `ProjectStore.scan()` returns readable projects **and** a list of skipped files with reasons; `list_projects()` returns just the projects | P1-12 requires that a corrupt or unreadable file be reported without taking down the list. The reason has to survive the scan for the picker to say anything useful about it. |
| P1-4 | Handle exposes project identity | `ProjectSummary` also carries `chapter_count`, `word_count`, and `schema_version` | `GET /api/projects` (P1-5) and the picker (P1-12) need exactly these; they are one aggregate query on a file already open. The scan opens files **read-only** so listing never migrates or mutates a project. |

**Toolchain note.** Built and tested on Python 3.14 and Node 24. The declared floors stay 3.11 and
20 per § 2; nothing in the code uses an API newer than 3.11.

**Not yet done in Group A.** `specs/data-model.md` and `specs/api-contract.md` are P1-15, and the
`CLAUDE.md` Commands section is filled in provisionally — P1-15 finalises it at phase close.
