# Archetype — Data Model

**Status:** Schema version 3 as built; later phases sketched · **Version:** 1.3 ·
**Date:** 2026-09-03
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1
(D3, D18, D19, D20, D21, D22, D23, D25, D26, D27, D28)
**Companions:** [`specs/api-contract.md`](api-contract.md) — the same vocabulary on the wire ·
[`specs/bible.md`](bible.md) — what the four Phase 3 tables *mean*

This document has two halves and they are not equally binding.

**§ 1–6 describe what exists.** They are generated from the code and are a bug if they disagree
with it. The authority for a table is the migration that created it; this document is the reading
guide.

**§ 7 sketches what is coming.** It is the outline § 5 sketch carried forward, refined where a
Phase 1 decision has already constrained it. Nothing in § 7 is binding, and a later phase is free
to arrive at a different shape — but it amends this document in the same change that does.

---

## 1. Shape of the store

**One SQLite file per project (D3).** No server, no shared database, no registry file. A project
is `data/projects/<slug>-<token>.sqlite`, and everything about that project — its text, and in
later phases its bible, anchors, chunks, embeddings, and run records — is inside that one file.

Three consequences the code depends on:

- **Backup is a file copy**, and a copy dropped back into the directory reappears in the list
  with no import step (D17).
- **The project list is a directory scan.** There is nothing to keep in sync, so nothing can
  disagree with the filesystem. A `.sqlite` file that is not an Archetype project is skipped and
  reported, never fatal (§ 4).
- **Cross-project queries do not exist.** Every query is inside one file, which is what makes the
  `ProjectHandle` scope in `projects/store.py` sufficient rather than merely conventional.

There is no ORM (D20). SQL is written out, in the module that owns the table.

### Connections

`projects/db.py` opens every connection the same way:

| Setting | Value | Why |
|---|---|---|
| `foreign_keys` | `ON` | Referential integrity enforced, not documented |
| `journal_mode` | `WAL` | The outline scan reads while autosave writes |
| `busy_timeout` | 5000 ms | A brief lock waits instead of raising |
| `isolation_level` | `None` | Transaction control is explicit — `BEGIN` and `COMMIT` are written, never implied |
| `row_factory` | `sqlite3.Row` | Columns are read by name |

Connections are short-lived: open, work, close. No pool.

`connect(path, read_only=True)` opens through a `file:…?mode=ro` URI and is used **only** by the
directory scan and the document locator — the two paths that run *before* a project has been
deliberately opened. Reads made through an opened project use an ordinary connection, because a
read-only handle cannot recover a write-ahead log left behind by an unclean shutdown, and every
read after a crash would then fail.

---

## 2. Identifiers and timestamps

**IDs are prefixed short tokens.** `prj_4k2h9wq0mzbt` — a two-to-eight letter prefix, an
underscore, then twelve characters of Crockford base32 with the ambiguous glyphs (`i`, `l`, `o`,
`u`) removed. Twelve characters over a 32-symbol alphabet is 60 bits; the alphabet is chosen so
an ID survives being read out of a log line or spoken aloud.

| Prefix | Entity | Arrives |
|---|---|---|
| `prj_` | project | Phase 1 |
| `doc_` | document | Phase 1 |
| `anc_` | anchor | Phase 2 |
| `snp_` | snapshot | Phase 2 |
| `ent_` | bible entry | Phase 3 |
| `run_` | agent run | Phase 6 |

Prefixes are registered in `archetype/ids.py` and are never reused for a different entity.
`random_token(n)` is the same alphabet without a prefix, for values that disambiguate rather than
identify — the suffix on a project filename is one, and keeping it out of `new_id` is what lets
IDs keep their eight-character minimum.

**Timestamps are UTC ISO-8601 with a `Z`**, second precision: `2026-08-30T20:40:52Z`. Every
`created_at` and `updated_at` in the store, every timestamp on the wire. They are formatted for
display in exactly one place on the client (`web/src/format.ts`), so a formatted string can never
leak back into a comparison.

---

## 3. Tables as built (schema version 3)

Created by `archetype/projects/migrations/001_init.sql` and extended by
`002_anchors_and_snapshots.sql` and `003_bible.sql`. Types are SQLite's, which means `TEXT` holds
UTF-8 and `INTEGER` holds a signed 64-bit integer.

Migration 003 is **extension-only in the strongest sense**: four tables added, and **not one
column changed** on `document`, `anchor`, or `snapshot`. Phase 3 adds no manuscript behaviour — it
reads anchors through `AnchorStore` and creates them through `AnchorStore.create`, which is the
only path there has ever been.

### `schema_version`

| Column | Type | Notes |
|---|---|---|
| `version` | `INTEGER PRIMARY KEY` | The migration number |
| `applied_at` | `TEXT NOT NULL` | UTC ISO-8601 |

One row per applied migration. Its **presence is how a file is recognised as an Archetype
project**: the scan reads `MAX(version)`, and a file with no `schema_version` table is version 0
and is skipped as "not an Archetype project" rather than migrated (§ 4).

### `project`

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | `prj_…` |
| `title` | `TEXT NOT NULL` | 1–200 characters, trimmed |
| `created_at` | `TEXT NOT NULL` | UTC ISO-8601 |
| `updated_at` | `TEXT NOT NULL` | Stamped by **every** document write, in the same transaction |
| `settings_json` | `TEXT NOT NULL DEFAULT '{}'` | Per-project settings. Unused in Phase 1; the column exists so Phase 4 adds no migration for it |

**Exactly one row.** The file *is* the project (D3), so the row carries identity rather than
selecting among several. `open_path` reads it with `LIMIT 1`, which is what lets a project file
be resolved from its path alone — the id inside is authoritative, not the filename.

`updated_at` is stamped inside the same transaction as the document write that caused it. The
picker sorts on it, and a project whose chapter changed a minute ago must not claim it was last
touched when it was created.

### `document`

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | `doc_…` |
| `project_id` | `TEXT NOT NULL REFERENCES project(id)` | Always the one project in the file |
| `order_index` | `INTEGER NOT NULL` | Position in the manuscript, from 0 |
| `title` | `TEXT NOT NULL` | 1–200 characters. Defaults to `Chapter N` |
| `kind` | `TEXT NOT NULL DEFAULT 'chapter'` | Phase 1 writes only `chapter` |
| `content_json` | `TEXT NOT NULL` | **The manuscript.** TipTap/ProseMirror JSON (D1, D15) |
| `text_plain` | `TEXT NOT NULL` | Derived (D18) |
| `headings_json` | `TEXT NOT NULL` | Derived (D18) — a JSON array of `{level, text, ordinal}` |
| `word_count` | `INTEGER NOT NULL` | Derived (D18) |
| `version` | `INTEGER NOT NULL` | Concurrency guard (D19). Starts at 1 |
| `created_at` | `TEXT NOT NULL` | UTC ISO-8601 |
| `updated_at` | `TEXT NOT NULL` | Moved by a save, a rename, a delete, and a restore — **not** by a reorder |
| `deleted_at` | `TEXT` | `NULL` while the chapter is live; a UTC timestamp once soft-deleted (D22, migration 002) |

Index: `idx_document_project_order ON document(project_id, order_index)` — the document list and
the outline both read one project's chapters in that order. Deliberately **not** `UNIQUE`, because
the reorder moves rows through transient duplicate indices.

**Deleting a chapter is a soft delete (D22).** The row and its content stay; `deleted_at` goes
from `NULL` to a timestamp. Every read path filters `deleted_at IS NULL` — `list_meta`, `get`,
`outline`, `list_content` (which is what the combined Markdown export reads, P2-13), and the
project summary's chapter and word counts — and the trash surface asks for the deleted ones
explicitly through `list_deleted()`. One predicate in one place, because a single query that
forgets it puts a ghost chapter into a count or into a file somebody has already sent to a
reader, and is then reported as a different bug entirely.

The summary's predicate is **version-gated**: the directory scan reads files it has deliberately
not migrated (§ 4), and asking a version-1 file for `deleted_at` would turn a perfectly readable
project into a skipped one.

**Reorder, delete, and restore do not bump `version`** — none of them is a text edit, which is the
rule `rename` already follows (§ 6). Reorder does not move any document's `updated_at` either: the
order is a property of the project, not of any one chapter, and stamping forty chapters because
one moved would make "last edited" mean nothing.

**`content_json` is the only authored column.** The four that follow it are derived from it on
every write and are never written independently. Storing them is a deliberate denormalisation:
`GET /api/projects/{pid}/outline` draws a whole manuscript's table of contents by reading
`headings_json` and `word_count` alone, without loading a single chapter's content (D2, D18).

**Ordering is `ORDER BY order_index, created_at, id`.** The two tiebreakers make the order total
even while duplicate indices exist, so a list never shuffles under a reader mid-reorder.

### `anchor`

A durable reference to a range of manuscript text. `specs/anchors.md` is the authority on how one
resolves; this is what is stored.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | `anc_…` |
| `project_id` | `TEXT NOT NULL REFERENCES project(id)` | |
| `document_id` | `TEXT NOT NULL REFERENCES document(id)` | An anchor lives in exactly one document |
| `from_pos`, `to_pos` | `INTEGER NOT NULL` | ProseMirror positions. **The fast path, not the truth** |
| `quote` | `TEXT NOT NULL` | The anchored text, from `text_plain`. What the anchor *means* |
| `prefix`, `suffix` | `TEXT NOT NULL` | Up to `CONTEXT_CHARS` either side. What tells two identical sentences apart |
| `status` | `TEXT NOT NULL` | `ok` or `stale` — the **text-match** answer only |
| `label` | `TEXT NOT NULL DEFAULT ''` | The writer's note |
| `document_version` | `INTEGER NOT NULL` | The version those positions were true at |
| `created_at`, `updated_at` | `TEXT NOT NULL` | |
| `checked_at` | `TEXT NOT NULL` | When resolution last ran, which may be long after `updated_at` |

Indexes: `idx_anchor_document ON anchor(document_id, from_pos)` — the editor loads one document's
anchors in position order; `idx_anchor_project_status ON anchor(project_id, status)` — the *Marks*
tab finds what needs repair across the project.

**`orphaned` is derived, never stored.** A reader sees `orphaned` when the owning document's
`deleted_at` is set, and the stored column holds only what the resolver concluded about the text.
The rule lives in exactly one module, in both its Python and its SQL form
(`archetype/manuscript/anchors/status.py`), and `effective_status` refuses a stored `orphaned`
rather than passing it through.

The reason for the split is that a soft delete changes no text. The cached text answer is as true
while the chapter is away as it was before it went, so restoring the chapter returns every anchor
to the answer the resolver actually gave — with nothing re-derived, nothing invented, and no
second resolver needed to undo a delete.

### `snapshot`

A versioned copy of one chapter (D23).

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | `snp_…` |
| `project_id` | `TEXT NOT NULL REFERENCES project(id)` | |
| `document_id` | `TEXT NOT NULL REFERENCES document(id)` | Kept when the chapter is soft-deleted, which is what makes the delete reversible |
| `taken_at` | `TEXT NOT NULL` | UTC ISO-8601 |
| `reason` | `TEXT NOT NULL` | `handover` \| `manual` \| `pre-restore` \| `pre-delete` \| `pre-import` |
| `label` | `TEXT NOT NULL DEFAULT ''` | Set on a `manual` mark |
| `content_json` | `TEXT NOT NULL` | The copy |
| `content_hash` | `TEXT NOT NULL` | SHA-256 of `content_json`; the dedupe key |
| `word_count` | `INTEGER NOT NULL` | Copied from the document row, not re-derived |
| `version` | `INTEGER NOT NULL` | The document version this content was |

Index: `idx_snapshot_document ON snapshot(document_id, taken_at DESC)` — the history reads one
chapter, newest first.

**Automatic and deliberate snapshots are stored differently.** `handover` is the only snapshot
nobody asked for, and it is the only one that is deduplicated (nothing is written when the newest
snapshot holds the same content) and the only one that is pruned (to the newest
`HANDOVER_RETENTION` = 25 per document, in the same transaction that inserts). `manual` and every
`pre-*` snapshot is always written and never pruned: a manual mark carries a label, and a `pre-*`
snapshot is a recovery guarantee rather than a history entry — deduplicating one against a
`handover` would leave the only copy of destroyed text sitting in the prunable pool.

**A `pre-*` snapshot is written inside the transaction of the thing it protects against**, so a
refused delete or a restore refused as stale leaves no snapshot behind. For a restore that means
`save_content` takes a `before_write` hook that runs after the version guard passes and before the
row is overwritten. The hook is for work that must share the transaction; it is **not** a second
way to write manuscript text (§ 6).

**Storage arithmetic**, written down so the ceiling is known rather than discovered: a
20,000-word chapter is roughly 300 KB of ProseMirror JSON, so 25 `handover` snapshots is about
7.5 MB per chapter at the ceiling. Dedup removes most of that in practice. If a real manuscript
proves otherwise, compressing `content_json` into a BLOB is the lever, and it is a Phase 9
measurement rather than a Phase 2 guess.

### `entry`

One bible record — **all seven kinds share it** (D26). The difference between a character and a
place is `kind` plus the contents of `attributes_json`; the per-kind field list lives in
`archetype/bible/schema.py` and is served by `GET /api/bible/schema`, and it lives nowhere else.

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | `ent_…` |
| `project_id` | `TEXT NOT NULL REFERENCES project(id)` | |
| `kind` | `TEXT NOT NULL` | `character` \| `place` \| `item` \| `faction` \| `event` \| `thread` \| `fact`. **Immutable after creation** |
| `name` | `TEXT NOT NULL` | Not unique; the bible is not a namespace |
| `summary` | `TEXT NOT NULL DEFAULT ''` | One line. What a list shows, and what Phase 6 puts in a context budget |
| `body_md` | `TEXT NOT NULL DEFAULT ''` | Markdown **as text**, not as a schema — an entry is a note, not a manuscript |
| `attributes_json` | `TEXT NOT NULL DEFAULT '{}'` | The per-kind fields, validated against the served definition |
| `status` | `TEXT NOT NULL` | `proposed` \| `accepted` \| `rejected` \| `superseded`. Only `accepted` has a writer in Phase 3 |
| `origin` | `TEXT NOT NULL` | `user` \| `agent`. Only `user` has a writer in Phase 3 |
| `revision` | `INTEGER NOT NULL` | Monotonic. The D19 guard, applied to entries |
| `needs_review` | `INTEGER NOT NULL DEFAULT 0` | The retcon flag (D27) |
| `review_reason` | `TEXT NOT NULL DEFAULT ''` | What set it: the entry and the revision that moved |
| `created_at` / `updated_at` | `TEXT NOT NULL` | UTC ISO-8601 |
| `deleted_at` | `TEXT` | `NULL` = live (D25) |

Indexes: `idx_entry_project_kind ON entry(project_id, kind, name)` — the browser lists one
project's entries of one kind by name; `idx_entry_review ON entry(project_id, needs_review)` — the
review queue finds the flagged ones without scanning.

**`kind` is immutable, refused rather than discouraged.** Every attribute the row holds was
validated against that kind's field list, so changing it would either destroy typed work silently
or leave data in `attributes_json` that the served definition does not describe. The wrong kind is
fixed by creating the right entry and deleting the wrong one, which is recoverable both ways.

**`attributes_json` is not a free-form bag.** An attribute the definition does not declare is a
refusal, not a silent drop — the moment one is dropped, the served definition stops describing what
is actually in the file. The field-type list is closed at six and a test enforces it on both sides
of the wire, exactly as the editor's node list is (D1, D26).

**`needs_review` and `status` are orthogonal.** One says "something this entry depended on moved",
the other is the proposal lifecycle. `superseded` is not the answer to "this entry is out of date".

### `entry_revision`

Every entry write records one, holding the entry's full state **after** the change (D27).

| Column | Type | Notes |
|---|---|---|
| `entry_id` | `TEXT NOT NULL REFERENCES entry(id)` | |
| `revision` | `INTEGER NOT NULL` | 1 is the creation |
| `revised_at` | `TEXT NOT NULL` | UTC ISO-8601 |
| `reason` | `TEXT NOT NULL DEFAULT ''` | `created`, `deleted`, `restored`, `review cleared`, `restored revision n`, or what the writer typed |
| `retcon` | `INTEGER NOT NULL DEFAULT 0` | Did this write flag dependents? |
| `origin` | `TEXT NOT NULL` | `user` \| `agent` |
| `snapshot_json` | `TEXT NOT NULL` | The state after the change |
| — | `PRIMARY KEY (entry_id, revision)` | A revision has no id of its own: it is only ever reached through its entry |

**Revision *n* is what the entry was at revision *n***, so reading a past state is one row rather
than a replay of everything before it. **Nothing is deduplicated and nothing is pruned** — the
deliberate opposite of a `handover` snapshot on both counts, because that is 300 KB nobody asked
for and this is two kilobytes somebody typed.

`snapshot_json` deliberately excludes `needs_review` and `review_reason`: those are notes about the
entry's *surroundings*, and restoring a revision must not drag a neighbour's old disturbance back.

### `entry_link`

A relationship between two entries, from the closed vocabulary (D26).

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | `lnk_…` |
| `project_id` | `TEXT NOT NULL REFERENCES project(id)` | |
| `from_entry` | `TEXT NOT NULL REFERENCES entry(id)` | |
| `to_entry` | `TEXT NOT NULL REFERENCES entry(id)` | |
| `relation` | `TEXT NOT NULL` | From the served vocabulary; refused on the side it is offered from |
| `attributes_json` | `TEXT NOT NULL DEFAULT '{}'` | |
| `since` / `until` | `TEXT` | Story-time bounds (D9): free text, **stored, displayed, never interpreted** |
| `created_at` / `updated_at` | `TEXT NOT NULL` | UTC ISO-8601 |
| `deleted_at` | `TEXT` | `NULL` = live (D25) |

Indexes: `idx_link_from ON entry_link(from_entry, relation)` and
`idx_link_to ON entry_link(to_entry, relation)` — an entry's links are read from both ends.

**Directed in storage, and possibly symmetric in meaning.** One row, always. A relation the
definition marks `symmetric` is stored once and read from both ends; storing it twice would mean
two rows that can disagree — one deleted and one not, one bounded and one not — and a Phase 8
adjacency matrix that double-counts.

**The endpoints and the relation are not editable.** Changing either is a delete and a create, and
both are recoverable; editing them in place would let a link's own history describe a relationship
it never had, which is `kind`'s immutability one table over. A link carries no revision: the D19
guard lives on the entry.

**Uniqueness is judged on the link's own row, visibility on all three.** A duplicate is refused
against `entry_link.deleted_at` alone — including a restore that would produce one — because two
rows for the same pair are duplicates whether or not an endpoint is currently away.

### `entry_anchor`

A citation: an entry pointing at the passage that produced it, through a Phase 2 anchor.

| Column | Type | Notes |
|---|---|---|
| `entry_id` | `TEXT NOT NULL REFERENCES entry(id)` | |
| `anchor_id` | `TEXT NOT NULL REFERENCES anchor(id)` | A **real** foreign key, with `PRAGMA foreign_keys` on |
| `role` | `TEXT NOT NULL` | `source` \| `mention` \| `setup` \| `payoff` |
| `created_at` | `TEXT NOT NULL` | UTC ISO-8601 |
| — | `PRIMARY KEY (entry_id, anchor_id, role)` | An entry may cite one anchor in more than one role |

Index: `idx_entry_anchor_anchor ON entry_anchor(anchor_id)` — the reverse view, so the *Marks* tab
can say an anchor is spoken for.

**Deleting an anchor removes its citations and leaves the entries; soft-deleting an entry leaves
its citations and its anchors.** The first is not a courtesy: `anchor_id` is a real foreign key, so
without the cleanup, deleting a cited anchor *fails*. It runs inside `AnchorStore.delete`'s own
transaction. The entry keeps what a person typed and loses one reason to believe it.

**An entry's narrative position is derived from its `source` anchor and never stored** — chapter
`order_index`, then `from_pos`, computed on read. So it moves when the writer reorders chapters,
for free, and an entry with no `source` anchor simply has none, which is D9's unplaced tray
arriving from the data rather than from a flag somebody maintains. A source in a soft-deleted
chapter places nothing.

---

## 4. What makes a file a project

The scan (`ProjectStore.scan`) opens every `*.sqlite` in the projects directory **read-only** and
classifies it. Looking at a project never changes it — no migration, no WAL recovery, no file
creation. Only an explicit open migrates.

| Outcome | Condition | What the picker shows |
|---|---|---|
| project | `schema_version` present and a `project` row exists | The project |
| `not-an-archetype-project` | No `schema_version` table (version 0) | Skipped, with the reason |
| `empty` | Schema present, no `project` row | Skipped, with the reason |
| `unreadable` | `sqlite3.Error` on open or read | Skipped, with the reason |

A skipped file is **reported, not swallowed and not fatal**: `GET /api/projects` returns it under
`skipped` (filename and reason only — the browser has no business knowing the directory layout).
One corrupt file must not be able to hide a writer's other manuscripts.

**Filenames.** `<slug>-<token>.sqlite`, where the slug is the title folded to ASCII, lowercased,
non-alphanumerics collapsed to hyphens, truncated to 48 characters, and the token is six random
alphabet characters. Apostrophes are removed rather than hyphenated, so `Emile's Journey` becomes
`emiles-journey-4k2h9w.sqlite`. The filename is a convenience for a person browsing the directory
and carries **no authority**: identity is the `project.id` inside the file, which is why a renamed
or copied file still resolves correctly.

**Finding a document without naming its project.** The API addresses documents as
`/api/documents/{did}` (§ api-contract), but storage is per project, so `manuscript/locator.py`
answers "which file". It caches the answer, and the cache is a *hint*: every resolution
re-confirms that the file still holds that document, and a miss falls back to a full scan. A
project file deleted, replaced, or copied in behind the app's back therefore costs one wasted
scan — never a wrong read or a wrong write.

---

## 5. The derived projection (D18)

`manuscript/projection.py` is a pure function: ProseMirror JSON in, `(text_plain, headings,
word_count)` out. No database, no framework, no I/O. It is the most-reused code in the project —
the TOC reads it now, chunking reads it in Phase 5, agent context composition in Phase 6 — so its
rules are written down in the module docstring rather than inferred from callers.

| Rule | Behaviour |
|---|---|
| Blocks | `paragraph` and `heading` each contribute one block; containers (`blockquote`, lists, list items, the doc) are walked through and contribute nothing. Empty blocks are dropped, so exactly one blank line separates blocks |
| Decoration | None. No bullets, no quote markers, no marks — `text_plain` is what the words are, not what they look like |
| Scene break | `horizontalRule` projects as its own block reading `* * *`, and counts zero words. A chunker that could not see it would cut across a scene change |
| Line break | `hardBreak` is a newline *within* a block; blank lines inside a block are dropped so a block cannot forge a block boundary |
| Headings | Every `heading` node, empty ones included. `ordinal` is its index among all heading nodes in document order, from 0 |
| Words | A run of Unicode letters and digits, optionally joined by apostrophes or dashes. `well-known` is one word, `* * *` is none. Counted over `text_plain`, headings included |
| Unknown nodes | Walked for their content, never rejected. A projection that threw would turn a schema question into lost text |

**One specification, two implementations.** `web/src/editor/projection.ts` mirrors it so the TOC
stays live between saves. Both run against `server/tests/fixtures/projection/cases.json`, so drift
fails a test rather than confusing a table of contents. **The server's answer wins on save** — the
client mirror exists for liveness only.

The projection is also where structure is **validated**: shape, node types being strings, `attrs`
being objects, nesting depth ≤ 64. It raises `InvalidDocumentError`, which is how "rejected before
any write" happens in one place that already walks every node. The client mirror deliberately does
*not* validate — throwing there would blank the outline panel over a node nobody has taught it yet.

`headings_json` stores the heading list as a JSON array of objects rather than in a table. It is
written and read only by us, always whole, and never queried across rows.

---

## 6. Writing rules

### One write path

**`DocumentStore.save_content` is the only path by which manuscript text changes.** Routes go
through it, tests go through it, restoring a snapshot goes through it, and in Phase 6 the agent's
accepted proposals go through it (D12). That is what makes "the writer owns the words" structural
rather than aspirational.

Restoring a snapshot is worth naming because it is the case that looks like an exception and is
not: `SnapshotStore.restore` writes the old content back **as an ordinary save**, so it increments
`version`, re-derives the projection, re-resolves the anchors, and is refused with a `409` if the
client is stale. Markdown import is the other one — it *creates* chapters and never replaces the
text of an existing one ([phase-2-plan](phase-2-plan.md) § 2, ruling 5).

### A rejected save has written nothing

Serialization, the size check (`MAX_CONTENT_BYTES` = 2 MiB), and the projection all run **before**
the transaction opens. Inside it, the stored `version` is re-read under the write lock and
compared — which is what makes the guard a guard rather than a race.

### The version guard (D19)

`version` starts at 1 and increments by exactly 1 on each successful content save.

The comparison is **equality, not "at least"**. A client cannot get ahead of the store except by
inventing a version, and accepting one would let a bug skip the guard entirely. A mismatch raises
`StaleVersionError`, nothing is written, and the client is handed the current version and
`updated_at` so it can offer a reload without a second round trip. There is no merge.

### Only a text edit bumps `version`

`rename` moves `title` and `updated_at` and leaves `version` alone. A rename is not a text edit,
and invalidating an in-flight autosave over a cosmetic change would cost the writer a keystroke —
the exact failure the autosave protocol exists to prevent. `reorder`, `delete`, and `restore`
follow the same rule for the same reason.

### A reorder presents the complete set

`reorder` takes the **complete** ordered list of the project's live chapters and rewrites
`order_index` to `0..n-1`. A list that is not exactly that set — one missing, one extra, one
duplicated, one from another project — is refused and nothing is written.

That set comparison **is** the concurrency guard, which is why there is no project-level version
column: a client working from a stale chapter list cannot produce a complete set, so it cannot
silently reorder a chapter out of existence.

### Every document write stamps the project

`create`, `save_content`, `rename`, `reorder`, `delete`, and `restore` all update
`project.updated_at` in the **same transaction**. The picker sorts on it.

### Every entry write records a revision (D27)

Creating, editing, deleting, restoring, clearing a review, and restoring a past revision **all**
write one, numbered from 1. Restoring a revision goes through the ordinary `update` path, so it
bumps `revision`, appends to the history rather than rewriting it, is guarded by D19, and computes
its own retcon answer — one write path, no exceptions, which is `SnapshotStore.restore`'s rule one
table over.

### Only a write marked as a retcon flags anything

The store computes the answer from `RETCON_FIELDS` (`name`, `attributes_json`, `status`) and the
request may override it in either direction. A dependent is **an entry joined by a live link in
either direction** — the only relationship the data actually knows — and flagging sets
`needs_review` with a reason naming the entry and the revision that caused it.

Three clauses hold the rest of it up:

- **Flagging writes no revision on the dependent.** `needs_review` is a note about the entry's
  surroundings, not a claim it makes; a revision for it would fill a densely linked character's
  history with rows recording that a neighbour changed.
- **Clearing a review is never a retcon**, not by default and not by override. Without that,
  clearing a flag on a densely linked character re-flags every neighbour and the queue regenerates
  itself as it is worked through — which teaches the writer that the queue does not mean anything.
- **A dependency the data does not know about is not flagged.** The honest limit ships with the
  rule: a prose mention is not a link. Widening it is retrieval, and that is Phase 5's.

### The two live predicates

Both live in `archetype/bible/predicates.py`, written once and spliced into every query.

- **An entry is live when `deleted_at IS NULL`** (D25) — the same one-column rule a chapter
  follows (D22). The row, its revisions, its links, and its citations all stay.
- **A link is live when the link is not deleted *and neither endpoint is*.** Three-way, in one
  place. It is the Phase 2 lesson one table wider: forgetting a leg puts a deleted character back
  into a relationship view and surfaces in Phase 8 as a wrong chart. One test asserts a deleted
  entry is absent from the list, the counts, the filters, the review queue, and the dependent
  computation **together**.

### Nothing cascades, which is what makes restore exact

An endpoint's deletion *hides* a link through the predicate rather than writing to it, so restoring
an entry brings back exactly the links it had — and a link deleted in its own right stays deleted,
because its own `deleted_at` was never touched. The two are distinguishable for the same reason.

### One transaction over three tables

*Add to bible* mints an anchor, creates an entry, and cites it atomically, so a stale document
version leaves **no anchor, no entry, and no citation**. It is possible because `AnchorStore` and
`EntryStore` each expose a connection-scoped `create_within`, and each public `create` is that
method plus a transaction — so there is still exactly **one** place an `anchor` row is written and
one place an `entry` row and its revision 1 are. A second `INSERT INTO anchor` in the bible's half
would be the second minting path § 2's rules exist to forbid.

---

## 7. Planned tables (not yet built)

The outline § 5 sketch, carried forward. **Illustrative, not binding** — each phase firms up its
own tables in its plan and amends this section in the same change.

The Phase 3 block that stood here is gone: those four tables are **built**, and § 3 describes them
as they are. What the sketch got wrong is worth recording, because both corrections were decisions
rather than details — a revision has no id of its own (it is only ever reached through its entry,
so an id would be an identity nobody dereferences), and every one of the four carries `deleted_at`,
because D25 ruled that deleting an entry is a soft delete exactly as D22 ruled for a chapter.

```
-- Phase 5: retrieval
chunk(id, document_id, ord, text, from_pos, to_pos, hash)
chunk_vec(chunk_id, embedding)                   -- sqlite-vec virtual table
chunk_fts(chunk_id, text)                        -- FTS5 virtual table

-- Phase 6: agent runs
run(id, project_id, kind, task_json, status, started_at, ended_at, usage_json)
run_step(id, run_id, ord, type, payload_json)    -- plan|tool_call|tool_result|message|error
proposal(id, run_id, kind, target_json, payload_json, status, decided_at)
finding(id, run_id, kind, severity, message, citations_json, status)
```

Two things the phases below inherit:

- **Anchors are for cited passages**, not for structure. A heading is a structural position the
  projection already numbers exactly and re-derives on every save, so jump-to-heading resolves by
  heading ordinal and continues to (P1-11, [phase-2-plan](phase-2-plan.md) § 2, ruling 1). An
  earlier draft of this document called the heading ordinal "the seam Phase 2 replaces"; that
  reading was wrong, and minting an anchor row per heading on every save to reproduce an answer
  that is already free is what it would have cost.
- **Chunking reads `text_plain`, not `content_json`.** That is why the projection's block rules —
  one blank line between blocks, scene breaks visible as text — are written down in § 5 rather
  than left to whatever the current implementation happens to do. Anchors read it too, which is
  why changing a projection rule moves every anchor in every project and is a spec change.

---

## 8. Changing the schema

**Migrations are numbered, forward-only, and applied on open (D20).** `NNN_lower_snake.sql` in
`archetype/projects/migrations/`, applied in numeric order, recorded in `schema_version`. There
are no down-migrations.

Rules the runner enforces, because each failure mode is a migration that silently does not run:

- A malformed filename is an error, not a skipped file.
- Versions must be **consecutive from 001** — a gap or a duplicate is an error.
- A file at a version **newer than this build knows** refuses to open, rather than being operated
  on by code that does not understand it.
- Each migration runs inside **one transaction with its `schema_version` row**, so a failure
  leaves the file at the previous version rather than half-migrated. The `BEGIN`/`COMMIT` pair is
  written *into the script text*, because `sqlite3.Cursor.executescript` commits any open
  transaction before it runs — a transaction opened around the call would be closed by the very
  call it was meant to protect.

**Storage schemas are extension-only** (outline § 7). Add a column or a table; never repurpose or
remove one without a migration and a note in the phase plan.

**Adding a migration** means dropping `00N_thing.sql` into `migrations/` **and** adding a test
that runs it against a fixture database captured at version `N-1`. `server/tests/fixtures/db/`
holds those fixtures and its README explains how one is captured. This is not optional: the
pattern exists so that the first real migration, in Phase 2, is tested against a version-1 file
that a writer's manuscript actually lives in.

---

## 9. What is deliberately not stored

| Not stored | Where it lives instead | Why |
|---|---|---|
| API keys and provider secrets | The environment only (D8) | Never in the file, never in a response, never in Git. A `SecretStr` settings field must be `Field(exclude=True)` or the settings class refuses to build |
| Pane widths, collapsed panes, active tab | `localStorage`, under `archetype.*` | Browser conveniences. Every value is validated field by field on the way in, and one that cannot be read is forgotten rather than repaired |
| Which project was open, recent projects | `localStorage` | Same. An id whose project is gone is silently not offered |
| A registry of projects | Nowhere — the directory is scanned (D17) | A registry is a second source of truth that can disagree with the filesystem |
| `text_plain` on the wire | Recomputed by the client mirror | Sending it would double every chapter load to carry something the client can derive |

None of the `localStorage` values are manuscript data, and none is worth failing over.
