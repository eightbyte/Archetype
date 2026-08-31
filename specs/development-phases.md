# Archetype — Decision Register & Development Phases

**Status:** Active · **Version:** 1.3 · **Date:** 2026-08-30
**Parent:** [`specs/project-outline.md`](project-outline.md)

This document is the **authoritative register of binding decisions** (§ 1) and the **work
breakdown across phases** (§ 2–3). Phase plans and commits cite these IDs.

- `D<n>` — a binding decision. Changing one requires editing this entry, noting the change in
  the outline § 11, and propagating to the affected phase plans and to `CLAUDE.md`.
- `P<phase>-<n>` — a work item. Stable for the life of the project; referenced by commits and
  code comments. Never renumbered — a dropped item is marked **withdrawn**, not deleted.

---

## 1. Decision Register

### Resolved by the writer (Phase 0, 2026-08-29)

| ID | Decision | Binding resolution | Affects |
|---|---|---|---|
| **D1** | Rich-text editor foundation | **TipTap (ProseMirror).** Chosen for ProseMirror position-mapping, which is what makes durable anchors possible. No second editor engine enters the project. | P1, P2 |
| **D2** | Manuscript granularity | **An ordered list of chapter documents**, one open in the editor at a time. The whole manuscript is never loaded into editor state; breadth comes from retrieval and the bible, not from holding the book in memory. | P1, P2, P5 |
| **D3** | Storage & vector index | **SQLite, one file per project, with `sqlite-vec` in the same file.** No second store. Backup is a file copy. | P1, P5 |
| **D4** | Embedding source | **An `Embedder` port with two adapters**; local `fastembed` (ONNX, no torch) is the default, because local processing is preferred for inexpensive, high-frequency operations. Changing the embedding model invalidates the index and forces a reindex — the UI must warn. | P5 |
| **D5** | Agent write authority over the bible | **Every agent write is a proposal in a review queue.** Per-kind auto-accept toggles exist but ship **off**. | P7 |
| **D6** | Multi-project support | **Project picker from day one.** Every table, route, and panel is project-scoped from Phase 1. | P1 |
| **D7** | Deployment & access model | **Single user, bound to `127.0.0.1`, no auth, no HTTPS.** Additional access and deployment are out of scope for 1.0. | P1, P9 |
| **D8** | API key handling | **Server-side secrets only.** Environment variables preferred, gitignored `config.yaml` accepted. The UI may POST a key; the server never returns it, and the browser never stores it. Keys stay out of `localStorage`, out of the bundle, and out of Git. | P1, P4 |
| **D9** | Story-time representation | **Narrative position is always known and exact; story-time is optional** and may be an absolute date/time, a relative offset from another event, or a named era — plus explicit ordering constraints. The timeline sorts by what is known, holds unplaced events in a tray, and flags contradictions rather than inventing an order. No calendar is ever required. | P3, P8 |
| **D10** | Frontend state management | **React context + `useReducer`.** No state library unless a measured problem appears. | P1 |
| **D11** | Agent streaming transport | **WebSocket**, leaving room for mid-run interaction (cancel, approve, clarify) without a second mechanism. | P4, P6 |
| **D12** | May the agent edit manuscript text? | **Never directly.** `propose_text_edit` renders **an explicit before/after diff** over an anchored range; accepting applies it as a normal editor transaction — undoable and snapshotted. | P4, P7 |
| **D13** | Bible extraction trigger | **On demand only** (selection- or chapter-scoped). Token spend is always a deliberate user act. Plumbing stays scheduler-ready; automatic extraction is a post-1.0 consideration. | P7 |
| **D14** | Character interaction chart | **Adjacency matrix first**, hand-rolled SVG/HTML, no graph library. Node-link is a Phase 8 stretch. *The writer flagged this for a closer design conversation when Phase 8 begins.* | P8 |
| **D15** | Export formats for 1.0 | **Markdown** (per chapter and combined) plus a **full project bundle**. No DOCX/EPUB/PDF. | P2, P9 |
| **D16** | Working name | **Archetype.** Python package `archetype`; config namespace and env prefix `ARCHETYPE_`; UI title "Archetype". The repository directory stays `WritingAssistant` unless renamed at Git setup — a path, not an identity. | all |

### Derived during Phase 0 close-out

These follow from D1–D16 and were not put to the writer. They are binding on the same terms, and
are flagged in the Phase 1 plan for override before implementation begins.

| ID | Decision | Binding resolution | Rationale |
|---|---|---|---|
| **D17** | Project discovery | **The project list is derived by scanning `data/projects/*.sqlite`** and reading each project row. No registry file. | A registry is a second source of truth that can disagree with the filesystem. This follows the D3 rule that backup is a file copy — a project file copied into the directory simply appears. |
| **D18** | Where the TOC is derived | **The server derives `text_plain`, `word_count`, and the heading list from `content_json` on every save; that projection is authoritative.** The client derives the same for the *open* document so the TOC stays live between saves, and reconciles to the server answer on save. | Only one document is open (D2), but the TOC spans every chapter — so it cannot come from editor state. One authoritative implementation also serves chunking (P5) and AI context composition (P6). |
| **D19** | Write concurrency | **Every document carries a monotonic `version`. A save presenting a stale version is rejected with `409`**; the UI warns and offers reload. It does not merge. | The multi-tab question (backlog Q5) has a data-loss shape. A version guard is a few lines in Phase 1 and closes it. Real conflict resolution stays out of scope. |
| **D20** | Migration strategy | **Numbered, forward-only SQL migrations** applied when a project file is opened, tracked in a `schema_version` table. Every migration ships with a test that runs it against a fixture database from the previous version. No down-migrations, no ORM. | Extension-only schemas (outline § 7) make forward-only safe. An ORM would earn its place only if the schema grew far past what is planned. |

### Resolved by the writer (Phase 2, 2026-08-30)

Put to the writer in the Phase 2 plan § 2 and accepted as recommended. Binding on the same terms
as D1–D20.

| ID | Decision | Binding resolution | Affects |
|---|---|---|---|
| **D21** | Who resolves an anchor, and whose answer wins | **The server re-resolves every anchor of a document from that document's own text on every write, and its answer is authoritative.** The client rebases anchor decorations through ProseMirror's transaction mapping for the open document only, and that rebasing is **display-only** — never sent, never allowed to override a text match. This is D18's rule (the server owns the derived truth; the client mirrors it for liveness) applied to anchors. Client-sent positions stay a documented extension point, not a second resolution path. | P2, P3, P6, P7 |
| **D22** | What deleting a chapter does | **A soft delete.** `document` carries a nullable `deleted_at`; the row and its content stay. The chapter leaves every list, outline, export, and count; its anchors read as `orphaned` — **derived from `deleted_at` on read, never written into the anchor row**, so a delete and a restore change nothing about an anchor and restoring returns each one to the answer the resolver actually gave; restoring is one click. A hard delete would either cascade its own recovery snapshot away or leave that snapshot pointing at nothing, and a data-loss path is a release blocker (outline § 9). | P2, P9 |
| **D23** | When a snapshot is taken (**settles `Q1`**) | **On handover, on demand, and before anything destructive.** `handover` when the editor hands a document over; `manual` when the writer marks a version, with a label; `pre-restore`, `pre-delete`, and `pre-import` before an operation that replaces or removes text. `handover` is the only snapshot nobody asked for, and it is the only one that is **deduplicated** (nothing is written when the newest snapshot for that document holds the same content, so an unchanged chapter never accumulates snapshots) and the only one that is **pruned** (the 25 most recent per document are kept, older ones dropped in the same transaction that inserts). `manual` and every `pre-*` snapshot is always written and never pruned: a manual mark carries a label, and a `pre-*` snapshot is a recovery guarantee rather than a history entry. | P2, P4, P9 |
| **D24** | Multi-tab safety (**settles `Q5`**) | **No lock.** D19's version guard plus the P1-10 conflict surface are the whole answer, and snapshots (D23) make even a clobber recoverable. A soft lock introduces a failure mode strictly worse than the one it prevents — a crashed tab holding a lock on a single-user machine, with no second party to release it. | P2, P9 |

---

## 2. Phase Map

| # | Phase | Exit criterion | Status |
|---|---|---|---|
| 0 | Planning & Specs | Decisions answered; Phase 1 plan approved | **Closed** (2026-08-29) |
| 1 | [Skeleton & Editor](phase-1-plan.md) | Write, format, and reload a multi-chapter document; navigate by TOC; both suites green | **Complete** (2026-08-30) — every exit criterion met; acceptance recorded in its § 6 |
| 2 | [Manuscript Model & Anchors](phase-2-plan.md) | An anchor survives heavy editing around it; deleted text yields `stale`, never a wrong match | **In progress** — § 2 ruled (D21–D24 binding, 2026-08-30); Group A complete |
| 3 | Story Bible (manual) | Build a bible by hand; retcon an entry and see dependents flagged | Not started |
| 4 | LLM Provider Layer & Chat | Ask a question about a selection, get a streamed answer; swap providers in settings with no code change | Not started |
| 5 | Retrieval & Indexing | Search 50k words by meaning and by exact phrase; edits reindex within seconds | Not started |
| 6 | Agent Harness & Tools | Watch the agent plan, search, read, and answer with citations | Not started |
| 7 | AI Bible Extraction & Continuity | Accept proposals from a chapter run; a contradictory paragraph is flagged with citations | Not started |
| 8 | Outline Views | Timeline and interaction chart render from real bible data and navigate to source text | Not started |
| 9 | Polish, Hardening & 1.0 | Clean clone to writing with AI in under 15 minutes; no known data-loss path | Not started |

**Ordering constraints.** 2 before 3 (bible entries cite anchors). 3 before 7 (the bible works by
hand before the agent writes to it, so extraction targets a real API and reviews in a real UI).
5 before 6 (an agent without retrieval only sees what it is handed, which is not the product).
4 and 5 are independent of each other and may swap. 8 depends on 3; 9 depends on everything.

---

## 3. Work Breakdown Beyond Phase 1

Sketch only. Each phase items are firmed up in its own plan as the phase begins, and plans are
written **one phase ahead at most** — reality moves the target.

**Phase 2 — [Manuscript Model & Anchors](phase-2-plan.md)** *(`specs/anchors.md` written here, at `P2-4`, before the code it governs)*
Chapter create / rename / delete / reorder · snapshots (auto on close plus a manual "mark
version") · Markdown import and export (D15) · the anchor record · position rebasing through
ProseMirror transactions · quote + prefix + suffix re-verification on load · the `ok` / `stale` /
`orphaned` lifecycle · re-linking UI · the dedicated anchor test suite.

**Phase 3 — Story Bible** *(`specs/data-model.md` completed here)*
Uniform entry record with a `kind` discriminator · per-kind attribute schemas · CRUD for all
seven kinds · links with story-time bounds (D9) · revision history and retcon dependent-flagging
· create-entry-from-selection with an anchor · bible browser, search, and detail views.

**Phase 4 — LLM Provider Layer & Chat** *(`specs/api-contract.md` extended here)*
The `LLMProvider` port · Anthropic and OpenAI-compatible adapters · prompted-JSON tool fallback
for providers without native tool calling · `FakeProvider` · settings UI with server-side key
handling (D8) · WebSocket transport (D11) · streaming chat panel · selection-as-context ·
single-pass proofread / tone / rewrite with before-and-after diffs (D12).

**Phase 5 — Retrieval & Indexing**
Paragraph-aware chunking with overlap · the `Embedder` port with `fastembed` and API adapters
(D4) · `sqlite-vec` and FTS5 tables in the project file · incremental reindex on document change
· reciprocal-rank-fusion hybrid search · one search endpoint serving both the search box and the
agent tool · a reindex warning when the embedding model changes.

**Phase 6 — Agent Harness & Tools** *(`specs/agent-tools.md` written here)*
The plan → act → synthesize loop · tool registry and JSON-Schema declarations · run records
capturing every step · iteration and token budgets · streaming run inspector · all read tools
plus `note` · composed context recorded on the run.

**Phase 7 — AI Bible Extraction & Continuity**
Selection- and chapter-scoped extraction runs (D13) · proposal queue with dedup and merge against
existing entries (D5) · continuity checking against the bible and retrieval · findings with
severity and citations · findings carry the entry revision they were computed against.

**Phase 8 — Outline Views**
Timeline with story-time against narrative order and conflict flags (D9) · unplaced-event tray ·
adjacency-matrix interaction chart (D14 — revisit the design with the writer first) · TOC upgrades.

**Phase 9 — Polish, Hardening & 1.0**
Error surfaces · performance pass at 120k words · backup / restore and project bundle export ·
example project · README and user docs · full regression pass · production static serving.
