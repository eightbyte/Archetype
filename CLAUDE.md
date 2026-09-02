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

**Current state: Phase 1 complete (2026-08-30); Phase 2 complete (2026-09-01); Phase 3 in
progress — its § 2 ruled on 2026-09-01 and Group A (`P3-1` … `P3-4`) delivered on 2026-09-02,
both suites green.** All twenty-nine decisions are resolved and binding: the writer ruled D21–D24
on 2026-08-30 and **D25–D29 on 2026-09-01**, each as recommended and including both reversals,
which settles backlog `Q1`, `Q2`, `Q5`, and `Q7`. Three open questions remain, none due before
Phase 6.

The app is a place you can write, a place you can **maintain** what you wrote, and now a place
you can get words **in and out of**: create a project, add chapters, reorder them by drag or by
keyboard, rename them in place, delete one recoverably and restore it; mark a passage and watch
the highlight follow it as you type around it; find every mark in the *Marks* tab, see which have
gone stale, and repair one by hand; mark a version of a chapter, read it beside what is there now,
and restore it; export a chapter or the whole manuscript to Markdown, and import a Markdown file
back as chapters — with a list of anything it could not keep.

What exists on the server: configuration and the secret guard, the project file schema at
**version 2** with its migration runner, the ID generator, the project store, the whole Phase 1
REST surface with its uniform error envelope and structured request logging, the save protocol
with the D19 version guard, the text projection, the static mount that lets one process serve both
the API and the built app; Group A's **chapter reorder, soft delete, and restore; snapshots with
capture, history, and restore-through-the-save-path; and the `anchor` and `snapshot` tables**;
Group B's **block index over the projection, anchor resolver and corpus, anchor store with its
five routes, and re-resolution inside every save's transaction**; Group C's **nine chapter and
snapshot routes**; and — new in Group D — the **Markdown serializer and parser, their round-trip
corpus, and the two export routes and one import route** over them.

On the client: the three-region workspace with resizable keyboard-accessible dividers, the three
contexts and their pure reducers, the TipTap editor over a closed schema with autosave, the live
table of contents with jump-to-heading, the project picker, error boundaries per region; Group C's
**anchor decorations mapped live through every transaction, the selection control that marks and
re-links a passage, the fifth outline tab (*Marks*) with its filters and repair flow, chapter
management in the Contents tab, and the per-chapter history panel**; and — new in Group D —
**Markdown export links per chapter and for the manuscript, and an import form that takes a pasted
or dropped file, offers the two modes, and shows what the import left behind**.

Every Phase 1 exit criterion is met, including the acceptance script run by hand against the
single-process build; the results are in [specs/phase-1-plan.md](specs/phase-1-plan.md) § 6.

**Every Phase 2 exit criterion is met** — 1–8 by the suites, 9 by the documentation pass — and the
manual acceptance run in [specs/phase-2-plan.md](specs/phase-2-plan.md) § 8 **passed all fifteen
steps on 2026-09-01**, with the results in its table one line per step. It earned its keep twice.
Step 13 found a bug no test could have: a manuscript with an H1 inside a chapter, exported whole
and re-imported, came back as three chapters instead of two (`D15`, fixed and the step re-run the
same day). Step 15 reached the failed save Phase 1 could not, closing that Phase 1 gap.

**In flight: Phase 3 — the story bible.** There is still no AI and no search, and no bible the
writer can *see* — Group A is the model, and every surface is Groups C and D. What exists on the
server as of Group A: `specs/bible.md` (written before the code, as `anchors.md` was); **migration
003** and its four tables (`entry`, `entry_revision`, `entry_link`, `entry_anchor`), proved against
a captured version-2 project file; the `lnk_` prefix; **the kind and relation definition** — seven
kinds, six closed field types, twelve relations, in one place and validated against; and
**`EntryStore`**, carrying CRUD for all seven kinds, the `LIKE` filter, the D25 soft delete,
complete revision history from creation, and D27's retcon flagging with its review queue.

Still to come: `LinkStore`, citations, and the story-time ordering module (Group B); the routes
(Group C); the Bible tab, the generic form, links, citations, and *Add to bible* (Group D). Nothing
in Groups B–D exists yet, and § 8's fifteen-step acceptance run has not been attempted.

**Four rulings worth knowing, each a product decision rather than an implementation detail:**

- Deviation `B4` in [specs/phase-2-plan.md](specs/phase-2-plan.md) § 7. `specs/anchors.md` § 10
  said a paragraph split through an anchored range yields `stale`, while its own neighbouring row
  said a *merge* across one stays `ok` "because the separator normalises". Those cannot both hold
  — a split and a merge are the same operation seen from two sides. **Ruled by the writer on
  2026-08-30 as built:** a bare split keeps the anchor, and only a split with new words written
  into the gap breaks it. So an anchor can legitimately span a block boundary, which is why the
  editor draws one as an *inline* decoration. `anchors.md` now carries the ruling.
- Deviation `D1`: **no `pre-import` snapshot is ever taken, and none can be.** § 2's ruling 5 says
  import *creates* chapters and never replaces one, so nothing an import does can destroy text and
  a snapshot before it would record that nothing happened. The reason stays registered for the
  phase that lets an import overwrite a chapter. (This corrects `C3`, which was written before
  P2-14 met ruling 5 and said the import took one itself.) The snapshot *capture route* still
  accepts only `handover` and `manual` — the `pre-*` reasons are the server's own.
- Deviation `D12`: **Group D carries a client surface for Markdown that P2-13 and P2-14 did not
  budget**, ruled by the writer on 2026-08-31. Without it the acceptance script's last step —
  "compare the two on screen" — has nothing on screen to compare.
- Deviation `D15`: **the combined export writes every heading inside a chapter one level down**,
  ruled by the writer on 2026-09-01 after § 8's step 13 found the collision. Level 1 means
  "chapter" in that file, and the closed schema lets a writer put an H1 in a chapter's body, so
  without the shift the two are the same character and re-importing cuts a chapter in half at a
  heading that was never a boundary. The cost is at the floor and it announces itself: a body H3
  goes out as `####` and returns at level 3 with a notice. The per-chapter export, which is the
  half that promises a round trip, is untouched. Reserving H1 for chapter titles in the editor is
  the better long-term answer and is backlog `Q7`, to be settled by Phase 3.

One thing the Phase 1 run surfaced, still true: **some of the app's surfaces are hard or impossible
to reach from a test.** Phase 1 could not make a save fail where the writer could see it — the
retry loop absorbed the outage — but § 8's step 15 reached it on 2026-09-01, so that one is
**closed**. Two remain, both pointer gestures jsdom cannot make: there is no native editing, so a
text selection cannot be made through the DOM and the mark and re-link gestures are covered in two
halves that meet at a typed boundary (deviation `C7`); and a file *drop* is a gesture too, so the
import is tested by pasting rather than dropping. The backoff ladder, the `409` reload prompt, the
selection control, and the drop target are exercised only by the frontend suite; a regression in
them will not show up by using the app, so those tests and the § 8 run are the only things standing
under them.

**And § 8 is not a formality.** Step 13 found `D15` — a real bug, in a case the whole Markdown
corpus was blind to because no test manuscript had a heading where this writer puts one.

## The specs are the contract

- [specs/project-outline.md](specs/project-outline.md) — the root document: vision, architecture,
  phase list, testing strategy, risks. **Read this first.**
- [specs/development-phases.md](specs/development-phases.md) — the **authoritative decision
  register** (D1–D24) and the work breakdown across all phases. Cite these IDs.
- [specs/phase-1-plan.md](specs/phase-1-plan.md) — Phase 1 work items (`P1-1` … `P1-15`), exit
  criteria, and the as-built deviations table.
- [specs/phase-2-plan.md](specs/phase-2-plan.md) — Phase 2 work items (`P2-1` … `P2-15`). Its § 2
  is **ruled** (D21–D24, 2026-08-30). Its § 7 holds fifty as-built deviations across all four
  groups — `B4`, `D1`, `D12`, and `D15` are product decisions rather than implementation details,
  and `C7` and `C8` say which surfaces no test reaches. **Its § 8 is the manual acceptance run**:
  the script step by step, what each step must show, and the outcome of each — run on 2026-09-01,
  all fifteen passed, step 13 having found `D15` and been re-run against the fix.
- [specs/phase-3-plan.md](specs/phase-3-plan.md) — Phase 3 work items (`P3-1` … `P3-15`). **Its
  § 2 is ruled** (D25–D29, 2026-09-01): D25 soft delete for entries (settling `Q2`), D26 the
  uniform record with per-kind fields as data served by the API, D27 what a revision is and what a
  retcon flags, D28 story-time as a partial order, D29 H1 stays in chapter bodies (settling `Q7`).
  Its § 3 is the record's shape, § 5 ten exit criteria, § 6 the risks, § 7 the deviations table —
  `A1`–`A4` from Group A, all sequencing rather than behaviour — and § 8 the fifteen-step
  acceptance run, not yet run.
- [specs/backlog.md](specs/backlog.md) — deferred features and open questions, each with the
  phase it must be settled by. `Q1`, `Q2`, `Q5`, and `Q7` are promoted and closed; `Q3`, `Q4`, and
  `Q6` are open, none due before Phase 6. `Q2` and `Q7` were each settled **against** the leaning
  recorded there, and § 3 keeps the reasoning so a future reversal is a deliberate act.
- [specs/data-model.md](specs/data-model.md) — storage as built at schema version 2: the project
  file, the four tables, the projection rules, the soft-delete predicate, and the migration
  discipline. Its § 7 sketches later phases and is **not** binding; the rest is a bug if it
  disagrees with the code.
- [specs/api-contract.md](specs/api-contract.md) — every route that exists, what it promises, and
  what it refuses: § 5's chapter operations, § 7's five anchor routes and the extended save
  response, § 8's four snapshot routes, and § 9's two Markdown exports and one import — including
  the **one non-JSON response in the API** and why it is one. The generated OpenAPI schema is
  authoritative for types; this is authoritative for behaviour.
- [specs/anchors.md](specs/anchors.md) — what an anchor stores, the two coordinate systems and
  the block index, the matching ladder with its exact thresholds, the whitespace normal form, the
  suggestion protocol, and **what an anchor does not promise**. Written in `P2-4` before the code
  it governs; `P2-8`'s corpus is written from it, not from the implementation. Read it before
  touching anything in `manuscript/anchors/`. Four places where the code corrected it are marked
  and cross-referenced to the phase plan's `B1`–`B5`; its § 7 says why a Markdown import is
  *not* one of the writes that re-resolves an anchor.
- [specs/bible.md](specs/bible.md) — written at `P3-1`, **before** the code it governs, on the
  `anchors.md` pattern. It fixes the entry record and why `kind` is immutable, the *vocabularies*
  of field types and relations, the `entry_ref`-versus-link distinction, the constants, the
  revision and retcon rules with the exact definition of a dependent, story-time and its two
  contradiction kinds, citations, and both live predicates — and § 1 says in as many words what an
  entry does **not** promise. It deliberately does **not** restate the per-kind field lists or a
  relation's permitted kinds: those are D26's served definition, and a second copy in prose is
  exactly the third place to disagree that `specs/markdown.md` was refused for being. Its § 12
  carries the corrections the code makes to it — empty so far.
- `specs/agent-tools.md` — written as its phase begins (Phase 6).

There is no `specs/markdown.md`, deliberately. The syntax is a docstring
(`manuscript/markdown/serialize.py`) and a corpus (`tests/fixtures/markdown/cases.json`); the
routes are api-contract § 9. A third place to state it would be a third place to disagree.

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
| `server/archetype/manuscript/projection.py` | The pure text projection: rules, `text_plain`, headings, word count (`P1-7`, D18), plus the block index and the two coordinate conversions (`P2-5`) |
| `server/archetype/manuscript/documents.py` | `DocumentStore` — the only path by which manuscript text changes (`P1-6`, D19), plus reorder, soft delete, and restore (`P2-2`, D22) |
| `server/archetype/manuscript/snapshots.py` | `SnapshotStore` — capture, history, and restore-as-an-ordinary-save (`P2-3`, D23) |
| `server/archetype/manuscript/anchors/status.py` | The anchor status vocabulary and the one rule that derives `orphaned` (`P2-1`, D22) |
| `server/archetype/manuscript/anchors/resolve.py` | The matching ladder, the normal form, the suggestion protocol, and the constants — **pure**, no I/O (`P2-6`) |
| `server/archetype/manuscript/anchors/records.py` | The stored anchor, and the one place a row becomes one |
| `server/archetype/manuscript/anchors/rewrite.py` | Re-resolution inside the transaction of the save that caused it (`P2-7`, D21) |
| `server/archetype/manuscript/anchors/store.py` | `AnchorStore` — create from a range, read, re-link, delete (`P2-7`) |
| `server/archetype/manuscript/markdown/schema.py` | The server's mirror of the editor's closed node list, held to it by a shared fixture (`P2-13`, D1) |
| `server/archetype/manuscript/markdown/serialize.py` | Closed schema in, Markdown out — total by construction, and where the escaping rules live (`P2-13`, D15) |
| `server/archetype/manuscript/markdown/parse.py` | CommonMark in, closed schema out, over `markdown-it-py`; and the notice for everything it could not keep (`P2-14`) |
| `server/archetype/manuscript/markdown/importer.py` | The part of an import that writes: measure every chapter, then create them (`P2-14`) |
| `server/archetype/manuscript/locator.py` | Resolves a bare document, anchor, or snapshot id to the project file holding it |
| `server/archetype/bible/schema.py` | The **one** place the seven kinds' fields and the twelve relations are written down; the six closed field types, `validate()`, and the JSON dump (`P3-5`, D26) |
| `server/archetype/bible/predicates.py` | The live predicate for an entry, and the **three-way** one for a link — written once (`P3-3`, D25) |
| `server/archetype/bible/entries.py` | `EntryStore` — CRUD for all seven kinds, the filters, the D25 soft delete, revisions, and D27's retcon flagging (`P3-3`, `P3-4`) |
| `server/archetype/api/routes.py` | The `/api` router (`P1-5`), including Group C's chapter and snapshot routes (`P2-11`, `P2-12`) and Group D's Markdown routes (`P2-13`, `P2-14`) |
| `server/archetype/api/logging.py` | Request logging: one line per request, with a request id (`P1-13`) |
| `server/archetype/api/schemas.py` | Wire shapes, mirrored in `web/src/api/types.ts` |
| `server/archetype/api/static.py` | The single-process static mount and the `web_not_built` notice (`P1-14`) |
| `server/archetype/api/errors.py` | The uniform error envelope and its exception handlers |
| `server/archetype/app.py` | `create_app()`; builds the store and locator onto `app.state` |
| `server/tests/fixtures/db/` | Databases captured at a known schema version, with their README and the scripts that captured `v001_phase1.sqlite` and `v002_phase2.sqlite` |
| `server/tests/fixtures/projection/` | The shared projection cases, now with the block index — read by **both** suites (`P1-7`, `P2-5`) |
| `server/tests/fixtures/anchors/` | The anchor corpus, hand-written from `specs/anchors.md` (`P2-8`) |
| `server/tests/fixtures/markdown/` | The round-trip corpus: each chapter stated twice, as JSON and as the Markdown it must export to (`P2-13`, `P2-14`) |
| `server/tests/fixtures/schema/` | The closed schema, stated once and read by **both** suites (`P2-13`) |
| `server/tests/fixtures/contract/` | API responses written by pytest, type-checked by vitest (`P1-8`) |
| `server/tests/fakes/` | `FakeProvider` and `FakeEmbedder` land here in Phases 4 and 5 |
| `web/src/api/` | The typed client, its interface, and the mirrored wire types |
| `web/src/state/` | The three contexts and their pure reducers, plus toasts and `localStorage` (`P1-9`, D10) |
| `web/src/state/projectReducer.ts` | The project's chapters, outline, deleted list, **and every anchor in it** (`P2-10`) |
| `web/src/shell/` | The workspace frame, the split dividers, the editor region, error boundaries, toasts |
| `web/src/panels/` | The outline panel and its five tabs, the contents, the *Marks* tab, the history, the picker |
| `web/src/panels/MarkdownTransfer.tsx` | Export links and the import form, with the report of what an import left behind (`P2-13`, `P2-14`) |
| `web/src/anchorText.ts` | The one place an anchor is put into words, for the panel, the control, and the decoration |
| `web/src/editor/extensions.ts` | The closed TipTap schema — a change here is a spec change (`P1-10`, D1) |
| `web/src/editor/anchors.ts` | The decoration plugin: mapping, collapse, clamping — display-only (`P2-9`, D21) |
| `web/src/editor/SelectionActions.tsx` | The control over a selection: *Mark passage*, and *Re-link here* (`P2-9`, `P2-10`) |
| `web/src/editor/autosave.ts` | `SaveScheduler` — *when* a save happens, with no React in it (`P1-10`) |
| `web/src/editor/projection.ts` | The client mirror of the projection, held to the server by shared fixtures |
| `web/src/format.ts` | The display edge: the only place a UTC timestamp becomes words |
| `web/src/__tests__/fakes/` | The hand-written typed fake API client (`P1-8`) |
| `web/src/__tests__/harness.tsx` | The real provider stack with a fake client and a hurried autosave |
| `server/tests/test_static.py` | The run-mode tests; each builds its own miniature `dist` in `tmp_path` |
| `server/tests/test_chapters.py` | Reorder, delete, restore, and the soft-delete predicate across all four read paths (`P2-2`) |
| `server/tests/test_snapshots.py` | Capture, dedupe, retention, and restore (`P2-3`) |
| `server/tests/test_block_index.py` | The index against the shared cases, and the conversions at their edges (`P2-5`) |
| `server/tests/test_anchors.py` | The corpus, the properties, and the resolver's refusals (`P2-6`, `P2-8`) |
| `server/tests/test_anchor_store.py` | The store, re-resolution on write, and the resolution budget (`P2-7`) |
| `server/tests/test_anchor_routes.py` | The five anchor routes over the real application (`P2-7`) |
| `server/tests/test_chapter_routes.py` | Reorder, delete, restore, and the deleted list over HTTP (`P2-11`) |
| `server/tests/test_snapshot_routes.py` | Capture, history, preview, and restore over HTTP (`P2-12`) |
| `server/tests/test_markdown.py` | The corpus both ways, totality over the closed schema, and every normalisation Markdown forces (`P2-13`, `P2-14`) |
| `server/tests/test_markdown_routes.py` | The media type, the filename, the soft-delete predicate, and the refusals over HTTP (`P2-13`, `P2-14`) |
| `web/src/__tests__/anchorPlugin.test.ts` | The decoration plugin against real ProseMirror and no React (`P2-9`) |
| `web/src/__tests__/selectionActions.test.tsx` | The mark and re-link control against a real editor (`P2-9`, `P2-10`) |
| `web/src/__tests__/anchorsInEditor.test.tsx` | Anchors through the real provider stack (`P2-9`) |
| `web/src/__tests__/marks.test.tsx` | The *Marks* tab, its filters, and the repair path (`P2-10`) |
| `web/src/__tests__/chapters.test.tsx` | Reorder, rename, delete, and restore in the Contents tab (`P2-11`) |
| `web/src/__tests__/snapshots.test.tsx` | The history panel, marking a version, and restoring one (`P2-12`) |
| `web/src/__tests__/markdown.test.tsx` | The export links, the import form, and the report (`P2-13`, `P2-14`) |
| `server/tests/test_bible_schema.py` | The closed field-type list, the definition's own consistency, and validation's refusals (`P3-5`) |
| `server/tests/test_entries.py` | All seven kinds through one store, every refusal writing nothing, and the deleted entry absent from every read path together (`P3-3`) |
| `server/tests/test_entry_revisions.py` | Revisions, restore-through-update, the retcon computation, and the review queue that empties (`P3-4`) |

**Invariants established in Phase 1's Groups A, B, and C, in Phase 2's Groups A, B, C, and D, and
in Phase 3's Group A**, beyond those already listed above.

Phase 3's Group A added these:

- **Seven kinds, one record, and the difference is data** (D26). One `entry` table with a `kind`
  discriminator and an `attributes_json` blob; the per-kind field list and the relation vocabulary
  live in `bible/schema.py` and nowhere else, and `specs/bible.md` names the vocabularies but not
  their members on purpose. Adding a field to a kind is a change to one file. This is not the
  shared-fixture pattern and must not become it: `closed_schema.json` is a test artifact holding
  two implementations to a list, whereas this is runtime data with one implementation that the
  client *fetches* — copying it into `web/src` would create the second copy D26 exists to prevent.
- **The field-type list is closed at six, and `attributes_json` is not a free-form bag.** An
  attribute the definition does not declare is a refusal, not a silent drop, because the moment it
  is dropped the served definition stops describing what is actually in the file. A field that does
  not fit one of the six becomes a `long_text` and a backlog entry, never a seventh type.
- **`kind` is immutable after creation** — refused, not discouraged. Every attribute an entry holds
  was validated against that kind's field list, so changing it would either destroy typed work
  silently or leave data the served definition does not describe. The wrong kind is fixed by
  creating the right entry and deleting the wrong one, which is recoverable both ways.
- **Every entry write records a revision holding the full state *after* the change**, numbered from
  1, so revision *n* is what the entry was at revision *n* and reading a past state is one row
  rather than a replay. Nothing is deduplicated and nothing is pruned — the deliberate opposite of
  D23's `handover` snapshot on both counts, because that is 300 KB nobody asked for and this is two
  kilobytes somebody typed. `revisions()` returns metadata only.
- **Restoring a revision goes through `update`**, so it bumps `revision`, appends to history rather
  than rewriting it, is guarded by D19, and computes its own retcon answer. One write path, no
  exceptions — `SnapshotStore.restore`'s rule, one table over.
- **Only a write marked as a retcon flags anything, and a dependent is an entry joined by a live
  link in either direction** (D27) — the only relationship the data actually knows. The store
  computes the answer from `RETCON_FIELDS` (`name`, `attributes_json`, `status`) and the request
  may override it either way; the result reports *which* field moved, so the client's checkbox can
  say why it came up checked. The honest limit ships with it: **a dependency the data does not know
  about is not flagged**, and a prose mention is not a link.
- **Clearing a review is never a retcon**, not by default and not by override. Without that rule,
  clearing a flag on a densely linked character re-flags every neighbour and the queue regenerates
  itself as it is worked through — which teaches the writer that the queue does not mean anything.
- **Flagging a dependent writes no revision on the dependent.** `needs_review` is a note about the
  entry's surroundings, not a claim it makes; a revision for it would fill a densely linked
  character's history with rows recording that a neighbour changed.
- **`needs_review` and `status` are orthogonal.** One is "something this depended on moved", the
  other is the proposal lifecycle. `superseded` is not the answer to "this entry is out of date".
- **A link is live only when the link is not deleted *and neither endpoint is deleted***, and that
  three-way predicate lives in `bible/predicates.py` — one place, spliced in, never retyped. It is
  the Phase 2 lesson one table wider: forgetting a leg puts a deleted character back into a
  relationship view and surfaces in Phase 8 as a wrong chart. One test asserts a deleted entry is
  absent from the list, the counts, the filters, the review queue, and the dependent computation
  **together**.
- **Nothing cascades, which is what makes restore exact.** An endpoint's deletion *hides* a link
  through the predicate rather than writing to it, so restoring an entry brings back exactly the
  links it had — and a link deleted in its own right stays deleted, because its own `deleted_at`
  was never touched.
- **`proposed`, `rejected`, `superseded`, and `agent` are registered with no writer**, exactly as
  `pre-import` was in Phase 2. Everything a person types is `accepted` and `user`. They exist so
  Phase 7's proposal queue lands in a shape storage already understands rather than as a migration.
- **A fixture database is captured before the migration it tests exists, and re-running the capture
  must produce the same bytes.** The runner stamps its own `schema_version.applied_at` from the
  wall clock, so a capture script that pins only its own rows is not deterministic — `v002_phase2`
  normalises that too, and the fixture README now says so and gives the hash check.

Established earlier, and still true:

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
- **An anchor that reports `ok` points at text equal to its quote — there is no case in which the
  resolver returns `ok` and is wrong.** Every step of the ladder that would answer `ok` goes
  through one gate, `_confirmed`, which re-reads the text at the span it is about to return and
  compares it to the quote. The property is asserted **once over the whole corpus** rather than
  per case, so a case added later is covered without anyone remembering, and again over seeded
  random edits that deliberately reach into the anchored text. Everything else in Phase 2 can be
  fixed later; a wrong anchor does not fail, so it cannot be detected later.
- **A fuzzy match is a suggestion, never an outcome.** Steps 2 to 4 are exact string searches;
  step 4's scoring decides *between* exact occurrences, never whether an inexact one is close
  enough. A `stale` anchor's suggestion is computed from its **unedited surroundings** — two
  exact substring searches, no threshold to tune — precisely because a quote matcher is the
  machinery that turns into automatic repointing under pressure.
- **The block index is produced by the walk that produces `text_plain`**, not alongside it. Two
  walks over one tree are two chances to disagree about what a block is, and an index that
  disagrees with the text it indexes makes every anchor in the project subtly wrong at once. The
  shared fixture states both, so the two cannot drift apart in one suite and not the other.
- **A conversion between the two coordinate spaces is a walk, not arithmetic** — the projection
  trims each line and drops empty ones, so a paragraph carrying a stray trailing space is shorter
  in `text_plain` than in the document. Arithmetic is a legal fast path exactly when the block's
  projected length equals its raw length, which is nearly always, and the check is one comparison.
- **`text_plain` and ProseMirror positions have no honest correspondence inside a scene break.**
  An offset in one has no position, and a range that spans one is refused rather than quoted with
  five characters nobody typed. An empty paragraph is also non-mappable but *is* spannable,
  because it contributes no text at all.
- **The server derives an anchor's quote; the client sends only a range and a version.** A client
  cannot create an anchor that disagrees with the manuscript, because it is never asked what the
  manuscript says — and a range against a stale version is refused with the same `409` a save is.
- **`save_content` re-resolves the document's anchors inside its own transaction, and its answer
  is authoritative** (D21). Whoever wrote — the editor, an import, a restore, a Phase 6 accepted
  proposal — the rows are correct when it commits or nothing happened at all. The client's
  ProseMirror mapping is display-only: it is never sent and never overrides a text match.
- **Status is recomputed, never latched.** Nothing in the resolver reads an anchor's stored
  status. An undo that restores a deleted passage returns its anchor to `ok` on the next save,
  and a `stale` anchor keeps the positions it had rather than moving somewhere approximately
  right.
- **Every anchor of a document is checked on every save, not just the ones that moved** — a
  status is a statement about the text as it is now, and a row nobody looked at cannot make one.
  Only the movers are reported back, and only an `ok` anchor's `document_version` advances,
  because a `stale` anchor's positions are true at no version.
- **Re-resolution is budgeted, not assumed.** 200 anchors over 100,000 characters, median of five
  runs, under `RESOLUTION_BUDGET_MS` — currently 27.5 ms against 250. It exists to catch a change
  of algorithmic class, so a resolver that gets cleverer and slower fails the suite rather than a
  writer whose typing has started to stutter.
- **The anchor package's import direction is one-way and load-bearing.** `resolve.py` and
  `status.py` are pure; `rewrite.py` is what `DocumentStore` calls and must not import it back;
  `store.py` sits above both and raises the document store's own `StaleVersionError`. The package
  `__init__` exports only the pure halves — importing the store from it re-creates the cycle.
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
- **Jump-to-heading resolves by ordinal, and only by ordinal — permanently.** Phase 2 added
  anchors *alongside* it and did not replace it; both jumps exist in the client, and they resolve
  by different means on purpose. A heading is a structural position the projection already numbers
  exactly and re-derives on every save; anchors are for cited passages that no derived structure
  names. Minting an anchor row per heading on every save, to reproduce an answer that is already
  free, is what the earlier "seam Phase 2 replaces" reading would have cost (phase-2-plan § 2,
  ruling 1).
- **An anchor is a decoration, never a mark in the schema.** A mark would be part of the
  manuscript: stored in `content_json`, subject to the writer's undo, and split by every edit
  crossing it. An anchor is a reference *to* a passage, not a property *of* one, and it lives in
  its own table. So `AnchorDecorations` contributes no node and no mark, and the closed schema is
  exactly what it was (D1).
- **The client's anchor positions are display-only, and the server's answer replaces them.**
  ProseMirror's mapping runs on every transaction so a highlight follows the words as they are
  typed around; it is never sent, and a save's response overwrites it whole (D21). It exists
  because it is exact and free *when it exists* — and it does not exist for an import, a restore,
  a file changed behind the app's back, or a Phase 6 proposal.
- **A collapsed anchor is drawn, not decided.** Deleting all of an anchored passage maps its two
  positions onto one; an inline decoration over nothing draws nothing, so it becomes a visible
  marker instead. The plugin does not call it `stale` — a status is the server's to give, and
  nothing on the client may become a second resolver (phase-2-plan § 2, ruling 2).
- **A decoration is clamped into the document before it is built.** The server leaves a `stale`
  anchor's positions where they were, deliberately, and that document may since have got shorter;
  a decoration built out of bounds throws and takes the writing surface with it.
- **Anchors live in `ProjectContext`, one list, and the open document's are the slice of it.**
  Their lifetime is the project's — the *Marks* tab holds every chapter's at once and a re-link
  may cross chapters — so a second list beside the open document would exist only to be
  reconciled with the first, and the reconciliation would be the bug.
- **Nothing repairs an anchor by itself.** A suggestion is data on a finding with a button on it;
  accepting one and choosing a passage by hand send the identical request, so the server cannot
  tell them apart and does not try. An `orphaned` anchor is not repaired at all — its chapter is
  restored.
- **A reorder always sends the complete order.** That completeness is the server's concurrency
  guard, so a refusal is answered by re-reading the chapter list, never by correcting a field.
- **Every reorder gesture has a keyboard equivalent that does the same thing**, and focus follows
  the chapter that moved — without that, the second press goes nowhere and the interaction is
  usable only with a mouse (P1-9).
- **Deleting the open chapter moves the editor to a neighbour.** A recoverable delete that leaves
  the editor holding a ghost is not recoverable in the way that matters.
- **A client may only ask for the two snapshot reasons it owns.** `pre-restore`, `pre-delete`, and
  `pre-import` are written inside the transaction of the operation each protects against; a client
  that could ask for one could write a `pre-delete` with nothing deleted, which is a lie in the
  one list a writer consults when something has gone wrong.
- **The fake API client has no resolver and must never grow one.** A save reports no moved anchors
  unless a test has staged what the server answers. A fake that decided for itself whether an edit
  broke an anchor would be a second resolver with neither a specification nor a corpus behind it,
  and every client test would be asserting against a rule nobody wrote down.
- **Each region has its own error boundary.** A panel that cannot draw takes itself down and
  leaves the editor — which may be holding the only copy of a sentence — working. Reading a
  document's anchors follows the same rule at the request level: a failure leaves the cached list
  in place rather than blanking a panel or, worse, the chapter.
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
- **The closed schema is stated once and both suites are held to it.**
  `server/tests/fixtures/schema/closed_schema.json` is the vocabulary; `schema.test.ts` holds the
  schema TipTap really built to it, and `test_markdown.py` holds the server's mirror and the
  serializer's case list to the same file. Adding a node to the editor now fails a test on each
  side of the wire in the commit that adds it — which is what a closed list was always for, and
  before this a new node would have reached a serializer with no case for it and nobody would have
  found out until somebody exported a chapter.
- **The Markdown serializer is total, and refuses rather than guesses.** Every node in
  `ALLOWED_NODES` and every mark in `ALLOWED_MARKS` has a case; anything else raises. Inventing
  syntax for an unknown node would put text into a file that could never be read back, which is
  the failure import exists to make impossible.
- **The parser is not ours, and the syntax is.** Serializing ten nodes and two marks is small,
  total, and ours to define; parsing CommonMark is none of those, so `markdown-it-py` does it
  (§ 2, ruling 3). It runs the strict `commonmark` preset with HTML off, so a table, a footnote,
  and a `<div>` are not syntax at all — they arrive as the characters the writer typed, and
  produce no notice because nothing was dropped.
- **The round-trip corpus states the Markdown, not just the round trip.** Two halves that agreed
  with each other on a syntax nobody chose would round-trip perfectly and still write files no
  other reader could open. So each case carries the exact Markdown, hand-written, and one test
  renders it with the parser's own renderer and compares what a reader would see to `text_plain`.
- **Import creates chapters; it never replaces the text of one** (§ 2, ruling 5). That is what
  keeps `save_content` the only path by which existing manuscript text changes. It is also why no
  `pre-import` snapshot is ever written: nothing an import does can destroy text.
- **Nothing is created until everything is measured.** An import parses the file, serializes every
  chapter, and checks every size before the first row is written, so a file with one oversized
  chapter is refused whole. A partial import leaves a writer with three chapters of a five-chapter
  file and no way to tell which two are missing.
- **What Markdown cannot hold is reported, and the words are kept.** A code fence becomes a
  paragraph, a link keeps its text and loses its target, an image leaves its alt text, a heading
  below level 3 is imported at level 3 — each named in `dropped` with the line it was on. The
  field is a list of real losses only, which is why constructs the parser does not recognise are
  absent from it.
- **A Markdown export is a link, not a fetch.** The server sends it as an attachment with a
  filename, so the client is an `<a href download>`: less code, no bytes held in memory, no second
  implementation of the filename rules, and keyboard-reachable for free.
- **In the combined export, level 1 means "chapter" — so every heading in a body goes down one**
  (`D15`). The closed schema lets a writer put an H1 inside a chapter, and an exported file where
  a boundary and a body heading are the same character cannot be split back into the chapters it
  was made from. The offset is threaded through the block walk rather than applied to the top
  level, because a heading inside a blockquote is subordinate too; it is zero everywhere but
  `chapters_to_markdown`, so the per-chapter export's round-trip promise is untouched. The cost
  lands on a body H3, which goes out as `####` and returns at level 3 **with a notice** — a loss
  that announces itself, in the one file that never promised a round trip.
- **The fake API client has no Markdown parser, and must never grow one** — the same rule as the
  resolver's, for the same reason. `stageImport` says what an import creates.
