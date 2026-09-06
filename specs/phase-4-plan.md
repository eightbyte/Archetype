# Phase 4 — LLM Provider Layer & Chat

**Status:** **Built, awaiting § 8 (2026-09-06)** — **§ 2 is ruled**: D30–D34 were put to the writer
on 2026-09-04 and accepted **as recommended**, all five; they are promoted to the register and
binding. **All four groups are delivered** (2026-09-04, 2026-09-05, 2026-09-05, 2026-09-06): the
port, the fake, migration 004, both adapters, the prompted-JSON fallback, the registry, the
conversation store, the chat routes, the **WebSocket**, the context composer, the settings surface
— and now the **panel a writer can click**. *Ask agent* is the fourth action over a selection; the
composed context is on screen before anything is sent; an answer streams, can be cancelled, and
comes back after a reload; proofread, tone, and rewrite return a word-level before/after that
applies as one undoable editor transaction and **refuses a `stale` anchor**; and the settings
screen swaps providers without a restart and never shows a key. Both suites are green (**1,373**
backend, **616** frontend).

**What is left is § 8** — the fifteen-step run by hand, against a real provider with a real key.
It cannot be run from here, it is the only thing standing under the three surfaces no test reaches,
and **the phase is not complete until its *Outcome* column is filled in** (deviation `D12`).
**Version:** 1.5 · **Date:** 2026-09-06
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1 (D5, **D8**, D10,
**D11**, **D12**, D13, D19, D20)
**Writes:** `specs/providers.md` (P4-1) · extends [`specs/api-contract.md`](api-contract.md) and
[`specs/data-model.md`](data-model.md) (P4-15)
**Settles:** nothing from the backlog. `Q3`, `Q4`, and `Q6` are not due this phase.

---

## 1. What this phase is for

Phase 1 made Archetype a place you can write. Phase 2 made what you wrote **referenceable**.
Phase 3 made it **known**. Phase 4 is where a model is allowed to read any of it.

Everything so far has been the writer and their own words. This phase adds the one thing the
product is named for and has so far only promised: **an assistant that can be asked a question
about a passage and answer it.** Not an agent — the loop, the tools, and the run records are
Phase 6, and they are deliberately not here. What lands is the layer underneath all of that, and
the smallest honest surface over it:

- **The port.** One `LLMProvider` protocol with a normalized request, a normalized result, and a
  normalized stream. Two adapters behind it — Anthropic and OpenAI-compatible — and nothing above
  it knowing which is in play. This is the single most load-bearing interface added after the
  anchor, because Phases 6 and 7 are written entirely against it and never against a provider.
- **The fake.** `FakeProvider`, scripted, backing the whole suite. No test in this project has
  ever touched the network and none starts now (outline § 8).
- **Chat.** A streamed conversation in the right-hand panel, over the WebSocket D11 chose,
  persisted so the writer can come back to what they paid for.
- **Selection as context.** The action bar over a selection gains *Ask agent* beside Phase 2's
  *Mark passage* and Phase 3's *Add to bible*. What the model sees is exactly what the writer
  pointed at, and the composed context is shown before it is sent.
- **Three single-pass actions** — proofread, tone, rewrite — each returning a replacement for an
  anchored range as an explicit **before/after diff** that the writer accepts, edits, or throws
  away (D12).

The acceptance bar is the outline's, unchanged: **highlight a paragraph, ask a question, get a
streamed answer; swap providers in settings with no code change.**

### What this phase must not become

Named explicitly, because each is one small step from where this phase ends:

- **It is not the agent.** No plan→act→synthesize loop, no tool registry, no run records, no run
  inspector, no iteration budget. One request, one answer. Phase 6 owns all of it, and it owns it
  *after* Phase 5, because an agent without retrieval can only see what it was handed.
- **It is not retrieval.** The model sees the selection, the chapter it is in, and bible entries
  the writer named — nothing found by searching, because there is no index until Phase 5. The
  context composer built here is deliberately dumb and deliberately explicit.
- **It is not a proposal queue.** A rewrite is accepted or discarded in the panel that produced it.
  The durable `proposal` record, dedup, and merge are Phase 7's (D5), and building half of one here
  means Phase 7 inherits a shape nobody designed for it.
- **It writes nothing to the bible.** Not one entry, not one link. Phase 7.
- **It does not evaluate output quality.** Prompt tuning, benchmarking, and automated assessment of
  what the model said are out of scope for 1.0 by design (outline § 2). The suite tests the
  *plumbing*; § 8 assesses the *answers*, by hand, and records what it saw.

---

## 2. Confirm before code

The same reasoning as Phases 1, 2, and 3: a ruling made before files exist costs nothing, and the
same ruling made in Phase 6 is a migration plus two adapter rewrites. **Five of these become
binding register entries.** Each was put with a recommendation, the alternative that was weighed,
and where it bites if the answer is wrong.

Phase 3's § 2 was ruled the day it was written and every item landed against a settled decision.
The same happened here.

### Register entries — D30 to D34 (**ruled 2026-09-04 — binding**)

**Ruled by the writer on 2026-09-04: all five as recommended**, and promoted to
[`specs/development-phases.md`](development-phases.md) § 1. D34 narrows D8, whose own wording
permitted the UI to POST a key. The table below is unchanged from the version that was put to
the writer — it is the reasoning behind the ruling, and it stays as it was asked.

| ID | Proposed decision | Recommendation | Alternative considered | Where it bites if wrong |
|---|---|---|---|---|
| **D30** | Where a chat conversation lives, and whether Phase 4 writes into Phase 6's tables | **Its own two tables in the project file — `conversation` and `message` — and a Phase 4 turn is explicitly *not* a run.** Migration 004. A conversation is project-scoped like everything else (D6), soft-deleted like everything else (D22, D25), and a message stores the composed context that produced it alongside the text and the token usage. Phase 6's `run` table, when it arrives, **references a message** rather than replacing it: a run is what produced one assistant turn. | Persist nothing — hold the conversation in React state and let a reload discard it. Rejected on D13's own logic: token spend is a deliberate act the writer paid for, and throwing the answer away on a refresh makes the writer pay twice for the same question; it also loses the composed context, which is the only way a bad answer gets diagnosed. Also rejected: writing Phase 6's `run`/`run_step` shape now. That is a schema guessed two phases early, bent around a single completion that has no plan and no tool calls — and D20's forward-only migrations mean guessing wrong is a migration to undo, not an edit. | Migration 004, every chat route, and how much of Phase 6 is a migration rather than an addition |
| **D31** | Whether the port carries tool declarations before any tool exists | **Yes — `CompletionRequest.tools` and `CompletionResult.tool_calls` are in the port from P4-2, and Phase 4 declares no tools and calls none.** The types, both adapters' translation of them, and the prompted-JSON fallback (P4-7) are built and tested here against `FakeProvider` and against **recorded provider fixtures**; no product surface uses them. | Leave tools out until Phase 6 needs them. **Rejected, and this is the one place this phase deliberately builds ahead** — for the reason Phase 3 shipped the ordering module rather than deferring it (D28): normalizing tool calls is the hardest and most provider-divergent part of each adapter, and discovering its shape in Phase 6 means rewriting both adapters, the fake, and the fallback at the moment the agent loop is also new. The counter-argument is real and is why this is a decision rather than an assumption: a shape with no consumer is a shape nobody has proved sufficient. The mitigation is that the *fixtures* are its consumer — a real Anthropic and a real OpenAI tool-call payload, recorded once, translated in both directions, asserted equal. | Both adapters, the fallback, the fake, and whether Phase 6 opens with a rewrite |
| **D32** | The streaming envelope, and whether chat and Phase 6's runs share one | **One event vocabulary over one WebSocket, defined here and extended — never replaced — by Phase 6.** D11 chose WebSocket; this fixes what travels on it. Phase 4 emits `start`, `delta`, `usage`, `done`, and `error`; Phase 6 adds `plan`, `tool_call`, `tool_result`, and `step` to the same union. The client switches on a `type` discriminator and **ignores an event type it does not know**, so a server ahead of a stale bundle degrades to less detail rather than to a broken panel. | A plain HTTP streaming response for chat now, WebSocket later for runs. Rejected: it is the "second mechanism" D11 exists to avoid, and it forecloses the mid-run interaction — cancel, approve, clarify — that D11 named as the reason. Cancel is wanted in *this* phase, because a long answer to a question the writer has changed their mind about is exactly when they reach for it. | The socket contract, the client's event handling, and whether Phase 6 adds a second transport |
| **D33** | What accepting a proofread, tone, or rewrite result actually does | **It applies through the editor as an ordinary transaction, and the result record is ephemeral.** The action returns a replacement for an anchored range; the panel renders an explicit before/after (D12); accepting dispatches a normal ProseMirror transaction, which means it is undoable, autosaved, and snapshotted by the machinery that already exists. Nothing is written to a `proposal` table, because there is no `proposal` table until Phase 7. | Persist every suggestion as a durable proposal now, so Phase 7 inherits a populated queue. Rejected: D5's proposal queue is about *agent writes to the bible*, reviewed asynchronously and possibly in bulk. A rewrite of the paragraph under the cursor is a synchronous, single-target, accept-or-discard interaction, and giving it a queue would produce a list of stale suggestions against passages that have since been rewritten — the exact failure `Q3` is open about for findings. | The selection actions, the editor's undo story, and the shape Phase 7 inherits |
| **D34** | How the API key reaches the server, and what the settings UI may do with it | **The key stays environment-only, and the settings UI is read-only about it.** `P1-2` narrowed D8 to the environment and this keeps that narrowing: `ARCHETYPE_ANTHROPIC_API_KEY` and `ARCHETYPE_OPENAI_API_KEY` are `SecretStr` fields, the settings route returns `Settings.public_dump()`, and the UI shows **whether a key is present** and never its value, its length, or its prefix. Non-secret provider settings — provider, base URL, model id, capability flags — are writable and persist to `config.yaml`. | Let the UI POST a key, as D8's own wording permits. Rejected for 1.0 on the grounds P1-2 already took: accepting a key means writing it somewhere, and the app writing a secret to disk is a new class of mistake — wrong permissions, a backup that captures it, a `config.yaml` that stops being gitignored. The cost is real and is being accepted: a writer changing providers edits their environment and restarts. If that proves intolerable in use, D34 is the entry to reopen, and it reopens as a deliberate act. | `config.py`, the settings route, the settings screen, and whether a secret can ever reach a file the app wrote |

### Conventions and smaller rulings

Cheap to change now, awkward once files exist.

| | Ruling | Why, and what it costs to reverse |
|---|---|---|
| **1** | **`specs/providers.md` is written at P4-1, before the code it governs.** It fixes the port, the normalized request and result, the stream event vocabulary, the capability flags, the error taxonomy, and what a provider may **not** be asked to do. | The `P2-4` / `P3-1` discipline, applied where it earns its place for the third time. Two later phases read from this document and neither can read it out of an adapter: Phase 6 declares tools against it, Phase 7 composes prompts against it. It describes the *port*, never a provider's own wire format — a second copy of Anthropic's schema in prose is the third place to disagree that `specs/markdown.md` was refused for being. |
| **2** | **No provider SDK is imported outside `llm/adapters/`.** Not in a route, not in a store, not in a test that is not an adapter test. The port's types are pure and import nothing but the standard library and pydantic. | The outline's own invariant, made structural rather than aspirational. It is enforced by a test that walks the import graph, the same way the closed schema and the anchor package's one-way imports are. An SDK type that escapes into a route is how "nothing above the port knows which provider is in play" quietly stops being true. |
| **3** | **An adapter is tested against recorded fixtures, never against the network.** Each adapter ships a directory of real request/response payloads captured once by hand, committed, and replayed. Tests that require a live provider are `@pytest.mark.live` and excluded by default. | The suite rule (outline § 8, `CLAUDE.md`). A recorded fixture is what makes "this adapter translates a tool call correctly" a claim a test can hold, and it is the only honest way to satisfy D31's "the fixtures are its consumer". Capturing them is a documented manual step, like the `v00N` database fixtures. |
| **4** | **A provider failure is an error envelope, never a crash and never a silent empty answer.** New codes: `provider_unconfigured`, `provider_auth_failed`, `provider_rate_limited`, `provider_unavailable`, `provider_refused`, `context_too_large`. On the socket they arrive as an `error` event carrying the same code. | The envelope is uniform across the API and this is the first subsystem whose failures are routinely *someone else's*. A rate limit that reaches the writer as a blank reply teaches them the assistant is unreliable rather than that their key is out of quota. |
| **5** | **The composed context is recorded on every message and is visible before sending.** What the model was given — the selection, the surrounding chapter, the named bible entries, the token estimate — is shown in the panel and stored on the `message` row. | The outline's standing invariant: "the composed context is recorded on the run record". Phase 4 has no run record, so it lands on the message, and Phase 6's run references it. Without it, a wrong answer cannot be diagnosed without guessing, which is the whole reason the invariant exists. |
| **6** | **Token spend is one deliberate act per answer** (D13). No retry on a failed completion, no speculative prefetch, no background summarisation, no "regenerate" that fires without a click. | The one rule in this phase with a bill attached. It is also why the autosave backoff ladder is **not** reused here: retrying a save costs nothing and protects the writer's words; retrying a completion costs money and protects nothing. |
| **7** | **The context budget is a hard refusal, not a truncation.** A request whose composed context exceeds the configured budget is refused with `context_too_large` naming what was too big; nothing is silently dropped. | Truncation is how a continuity answer comes back confidently wrong because the half of the chapter that contradicted it was cut. The writer narrowing their selection is a correct and cheap fix; a quiet cut is neither. |
| **8** | **The chat panel is one more error boundary, and the editor is never inside it.** The right region already has its own (P1-12); the conversation, the composer, and the diff view each degrade independently. | The P1-12 rule one level in, exactly as the Bible tab took it in Phase 3. A panel talking to a network service is the most likely thing in the app to throw. |
| **9** | **Phase 4 adds no route that answers `501`, and no button for a Phase 6 feature.** The run inspector, the proposals queue, and the findings list are absent, not stubbed. | api-contract's standing rule (its *deliberately absent* section). A stub is a thing a client comes to depend on with the wrong meaning, and a disabled button is a promise with a date on it. |

---

## 3. The port in brief

The full specification is `specs/providers.md` (P4-1), written **before** the code it governs.
This section is the shape the work items are sized against.

### The protocol

```python
class LLMProvider(Protocol):
    name: str
    capabilities: Capabilities

    async def complete(self, req: CompletionRequest) -> CompletionResult: ...
    def stream(self, req: CompletionRequest) -> AsyncIterator[StreamEvent]: ...
```

Two methods, because a streamed answer and a whole one are genuinely different call sites and
faking one from the other lies in both directions — buffering a stream to fake `complete` hides
latency, and chunking a result to fake `stream` invents a token cadence that was never real.

### The normalized shapes

| Type | Carries | Note |
|---|---|---|
| `Message` | `role` (`system` \| `user` \| `assistant` \| `tool`), `content`, optional `tool_calls`, optional `tool_call_id` | One vocabulary. Adapters translate; nothing above the port sees a provider's role names. |
| `CompletionRequest` | `messages`, `model`, `max_tokens`, `temperature`, `stop`, `tools`, `tool_choice` | `tools` is present and empty in every Phase 4 call (D31). |
| `ToolDeclaration` | `name`, `description`, `parameters` (JSON Schema) | Declared here, used in Phase 6. |
| `CompletionResult` | `text`, `tool_calls`, `stop_reason`, `usage` | `stop_reason` is normalized to a closed set; a provider's own string is kept on `raw_stop_reason`. |
| `Usage` | `input_tokens`, `output_tokens` | What the message row records, and what the panel shows. |
| `StreamEvent` | a discriminated union: `start`, `delta`, `usage`, `done`, `error` | D32's vocabulary, extended by Phase 6 and never replaced. |
| `Capabilities` | `native_tools`, `streaming`, `max_context`, `supports_system` | What the fallback (P4-7) and the budget check (ruling 7) read. |

### What a provider may not be asked to do

Stated in `providers.md` in as many words, because each is a thing someone will reasonably assume:

- **It is not asked to remember anything.** Every request is complete. Conversation state lives in
  the project file (D30) and is composed into `messages` on the way out.
- **It is not asked to fetch anything.** No URL, no file path, no tool that reaches the network
  (`Q4`, and Phase 6 owns tools regardless).
- **It is not asked to be deterministic**, and no test asserts on the text of a real model's answer.
- **It is not the place retries live.** One request, one answer, one bill (ruling 6).

---

## 4. Work Items

Fifteen items in four groups. The **Done when** line is the acceptance bar — an item without its
tests is not done (outline § 8).

### Group A — The port, the fake, and where a conversation lives (P4-1 → P4-4)

**Delivered 2026-09-04.** `specs/providers.md` exists; `archetype/llm/port.py` and
`archetype/llm/adapters/` are in place; `tests/fakes/provider.py` is the fake the
suite runs against; migration 004 is proved against `v003_phase3.sqlite`. Six
deviations, in § 7. Both suites green — **1,180 backend, 535 frontend**.

---

**P4-1 · `specs/providers.md`**

The specification, written **before** Group A's code, in the shape `anchors.md` and `bible.md`
established. It settles, at minimum: the protocol and its two methods and why they are two; every
normalized shape in § 3 with its field meanings; the closed `stop_reason` set and the rule that a
provider's own string is preserved beside it; the stream event vocabulary (D32) and the
forward-compatibility rule; the capability flags and exactly what each one changes; the error
taxonomy behind ruling 4 and which provider conditions map to which code; the context budget rule
(ruling 7); and **what a provider may not be asked to do**.

It must **not** restate either provider's wire format. It describes the port; the adapters hold the
translation, and a recorded fixture holds the truth about what a provider actually sends.

*Done when:* the document exists; P4-2's types are written *from* it; every constant and every
vocabulary member it names appears in the code under that name.

---

**P4-2 · The port and its types (`llm/port.py`)**

`Protocol`, the normalized shapes, the closed unions. **Pure** — pydantic and the standard library,
nothing else, no I/O, no SDK, importable by a test with nothing running. This is the module Phases
6 and 7 are written against.

The import rule from ruling 2 is enforced here rather than asserted: a test walks the import graph
of `archetype/` and fails if any module outside `llm/adapters/` imports `anthropic` or `openai`.

*Done when:* the types round-trip through pydantic; the discriminated `StreamEvent` union
deserializes each member and **rejects an unknown `type` on the server while the client ignores
one** (D32's asymmetry is deliberate and is tested in both suites); the import-graph test passes;
and `mypy`/`ruff` are clean over the package.

---

**P4-3 · `FakeProvider`, and the scripted corpus behind it**

`server/tests/fakes/provider.py` — the thing the entire backend suite runs against, and the first
resident of a directory reserved since Phase 1.

It is scripted and it computes nothing: a test stages the answer, the deltas, the usage, the stop
reason, or the error, and the fake returns them. It may simulate **cadence and failure** —
mid-stream error, a stream that ends without `done`, a slow first token — because those are the
conditions the client's handling exists for and no real provider produces them on demand.

The standing rule from the fake API client applies unchanged and is written into its docstring:
**it holds no rule of its own.** It does not count tokens (that is the budget module's job, tested
separately), does not decide whether context is too large, and does not translate anything.

*Done when:* it satisfies `LLMProvider` structurally; a test asserts the protocol is satisfied
rather than assuming it; and every stream failure mode the panel handles has a staging method.

---

**P4-4 · Migration 004, and the fixture database that guards it**

`004_chat.sql` — two tables, and the third real migration (D30).

```sql
CREATE TABLE conversation (
    id          TEXT PRIMARY KEY,                    -- cnv_...
    project_id  TEXT NOT NULL REFERENCES project(id),
    title       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT                                 -- soft delete (D22, D25)
);

CREATE TABLE message (
    id              TEXT PRIMARY KEY,                -- msg_...
    conversation_id TEXT NOT NULL REFERENCES conversation(id),
    ord             INTEGER NOT NULL,                -- position in the conversation
    role            TEXT NOT NULL,                   -- user|assistant|system
    content         TEXT NOT NULL,
    context_json    TEXT NOT NULL DEFAULT '{}',      -- what was composed and sent (ruling 5)
    provider        TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    usage_json      TEXT NOT NULL DEFAULT '{}',
    error_code      TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
```

New ID prefixes `cnv_` and `msg_`, registered in `archetype/ids.py` and `IdPrefix.ALL` in the same
change as the migration. A message is reached through its conversation and is addressable, so it
gets an id; nothing about a message is independently mutable, so it carries no `revision` and no
D19 guard — an assistant turn is never edited.

The fixture discipline from `P3-2` applies: capture `v003_phase3.sqlite` from a real Phase 3
project **before** writing the migration, normalise the runner's `applied_at` so re-running the
capture produces identical bytes, and record the hash in the fixture README.

*Done when:* migration 004 runs against `v003_phase3.sqlite` with every document, anchor, snapshot,
entry, link, and citation intact afterward; a version-1 file migrates all the way in one open; and
the capture script is deterministic and documented.

---

### Group B — The adapters (P4-5 → P4-8)

**Delivered 2026-09-05.** Both adapters exist and are proved interchangeable; the prompted-JSON
fallback is built and its corpus passes; `Settings` carries the provider block and the registry is
the only place a provider is constructed. `httpx` is now a runtime dependency and is fenced into
`llm/` by a second import-graph test. No product surface calls a model yet — Groups C and D are
not started. Ten deviations, in § 7. Backend **1,293**, frontend 535 — both green.

---

**P4-5 · The Anthropic adapter**

`llm/adapters/anthropic.py`. Messages API. Translates the normalized request out and the response
and stream back, including the system prompt's separate position, `stop_reason` normalization, and
usage. Declares `native_tools=True`.

Recorded fixtures (ruling 3): a plain completion, a streamed completion, a completion carrying a
tool call, an auth failure, a rate limit, and an over-context refusal.

*Done when:* every fixture translates in both directions and is asserted field by field; each
provider error maps to the ruling-4 code a test names; and no test in this item opens a socket.

---

**P4-6 · The OpenAI-compatible adapter**

`llm/adapters/openai_compat.py`. The same job against the chat-completions shape, configured by
**base URL + key + model id + capability flags**, which is what makes most local and hosted servers
that mimic OpenAI work without a new adapter. Its own recorded fixtures, including one captured
from a non-OpenAI server speaking the same protocol, because the point of this adapter is the ones
that are *nearly* compatible.

*Done when:* the fixture set passes; a server declaring `native_tools=False` routes through P4-7
rather than failing; and the two adapters are proved interchangeable by one parametrised test that
runs the same normalized request through both and compares the normalized results.

---

**P4-7 · The prompted-JSON tool fallback**

For providers without native tool calling. The declarations are rendered into the system prompt,
the model's JSON is parsed out of the reply, and it is presented at the port as ordinary
`tool_calls` — so nothing above the port can tell the difference, which is the entire requirement.

It is built here and used in Phase 6 (D31). Its own corpus: well-formed JSON, JSON in a fenced
block, JSON with prose either side, malformed JSON, and a reply that calls no tool at all. A
parse failure is `provider_refused` with the raw text preserved, never a silently empty tool call.

*Done when:* the corpus passes; a fallback provider and a native one produce **identical**
normalized `tool_calls` for the same declaration, asserted by one test over both paths.

---

**P4-8 · Provider configuration and the registry**

`Settings` gains provider fields — `llm_provider`, `llm_base_url`, `llm_model`, `llm_max_tokens`,
`llm_context_budget`, and the two `SecretStr` keys (D34). The registry builds the configured
adapter and is the only place a provider is constructed.

The Phase 1 secret guard does its job here for the first time on a real secret: a `SecretStr`
field that is not `Field(exclude=True)` fails at class definition, the YAML layer refuses to supply
one, and `public_dump()` strips them again. A test asserts a key **cannot** appear in any route's
response, by walking the full API surface with a key configured.

*Done when:* switching provider is a settings change with no code change, proved by a test that
builds both adapters from config alone; an unconfigured provider raises `provider_unconfigured`
before any request is composed; and the secret tests pass against a key that is actually set.

---

### Group C — The API (P4-9 → P4-11)

---

**P4-9 · `ConversationStore` and the REST routes**

The store: create, list, get with messages, rename, soft delete, restore. Append a message. The
soft-delete predicate is the one that already exists, applied to a fifth table, and the standing
test shape applies — one test asserting a deleted conversation is absent from **every** read path
together.

Routes under the existing `/api` prefix, in a third router module (`api/chat_routes.py`) on the
`C1` precedent:

| Method | Path | Answers |
|---|---|---|
| `GET` | `/api/projects/{pid}/conversations` | The live conversations, newest first |
| `POST` | `/api/projects/{pid}/conversations` | Create one |
| `GET` | `/api/conversations/{cid}` | One conversation with its messages, in `ord` |
| `PATCH` | `/api/conversations/{cid}` | Rename |
| `DELETE` | `/api/conversations/{cid}` | Soft delete |
| `POST` | `/api/conversations/{cid}/restore` | Restore |

The locator gains `conversation` and `message` in its closed `_ADDRESSABLE` set — one more prefix
over one mechanism.

*Done when:* every route is covered over the real application; the deleted-conversation test
asserts absence from all read paths at once; and the contract fixtures are written and
type-checked by the frontend.

---

**P4-10 · The WebSocket, and the one thing that streams**

`WS /api/conversations/{cid}/stream` — the first non-HTTP surface in the API (api-contract § 12,
has reserved it since Phase 1).

The client sends one *ask* frame carrying the prompt and the context selector; the server composes
the context, refuses it if it is over budget (ruling 7), persists the user message, opens the
provider stream, and emits D32's events. The assistant message is persisted **when the stream
closes**, with its usage and its composed context — and also on an error, carrying `error_code`, so
a failed answer is visible in the history rather than being a gap the writer has to remember.

Cancel is a client frame, and cancelling closes the provider stream and persists what arrived
marked as cancelled. That is D11's stated reason for choosing a socket, exercised in the phase that
introduces it.

The context composer lives in `llm/context.py`, not in the route — composition that is not HTTP
does not live in a route (`C2`'s rule), because Phase 6 needs the same composer without a request.

*Done when:* a full streamed exchange is tested end to end over the real app against
`FakeProvider`; a mid-stream failure persists a message carrying the code; a cancel persists the
partial answer; an over-budget request is refused before the provider is called at all, asserted by
the fake recording zero calls.

---

**P4-11 · The settings route**

`GET /api/settings` returning `Settings.public_dump()` — the provider, the base URL, the model, the
budgets, the capability flags, and **`has_key: bool` per provider and nothing more** (D34).
`PATCH /api/settings` writes the non-secret fields to `config.yaml` and refuses a secret-valued
field with a message saying where keys come from.

This is the first route in the project that returns a setting, which api-contract had so far
listed as absent. Its § 12 row is amended in the same change to say what is now true and what stays
never true.

*Done when:* a configured key is provably absent from the response, asserted by a test that greps
the serialized body for the key's value; `PATCH` refuses every `SecretStr` field by name; and an
invalid provider name is a `422` rather than a broken app on the next request.

---

### Group D — The application and close-out (P4-12 → P4-15)

**Delivered 2026-09-06**, less § 8. Twelve as-built deviations in § 7.

---

**P4-12 · `ChatContext` and the agent panel**

The fifth context, beside the project, document, bible, and UI reducers (D10) — and the panel that
replaces the Phase 1 placeholder. It holds the conversation list, the open conversation and its
messages, and the in-flight stream's accumulating text.

The socket lives in the provider as an effect, never in the reducer: reducers are pure and hold no
`localStorage`, no client, and no DOM, and a WebSocket is all three problems at once. Reconnection
is **not** automatic — a dropped socket mid-answer surfaces as an error the writer can retry from,
because an automatic reconnect that re-sends is ruling 6 violated by accident.

The panel: a conversation list, the transcript with roles distinguished, a composer, a visible
token count and cost-shaped feedback per answer, and a **cancel** control while a stream is open.

*Done when:* a streamed answer renders progressively against the fake client; cancel stops it and
leaves the partial text on screen and in the history; a mid-stream error leaves the transcript
intact and says what went wrong; the panel has its own error boundary; and a reload restores the
conversation from the server (D30's whole point).

---

**P4-13 · Selection as context — *Ask agent***

`SelectionActions.tsx` gains a fourth action, beside *Mark passage*, *Re-link here*, and *Add to
bible*. It sends the selected range and opens the composer with the context already assembled.

**What is being sent is shown before it is sent** (ruling 5): the passage, how much of the
surrounding chapter came with it, which bible entries were included and why, and the token
estimate. The writer can drop any part of it.

The two-halves-that-meet-at-a-typed-boundary problem applies here exactly as it did in Phases 2 and
3 ([phase-2-plan](phase-2-plan.md) § 7, `C7`): jsdom cannot make a text selection, so the gesture
is covered on one side and the composition on the other, and § 8 is what joins them. This is the
**fourth** feature under that limitation — after *Mark passage*, *Re-link here*, and *Add to
bible* — and § 7 should say so plainly when it lands.

*Done when:* the context preview matches what the server composes, held by a shared contract
fixture rather than by two implementations agreeing; dropping a part of the context changes what is
sent; and the panel opens focused on the composer.

---

**P4-14 · Proofread, tone, and rewrite — the before/after diff (D12)**

Three single-pass actions over an anchored range, each returning a replacement. The panel renders
an **explicit before/after** and accepting applies it as an ordinary editor transaction (D33) —
undoable, autosaved, and covered by the snapshot machinery that already exists.

Each action mints an anchor for its range through `AnchorStore` and by no other means ([phase-3-plan](phase-3-plan.md)
§ 2, ruling 8, unchanged), so a suggestion whose passage has since been rewritten reports itself
`stale` rather than applying to the wrong text. **An action never applies to a `stale` anchor** —
it refuses and says why, which is the whole reason Phase 2 was built before this.

A word-level diff is **desirable, not required**. If the before/after lands and the intra-paragraph
diff does not, that is the correct thing to cut — it is already a backlog entry from `P3-13`'s
identical call, and shipping the same field-level answer here is a legitimate outcome.

*Done when:* each action round-trips against the fake; accepting produces exactly one editor
transaction and one autosave; rejecting writes nothing anywhere; and applying against a `stale`
anchor is refused with a message naming the passage.

---

**P4-15 · The settings screen, and the documentation pass**

The screen: provider, base URL, model, budgets, and a **key presence indicator that is never a key**
(D34). Changing a provider takes effect on the next request with no reload and no restart.

The documentation pass, on the `P2-15` / `P3-15` pattern — every document brought level with what
was built, in this order: `specs/project-outline.md` (§ 4.5, § 4.7, § 6), the decision register
(D30–D34 promoted, phase map), `specs/data-model.md` (the two new tables at schema version 4),
`specs/api-contract.md` (the chat routes, the socket, the settings route, § 12 amended),
`specs/providers.md` (§ 12, the corrections the code made to it), this plan's § 7, the README's
configuration keys, and `CLAUDE.md`.

*Done when:* every document matches the code; `CLAUDE.md` describes the project as it now is; and
§ 8's script has been run and its results recorded here.

---

## 5. Exit Criteria

Phase 4 is done when **all** of these hold.

1. **A question about a selection is answered, streamed, in the panel** — the outline's own bar.
2. **Swapping providers is a settings change with no code change**, proved by a test that builds
   both adapters from configuration alone and by § 8 doing it by hand.
3. **No provider SDK is imported outside `llm/adapters/`**, enforced by the import-graph test.
4. **No test touches the network.** The whole suite runs against `FakeProvider` and recorded
   fixtures; `@pytest.mark.live` is excluded by default and the suite is green without a key set.
5. **A conversation survives a reload**, with its messages, its usage, and the composed context
   that produced each answer (D30, ruling 5).
6. **Every provider failure reaches the writer as a stated cause**, not a blank reply: auth, rate
   limit, unavailable, refused, and over-budget each surface with their own code and message.
7. **Cancel works and is honest** — the stream stops, the partial answer is kept and marked, and no
   further tokens are spent (D11, ruling 6).
8. **A proofread, tone, or rewrite result applies through the editor as one ordinary, undoable
   transaction, or not at all** (D12, D33) — and never applies to a `stale` anchor.
9. **No key reaches the browser**, asserted by walking the whole API surface with a key configured
   and searching every response body for its value (D8, D34).
10. **Migration 004 runs against a captured version-3 fixture database** with everything Phase 3
    built intact afterward, and a version-1 file migrates all the way in one open (D20).
11. `pytest` and `vitest` are both **green**, and P4-7 and P4-10 have tests covering their edges —
    malformed tool JSON, a stream that ends without `done`, a cancel mid-token — not just their
    happy paths.
12. `specs/providers.md` exists and describes what was built; the documents in P4-15 match the code.

**Manual acceptance script** (run by hand at the phase boundary; written out step by step in § 8,
where its results go):

configure a provider from the environment → open a chapter, **select a paragraph and ask a
question** → watch it stream → **cancel** one mid-answer → reload and confirm the conversation and
its usage survived → **proofread** a paragraph and accept the result → **rewrite** one and reject it
→ rewrite a passage, then edit it underneath the suggestion and confirm the apply is refused →
**swap to the second provider** in settings and ask the same question → unset the key and confirm
the failure says so → confirm no key is anywhere in the browser.

---

## 6. Risks in this phase

| Risk | Why it bites | Mitigation |
|---|---|---|
| **The port is shaped by whichever adapter is written first.** Anthropic's system prompt is a separate parameter; OpenAI's is a message. Whichever is built first leaks its assumption into the "normalized" type. | It is the classic way an abstraction over two things becomes an abstraction over one. Phase 6 then finds the port cannot express what the second provider needs, and the fix is a rewrite of everything above it. | `providers.md` is written **first** (P4-1), from both providers' documentation rather than from either's code. P4-6's parametrised test runs one normalized request through **both** adapters and compares normalized results — a test that fails the moment the port has a favourite. |
| **D31's tool plumbing ships unproven.** Types, two translations, and a fallback, with no consumer until Phase 6. | This is the risk the phase is knowingly taking, and it is the mirror of D28's. If the shape is wrong, Phase 6 opens with a rewrite — exactly the outcome D31 was trying to prevent. | Recorded provider fixtures carrying **real** tool-call payloads are the consumer (ruling 3), and P4-7's test asserts a native and a fallback path produce identical normalized calls. If the writer rules D31 the other way, the plumbing is cut and the risk becomes Phase 6's — a legitimate trade, recorded either way. |
| **Streaming state in React is a class of bug the app has not had.** Out-of-order events, a component unmounting mid-stream, two sockets open after a fast switch, a cancel that races the last delta. | Every one of them shows up as a transcript that is subtly wrong or a panel that is stuck, and none of them shows up in a unit test of a reducer. | The socket is an effect in the provider with one owner and an explicit teardown; the reducer stays pure and is tested directly against event sequences, including out-of-order and duplicate ones. P4-3's fake can produce every pathological cadence on demand, which is the reason it may simulate cadence at all. |
| **Money.** This is the first phase where a bug has a bill. A retry loop, a component remounting in a `useEffect`, or an auto-reconnect that re-sends can spend real tokens in a loop nobody watched. | The autosave retry ladder is right there and looks like the obvious thing to reuse, and it is exactly wrong here. | Ruling 6 states it as a rule; no retry, no prefetch, no auto-reconnect, no regenerate without a click. A test asserts the fake records exactly one provider call per deliberate ask, including across a remount. |
| **The context composer quietly becomes retrieval.** "Include the relevant bible entries" is one small step from "search for relevant bible entries", and there is no index until Phase 5. | It would ship a retrieval feature with no embeddings, no chunking, and no way to measure whether it retrieved the right thing — and Phase 5 would then be replacing something the writer already relies on. | § 1's non-goals name it. The composer takes what the writer **pointed at** and what they **named**, and the preview (ruling 5) makes that visible on every request, so a composer that started guessing would be immediately obvious on screen. |
| **The settings screen becomes a key manager.** D34 says environment-only; the first time a writer swaps providers they will want to paste a key. | The pressure is real and arrives on the first day of use. Giving in means the app writes a secret to a file it chose, which is the class of mistake D8 exists to prevent. | D34 is put to the writer **now**, with the cost stated plainly, so it is a decision rather than a discovery. If it is reopened later it is reopened deliberately, with the reasoning on the record. |
| **The answer is bad and there is no way to tell why.** A model given the wrong context answers confidently and the writer has no way to see what it was given. | It is the failure that makes an assistant untrustworthy rather than merely wrong, and it is unfalsifiable without the record. | Ruling 5: the composed context is shown before sending and stored on the message. § 8 spends steps on reading it back. |
| **Output quality is not testable and the phase still has to be judged.** The suite can prove the plumbing and prove nothing about the answers. | Groups A to C could all be green and the product still be useless in the writer's hands. | Explicitly out of scope for automated testing (outline § 2, § 8). § 8's run is where the answers are assessed, by hand, and it must record **what the model actually said** for at least three questions — the Phase 2 and Phase 3 precedent that the acceptance run is the only thing standing under what no test reaches. |

---

## 7. As-Built Deviations

*Every divergence from this plan is recorded here in the same change that makes it, with what
happened and why (outline § 13).*

**Group A, delivered 2026-09-04.** Six deviations. `A1` is the only one that changes a stored
shape; `A3` is the only one that adds a surface the group did not budget; none touches a `D<n>`.

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **A1** | `P4-4` | The `message` DDL in § 4: `id`, `conversation_id`, `ord`, `role`, `content`, `context_json`, `provider`, `model`, `usage_json`, `error_code`, `created_at`. | **One more column: `stop_reason`**, holding the port's normalised vocabulary, `''` until a turn finishes. Without it a **cancelled** turn is indistinguishable from a complete one after a reload, which § 8's step 7 requires it not to be, and cancel is this phase's own feature (D11). The alternative was `error_code = 'cancelled'`, and it is wrong twice over: a deliberate act would be filed as a failure in the one column a writer consults when something went wrong, and ruling 4's code set is closed at six and does not contain it. Extension-only; no other column changed. |
| **A2** | `P4-1` / `P4-2` | "`stop_reason` is normalized to a closed set" — the set left open. | **Seven members, each with exactly one writer** (`providers.md` § 3): `end_turn`, `max_tokens`, `stop_sequence`, `tool_use`, `refusal`, `other`, `cancelled`. Two of them are the ones worth arguing about. **`other`** exists so that a provider string this build does not recognise normalises honestly instead of being mapped onto `end_turn` — with `raw_stop_reason` carrying the original, which is what makes it diagnosable rather than merely honest. **`cancelled`** is never produced by an adapter: it is written by whoever closed the stream, and it is the one stop reason a provider cannot cause. |
| **A3** | `P4-2` | Group A is the port, the fake, and the migration — no client code until Group D. | **One client module lands now: `web/src/api/stream.ts`, with nine tests and no panel.** `P4-2`'s own *done when* requires D32's asymmetry to be "tested in both suites", and the client half is the half that protects a writer — a stale bundle degrading to less detail rather than to a broken panel. Deferring it to `P4-12` would have left the ruling untested on the side it exists for, in the phase that ruled it. The reader is the whole of it: the vocabularies, `parseStreamEvent`, and two guards. Same shape as Phase 2's `D12`, and smaller. |
| **A4** | `P4-4` | Migration 003's test against `v002_phase2.sqlite` keeps running unchanged. | **One assertion changed**: it asserted `migrate(conn) == 3`, and a version-2 file now migrates two steps to 4, so it asserts `latest_version()`. The test's subject — a real Phase 2 file carried forward with document, anchor, and snapshot rows identical — is unchanged and still compared row for row. This is the identical correction `P3-2` made to the version-1 test (phase-3 plan § 7, `A4`), and it is recorded for the same reason: a changed assertion is a deliberate act (`CLAUDE.md`, Testing). |
| **A5** | `P4-3` | "It holds no rule of its own." | **One exception, stated in its docstring:** a `FakeProvider` declaring `streaming=False` refuses `stream()` with `provider_unavailable`, because that is what `providers.md` § 5 says a provider does. Implementing the contract it claims to satisfy is not the same as computing an answer — it still counts no tokens, judges no context, translates nothing, and invents nothing when a test staged nothing (an unstaged call raises `NothingStagedError`, which is an `AssertionError` because it is a defect in the test). |
| **A6** | `P4-4` | The fixture-capture discipline from `P3-2`, applied again. | **It caught a second determinism trap, and the README now names it.** Pinning every *column* that holds a timestamp is not enough when a column holds a **document**: `entry_revision.snapshot_json` embeds the entry's whole state, and the revision a soft delete writes carries a `deleted_at` straight off the wall clock. The first capture differed between runs in exactly one byte range because of it. `capture_v003_phase3.py` now normalises inside the JSON as well, and the fixture is byte-for-byte reproducible — hash in `tests/fixtures/db/README.md`. |

**Group B, delivered 2026-09-05.** Ten deviations. `B1` is the one to read — it is the honest
limit on what this group's tests actually prove. `B5` is the only one that adds stored
configuration, `B7` the only one that adds an unbudgeted module, and three of them (`B3`, `B4`,
`B8`) are corrections to `specs/providers.md` and are cross-referenced from its § 13.

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **B1** | `P4-5` / `P4-6` | Ruling 3: "a directory of real request/response payloads captured once by hand, committed, and replayed." | **The payloads are transcribed from each provider's published wire format, not captured from a live account** — Group B was built with no key in the environment, and a capture makes billed requests. The capture scripts are written and committed (`tests/fixtures/providers/capture_*.py`) and the fixture README says which files are which, in as many words. The limit is stated there and is worth stating here too: **a transcribed payload proves the adapter matches what the documentation says, not what the provider actually sends.** Closing that gap is § 8's job — steps 4 and 12 put a real answer from each provider on screen — and refreshing the corpus from that run is one command per provider. A capture that then makes a test fail has found something real, which is why the scripts rewrite only the provider's half and never the expectations. |
| **B2** | `P4-5` / `P4-6` | "A directory of real request/response payloads." | **One `cases.json` per provider inside that directory**, in the shape every other corpus in this project uses (`anchors/`, `markdown/`, `schema/`, `bible/storytime/`). A reader who has seen one corpus can read this one; the capture script rewrites one file per provider rather than six; and each case states **both** halves — the body the adapter must send and the port shape it must produce — so a translation that drifted on one side only fails rather than round-tripping quietly against itself. |
| **B3** | `P4-6` | `stop_reason` normalises to the closed set of seven. | **`stop_sequence` is unreachable through the OpenAI-compatible adapter, and that is the protocol's limit rather than this adapter's.** A chat-completions server reports `finish_reason: "stop"` whether the model finished on its own or produced a stop sequence, so `stop` maps to `end_turn` and `raw_stop_reason` records what was actually said. The member is not wrong and Anthropic writes it; this provider simply cannot tell us. It is also why the interchangeability test compares the normalised results **excluding `raw_stop_reason`**, which is *supposed* to differ (`providers.md` § 3). |
| **B4** | `P4-5` / `P4-6` | D32's five events, and `providers.md` § 8's "a tool call arrives normalised or not at all". | **A tool call that arrives mid-stream has no Phase 4 event to arrive in.** `start`, `delta`, `usage`, `done`, `error` has no member it fits, so a streamed `input_json_delta` is ignored and the stream's `done` still carries `stop_reason="tool_use"` — which is true, and is the most a Phase 4 stream can say. `complete()` returns tool calls in full and is the path the fixtures assert. Phase 4 declares no tools, so nothing is lost today; a test pins the behaviour so that Phase 6 adding `tool_call` to the same union is a change to a test rather than a discovery. `providers.md` § 13, correction 3. |
| **B5** | `P4-8` | `Settings` gains `llm_provider`, `llm_base_url`, `llm_model`, `llm_max_tokens`, `llm_context_budget`, and the two keys. | **Five more fields: the four capability flags and `llm_stream_usage`.** `P4-6`'s own *done when* requires that "a server declaring `native_tools=False` routes through P4-7", which needs a way to declare it — and the item's own text says this adapter is configured by "base URL + key + model id + **capability flags**". So `llm_native_tools`, `llm_streaming`, `llm_supports_system`, and `llm_max_context` are settings, with `0` on the last meaning *leave the adapter's own answer alone*. `llm_stream_usage` is the fifth and is the one that is not a capability: `stream_options.include_usage` is how this protocol reports usage on a streamed answer, and a server that has never heard of the field rejects the whole request — so a writer pointed at such a server turns it off and loses the token counts rather than the answer. |
| **B6** | `P4-8` | Phase 1's `test_phase_1_declares_no_secrets` keeps running unchanged. | **One assertion changed, and it is still exact.** It asserted `Settings.secret_fields() == frozenset()`; it now asserts `{"anthropic_api_key", "openai_api_key"}`. Phase 1's point was that the guard existed *before* there was a secret to guard, and Phase 4 is where that stops being theoretical. It was not loosened to "contains" — a third secret is a deliberate act and fails here until it is written down. Recorded because a changed assertion is a deliberate act (`CLAUDE.md`, Testing), the same as `A4`. |
| **B7** | `P4-8` | "`Settings` gains provider fields. The registry builds the configured adapter." | **Two modules, not one: `llm/registry.py` and `llm/budget.py`.** The budget was already named as `P4-8`'s by `providers.md` § 5 and by `FakeProvider`'s docstring ("that is the budget module's job (P4-8), tested separately") but not by this item's own text, so it is recorded here. It is pure and sits in `llm/` rather than `llm/adapters/`: it takes a request, a capability, and a number. The registry also grew `provider_status()` — provider, model, base URL, and **whether a key is present, never the key** — because that is the registry's knowledge of what it can build, and a second copy of "is this configured" in Group C's settings route is the copy that would drift. |
| **B8** | `P4-7` | "A fallback provider and a native one produce **identical** normalized `tool_calls`." | **Identical on the name and the parsed arguments; the ids are excluded, by `providers.md` § 8's own rule 3.** That rule says the fallback mints ids and a native provider's are kept, so two paths producing the *same* id would mean one of them was ignoring its provider. The test compares the calls without ids and asserts both ids exist, which is the strongest claim the two rules permit together. The fallback's ids are positional (`call_0`, `call_1`) rather than random, so a recorded reply parses the same way twice. `providers.md` § 13, correction 2. |
| **B9** | `P4-5` / `P4-6` | Ruling 2: no provider SDK outside `llm/adapters/`. | **This build imports no provider SDK at all, and the rule is extended to the thing it uses instead.** `specs/project-outline.md` § 3 fixes LLM access as *HTTP via `httpx`, one adapter per provider*, so `httpx` occupies the position a vendor SDK would have and inherits its rule: a second import-graph test fails if any module outside `llm/` imports it, and a third asserts `archetype.llm` still re-exports the port and nothing that would drag a transport onto the import path of everything that touches it. `httpx` moves from a dev dependency to a runtime one — it was already installed in development, because the Starlette test client is built on it. The two vendor SDKs were the alternative and were declined on the dependency budget (`P1-1`) and on ruling 6: each ships a retry policy that would have to be disabled. |
| **B10** | ruling 4 | Six codes, and `context_too_large` for "the provider's own context error". | **Telling `provider_refused` from `context_too_large` is a heuristic over somebody else's prose, and it is written down as one.** Neither provider sets a status or a code that means only this: an over-long prompt arrives as an ordinary `400` with a sentence in it (OpenAI-compatible servers usually add `code: "context_length_exceeded"`; Anthropic does not). `transport.py` holds the substring list in one place with the reasoning beside it. The failure is mild in both directions: a miss lands as `provider_refused`, which is still a stated cause carrying the provider's own message rather than a blank reply. **Our own budget check is the path that matters** — it runs before the request is sent and never guesses (ruling 7). |

**Group C, delivered 2026-09-05.** Ten deviations. `C2` and `C6` are the two worth reading —
one adds a surface the group did not budget and the other is a rule this phase had not written
down. `C4` is the only one that narrows a stated capability, `C8` the only one that changes a
Phase 1 signature, and none touches a `D<n>`.

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **C1** | `P4-9` | Six routes: list, create, get, rename, delete, restore. | **Seven: `GET /api/projects/{pid}/conversations/deleted` as well.** A soft delete whose only recovery path is a toast the writer has to catch before it fades is a delete with a grace period, not a recoverable one — and D22 and D25 each shipped a deleted list for exactly that reason (chapters, entries). The store method the item already asks for (`restore`) is unreachable after a reload without it. |
| **C2** | `P4-10` | The composer lives in `llm/context.py`, called by the socket. | **`POST /api/conversations/{cid}/context` as well — the composer over HTTP, spending nothing.** Ruling 5 says what is being sent is shown *before* it is sent, and `P4-13`'s own *done when* requires the preview to match what the server composes "held by a shared contract fixture rather than by two implementations agreeing". Without a route there is no fixture and no server answer, so the panel would have to compose in the browser — which is the second implementation that ruling exists to prevent. The route is the same `compose()` the socket calls, and an over-budget context is **reported** rather than refused: the refusal belongs to the ask, and the preview's whole job is to show the number first. |
| **C3** | `P4-9` | "a third router module (`api/chat_routes.py`)". | **A fourth as well: `api/settings_routes.py`.** `P4-11`'s routes are not chat, and putting them in the manuscript half would make "the manuscript half of the `/api` router" untrue. Its four wire shapes live in that file rather than in a fourth `*_schemas.py`: two routes and four models is not a module's worth, and splitting sixty lines across two files makes a reader open both to learn one thing. `chat_schemas.py` *is* a separate module, because the chat shapes are as many again as Phases 1 and 2 put together. |
| **C4** | `P4-11` | "`PATCH /api/settings` writes the non-secret fields to `config.yaml`." | **It writes the provider block and refuses everything else.** `data_dir`, `host`, `port`, `log_level`, and `web_dist` are resolved once, at startup: the projects directory is scanned from one and the static mount installed from another, so a route that changed one would leave a running server whose settings describe something it is not doing. They stay **readable** — the screen shows them — and they change the way they always have, through the environment or the file and a restart. `WRITABLE_SETTINGS` is served on the response so the screen renders inputs from the server's list rather than its own. |
| **C5** | `P4-9` | The store, unplaced — the item names `api/chat_routes.py` and `llm/context.py` and not where `ConversationStore` lives. | **A new package, `archetype/chat/`.** Not `llm/`: that is the provider layer, and a conversation can be created, read, renamed, deleted, and restored with no key set and no provider configured at all — which is what lets the panel show a transcript when the assistant is unavailable. The stored turn is `ChatMessage` rather than `Message`, because the port already has a `Message` and two types with one name in one process is how a shape ends up on the wrong side of a wire. |
| **C6** | `P4-10` | Ruling 4: a provider failure is an `error` event carrying one of six codes. | **Everything that is *not* a provider failure closes the socket with a reason instead of borrowing one.** The plan says what a provider failure does and does not say what a malformed frame, an unknown conversation, or a selection in a since-deleted chapter does — and every one of those is reachable. Filing one as `provider_refused` would put a lie in the one column a writer consults when something went wrong, and the taxonomy is closed at six. So they close with `1008` and a short reason (a close frame carries 123 bytes, which a sentence a writer can act on fits inside). The rule is now in `chat_routes.py`'s docstring and in api-contract § 12. |
| **C7** | `P4-10` | D32's five events over the socket. | **Exactly five, and the client re-reads the conversation for the ids.** There is no sixth event announcing a saved message, because D32's vocabulary is shared with Phase 6 and adding to it here would make the two halves disagree about what "one vocabulary" means. So the turn is **persisted before the terminator is sent**, and a client that refetches `GET /api/conversations/{cid}` on `done` cannot lose the race. One test asserts exactly that ordering by reading while the socket is still open. |
| **C8** | `P1-5` / `P4-10` | `api/deps.py` accessors take a `Request`. | **They take an `HTTPConnection`, and one accessor is new.** A WebSocket is an `HTTPConnection` and not a `Request`, and the socket needs the same settings, locator, and provider that a route does. The new one is `get_provider_factory`, reading `app.state.provider_factory` — installed in `create_app` as `build_provider` and replaced by the suite with one that hands back `FakeProvider`. It is a **factory** rather than a built provider so that a settings change takes effect on the next request (exit criterion 2), and it is the single seam that runs the whole application against a fake. `app.py` is now the only module in the application that imports the registry, which is the composition root paying for httpx on the import path exactly as it should. |
| **C9** | `P4-11` | "`has_key: bool` per provider and nothing more". | **`key_presence()` in the registry, and a `ProviderError` handler in the envelope.** The registry's `provider_status()` already answered for the *configured* provider only; per-provider presence is one more thing that must be derived where a key may be unwrapped, so it is a registry function rather than a route reading two settings fields. The handler is the other half: ruling 4 says a provider failure is an envelope and never a crash, and **no Phase 4 route raises one** — the socket carries them as events and the settings route reports an unconfigured provider as *data*. It is registered and tested anyway, on a route the test adds, because the first provider call from a Phase 6 route would otherwise reach the writer as a `500` carrying a request id and a traceback left in the log. |
| **C10** | `P4-9` | "The live conversations, newest first". | **Newest first by `updated_at`, with a stable tiebreak, and the docstring says which part is which.** `utc_now` has second resolution (the project's standing choice), so two conversations touched in the same second cannot be ordered by time at all. The remaining sort keys make that case **stable rather than meaningful**: two identical reads answer identically, because a panel whose rows swap places on a refresh looks broken in a way nobody can reproduce. The ordering test stamps its own timestamps rather than racing the clock, and a second test asserts the tie is stable. |

**Group D, delivered 2026-09-06.** Sixteen deviations. `D1` is the only one that moves a surface
this plan placed somewhere else; `D4` is the only one that *adds* a feature (and it is one the plan
named as desirable); `D2` and `D11` are the two to read — one says what an accepted rewrite does
**not** leave behind, and the other is the rule that keeps the editor the only thing that edits.
`D13` and `D14` are the two the documentation pass found rather than the build: both are places
where the **client** turned out to read `specs/providers.md` differently from the server, both were
already built and tested this way, and both are now that document's § 13 corrections 4 and 5. `D15`
is the pass's own scope, and `D16` is a **test-suite** change made during it — the one kind that
this project requires to be written down whether or not it changes behaviour.

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **D1** | `P4-13` / `P4-14` | `SelectionActions.tsx` gains a **fourth** action (P4-13), and P4-14 does not say where its three live. | ***Ask agent* is the fourth action over a selection; proofread, tone, and rewrite live in the panel.** Taken literally, putting all four over the selection would make it six buttons — and the three actions want the thing the panel already has and the selection does not: **the composed context on screen**. An action is a question with a fixed wording, it costs money, and ruling 5 says what is being sent is shown before it is sent; over the selection there is nowhere to show it. So *Ask agent* points the panel at the passage, and the actions act on what the writer can see is going to be sent. They are offered **only** while that passage is in the chapter that is open, because `createAnchor` anchors a range of the *open* document and a range pointed at in one chapter and anchored in another is a suggestion about text nobody looked at. |
| **D2** | `P4-14` | "The panel renders an explicit before/after and accepting applies it as an ordinary editor transaction." | **The before/after is client state and does not survive a reload, and the anchor the action minted is removed either way.** D33 is what settles the first half: an accepted rewrite is an ordinary transaction *rather than a durable proposal*, so a diff that came back after a reload would be half of Phase 7's proposal record with none of its dedup or its merge — the shape D33 exists to keep this phase out of. What *does* survive is the **turn**, in the transcript, because it was asked for and paid for. The second half is not in the plan at all and is a decision: the anchor is machinery this action created rather than a mark the writer asked for, so leaving one behind per rewrite would fill the *Marks* tab with passages nobody marked. It is deleted on accept **and** on discard, best-effort — failing to tidy up must never be the reason an accepted rewrite is not applied. |
| **D3** | `P4-12` | "The socket lives in the provider as an effect, never in the reducer." | **It does — and *constructing* one is an injected seam, `ChatSocketFactory`.** jsdom has a `WebSocket` constructor and it would try to open a real connection, and no test in this project has ever touched the network (outline § 8). So `api/socket.ts` declares the interface, the app passes `createChatSocket`, and `__tests__/fakes/fakeChatSocket.ts` is a hand-written fake on the `ApiClient` pattern — it fails to compile when the interface changes, which a global stub would not. It **runs no stream of its own**: what a test needs from it is *cadence*, which is the one thing no real provider produces on demand and the whole reason `FakeProvider` may stage it on the server. |
| **D4** | `P4-14` | "A word-level diff is **desirable, not required**… shipping the same field-level answer here is a legitimate outcome." | **It landed: `web/src/wordDiff.ts`, a longest-common-subsequence over words.** A proofread changes four characters in two hundred words, and two paragraphs that differ in four characters are two paragraphs the writer has to compare by eye before they can accept anything — the acceptance stops being a decision and becomes a leap. Nothing smarter than an LCS: no character-level refinement, no move detection, no similarity heuristics, because those are the parts that need tuning and a tuned diff with no corpus is wrong in ways nobody notices. The property asserted over every case is that **the parts concatenate back to both texts**, so what is drawn as "unchanged plus added" *is* what accepting applies. Past `MAX_DIFF_WORDS` it reports one replacement rather than spending a second of the writer's afternoon. |
| **D5** | `P4-14` | Three actions, each "returning a replacement" — the plan does not say where their wording lives. | **One client module, `web/src/rewriteActions.ts`, named as the one place it lives.** The socket takes the writer's question **verbatim**, and an action is a question the app asks on their behalf, so it travels as an ordinary `ask` frame — no second path to a model and no route that spends tokens differently from the one the panel uses. Putting the wording behind a new frame field or a new route would be a surface this phase did not budget *and* would fix a vocabulary of actions before Phase 6 knows what its tools want to say. Moving them server-side when the agent needs them is a change to one file. Prompt tuning is out of scope for 1.0 (outline § 2): these are a starting point § 8 assesses by hand. |
| **D6** | `P4-15` | The settings screen, unplaced — the item names the screen and not what reaches the routes. | **`readSettings` and `writeSettings` hang off `ChatContext`, and there is no sixth context.** The screen is a **view of the assistant panel**: the block it can change is the assistant's own, and the sentence it shows when nothing is configured is the same sentence the transcript shows as `provider_unconfigured`. A sixth context for two calls would be a provider tree one level deeper for no lifetime of its own, and handing the raw `ApiClient` down through the panel would be the first place in the app that does. |
| **D7** | `P4-12` | Phase 1's `Workspace.test.tsx` keeps running unchanged. | **One assertion changed.** It asserted the agent region contained the words *arrives in Phase 4*; it now asserts the region holds the conversation list. The placeholder was P1-9's, it said what was true, and P4-12 is the commit that makes it untrue. Recorded because a changed assertion is a deliberate act (`CLAUDE.md`, Testing) — the same as `A4` and `B6`. |
| **D8** | `P4-9` / `P4-12` | Group C added `conversation_not_found` to the envelope. | **The client's `ERROR_CODES` mirror had not caught up, and now has.** Group C's routes raise it and Group C's client did not know the name, which is exactly the drift the mirrored vocabularies exist to prevent. Extension-only; nothing else in `types.ts` moved. |
| **D9** | `P4-13` | "jsdom cannot make a text selection, so the gesture is covered on one side and the composition on the other." | **The fourth feature under that limitation, and the probe has to run *after* the panel has loaded.** `selectionActions.test.tsx` covers the control against a real editor and `askAgent.test.tsx` covers the panel, exactly as *Mark passage*, *Re-link here*, and *Add to bible* are covered. The wrinkle worth writing down: the probe is a **button the test presses**, not a mount effect. React runs a child's effects before its parent's, so a probe that pointed at a passage on mount would be overwritten by `ChatProvider`'s own load — which resets the state, correctly, because at mount there is nothing to preserve. A writer selects a passage after the app has loaded, and so does the probe. |
| **D10** | `P4-12` | "The socket… opened, and an explicit teardown." | **It is opened on the first *ask*, not on opening a conversation.** Reading a transcript is a read of the project file and opens nothing: a socket held for every conversation the writer glances at is a connection per glance, and D30's whole point is that a conversation can be read with no key set and no provider configured at all. One socket at a time, belonging to the conversation on screen, closed when that changes or the provider unmounts, and **never reopened by itself** — an automatic reconnect that re-sends the question is D13 and ruling 6 violated by accident. Frames are buffered until the handshake finishes, because a browser socket drops a send made before it opens and losing the writer's first question that way is a bug they could only reproduce on a slow connection. |
| **D11** | `P4-14` | "Accepting applies it as an ordinary editor transaction (D33)." | **The replacement travels to the editor as *pending state*, the way a heading jump does, and `DocumentContext` gained `resolveAnchor`.** `ManuscriptEditor` owns the TipTap instance and everything it is asked to do arrives as state it clears when it has done it (`pendingHeading`, `pendingAnchor`, now `pendingReplacement`) — so the panel never holds an editor handle and there is still exactly one thing in this application that edits the manuscript. `resolveAnchor` flushes and re-reads the document's anchors, and it **throws** rather than returning when that read fails: an action must never apply to a `stale` anchor, and *we could not find out* is not *it is fine*. A single-paragraph replacement goes in as a text node so a partial sentence stays in its paragraph; one with blank lines in it goes in as paragraphs, because a model asked to rewrite across paragraphs answers with paragraphs. |
| **D12** | `P4-15` | "§ 8's script has been run and its results recorded here." | **Not yet run — it needs a real key, a real provider, and a person.** Every other part of P4-15 is done: the screen, and the documentation pass across all eight documents. § 8 is the writer's to run, and it is the only thing standing under the three surfaces no test reaches — the pointer gesture, a real provider on the other end of a real socket, and **whether the answers are any good**. The phase is not complete until its *Outcome* column is filled in. |
| **D13** | `P4-12` | `specs/providers.md` § 4's ordering rules, and its asymmetry stated as being about an unknown event **`type`**. | **The client enforces none of the ordering rules but one, and that is D32's own reasoning taken one step further.** `chatReducer` appends a `delta` that arrives before a `start` and does not reset on a second `start`, because a fragment dropped to satisfy an ordering nobody promised on the wire costs the writer **words they paid for** — a strictly worse outcome than the detail an unknown `type` costs. The one rule it does enforce is the one that cannot be tolerated: after a terminator, nothing lands. The rules still bind the server, and the adapter suites say so. Built this way in Group D and pinned by `chatReducer.test.ts`; written down here and in `providers.md` § 13 at `P4-15`. |
| **D14** | `P4-12` | Ruling 4 and `specs/providers.md` § 6: six error codes, **closed**. | **`StreamFailure.code` is `ProviderErrorCode \| null`, and a socket that stops mid-answer carries `null`.** None of the six is true of it — nothing was refused, no limit was reached, and the provider said nothing at all — so the panel has its own sentence for it rather than borrowing `provider_unavailable`. This is `C6`'s rule arriving on the client: the six are the **provider's** taxonomy, and a condition no provider caused does not get one of its names. The six stay closed. |
| **D15** | `P4-15` | "the README's configuration keys". | **The configuration keys were already level; the rest of the README was not, and the pass brought it level too.** `P4-11` had written the whole `ARCHETYPE_LLM_*` block into it in the change that added those settings, so the named item was already done — but the document around it still opened with *Current state: Phase 2 built*, still called the assistant panel a placeholder, still said there was no story bible, and still listed a route table that stopped before Phase 3's twenty-three bible routes. A README that describes the product as it was two phases ago is exactly the bug this project's third rule exists to prevent, so the state paragraph, *Using it*, the route table, and the closing pointer were rewritten. The **configuration** section is untouched, which is the item as written. |
| **D16** | — | The frontend suite runs green. | **It did, and then it did not, and the cause was a Phase 2 test asserting an exact autosave count.** `snapshots.test.tsx`'s preview test failed on roughly one run in two once Group D had added seventy-two tests to the same run, always with `expected 4 to be 3`. It typed seven characters and then waited for the document to reach **version 3** — which is a claim about how many autosave windows elapsed while `userEvent` typed, and on a loaded machine those keystrokes straddle two windows instead of one. The first diagnosis was impatience and the remedy was a longer `waitFor`; that was **wrong**, and it was reverted — raising the timeout only made a wrong assertion take three seconds to fail. The fix is that the test now waits for the **text** it typed to be the stored text, through a new `FakeApiClient.textOf`, which is the question it always had: *has what I typed been saved?* rather than *how many times did the scheduler fire?* Two waits in that file were of this shape and both were changed; four consecutive full runs are green. **No assertion was weakened** — waiting on the content is a stronger claim than waiting on a counter, which is what keeps this on the right side of *never loosen a test to get a green suite*. |

---

## 8. Manual Acceptance — the phase-boundary run

§ 5's script, written out step by step with what each step must show. It is here, rather than in a
scratch file, for the reason Phases 2 and 3 both earned: **it is the only thing standing under the
surfaces no test reaches.** In this phase those are three — the pointer gesture jsdom cannot make
([phase-2-plan](phase-2-plan.md) § 7, `C7` — now for a fourth selection action), a real provider on the other end of a real socket, and
**whether the answers are any good**, which is the exit criterion in the outline's own words and
the one thing no fixture can stage.

Run it against the **single-process build** — the shape the product ships in (`P1-14`, D7) — with a
real key in the environment:

```powershell
cd web; npm run build
cd server; .\.venv\Scripts\python.exe -m archetype     # http://127.0.0.1:8787
```

**Result: not yet run.** Fill the *Outcome* column in step by step as it happens, and record
anything it finds in § 7 the way Phase 2's step 13 recorded `D15` and Phase 3's step 12 recorded
`E2`.

| # | Do this | It must | Outcome |
|---|---|---|---|
| **1** | Start with no key set. Open the assistant panel and ask anything. | It refuses with `provider_unconfigured` and says where a key comes from. Nothing is persisted as an answer, and nothing crashes. | — |
| **2** | Set the Anthropic key in the environment, restart, and confirm the settings screen. | It shows the provider, base URL, and model, and says a key is **present** — never the key, its length, or its first characters. | — |
| **3** | Open the Phase 2 test manuscript, select a paragraph, and use *Ask agent* to ask something about it. | The context preview shows the passage, what surrounding text came with it, and a token estimate, **before** anything is sent. | — |
| **4** | Send it. | The answer streams in progressively rather than appearing at once, and the usage is shown when it finishes. | — |
| **5** | Ask a second question in the same conversation. | The reply takes the first exchange into account — the conversation is composed, not just the latest message. | — |
| **6** | Ask a long question and **cancel** it mid-answer. | The stream stops, the partial answer stays on screen, it is marked cancelled, and no further tokens are billed. | — |
| **7** | Reload the page. | The conversation, all its messages, the usage, and the cancelled turn are all still there, read back from the project file (D30). | — |
| **8** | Open the stored context for one answer. | It shows exactly what was sent — the same thing step 3 previewed (ruling 5). | — |
| **9** | **Proofread** a paragraph and accept the result. | An explicit before/after is shown; accepting changes the text in one undoable step; `Ctrl+Z` puts it back; the autosave runs once. | — |
| **10** | **Rewrite** a different paragraph and reject the result. | The manuscript is untouched, and nothing is left behind in any list or history. | — |
| **11** | Ask for a rewrite, then **edit that passage in the editor** before applying it. | The apply is **refused**, naming the passage and saying it has changed — the anchor went `stale` and the action honoured it. | — |
| **12** | Swap to the OpenAI-compatible provider in settings (or a local server speaking it) and ask **the same question as step 3**. | It answers, with no code change and no restart. The two answers may differ in content; both must be coherent answers to the question asked. | — |
| **13** | Unset the key or set a bad one, and ask again. | `provider_auth_failed` reaches the writer as a stated cause. The transcript survives, and the failed turn is visible in the history rather than being a gap. | — |
| **14** | Select an entire long chapter and ask a question about it. | Either it answers, or it refuses with `context_too_large` naming what was too big. It must **not** silently truncate (ruling 7). | — |
| **15** | With a key configured, open the browser devtools and search the network traffic, `localStorage`, and the bundle for the key. | It is nowhere. Not in a response body, not in a settings payload, not in storage, not in the JavaScript (D8, D34). | — |

**And record what the model actually said** for at least three of the questions above, verbatim, in
this section. The suite cannot assess an answer and § 5's first exit criterion is about answers.
That record is the only evidence the phase met its own bar, and it is what a later phase compares
against when a prompt changes.
