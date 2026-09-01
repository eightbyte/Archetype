"""P1-8 - the contract fixtures.

This test drives the real routes, normalises what varies, and writes the results to
``tests/fixtures/contract/*.json``. ``web/src/__tests__/contract.test.ts`` reads the same files
and checks them against the client's TypeScript types, so a backend shape change fails the
frontend suite rather than the browser. Small in Phase 1; load-bearing from Phase 4.

**The fixtures are written, not asserted against.** Regenerating them is the point: run the
suite, and ``git diff`` shows exactly what the wire shape did. Ids and timestamps are replaced
with fixed placeholders first, so a run that changed nothing produces no diff at all - otherwise
every run would rewrite every file and the diff would say nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from archetype.ids import IdPrefix
from archetype.manuscript.projection import project, text_offset_to_pm_position

from .conftest import CONTRACT_FIXTURES_DIR, build_document

# Built from the registered prefixes rather than spelled out, because a prefix the pattern has
# never heard of is not a failure - it is a fixture that is rewritten on every run and a diff
# that stops meaning anything. `snp_` was exactly that, for one commit.
_ID_PATTERN = re.compile(rf"\b({'|'.join(sorted(IdPrefix.ALL))})_[0-9a-z]{{8,}}\b")
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

FIXED_TIMESTAMP = "2026-01-01T00:00:00Z"

PROSE = build_document(
    headings=[(1, "Arrival"), (2, "The Quay")],
    paragraphs=["The harbour was grey.", "He did not look back."],
)

#: The same chapter with the anchored passage rewritten, so that one fixture carries a stale
#: anchor and the suggestion that goes with it.
BROKEN_PROSE = build_document(
    headings=[(1, "Arrival"), (2, "The Quay")],
    paragraphs=["The harbour was calm.", "He did not look back."],
)


def _range_over(document: Any, passage: str) -> tuple[int, int]:
    """The ProseMirror range a client selecting ``passage`` would send."""
    projection = project(document)
    text_from = projection.text_plain.index(passage)
    from_pos = text_offset_to_pm_position(projection, text_from)
    to_pos = text_offset_to_pm_position(projection, text_from + len(passage))
    assert from_pos is not None and to_pos is not None
    return from_pos, to_pos


class Normaliser:
    """Replaces ids and timestamps with stable placeholders.

    Ids keep their identity across the whole fixture set - the same project is ``prj_000000000001``
    in every file - so the frontend can assert that a document's ``project_id`` matches the
    project it came with.
    """

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self.value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, str):
            return self._string(value)
        return value

    def _string(self, value: str) -> str:
        if _TIMESTAMP_PATTERN.match(value):
            return FIXED_TIMESTAMP
        # Substitution rather than a whole-string match, because ids also appear inside prose -
        # the 404 message names the one that was asked for.
        return _ID_PATTERN.sub(lambda match: self._identifier(match.group(0)), value)

    def _identifier(self, value: str) -> str:
        if value not in self._seen:
            prefix = value.split("_", 1)[0]
            counted = sum(1 for seen in self._seen if seen.startswith(f"{prefix}_")) + 1
            self._seen[value] = f"{prefix}_{counted:012d}"
        return self._seen[value]


def write_fixture(name: str, body: Any, normaliser: Normaliser) -> Any:
    """Write one fixture and return what was written."""
    CONTRACT_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    normalised = normaliser.value(body)
    path = CONTRACT_FIXTURES_DIR / f"{name}.json"
    path.write_text(json.dumps(normalised, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return normalised


def test_contract_fixtures_round_trip(client: TestClient) -> None:
    """Drive every Phase 1 response shape, write it, and read it back."""
    normaliser = Normaliser()
    written: dict[str, Any] = {}

    def capture(name: str, response) -> Any:
        assert response.status_code in (200, 201, 404, 409, 422), (name, response.text)
        written[name] = write_fixture(name, response.json(), normaliser)
        return response.json()

    capture("health", client.get("/api/health"))

    created = capture(
        "project_detail", client.post("/api/projects", json={"title": "The Long Road"})
    )
    project_id = created["project"]["id"]
    first_document = created["documents"][0]["id"]

    second = client.post(
        f"/api/projects/{project_id}/documents", json={"title": "Departure"}
    ).json()

    capture(
        "save_result",
        client.put(
            f"/api/documents/{first_document}/content",
            json={"content_json": PROSE, "version": 1},
        ),
    )
    client.put(
        f"/api/documents/{second['id']}/content",
        json={"content_json": build_document(headings=[(1, "Away")]), "version": 1},
    )

    capture("project_list", client.get("/api/projects"))
    capture("document_list", client.get(f"/api/projects/{project_id}/documents"))
    capture("document", client.get(f"/api/documents/{first_document}"))
    capture("outline", client.get(f"/api/projects/{project_id}/outline"))
    capture(
        "document_meta",
        client.patch(f"/api/documents/{second['id']}", json={"title": "Departure"}),
    )

    capture(
        "error_version_conflict",
        client.put(
            f"/api/documents/{first_document}/content",
            json={"content_json": PROSE, "version": 1},
        ),
    )
    capture("error_not_found", client.get("/api/documents/doc_doesnotexist"))
    capture(
        "error_validation",
        client.put(f"/api/documents/{first_document}/content", json={"content_json": PROSE}),
    )

    # Anchors last, so that adding them changed no fixture that already existed (P2-7). The
    # three between them cover both shapes the client has to read: an anchor the resolver is
    # happy with, and one a save broke, carrying the suggestion for repairing it.
    from_pos, to_pos = _range_over(PROSE, "harbour was grey")
    anchor = capture(
        "anchor",
        client.post(
            f"/api/documents/{first_document}/anchors",
            json={
                "from_pos": from_pos,
                "to_pos": to_pos,
                "version": 2,
                "label": "the harbour",
            },
        ),
    )
    capture(
        "save_result_anchors",
        client.put(
            f"/api/documents/{first_document}/content",
            json={"content_json": BROKEN_PROSE, "version": 2},
        ),
    )
    capture("anchor_list", client.get(f"/api/projects/{project_id}/anchors"))
    assert anchor["status"] == "ok"

    # Group C's routes, in the order the app uses them: mark a version, read the history, read
    # one back, then the two refusals the chapter surfaces have to draw.
    capture(
        "snapshot_capture",
        client.post(
            f"/api/documents/{first_document}/snapshots",
            json={"reason": "manual", "label": "before the rewrite"},
        ),
    )
    snapshots = capture("snapshot_list", client.get(f"/api/documents/{first_document}/snapshots"))
    capture("snapshot", client.get(f"/api/snapshots/{snapshots['snapshots'][0]['id']}"))

    capture(
        "error_reorder_mismatch",
        client.put(
            f"/api/projects/{project_id}/documents/order",
            json={"document_ids": [first_document]},
        ),
    )
    client.delete(f"/api/documents/{second['id']}")
    capture("document_list_deleted", client.get(f"/api/projects/{project_id}/documents/deleted"))
    client.post(f"/api/documents/{second['id']}/restore")

    # The round trip: everything written parses back to what was written.
    for name, body in written.items():
        path = CONTRACT_FIXTURES_DIR / f"{name}.json"
        assert json.loads(path.read_text(encoding="utf-8")) == body


def test_every_fixture_is_one_the_test_writes() -> None:
    """A fixture left behind by a deleted route would silently pass forever on the client."""
    expected = {
        "anchor",
        "anchor_list",
        "document",
        "document_list",
        "document_list_deleted",
        "document_meta",
        "error_not_found",
        "error_reorder_mismatch",
        "error_validation",
        "error_version_conflict",
        "health",
        "outline",
        "project_detail",
        "project_list",
        "save_result",
        "save_result_anchors",
        "snapshot",
        "snapshot_capture",
        "snapshot_list",
    }
    found = {path.stem for path in CONTRACT_FIXTURES_DIR.glob("*.json")}
    assert found == expected


def test_normalisation_is_stable() -> None:
    """The same shape twice must produce byte-identical fixtures, or every run is a diff."""
    body = {
        "id": "prj_abcdefgh1234",
        "documents": [{"id": "doc_zyxwvuts9876", "project_id": "prj_abcdefgh1234"}],
        "created_at": "2026-08-29T12:34:56Z",
        "message": "no document 'doc_zyxwvuts9876' in this workspace",
    }
    once = Normaliser().value(body)
    twice = Normaliser().value(body)

    assert once == twice
    assert once["id"] == "prj_000000000001"
    assert once["documents"][0]["id"] == "doc_000000000001"
    assert once["documents"][0]["project_id"] == "prj_000000000001"
    assert once["created_at"] == FIXED_TIMESTAMP
    assert once["message"] == "no document 'doc_000000000001' in this workspace"


def test_every_registered_prefix_is_normalised() -> None:
    """A prefix the pattern misses rewrites its fixture on every run (P2-12 found `snp_`)."""
    normaliser = Normaliser()
    for prefix in sorted(IdPrefix.ALL):
        assert normaliser.value(f"{prefix}_abcdefgh1234") == f"{prefix}_000000000001"


def test_the_fixtures_directory_is_where_the_frontend_looks() -> None:
    """The path is hard-coded in web/src/__tests__/contract.test.ts; keep them in step."""
    assert CONTRACT_FIXTURES_DIR == Path(__file__).parent / "fixtures" / "contract"
