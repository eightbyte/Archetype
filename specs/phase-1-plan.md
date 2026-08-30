# Phase 1 — Skeleton & Editor

**Status:** In progress — **Groups A, B, and C (P1-1 → P1-13) complete** · **Version:** 1.3 · **Date:** 2026-08-30
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
bullet and ordered lists, horizontal rule as scene break, **hard break**, undo/redo. Nothing else
— every node type is a case that anchors, chunking, and Markdown export must each handle, so the
schema stays small until something earns its way in.

> **Amended 2026-08-30 (Group C).** `hardBreak` was added to the closed list by the writer's
> ruling. Verse, epigraphs, and an address block are one block with line breaks in them, not a
> run of paragraphs, and forcing them into paragraphs would misrepresent the text to every later
> consumer of the projection. The projection already had a rule for it on both sides (P1-7), so
> nothing downstream changes; what changes is that the editor can now produce one. The list in
> `web/src/editor/extensions.ts` is checked against the built TipTap schema by a test, so this
> list and the code cannot drift apart silently.

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

### Group B (P1-5 → P1-8), 2026-08-30

**Decisions of record.** The plan asks for a text projection and names the cases it must cover,
but the *rules* were left open. They are load-bearing — chunking reads them in Phase 5 and agent
context composition in Phase 6 — so they are written down in the module docstring of
`server/archetype/manuscript/projection.py` and summarised here:

- **Blocks.** Paragraphs and headings are text blocks; containers (blockquote, lists, list items)
  are walked through and contribute nothing of their own. An empty block is dropped, so exactly
  one blank line separates blocks and later chunking can split on real boundaries.
- **No decoration.** No bullets on list items, no marker on blockquotes, no marks. `text_plain` is
  what the words are, not what they look like.
- **A scene break is text.** `horizontalRule` projects as its own block reading `* * *`. It is a
  real narrative boundary, and a chunker that could not see it would cut across a scene change.
  It contributes no words.
- **Headings include the empty ones**, and `ordinal` is the index among all heading nodes in
  document order, from zero. That makes an ordinal mean "the Nth heading node in this document" —
  what P1-11 resolves against. Skipping empty headings would renumber every heading below the one
  being typed.
- **A word** is a run of Unicode letters and digits, optionally joined by apostrophes or dashes,
  counted over `text_plain` with headings included. `* * *` and `--` are zero words.
- **Unknown node types are projected, not rejected.** The TipTap schema is a closed list enforced
  where documents are authored (P1-10); a projection that threw would turn a schema question into
  lost text.

| Item | Planned | As built | Why |
|---|---|---|---|
| P1-5 | `GET /api/projects` returns id, title, chapter count, word count, `updated_at` | Also returns `created_at`, and a second list, `skipped`, of files that are not usable projects | P1-12 requires a corrupt or unreadable file to be reported without taking down the list. `ProjectStore.scan()` already carried the reason (Group A); this is the route that surfaces it. |
| P1-5 | `POST /api/projects` — "Create" | Creates the project **and seeds one empty chapter**, returning the same body as `GET /api/projects/{pid}` | P1-12 requires that a new project open into a writable editor rather than an empty state. Doing it in the route makes that true for every client, including the agent later, rather than being a property of one UI flow. |
| P1-5 | Routes for documents addressed as `/api/documents/{did}` | Added `manuscript/locator.py`, which resolves a bare document id to the project file holding it | Storage is one file per project (D3) but the planned route names no project, so something has to answer "which file". The answer is cached; the cache is a hint, re-confirmed on every use, so a project file moved behind the app's back costs a wasted scan and never a wrong read or write. |
| P1-5 | `GET /api/documents/{did}` — "Full document including content" | Returns `content_json` and the derived `headings` and `word_count`, but **not** `text_plain` | `text_plain` is derived from `content_json` by rules the client mirrors (P1-7), so sending it would double the size of every chapter load to carry something the client can compute. Extension-only rules allow adding it later if a consumer needs the server's exact string. |
| P1-5 | Uniform error envelope | Domain exceptions are translated by FastAPI exception handlers, not caught per route; every route stays free of HTTP vocabulary | The same store is called by the agent loop in Phase 6, which is not serving a request. Keeping status codes out of the store is what lets one implementation serve both. |
| P1-5 | — | Request models are `extra="forbid"`; an undeclared field is a `422` | Wire schemas are extension-only in the *server's* favour: the server may add fields, but a client sending one the server does not know is a client bug, and silence would hide it until Phase 4. |
| P1-5 / P1-13 | An exception handler producing the envelope is P1-13 | The catch-all handler landed here | "The error envelope is uniform" is P1-5's acceptance bar and is not checkable while an unhandled exception still returns Starlette's plain-text `500`. P1-13 keeps structured request logging and the client-side error boundaries. |
| P1-5 | — | A `404` names the id that was asked for and nothing else; the store's message, which carries the projects directory, goes to the log | The browser has no business knowing the writer's directory layout, and the log is where that detail is actually useful. |
| P1-5 | `GET /api/health` lives in `app.py` (Group A) | Moved into the `/api` router with the rest | It is an `/api` route; leaving it defined in the factory would have made the router an incomplete description of the API surface. Behaviour and path are unchanged. |
| P1-6 | "An oversized or malformed payload is rejected before any write" | `MAX_CONTENT_BYTES` = 2 MiB per document, refused with `413` and a `detail` carrying the size and the limit | The plan requires the rejection but names no limit. A 20,000-word chapter is roughly 300 KB of ProseMirror JSON, so two megabytes is generous for a chapter and still refuses a payload that would take the process down. |
| P1-6 | A stale save gets a `409` | The guard is **equality**, not "at least": a version ahead of the stored one is refused too | A client cannot get ahead of the store except by inventing a version. Accepting it would let a bug skip the guard entirely. |
| P1-6 | — | `PATCH /api/documents/{did}` (rename) deliberately does **not** bump `version` | A rename is not a text edit. Bumping the version would invalidate an in-flight autosave and cost the writer a keystroke over a cosmetic change — the exact failure P1-10 exists to prevent. |
| P1-6 | — | Every document write stamps `project.updated_at` in the same transaction | The picker sorts on it (P1-12). A project whose chapter changed a minute ago must not claim it was last touched when it was created. |
| P1-7 | A pure module, no database or framework imports | Also validates structure — shape, node types being strings, `attrs` being objects, nesting depth ≤ 64 — and raises `InvalidDocumentError` | The save protocol needs "rejected before any write" to happen somewhere, and the projection is the one place that already walks every node. The client mirror deliberately does **not** validate: throwing there would blank the outline panel over a node nobody has taught it yet. |
| P1-7 | The client mirror agrees with the server on every shared fixture | The mirror uses `\p{L}\p{N}` where Python uses `[^\W_]` | JavaScript's `\w` is ASCII-only even under the `u` flag, so the obvious spelling would have counted "naïve" as two words where Python counts one. The shared cases include a non-ASCII case that fails if this regresses. |
| P1-8 | "A pytest test serializes representative responses to `tests/fixtures/contract/*.json`" | It also normalises ids and timestamps to fixed placeholders before writing | Without it every run would rewrite every fixture with fresh ids, and the `git diff` that is supposed to show a wire-shape change would show noise instead. |
| P1-8 | The frontend "type-checks against" the contract fixtures | Checked twice: assigned to the client type for `tsc`, and compared key-set-for-key-set at run time | `tsc` cannot see into a `JSON.parse`, so a field the server dropped would arrive as `undefined` and type-check cleanly. The run-time check is an exact key match — extension-only protects an old client, but both sides live in one repository and move in one commit, so a field on one side only is drift. |
| P1-8 | Web dev budget | Added `@types/node` | The shared fixture sets live under `server/tests/` and are read from disk by the frontend suite, which runs in Node. Type-only, dev-only, and scoped by a comment in `tsconfig.json` saying application code must not use Node APIs. |
| P1-8 | "The fake client backs at least one real component test" | Added `web/src/panels/ProjectList.tsx` — a small, real component | There was no component to test: the Group A frontend was a health-check placeholder. This is the seed of the picker (P1-12), kept read-only, and it makes the fake's interface conformance load-bearing rather than notional. |
| P1-8 | — | `web/src/health.ts` deleted; `App.test.tsx` rewritten against the fake client | `health.ts` was P1-1's single stubbed call, and its own docstring said the typed client would replace it at P1-8. Its tests moved rather than went: three of the four now run against the fake, and the fourth — that a failing status code is an error and not a silent success — moved to `client.test.ts`, which is where `fetch` itself is now exercised. Recorded here because the failing-test rule requires a deliberate test change to be written down. |
| P1-8 | `tests/fakes/` exists | Exists with a README and no fakes | Phase 1 has no collaborator to fake — SQLite runs for real against `tmp_path`, and there is no provider, embedder, or network. The README says what belongs there and when (`FakeProvider` in Phase 4, `FakeEmbedder` in Phase 5). |
| P1-8 | — | The frontend resolves the shared fixtures from `process.cwd()`, not `import.meta.url` | Under Vitest the module URL is not a `file:` URL, so `fileURLToPath` throws. `src/__tests__/fixtures.ts` resolves the path and, if it is wrong, says so plainly instead of failing with a bare `ENOENT`. |
| P1-5 / P1-6 | — | Document **reads** use an ordinary connection, not the read-only mode the scan uses | The D17 discipline is that *looking at* a project — the directory scan, before the file has been opened — must not change it. By the time a `DocumentStore` exists the project has been explicitly opened and migrated. A read-only handle also cannot recover a write-ahead log left by an unclean shutdown, which would turn every read into an error after a crash. |
| P1-1 | Vite on 5173 with `/api` proxied | `vite.config.ts` now binds `host: '127.0.0.1'` explicitly | Vite's default is the *name* `localhost`, which on Windows resolves to `::1` first — so the dev server listened on IPv6 only and the `http://127.0.0.1:5173` the README tells you to open refused the connection. Found by testing the documented URL rather than the one Vite prints. Naming the address also states the D7 loopback posture outright instead of leaving it to name resolution. |

### Group C (P1-9 → P1-13), 2026-08-30

**Decisions of record.** Two questions the plan leaves open were put to the writer before code was
written, because both are expensive to change later:

- **`hardBreak` is in the schema.** See the amendment in P1-10 above. The alternative — Shift+Enter
  making a new paragraph — was the stricter reading of "nothing else", and was rejected because a
  stanza is not a sequence of paragraphs.
- **A reload reopens the project that was open.** The open project id is persisted, and the
  workspace header carries a *Projects* control that flushes before it leaves. The alternative,
  always landing on the picker, reads worse against exit criterion 1 ("close the browser, reopen —
  everything is exactly as it was left") and costs a click after every mid-sentence reload.

**The client half of the save protocol**, which the plan names but does not specify:

- **Dirtiness is a revision comparison, not a flag.** Every edit bumps a counter; a save records
  which revision it is writing and marks that one saved when it lands. An edit made *while* a save
  is in flight therefore leaves the document dirty when the save returns — a boolean set to
  `false` on success would have swallowed that keystroke until the next one arrived.
- **`openDocument` refuses rather than discards.** It flushes first; if the flush did not leave the
  document clean — a failed save, or an unanswered `409` — it does not switch, and says so.
  "Switching chapters with unsaved changes must be impossible" is read as *impossible*, not as
  *usually saved first*.
- **A conflict stops autosave until it is answered.** Typing more does not clear it and does not
  resume saving. The only offered answer is to take the server's copy; there is no merge and no
  "save anyway", because the version guard exists precisely to stop a client overwriting what it
  has not seen (D19).
- **Retry backoff** is 1s, 2s, 5s, 10s, 30s, holding at 30s. It tops out rather than growing
  without bound: the usual cause here is a server that was stopped and will be started again, and a
  writer who fixes it should not wait ten minutes to learn that they did.

| Item | Planned | As built | Why |
|---|---|---|---|
| P1-9 | Three regions with split dividers | Added `web/src/shell/` for the workspace frame, the divider, the error boundary, and the toast surface | Outline § 10 lists `api/`, `editor/`, `panels/`, and `state/`. None of them is the layout: a panel is content, and the frame that arranges panels is not. One new directory, named for what it holds. |
| P1-9 | Pane widths persisted to `localStorage` | Also the open project and the recent-projects list, all under `archetype.*` keys, all validated field by field on the way in | A stored value can be written by a previous version of this app, an extension, or a person with the console open. None of it is worth failing over, so a value that cannot be read is forgotten rather than repaired. |
| P1-9 | `UiContext`, `ProjectContext`, `DocumentContext` | `ToastProvider` as a fourth, outermost | P1-13 asks for a toast for transient failures, and the thing that pushes one is usually a panel deep in the tree. Its lifetime is the session's, which puts it outside all three. |
| P1-9 | Collapse / expand | A collapsed pane becomes a 28px rail with a button on it, not nothing | A pane that vanishes entirely is a pane a writer cannot find again. The divider stays where it is and reports `aria-valuetext="collapsed"`. |
| P1-9 | The outline panel's tabs | All four tabs render now; the three that are not Contents say which phase they arrive in (Timeline and Characters in Phase 8, Bible in Phase 3) | The tab strip is a layout commitment. A panel that grows one in Phase 3 is a panel whose every measurement changes in Phase 3. |
| P1-9 | — | `DocumentContext` keeps a ref beside its reducer, updated by running the same pure reducer synchronously | The save loop runs on timers and promises and has to read the current `version` *now*; a `useReducer` state is not readable after a dispatch until React re-renders, and a save presenting a stale version would be refused as a conflict the client itself caused. One set of rules, two readers — the ref for the loop, React's copy for the screen. Every action goes through one function, so they cannot diverge. |
| P1-10 | The closed schema | `hardBreak` added; `code`, `codeBlock`, and `strike` switched off by name | StarterKit brings more than the list. Naming the surplus explicitly means a future StarterKit release that adds a node fails `schema.test.ts` rather than quietly widening the schema. |
| P1-10 | Debounced save, flush, retry, status | The *timing* is a framework-free `SaveScheduler` in `editor/autosave.ts`; what a save does is a callback | It makes the rules that decide whether a keystroke survives testable with fake timers and no React, no network, and no editor. Attempts are serialised on one chain, so a flush racing the debounce cannot put two saves in the air presenting the same version. |
| P1-10 | — | The pane bounds, the debounce, and the backoff are exported constants, and tests shorten the last two through a `scheduler` prop | A test that waits a second and a half per keystroke is a test nobody runs. |
| P1-10 | — | `ProseMirrorNode` and `ProseMirrorDocument` in `editor/projection.ts` became type aliases with a typed `marks` array | A type alias carries an implicit index signature, which is what lets these values reach TipTap's `JSONContent` with no cast. The cast would have been the one place the two could stop describing the same JSON. |
| P1-11 | Jump-to-heading scrolls to the target | Implemented by counting `h1`–`h3` in the rendered editor DOM | Every heading level the schema allows renders as one of those, in document order, so DOM order and ordinal order are the same thing. It reads nothing the projection does not already number, which is what keeps this a seam Phase 2 can replace with an anchor. |
| P1-11 | The TOC updates live for the open document | The merge happens at the point of display: the server outline is used for every chapter, overlaid by the client mirror for the one whose id is open | Keeping the two in separate reducers means it is always obvious which answer is on screen, and the server's replaces the mirror's the moment a save returns (D18). |
| P1-11 | Create, rename, and open only | The *New chapter* control lives in the Contents tab's footer | The plan gives chapter creation a route (P1-5) but no home in the UI, and exit criterion 1 needs three chapters. Reorder and delete stay out until Phase 2 brings the snapshot that makes deleting safe. |
| P1-12 | The picker lists projects | Sorted by `updated_at`, most recent first, with relative timestamps | The project a writer wants is almost always the one they were last in. `web/src/format.ts` is the only place a timestamp becomes words, which is what keeps a formatted string from leaking back into a comparison. |
| P1-12 | Recent-projects shortcut | Ids come from `localStorage`, titles from the list already fetched; an id whose project is gone is silently not offered | The shortcut can never offer something that is not there, and it costs no second request. |
| P1-12 | `ProjectList` from P1-8 | Grown rather than replaced: it gained `onOpen`, `recentIds`, `reloadToken`, and `onLoaded`, and every P1-8 test still passes unchanged | Those tests are as much about the fake client's interface conformance as about the component. Rewriting them would have thrown that away. |
| P1-13 | Structured request logging | `api/logging.py`, pure ASGI, one line per request carrying `request_id`, `method`, `path`, `status`, and `duration_ms` as `key=value` **and** as `extra` fields | Pure ASGI because it must sit outside the exception handlers and inside Starlette's `ServerErrorMiddleware`, so an unhandled exception passes through it and is logged with the status it actually produced. `extra` means a JSON formatter in Phase 9 needs no message change. The level follows the outcome: `5xx` error, `4xx` warning, otherwise info. |
| P1-13 | "No stack traces in responses" | A `500` carries `{"request_id": …}` in `detail`, and nothing else | It is what turns "it broke" into a line in the log. Everything else about the failure stays server-side. |
| P1-13 | — | uvicorn's own access log is switched off in `__main__.py` | It duplicated every line the middleware writes, with less in it. |
| P1-13 | An error boundary around each region | Also one around the whole app, and each boundary offers *Try again* | A failure in the shell itself would otherwise show a blank page. Retrying costs nothing and is right whenever the cause was transient. |
| P1-8 / P1-10 | The hand-written fake client | Gained `failAlways`, `stopFailing`, and `writeBehindTheScenes` | A retry loop calls again by definition, so a one-shot failure cannot exercise one. `writeBehindTheScenes` moves the store on the way another window or the Phase 6 agent would, which stages a *real* `409` rather than a simulated one. |
| P1-8 | Vitest setup unmounts React trees between tests | Also clears `localStorage`, and stubs `Element.scrollIntoView`, `Range.getBoundingClientRect`, `Range.getClientRects`, and `document.elementFromPoint` | jsdom omits what ProseMirror expects. They are stubs, not implementations — anything needing a real measurement is out of reach and is not tested — but with them a real TipTap editor mounts and real keystrokes drive it, which is worth considerably more than testing a mock of the editor. |
| P1-10 | — | `SaveScheduler.dispose()` is reversible, paired with `activate()`, and `ManuscriptEditor` never destroys its own editor | `main.tsx` renders in `StrictMode`, which mounts, unmounts, and remounts every component while refs survive. A one-way dispose left autosave permanently off, and an unmount-effect `editor.destroy()` tore down the instance TipTap's own manager waits a tick to reuse — both broken in the browser only, with every test still green. A test that renders the workspace inside `StrictMode` now covers it. |
| P1-10 | — | The editor tests avoid `{End}` and other selection-moving keys | `user-event` implements them with `setSelectionRange`, which jsdom does not support on a contenteditable. Where a test needs a heading it types the markdown input rule (`# `) instead, which is also how a writer will make one. |

**Toolchain note.** Built and tested on Python 3.14 and Node 24. The declared floors stay 3.11 and
20 per § 2; nothing in the code uses an API newer than 3.11.

**Not yet done.** Group D. `P1-14` (the single-process static mount) and `P1-15`
(`specs/data-model.md`, `specs/api-contract.md`, and the phase close-out) remain, so the
`CLAUDE.md` Commands section is still provisional. The manual acceptance script in section 4 is
run by hand at the phase boundary and its results recorded here then; it has not been run yet.
