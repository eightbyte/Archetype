# Archetype — API Contract

**Status:** Phase 1 surface as built · **Version:** 1.0 · **Date:** 2026-08-30
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1 (D7, D8, D18, D19)
**Companion:** [`specs/data-model.md`](data-model.md) — the same vocabulary in storage

This document covers **every route that exists**. Chat and streaming arrive in Phase 4, search in
Phase 5, agent runs in Phase 6; each extends this document as it lands.

The generated OpenAPI schema at `http://127.0.0.1:8787/openapi.json` (browsable at `/docs`) is
produced from the same pydantic models and is authoritative for exact types. This document is
authoritative for **behaviour** — what a route promises, what it refuses, and why.

---

## 1. Ground rules

**Base URL** `http://127.0.0.1:8787/api`. Loopback is a deliberate posture, not an oversight:
single user, no auth, no HTTPS, no CORS (D7). There is **no authentication**, because there is no
second party. Anything reaching this port is already inside the writer's machine.

**JSON in, JSON out.** UTF-8 throughout. Request bodies are `application/json`.

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
| `GET` | `/api/projects/{project_id}/outline` | `200` | `404` |
| `GET` | `/api/documents/{document_id}` | `200` | `404` |
| `PUT` | `/api/documents/{document_id}/content` | `200` | `400`, `404`, `409`, `413`, `422` |
| `PATCH` | `/api/documents/{document_id}` | `200` | `404`, `422` |

Any route can also answer `500` (§ 6).

**Documents are addressed without naming a project.** Storage is one file per project (D3), so
`manuscript/locator.py` resolves the bare id to a file; see data-model § 4. The alternative —
`/api/projects/{pid}/documents/{did}` — would have put a redundant, spoofable scope in every
autosave URL.

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
  "updated_at": "2026-01-01T00:00:00Z"
}
```

The list routes return these deliberately. **The outline panel must never pull the whole
manuscript to draw a chapter list**, and that discipline starts at the wire shape rather than at
a client's good intentions.

`kind` is `"chapter"` in Phase 1. Later phases add kinds; they do not repurpose this one.

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
  "updated_at": "2026-01-01T00:00:00Z"
}
```

The derived values in that response are **authoritative** and replace whatever the client's mirror
had computed (D18).

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
| `version_conflict` | 409 | Stale save (D19). Nothing was written |
| `invalid_document` | 400 | Not a well-formed ProseMirror document |
| `payload_too_large` | 413 | Over the 2 MiB per-document limit |
| `validation_error` | 422 | Body or path failed validation; `detail` is pydantic's error list |
| `not_found` | 404 | No such route |
| `method_not_allowed` | 405 | Wrong method for an existing route |
| `internal_error` | 500 | An unhandled exception (below) |
| `web_not_built` | 404 | `GET /` with no frontend mounted (§ 7) — a diagnostic, not part of the API |

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

## 7. Serving the app itself (P1-14)

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

## 8. What is deliberately absent in Phase 1

Named, because each is a plausible thing to reach for and find missing:

| Absent | Arrives |
|---|---|
| Chapter reorder and delete | Phase 2, with the snapshot that makes deletion safe |
| Snapshots, anchors, Markdown import/export | Phase 2 |
| Bible entries, links, revisions | Phase 3 |
| Chat, streaming, provider settings | Phase 4 |
| Search — keyword, semantic, or hybrid | Phase 5 |
| Agent runs, proposals, findings | Phase 6 |
| WebSocket or SSE of any kind | Phase 4 |
| Pagination on any list route | When a manuscript needs it; a chapter list is tens of rows |
| Any route returning a setting | Never for secrets (D8); `Settings.public_dump` is the only sanctioned shape if one is ever needed |

There is **no stub route** for any of these. A route that answers `501` is a route a client can
come to depend on.
