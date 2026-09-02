# Archetype — Project Outline

**Status:** **Phase 2 complete** — all fifteen work items delivered, both suites green, and the manual acceptance run passed on 2026-09-01 · **Version:** 1.4 · **Date:** 2026-09-01
**Phase:** 3 (Story Bible) — next. Phase 2 (Manuscript Model & Anchors) closed on 2026-09-01
**Child documents:**
- [`specs/development-phases.md`](development-phases.md) — binding decision register (D1–D24) and the work breakdown across all phases
- [`specs/phase-1-plan.md`](phase-1-plan.md) — Phase 1 work items
- [`specs/phase-2-plan.md`](phase-2-plan.md) — Phase 2 work items; its § 2 carries the rulings (D21–D24), its § 7 the as-built deviations, its § 8 the acceptance run
- [`specs/backlog.md`](backlog.md) — deferred ideas and revisit list
- [`specs/data-model.md`](data-model.md) — storage at schema version 2 as built, later phases sketched
- [`specs/api-contract.md`](api-contract.md) — the HTTP surface as built
- [`specs/anchors.md`](anchors.md) — what an anchor stores, the two coordinate systems, the matching ladder, and what an anchor does **not** promise (written at `P2-4`, before the code it governs)
- `specs/agent-tools.md` *(written as its phase begins)*

> This is the root planning document. Every phase plan links back to it, and any change to
> scope, architecture, or phase boundaries is recorded **here first**, then propagated to the
> affected phase plan and to `CLAUDE.md`.

**Changes in 1.4 (2026-09-01):** **Phase 2 is closed.** Its manual acceptance script (phase-2 plan § 8) was run by hand against the single-process build; all fifteen steps pass and the results are recorded step by step in that table. It earned the phase boundary twice over. **Step 13 found a bug no test could have**: the combined Markdown export wrote chapter titles as H1, and the closed schema lets a writer put an H1 *inside* a chapter, so a manuscript that did came back from a re-import as three chapters instead of two — an empty one, and one whose title was a heading from the middle of the prose. Nothing was lost and no count was wrong, but § 8's own expectation could not hold for any manuscript shaped that way. Ruled and fixed the same day as deviation `D15`: the combined export now writes every heading in a chapter body one level down, so level 1 means "chapter" in that file and nothing else. The per-chapter export, which is the half that promises a round trip, is untouched; the cost falls on a body H3, which returns at level 3 with a notice. Step 13 was re-run against the fixed build and passes. **Step 15 closed a Phase 1 open item**: the failed save Phase 1 could not reach — the retry loop absorbed the outage before the writer could see it — is reachable now. One new backlog question, `Q7`: whether H1 should be reserved for chapter titles, removing the ambiguity at the source rather than in one exporter; due by Phase 3. No phase boundary moved, no decision changed, and no scope was added. **Next: Phase 3 — the story bible.**

**Changes in 1.3 (2026-08-31):** **Phase 2 built.** All fifteen items (`P2-1` … `P2-15`) delivered across four groups; both suites green (864 backend, 399 frontend). The four proposed register entries were ruled as recommended on 2026-08-30 and are binding — D21 anchor resolution authority, D22 soft chapter delete, D23 the snapshot policy (settling `Q1`), D24 no multi-tab lock (settling `Q5`) — and `specs/anchors.md` now exists. Two things this document said are corrected below: § 5's sketch is superseded for the four tables that now exist, and § 6's Phase 2 row is brought level with what shipped. One scope addition was put to the writer and ruled: Group D carries a **client surface for Markdown** that P2-13 and P2-14 did not budget, because the acceptance script ends "compare the two on screen". No phase boundary moved and no decision changed. The phase is **built, not closed**: its manual acceptance script (phase-2 plan § 8) is the remaining act, and it covers the two surfaces no test reaches — the pointer gestures, and heavy editing against the real resolver.

**Changes in 1.2 (2026-08-30):** `specs/phase-2-plan.md` written — fifteen items (`P2-1` … `P2-15`) in four groups, exit criteria, and a manual acceptance script. No scope changed and no phase boundary moved. The plan **proposes** four register entries (D21 anchor resolution authority, D22 soft chapter delete, D23 the snapshot policy settling `Q1`, D24 no multi-tab lock settling `Q5`) and one correction to a Phase 1 claim: heading jump stays resolved by ordinal, and anchors are added alongside it rather than replacing it. None of the four is binding until ruled on and promoted to the register.

**Changes in 1.1 (2026-08-30):** **Phase 1 closed.** All fifteen items delivered, both suites green, and the phase-1 acceptance script run by the writer against the single-process build — results in that plan's § 6. `specs/data-model.md` and `specs/api-contract.md` written (P1-15), so § 5 below is now a **sketch superseded for the Phase 1 tables** by the data model, and still the sketch for everything after them. No decision changed and no phase boundary moved; every divergence from the plan is recorded in that plan's § 6.

**Changes in 1.0 (2026-08-29):** all sixteen § 11 decisions answered and closed; the project is
named **Archetype** (D16), Python package `archetype`, config namespace `ARCHETYPE_`; decisions
promoted to the binding register in `specs/development-phases.md`; Phase 1 plan written.

---

## 1. Vision

**Archetype** is a browser-based workspace for **writing and maintaining a long narrative**, where an AI agent
acts as a research assistant, continuity checker, and note-taker — never as the author.

The human writes. The agent reads what has been written, keeps a structured record of it (the
**story bible**), answers questions about it, and flags problems. Every AI output is a
*proposal* or a *report* the writer can accept, edit, or throw away.

The screen is a three-region workspace: a **manuscript editor** in the center, an **outline /
navigation panel** on one side, and an **agent chat panel** on the other. Selecting text in the
editor and asking a question about it is the primary interaction.

### Guiding principles

- **The writer owns the words.** The agent never mutates manuscript text or bible records
  silently. It proposes; the user disposes. (See D5, D12.)
- **Functionality before accuracy.** 1.0 proves the system works end to end. Prompt quality,
  model tuning, and extraction accuracy are explicitly a post-1.0 concern.
- **Every AI feature has a manual path first.** The bible, timeline, and roster are all fully
  usable by hand before the agent is wired to them. The agent drives the *same* API a user does,
  which makes it testable and makes the app useful with the AI turned off.
- **LLM-agnostic by construction.** No provider's request shape, tool-call format, or token
  accounting leaks past the adapter layer.
- **Small dependency surface.** Every third-party package must earn its place. The rich-text
  editor and the vector index are the two places where writing it ourselves would be a mistake.
- **Observability while developing.** Agent runs are recorded step-by-step and inspectable in
  the UI, the same way an agent harness shows its work.
- **Local-first, single user.** Runs on the writer's machine, binds to localhost, no accounts.

---

## 2. Goals & Non-Goals

### Goals (1.0 scope)

1. A rich-text manuscript editor with headings, standard formatting, autosave, and fast
   navigation to any heading or anchor.
2. Durable **anchors**: a stored reference to a text range that survives ongoing editing, so
   bible entries can cite the passage that produced them.
3. A **story bible** — characters, places, events, factions, items, plot threads, and
   relationships — with full manual CRUD, search, revision history, and retcon support.
4. Three outline views over the same manuscript: **table of contents** (from headings),
   **narrative timeline** (chronological events), and **character interaction chart**.
5. An **agentic AI layer**: multi-pass, tool-using, plan-then-act, with recorded runs.
6. **Selection-scoped AI actions**: proofread, tone check, rewrite assistance, continuity check,
   and "add this to the bible".
7. **Retrieval** over the manuscript and bible (hybrid semantic + keyword) so the agent can work
   on a novel-length text without ever seeing all of it at once.
8. **Provider-agnostic LLM access** configured by base URL + key + model name, with adapters for
   Anthropic and OpenAI-compatible APIs shipped in 1.0.
9. A test suite that grows with every phase and is green at every phase boundary.

### Non-Goals (explicitly out of scope for 1.0)

- Multi-user editing, collaboration, presence, accounts, or permissions.
- AI-authored prose generated unprompted, or any "write the next chapter" feature.
- Prompt/model tuning, quality benchmarking, or automated evaluation of AI output quality.
- Internet-facing deployment, HTTPS, hardening beyond localhost binding.
- Mobile or tablet layouts (desktop browser only).
- Publishing-grade export (DOCX, EPUB, PDF typesetting). Markdown + a project bundle only.
- Offline/conflicting edits across multiple tabs or machines.
- Local model hosting. The app talks to an API endpoint; whatever serves it is the user's
  business (which includes a local server exposing an OpenAI-compatible endpoint).

---

## 3. High-Level Architecture

```
┌─────────────────────────── Browser (localhost) ────────────────────────────┐
│  React + TypeScript                                                        │
│  ┌────────────────┐ ┌──────────────────────────┐ ┌──────────────────────┐  │
│  │ Outline panel  │ │   Manuscript editor      │ │  Agent panel         │  │
│  │ · TOC          │ │   (rich text, headings,  │ │  · chat + streaming  │  │
│  │ · Timeline     │ │    selection → actions)  │ │  · run inspector     │  │
│  │ · Interactions │ │                          │ │  · proposals queue   │  │
│  │ · Bible browser│ │                          │ │  · findings/reports  │  │
│  └────────────────┘ └──────────────────────────┘ └──────────────────────┘  │
└──────────────▲───────────────────────────────────────────▲─────────────────┘
               │ REST (documents, bible, search, settings)  │ WS (agent run
               │                                            │ events + tokens)
┌──────────────┴────────────────────────────────────────────┴────────────────┐
│                     Python API (FastAPI, single process)                   │
│                                                                            │
│  ┌────────────┐  ┌────────────┐  ┌───────────┐  ┌───────────────────────┐  │
│  │ Manuscript │  │   Bible    │  │ Retrieval │  │ Agent Orchestrator    │  │
│  │ · chapters │  │ · entries  │  │ · chunker │  │ · plan → act → report │  │
│  │ · anchors  │  │ · links    │  │ · embed   │  │ · run records         │  │
│  │ · snapshots│  │ · revisions│  │ · hybrid  │  │ · tool registry       │  │
│  └────────────┘  └────────────┘  │   search  │  └──────────┬────────────┘  │
│                                  └───────────┘             │               │
│                                                 ┌──────────▼────────────┐  │
│                                                 │ LLM Provider (port)   │  │
│                                                 │  ├ AnthropicAdapter   │  │
│                                                 │  ├ OpenAICompatAdapt. │  │
│                                                 │  └ FakeProvider(test) │  │
│                                                 └───────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
                    Storage: one SQLite file per project
                    (relational data + FTS5 keyword index + vector index)
```

### Proposed tech stack

| Concern | Choice | Notes |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite | No UI framework, no CSS framework. Hand-rolled split panes. |
| Editor | TipTap (ProseMirror) — **see D1** | ProseMirror's position-mapping is what makes durable anchors possible. |
| FE state | React context + `useReducer` — **see D10** | No Redux/Zustand unless a real need appears. |
| Backend | Python 3.11+, FastAPI, uvicorn, pydantic v2 | REST + WebSocket in one process. |
| Storage | SQLite (one file per project) — **see D3** | Relational bible + document blobs + FTS5. |
| Vector index | `sqlite-vec` in the same file — **see D3** | No server, no second store to keep in sync. |
| Embeddings | `fastembed` (ONNX, no torch) default — **see D4** | Plus an API-embedding adapter. |
| LLM access | HTTP via `httpx`, adapter per provider | Anthropic + OpenAI-compatible in 1.0. |
| Config | `config.yaml` + env for secrets — **see D8** | Keys never reach the browser. |
| Tests | pytest (backend), Vitest + RTL (frontend) | See § 8. |
| VCS | Git, commits referencing work-item IDs | |

---

## 4. Core Components

### 4.1 Project & manuscript store

A **project** is one narrative work, stored as a single SQLite file under `data/projects/`.
Everything about the project — manuscript, bible, anchors, runs, embeddings — lives in that one
file, so backup and "send it to someone" are a file copy.

The manuscript is an **ordered list of documents** (default granularity: one per chapter — D2).
Each document stores its rich-text content as an editor JSON blob plus a derived plain-text
projection used for search, chunking, and AI context. The editor loads one document at a time,
which keeps saves small and keeps a 150k-word manuscript from ever living in one editor state.

Also stored per document: word count, derived heading list, `updated_at`, and periodic
**snapshots** (a versioned copy) so a bad AI-assisted rewrite or a bad afternoon is recoverable.

### 4.2 Anchors — the load-bearing primitive

An **anchor** is a durable reference to a range of manuscript text. Bible entries cite them,
findings point at them, the TOC jumps to them, and the agent quotes them.

Naive character offsets break on the first edit above them, so an anchor stores three things:

- `document_id` + `from`/`to` positions (fast path),
- the `quote` text itself, plus a short `prefix` and `suffix` of surrounding context,
- a `status`: `ok` | `stale` | `orphaned`.

Positions are **rebased through the editor's change mapping** while a document is open (an edit
above an anchor shifts it; an edit that deletes it marks it `stale`). On load, or after an edit
made outside the editor (import, snapshot restore), positions are **re-verified by matching the
quote + context**; unmatched anchors become `stale` and surface in the UI for re-linking rather
than silently pointing at the wrong paragraph.

This is the single hardest technical problem in the project, and it gets its own spec and its
own dedicated test suite in Phase 2.

### 4.3 Story bible

A uniform record shape with a `kind` discriminator, so one storage layer, one search, one
review queue, and one revision history serve every entity type.

| Kind | Purpose | Notable fields |
|---|---|---|
| `character` | Named or significant people | aliases, role, physical/voice traits, goals, secrets, status (alive/absent/…) |
| `place` | Locations | parent place, description |
| `item` | Objects that matter | owner, location, state |
| `faction` | Groups, organizations | members, allegiances |
| `event` | Something that happened | participants, place, narrative position, story-time (D9), consequences |
| `thread` | Plot threads, setups & payoffs | status (open/resolved), setup anchor, payoff anchor |
| `fact` | World rules, established truths | scope, constraints |

Shared by all kinds: `name`, `summary`, `body` (markdown), free-form `attributes` (JSON,
per-kind schema), `status` (`proposed` | `accepted` | `rejected` | `superseded`), `origin`
(`user` | `agent`), anchors, and a full **revision history**.

**Links** connect entries (`character —knows→ character`, `event —occurs_at→ place`,
`character —participates_in→ event`) with an optional `since`/`until` in story-time. The
character interaction chart and the timeline are both *derived from links and events*, not
separately maintained.

**Retcon support** is a first-class requirement, not an afterthought: editing or deleting an
entry writes a revision, marks dependent entries for review, and re-runs affected continuity
checks rather than leaving stale conclusions behind.

### 4.4 Retrieval

The manuscript is chunked (paragraph-aware, with overlap), embedded, and indexed incrementally
as documents change. Bible entries are indexed too — the agent needs to find "what do we know
about the harbor" as readily as "where does the harbor appear in the text".

Search is **hybrid**: SQLite FTS5 for exact names and phrases (which embeddings are bad at) plus
vector similarity for semantics, merged with reciprocal rank fusion. The same search endpoint
serves the user's search box and the agent's `search_manuscript` tool.

**Context discipline:** the agent never receives the whole manuscript. Every AI call is built
from an explicit selection, explicitly requested ranges, retrieval results, and bible entries,
each within a per-block token budget. The composed context is recorded on the run so it can be
inspected when output is wrong.

### 4.5 LLM provider layer

A single `LLMProvider` port:

```python
class LLMProvider(Protocol):
    async def complete(self, req: CompletionRequest) -> CompletionResult: ...
    async def stream(self, req: CompletionRequest) -> AsyncIterator[StreamEvent]: ...
```

`CompletionRequest` carries normalized messages, tool declarations (JSON Schema), and sampling
params. `CompletionResult` carries text, **normalized tool calls**, stop reason, and usage.
Adapters translate to and from provider-native shapes; nothing above the port knows which
provider is in play.

Shipped adapters: **Anthropic** (Messages API) and **OpenAI-compatible** (which covers OpenAI
plus most local and hosted servers that mimic it). Configuration is base URL + API key + model
id + capability flags, so a new endpoint is often just config, and a genuinely different API is
one new adapter file. A `FakeProvider` with scripted responses backs the entire test suite.

Providers without native tool calling fall back to a prompted JSON tool protocol, so the agent
loop is not gated on provider features.

### 4.6 Agent orchestrator

A real agent loop, not a single prompt:

```
task (user question / selection action / extraction request)
  → 1. plan          model drafts an explicit step list, recorded and shown to the user
  → 2. act           loop: model calls tools → server executes → results appended
                     (bounded by max iterations and a token budget)
  → 3. synthesize    model produces the user-facing output
  → 4. emit          proposals, findings, or an answer — always a durable record
```

Every run is persisted as a **run record**: task, composed context, plan, each tool call and
result, model messages, token usage, timings, and final outputs. The agent panel renders this
live over WebSocket and it remains browsable afterward. This is how a wrong answer gets
diagnosed without guessing.

The agent may keep its own working notes (a run-scoped scratchpad tool) — but a run is only
complete when it has produced a user-visible artifact: an answer, a proposal, or a finding.

**Tool set (v1, refined in `specs/agent-tools.md`):**

| Tool | Kind | Purpose |
|---|---|---|
| `get_outline` | read | Chapters + headings + word counts |
| `read_manuscript` | read | Text of a document, heading section, or anchor range |
| `search_manuscript` | read | Hybrid search over manuscript chunks |
| `list_bible_entries` / `get_bible_entry` | read | Browse and inspect bible records |
| `get_timeline` | read | Events in narrative or story-time order |
| `get_relationships` | read | Links for an entity; interaction data |
| `note` | scratch | Run-scoped working notes (visible in the inspector) |
| `propose_bible_entry` / `propose_bible_edit` | write-proposal | New or amended bible records |
| `propose_text_edit` | write-proposal | A replacement for an anchored range, shown as a diff |
| `report_finding` | output | Continuity issue, proofreading note, tone observation — with severity and citations |

Every write goes through a **proposal** that lands in a review queue. Nothing the agent produces
reaches the manuscript or the accepted bible without a click (D5, D12).

### 4.7 Web UI

Three resizable regions plus a settings screen.

- **Editor (center).** Rich text with headings, emphasis, block quotes, lists, scene breaks.
  Selecting text raises an action bar: *Ask agent*, *Proofread*, *Tone*, *Rewrite*,
  *Continuity check*, *Add to bible*. Jump-to-anchor and jump-to-heading navigation.
- **Outline panel (left).** Four tabs — **Contents** (heading tree, drag to reorder chapters),
  **Timeline** (events in story-time with narrative order shown alongside; conflicts flagged),
  **Interactions** (who has been in scenes with whom — adjacency matrix first, node-link second,
  D14), **Bible** (browse, search, edit, review queue).
- **Agent panel (right).** Chat with streamed replies; an expandable run inspector (plan, tool
  calls, retrieved context, token usage); the proposals queue with accept / edit / reject; and
  findings from analysis runs.
- **Settings.** Provider, base URL, model, key handling, embedding source, agent limits
  (max iterations, token budget), extraction auto-accept toggles.

---

## 5. Data Model Sketch

**Superseded for the tables that exist.** [`specs/data-model.md`](data-model.md) documents `project`, `document`, `anchor`, `snapshot`, and `schema_version` **as built at schema version 2**, and is the authority on them. The five below are kept only as the shape they were sketched in; where the sketch and the data model disagree, the data model is right and the sketch is history. Two differences are worth naming because they are decisions rather than drift: `document` carries a nullable `deleted_at`, because deleting a chapter is a **soft** delete (D22); and `anchor.status` holds the resolver's text answer alone — `orphaned` is **derived** from the chapter's `deleted_at` on read and never written into the row.

What is below stays as the sketch for the tables later phases will add — illustrative, not final:

```
project(id, title, created_at, settings_json)                        -- built, see data-model § 3
document(id, project_id, order_index, title, kind, content_json,     -- built, plus deleted_at
         text_plain, word_count, updated_at)
snapshot(id, document_id, taken_at, reason, content_json)            -- built, plus label + hash
anchor(id, project_id, document_id, from_pos, to_pos,                -- built, plus document_version
       quote, prefix, suffix, status, updated_at)

entry(id, project_id, kind, name, summary, body_md, attributes_json,
      status, origin, created_at, updated_at)
entry_revision(id, entry_id, revised_at, reason, snapshot_json, origin)
entry_anchor(entry_id, anchor_id, role)          -- 'source' | 'mention' | 'setup' | 'payoff'
entry_link(id, from_entry, to_entry, relation, attributes_json, since, until)

chunk(id, document_id, ord, text, from_pos, to_pos, hash)
chunk_vec(chunk_id, embedding)                   -- sqlite-vec virtual table
chunk_fts(chunk_id, text)                        -- FTS5 virtual table

run(id, project_id, kind, task_json, status, started_at, ended_at, usage_json)
run_step(id, run_id, ord, type, payload_json)    -- plan|tool_call|tool_result|message|error
proposal(id, run_id, kind, target_json, payload_json, status, decided_at)
finding(id, run_id, kind, severity, message, citations_json, status)
```

---

## 6. Development Phases

Each phase gets a `specs/phase-N-plan.md` with work items carrying stable IDs (`P3-4`) that
commits and code comments reference. A phase is done when its exit criteria pass **and** the
full test suite is green.

| # | Phase | Delivers | Exit criterion |
|---|---|---|---|
| **0** | **Planning & Specs** | This outline, resolved decisions (§ 11), `CLAUDE.md`, plan for Phase 1 | Decisions answered; Phase 1 plan approved |
| **1** | **Skeleton & Editor** | Repo scaffold (server + web), config, project SQLite store, three-pane shell, rich-text editor, autosave, load/save, TOC from headings, jump-to-heading. Test harness on both sides. | Write, format, and reload a multi-chapter document; navigate by TOC; `pytest` and `vitest` green |
| **2** | **Manuscript Model & Anchors** | Chapter CRUD + reorder + soft delete/restore, snapshots (handover, manual, and before anything destructive), Markdown import and export both ways over a round-trip corpus, the anchor service with server-side re-resolution and client-side rebasing, staleness detection, the *Marks* tab and its re-linking flow | An anchor created before an editing session still resolves to the right passage after heavy editing above, below, and around it; deleted text yields `stale`, never a wrong match |
| **3** | **Story Bible (manual)** | Entry schema + CRUD for all kinds, links, revisions/retcon, anchors from selection, bible browser, search, character roster with structured detail | Build a bible for a test story entirely by hand; retcon an entry and see dependents flagged |
| **4** | **LLM Provider Layer & Chat** | Provider port, Anthropic + OpenAI-compatible adapters, settings UI, streaming chat panel, selection-as-context, single-pass proofread / tone / rewrite with accept-reject diffs | Highlight a paragraph, ask a question, get a streamed answer; swap providers in settings with no code change |
| **5** | **Retrieval & Indexing** | Chunking, embeddings, sqlite-vec + FTS5, incremental reindex, hybrid search API + UI | Search a 50k-word manuscript by meaning and by exact phrase; edits reindex within seconds |
| **6** | **Agent Harness & Tools** | Agent loop (plan → act → synthesize), tool registry, run records, streaming run inspector, all read tools + `note` | Ask "where did I first describe the harbor?" and watch the agent plan, search, read, and answer with citations |
| **7** | **AI Bible Extraction & Continuity** | Extraction runs (selection- and chapter-scoped), proposal queue with dedup/merge against existing entries, continuity checking, findings UI | Run extraction over a chapter, review and accept proposals, then have a deliberately contradictory paragraph flagged with citations |
| **8** | **Outline Views** | Timeline view (story-time vs narrative order, conflict flags), character interaction chart, TOC upgrades | All three outline views render from real bible data and navigate to source text |
| **9** | **Polish, Hardening & 1.0** | Error surfaces, perf pass on a 120k-word manuscript, backup/restore, example project, README + user docs, full regression pass | Clean clone → writing with AI assistance in under 15 minutes; suite green; no known data-loss path |

**Dependency notes.** Phase 3 before Phase 7 is deliberate: the bible must work by hand before
the agent writes to it, so extraction has a real API to target and a real UI to review in.
Phase 5 before Phase 6 is likewise deliberate: an agent without retrieval can only see what is
handed to it, which is not the product. Phases 4 and 5 are independent of each other and could
run in either order.

---

## 7. Cross-Cutting Conventions

- **IDs** are prefixed short tokens (`prj_`, `doc_`, `anc_`, `ent_`, `run_`) — greppable in logs.
- **Timestamps** are UTC ISO-8601 everywhere, formatted only at the display edge.
- **API shapes** are pydantic models on the server and mirrored TypeScript types on the client;
  the contract lives in `specs/api-contract.md` and drifting from it is a bug.
- **Wire and storage schemas are extension-only** — add fields, never repurpose or remove one
  without a migration and a note in the phase plan.
- **Migrations**: every schema change ships with a numbered migration and a test that runs it
  against a fixture database from the previous version.
- **No AI call outside the provider port.** No provider SDK imported outside `llm/adapters/`.
- **Definition of done** for a work item: code + tests + docstrings/types + config keys
  documented + spec updated + no `TODO` without a tracked backlog entry.

---

## 8. Testing Strategy

Testing is a phase deliverable, not a cleanup task. The suite grows every phase and must be
green at every phase boundary.

**Backend (pytest).** Unit tests never touch the network, a real model, or a real API key.
`FakeProvider` returns scripted completions and tool calls; `FakeEmbedder` returns deterministic
vectors; SQLite runs against `tmp_path`. Agent-loop tests script multi-turn tool-calling
conversations to assert the loop's control flow, budgets, and failure handling.

**Frontend (Vitest + React Testing Library).** Component and reducer tests against a fake API
client. The editor gets focused tests for heading extraction, selection → anchor creation, and
anchor rebasing across representative edits.

**Contract tests.** Shared JSON fixtures assert that server responses and client-side types
agree, so a backend change that breaks the UI fails in the suite rather than in the browser.

**Live-provider tests** are marked (`@pytest.mark.live`) and excluded by default; they are
smoke-level only — does a real endpoint return a parseable tool call — never quality checks.

**Quality of AI output is not automatically tested in 1.0.** It is assessed by hand against
scripted scenarios recorded in the relevant phase plan.

### The failing-test rule

> **A failing test is fixed before any other work continues — including a test that the current
> phase's work "shouldn't have touched."** A failure means a real assumption broke somewhere;
> unrelated is a hypothesis, not an excuse. Tests are never deleted, skipped, or loosened to
> restore a green suite. If a test is genuinely testing the wrong thing, correcting it is a
> deliberate change: fix the test, and record what changed and why in the current phase plan.

---

## 9. Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| **Anchor drift** | Bible entries citing the wrong passage silently destroys trust in the whole feature | Quote+context re-verification, explicit `stale` state, a dedicated Phase-2 test suite, never a silent best guess |
| **Editor performance at novel length** | A 150k-word document in one editor state janks on every keystroke | Per-chapter documents (D2); measure at 120k words in Phase 9 |
| **Extraction noise** | An over-eager agent buries the writer in low-value bible entries | Proposal queue with dedup/merge; selection-scoped extraction before whole-chapter; auto-accept off by default |
| **Retcon leaving stale conclusions** | Continuity checks against outdated records are worse than none | Revisions flag dependents for review; findings carry the entry revision they were computed against |
| **Provider drift** | Tool-calling formats differ and change under us | Everything normalized at the adapter; adapter-level tests against recorded fixtures |
| **Cost / latency of multi-pass runs** | Agentic runs make many calls over a long text | Hard iteration and token budgets per run, visible usage per run, retrieval instead of bulk context |
| **Scope creep from a large feature list** | 1.0 never ships | Phase exit criteria are the contract; new ideas go to `specs/backlog.md` |
| **Data loss** | A writer's manuscript is irreplaceable | Autosave + snapshots + single-file backup + never destructive AI writes; a data-loss path is a release blocker |

---

## 10. Suggested Repository Layout

```
WritingAssistant/                   # repo root (product name: Archetype)
├── CLAUDE.md
├── README.md
├── .gitignore                      # data/ and config.yaml are never committed (D3, D8)
├── specs/
│   ├── project-outline.md          # this document
│   ├── development-phases.md       # decision register (D1-D20) + work breakdown
│   ├── phase-N-plan.md             # one per phase, written as the phase begins
│   ├── data-model.md
│   ├── api-contract.md
│   ├── agent-tools.md
│   ├── anchors.md
│   └── backlog.md
├── server/
│   ├── pyproject.toml
│   ├── archetype/
│   │   ├── config.py
│   │   ├── api/                    # FastAPI routes, WS handler, schemas
│   │   ├── projects/               # project store, migrations
│   │   ├── manuscript/             # documents, anchors, snapshots, import/export
│   │   ├── bible/                  # entries, links, revisions
│   │   ├── retrieval/              # chunking, embeddings, hybrid search
│   │   ├── llm/                    # provider port + adapters/
│   │   └── agent/                  # orchestrator, tools/, run records
│   └── tests/
│       ├── fakes/                  # FakeProvider, FakeEmbedder
│       └── fixtures/
├── web/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── api/                    # typed client
│       ├── editor/                 # editor setup, anchors, selection
│       ├── panels/                 # outline, agent, bible
│       ├── state/                  # contexts + reducers
│       └── __tests__/
└── data/                           # runtime project files (gitignored)
```

---

## 11. Decisions — RESOLVED (2026-08-29)

**All sixteen decisions are answered and closed.** They are now binding `D<n>` entries in
[`specs/development-phases.md`](development-phases.md) § 1, which is the authoritative register
that phase plans cite. The recommendations and answers are preserved below as the *rationale
record* — why each choice was made, so a future reversal is a deliberate act with the original
reasoning in view.

Reopening a decision means editing the register entry, noting the change here, and propagating
to the affected phase plans and `CLAUDE.md` — never a silent divergence in code.

| | Decision | Resolution |
|---|---|---|
| D1 | Editor foundation | TipTap (ProseMirror) |
| D2 | Manuscript granularity | Chapter documents |
| D3 | Storage & vector index | SQLite + `sqlite-vec`, one file per project |
| D4 | Embedding source | `Embedder` port; local `fastembed` default, API adapter available |
| D5 | Agent write authority | Proposal queue always; per-kind auto-accept off by default |
| D6 | Multi-project | Project picker from day one |
| D7 | Deployment | Single user, localhost-bound, no auth, no HTTPS |
| D8 | API keys | Server-side secrets only; never returned to or stored in the browser |
| D9 | Story-time | Narrative position always; story-time optional (absolute / relative / era) + ordering constraints |
| D10 | Frontend state | React context + `useReducer` |
| D11 | Streaming transport | WebSocket |
| D12 | Agent editing text | Never directly; `propose_text_edit` diffs with explicit before/after |
| D13 | Extraction trigger | On demand only; token spend is always deliberate |
| D14 | Interaction chart | Adjacency matrix first; node-link a Phase 8 stretch |
| D15 | Export formats | Markdown (per chapter + combined) plus a project bundle |
| D16 | Name | **Archetype** — package `archetype`, config namespace `ARCHETYPE_` |

---

**D1 · Rich-text editor foundation**
Options: TipTap (ProseMirror) · Lexical · raw `contentEditable`.
**Recommendation: TipTap.** This is the one dependency worth taking. Anchors are the backbone of
the bible, and ProseMirror is the only option with a mature position-mapping model that can
rebase a stored range through arbitrary edits. Raw `contentEditable` means re-inventing that
badly; Lexical is capable but its external-position story is weaker for our use.
**Your answer:**
TipTap

**D2 · Manuscript granularity**
One document for the whole book, or an ordered list of chapter documents?
**Recommendation: chapter documents.** Keeps the editor fast, saves small, snapshots cheap, and
gives natural units for chunking and AI scoping. The TOC stitches them into one outline, and a
continuous-scroll reading mode can come later if you miss it.
**Your answer:**
I agree, chapter documents. Having the entire narrative at all times is redundant if we have a vector and database for reference. Should help control context size a bit too.

**D3 · Storage & vector index**
Options: SQLite + `sqlite-vec` in one file · SQLite + ChromaDB alongside · Postgres + pgvector.
**Recommendation: SQLite + `sqlite-vec`, one file per project.** The bible is relational
(entries, links, revisions, anchors), so a relational store is needed regardless; putting vectors
in the same file removes an entire class of "the two stores disagree" bugs, makes backup a file
copy, and avoids the Chroma file-locking pain from the prior project.
**Your answer:**
Your suggestion is correct

**D4 · Embedding source**
Options: local `fastembed` (ONNX, no torch) · provider API embeddings · both behind one port.
**Recommendation: both behind an `Embedder` port, `fastembed` as the default.** Local means no
per-keystroke API cost and it works offline; the API adapter is there for anyone who wants
better vectors. Note that changing the embedding model invalidates the index and forces a
reindex — worth a UI warning.
**Your answer:**
Exactly the anticipation. If we can do local processing should be a preferred option for inexpensive operations.

**D5 · Agent write authority over the bible**
Options: agent writes accepted entries directly · everything lands as a proposal for review ·
per-kind auto-accept toggles.
**Recommendation: proposal queue always, with per-kind auto-accept toggles off by default.**
Matches "assist, don't author", makes extraction errors cheap, and gives 1.0 a review UI you
will want anyway. Turning auto-accept on for low-risk kinds later is a settings change.
**Your answer:**
Recommendation is correct

**D6 · Multi-project support**
Options: one project per install · a project picker from day one.
**Recommendation: project picker from day one.** A project is a file path; supporting a list
costs almost nothing in Phase 1 and retrofitting a project scope through every table, route, and
panel later is expensive.
**Your answer:**
Project picker

**D7 · Deployment & access model**
**Recommendation: single-user, localhost-bound, no auth, no HTTPS** — same posture as the prior
project. Confirming this closes out a lot of design surface. (If you ever want it on a home
server reachable from a laptop, say so now — it changes the auth and secrets design, not the
features.)
**Your answer:**
Correct.  This is intended for single user use. Additional access and deployement is out of scope.

**D8 · API key handling**
Options: server-side `config.yaml` / env vars · entered in the UI and stored server-side ·
stored in the browser.
**Recommendation: server-side only — env vars preferred, `config.yaml` (gitignored) accepted;
the UI can set a key by POSTing it to the server but never receives it back, and never stores it
in the browser.** Keys stay out of localStorage, out of the bundle, and out of Git.
**Your answer:**
Correrct.  API keys are handled as secrets and should be treated as sensitive.

**D9 · How story-time is represented on the timeline**
Fiction resists a real calendar: fantasy dates, "three days later", deliberately vague flashbacks.
**Recommendation: every event always has a narrative position (where it sits in the text — free
and exact) and an *optional* story-time that can be any of — an absolute date/time, a relative
offset from another event ("2 days after ent_x"), or a named era/label — plus explicit ordering
constraints (A before B).** The timeline sorts by whatever is known, shows unplaced events in a
separate tray, and flags contradictions instead of inventing an order. Do not require a calendar.
**Your answer:**
Your recommendation is correct

**D10 · Frontend state management**
**Recommendation: React context + `useReducer`, no state library.** The app has a handful of
long-lived stores (project, document, selection, bible, agent run) with clear boundaries. If a
performance or prop-drilling problem shows up, adding Zustand later is a small, local change.
**Your answer:**
correct

**D11 · Agent streaming transport**
Options: Server-Sent Events · WebSocket.
**Recommendation: WebSocket.** Slightly more setup than SSE, but you already have the pattern
from the prior project, and it leaves room for mid-run interaction (cancel a run, approve a tool
call, answer an agent's clarifying question) without a second mechanism.
**Your answer:**
yes websocket

**D12 · May the agent edit manuscript text?**
**Recommendation: never directly.** `propose_text_edit` renders as a diff over an anchored range
that you accept, edit, or reject; accepting applies it as a normal editor transaction (undoable,
snapshotted). This keeps "the writer owns the words" mechanically true, not just aspirational.
**Your answer:**
correct. Any proposed edits to the manuscript should have a clear before and after to show changes.

**D13 · Bible extraction trigger**
Options: automatic as you write · on demand only (selection or chapter) · both.
**Recommendation: on demand for 1.0, with the plumbing built so a background trigger is a
scheduler away.** Automatic extraction while drafting burns tokens on prose you are about to
delete and buries the review queue. Manual first makes the feature legible and cheap to test.
**Your answer:**
on demand. token usage should be on purpose by the user.  Maybe an "automatic" in the future, but not a current consideration.

**D14 · Character interaction chart form**
Options: node-link graph · adjacency matrix · both.
**Recommendation: adjacency matrix first (hand-rolled SVG/HTML, no graph library), node-link as
a Phase-8 stretch.** A matrix is unambiguous, sorts and filters well, never turns into a hairball
at 40 characters, and needs no layout engine. It also makes "who has *not* met whom" — a question
writers actually ask — readable at a glance.
**Your answer:**
I agree to the recommendation. This is something i will want to make sure to revisit and understand more when we are building it.

**D15 · Export formats for 1.0**
**Recommendation: Markdown (per chapter and combined) plus a full project bundle (the SQLite
file, or a JSON export of it).** DOCX/EPUB pull heavy dependencies and belong post-1.0.
**Your answer:**
agreed

**D16 · Working name**
"WritingAssistant" is the directory name. **Recommendation: pick a real name now** — it becomes
the Python package, the UI title, and the config namespace, and renaming later touches
everything. Placeholder in these specs is "Writing Assistant" / `writing_assistant`.
**Your answer:**
Archetype

---

## 12. Open Questions To Revisit (not blocking Phase 0)

*These are tracked in [`specs/backlog.md`](backlog.md) with the phase each must be settled by.
Listed here because they touch design, not just features.*

1. Should snapshots be automatic on a timer, on chapter close, or only manual? (Leaning:
   automatic on close + manual "mark version".)
2. Do we need soft-delete/trash for bible entries, or is revision history enough? (Leaning:
   revision history is enough; `superseded` status covers retcons.)
3. Should findings expire when the text they cite changes, or be re-checked? (Leaning: mark
   `outdated` when the cited anchor changes, offer a re-run.)
4. Does the agent get a web-search-style external tool? (Leaning: no for 1.0 — offline story
   consistency is the product.)
5. Multi-tab safety: soft lock, last-write-wins with a warning, or ignore? (Leaning: detect and
   warn; do not build real conflict resolution.)

---

## 13. Document Maintenance

This outline is the root of the spec tree and is expected to change as phases reveal reality.

- Any change to scope, architecture, phase boundaries, or a `D<n>` decision is recorded **here
  first**, then propagated to the affected `phase-N-plan.md` and to `CLAUDE.md`.
- Phase plans record **as-built deviations** from this outline rather than quietly diverging;
  when a deviation is permanent, this document is updated to match.
- Bump the version and date in the header on every substantive edit, and note what changed.
- `CLAUDE.md` must always describe the project as it currently is — never as it was planned.
