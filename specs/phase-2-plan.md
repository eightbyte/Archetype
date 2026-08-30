# Phase 2 — Manuscript Model & Anchors

**Status:** **Draft — awaiting the § 2 rulings** · **Version:** 1.0 · **Date:** 2026-08-30
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1
**Writes:** `specs/anchors.md` (P2-4) · extends [`specs/data-model.md`](data-model.md) and
[`specs/api-contract.md`](api-contract.md) (P2-15)
**Settles:** backlog `Q1` (snapshot trigger) and `Q5` (multi-tab safety)

---

## 1. What this phase is for

Phase 1 made Archetype a place you can write. Phase 2 makes what you wrote **referenceable**.

Three things arrive together, and they arrive together because each is unsafe without the others:

- **Chapter operations** — reorder and delete, alongside the create and rename that already
  exist. A manuscript whose chapters cannot move is an outline you have to plan perfectly in
  advance.
- **Snapshots** — a versioned copy of a chapter, taken automatically at handover and by hand on
  demand. This is what makes deleting a chapter, restoring an old draft, and (in Phase 4) accepting
  an AI rewrite recoverable rather than final.
- **Anchors** — a durable reference to a range of manuscript text that survives the writer editing
  around it. Bible entries cite anchors (Phase 3), findings point at them (Phase 7), and the agent
  quotes them (Phase 6). Nothing above Phase 2 works if this one is wrong.

The outline calls anchors **the single hardest technical problem in the project** (§ 4.2) and the
top entry in its risk table (§ 9): a bible entry citing the wrong passage does not fail loudly, it
quietly destroys trust in every feature built on top. So this phase spends more of its budget on
one small module and its test corpus than the module's size can possibly justify, and the
acceptance bar is not "anchors work" but **"an anchor is never silently wrong."**

The other reason these three ship together: **an anchor is only as durable as the text it points
into is recoverable.** Deleting a chapter, restoring a snapshot, and importing Markdown all change
manuscript text without a keystroke, and each is a way to invalidate every anchor in a document at
once. Building them in the same phase as the resolver is what makes those paths get tested against
it instead of discovered by it.

### Non-goals for Phase 2

Named explicitly, because each is a plausible thing to drift into:

- **No bible.** Nothing cites an anchor yet. Phase 2 gives anchors a manual surface (P2-10) so the
  writer can create, inspect, and repair one; the first real consumer is Phase 3.
- **No AI, no chat, no WebSocket, no search.** Not even a stub route (api-contract § 8).
- **Anchors are text ranges only.** No anchor to a whole chapter, no anchor to a heading, no
  anchor spanning two documents. One shape, resolved one way.
- **No fuzzy resolution.** A quote that has been edited yields `stale` and, at most, a *suggestion*
  the writer accepts by hand. The resolver never picks a passage it is not sure of (§ 2, ruling 6).
- **No merge, no lock.** D19's version guard stands unchanged; `Q5` is settled as "no lock"
  (§ 2, D24). The save protocol from P1-6 is not touched by this phase — only its *response* grows.
- **No purge.** A soft-deleted chapter stays in the file. An "empty trash" surface, and any pruning
  of snapshot storage beyond the retention rule, is Phase 9.
- **No DOCX/EPUB/PDF, and no project bundle.** Markdown per chapter and combined only (D15); the
  bundle is Phase 9.
- **No round-trip promise for the combined export.** Fidelity is asserted per chapter (§ 2,
  ruling 8).
- **No styling investment beyond legibility**, as in Phase 1.

---

## 2. Confirm before code

Phase 1's § 2 existed because a ruling made before files exist costs nothing and the same ruling
made in Phase 3 is a migration. The same applies here, more sharply: four of these become binding
register entries, and two of them settle backlog questions that were due this phase.

### Proposed register entries — D21 to D24

**These are proposals, not yet binding.** They are written in register form so that approving them
is one edit to [`specs/development-phases.md`](development-phases.md) § 1. Nothing in Group B
should be built until D21 is ruled on.

| ID | Proposed decision | Recommendation | Alternative considered | Where it bites if wrong |
|---|---|---|---|---|
| **D21** | Who resolves an anchor, and whose answer wins | **The server re-resolves every anchor of a document from the document's own text on every write, and its answer is authoritative. The client rebases anchor decorations live through ProseMirror's transaction mapping for the open document only, and that rebasing is display-only** — it is never sent, and never overrides a text match. This is D18's rule (the server owns the derived truth; the client mirrors it for liveness) applied to anchors. | The client sends rebased positions with the save, either as the answer or as a tie-break hint. Rejected for Phase 2: ProseMirror's mapping is exact **when it exists**, and it does not exist for an import, a snapshot restore, a file edited outside the app, or a Phase 6 agent proposal. Two resolution paths where the better one is usually absent is worse than one path that is always the same. The hint stays available as a documented extension point if § 5's corpus shows step 4 losing cases that mapping would have kept. | Everything in Group B, the save response shape, and every later consumer of an anchor |
| **D22** | What deleting a chapter does | **A soft delete.** `document` gains a nullable `deleted_at`; the row and its content stay. The chapter leaves every list, outline, and count; its anchors become `orphaned`; restoring it is one click and brings the anchors back. | A hard delete with a `pre-delete` snapshot as the only recovery. Rejected: the snapshot references the document row, so a hard delete either cascades the recovery away or leaves a snapshot pointing at nothing — and "a data-loss path is a release blocker" (outline § 9). One nullable column and one predicate is a cheap price for making an irreversible click reversible. | Migration 002, every document query, the anchor lifecycle, the picker's counts |
| **D23** | When a snapshot is taken (**settles `Q1`**) | **On handover, on demand, and before anything destructive.** `handover` when the editor hands a document over (chapter switch, project close, best-effort on unload); `manual` when the writer marks a version, with a label; `pre-restore`, `pre-delete`, and `pre-import` before an operation that replaces or removes text. Deduplicated by content hash, so an unchanged chapter never accumulates snapshots. Retention: **manual and `pre-*` snapshots are kept forever; the 25 most recent `handover` snapshots per document are kept and older ones pruned in the same transaction that inserts.** | A timer, or manual only. `Q1`'s recorded leaning is exactly what is recommended here. A timer duplicates autosave's job while producing snapshots at moments that mean nothing; manual-only leaves the writer with nothing on the day they need one. | The snapshot table, the client's handover path, project file size |
| **D24** | Multi-tab safety (**settles `Q5`**) | **No lock.** D19's version guard plus the P1-10 conflict surface are the whole answer, and Phase 2 strengthens them: with snapshots, even a clobber is recoverable. `Q5` closes. | A soft lock with a heartbeat. Rejected: a lock introduces a failure mode strictly worse than the one it prevents — a crashed tab holding a lock on a single-user machine, locking the writer out of their own manuscript with no second party to release it. | The save protocol; a lock retrofitted in Phase 9 touches P1-6 and P1-10, which are the two most delicate pieces of Phase 1 |

### Conventions and smaller rulings

Cheap to change now, awkward once files exist.

| | Ruling | Why, and what it costs to reverse |
|---|---|---|
| **1** | **Heading jump stays resolved by ordinal.** Phase 2 adds anchors *alongside* it; it does not replace it. | `specs/data-model.md` § 7 and `CLAUDE.md` both call heading-ordinal jumping "the seam Phase 2 replaces." That reading turns out to be wrong and this plan corrects it: a heading is a structural position that the projection already numbers exactly and re-derives on every save, and minting an anchor per heading would write anchor rows on every save to reproduce an answer that is already free. Anchors are for **cited passages** — arbitrary ranges of prose that no derived structure names. If ruled the other way, P2-9 grows heading anchors and the projection starts writing rows. |
| **2** | **A fuzzy match is a suggestion, never an outcome.** When the quote cannot be found, the anchor becomes `stale` and the resolver may attach a *suggested* range for the re-link UI. Accepting it is a click. | This is the outline's top risk stated as a rule. An anchor that repoints itself to something approximately right is the exact failure that destroys trust, and it is undetectable from the outside. Reversing this is not a code change, it is a change of product promise. |
| **3** | **Markdown: `markdown-it-py` for import, a hand-rolled serializer for export.** One new server runtime dependency — the first since P1-1. | Serializing our closed schema is small, total, and ours to define; parsing CommonMark is neither. A hand-rolled parser gets nested emphasis, lazy continuation, setext headings, and list tightness subtly wrong in ways nobody notices until an import mangles a chapter someone typed. `markdown-it-py` is pure Python, CommonMark-compliant, and has no transitive weight. If refused, P2-14 becomes "a documented Markdown *subset*, rejecting what it does not understand rather than guessing" — which is a defensible product too, just a different one. |
| **4** | **Round-trip fidelity is promised per chapter, over the closed schema.** `import(export(doc)) == doc` for every case in the corpus. The **combined** export is a reading and hand-off artifact, not a round-trip format. | The combined file needs chapter boundaries that the schema has no node for. Promising fidelity there means inventing a container syntax and parsing it back — a private format wearing Markdown's clothes. |
| **5** | **Import creates chapters; it never replaces the text of one.** | `DocumentStore.save_content` stays the only path by which *existing* manuscript text changes (data-model § 6). Import appends new chapters through `create`; replacing a chapter is import-then-delete, both of which are already recoverable. A second text-mutation route is exactly the kind of erosion that makes "the writer owns the words" stop being structural. |
| **6** | **A fifth outline tab, *Marks*.** Anchors are listed there, grouped by chapter, with status and the re-link flow. | The outline panel's four tabs were fixed in P1-9 precisely so the tab strip would not be re-measured later, so widening it is a deliberate act rather than a default. Anchors need a home this phase — the exit criteria are not demonstrable without one — and folding them into Contents would put two unrelated trees in one scroll. In Phase 3 the Bible tab becomes their real consumer and *Marks* may narrow to a stale-anchor surface; that is a Phase 3 decision, not a reason to skip it now. |
| **7** | **New ID prefix `snp_` for snapshots**, registered in `archetype/ids.py` alongside `prj_`, `doc_`, `anc_`, `ent_`, `run_`. `anc_` is already registered and unused; Phase 2 is what uses it. | Prefixes are never reused for a different entity (data-model § 2). Registering it with the migration keeps `IdPrefix.ALL` true. |
| **8** | **Phase 2 adds no configuration keys.** Context width, quote cap, and snapshot retention are module constants, as `MAX_CONTENT_BYTES` is. | A setting is a promise to support every value of it. None of these has a second value anyone wants yet. |
| **9** | **Markdown export is the one non-JSON response in the API**, served as `text/markdown; charset=utf-8` with a `Content-Disposition`. | api-contract § 1 says "JSON in, JSON out". An export is a file a person saves, not a payload a client parses, and wrapping it in JSON just to honour a ground rule would make every client unwrap it. The exception is recorded in the contract rather than left to be noticed. |

---

## 3. The anchor design in brief

The full specification is `specs/anchors.md` (P2-4), written **before** the code it governs. This
section is the shape the work items are sized against, and is the part a reviewer needs in order
to judge them.

### What an anchor stores

| Field | Role |
|---|---|
| `from_pos`, `to_pos` | ProseMirror positions. **The fast path, not the truth** — checked first because when nothing moved it costs one substring comparison |
| `quote` | The anchored text, taken from `text_plain`. This is what the anchor *means* |
| `prefix`, `suffix` | Up to 48 characters of `text_plain` either side. What disambiguates a sentence that appears twice |
| `status` | `ok` \| `stale` \| `orphaned` |
| `document_version` | The document version those positions were true at — a cheap way to know whether the fast path is even worth trying |

### The two coordinate systems, and the index between them

An anchor is authored in **ProseMirror positions** (what a selection gives you, what a decoration
needs) and matched in **`text_plain` offsets** (what the quote and its context live in). These are
not the same space and the relationship is not linear across a document: two sibling paragraphs
are separated by two ProseMirror positions and by the two characters of `BLOCK_SEPARATOR`, but a
paragraph closing a blockquote is separated from the next paragraph by three positions and still
two characters.

They *are* linear **within a text block**: a text node contributes its length to both, and a
`hardBreak` contributes one position and one newline. So the projection gains a **block index** —
for each block it emits, the pair `(pm_from, pm_to, text_from, text_to)` and whether it is
mappable. A `horizontalRule` block is not mappable: it reads as five characters of `* * *` and
occupies one position, and no anchor may begin or end inside it.

This is why P2-5 lands before P2-6: the resolver's output is meaningless without it.

### The matching ladder

Tried in order; the **first** step that produces a confident answer wins.

| # | Step | Outcome |
|---|---|---|
| 1 | **Fast path.** The stored positions still yield exactly `quote` | `ok`, positions unchanged |
| 2 | **Context-unique.** `prefix + quote + suffix` occurs exactly once in `text_plain` | `ok`, relocated |
| 3 | **Quote-unique.** `quote` occurs exactly once | `ok`, relocated |
| 4 | **Quote-ambiguous.** `quote` occurs several times: each candidate is scored on how much of `prefix` and `suffix` it still agrees with. A candidate that clears the threshold **and** strictly beats the runner-up wins | `ok`, relocated — otherwise fall through |
| 5 | **Not found, or no clear winner** | `stale`, positions left where they were, plus a *suggested* range if a bounded similarity search finds a plausible one. The suggestion is never applied |
| 6 | **The document is gone** — soft-deleted or absent | `orphaned` |

Two properties the corpus exists to hold:

- **Status is recomputed, never latched.** An undo that restores a deleted passage returns its
  anchor to `ok` on the next save. A `stale` anchor is a statement about the text as it is now, not
  a mark the anchor carries forever.
- **Matching is whitespace-normalised, offsets are not.** Runs of whitespace are collapsed for
  comparison so that reflowing a paragraph does not break an anchor, and the winning span is mapped
  back to real offsets in the real text before it becomes positions. `anchors.md` fixes the exact
  normal form; getting it wrong in one direction breaks anchors on reflow, and in the other makes
  two different passages compare equal.

### Where it runs

`archetype/manuscript/anchors/resolve.py` is **pure** — `(anchor record, document JSON) →
resolution` — in the same sense `projection.py` is pure, and for the same reason: it is driven by a
JSON corpus rather than by a database, every case is data, and Phase 6's agent gets identical
behaviour without going through HTTP.

It runs in exactly two places:

- **Inside the save transaction**, for every anchor of the document being written, so that the
  stored status is correct no matter who wrote — an editor, an import, a restore, or a Phase 6
  accepted proposal.
- **On read**, without persisting, so a document opened after its file was changed behind the app's
  back reports what is true now rather than what was true at the last write. The stored columns are
  a cache of the last write's answer; the resolver is the answer.

Unlike the projection, this has **one implementation, not two**. The client does not need it: for
the open document ProseMirror's mapping is exact and free, and after a reload the server's answer
arrives with the document.

---

## 4. Work Items

Fifteen items in four groups. The **Done when** line is the acceptance bar — an item without its
tests is not done (outline § 8).

### Group A — The manuscript model (P2-1 → P2-4)

---

**P2-1 · Migration 002, and the fixture database that guards it**

`002_anchors_and_snapshots.sql` — the first real migration, and the one data-model § 8 says the
whole migration pattern exists for.

```sql
ALTER TABLE document ADD COLUMN deleted_at TEXT;          -- NULL = live (D22)

CREATE TABLE anchor (
    id               TEXT PRIMARY KEY,                    -- anc_...
    project_id       TEXT NOT NULL REFERENCES project(id),
    document_id      TEXT NOT NULL REFERENCES document(id),
    from_pos         INTEGER NOT NULL,                    -- ProseMirror positions, the fast path
    to_pos           INTEGER NOT NULL,
    quote            TEXT NOT NULL,
    prefix           TEXT NOT NULL,
    suffix           TEXT NOT NULL,
    status           TEXT NOT NULL,                       -- ok | stale | orphaned
    label            TEXT NOT NULL DEFAULT '',
    document_version INTEGER NOT NULL,                    -- the version those positions were true at
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    checked_at       TEXT NOT NULL                        -- when resolution last ran
);

CREATE TABLE snapshot (
    id           TEXT PRIMARY KEY,                        -- snp_...
    project_id   TEXT NOT NULL REFERENCES project(id),
    document_id  TEXT NOT NULL REFERENCES document(id),
    taken_at     TEXT NOT NULL,
    reason       TEXT NOT NULL,                           -- handover|manual|pre-restore|pre-delete|pre-import
    label        TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,                           -- sha-256 of content_json; dedupe (D23)
    word_count   INTEGER NOT NULL,
    version      INTEGER NOT NULL                         -- the document version this content was
);

CREATE INDEX idx_anchor_document       ON anchor(document_id, from_pos);
CREATE INDEX idx_anchor_project_status ON anchor(project_id, status);
CREATE INDEX idx_snapshot_document     ON snapshot(document_id, taken_at DESC);
```

Extension-only (outline § 7): a column added, two tables added, nothing repurposed. `snp_` is
registered in `archetype/ids.py` and in `IdPrefix.ALL` in the same change.

Capture `server/tests/fixtures/db/v001_phase1.sqlite` — a real Phase 1 project file with two
chapters and content — by the procedure in that directory's README, and test migration 002 against
it. The fixtures directory holds only `v000_empty.sqlite` today; this is the item that makes the
D20 pattern real rather than demonstrated.

*Done when:* a v1 fixture migrates to v2 with its documents intact and readable through
`DocumentStore`; a fresh file reaches v2 in one open; re-opening is a no-op; `latest_version()` is
2 and the consecutive-from-001 check still passes.

---

**P2-2 · Chapter reorder, delete, and restore**

`DocumentStore` grows four operations, and the store keeps carrying every rule (api-contract § 1):

- `reorder(document_ids)` — takes the **complete** ordered list of the project's live chapters and
  rewrites `order_index` to `0..n-1` in one transaction. A list that is not exactly the current set
  — one missing, one extra, one duplicated, one from another project — is refused and nothing is
  written. That set comparison *is* the concurrency guard: a client working from a stale chapter
  list cannot present a complete set, so no project-level version column is needed.
- `delete(document_id)` — takes a `pre-delete` snapshot, sets `deleted_at`, and re-resolves the
  document's anchors to `orphaned`, in one transaction.
- `restore(document_id)` — clears `deleted_at`, re-resolves its anchors, appends it at the end of
  the order rather than guessing where it used to be.
- Every read path — `list_meta`, `get`, `outline`, and the project summary's chapter and word
  counts — filters `deleted_at IS NULL`. One predicate, one place, one test that asserts a deleted
  chapter is absent from **all four**.

Neither reorder, delete, nor restore bumps a document's content `version`: none of them is a text
edit, which is the rule `rename` already follows (data-model § 6).

*Done when:* reorder round-trips and is refused for every malformed set; delete removes a chapter
from all four read paths and leaves its row and content intact; restore brings it back with its
text byte-for-byte; a deleted chapter's anchors are `orphaned` and are `ok` again after restore.

---

**P2-3 · Snapshots: capture, list, and restore (D23)**

`archetype/manuscript/snapshots.py` — a `SnapshotStore` scoped by the same `ProjectHandle`.

- `capture(document_id, reason, label)` — reads the document's current content, hashes it, and
  **writes nothing if the newest snapshot for that document has the same hash**. Prunes `handover`
  snapshots beyond the newest 25 in the same transaction. Manual and `pre-*` are never pruned.
- `list(document_id)` — metadata only: id, `taken_at`, `reason`, `label`, `word_count`, `version`,
  and the stored byte size. Never content. The same discipline as `DocumentMeta` (api-contract § 3).
- `get(snapshot_id)` — one snapshot's content, for preview and diff.
- `restore(snapshot_id, version)` — captures `pre-restore`, then writes the snapshot's content back
  **through `DocumentStore.save_content`** with the presented version, so the restore is an
  ordinary save: it increments `version`, re-derives the projection, re-resolves the anchors, and
  is refused with a `409` if the client is stale. One write path, no exceptions (data-model § 6).

Storage arithmetic, written down because it is the reason for the retention rule: a 20,000-word
chapter is roughly 300 KB of ProseMirror JSON, so 25 `handover` snapshots is about 7.5 MB per
chapter at the ceiling, and a 40-chapter manuscript could reach a few hundred megabytes before
dedup. Dedup by hash removes most of it in practice — a `handover` on an unread chapter writes
nothing. If a real manuscript proves otherwise, compressing `content_json` into a BLOB is the lever,
and it is a Phase 9 measurement, not a Phase 2 guess (§ 6).

*Done when:* capture dedupes by hash; retention prunes only `handover` snapshots and keeps the
newest 25; restore round-trips content exactly, bumps `version`, re-derives word count and
headings, and is refused on a stale version with nothing written.

---

**P2-4 · `specs/anchors.md`**

The specification, written **before** Group B's code, in the shape `projection.py`'s docstring
established: the rules stated once, in prose, so that two readers and one test corpus can agree on
them. It settles, at minimum:

- The anchor record and its lifecycle, `ok` → `stale` → `ok`, and `orphaned`;
- The two coordinate systems and the block index (§ 3);
- The matching ladder, step by step, with the exact tie-break scoring and thresholds;
- The whitespace normal form used for comparison, and how a match maps back to real offsets;
- `CONTEXT_CHARS` (proposed: 48) and `MAX_QUOTE_CHARS` (proposed: 4000), with the reasoning;
- What is refused at creation: a zero-length range, a range crossing a non-mappable block, a range
  outside the document, a quote over the cap;
- The suggestion protocol for a `stale` anchor — how one is computed, and that it is never applied;
- What an anchor does **not** promise, in as many words.

*Done when:* the document exists, the corpus in P2-8 is written *from* it rather than from the
code, and every constant it names appears in the code by that name.

---

### Group B — Anchors (P2-5 → P2-8)

---

**P2-5 · The block index — extending the projection**

`Projection` gains `blocks: tuple[Block, ...]`, where a `Block` carries `pm_from`, `pm_to`,
`text_from`, `text_to`, and `mappable`. Produced by the same walk that produces `text_plain`, in the
same module, because two walks over the same tree is two chances to disagree about what a block is.

Two conversions, both pure and both tested at their edges: `text_offset → pm_position` and
`pm_range → text_span`. An offset that lands in a non-mappable block, or between blocks in the
`BLOCK_SEPARATOR`, has a defined answer rather than an accidental one.

This is an **extension-only** change to a Phase 1 shape: `text_plain`, `headings`, and `word_count`
keep their meaning and their values, and the shared fixture file gains an optional `blocks` key on
each case. The client mirror reads named keys, so it ignores the new one and stays green without
being touched — the mirror does not need the index (§ 3), and giving it one would be a second
implementation with no second reader.

*Done when:* every existing projection case still passes on both sides unchanged; the index is
asserted for nesting, scene breaks, hard breaks, empty blocks, and blockquoted lists; the two
conversions round-trip for every mappable offset in the corpus.

---

**P2-6 · The resolver**

`archetype/manuscript/anchors/resolve.py` — pure, no I/O, no database, no framework. The ladder
from § 3, returning a resolution: the new status, the new positions when it moved, and a suggestion
when it did not.

The whole module is written against `specs/anchors.md`, and its docstring carries the rules the way
`projection.py` does, because it is the second most-reused piece of logic in the project.

*Done when:* every case in the P2-8 corpus passes; the ladder's steps are individually reachable
and individually tested; the module imports nothing from `archetype.projects` or `archetype.api`.

---

**P2-7 · The anchor store, the routes, and re-resolution on write**

`AnchorStore`, scoped by `ProjectHandle`, and the routes that expose it.

**The server derives the quote and its context; the client sends only a range.** `POST` carries
`{from_pos, to_pos, version, label?}`, and the server extracts `quote`, `prefix`, and `suffix` from
the *stored* content through the block index. A client cannot create an anchor whose quote
disagrees with the manuscript, and a range presented against a stale version is refused with a
`409` exactly as a save is — an anchor over text that has since changed is an anchor over text
nobody looked at.

| Method | Route | Notes |
|---|---|---|
| `POST` | `/api/documents/{did}/anchors` | Create from a range. `409` on a stale version |
| `GET` | `/api/documents/{did}/anchors` | This document's anchors, resolved on read, not persisted |
| `GET` | `/api/projects/{pid}/anchors` | All of them, filterable by `status` — how the *Marks* tab finds what needs repair |
| `PATCH` | `/api/anchors/{aid}` | Re-link to a new range, or change the label. Re-linking re-derives quote and context |
| `DELETE` | `/api/anchors/{aid}` | Remove one |

And the piece that makes D21 real: **`save_content` re-resolves the document's anchors inside its
own transaction**, and `SaveResultOut` grows an `anchors` field carrying every anchor whose status
or position moved. Extension-only on the wire, and it saves the client a round trip on the one
request that happens most often.

Cost, budgeted rather than assumed: resolution is `O(anchors × text length)` in the worst case,
run on every autosave. A test asserts the shape of that cost at 200 anchors over a 100,000-character
chapter and fails if it exceeds the budget `anchors.md` names, so a resolver that gets cleverer and
slower is caught by the suite rather than by a writer whose typing has started to stutter.

*Done when:* every route has a happy path and a not-found test; a stale-version create is refused
with nothing written; a save moves the anchors it should and reports them; a save that changes
nothing reports no anchor changes; the resolution budget test passes.

---

**P2-8 · The anchor test suite**

The outline promises anchors "its own dedicated test suite" (§ 4.2). This is that item, and it is
the one that decides whether Phase 2 is trustworthy.

- **A JSON corpus** — `server/tests/fixtures/anchors/cases.json`, in the shape the projection
  corpus established: each case is `(document before, anchored range, document after, expected
  outcome)`, hand-written from `anchors.md` as the specification rather than recorded from the
  code. It covers, at minimum: an edit far above, far below, immediately before, immediately after,
  and inside the range; the quote deleted; the quote duplicated elsewhere; the quote already
  appearing twice at creation; a paragraph split through the range; two paragraphs merged across
  it; a reflow that changes only whitespace; the document emptied; the document restored by undo.
- **Property tests** over generated edits: for a corpus of documents and anchors, applying N random
  edits that do not touch the anchored text must leave the anchor `ok` and pointing at the same
  characters — the exit criterion stated as a property rather than as an anecdote.
- **The negative property, which matters more:** across every case, an anchor that ends `ok` points
  at text equal to its quote. There is no case in which the resolver returns `ok` and is wrong.
  Everything else in this phase can be fixed later; this one cannot be detected later.

*Done when:* the corpus runs green, the properties hold over a seeded generator, and the negative
property is asserted across the whole corpus rather than per case.

---

### Group C — The application (P2-9 → P2-12)

---

**P2-9 · Anchors in the editor**

A ProseMirror plugin holding the open document's anchors as decorations, mapped through each
transaction's `mapping` so a highlight follows the text as the writer types above it. Display-only
(D21): the mapped positions are never sent.

- An anchored range renders as a subtle underline; a `stale` one renders differently and is
  reachable from the *Marks* tab rather than being invisible in the text.
- A range whose content is entirely deleted collapses, and shows as pending until the save answers.
- The save response replaces the client's set with the server's (D18's rule again).
- Creating an anchor: select text, then a control in the selection's reach. The client sends the
  ProseMirror range and the document version, and nothing else.

*Done when:* an anchor's decoration survives typing above, below, and around it without a save; a
deleted anchored range collapses and reconciles to `stale` when the save returns; the editor holds
its decorations across a chapter switch and back.

---

**P2-10 · The Marks tab and re-linking**

The fifth outline tab (§ 2, ruling 6): every anchor in the project, grouped by chapter, each showing
its quote, its status, and its label. Filter by status, so "what is stale" is one click.

Re-linking is the repair path and it is the reason this surface exists: a `stale` anchor offers its
suggestion when it has one, with the old quote and the suggested passage side by side, and *Use
this* / *Pick manually* / *Delete*. Picking manually means selecting text in the editor and
confirming — the same `PATCH` either way. An `orphaned` anchor offers to restore its chapter.

Nothing is ever repaired automatically, and the tab says which anchors need attention rather than
quietly fixing them.

*Done when:* a stale anchor's suggestion can be accepted and returns it to `ok`; manual re-linking
works across chapters; an orphaned anchor's chapter can be restored from here; the tab reflects
status changes that arrive on a save response without a refetch.

---

**P2-11 · Chapter management in the UI**

The Contents tab grows what P2-2 made possible: reorder by drag **and** by keyboard (the P1-9 rule
— hand-rolled and accessible, not mouse-only), rename in place, delete with a confirmation that
says what will happen to the chapter's anchors, and a way to see and restore deleted chapters.

Delete is recoverable (D22), so the confirmation can be brief; the undo path is what carries the
safety, not the dialogue.

*Done when:* reorder works by drag and by keyboard and persists; the outline and editor follow a
reorder without a reload; deleting the open chapter moves the editor somewhere sensible rather than
leaving it holding a ghost; a deleted chapter can be found and restored.

---

**P2-12 · Snapshot history in the UI**

Per chapter: the snapshot list with when, why, and how many words; a preview of any snapshot; and
restore, which warns that the current text will be snapshotted first and then replaced. Plus *Mark
this version*, with a label.

A diff between a snapshot and the current text is **desirable, not required** — if the plain
before/after preview lands and a real diff does not, that is the correct thing to cut, and D12's
before/after requirement bites in Phase 4, not here. Recorded so that cutting it is a decision
rather than a shortfall.

*Done when:* the history lists what was taken and why; a manual mark appears immediately with its
label; restoring replaces the text, bumps the version, and leaves the pre-restore snapshot in the
list; the editor reloads to the restored content without the writer losing their place in the app.

---

### Group D — Markdown and close-out (P2-13 → P2-15)

---

**P2-13 · Markdown export (D15)**

`archetype/manuscript/markdown/serialize.py` — closed schema in, Markdown out. Total by
construction: every node and mark in `ALLOWED_NODES` and `ALLOWED_MARKS` has a case, and the test
that enumerates them fails if the schema grows a node the serializer has not been taught.

Headings `#`/`##`/`###`, bold `**`, italic `*`, blockquote `>`, bullet `-`, ordered `1.`,
`horizontalRule` as `* * *` (the same `SCENE_BREAK` the projection uses, so a scene break reads the
same everywhere), `hardBreak` as a backslash at end of line. Escaping is the fiddly part and gets
its own cases: a paragraph that begins with `#`, `-`, `>`, or a number and a dot must come back as
itself.

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/documents/{did}/markdown` | One chapter, `text/markdown` (§ 2, ruling 9) |
| `GET` | `/api/projects/{pid}/markdown` | Every live chapter in order, each preceded by its title as an H1 |

*Done when:* every node and mark has a case; escaping round-trips; the combined export contains
every live chapter in order and no deleted one.

---

**P2-14 · Markdown import**

`POST /api/projects/{pid}/import` — `{markdown, mode}` where mode is `one-chapter` or `split-on-h1`,
creating chapters appended at the end through `DocumentStore.create` (§ 2, ruling 5). Anything the
closed schema cannot hold — a table, an image, a code fence, a footnote — is reported in the
response as what was dropped and where, never silently discarded.

The round-trip corpus is the acceptance bar: for every case, `import(export(doc))` is the same
document, compared as ProseMirror JSON. The corpus is the same one P2-13 uses, which is what makes
the two halves hold each other honest.

*Done when:* the round-trip corpus passes both directions; an import reports what it dropped;
a document too large for `MAX_CONTENT_BYTES` is refused before anything is created; importing a
file that is not Markdown at all produces prose, not an error, because a plain text file is valid
Markdown and a writer will try it.

---

**P2-15 · Documentation and phase close-out**

- **`specs/anchors.md`** — reconciled with what was built (it was written in P2-4 against what was
  planned).
- **`specs/data-model.md`** — the anchor and snapshot tables and the `deleted_at` column move from
  § 7's sketch into § 3's as-built half; § 2's prefix table gains `snp_`; § 7 drops what shipped and
  keeps what has not; the "seam Phase 2 replaces" line in § 7 is corrected per § 2, ruling 1.
- **`specs/api-contract.md`** — every new route, the extended `SaveResultOut` and `DocumentMeta`,
  the non-JSON export exception, and § 8's "absent" table updated to move what arrived.
- **`specs/backlog.md`** — `Q1` and `Q5` move to § 3, *Promoted*, with the date and the ruling.
- **`specs/development-phases.md`** — D21 to D24 promoted into § 1 as ruled; the Phase 2 row in § 2
  closed.
- **`specs/project-outline.md`** — § 5's sketch and § 6's phase table brought level; version bumped.
- **`CLAUDE.md`** — Phase 2 recorded as complete, the new invariants added, the heading-ordinal
  claim corrected, and the file describing the project as it now is.
- **As-built deviations** — § 7 below, written in the same change that diverges.

*Done when:* all eight documents match the code, and a reader who has never seen the project can
create an anchor, break it, and repair it using only what is written down.

---

## 5. Exit Criteria

Phase 2 is done when **all** of these hold.

1. **An anchor created before an editing session still resolves to the right passage** after heavy
   editing above, below, and around it — including edits that did not come from the editor
   (a Markdown import, a snapshot restore, a chapter deleted and restored).
2. **Deleting the anchored text yields `stale`, never a wrong match.** Across the whole corpus,
   every anchor that reports `ok` points at text equal to its quote — asserted as a property, not
   demonstrated by an example.
3. **A `stale` anchor can be repaired by hand**, from a suggestion or by selecting new text, and
   nothing repairs itself.
4. Chapters can be **created, renamed, reordered, deleted, and restored**; a deleted chapter is
   gone from every list and count, its text is not, and its anchors are `orphaned` rather than
   destroyed.
5. **Snapshots** are taken on handover, on demand, and before anything destructive; the history is
   browsable; restoring writes through the save protocol, re-derives the projection, and
   re-resolves the anchors.
6. **A chapter exports to Markdown and re-imports to an identical document** for every case in the
   corpus.
7. **Migration 002 runs against a captured version-1 fixture database** in a test, with its
   documents intact afterward (D20).
8. `pytest` and `vitest` are both **green**, and the resolver (P2-6) and the block index (P2-5) have
   tests covering their edges, not just their happy paths.
9. `specs/anchors.md` exists and describes what was built; the other seven documents in P2-15 match
   the code.

**Manual acceptance script** (run by hand at the phase boundary, results recorded in § 7):

Open the Phase 1 test manuscript → create three anchors in one chapter: one in the first paragraph,
one mid-chapter, one in the last → **edit heavily**: add two paragraphs above the first, rewrite a
paragraph between the second and third, and delete a paragraph below the last → confirm all three
still highlight the passages they were made over → **delete the text under the second anchor** →
confirm it goes `stale` and does not move → repair it by hand → **mark a version**, edit the
chapter substantially, then restore the mark → confirm the text returns and the anchors resolve →
**reorder** the chapters and confirm the outline and editor follow → **delete a chapter**, confirm
its anchors go `orphaned`, restore it, confirm they return → **export** a chapter to Markdown,
re-import it as a new chapter, and compare the two on screen.

---

## 6. Risks in this phase

| Risk | Why it bites | Mitigation |
|---|---|---|
| **The resolver gets clever and starts guessing.** The pressure is real: every `stale` anchor is a small annoyance, and each individual loosening looks reasonable. | A wrong match is invisible. It does not fail, it just quietly cites the wrong paragraph forever, which is the outline's top risk (§ 9). | § 2 ruling 2 is a product promise, not a preference. The negative property in P2-8 is asserted across the whole corpus. A fuzzy result is a suggestion with a click on it. |
| **The block index and the projection drift**, so an anchor's positions and its quote describe different text. | Every anchor in the project becomes subtly wrong at once, and the symptom looks like a resolver bug. | One walk, one module, one fixture file (P2-5). The index is produced by the code that produces `text_plain`, not alongside it. |
| **Re-resolution on every autosave becomes a performance problem** on a long chapter with many anchors. | Autosave runs every 1.5 seconds while someone is typing. A slow save is felt as a slow editor. | A budgeted test at 200 anchors over 100,000 characters (P2-7), failing on regression rather than on complaint. |
| **Soft delete leaks.** One query that forgets `deleted_at IS NULL` puts a deleted chapter back in a count, an outline, or an export. | It surfaces as a wrong word count or a ghost chapter in an export — reported as a different bug entirely. | One predicate in the store, and one test that asserts absence from the document list, the outline, the project summary counts, and the combined Markdown export together. |
| **Markdown promises more fidelity than it can keep.** | An import that mangles a chapter is data loss with a friendly name. | Fidelity is promised per chapter over the closed schema and asserted by a round-trip corpus; the parser is a library, not ours (§ 2, ruling 3); what cannot be represented is reported, not dropped. |
| **Snapshot storage grows faster than anyone notices.** | A project file that quietly reaches a gigabyte is a backup that stops being a file copy — which is D3's whole premise. | Hash dedup, retention on `handover` snapshots, and the arithmetic written into P2-3 so the ceiling is known rather than discovered. |
| **Scope leaks toward the bible**, because an anchor with nothing citing it feels unfinished. | Phase 3's entry schema is a larger design than it looks, and starting it inside Phase 2 means finishing neither. | The *Marks* tab is the anchor's only consumer this phase, and it is deliberately thin. Entries are Phase 3. |
| **The editor's failure surfaces stay hard to reach** — the finding carried forward from the Phase 1 acceptance run. | Phase 2 adds more of them: a stale anchor, an orphaned anchor, a refused reorder, a restore conflict. | Each new failure state gets a test through the fake client at the time it is built, not a promise to test it later. The Phase 1 record says plainly that these tests are the only thing standing under those surfaces. |

---

## 7. As-Built Deviations

*Every divergence from this plan is recorded here in the same change that makes it, with what
happened and why (outline § 13). Empty until Phase 2 begins.*
