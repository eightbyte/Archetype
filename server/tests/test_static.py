"""P1-14 - the single-process run mode.

Every test here builds its own miniature ``dist`` in ``tmp_path`` rather than depending on
``npm run build`` having been run, so the suite says the same thing on a machine that has never
touched Node - and so a stale real build cannot make a passing test lie.

What these assert, in order of how much it would hurt to get wrong:

* the API is never shadowed by the mount (a file called ``api`` in a bundle must not be able to
  take the manuscript routes away);
* a save round-trips through the single-process app, which is the P1-14 acceptance bar;
* a clone that has not been built still starts, and says why the root is empty.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archetype.api.static import INDEX_FILE
from archetype.app import create_app
from archetype.config import Settings

INDEX_HTML = (
    '<!doctype html><html lang="en"><head><title>Archetype</title>'
    '<script type="module" src="/assets/index-abc123.js"></script></head>'
    '<body><div id="root"></div></body></html>'
)
ASSET_JS = "export const built = true;\n"
ASSET_NAME = "index-abc123.js"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A directory shaped like the one Vite writes: an index plus a fingerprinted asset."""
    directory = tmp_path / "dist"
    (directory / "assets").mkdir(parents=True)
    # Bytes, not text: on Windows write_text rewrites newlines as CRLF, which a bundler
    # does not, and the assertions below compare the wire against what went onto disk.
    (directory / INDEX_FILE).write_bytes(INDEX_HTML.encode("utf-8"))
    (directory / "assets" / ASSET_NAME).write_bytes(ASSET_JS.encode("utf-8"))
    return directory


@pytest.fixture
def served(data_dir: Path, dist: Path) -> Iterator[TestClient]:
    """The app with the bundle mounted - the single-process mode."""
    app = create_app(Settings(data_dir=data_dir, web_dist=dist))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def unbuilt(data_dir: Path, tmp_path: Path) -> Iterator[TestClient]:
    """The app pointed at a directory nobody has built - a fresh clone."""
    app = create_app(Settings(data_dir=data_dir, web_dist=tmp_path / "never-built"))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# -- serving the bundle ---------------------------------------------------------------------


def test_the_built_app_is_served_at_the_root(served: TestClient) -> None:
    response = served.get("/")

    assert response.status_code == 200
    assert response.text == INDEX_HTML
    assert response.headers["content-type"].startswith("text/html")


def test_index_html_is_revalidated_rather_than_cached(served: TestClient) -> None:
    # index.html is the one file whose name never changes and whose contents do on every build.
    # Cached, it would go on loading the previous build's scripts after an upgrade.
    response = served.get("/")

    assert response.headers["cache-control"] == "no-cache"
    assert response.headers.get("etag")  # so revalidation is a 304, not a re-download


def test_a_fingerprinted_asset_is_served(served: TestClient) -> None:
    response = served.get(f"/assets/{ASSET_NAME}")

    assert response.status_code == 200
    assert response.text == ASSET_JS
    # Fingerprinted names are safe to cache; only the index is held back.
    assert response.headers.get("cache-control") is None


def test_the_app_records_that_it_mounted_a_bundle(served: TestClient) -> None:
    assert served.app.state.web_mounted is True


# -- the API is not shadowed ----------------------------------------------------------------


def test_the_api_still_answers_with_a_bundle_mounted(served: TestClient) -> None:
    assert served.get("/api/health").json()["status"] == "ok"
    assert served.get("/api/projects").json() == {"projects": [], "skipped": []}


def test_a_bundle_cannot_take_an_api_route_away(served: TestClient, dist: Path) -> None:
    # A bundle holding a file at api/health must lose to the route of the same name: the mount
    # is registered last and Starlette matches routes in order.
    (dist / "api").mkdir()
    (dist / "api" / "health").write_text("not the api", encoding="utf-8")

    response = served.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_an_unknown_api_path_is_still_the_error_envelope(served: TestClient) -> None:
    # It falls through to the mount, finds nothing, and must come back as JSON - not as the
    # single-page app, which would turn a typo'd route into a blank screen.
    response = served.get("/api/no-such-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_missing_asset_says_it_is_missing(served: TestClient) -> None:
    response = served.get("/assets/index-deadbeef.js")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_the_generated_documentation_still_serves(served: TestClient) -> None:
    assert served.get("/openapi.json").status_code == 200
    assert served.get("/docs").status_code == 200


# -- the acceptance bar: the built app loads and saves through one process ------------------


def test_a_manuscript_round_trips_through_the_single_process_app(served: TestClient) -> None:
    """Create, read, save, and re-read - all on the port that is also serving the bundle."""
    created = served.post("/api/projects", json={"title": "Single Process"})
    assert created.status_code == 201
    project = created.json()
    document_id = project["documents"][0]["id"]

    loaded = served.get(f"/api/documents/{document_id}").json()
    assert loaded["version"] == 1

    content = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "One"}],
            },
            {"type": "paragraph", "content": [{"type": "text", "text": "The harbour was grey."}]},
        ],
    }
    saved = served.put(
        f"/api/documents/{document_id}/content",
        json={"content_json": content, "version": loaded["version"]},
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == 2
    assert saved.json()["word_count"] == 5

    reloaded = served.get(f"/api/documents/{document_id}").json()
    assert reloaded["content_json"] == content
    assert reloaded["headings"] == [{"level": 1, "text": "One", "ordinal": 0}]

    # And the page that would have loaded it is coming off the same process.
    assert served.get("/").status_code == 200


# -- a clone that has not been built --------------------------------------------------------


def test_an_unbuilt_clone_still_serves_its_api(unbuilt: TestClient) -> None:
    assert unbuilt.get("/api/health").json()["status"] == "ok"
    assert unbuilt.app.state.web_mounted is False


def test_an_unbuilt_root_says_what_to_do_about_it(unbuilt: TestClient) -> None:
    response = unbuilt.get("/")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "web_not_built"
    assert INDEX_FILE in error["detail"]["reason"]
    assert "npm run build" in error["detail"]["remedy"]


def test_a_directory_without_an_index_is_not_mounted(data_dir: Path, tmp_path: Path) -> None:
    # An empty or half-written directory is not a build. Mounting one would serve 404s from a
    # path that looks like it is working.
    empty = tmp_path / "empty-dist"
    empty.mkdir()
    app = create_app(Settings(data_dir=data_dir, web_dist=empty))

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.app.state.web_mounted is False
        assert client.get("/").json()["error"]["code"] == "web_not_built"


def test_the_mount_can_be_switched_off_entirely(data_dir: Path, dist: Path) -> None:
    # ARCHETYPE_WEB_DIST= - a built bundle on disk is ignored because the setting says so.
    app = create_app(Settings(data_dir=data_dir, web_dist=None))

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.app.state.web_mounted is False
        error = client.get("/").json()["error"]
        assert error["code"] == "web_not_built"
        assert "switched off" in error["detail"]["reason"]


def test_the_not_built_notice_stays_out_of_the_openapi_schema(unbuilt: TestClient) -> None:
    # It is a diagnostic for a person who opened the wrong port, not part of the contract.
    schema = json.loads(unbuilt.get("/openapi.json").text)
    assert "/" not in schema["paths"]
