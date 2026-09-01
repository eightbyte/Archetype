# Phase 2 — Manuscript Model & Anchors

**Status:** **Active — § 2 ruled, Groups A, B, and C complete** · **Version:** 1.3 · **Date:** 2026-08-30
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

**Ruled by the writer on 2026-08-30, as recommended.** All four are now binding entries in
[`specs/development-phases.md`](development-phases.md) § 1, and the table below is kept as the
reasoning behind them. One clarification made when D22 met the code is recorded in § 7: the
`orphaned` status is *derived* from `deleted_at` on read rather than written into the anchor row,
which is what lets delete and restore stay correct without a second resolver.

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
happened and why (outline § 13).*

### Group A (P2-1 → P2-4), 2026-08-30

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **A1** | P2-1, P2-2 | `anchor.status` holds `ok \| stale \| orphaned`, and `delete()` "re-resolves the document's anchors to `orphaned`" | **`orphaned` is derived on read from `document.deleted_at`, never written to the anchor row.** The stored column holds the text-match answer only (`ok` \| `stale`); the rule lives in both its Python and its SQL form in `archetype/manuscript/anchors/status.py`, and `effective_status` **refuses** a stored `orphaned` rather than passing it through. The plan as written has no correct value for `restore()` to write back: a soft delete changes no text, so neither `ok` nor `stale` would be a fact anyone established, and the resolver that could establish one is P2-6 in Group B. Deriving it makes delete and restore write nothing at all to anchor rows, which is both exactly correct and testable today — the "orphaned, then `ok` again" round trip is asserted in `test_chapters.py` without a resolver existing. **Ruled by the writer before implementation**, so the plan's § 2 table records the reasoning and the D22 register entry is worded to match. Cost: P2-7's `?status=orphaned` filter joins `document` instead of reading the column. |
| **A2** | P2-3 | `restore()` "captures `pre-restore`, then writes the snapshot's content back through `DocumentStore.save_content`", and is "refused on a stale version with nothing written" | Those two sentences conflict if taken in sequence: capturing first and then being refused leaves a snapshot behind. `save_content` therefore grew one keyword-only argument, `before_write`, which runs inside the save's own transaction **after** the version guard passes and **before** the row is overwritten. The `pre-restore` snapshot and the write it protects are one atomic act, so a refused restore leaves nothing — asserted directly in `test_snapshots.py`. The seam is documented as being for work that must share the transaction, **not** a second way to write manuscript text; `save_content` remains the only one of those (data-model § 6). The alternative — pre-flighting the guard, then compensating by deleting the snapshot when the real guard refuses — was rejected as a correctness rule implemented by cleanup. |
| **A3** | P2-3 | Snapshots are "deduplicated by content hash" | **Only `handover` snapshots are deduplicated and pruned.** `manual` and every `pre-*` snapshot is always written and never pruned. Found by a failing test: a `pre-delete` snapshot was being suppressed because a `manual` mark of the same content preceded it. Two reasons to fix it rather than the test. A `manual` mark carries a **label**, and suppressing it because the words had not changed discards the only thing the writer was recording. And a `pre-*` snapshot is a **recovery guarantee**, not a history entry — deduplicating one against a `handover` would leave the only copy of destroyed text in the prunable pool, where a later run of edits could delete it; a data-loss path is a release blocker (outline § 9). D23's stated purpose for dedup is that "an unchanged chapter never accumulates snapshots", and `handover` is the only snapshot nobody asked for, so narrowing it to the automatic case keeps the rule's intent exactly. The D23 register entry is worded to match. |
| **A4** | P2-2 | Four operations on `DocumentStore` | Two read helpers came with them, because a soft delete is not usable without a way to see what is deleted: `list_deleted()` (the restore surface, most recently deleted first) and `include_deleted=` on `list_meta` and `get` (previewing a chapter before restoring it). Both default to excluding deleted chapters, so the D22 predicate is what a caller gets unless it says otherwise. |
| **A5** | P2-2 | — | **The project summary's `deleted_at` predicate is version-gated.** The directory scan reads project files **read-only and unmigrated** (D17), so a version-1 file in the projects directory does not have the column. Asking it for one would turn a perfectly readable project into a skipped one in the picker. `_read_summary` already knows the file's schema version and applies the filter only from version 2. |
| **A6** | P2-1 | "Capture `v001_phase1.sqlite` … by the procedure in that directory's README" | The procedure is now a committed script, `tests/fixtures/db/capture_v001_phase1.py`, rather than a paragraph of instructions. It refuses to run unless the code is at the version it claims to capture, uses fixed ids and timestamps so a re-run is byte-identical, and folds the write-ahead log back in so what lands is one self-contained file. A fixture database is an opaque binary otherwise, and the next migration's fixture should be reviewable rather than trusted. |
| **A7** | P2-4 | `specs/anchors.md` names `CONTEXT_CHARS` and `MAX_QUOTE_CHARS` | It names four more, because the plan asks it to fix "the exact tie-break scoring and thresholds" and those need names to be fixed: `MIN_CONTEXT_SCORE`, `WIN_MARGIN`, `MAX_SUGGESTION_CHARS`, and `RESOLUTION_BUDGET_MS`. Two design points were settled there that the plan left open, and either could change when P2-5 and P2-6 meet real text — § 11 of that document records both as extension points. **(a)** The suggestion for a `stale` anchor is computed from its *unedited surroundings* (two unique substring searches), not from a fuzzy match on its quote; fuzzy quote matching is the machinery that turns into automatic repointing under pressure, and this has no threshold to loosen. **(b)** `text_offset → pm_position` is specified as a **walk** of the block's inline nodes rather than as arithmetic, because the projection trims each line and drops empty ones — so a paragraph carrying a stray trailing space is shorter in `text_plain` than in the document, and arithmetic would point one character early for every character trimmed. Arithmetic stays a legal fast path for a block whose projected length matches its raw length, which is nearly all of them. |

### Carried into Group B — *settled*

- **P2-2's delete and restore write nothing to anchor rows** (A1), so nothing in Group A needed the
  resolver. What Group B must still do is the other half of D21: `save_content` re-resolving the
  document's anchors inside its own transaction (P2-7). The `before_write` seam added in A2 is not
  that — re-resolution runs after the write, against the new text, not before it. **Done in P2-7:**
  `anchors/rewrite.py`, called from inside `save_content`'s transaction.
- **`RESOLUTION_BUDGET_MS` is named but not yet asserted.** The budget test is P2-7's. **Done**
  — see B12.

### Group B (P2-5 → P2-8), 2026-08-30

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **B1** | P2-5 | `Block` carries `pm_from`, `pm_to`, `text_from`, `text_to`, and `mappable` | **It carries a sixth field, `raw`** — the block's inline text *before* the projection trimmed it. Without it the two conversions would need the document JSON as well as the index, which means either holding a reference to the source node inside `Projection` (aliasing a mutable document into a frozen value) or walking the tree a second time to find the node again (the exact thing P2-5 exists to prevent). With it, a conversion is a pure function of the projection alone, the resolver never holds document JSON, and the shortcut `anchors.md` § 2 permits — arithmetic when the block's projected length equals its raw length — is a one-line check rather than a judgement. `Block.to_dict()` emits the five the specification names, so the shared fixture states the index exactly as written. |
| **B2** | P2-5 | "`pm_range → text_span`. The same, in reverse, for both ends" | **The snap is directional: a range start snaps forward to the next mappable text, an end snaps backward.** `anchors.md` § 2 fixes the backward snap for `text_offset → pm_position` and leaves the reverse to "the same, in reverse", which taken literally snaps both ends backward — and then *select all* (`from_pos = 0`, which is inside no block) refuses to yield a range at all, so an anchor over the whole first paragraph is impossible. Snapping each end toward the text the range actually encloses can only ever shrink a range onto real words, and never invents any. |
| **B3** | P2-5, P2-6 | § 8 refuses "a range beginning or ending in a non-mappable block, or spanning one" at creation | **`pm_range_to_text_span` itself refuses a range that spans a scene break**, so the refusal is one rule in one place rather than a creation-time check the resolver could route around. The distinction it draws is a non-mappable block's *text*: a `horizontalRule` reads as five characters nobody typed, so a quote across one would carry them; an empty paragraph contributes nothing, so a range spanning one is ordinary and is allowed. Both are non-mappable, and only the first is unspannable. |
| **B4** | P2-6, P2-8 | `anchors.md` § 10: "A paragraph split through the range → `stale`" | **A bare split resolves `ok`; a split with new words written into the gap is `stale`.** The specification contradicts itself here, and this is the reading that makes it consistent: § 4 collapses whitespace *so that* reflow does not break an anchor, and § 10's neighbouring row says two paragraphs merged across the range stay `ok` "because the separator normalises". A split and a merge are the same operation seen from two sides; a rule cannot normalise the separator in one direction only. So the corpus carries **both** cases — a split with nothing added, and a split with a sentence written into the gap — and `anchors.md` § 10 is corrected to match. **Put to the writer and ruled as built on 2026-08-30**, the contradiction and both readings shown: ruling the other way would mean the resolver compares block structure as well as characters, which also makes the *merge* case `stale` and gives up the reflow guarantee § 4 was written for. |
| **B5** | P2-4, P2-6 | "every constant it names appears in the code by that name" | `MAX_SUGGESTION_CHARS` is spelled **`max_suggestion_chars(quote)`**, a function. Its value is `4 × len(quote) + 2 × CONTEXT_CHARS`, which depends on the anchor, and a module constant cannot. The other five are constants under exactly their names. |
| **B6** | P2-6 | The record the resolver takes is the anchor record | **`AnchorRecord` omits `document_version`.** § 5 notes that when it still matches the document's version the fast path is certain to succeed *unless something wrote text without going through `save_content`* — which is precisely the case anchors exist to survive. So step 1 is checked either way, and carrying the column into the resolver would only be a branch nobody may take. |
| **B7** | P2-6, P2-7 | One new module, `anchors/resolve.py` | **Four.** `resolve.py` is the pure ladder as planned; `records.py` holds the stored anchor; `rewrite.py` is the re-resolution `save_content` calls; `store.py` is the repository. The split is forced by the import direction and is not cosmetic: `DocumentStore.save_content` must call re-resolution, and `AnchorStore` must raise the *same* `StaleVersionError` a save raises — so the two cannot live in one module without a cycle. `anchors/__init__.py` exports only the pure halves, because importing the store from the package `__init__` would re-create the cycle through the back door. |
| **B8** | P2-7 | `GET /api/projects/{pid}/anchors` — "all of them, filterable by `status`" | **It reports the cached answers, not a fresh resolution.** Only the per-document route re-resolves on read (`anchors.md` § 7). Re-resolving the project list would mean projecting every chapter in the manuscript to draw one panel, which is what P1-5 and D2 exist to prevent; the cached answer is refreshed for a chapter the moment it is opened or saved. The plan's route table already distinguishes the two, but a reader could reasonably assume otherwise, so it is written down. |
| **B9** | P2-7 | `PATCH /api/anchors/{aid}` — "re-link to a new range, or change the label" | **A re-link carries all three of `from_pos`, `to_pos`, and `version`, or none of them.** Two of the three is a client that has lost track of which version it is looking at, and inferring the third is how an anchor ends up over text nobody looked at (D19). Refused as a `422` by the wire schema. |
| **B10** | P2-7 | — | **`?status=` is validated at the wire edge as well as in the store.** Found by a route test: the store's `ValueError` reached the unhandled-exception handler, so an unknown status came back as a `500` with a request id instead of a `422` in the envelope. The vocabulary is now spelled in `api/schemas.py` as well as in `anchors/status.py`, and a test asserts the two are the same set — the store keeps its own check for callers that never touch HTTP, which is Phase 6's agent. |
| **B11** | P2-8 | A JSON corpus "in the shape the projection corpus established" | The corpus writes a document as a **list of blocks** — a string is a paragraph, `---` is a scene break, a newline is a hard break — rather than as literal ProseMirror JSON. The node vocabulary is the projection corpus's subject; these cases are about *text*, and spelling seventeen cases × two or three documents as ProseMirror JSON would bury the passage each case is actually about. A case also names its anchor **by the words it covers** rather than by positions, so the harness converts them the way a client's selection would and the case stays readable. |
| **B12** | P2-7 | "A test asserts the shape of that cost at 200 anchors over a 100,000-character chapter" | The test times the **pure resolution pass**, not a save through SQLite: putting disk in the measurement would make a resolver regression look like noise, and it is the resolver the budget guards. Measured **27.5 ms median against the 250 ms budget** on the development machine, with every one of the 200 anchors forced off the fast path. The headroom is the point — `RESOLUTION_BUDGET_MS` exists to catch a change of algorithmic class, not to benchmark a machine. |

### Carried into Group C — *settled*

- **Nothing in `web/` consumes anchors yet.** **Done:** P2-9 draws them, P2-10 lists and repairs
  them. The fake API client still has no resolver, deliberately — see C4.
- **The five anchor routes have no client methods.** **Done:** `ApiClient` grew thirteen methods
  in Group C (five anchor, four chapter, four snapshot), and the hand-written fake implements
  every one.
- **B4 is ruled, not open** (2026-08-30). **Held:** `anchorPlugin.test.ts` asserts that a bare
  split through an anchored range leaves a decoration spanning the block boundary, which is why
  the decoration is a ProseMirror *inline* decoration rather than one span per anchor.

### Group C (P2-9 → P2-12), 2026-08-30

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **C1** | P2-11, P2-12 | Group C is "the application" | **Group C is nine new routes as well.** P2-2 and P2-3 built the stores; nothing exposed them over HTTP, and the plan put "the chapter and snapshot routes" in Group C without listing them. They are: `PUT /api/projects/{pid}/documents/order`, `DELETE /api/documents/{did}`, `POST /api/documents/{did}/restore`, `GET /api/projects/{pid}/documents/deleted`, `GET`/`POST /api/documents/{did}/snapshots`, `GET /api/snapshots/{sid}`, and `POST /api/snapshots/{sid}/restore`. All are in `specs/api-contract.md` §§ 5 and 8, with `test_chapter_routes.py` and `test_snapshot_routes.py` behind them. `DocumentLocator` gained `resolve_snapshot`, so a snapshot is addressed by a bare id for the same reason a document is. |
| **C2** | — | — | **`DocumentMeta` grew `deleted_at`** (extension-only, outline § 7). It is `null` in every list route, because those filter the deleted ones out — and it is the entire content of the restore surface, which needs to say *when* a chapter went. The contract fixtures and `contract.test.ts` moved with it in the same change. |
| **C3** | P2-3, P2-12 | `capture(document_id, reason, label)` | **The wire accepts only `handover` and `manual`.** The three `pre-*` reasons are the server's own, each written inside the transaction of the operation it protects against; a client that could ask for one could put a `pre-delete` in the history with nothing deleted — a lie in the one list a writer consults when something has gone wrong. `SnapshotReasonIn` is a `Literal` in `api/schemas.py`, and a test asserts it is a strict subset of `SnapshotReason.ALL`, the same discipline B10 established for `?status=`. The capture route also answers `{"captured": false, "snapshot": null}` rather than a `409` when dedup suppresses a handover: that is the ordinary answer for a chapter nobody touched. |
| **C4** | P2-9 → P2-12 | The fake API client | **The fake still has no resolver, and now says so in its own docstring.** A save reports **no** moved anchors unless a test has staged what the server answers, through `stageAnchorResolution`. The alternative — a fake that decided for itself whether an edit broke an anchor — would be a second resolver with neither a specification nor a corpus behind it, and every client test would then assert against a rule nobody wrote down. What the fake *does* do is **extract** a quote from a range, because a client never sends one and a store has to be able to answer that; extraction has no thresholds, no candidates, and no status in it. |
| **C5** | P2-9, P2-10 | — | **Anchors live in `ProjectContext`, not beside the open document.** An anchor's lifetime is the project's: the *Marks* tab holds every chapter's at once, and a manual re-link may cross chapters. Two lists — the open document's and the panel's — would need reconciling, and the reconciliation would be the bug. So there is one list, and the open document's anchors are the slice of it whose `document_id` matches. `relinking` (the anchor being re-linked by hand) is there for the same reason: a repair starts in the panel and finishes in the editor, possibly in a different chapter, so it outlives every switch it might involve. |
| **C6** | P2-9 | "a control in the selection's reach" | **Hand-rolled, positioned from `coordsAtPos`.** TipTap's `BubbleMenu` would have added `@tiptap/extension-bubble-menu` and `tippy.js` for one small control, against the standing dependency rule (outline § 8, D10). The control is a real button in the document either way, so it is reachable by keyboard and assertable in a test whether or not a layout engine has opinions. |
| **C7** | P2-9, P2-10 | *Done when:* a mark can be made and re-linked from the editor | **The selection itself cannot be driven through the DOM in jsdom, so the flow is covered in two halves that meet at a typed boundary.** `selectionActions.test.tsx` builds a real TipTap editor, sets the selection through ProseMirror's own command, and asserts the control reports exactly the range that was selected; `anchorsInEditor.test.tsx` drives everything below that call through the real provider stack with small probes standing in for the gesture. Both halves are real code — what is stubbed is the mouse. **This is the Phase 1 finding repeating**: a surface that needs a pointer gesture is not reachable from a test, so the manual acceptance script (§ 5) is what stands under the gesture itself. |
| **C8** | P2-11 | "reorder by drag **and** by keyboard" | **The keyboard path is a *Move up* / *Move down* pair on every chapter, and the arrow keys work on it too.** A grab-and-move mode with `aria-grabbed` was rejected: it is a mode the writer has to learn, and the pair is the same gesture whether it is clicked or reached by tab. Focus is restored to the moved chapter's control after the list redraws — without that, a second press goes nowhere and the interaction is unusable by exactly the people it is for. The drag path is tested by dispatching the events with a stand-in `dataTransfer`, because jsdom has neither `DataTransfer` nor a layout engine; that test proves the handlers are wired, and no more. |
| **C9** | P2-11 | "rename in place" | **Renaming the open chapter goes through `DocumentContext`, every other chapter through `ProjectContext`.** The editor header holds the open chapter's title in its own state, so a second writer of that title would leave the header showing the old one. The Contents tab branches on one line. The row's controls are also renamed for the screen reader — `Departure: rename` rather than `Rename Departure` — because the editor header's control already has the second name and two buttons with one accessible name doing subtly different things is a worse answer than a slightly stiffer phrase. |
| **C10** | P2-12 | "a preview of any snapshot" | **The "now" side of a preview is the chapter's text after a flush, not the content the editor was seeded with.** The seed is what the chapter was when it was *opened*, which is a different chapter by the time anyone reaches for the history. A real diff was cut, as P2-12 permits: the plain before-and-after landed, and D12's before/after requirement is about proposed edits and bites in Phase 4. |
| **C11** | P2-12, D23 | "`handover` … best-effort on unload" | **Handover snapshots are captured on a chapter switch and on leaving the project, and *not* on unload.** The unload path already cannot await the save it starts (P1-10), so a snapshot after it cannot be ordered behind it, and a beacon fired before it would capture the text the save is about to replace. What it would buy is also small: the next open of that chapter captures a handover anyway, and dedup means an unchanged chapter writes nothing. Recorded so that adding it later is a decision rather than a repair. |
| **C12** | P2-9 | — | **The editor's anchor set is pushed into the plugin on a *signature*, not on array identity.** The anchors come out of project state, which is rebuilt on every save, and a transaction per keystroke would discard the mapping the plugin exists to keep. The signature carries id, status, **and positions** — a re-link moves an `ok` anchor without changing its status, and a signature that ignored the range would leave the highlight on the passage the writer had just replaced. |
| **C13** | P2-8, P2-12 | — | **The contract normaliser now builds its id pattern from `IdPrefix.ALL`.** It had `prj|doc|anc|ent|run` spelled out, so `snp_` ids sailed through unnormalised the moment snapshot fixtures existed — which does not fail, it just rewrites two fixtures on every run until the diff stops meaning anything. A test now asserts every registered prefix normalises. |
| **C14** | P2-11 | "delete with a confirmation" | **The client will not delete a project's *last* live chapter — the control is disabled.** The server allows it: a soft delete is recoverable, so there is no data-loss argument for a rule there, and the agent in Phase 6 should not have to know about a UI constraint. But a project with no live chapters has nowhere for the editor to go and nothing for a reorder to present, and P1-12 seeds every new project with one precisely so a writer lands in an editor. Enforcing it at the one surface that could reach the state is cheaper than a rule in the store that every caller then has to work around. |
| **C15** | P2-12 | — | **The snapshot panel reaches the server through `DocumentContext`, not through a client of its own.** Marking a version and previewing one both have to **flush first** — a mark records what is on screen, and a preview's "now" side is what a restore would replace — and a component holding its own client would be a second place that knows when a save has to happen. So `listSnapshots`, `readSnapshot`, and `savedContent` are on the document layer, and no `ApiContext` was added. |
| **C16** | P2-10, P2-11 | "an orphaned anchor's chapter can be restored from here" | **Restoring a chapter re-reads that chapter's anchors rather than un-deriving their status locally.** The first cut had the reducer map `orphaned` back to `ok`, which is wrong: `orphaned` was the chapter showing through a stored `ok` **or `stale`**, and which of the two it is underneath is the server's to say. Guessing `ok` would have been the client deciding an anchor's status — the one thing § 2's ruling 2 forbids, and invisible when wrong. `ProjectContext.restoreChapter` now awaits the restore *and* the per-document anchor list (which resolves on read) before dispatching either, so the panel never draws the moment in between. A test restores a chapter whose mark was already `stale` and asserts it is still `stale`. |

### Carried into Group D

- **The manual acceptance script in § 5 has not been run.** It is the phase-boundary act and it
  covers the two things no test reaches: the pointer gestures (C7, C8) and heavy editing against
  the real resolver rather than a staged answer. Group D runs it and records the results here.
- **`specs/anchors.md` § 4 and § 10 still carry the pre-`B4` wording.** The ruling is recorded in
  this document's § 7; carrying it into `anchors.md` is P2-15's, alongside the rest of the
  documentation pass.
- **The *Marks* tab is the anchors' only consumer, and stays that way.** Phase 3's bible is what
  cites one. Nothing in Group D should widen it.
