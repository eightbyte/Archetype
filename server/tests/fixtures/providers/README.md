# Provider fixtures

The payloads the two adapters are asserted against (`P4-5`, `P4-6`; phase-4-plan § 2, ruling 3).

**An adapter is tested against recorded fixtures, never against the network.** Nothing in the
suite opens a socket: every adapter test replays one of these through an `httpx.MockTransport`.
Tests that would require a live provider are marked `@pytest.mark.live` and excluded by default,
and the suite is green with no key set.

These are also D31's only consumer. Phase 4 declares no tools and calls none, so the `tool_call`
case in each corpus is the one thing standing under the claim that tool plumbing built two phases
early actually works — which is the argument the decision was ruled on, and the risk it takes.

## Provenance — read this before trusting a payload

| Corpus | How it was produced |
|---|---|
| `anthropic/cases.json` | **Transcribed by hand** from the published Messages API wire format, not captured from a live account. |
| `openai/cases.json` | **Transcribed by hand** from the published chat-completions wire format, not captured from a live account. |

Ruling 3 asks for payloads captured once by hand and committed. The capture scripts beside this
file are that step, and they are written and committed; they have **not been run**, because
running one spends money against a real key and Group B was built without one. Every field in
these files is one a real response carries, and the shapes were written from both providers'
documentation rather than from either adapter's code — which is the same discipline
`tests/fixtures/anchors/cases.json` follows, and it is what makes a disagreement a bug in one of
the two rather than a fixture to re-record.

**The honest limit, stated plainly: a transcribed payload proves the adapter matches what the
documentation says, not what the provider actually sends.** Closing that gap is
[`specs/phase-4-plan.md`](../../../../specs/phase-4-plan.md) § 8's job — its steps 4 and 12 put a
real answer from each provider on the screen — and refreshing these files from that run is one
command each. Do it when § 8 runs, and again whenever a provider changes something.

```powershell
# from server/, with the venv active and the relevant key in the environment.
# Each script makes a handful of real, billed requests and rewrites its cases.json in place.
$env:ARCHETYPE_ANTHROPIC_API_KEY = "sk-ant-..."
.\.venv\Scripts\python.exe tests/fixtures/providers/capture_anthropic.py

$env:ARCHETYPE_OPENAI_API_KEY = "sk-..."
.\.venv\Scripts\python.exe tests/fixtures/providers/capture_openai.py
```

A capture keeps each case's `name`, `note`, and `port_request` — those are the corpus's, written
from the specification — and replaces only what the provider said: `wire_response`, `sse`, and the
`http_status`. The expectations (`port_result`, `port_events`, `port_error`) are **not** rewritten,
because a fixture that re-recorded the answer as well as the question would assert nothing. A
capture that makes a test fail has found something, and the failure is the point.

## The case file

One `cases.json` per provider, in the shape every other corpus in this project uses
(`anchors/`, `markdown/`, `bible/storytime/`). Each case states both halves — what the adapter
must send, and what it must produce from what came back — so a translation that drifted in either
direction fails rather than round-tripping quietly against itself.

| Key | Meaning |
|---|---|
| `name` | The case, and what a failure is reported as. |
| `note` | Why this case is in the corpus. Not decoration: each one names the thing it is the only cover for. |
| `stream` | True when the case exercises `stream()` rather than `complete()`. |
| `adapter` | Constructor overrides for this case — `capabilities`, `stream_usage`. Absent means the adapter's own defaults. |
| `port_request` | A `CompletionRequest`, as the composer would build it. |
| `wire_request` | The exact body the adapter must POST. Absent means the case does not assert the outbound half. |
| `http_status` | What the provider answered with. |
| `wire_response` | The provider's JSON body — a whole answer, or an error. |
| `sse` | The provider's response body as SSE lines, for a streamed case. |
| `port_result` | The `CompletionResult` the adapter must produce. |
| `port_events` | The exact `StreamEvent` sequence it must produce. |
| `port_error` | The `ProviderError` it must raise: `code`, and a fragment the message must contain. |

Adding a case is adding an object to the list. Nothing enumerates them by name, so a new one is
picked up by every test in the file that applies to its shape.
