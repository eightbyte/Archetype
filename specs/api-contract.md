# Archetype — API Contract

**Status:** The Phase 3 surface as built — every route that exists · **Version:** 1.5 ·
**Date:** 2026-09-03
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1
(D7, D8, **D15**, D18, D19, **D21**, **D22**, **D23**, **D25**, **D26**, **D27**, **D28**)
**Companions:** [`specs/data-model.md`](data-model.md) — the same vocabulary in storage ·
[`specs/bible.md`](bible.md) — what an entry *means*

This document covers **every route that exists**. Chat and streaming arrive in Phase 4, search
in Phase 5, agent runs in Phase 6; each extends this document as it lands.

The generated OpenAPI schema at `http://127.0.0.1:8787/openapi.json` (browsable at `/docs`) is
produced from the same pydantic models and is authoritative for exact types. This document is
authoritative for **behaviour** — what a route promises, what it refuses, and why.

---

## 1. Ground rules

**Base URL** `http://127.0.0.1:8787/api`. Loopback is a deliberate posture, not an oversight:
single user, no auth, no HTTPS, no CORS (D7). There is **no authentication**, because there is no
second party. Anything reaching this port is already inside the writer's machine.

**JSON in, JSON out.** UTF-8 throughout. Request bodies are `application/json`. The two
Markdown exports are the **one exception**, and § 9 says why; their failures are still the
envelope.

**Timestamps** are UTC ISO-8601 with a `Z`: `2026-08-30T20:40:52Z`. They are formatted for
display only at the client's edge (`web/src/format.ts`).

**Field names are `snake_case` on the wire, in storage, and in the TypeScript client.** One
vocabulary end to end — `content_json` is `content_json` everywhere. A camelCase translation layer
would exist only to be a place the two sides can drift apart.

**Wire schemas are extension-only** (outline § 7). The server may add a field to a response; it
never repurposes or removes one without a migration note in the phase plan.

**Requests, though, are closed.** Every request model is `extra="forbid"`: a body carrying an
undeclared field is a `422`, not a silent ignore. Extension-only protects an old *client*; a
client sending a field the server has never heard of is a bug, and silence would hide it.

**Routes carry no domain logic.** A route resolves scope, calls a store, and shapes the answer.
Every rule that matters — the projection, the version guard, the size limit — lives in the store,
so the Phase 6 agent gets identical behaviour without going through HTTP. Domain exceptions are
translated into the envelope by handlers in `api/errors.py`, never caught per route.

**Every request is logged once**, with a generated `request_id`, method, path, status, and
duration. That id is the only thing a `500` gives the browser.

### How the contract is held

The server writes representative responses to `server/tests/fixtures/contract/*.json` during
`pytest`, with ids and timestamps normalised to fixed placeholders so a run that changed no shape
produces no diff. The frontend suite reads the same files and checks them **twice**: assigned to
the client's type so `tsc` sees them, and compared key-set-for-key-set at run time, because `tsc`
cannot see into a `JSON.parse` and a dropped field would arrive as `undefined` and type-check
cleanly. A wire-shape change fails a suite rather than the browser.

---

## 2. Route table

| Method | Path | Success | Failures |
|---|---|---|---|
| `GET` | `/api/health` | `200` | — |
| `GET` | `/api/projects` | `200` | — |
| `POST` | `/api/projects` | `201` | `422` |
| `GET` | `/api/projects/{project_id}` | `200` | `404` |
| `GET` | `/api/projects/{project_id}/documents` | `200` | `404` |
| `POST` | `/api/projects/{project_id}/documents` | `201` | `404`, `422` |
| `GET` | `/api/projects/{project_id}/documents/deleted` | `200` | `404` |
| `PUT` | `/api/projects/{project_id}/documents/order` | `200` | `404`, `409`, `422` |
| `GET` | `/api/projects/{project_id}/outline` | `200` | `404` |
| `GET` | `/api/documents/{document_id}` | `200` | `404` |
| `PUT` | `/api/documents/{document_id}/content` | `200` | `400`, `404`, `409`, `413`, `422` |
| `PATCH` | `/api/documents/{document_id}` | `200` | `404`, `422` |
| `DELETE` | `/api/documents/{document_id}` | `200` | `404` |
| `POST` | `/api/documents/{document_id}/restore` | `200` | `404` |
| `POST` | `/api/documents/{document_id}/anchors` | `201` | `404`, `409`, `422` |
| `GET` | `/api/documents/{document_id}/anchors` | `200` | `404` |
| `GET` | `/api/projects/{project_id}/anchors` | `200` | `404`, `422` |
| `PATCH` | `/api/anchors/{anchor_id}` | `200` | `404`, `409`, `422` |
| `DELETE` | `/api/anchors/{anchor_id}` | `204` | `404` |
| `GET` | `/api/documents/{document_id}/snapshots` | `200` | `404` |
| `POST` | `/api/documents/{document_id}/snapshots` | `200` | `404`, `422` |
| `GET` | `/api/snapshots/{snapshot_id}` | `200` | `404` |
| `POST` | `/api/snapshots/{snapshot_id}/restore` | `200` | `404`, `409`, `422` |
| `GET` | `/api/documents/{document_id}/markdown` | `200` | `404` |
| `GET` | `/api/projects/{project_id}/markdown` | `200` | `404` |
| `POST` | `/api/projects/{project_id}/import` | `201` | `404`, `413`, `422` |
| `GET` | `/api/bible/schema` | `200` | — |
| `GET` | `/api/projects/{project_id}/entries` | `200` | `404`, `422` |
| `POST` | `/api/projects/{project_id}/entries` | `201` | `404`, `422` |
| `GET` | `/api/projects/{project_id}/entries/deleted` | `200` | `404` |
| `GET` | `/api/entries/{entry_id}` | `200` | `404` |
| `PUT` | `/api/entries/{entry_id}` | `200` | `404`, `409`, `422` |
| `DELETE` | `/api/entries/{entry_id}` | `200` | `404` |
| `POST` | `/api/entries/{entry_id}/restore` | `200` | `404` |
| `POST` | `/api/entries/{entry_id}/review/clear` | `200` | `404`, `409`, `422` |
| `GET` | `/api/entries/{entry_id}/revisions` | `200` | `404` |
| `GET` | `/api/entries/{entry_id}/revisions/{number}` | `200` | `404` |
| `POST` | `/api/entries/{entry_id}/revisions/{number}/restore` | `200` | `404`, `409`, `422` |
| `GET` | `/api/projects/{project_id}/links` | `200` | `404`, `422` |
| `POST` | `/api/projects/{project_id}/links` | `201` | `404`, `409`, `422` |
| `GET` | `/api/entries/{entry_id}/links` | `200` | `404` |
| `PATCH` | `/api/links/{link_id}` | `200` | `404`, `422` |
| `DELETE` | `/api/links/{link_id}` | `200` | `404` |
| `POST` | `/api/links/{link_id}/restore` | `200` | `404`, `409` |
| `POST` | `/api/entries/{entry_id}/citations` | `201` | `404`, `422` |
| `DELETE` | `/api/entries/{entry_id}/citations/{anchor_id}` | `200` | `404`, `422` |
| `GET` | `/api/anchors/{anchor_id}/entries` | `200` | `404` |
| `POST` | `/api/documents/{document_id}/entries` | `201` | `404`, `409`, `422` |
| `GET` | `/api/projects/{project_id}/storytime` | `200` | `404` |

Any route can also answer `500` (§ 6).

**Documents, anchors, snapshots, entries, and links are addressed without naming a project.** Storage is one
file per project (D3), so `manuscript/locator.py` resolves the bare id to a file, for any of the five tables;
see data-model § 4. The alternative — `/api/projects/{pid}/documents/{did}` — would have put a redundant,
spoofable scope in every autosave URL. Phase 3 added two prefixes to that one mechanism and no second mechanism.

**`GET /api/bible/schema` is the one route with no project scope at all**, because D26's vocabulary is the
product's and not a manuscript's (§ 10).

---

## 3. Shared shapes

### `Heading`

```json
{ "level": 1, "text": "Arrival", "ordinal": 0 }
```

`level` is 1–6 (the editor authors 1–3). `ordinal` is the heading's index among **all** heading
nodes in its document, from 0 — including empty ones, so that typing a new heading does not
renumber the ones below it. Jump-to-heading resolves against `ordinal` and nothing else, until
anchors arrive in Phase 2 (P1-11).

### `ProjectSummary`

```json
{
  "id": "prj_000000000001",
  "title": "The Long Road",
  "chapter_count": 2,
  "word_count": 13,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

`word_count` sums the chapters. `updated_at` moves on every document write, so sorting on it puts
the manuscript the writer was last in at the top.

### `DocumentMeta` — a document **without** its content

```json
{
  "id": "doc_000000000001",
  "project_id": "prj_000000000001",
  "order_index": 0,
  "title": "Chapter 1",
  "kind": "chapter",
  "headings": [{ "level": 1, "text": "Arrival", "ordinal": 0 }],
  "word_count": 12,
  "version": 2,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z",
  "deleted_at": null
}
```

The list routes return these deliberately. **The outline panel must never pull the whole
manuscript to draw a chapter list**, and that discipline starts at the wire shape rather than at
a client's good intentions.

`kind` is `"chapter"` in Phase 1. Later phases add kinds; they do not repurpose this one.

`deleted_at` is `null` on every chapter every list route returns, because those routes filter the
soft-deleted ones out (D22). It is carried anyway, and it is the whole content of the restore
surface: `GET /api/projects/{pid}/documents/deleted` returns these, and a chapter with nothing to
say about when it went is a chapter nobody can make a decision about.

### `SkippedFile`

```json
{ "name": "notes.sqlite", "reason": "not-an-archetype-project", "detail": "no schema_version table" }
```

`reason` is one of `not-an-archetype-project`, `empty`, `unreadable`. Only the **filename**
crosses — never the path. The browser has no business knowing the writer's directory layout; the
full path goes to the log, where it is actually useful.

---

## 4. Projects

### `GET /api/health`

```json
{ "status": "ok", "version": "0.1.0" }
```

Liveness, and the version the browser is talking to. It lives in the `/api` router rather than
the app factory, so the router is a complete description of the API surface.

### `GET /api/projects`

Scans the projects directory (D17) and answers with what was readable **and what was not**:

```json
{
  "projects": [ { "…ProjectSummary…": true } ],
  "skipped": []
}
```

Sorted by `updated_at`, most recent first. **A file that cannot be read appears under `skipped`
rather than failing the request** — one corrupt file must not hide a writer's other manuscripts.
This route therefore has no `404` and no error path of its own.

The scan opens every file **read-only**: listing projects never migrates or otherwise changes one.

### `POST /api/projects`

```json
{ "title": "The Long Road" }
```

`title` is required, trimmed, 1–200 characters. Answers `201` with a **`ProjectDetail`** — the
same body as `GET /api/projects/{pid}`.

**The new project is seeded with one empty chapter.** A new project must open into a writable
editor rather than an empty state, and doing it in the route makes that true for every client
including the Phase 6 agent, rather than being a property of one UI flow.

### `GET /api/projects/{project_id}`

```json
{ "project": { "…ProjectSummary…": true }, "documents": [ { "…DocumentMeta…": true } ] }
```

Opening a project **migrates its file** to the current schema version (D20) — unlike the list,
which only looks.

### `GET /api/projects/{project_id}/documents`

```json
{ "documents": [ { "…DocumentMeta…": true } ] }
```

Ordered by `order_index`, then `created_at`, then `id`. The two tiebreakers keep the order total
even while Phase 2's reorder moves rows through transient duplicate indices.

### `POST /api/projects/{project_id}/documents`

```json
{ "title": "Departure" }
```

The body is optional and so is `title`; omitting it takes `Chapter N`, N being one past the
chapters already there. Answers `201` with a full **`Document`**, content included, so the client
can open straight into it without a second request.

Appended at the end. **Reorder and delete do not exist in Phase 1** — they arrive in Phase 2,
together with the snapshot that makes deleting safe.

### `GET /api/projects/{project_id}/outline`

The stitched table of contents across the whole manuscript:

```json
{
  "project_id": "prj_000000000001",
  "chapters": [
    {
      "document_id": "doc_000000000001",
      "title": "Chapter 1",
      "order_index": 0,
      "word_count": 12,
      "headings": [{ "level": 1, "text": "Arrival", "ordinal": 0 }]
    }
  ]
}
```

Chapters only (`kind = 'chapter'`). Reads **only derived columns**, so a whole manuscript's TOC is
drawn without loading one chapter's content (D2, D18).

---

## 5. Documents

### `GET /api/documents/{document_id}`

A `DocumentMeta` plus `content_json` — the ProseMirror document itself.

**There is no `text_plain`.** It is derived from `content_json` by rules the client mirrors
exactly (data-model § 5), so shipping it would double the size of every chapter load to carry
something the client can compute. The server's projection still reaches the client where it
matters: in `headings` and `word_count` here, and again in every save response (D18).

### `PUT /api/documents/{document_id}/content` — the save protocol (P1-6, D19)

```json
{ "content_json": { "type": "doc", "content": [] }, "version": 3 }
```

`version` is the version the client believes it is editing, and must be ≥ 1. Both fields are
required.

In **one transaction** the server validates the document, derives `text_plain`, the heading list
and the word count from it, increments `version`, and writes. It answers:

```json
{
  "document_id": "doc_000000000001",
  "version": 4,
  "word_count": 12,
  "headings": [{ "level": 1, "text": "Arrival", "ordinal": 0 }],
  "updated_at": "2026-01-01T00:00:00Z",
  "anchors": []
}
```

The derived values in that response are **authoritative** and replace whatever the client's mirror
had computed (D18).

`anchors` (added in P2-7, extension-only) carries every anchor this write **moved** — a changed
status, a changed position, or both — as full `Anchor` objects. The same transaction that wrote
the text re-resolved them, so the list is what is true of the row that was just stored, and it
saves the client a round trip on the request that happens most often. An **empty list is the
ordinary answer**: it means the writer typed above their anchors rather than through them. A
client replaces its own mapped positions with these; its mapping is for liveness, this is the
truth (D21).

**This route is the only way manuscript text changes.** Not "the only way the UI changes it" — the
only way. That is what makes "the writer owns the words" a property of the system rather than a
promise: when the agent arrives in Phase 6, its accepted proposals come back through here like
any other save (D12).

#### When the version is stale — `409`

If the presented `version` is not the stored one, **nothing is written** and the answer is:

```json
{
  "error": {
    "code": "version_conflict",
    "message": "document doc_000000000001 is at version 2, not 1; reload before saving",
    "detail": {
      "document_id": "doc_000000000001",
      "presented_version": 1,
      "current_version": 2,
      "updated_at": "2026-01-01T00:00:00Z"
    }
  }
}
```

The comparison is **equality, not "at least"**: a version *ahead* of the stored one is refused
too. A client cannot get ahead of the store except by inventing a version, and accepting one would
let a bug skip the guard entirely.

`detail` carries everything the client needs to explain itself and offer a reload without a second
round trip. **The client never merges and never offers "save anyway"** — the guard exists
precisely to stop a client overwriting what it has not seen. In the browser a conflict stops
autosave until it is answered; typing on does not clear it and does not resume saving.

#### Rejections that happen before any write

| Status | `code` | When |
|---|---|---|
| `422` | `validation_error` | The body did not parse, a field is missing, or an undeclared field was sent |
| `413` | `payload_too_large` | Serialized `content_json` exceeds **2 MiB**. `detail` carries `size` and `limit` |
| `400` | `invalid_document` | Not a well-formed ProseMirror document: bad shape, a non-string node type, non-object `attrs`, or nesting deeper than 64 |
| `404` | `document_not_found` | No project file holds that document |

Serialization, the size check, and the projection all run **before the transaction opens**, so
every one of these leaves the stored row untouched — asserted by reading it back, not assumed.

Two megabytes is roughly seven times a 20,000-word chapter's ProseMirror JSON: generous for a
chapter, and still a refusal for a payload that would take the process down.

### `PATCH /api/documents/{document_id}` — rename

```json
{ "title": "One: Arrival" }
```

Required, trimmed, 1–200 characters. Answers with the updated `DocumentMeta`.

**`version` is deliberately not bumped.** A rename is not a text edit, and invalidating an
in-flight autosave over a cosmetic change would cost the writer a keystroke — the exact failure
the autosave protocol exists to prevent. `updated_at` does move.

### `PUT /api/projects/{project_id}/documents/order` — reorder (P2-2, P2-11)

```json
{ "document_ids": ["doc_000000000002", "doc_000000000001"] }
```

The **complete** ordered list of the project's live chapters. Answers with the whole list as
`DocumentListOut`, `order_index` rewritten to `0..n-1`.

**That completeness is the concurrency guard, and it is why no project version is presented
alongside it.** A client working from a stale chapter list cannot produce the complete set, so it
cannot silently reorder a chapter it has never heard of out of existence. A list that is not
exactly the live set — one missing, one extra, one duplicated, one from another project — is a
`409 reorder_mismatch` and **nothing is written**:

```json
{ "error": { "code": "reorder_mismatch", "message": "…",
             "detail": { "missing": ["doc_…"], "unexpected": [], "duplicated": [] } } }
```

A `409` rather than a `422`: the body is well-formed and every id in it is a string. What is
wrong is that it does not describe the project *as it is now* — the same kind of failure a stale
save is, and the client answers it the same way, by re-reading the chapter list rather than by
correcting a field. An empty list is a `422`: a project always has at least one chapter, so that
is a client bug, not a race.

**No document's `version` moves, and no document's `updated_at` is stamped.** The order belongs
to the project, not to any chapter; marking forty chapters as edited because one moved would make
"last edited" mean nothing.

### `DELETE /api/documents/{document_id}` — soft delete (P2-2, D22)

Answers `200` with the chapter's `DocumentMeta`, `deleted_at` now set.

**A soft delete.** A `pre-delete` snapshot and `deleted_at` are written in **one** transaction, so
a chapter is never removed from the lists without the copy that undoes it, and a failure anywhere
leaves neither. The row, its content, its snapshots, and its anchors all stay exactly where they
were; the chapter leaves every list, outline, and count, and its anchors read as `orphaned` until
it comes back — with nothing written to a single anchor row (§ 7).

`200` rather than `204`, carrying the metadata: the client has just been told a chapter is gone
and has to say *what* went and *when*, which is precisely `deleted_at`.

The chapter is then out of the editor's reach: `GET /api/documents/{did}` and the save route both
answer `404` for it, so nothing in the app can open a ghost and write to it. Deleting it a second
time is a `404` for the same reason.

### `POST /api/documents/{document_id}/restore` — undo a delete (P2-2, D22)

No body. Answers `200` with the chapter's `DocumentMeta`, `deleted_at` back to `null`.

The chapter returns with its text byte for byte and its anchors at the statuses they held — a
soft delete changed no text, so nothing about them ever became untrue. It is appended at the
**end** of the order rather than dropped back into a position the chapters around it have moved
on from. Restoring a live chapter is a no-op, not an error.

### `GET /api/projects/{project_id}/documents/deleted` — the restore surface (P2-11)

Answers `DocumentListOut`, most recently deleted first. The one route where `deleted_at` is not
`null`. A soft delete is only recoverable if there is somewhere to recover it from, and this is
the reason the delete confirmation can be brief.

---

## 6. Errors

**Every** failing response — a missing project, a stale save, a malformed body, an unhandled bug —
uses one envelope:

```json
{ "error": { "code": "version_conflict", "message": "…", "detail": { "current_version": 7 } } }
```

- `code` — the stable, machine-readable name. **Branch on this**, never on `message`.
- `message` — one sentence a person can read.
- `detail` — whatever this failure needs, or `null` when there is nothing to add. The key is
  always present.

| `code` | Status | Meaning |
|---|---|---|
| `project_not_found` | 404 | No project file in the directory holds that id |
| `document_not_found` | 404 | No project file holds that document |
| `anchor_not_found` | 404 | No project file holds that anchor (P2-7) |
| `snapshot_not_found` | 404 | No project file holds that snapshot (P2-12) |
| `version_conflict` | 409 | Stale save, stale restore, or a range presented against a stale version (D19). Nothing was written |
| `reorder_mismatch` | 409 | The presented order is not exactly the project's live chapters (§ 5). Nothing was written |
| `invalid_anchor_range` | 422 | A range that cannot become an anchor (§ 7). The message is written to be shown |
| `invalid_document` | 400 | Not a well-formed ProseMirror document |
| `payload_too_large` | 413 | Over the 2 MiB per-document limit |
| `validation_error` | 422 | Body or path failed validation; `detail` is pydantic's error list |
| `not_found` | 404 | No such route |
| `method_not_allowed` | 405 | Wrong method for an existing route |
| `internal_error` | 500 | An unhandled exception (below) |
| `entry_not_found` | 404 | No project file holds that entry (§ 10) |
| `link_not_found` | 404 | No project file holds that link (§ 10) |
| `revision_not_found` | 404 | That entry has no such revision (§ 10) |
| `entry_version_conflict` | 409 | Stale entry write (D19, ruling 3). Its **own** code, because the editor and the entry form recover differently. Nothing was written |
| `duplicate_link` | 409 | A live link already says the same thing; `detail.link_id` names it (§ 10) |
| `invalid_attributes` | 422 | An unknown kind, relation, or attribute, or a value the definition refuses; `detail.field` names the input (§ 10) |
| `web_not_built` | 404 | `GET /` with no frontend mounted (§ 11) — a diagnostic, not part of the API |

**A `404` names only what was asked for.** The store's own message carries the projects directory;
that goes to the log, and the client is told `no document 'doc_…' in this workspace`.

**A `500` carries a request id and nothing else:**

```json
{ "error": { "code": "internal_error", "message": "the server failed to handle the request",
             "detail": { "request_id": "hy44vj3q" } } }
```

The traceback stays in the log. The id is what turns "it broke" into a specific line in it — every
request is logged with that same id, its status, and its duration.

---

## 7. Anchors (P2-7, D21, D22)

A durable reference to a range of manuscript text. `specs/anchors.md` is the authority on how one
resolves; this is what the routes promise.

### `Anchor`

```json
{
  "id": "anc_000000000001",
  "project_id": "prj_000000000001",
  "document_id": "doc_000000000001",
  "from_pos": 24,
  "to_pos": 40,
  "quote": "harbour was grey",
  "prefix": "Arrival\n\nThe Quay\n\nThe ",
  "suffix": ".\n\nHe did not look back.",
  "status": "ok",
  "label": "the harbour",
  "document_version": 2,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z",
  "checked_at": "2026-01-01T00:00:00Z",
  "suggestion": null
}
```

`status` is `ok`, `stale`, or `orphaned`. The first two are the resolver's answer about the text;
**`orphaned` is derived from the chapter being soft-deleted and is never stored** (D22), which is
why restoring a chapter returns every one of its anchors to exactly the answer the resolver gave.

`from_pos`/`to_pos` are a **cache of the last resolution's conclusion**, not a promise about the
document a client is holding. `quote` is what the anchor *means*. `checked_at` is when resolution
last ran, which may be long after `updated_at`.

`suggestion` is `null`, or `{from_pos, to_pos, text}` — where a `stale` anchor's passage may have
gone, computed from its unedited surroundings. **Nothing on the server ever applies one.** It is
data on a finding; accepting it is a `PATCH` the writer asks for.

### `POST /api/documents/{document_id}/anchors`

```json
{ "from_pos": 24, "to_pos": 40, "version": 2, "label": "the harbour" }
```

A range and a version, and nothing else — `label` is optional and defaults to empty.
**The server derives `quote`, `prefix`, and `suffix` from the stored content**, so a client
cannot create an anchor whose quote disagrees with the manuscript: it is never asked what the
manuscript says. Answers `201` with the `Anchor`.

The stored positions are the ones the *quote* occupies, which is not always the range that was
sent: a selection that ran into the whitespace at the end of a paragraph, or began before the
first block, is trimmed onto the words it enclosed.

| Status | `code` | When |
|---|---|---|
| `409` | `version_conflict` | `version` is not the document's current one. Same `detail` as a save's — an anchor over text that has since changed is an anchor over text nobody looked at (D19) |
| `422` | `invalid_anchor_range` | A zero-length or backwards range; a range outside the document; a range beginning, ending, or spanning a scene break; a quote over 4,000 characters; a quote that is empty or only whitespace. The `message` is written to be shown to the writer |
| `404` | `document_not_found` | No live document with that id. A soft-deleted chapter is gone from this path like every other |

### `GET /api/documents/{document_id}/anchors`

`{ "anchors": [...] }`, in position order. **Resolved on read and not persisted**, so a document
opened after its file changed behind the app's back reports what is true *now* rather than what
was true at the last write. `404 document_not_found` for a missing or soft-deleted chapter.

### `GET /api/projects/{project_id}/anchors`

Every anchor in the project, in chapter order then position order. `?status=ok|stale|orphaned`
filters on the **effective** status, so `orphaned` finds the anchors of deleted chapters — which
is how the *Marks* tab finds what needs attention. An unrecognised value is a `422`.

Unlike the per-document route, this **reports the stored answers** rather than re-resolving:
re-resolving here would mean projecting every chapter in the manuscript to draw one panel, which
is the thing the document-list route exists not to do. A chapter's answers are refreshed the
moment it is opened or saved.

### `PATCH /api/anchors/{anchor_id}`

```json
{ "from_pos": 24, "to_pos": 43, "version": 3 }
```

Re-link, re-label, or both. A re-link carries **all three** of `from_pos`, `to_pos`, and
`version` or none of them — two of the three is a client that has lost track of which version it
is looking at, and it is refused as a `422`. A re-link re-derives the quote and context from the
new range and returns the anchor to `ok`; `label` alone presents no version, because a label is
not a text change.

Accepting a suggestion and picking a passage by hand are the same request. The server cannot tell
them apart and does not try: **nothing is ever repaired automatically.**

`409` on a stale version, `422` for a refused range, `404 anchor_not_found` for a missing anchor,
`404 document_not_found` when the anchor's chapter is soft-deleted — an orphaned anchor is
repaired by restoring its chapter, not by re-linking it.

### `DELETE /api/anchors/{anchor_id}`

`204`, no body. The only way an anchor ever goes away. `404 anchor_not_found` otherwise.

An anchor is addressed by a bare id, without naming its document or its project, for the same
reason a document is: the *Marks* tab holds anchors from every chapter at once, and making the
client carry a project id would put it in charge of a fact the server already knows.

---

## 8. Snapshots (P2-3, P2-12, D23)

A versioned copy of one chapter, taken **on handover, on demand, and before anything
destructive**. This is what makes deleting a chapter, restoring an old draft, and (in Phase 4)
accepting an AI rewrite recoverable rather than final.

### `SnapshotMeta`

```json
{
  "id": "snp_000000000001",
  "project_id": "prj_000000000001",
  "document_id": "doc_000000000001",
  "taken_at": "2026-01-01T00:00:00Z",
  "reason": "manual",
  "label": "before the rewrite",
  "word_count": 12,
  "version": 3,
  "size_bytes": 355
}
```

`reason` is one of `handover`, `manual`, `pre-restore`, `pre-delete`, `pre-import`. `version` is
the document version the stored content was at. `size_bytes` is the stored size of
`content_json`, which is what makes the retention arithmetic visible to somebody rather than only
to the phase plan.

**Content is deliberately absent**, for the reason `DocumentMeta` exists: drawing a chapter's
history must not pull every version of that chapter across the wire.

### `GET /api/documents/{document_id}/snapshots`

`{ "snapshots": [SnapshotMeta, …] }`, newest first.

**Not filtered by `deleted_at`.** The history of a deleted chapter is exactly what somebody
deciding whether to restore it wants to see.

### `POST /api/documents/{document_id}/snapshots`

```json
{ "reason": "manual", "label": "before the rewrite" }
```

Both optional; the default is `{"reason": "handover", "label": ""}`, which is the client's
commonest call — one on every chapter switch. Answers `200`:

```json
{ "captured": true, "snapshot": { "…": "SnapshotMeta" } }
```

**Only `handover` and `manual` are accepted.** The three `pre-*` reasons are the server's own,
each written inside the transaction of the operation it protects against — a client that could
ask for one could put a `pre-delete` in the history with nothing deleted, which is a lie in the
one list a writer consults when something has gone wrong. Anything else is a `422`.

**A `handover` whose content the newest snapshot already holds writes nothing and says so:**
`{"captured": false, "snapshot": null}`. That is the ordinary answer for a chapter nobody touched,
not a failure — only the automatic snapshots are deduplicated (phase-2-plan § 7, deviation A3).

`404` for an unknown document, and for a soft-deleted one: nothing writes to a chapter that is
out of every list, snapshots included.

### `GET /api/snapshots/{snapshot_id}`

One snapshot's metadata **plus** `content_json` — this is the route a preview reads, and the
content is the whole point of it. `404 snapshot_not_found` otherwise.

### `POST /api/snapshots/{snapshot_id}/restore`

```json
{ "version": 4 }
```

`version` is the document version the client believes it is at. Answers with a **`SaveResult`**,
because that is what this is: a restore is an ordinary save (D23). It goes through
`DocumentStore.save_content`, increments the version, re-derives the projection, and re-resolves
the anchors — one write path, no exceptions (data-model § 6).

The document's outgoing content is captured as `pre-restore` **inside the save's own
transaction**, after the D19 guard has passed, so a restore refused as stale has written nothing
at all — not even the snapshot that was about to protect it. `409 version_conflict` on a stale
version; `404` if the snapshot or its chapter is gone.

---

## 9. Markdown (P2-13, P2-14, D15)

Two exports and one import. The exports are **the one non-JSON corner of this API** — see § 1's
ground rules and the exception below.

### The non-JSON exception

`GET /api/documents/{document_id}/markdown` and `GET /api/projects/{project_id}/markdown` answer
with `Content-Type: text/markdown; charset=utf-8` and a `Content-Disposition: attachment` naming
the file. § 1 says "JSON in, JSON out"; this is the exception, and it is written down here rather
than left to be discovered.

An export is a **file a person saves**, not a payload a client parses. Wrapping it in JSON to
honour a ground rule would make every client unwrap it, and would cost the app the thing that
makes the client for it trivial: with an attachment, the control is an ordinary `<a href download>`
and the browser does the saving and the naming.

The disposition carries the name twice — an ASCII fallback and the RFC 5987 `filename*` form — so
a chapter called *Départ* saves under its own name where the browser understands it and under a
readable one where it does not. Everything a filesystem or a header would object to becomes a
hyphen; a title that reduces to nothing becomes `chapter.md`.

A failure is still the JSON envelope: a missing or deleted chapter is the ordinary `404`.

### `GET /api/documents/{document_id}/markdown` — one chapter

The chapter's content as Markdown, ending in a newline. **The title is not in the body.** This is
the round-trip artifact — importing this file back produces the same document, which is the
phase's sixth exit criterion — and a title written into the text would come back as a heading the
writer never typed. It travels in the filename instead.

The syntax is fixed in `archetype/manuscript/markdown/serialize.py` and stated case by case in
`server/tests/fixtures/markdown/cases.json`: `#`/`##`/`###`, `**`, `*`, `>`, `-`, `1.`, `* * *`
for a scene break (the same `SCENE_BREAK` the projection uses), and a trailing backslash for a
hard break. A paragraph that begins with a block marker, or that the writer typed as three
asterisks, is escaped and comes back as itself.

`404` if the chapter does not exist or has been deleted — a deleted chapter is absent from every
read (D22), and an export is a read.

### `GET /api/projects/{project_id}/markdown` — the whole manuscript

Every **live** chapter in order, each preceded by its title as an H1, and **every heading inside a
chapter written one level down** — a body H1 as `##`, H2 as `###`, H3 as `####`.

The demotion is what makes level 1 mean "chapter" in this file and only in this file. The closed
schema permits an H1 inside a chapter and a writer will type one; without the shift the boundaries
and the body headings are the same character, and re-importing with `split-on-h1` cuts a chapter
in two at a heading that was never a chapter break. It is also the honest structure: in one
combined document the chapter titles *are* the top level. The cost is at the floor — the editor
offers three levels, so a body H3 is written as `####` and an import brings it back at level 3
with a notice saying so (phase-2 plan § 7, `D15`). The per-chapter export above is untouched.

**No round trip is promised here** (phase-2 plan § 2, ruling 4). The file needs a chapter boundary
the schema has no node for, so reading it back would mean inventing a container syntax and parsing
it — a private format wearing Markdown's clothes. It is a reading and hand-off artifact.
`split-on-h1` will read one back into chapters because that is a useful thing to do with a file
shaped like this, not because there is a promise attached — and the demotion is what makes that
reading give back the chapters the manuscript actually had.

Deleted chapters are absent, from the one predicate every read applies.

### `POST /api/projects/{project_id}/import` — create chapters from Markdown

```json
{ "markdown": "# Ashore\n\nThe tide turned.\n", "mode": "split-on-h1", "title": null }
```

| Field | |
|---|---|
| `markdown` | The file's text. Anything is valid input — a plain text file is valid Markdown, and a writer will try one |
| `mode` | `one-chapter` or `split-on-h1`. Anything else is a `422` |
| `title` | Optional. Names the single chapter `one-chapter` creates; `split-on-h1` takes each title from its own heading and ignores this. Omitted or `null`, the store names the chapter as it names any new one |

`one-chapter` keeps a leading H1 **in the text**. Eating it would be reasonable and would break
the round trip, which is the stronger rule. `split-on-h1` cuts at every top-level H1, takes it as
the chapter's title, and gives any text before the first one a chapter of its own.

**`201`**, with the chapters that were created and what could not be kept:

```json
{
  "documents": [ { "id": "doc_…", "title": "Ashore", "…": "…" } ],
  "dropped": [
    { "element": "code fence", "line": 5,
      "detail": "the text was kept as a paragraph; the code formatting was not" }
  ]
}
```

`documents` are `DocumentMeta` (§ 3) — metadata, not whole documents, because an import of a long
file would otherwise return the whole manuscript to a client that is about to redraw a chapter
list from it.

`dropped` is **never an error and never empty of meaning**. Where a construct carried words, the
words are in the chapter and only the construct is gone — a code fence becomes a paragraph, a
link keeps its text and loses its target, an image leaves its alt text, a heading below level 3 is
imported at level 3. `element` names it, `line` is 1-based into the file the writer chose, and
`detail` says what actually happened. A file this server wrote drops nothing.

A table, a footnote, and raw HTML produce **no** entry, because nothing is dropped: the parser is
strict CommonMark with HTML off, so none of them is syntax it knows and every character survives
as prose.

**Import creates chapters; it never replaces the text of one** (ruling 5), which is what keeps
`PUT /api/documents/{did}/content` the only route by which existing manuscript text changes.
Replacing a chapter is import-then-delete, and both are already recoverable.

| Refusal | |
|---|---|
| `404` | No such project |
| `413` | The file is over 8 MiB, or one chapter it describes is over `MAX_CONTENT_BYTES`. **Nothing was created** — every chapter is measured before the first is written |
| `422` | An unknown `mode`, a title too long, or an undeclared field |

---

## 10. The story bible (P3-9 … P3-11, D25 – D28)

Twenty-three routes under the same `/api` prefix, written in `api/bible_routes.py` and
`api/bible_schemas.py` — a second pair of modules, not a second router: the prefix, the envelope,
and the ordering guarantees are the API's, not the bible's. `specs/bible.md` is the authority on
what an entry *means*; this section is what the wire promises.

**The two closed vocabularies are not restated on the wire.** `kind` and `relation` cross as plain
strings and are refused by `archetype/bible/schema.py`, which is the one place their members are
written down (D26). A `Literal` of the seven kinds in the request models would be the second copy
that decision exists to prevent — and it would be the copy that drifts, because the client fetches
the other one. The rule has an exact boundary: a vocabulary a **module constant** owns *is*
restated and held to it by a test (`EntryStatusFilter`, `CitationRoleIn`), exactly as
`AnchorStatusFilter` is; one the **served definition** owns never is.

**A status with no writer gets no route that writes it.** `proposed`, `rejected`, `superseded`,
and `agent` are absent from every request model, not merely defaulted away — the rule the `pre-*`
snapshot reasons already follow. They stay readable as filters, because a filter that cannot ask
for a value the column can hold is one that needs changing the moment a writer exists.

### `GET /api/bible/schema` — the served definition (P3-11, D26)

**The one route in the API with no project scope**, because the vocabulary is the product's and
not a manuscript's. It answers the same bytes for every caller.

```json
{
  "field_types": ["entry_ref", "enum", "list_of_text", "long_text", "story_time", "text"],
  "kinds": [
    { "kind": "character", "label": "Character", "plural": "Characters",
      "fields": [
        { "name": "role", "type": "enum", "label": "Role", "required": false, "help": "",
          "members": ["protagonist", "antagonist", "supporting", "minor", "chorus"],
          "kinds": [] }
      ] }
  ],
  "relations": [
    { "relation": "member_of", "label": "is a member of", "inverse_label": "has as a member",
      "from_kinds": ["character"], "to_kinds": ["faction"], "symmetric": false }
  ]
}
```

**A field carries every key, whatever its type.** `help`, `members`, and `kinds` are always
present, empty where the type does not use them, because the client renders **one** generic form
over this and a shape whose key set depends on the value of another key is one every consumer has
to branch on. The contract fixture compares key sets exactly.

`fields` is **in the order a form renders them**. Adding a field to a kind is a change to
`archetype/bible/schema.py` and this route's fixture, and to nothing else — which is the whole of
what D26 bought.

No `ETag`. A conditional `304` would cost the `response_model`, and with it the generated schema
for the most load-bearing shape in the phase; the definition is a few kilobytes and the client
reads it once per project open.

### `Entry` — the shape every kind shares

| Field | Notes |
|---|---|
| `id`, `project_id` | `ent_…` |
| `kind` | One of the seven. **Immutable** — absent from `PUT` for that reason |
| `name`, `summary`, `body_md` | Present on every kind |
| `attributes` | The per-kind map, already validated against the kind's definition |
| `status`, `origin` | `accepted` and `user` in Phase 3; the rest have no writer |
| `revision` | Monotonic. The D19 guard, applied to entries |
| `needs_review`, `review_reason` | The retcon flag and what set it. **Orthogonal to `status`** |
| `created_at`, `updated_at`, `deleted_at` | `deleted_at` is `null` in every read but the deleted list |

### `GET /api/projects/{project_id}/entries` — the list, filtered

Query: `kind`, `status`, `needs_review`, `q`, `include_deleted`. They compose, and every one is
optional. `q` is a `LIKE` filter over names, aliases, and summaries — **a filter, not search**, and
deliberately not `/search`: Phase 5 owns search and owns that route name.

```json
{ "entries": [ … ], "counts": { "character": 4, "place": 2, "item": 0 }, "truncated": false }
```

`counts` is the number of **live** entries of each kind, **unfiltered**, so a client showing only
the places can still say how many characters there are. Every kind appears, including the ones with
none.

`truncated` is exact rather than inferred: the route asks the store for `SEARCH_LIMIT + 1` and
trims, so a project with exactly two hundred matches does not send the writer looking for a row
that is already on screen.

### `POST /api/projects/{project_id}/entries` — create → `201`

Body: `kind`, `name`, and optionally `summary`, `body_md`, `attributes`. **`status` and `origin`
are not accepted**, by create or by update.

An unknown kind, an attribute the kind does not declare, one of the wrong type, a value outside a
declared `enum` set, an `entry_ref` to a kind the field does not allow, and a missing required
field are each a `422 invalid_attributes` **naming the field**, with nothing written.

### `GET /api/projects/{project_id}/entries/deleted` — the restore surface (D25)

Most recently deleted first. Every other read path filters these out; this is the one that asks for
them. A soft delete is only recoverable if there is somewhere to recover it from.

### `GET /api/entries/{entry_id}` — one entry, with what points at it

```json
{ "entry": { … }, "citations": [ … ], "link_count": 3,
  "narrative_position": { "entry_id": "ent_…", "document_id": "doc_…",
                          "order_index": 0, "from_pos": 24 } }
```

The citations carry each anchor's **current** status — `ok`, `stale`, or `orphaned` — derived in
the one place D22 put it, so a citation can never disagree with the *Marks* tab about the same
anchor.

`narrative_position` is derived from the `source` anchor and never stored, so it follows a chapter
reorder for free; an entry with no source anchor simply has none, and one whose source sits in a
soft-deleted chapter has none either.

`link_count` is the live links in **either** direction — what a detail header shows. The links
themselves are their own route, because a list of them is a panel of its own.

A deleted entry is readable here: somebody deciding whether to restore it needs to see it.

### `PUT /api/entries/{entry_id}` — edit, presenting the revision (D19, ruling 3)

Body: `revision`, and any of `name`, `summary`, `body_md`, `attributes`, plus `retcon` and
`reason`. `kind` and `status` are absent, for the two different reasons above.

**An absent field and a field sent as empty are different requests.** A `PUT` that does not mention
`summary` keeps it; one that sends `attributes: {}` clears them. The distinction is read from
pydantic's `model_fields_set`, not from a sentinel value.

`retcon` is `null` by default and takes the store's **computed** answer — true when `name`,
`attributes_json`, or `status` moved, false for a `summary`- or `body_md`-only edit. `true` or
`false` overrides it in that direction.

```json
{ "entry": { … }, "revision": 3, "retcon": true,
  "flagged": ["ent_…", "ent_…"], "changed_fields": ["name"] }
```

`flagged` is the point: the writer is told which entries this retcon put into the review queue **at
the moment it happens**, rather than discovering it by opening the queue. `changed_fields` reports
the computed answer even when the request overrode it, so an override is legible as one.

A stale `revision` is refused with `409 entry_version_conflict` — **its own code**, not
`version_conflict`, because the two surfaces recover differently: the editor offers to reload a
chapter, the entry form offers to reload a record, and one code for both would make that a branch
on which request was in flight.

```json
{ "error": { "code": "entry_version_conflict",
             "message": "entry ent_… is at revision 2, not 1; reload before saving",
             "detail": { "entry_id": "ent_…", "presented_revision": 1,
                         "current_revision": 2, "updated_at": "…" } } }
```

### `DELETE /api/entries/{entry_id}` — soft delete (D25) → `200` with the entry

Nothing cascades. The row, its revisions, its links, and its citations all stay; the entry leaves
every list, count, link view, and the review queue, because all of those filter on one predicate.
Deleting is **not** a retcon — the entry has not changed its claims, it has left the bible.

`200` rather than `204`, for the reason a chapter delete answers with its metadata: the client has
just been told the entry is gone and needs to say what went and when.

### `POST /api/entries/{entry_id}/restore` → `200`

Its links come back because nothing ever removed them: an endpoint's deletion *hides* a link
through the three-way predicate rather than writing to it. A link deleted in its own right stays
deleted. Restoring a live entry is a no-op, not an error.

### `POST /api/entries/{entry_id}/review/clear` — the writer has looked

Body: `revision`. Answers the same shape a `PUT` does. **Never a retcon** — not by default and not
by override: a queue that re-flags every neighbour as it is worked through is a queue that never
empties and stops meaning anything.

### Revisions — `GET …/revisions`, `GET …/revisions/{n}`, `POST …/revisions/{n}/restore`

The list carries **metadata only** — `entry_id`, `revision`, `revised_at`, `reason`, `retcon`,
`origin` — newest first, complete from creation, and deliberately **not** filtered by `deleted_at`.
Reading one adds `state`: the entry as it was **after** that write, so revision *n* is what the
entry was at revision *n* and reading a past state is one row rather than a replay. `state` carries
no `needs_review`.

A restore presents the entry's **current** revision, not the one being restored, because it goes
through the ordinary update path: it bumps `revision`, appends a new revision at the top of the
history rather than rewriting it, is guarded by D19, and computes its own retcon answer. It answers
the same shape a `PUT` does. An unknown number is `404 revision_not_found`.

### Links (P3-10, ruling 7)

| Route | Notes |
|---|---|
| `GET /api/projects/{pid}/links` | Every **live** link, optionally of one `relation`. An unknown relation is a `422`, not an empty list |
| `POST /api/projects/{pid}/links` | `from_entry`, `relation`, `to_entry`, and optional `since`, `until`, `attributes` → `201` |
| `GET /api/entries/{eid}/links` | Both directions in one answer |
| `PATCH /api/links/{lid}` | Bounds and attributes, **and nothing else** |
| `DELETE /api/links/{lid}` | Soft delete → `200` with the link |
| `POST /api/links/{lid}/restore` | `409 duplicate_link` when a live link now says the same thing |

**Live means the link is not deleted *and neither endpoint is*** — the three-way predicate.

**A relation is refused on the side it is offered from.** `member_of` runs character → faction;
faction → character is a different statement and is refused, never silently reversed. The only
exception is a relation whose *definition* says it is symmetric, and that answer comes from the
vocabulary rather than from a list any consumer keeps.

An entry's links come back as **views**, each marked with which end this entry is on and labelled
the way that end reads it:

```json
{ "links": [ { "link": { … }, "end": "from", "other_id": "ent_…", "other_name": "The Company",
               "other_kind": "faction", "label": "is a member of" } ] }
```

A symmetric relation is one row and appears **once from each side**, never twice from either.

`PATCH` takes bounds and attributes only. The endpoints and the relation are absent on purpose:
changing either is a delete and a create, and both are recoverable; editing them in place would let
a link's own history describe a relationship it never had. A bound is genuinely nullable, so
`since: null` clears it — unlike an entry's content fields, where `null` is a client sending the
wrong thing. No revision is presented, because a link has none: the D19 guard lives on the entry.

An entry linked to itself is a `422`, and so is a duplicate of a live link — including a restore
that would produce one, because two identical rows would double-count in Phase 8's chart with
neither being the wrong one to remove.

### Citations (P3-10, P3-7)

| Route | Notes |
|---|---|
| `POST /api/entries/{eid}/citations` | `anchor_id` and a `role` → `201`. Citing what is already cited in that role is a no-op |
| `DELETE /api/entries/{eid}/citations/{aid}` | Optional `?role=`; without one, every role. Answers `{ "removed": n }` |
| `GET /api/anchors/{aid}/entries` | The reverse view — which live entries cite this anchor |

A `stale` or `orphaned` anchor **may** be cited: that is exactly the anchor an entry wants, so it
can say the passage behind it has moved.

**Uncite removes the join, never the anchor.** An anchor is a fact about the manuscript, and *Marks*
is where one is removed; the entry keeps what a person typed and loses one reason to believe it.
Removing a citation that is not there returns zero rather than a `404`.

### `POST /api/documents/{document_id}/entries` — *Add to bible* → `201`

The interaction the whole product is arranged around, in its manual form.

Body: `from_pos`, `to_pos`, `version`, `kind`, `name`, and optionally `summary`, `body_md`,
`attributes`, `label`, `role`. **A range and a version, never a quote** — the server derives the
words, exactly as marking a passage does, so an entry created from a selection cannot cite a
passage the manuscript does not contain (ruling 8).

One transaction over three tables: a stale `version` is refused with the same `409` a save gets and
**leaves no anchor, no entry, and no citation**.

```json
{ "entry": { … }, "anchor": { … }, "role": "source" }
```

### `GET /api/projects/{project_id}/storytime` — D28's three answers

```json
{ "order": [ { "entry_id": "ent_…", "name": "The departure",
               "label": "the first grey morning", "sort_key": 1.0, "era": "Before" } ],
  "unplaced": [ … ],
  "contradictions": [ { "kind": "cycle", "events": ["ent_…", "ent_…"], "detail": "…" } ],
  "eras": [ { "era": "Before", "rank": 1.0 } ] }
```

`order` and `unplaced` **partition** the events: every event appears in exactly one of them,
always. An event with neither an edge nor a `sort_key` is unplaced — not appended, not dropped, and
never guessed at (D9).

There are exactly **two** contradiction kinds — `cycle` and `sort_key_inversion` — and they are
independent: an edge inside a cycle whose keys also disagree is reported as both, because a writer
fixes them differently.

**A contradiction never costs the rest of the graph.** A cycle is reported *and* everything outside
it is still ordered, because a timeline that refuses to draw anything until two events agree is a
timeline nobody can use to find the disagreement.

`label` is what a person reads as "when" and it **never sorts**; `sort_key` is the only number in
story-time, and it is a float so an event can be inserted between two others without renumbering.
An era is a name on an event, not a stored entity, and ranks by the least `sort_key` among its
members — `null` when none of them has one, which is an era nobody has placed yet rather than a
contradiction.

Phase 3 renders no timeline; Phase 8 owns that. This route exists because a stored shape with no
consumer is a shape nobody has proved sufficient.

**Composition that is not HTTP does not live in the route.** It is
`StoryTimeOut.of(project_timeline(handle))`; the two reads and the pure call are
`archetype/bible/timeline.py`, so Phase 6's agent and Phase 8's timeline get the same answer
without going through a request.

---

## 11. Serving the app itself (P1-14)

Not an API route, but part of the contract for how the server is reached.

**Two-process dev:** uvicorn on `127.0.0.1:8787`, Vite on `127.0.0.1:5173` proxying `/api` to it.

**Single process:** with a built `web/dist` present, the same FastAPI process serves it at `/` and
the whole app is one uvicorn on 8787 — the real target shape (D7).

The mount is registered **after** every API route. Starlette matches in order, so a bundle can
never shadow the API: a file at `dist/api/health` loses to the route of the same name. A path
under the mount that matches no file answers with the standard **404 envelope**, not with
`index.html`, so a typo'd route says it is a typo rather than returning a blank page. (The client
has no router — see `web/src/App.tsx` — so there is no deep link to rewrite.)

`index.html` is served with `Cache-Control: no-cache`; the fingerprinted files under `assets/` are
not, and are safe to cache. Without that, a browser would go on loading the previous build's
scripts after an upgrade.

With no bundle to serve, the server still starts and serves its API, and `GET /` answers `404`
with `code: "web_not_built"` and a `detail` saying what to run. A bare "Not Found" at the address
the README tells you to open is a bad way to learn you skipped a build step.

---

## 12. What is deliberately absent

Named, because each is a plausible thing to reach for and find missing:

| Absent | Arrives |
|---|---|
| ~~Chapter reorder, delete, and restore~~ | **Arrived** — § 5 above (P2-2, P2-11) |
| ~~Snapshot capture, history, and restore~~ | **Arrived** — § 8 above (P2-3, P2-12) |
| ~~Markdown import and export~~ | **Arrived** — § 9 above (P2-13, P2-14) |
| ~~Anchors~~ | **Arrived** — § 7 above (P2-7) |
| ~~Bible entries, links, revisions~~ | **Arrived** — § 10 above (P3-9 … P3-11) |
| Chat, streaming, provider settings | Phase 4 |
| Search — keyword, semantic, or hybrid | Phase 5 |
| Agent runs, proposals, findings | Phase 6 |
| WebSocket or SSE of any kind | Phase 4 |
| Pagination on any list route | When a manuscript needs it; a chapter list is tens of rows |
| Any route returning a setting | Never for secrets (D8); `Settings.public_dump` is the only sanctioned shape if one is ever needed |

There is **no stub route** for any of these. A route that answers `501` is a route a client can
come to depend on.
