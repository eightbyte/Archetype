# Archetype — The Provider Port

**Status:** Specification · written at `P4-1`, **before** the code it governs ·
**Version:** 1.0 · **Date:** 2026-09-04
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1
(D5, D8, D11, D12, D13, **D30**, **D31**, **D32**, **D33**, **D34**)
**Plan:** [`specs/phase-4-plan.md`](phase-4-plan.md) — this document is `P4-1`; it governs `P4-2`
through `P4-14`, and any place the code corrects it is marked in § 12 and cross-referenced to that
plan's § 7
**Companions:** [`specs/api-contract.md`](api-contract.md) (the socket and the settings route) ·
[`specs/data-model.md`](data-model.md) (the two tables a conversation lives in) ·
`server/archetype/llm/port.py` (the types this document fixes)

The **provider port** is the one interface through which Archetype talks to a language model.
Phase 4 puts a chat panel and three single-pass actions on top of it; Phase 6 writes an entire
agent against it; Phase 7 composes proposals through it. None of them will ever import a provider
SDK, and none of them will ever branch on which provider is configured.

An anchor promises never to point at the wrong passage. A bible entry promises that a moved fact
flags what depended on it. A provider cannot promise anything about what a model *says* — the
model is somebody else's program and it is not deterministic. So the promise here is about shape:

> **Nothing above the port knows which provider is in play, and no answer changes shape because of
> who produced it.**

And the limit is stated in the same breath, because a port that appears to promise more than this
is a port people will trust with the wrong things:

> **The port normalises the shape of an answer, never its quality, its latency, or its cost.** Two
> providers given the identical `CompletionRequest` will return the identical *types* and may
> return entirely different *text*. Nothing in this project asserts on the text of a real model's
> answer.

Everything else here — how many stop reasons there are, which errors map where, whether tools are
native or prompted — is a quality that can be improved later. Those two are the contract.

---

## 1. What the port is, and what it is not

### The protocol

```python
class LLMProvider(Protocol):
    name: str
    capabilities: Capabilities

    async def complete(self, req: CompletionRequest) -> CompletionResult: ...
    def stream(self, req: CompletionRequest) -> AsyncIterator[StreamEvent]: ...
```

Four members. `name` identifies the adapter (`anthropic`, `openai_compat`, `fake`) and is what a
log line and a `message` row record; `capabilities` is § 5; the two methods are § 1's next
paragraph.

`stream` is declared as an ordinary method returning an `AsyncIterator`, **not** as `async def`, so
that an implementation may be an async generator function and a caller may hold the iterator before
awaiting anything. Both forms satisfy the protocol; neither is preferred.

### Why there are two methods and not one

A streamed answer and a whole answer are genuinely different call sites, and faking either from the
other lies:

- **Buffering a stream to fake `complete`** hides latency. The caller believes it made one quick
  request; it actually held a socket open for forty seconds.
- **Chunking a result to fake `stream`** invents a token cadence that never existed. The panel
  draws a typing rhythm that is a lie about what the provider did, and every test written against
  it is testing our own chunker.

So both are declared, both are implemented by every adapter, and a caller picks the one that
matches what it is doing. What a caller may do when `capabilities.streaming` is false is § 5.

### What the port promises

1. **One vocabulary.** Roles, stop reasons, stream events, error codes, and tool calls are this
   document's, not a provider's. An adapter translates in both directions.
2. **A result is complete or it raises.** There is no partially-filled `CompletionResult`, and no
   empty-string answer standing in for a failure (§ 6).
3. **Nothing is retried inside the port** (plan § 2, ruling 6). One request, one answer, one bill.
4. **Nothing is remembered inside the port.** Every request carries its whole conversation.
5. **A provider's own words are preserved beside the normalised ones**, never instead of them:
   `raw_stop_reason` keeps the provider's string (§ 3), and `ProviderError.detail` keeps what the
   provider said about a failure (§ 6).

### What the port does **not** promise

Stated plainly, because each is a thing a caller will reasonably assume:

- **It does not promise the same text from two providers**, or from one provider twice.
- **It does not promise a token count before a request is sent.** The budget check (§ 7) uses an
  *estimate*; the true count arrives on `Usage` after the answer does, and the two will differ.
- **It does not promise that `max_tokens` is enough.** A truncated answer is a normal outcome and
  reports `stop_reason="max_tokens"`; it is the caller's job to say so on screen.
- **It does not promise streaming is faster.** It promises the caller sees text as it arrives.
- **It does not promise a tool call is well-formed against your schema.** The port normalises the
  *shape* of a tool call; whether the arguments satisfy the declaration's JSON Schema is the
  caller's check, and in Phase 6 it is the tool registry's (§ 8).
- **It does not promise a provider is reachable, configured, or in credit.** Those are § 6's six
  codes, and every one of them reaches the writer as a stated cause.

---

## 2. The normalised shapes

Every shape below is a pydantic model in `llm/port.py`, pure — pydantic and the standard library,
no I/O, no SDK, importable by a test with nothing running.

### `Message`

| Field | Type | Meaning |
|---|---|---|
| `role` | `system` \| `user` \| `assistant` \| `tool` | One vocabulary. An adapter translates; nothing above the port sees a provider's role names |
| `content` | text | The message text. Empty is legal — an assistant turn that only called a tool has no text |
| `tool_calls` | tuple of `ToolCall` | Present on an `assistant` message that called tools. Empty in every Phase 4 message (D31) |
| `tool_call_id` | text or `None` | Set on a `tool` message, naming the call it answers |

A `system` message is a `Message` like any other. Where it *goes* on the wire is the adapter's
problem and is exactly the asymmetry § 6 of the phase plan's risk table names: Anthropic takes a
separate `system` parameter, OpenAI takes a message in the list. The port has one representation
and both adapters translate it, which is what stops the port from having a favourite.

### `ToolCall`

| Field | Type | Meaning |
|---|---|---|
| `id` | text | The provider's identifier for this call, echoed back on the answering `tool` message. Minted by the fallback when the provider has none (§ 8) |
| `name` | text | The declared tool's name |
| `arguments` | JSON object | Already parsed. **Never a JSON string** — a provider that sends a string has it parsed by its adapter, and a string that will not parse is `provider_refused` (§ 6) |

### `ToolDeclaration`

| Field | Type | Meaning |
|---|---|---|
| `name` | text | What the model calls it |
| `description` | text | What it does, in the model's terms |
| `parameters` | JSON Schema object | The argument shape |

Declared in Phase 4, used in Phase 6 (D31). **Phase 4 declares none.**

### `CompletionRequest`

| Field | Type | Meaning |
|---|---|---|
| `messages` | tuple of `Message` | The whole conversation, composed by the caller |
| `model` | text | The provider's model id, verbatim. The port never maps model names |
| `max_tokens` | int | The answer's ceiling |
| `temperature` | float or `None` | `None` means "the provider's default", which is not the same as `0.0` |
| `stop` | tuple of text | Stop sequences. Empty is the normal case |
| `tools` | tuple of `ToolDeclaration` | **Empty in every Phase 4 call** (D31) |
| `tool_choice` | `auto` \| `none` \| `required` | Only meaningful with tools; `auto` is the default |

### `CompletionResult`

| Field | Type | Meaning |
|---|---|---|
| `text` | text | The answer. Empty when the model only called tools |
| `tool_calls` | tuple of `ToolCall` | Empty in Phase 4 |
| `stop_reason` | one of § 3 | Normalised, closed |
| `raw_stop_reason` | text | The provider's own string, kept verbatim. Empty only when the provider sent none |
| `usage` | `Usage` | What it cost |

### `Usage`

| Field | Type | Meaning |
|---|---|---|
| `input_tokens` | int | As reported by the provider |
| `output_tokens` | int | As reported by the provider |

Both default to `0`, which means **"not reported"** and not "free". A provider that does not report
usage is a provider whose bill this app cannot show, and the panel says "not reported" rather than
drawing a zero. `Usage` is what a `message` row records (D30) and what the panel shows.

---

## 3. Stop reasons — the closed set, and the provider's own string

`stop_reason` is closed. Seven members, each with exactly one writer:

| Member | Written by | Means |
|---|---|---|
| `end_turn` | an adapter | The model finished on its own |
| `max_tokens` | an adapter | The answer hit the request's ceiling and is truncated |
| `stop_sequence` | an adapter | A stop sequence from the request was produced |
| `tool_use` | an adapter | The model stopped in order to call a tool (Phase 6) |
| `refusal` | an adapter | The provider declined to answer. **Not an error** — a refusal is a complete, successful response whose content is a refusal |
| `other` | an adapter | A provider string this build does not recognise. `raw_stop_reason` holds it |
| `cancelled` | **the caller**, never an adapter | The stream was closed by us, mid-answer (D11, plan § 2 ruling 6) |

Two rules follow, and both are tested:

- **`raw_stop_reason` is never dropped.** An adapter that maps `"end_turn"` to `end_turn` still
  records `"end_turn"`. This is what makes `other` diagnosable instead of merely honest.
- **No adapter ever produces `cancelled`.** It is written by whoever closed the stream, and it is
  the one stop reason a provider cannot cause.

`refusal` deliberately does *not* raise. A model saying "I won't do that" is an answer, it is
billed, and the writer paid for it — throwing it away and reporting an error would lose both the
text and the usage. `provider_refused` (§ 6) is a different thing: the *provider*, not the model,
rejected the request.

---

## 4. The stream event vocabulary (D32)

One vocabulary, over one WebSocket, defined here and **extended — never replaced — by Phase 6**.
Every event is an object with a `type` discriminator.

| `type` | Carries | When |
|---|---|---|
| `start` | `model` | Once, first, before any text |
| `delta` | `text` | Zero or more times. `text` is a fragment, never the accumulated answer |
| `usage` | `usage` | At most once, when the provider reports it. May arrive before or after the last `delta` |
| `done` | `stop_reason`, `raw_stop_reason` | Once, last, on a stream that completed |
| `error` | `code`, `message` | Once, last, on a stream that failed. `code` is one of § 6's six |

Phase 6 adds `plan`, `tool_call`, `tool_result`, and `step` to this union and changes nothing that
is here.

### The ordering rules

- `start` is first. `done` or `error` is last, and **exactly one of them** ends a stream.
- A stream that ends **without** either is a failure the caller must handle — it is what a dropped
  socket looks like from the inside, and `FakeProvider` can produce it on demand (`P4-3`).
- `delta` fragments concatenate, in arrival order, to the whole answer. Nothing de-duplicates them
  and nothing re-orders them.

### The asymmetry, which is deliberate (D32)

> **The server rejects an event type it does not know. The client ignores one.**

The server's union is a pydantic discriminated union: an unknown `type` fails to validate, loudly,
because on the server an unrecognised event means an adapter and the port have parted company and
the only safe answer is to stop. The client's reader returns `null` for an unknown `type` and the
panel skips it, because a browser holding a stale bundle against a newer server must degrade to
*less detail*, not to a broken panel — a Phase 6 server emitting `step` events at a Phase 4 bundle
must still show the answer.

This is one rule with two implementations on purpose, and it is tested in **both** suites
(`P4-2`).

---

## 5. Capabilities — four flags, and exactly what each one changes

```python
class Capabilities:
    native_tools: bool
    streaming: bool
    max_context: int
    supports_system: bool
```

| Flag | False / low means | Who reads it |
|---|---|---|
| `native_tools` | The provider has no tool-calling API. Tool declarations are rendered into the system prompt and the reply is parsed back into `tool_calls` — § 8 | The adapter, at construction; `P4-7`'s fallback |
| `streaming` | The provider cannot stream. `stream()` raises `provider_unavailable` rather than faking a cadence | The socket (`P4-10`), before it opens one |
| `max_context` | The provider's context window in tokens. The effective budget is `min(max_context, llm_context_budget)` | The budget check (§ 7) |
| `supports_system` | The provider has no system role. The adapter folds the system message into the first user message, and says so in no other way | The adapter only |

Two rules that are easy to get wrong:

- **A capability is a statement about the provider, not a switch on our behaviour anywhere above
  the port.** No route, no store, and no component branches on one. The only readers are the
  adapters, the socket's decision to stream at all, and the budget check.
- **A caller facing `streaming=False` may call `complete()` and emit `start`, one `delta` carrying
  the whole text, `usage`, and `done`.** That is permitted — it says truthfully that the answer
  arrived all at once. What is forbidden is *splitting* it into fragments to look like typing. The
  adapter never does either; this is the socket's decision, in the open.

---

## 6. The error taxonomy (plan § 2, ruling 4)

**A provider failure is an error envelope, never a crash and never a silent empty answer.** Six
codes, closed:

| Code | The condition | Typical provider signal |
|---|---|---|
| `provider_unconfigured` | No provider selected, no key present, or a provider name this build does not have an adapter for | *ours* — raised before any request is composed |
| `provider_auth_failed` | The key is missing, wrong, revoked, or lacks access to the model | `401`, `403` |
| `provider_rate_limited` | Rate or quota limit reached | `429` |
| `provider_unavailable` | The provider could not be reached or failed on its own side | connection error, timeout, `5xx` |
| `provider_refused` | The provider rejected the *request* — a malformed body, an unsupported parameter, a safety refusal at the API level, or a tool reply the fallback could not parse | `400`, `422`, a content-policy rejection |
| `context_too_large` | The composed context exceeds the effective budget | *ours* (§ 7), or the provider's own context error |

Carried by one exception, `ProviderError`, holding `code`, a writer-facing `message`, the
`provider` name, and a `detail` field preserving what the provider actually said. Routes carry no
domain logic: `api/errors.py` translates it to the uniform envelope, and the socket emits it as an
`error` event carrying **the same code** (§ 4). One taxonomy, two transports.

Three rules:

- **`provider_refused` is about the provider; `stop_reason="refusal"` is about the model** (§ 3).
  The first is an error and costs nothing; the second is a billed answer.
- **A failed answer is persisted** (`P4-10`, D30). The `message` row records `error_code` so a
  failed turn is visible in the history rather than being a gap the writer has to remember.
- **Nothing is retried** (ruling 6). Not by the adapter, not by the socket, not by the panel. The
  autosave backoff ladder is right there and is exactly wrong here: retrying a save costs nothing
  and protects the writer's words; retrying a completion costs money and protects nothing.

The HTTP status each code maps to belongs to
[`specs/api-contract.md`](api-contract.md) and is fixed at `P4-9`/`P4-11`, not here.

---

## 7. The context budget — a hard refusal, not a truncation (ruling 7)

A request whose composed context exceeds the effective budget is **refused** with
`context_too_large`, naming what was too big. Nothing is silently dropped.

- The effective budget is `min(capabilities.max_context, settings.llm_context_budget)`, in tokens.
- The check runs **before the provider is called at all**, and `P4-10`'s test asserts the fake
  recorded zero calls when it fires.
- The estimate is an estimate, and this document says so where a reader will look: it is computed
  from the composed text without asking a provider to count, so it is approximate and deliberately
  conservative. `Usage` after the fact is the true number, and the two will differ.

Truncation is how a continuity answer comes back confidently wrong, because the half of the chapter
that contradicted it was the half that got cut. A writer narrowing their selection is a correct and
cheap fix; a quiet cut is neither.

---

## 8. Tools, before there are any (D31)

`ToolDeclaration`, `ToolCall`, `CompletionRequest.tools`, `CompletionResult.tool_calls`, and the
`tool` role are all in the port from `P4-2`. **Phase 4 declares no tools and calls none.** This is
the one place the phase deliberately builds ahead, and the ruling records both the argument and the
counter-argument (D31).

What that costs and what it buys is § 6 of the plan. What it *means for this document* is three
rules an adapter is held to:

1. **A tool call arrives normalised or not at all.** `arguments` is a parsed JSON object at the
   port. A provider that sends a JSON string has it parsed by its adapter; a string that will not
   parse is `provider_refused` with the raw text preserved — never a silently empty call.
2. **The prompted-JSON fallback is invisible above the port** (`P4-7`). When `native_tools` is
   false, the declarations are rendered into the system prompt and the model's JSON is parsed out
   of the reply and presented as ordinary `tool_calls`. A caller cannot tell the difference, and
   one test asserts a native path and a fallback path produce **identical** normalised calls for
   the same declaration.
3. **The fallback mints call ids; a native provider's ids are kept.** Nothing above the port may
   assume an id's shape, and nothing may parse one.

---

## 9. Constants

Every constant this document names exists in the code under that name (`P4-1`'s *done when*).

| Name | Where | Value in this build | Why |
|---|---|---|---|
| `ROLES` | `llm/port.py` | `system`, `user`, `assistant`, `tool` | § 2's closed role vocabulary |
| `STOP_REASONS` | `llm/port.py` | the seven of § 3 | Closed, each with one writer |
| `STREAM_EVENT_TYPES` | `llm/port.py` | `start`, `delta`, `usage`, `done`, `error` | D32's Phase 4 members; Phase 6 adds four |
| `PROVIDER_ERROR_CODES` | `llm/port.py` | the six of § 6 | The taxonomy, in one place |
| `TOOL_CHOICES` | `llm/port.py` | `auto`, `none`, `required` | § 2 |
| `IdPrefix.CONVERSATION` | `archetype/ids.py` | `cnv` | D30's table |
| `IdPrefix.MESSAGE` | `archetype/ids.py` | `msg` | D30's table |

Settings keys (`llm_provider`, `llm_base_url`, `llm_model`, `llm_max_tokens`,
`llm_context_budget`, and the two `SecretStr` keys) are `P4-8`'s and are documented in the README's
configuration table rather than duplicated here.

---

## 10. What a provider may **not** be asked to do

Stated in as many words, because each is a thing someone will reasonably assume it does:

- **It is not asked to remember anything.** Every request is complete. Conversation state lives in
  the project file (D30) and is composed into `messages` on the way out. There is no session, no
  thread id, and no provider-side history.
- **It is not asked to fetch anything.** No URL, no file path, no built-in web tool, no
  provider-hosted retrieval. The model sees what the composer put in front of it and nothing else
  (backlog `Q4`; Phase 6 owns tools regardless).
- **It is not asked to be deterministic**, and **no test in this project asserts on the text of a
  real model's answer.** The suite tests the plumbing; the phase plan's § 8 assesses the answers,
  by hand, and records what the model actually said.
- **It is not asked to count tokens for us.** § 7's estimate is ours, before the call; `Usage` is
  the provider's, after it.
- **It is not the place retries live** (ruling 6).
- **It is not asked to store, log, or return a key.** `ARCHETYPE_ANTHROPIC_API_KEY` and
  `ARCHETYPE_OPENAI_API_KEY` are `SecretStr`, never returned by a route, never in a log line, and
  never in the browser (D8, **D34**).
- **It is not asked to write to the manuscript or the bible.** The writer owns the words (D12). A
  proofread, tone, or rewrite result is a *replacement offered*, applied only by the writer's
  acceptance and only as an ordinary editor transaction (D33).

---

## 11. Where a provider is constructed, and the import rule

**No provider SDK is imported outside `llm/adapters/`** (plan § 2, ruling 2). Not in a route, not
in a store, not in a test that is not an adapter test. The port's types import nothing but the
standard library and pydantic.

This is enforced rather than asserted: a test walks the import graph of `archetype/` and fails if
any module outside `llm/adapters/` imports `anthropic` or `openai` — the same shape of guard as the
closed editor schema and the anchor package's one-way imports.

The registry (`P4-8`) is the **only** place a provider is constructed. It reads settings, builds
the configured adapter, and raises `provider_unconfigured` before anything is composed if it
cannot. Callers receive an `LLMProvider` and never a class name.

An adapter is tested against **recorded fixtures, never the network** (ruling 3): real
request/response payloads captured once by hand, committed, and replayed. Tests that require a live
provider are `@pytest.mark.live` and excluded by default. The suite is green with no key set.

---

## 12. Deliberate extension points

Shapes chosen so that a later phase adds rather than migrates:

- **`StreamEvent` is a union with a discriminator**, so Phase 6 adds `plan`, `tool_call`,
  `tool_result`, and `step` without touching a Phase 4 member, and a stale client degrades (§ 4).
- **`tools` and `tool_calls` exist and are empty** (D31), so Phase 6 declares tools without
  changing a signature.
- **`Message.role` includes `tool`** for the same reason.
- **`Capabilities` is a model, not a set of booleans passed around**, so a fifth flag is a field.
- **A `message` row references nothing about a run, and Phase 6's `run` will reference a message**
  (D30) — so an agent turn is an addition to this schema, not a rewrite of it.
- **`ProviderError.detail` is untyped and preserved**, so a provider condition this build does not
  distinguish is still diagnosable from a log.

---

## 13. Corrections

*Where the code corrected this document, in the same change that made the correction. Each entry
cross-references [`specs/phase-4-plan.md`](phase-4-plan.md) § 7.*

| # | What this document said | What is true, and why |
|---|---|---|
| — | *Nothing yet.* | `P4-2` was written from this document; the first correction lands here with the deviation that caused it. |
