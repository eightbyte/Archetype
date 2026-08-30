# Archetype

A browser-based workspace for writing and maintaining a long narrative, with an AI agent that
assists rather than authors. A rich-text manuscript editor sits in the centre; an outline panel
(table of contents, timeline, character interactions, story bible) sits on one side; an agentic
chat panel sits on the other.

React + TypeScript frontend, Python (FastAPI) backend, one SQLite file per project. Single user,
localhost, Windows 11 primary.

**Current state: Phase 1, Group A (foundations) complete** — the toolchain, configuration,
project file schema, migration runner, and project store are built and tested. There is no
editor and no AI yet; those are Groups B and C of [Phase 1](specs/phase-1-plan.md) and the phases
after it. See [specs/project-outline.md](specs/project-outline.md) for the whole plan.

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

Development is two processes. Open two terminals.

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

Then open <http://127.0.0.1:5173>. The page reports whether it can reach the server.

A single-process mode — FastAPI serving the built `web/dist` from `http://127.0.0.1:8787`, which
is the real target shape — arrives in work item `P1-14`.

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
| — | `ARCHETYPE_CONFIG_FILE` | `<repo>/config.yaml` | Which YAML file the middle layer reads. Environment only. |

Example `config.yaml`:

```yaml
port: 8787
log_level: debug
data_dir: D:/manuscripts
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
