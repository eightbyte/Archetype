"""Re-record a provider corpus against the real service (P4-5, P4-6; ruling 3).

Shared by ``capture_anthropic.py`` and ``capture_openai.py``. Not imported by the suite - it is a
documented manual step, like ``tests/fixtures/db/capture_v00N_*.py``, and it is the *only* thing in
this repository that makes a billed request.

What it rewrites, and what it deliberately does not:

* **rewritten** - ``http_status``, ``wire_response``, ``sse``. What the provider actually said.
* **left alone** - ``name``, ``note``, ``port_request``, ``wire_request``, ``adapter``, and every
  expectation (``port_result``, ``port_events``, ``port_error``). A capture that re-recorded the
  answer as well as the question would assert nothing at all, which is the failure the whole
  fixture discipline exists to prevent. **A capture that makes a test fail has found something.**

The failure cases are captured too, and each needs a condition arranged by hand - a bad key, an
exhausted quota, a prompt over the window. The script says which ones it could not reproduce and
leaves those cases exactly as they were rather than filling them with a wrong answer.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from archetype.config import Settings
from archetype.llm.port import CompletionRequest
from archetype.llm.registry import build_provider

HERE = Path(__file__).resolve().parent


def _cases_path(provider: str) -> Path:
    return HERE / provider / "cases.json"


def _adapter_for(provider: str, case: dict[str, Any], client: httpx.AsyncClient) -> Any:
    """The same adapter the suite builds, through the same registry the application uses."""
    overrides = case.get("adapter") or {}
    settings = Settings(
        llm_provider=provider,
        llm_stream_usage=bool(overrides.get("stream_usage", True)),
    )
    return build_provider(settings, client=client)


async def _capture_case(provider: str, case: dict[str, Any]) -> str:
    """Make the real call for one case and fold the answer back into it. Returns a status line."""
    recorded: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        adapter = _adapter_for(provider, case, client)
        req = CompletionRequest.model_validate(case["port_request"])
        body = adapter.build_body(req, stream=bool(case.get("stream")))
        url = adapter._transport.url(  # noqa: SLF001 - a capture script, not a caller
            "/v1/messages" if provider == "anthropic" else "/chat/completions"
        )
        headers = adapter._transport.headers  # noqa: SLF001
        if case.get("stream"):
            lines: list[str] = []
            async with client.stream("POST", url, json=body, headers=headers) as response:
                status = response.status_code
                if status >= 400:
                    recorded["wire_response"] = json.loads((await response.aread()).decode())
                else:
                    async for line in response.aiter_lines():
                        lines.append(line.rstrip("\r"))
                    recorded["sse"] = lines
        else:
            response = await client.post(url, json=body, headers=headers)
            status = response.status_code
            recorded["wire_response"] = response.json()
        recorded["http_status"] = status

    expected_failure = "port_error" in case
    actually_failed = recorded["http_status"] >= 400
    if expected_failure != actually_failed:
        return (
            f"  {case['name']}: left as it was - expected "
            f"{'a failure' if expected_failure else 'an answer'} and got "
            f"{'a failure' if actually_failed else 'an answer'} ({recorded['http_status']}). "
            "Arrange the condition by hand and run again."
        )
    case.update(recorded)
    return f"  {case['name']}: captured ({recorded['http_status']})"


async def _run(provider: str) -> None:
    path = _cases_path(provider)
    document = json.loads(path.read_text(encoding="utf-8"))
    print(f"capturing {provider} into {path}")
    for case in document["cases"]:
        print(await _capture_case(provider, case))
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("done. Run pytest: a case that now fails has found a real difference.")


def capture(provider: str) -> None:
    """Entry point for the two thin scripts beside this one."""
    settings = Settings(llm_provider=provider)
    try:
        build_provider(settings)
    except Exception as exc:  # noqa: BLE001 - a script, and the message is the whole point
        raise SystemExit(f"cannot capture: {exc}") from exc
    asyncio.run(_run(provider))
