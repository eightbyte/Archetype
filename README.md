# Archetype

A browser-based workspace for writing and maintaining a long narrative, with an AI agent that
assists rather than authors. A rich-text manuscript editor sits in the centre; an outline panel
(table of contents, timeline, character interactions, story bible) sits on one side; an agentic
chat panel sits on the other.

React + TypeScript frontend, Python (FastAPI) backend, one SQLite file per project. Single user,
localhost, Windows 11 primary.

**Current state: Phase 2 built** — you can write in it, and you can maintain what you wrote.
Create a project, add chapters, write formatted prose that saves itself and survives a reload, and
move around the manuscript by its headings. Reorder chapters, rename them, delete one and get it
back. Mark a passage and watch the highlight follow it as you type around it; find every mark in
one place, see which have gone stale, and repair one by hand. Mark a version of a chapter, read it
beside what is there now, and restore it. Export a chapter or the whole manuscript to Markdown,
and import Markdown back as chapters.

There is still no AI, no story bible, and no search; those are Phase 4 onwards. See
[specs/project-outline.md](specs/project-outline.md) for the whole plan, and each phase plan's
final sections for what that phase actually shipped.

---

## Prerequisites

| | Version | Notes |
|---|---|---|
| Python | 3.11 or newer | Built and tested here on 3.14. |
| Node.js | 20 or newer | Built and tested here on 24. |

Nothing else — no database server, no Docker. A project is a single `.sqlite` file.

## Bootstrap

From a clean clone, in PowerShell:

```powershell
# --- server ---
cd server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd ..

# --- web ---
cd web
npm install
cd ..
```

## Run

There are two ways to run it. Use the first while you are working on the app, the second to see
it the way it ships.

### Two processes (development)

Vite serves the app with hot reload and proxies `/api` to the Python server. Open two terminals.

```powershell
# terminal 1 - the API on http://127.0.0.1:8787
cd server
.\.venv\Scripts\python.exe -m archetype
```

```powershell
# terminal 2 - the web app on http://127.0.0.1:5173, with /api proxied to the server
cd web
npm run dev
```

Then open <http://127.0.0.1:5173>. You land on the project picker.

### One process (the shipping shape)

Build the frontend once and the Python server serves it too, from a single port. This is the
shape the finished product runs in, and it needs no Node process at all.

```powershell
# build the app (repeat after any change to web/)
cd web
npm run build
cd ..

# serve the API and the built app together on http://127.0.0.1:8787
cd server
.\.venv\Scripts\python.exe -m archetype
```

Then open <http://127.0.0.1:8787>.

The server looks for `web/dist` and mounts it at `/` when it holds an `index.html`. If you have
not built the app, the server still starts and serves its API — and `http://127.0.0.1:8787/` tells
you so rather than answering a bare "Not Found". Point `ARCHETYPE_WEB_DIST` somewhere else to
serve a bundle from another directory, or set it empty to never serve one.

Use the two-process mode while you are working on the frontend — it has hot reload; this one does
not.

## Using it

**The picker** lists every project in your data directory, most recently touched first, with its
chapter and word counts. Type a title and *Create project* to start one; it opens straight into a
writable first chapter. Projects you have opened before are offered as a *Recent* shortcut.

**The workspace** has three regions: the outline panel, the manuscript, and the assistant panel
(a placeholder until Phase 4). Drag the dividers between them, or focus one and use the keyboard:

| Key | What it does |
|---|---|
| ← / → | Move the divider by 16px |
| Shift + ← / → | Move it by 160px |
| Home / End | Narrowest / widest |
| Enter or Space | Collapse or expand the pane |

Pane widths, which panes are collapsed, the active outline tab, and which project you had open
are remembered in your browser. They are conveniences only — your manuscript lives in the project
file, never in the browser.

**Writing.** The editor offers paragraphs, headings 1–3, bold, italic, blockquote, bulleted and
numbered lists, a horizontal rule that reads as a scene break, hard breaks, and undo/redo — and
nothing else, deliberately. Markdown shortcuts work as you type: `# ` for a heading, `- ` for a
bullet, `> ` for a quotation.

**Saving** happens on its own: about a second and a half after you stop typing, when you leave
the editor, and before anything that would take you away from the chapter. The indicator beside
the chapter title always says where things stand — *Saved*, *Unsaved changes*, *Saving…*, or
*Save failed*. A failed save keeps every word, says what went wrong, and keeps retrying; you can
also retry immediately. If the chapter changed somewhere else while you were editing it, the save
is refused and you are asked what to do — nothing is ever silently overwritten.

**The contents tab** shows every chapter and its headings across the whole manuscript, with word
counts. Click a heading to go to it, in this chapter or another one. The chapter you have open
updates as you type; the rest come from the server. *New chapter* adds one at the end, and
clicking the chapter title in the editor header renames it.

Each chapter row also carries controls to **move it up or down** — by clicking, or with the arrow
keys once the control has focus — to **rename** it in place, to **export** it as Markdown, and to
**delete** it. Deleting is a soft delete: the chapter leaves every list and count, its text stays
exactly where it was, and *Deleted chapters* at the foot of the tab brings it back. Dragging a
chapter row does the same as the move controls.

**Marks.** Select a passage in the editor and a small control appears offering *Mark passage*. A
mark is a durable reference to those words: it is drawn as a highlight, and it follows the passage
as you write above, below, and around it. The *Marks* tab lists every mark in the project, grouped
by chapter, with its status.

A mark whose words you have rewritten or deleted goes **stale** rather than moving to something
approximately right. That is deliberate and it is the point of the whole feature: a reference that
silently re-points itself at the wrong paragraph is worse than one that admits it is lost. A stale
mark can be repaired from the *Marks* tab — sometimes with a suggested passage to accept, always
by selecting new text and choosing *Re-link here*. Nothing repairs itself.

Marks are the foundation the story bible is built on in Phase 3. For now they are yours to use as
bookmarks.

**History.** *Mark version* records the chapter as it stands, with a label. The history panel
lists every version — the ones you marked, the ones taken automatically when you leave a chapter,
and the ones taken just before something destructive — and any of them can be read beside the
chapter as it is now, and restored. Restoring is an ordinary save: it can itself be undone, from
the version it takes on the way past.

**Markdown, in and out.** *Export* on a chapter row saves that chapter; *Export manuscript* at the
foot of the contents tab saves every live chapter in order, each under its title. A chapter
exported and imported back is the same chapter — headings, emphasis, lists, scene breaks and all.

*Import Markdown…* takes a file you drop on it or text you paste. It can make one chapter of the
whole file, or a chapter per top-level heading. It always **appends**; it never overwrites a
chapter you already have. Anything Markdown can express that this editor cannot hold — a code
fence, a link's target, an image, a heading deeper than three — is reported afterwards, with the
line it was on and what became of it. The words are kept; only the formatting is lost.

## Test and lint

```powershell
# backend: pytest, ruff
cd server
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format .

# frontend: vitest, tsc
cd web
npm test
npm run typecheck
npm run build
```

Tests marked `@pytest.mark.live` touch a real provider and are excluded by default. Nothing else
in either suite touches the network, a real model, or a real API key.

## The API

The server exposes one JSON API under `/api`, on `127.0.0.1:8787`. Interactive documentation is
generated from the code at <http://127.0.0.1:8787/docs>; the written contract — what each route
promises, what it refuses, and why — is [specs/api-contract.md](specs/api-contract.md), and the
storage behind it is [specs/data-model.md](specs/data-model.md).

| Method | Route | What |
|---|---|---|
| `GET` | `/api/health` | Liveness and the running version |
| `GET` | `/api/projects` | Every readable project, plus any file that could not be read |
| `POST` | `/api/projects` | Create a project, seeded with one empty chapter |
| `GET` | `/api/projects/{pid}` | One project with its document list |
| `GET` | `/api/projects/{pid}/documents` | Ordered chapter metadata, **without** content |
| `POST` | `/api/projects/{pid}/documents` | Add a chapter at the end |
| `GET` | `/api/projects/{pid}/documents/deleted` | The chapters you can restore |
| `PUT` | `/api/projects/{pid}/documents/order` | Rewrite the chapter order |
| `GET` | `/api/projects/{pid}/outline` | The table of contents across every chapter |
| `GET` | `/api/documents/{did}` | One document including its content |
| `PUT` | `/api/documents/{did}/content` | Save (see below) |
| `PATCH` | `/api/documents/{did}` | Rename |
| `DELETE` | `/api/documents/{did}` | Soft-delete a chapter |
| `POST` | `/api/documents/{did}/restore` | Undo that |
| `POST`/`GET` | `/api/documents/{did}/anchors` | Create a mark from a range; list a chapter's |
| `GET` | `/api/projects/{pid}/anchors` | Every mark in the project, filterable by status |
| `PATCH`/`DELETE` | `/api/anchors/{aid}` | Re-link or relabel a mark; remove one |
| `GET`/`POST` | `/api/documents/{did}/snapshots` | A chapter's history; mark a version |
| `GET` | `/api/snapshots/{sid}` | One version, with its content |
| `POST` | `/api/snapshots/{sid}/restore` | Write it back, as an ordinary save |
| `GET` | `/api/documents/{did}/markdown` | One chapter as a Markdown file |
| `GET` | `/api/projects/{pid}/markdown` | Every live chapter as one Markdown file |
| `POST` | `/api/projects/{pid}/import` | Create chapters from Markdown |

The two Markdown exports are the one **non-JSON** response here: they answer `text/markdown` with
a filename attached, because an export is a file you save rather than a payload a client parses.
Everything else, failures included, is JSON.

Every failing response uses one envelope:

```json
{ "error": { "code": "version_conflict", "message": "…", "detail": { "current_version": 7 } } }
```

`code` is the stable name to branch on; `detail` is `null` when there is nothing to add. A `500`
carries only a `request_id`, which is the one thing that crosses to the browser — every request is
logged server-side with that id, its status, and how long it took, and the traceback stays in the
log where it is useful.

### Saving

`PUT /api/documents/{did}/content` takes the document and the version the client believes it is
editing:

```json
{ "content_json": { "type": "doc", "content": [] }, "version": 3 }
```

In one transaction the server validates the document, derives `text_plain`, the heading list, and
the word count from it, increments the version, and writes. It answers with the new version and
the derived values — the server's projection is the authoritative one (D18).

If the presented version is not the stored one, **nothing is written** and the answer is `409`
with the current version in `detail` (D19). The client warns and offers a reload. It never merges.
This route is the only way manuscript text changes, which is what makes "the writer owns the
words" a property of the system rather than a promise.

## Configuration

Settings layer **defaults < `config.yaml` < `ARCHETYPE_*` environment variables**, with the
environment winning so a shell can always override a file. `config.yaml` is optional — a fresh
clone has none — and lives at the repository root unless `ARCHETYPE_CONFIG_FILE` points
elsewhere. It is gitignored.

| Key | Env var | Default | What it does |
|---|---|---|---|
| `data_dir` | `ARCHETYPE_DATA_DIR` | `<repo>/data` | Runtime data root. Project files live in `<data_dir>/projects`. A relative value resolves against the repository root. |
| `host` | `ARCHETYPE_HOST` | `127.0.0.1` | Bind address. Loopback is deliberate: single user, no auth, no HTTPS (D7). |
| `port` | `ARCHETYPE_PORT` | `8787` | Server port. |
| `log_level` | `ARCHETYPE_LOG_LEVEL` | `info` | One of `critical`, `error`, `warning`, `info`, `debug`, `trace`. Case-insensitive. |
| `web_dist` | `ARCHETYPE_WEB_DIST` | `<repo>/web/dist` | The built frontend to serve from the API process. Mounted at `/` when the directory holds an `index.html`; skipped with a log line when it does not. Set it empty to never serve one. A relative value resolves against the repository root. |
| — | `ARCHETYPE_CONFIG_FILE` | `<repo>/config.yaml` | Which YAML file the middle layer reads. Environment only. |

Example `config.yaml`:

```yaml
port: 8787
log_level: debug
data_dir: D:/manuscripts
web_dist: web/dist
```

### Secrets

There are no secret settings yet — provider keys arrive in Phase 4 — but the discipline is
already enforced (D8):

- a secret-valued setting is any field annotated `SecretStr`;
- it is read from the **environment only**; `config.yaml` cannot supply one;
- it must be declared `Field(exclude=True)` or the settings class fails to build;
- it is stripped from every serialization, and no route ever returns one.

API keys therefore stay out of the browser, out of `localStorage`, out of the bundle, and out of
Git.

## Your projects

```
data/projects/
├── the-long-road-4k2h9w.sqlite
└── test-manuscript-p3n8qx.sqlite
```

One SQLite file per project (D3), named from a slug of the title plus a short suffix. The project
list is derived by scanning that directory (D17) — there is no registry file, so **backup is a
file copy** and a file copied back in simply reappears in the list. A `.sqlite` file that is not
an Archetype project is skipped, not treated as an error.

The `data/` directory is gitignored. Your manuscripts are never committed.

## Repository layout

```
server/          Python package `archetype` - FastAPI app, config, project store, migrations
web/             Vite + React 18 + TypeScript client
specs/           The contract: outline, decision register, phase plans, data model, API
data/            Runtime project files (gitignored)
```

The specs are binding, not background reading. `specs/development-phases.md` holds the decision
register (`D1`–`D20`); `specs/phase-1-plan.md` holds the current work items and their as-built
deviations.
