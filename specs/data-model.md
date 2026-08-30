# Archetype — Data Model

**Status:** Phase 1 tables as built; later phases sketched · **Version:** 1.0 · **Date:** 2026-08-30
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1 (D3, D18, D19, D20)
**Companion:** [`specs/api-contract.md`](api-contract.md) — the same vocabulary on the wire

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

## 3. Tables as built (schema version 1)

Created by `archetype/projects/migrations/001_init.sql`. Types are SQLite's, which means `TEXT`
holds UTF-8 and `INTEGER` holds a signed 64-bit integer.

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
| `updated_at` | `TEXT NOT NULL` | Moved by a save **and** by a rename |

Index: `idx_document_project_order ON document(project_id, order_index)` — the document list and
the outline both read one project's chapters in that order. Deliberately **not** `UNIQUE`, because
Phase 2's reorder needs to move rows through transient duplicate indices.

**`content_json` is the only authored column.** The four that follow it are derived from it on
every write and are never written independently. Storing them is a deliberate denormalisation:
`GET /api/projects/{pid}/outline` draws a whole manuscript's table of contents by reading
`headings_json` and `word_count` alone, without loading a single chapter's content (D2, D18).

**Ordering is `ORDER BY order_index, created_at, id`.** The two tiebreakers make the order total
even while duplicate indices exist, so a list never shuffles under a reader mid-reorder.

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
through it, tests go through it, and in Phase 6 the agent's accepted proposals go through it
(D12). That is what makes "the writer owns the words" structural rather than aspirational.

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

### A rename does not bump `version`

`rename` moves `title` and `updated_at` and leaves `version` alone. A rename is not a text edit,
and invalidating an in-flight autosave over a cosmetic change would cost the writer a keystroke —
the exact failure the autosave protocol exists to prevent.

### Every document write stamps the project

`create`, `save_content`, and `rename` all update `project.updated_at` in the **same transaction**.
The picker sorts on it.

---

## 7. Planned tables (not yet built)

The outline § 5 sketch, carried forward. **Illustrative, not binding** — each phase firms up its
own tables in its plan and amends this section in the same change.

```
-- Phase 2: anchors and snapshots
snapshot(id, document_id, taken_at, reason, content_json)
anchor(id, project_id, document_id, from_pos, to_pos,
       quote, prefix, suffix, status, updated_at)

-- Phase 3: the story bible
entry(id, project_id, kind, name, summary, body_md, attributes_json,
      status, origin, created_at, updated_at)
entry_revision(id, entry_id, revised_at, reason, snapshot_json, origin)
entry_anchor(entry_id, anchor_id, role)          -- 'source' | 'mention' | 'setup' | 'payoff'
entry_link(id, from_entry, to_entry, relation, attributes_json, since, until)

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

Two things Phase 1 has already settled for them:

- **Anchors will carry ProseMirror positions plus their own quote and context** (`quote`, `prefix`,
  `suffix`), and are re-verified on load. An anchor that cannot be resolved becomes `stale` and is
  surfaced — never silently re-pointed at the wrong passage. Phase 1 deliberately built no anchor
  record: jump-to-heading resolves by heading ordinal alone (P1-11), which is the seam Phase 2
  replaces.
- **Chunking reads `text_plain`, not `content_json`.** That is why the projection's block rules —
  one blank line between blocks, scene breaks visible as text — are written down in § 5 rather
  than left to whatever the current implementation happens to do.

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
