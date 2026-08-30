"""P1-13 - structured request logging, and what a failure does and does not reveal."""

from __future__ import annotations

import logging
import re

import pytest
from fastapi.testclient import TestClient

from archetype.api.logging import REQUEST_ID_LENGTH
from archetype.ids import ALPHABET
from archetype.projects.store import ProjectStore

REQUEST_LOGGER = "archetype.request"

_FIELDS = re.compile(
    r"request_id=(?P<request_id>\S+) method=(?P<method>\S+) path=(?P<path>\S+) "
    r"status=(?P<status>\d+) duration_ms=(?P<duration_ms>[\d.]+)"
)


def request_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == REQUEST_LOGGER]


def only_line(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    lines = request_lines(caplog)
    assert len(lines) == 1, f"expected one request line, got {[r.getMessage() for r in lines]}"
    return lines[0]


def test_a_request_is_logged_once_with_its_outcome(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        client.get("/api/health")

    record = only_line(caplog)
    fields = _FIELDS.search(record.getMessage())
    assert fields is not None, record.getMessage()
    assert fields["method"] == "GET"
    assert fields["path"] == "/api/health"
    assert fields["status"] == "200"
    assert float(fields["duration_ms"]) >= 0.0


def test_the_fields_are_also_attached_for_a_structured_formatter(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        client.get("/api/health")

    record = only_line(caplog)
    assert record.method == "GET"
    assert record.path == "/api/health"
    assert record.status == 200
    assert isinstance(record.duration_ms, float)


def test_a_request_id_is_a_short_token_and_differs_per_request(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        client.get("/api/health")
        client.get("/api/health")

    ids = [_FIELDS.search(record.getMessage())["request_id"] for record in request_lines(caplog)]
    assert len(ids) == 2
    assert ids[0] != ids[1]
    for request_id in ids:
        assert len(request_id) == REQUEST_ID_LENGTH
        assert set(request_id) <= set(ALPHABET)


def test_a_client_error_is_a_warning_not_an_error(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        client.get("/api/projects/prj_nope")

    record = only_line(caplog)
    assert record.levelno == logging.WARNING
    assert record.status == 404


def test_an_unhandled_exception_logs_the_traceback_server_side(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(self) -> None:
        raise RuntimeError("the disk caught fire")

    monkeypatch.setattr(ProjectStore, "scan", explode)

    with caplog.at_level(logging.INFO):
        response = client.get("/api/projects")

    assert response.status_code == 500
    record = only_line(caplog)
    assert record.levelno == logging.ERROR
    assert record.status == 500
    assert record.exc_info is not None
    assert "the disk caught fire" in caplog.text
    assert "Traceback" in caplog.text
    # ... and none of it crossed to the browser.
    assert "disk caught fire" not in response.text
    assert "Traceback" not in response.text


def test_a_500_carries_the_request_id_that_finds_its_traceback(
    client: TestClient, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(self) -> None:
        raise RuntimeError("the disk caught fire")

    monkeypatch.setattr(ProjectStore, "scan", explode)

    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        response = client.get("/api/projects")

    logged = _FIELDS.search(only_line(caplog).getMessage())["request_id"]
    assert response.json()["error"]["detail"] == {"request_id": logged}


def test_a_successful_response_carries_no_request_id(client: TestClient) -> None:
    """The id is a debugging aid on failure, not a header on every answer."""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert "request_id" not in response.text
