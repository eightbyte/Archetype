"""The three Markdown routes over the real application (P2-13, P2-14).

The serializer and the parser have their own tests, and the corpus is where fidelity is
asserted. What is left for HTTP is what only HTTP can get wrong: the media type and the
disposition on the one non-JSON response in the API, the soft-delete predicate on a read that
loads the whole manuscript, and the refusals - a mode that is not a mode, a file too large, a
chapter too large, and the promise that a refused import created nothing.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from archetype.manuscript.markdown.importer import MAX_IMPORT_BYTES

from .conftest import build_document


def make_project(client: TestClient, title: str = "The Long Road") -> tuple[str, str]:
    """A project and its seeded first chapter."""
    created = client.post("/api/projects", json={"title": title}).json()
    return created["project"]["id"], created["documents"][0]["id"]


def write(client: TestClient, document_id: str, content: dict[str, Any], version: int = 1) -> int:
    response = client.put(
        f"/api/documents/{document_id}/content",
        json={"content_json": content, "version": version},
    )
    assert response.status_code == 200, response.text
    return response.json()["version"]


PROSE = build_document(headings=[(1, "Arrival")], paragraphs=["The harbour was grey."])


# -- exporting one chapter ---------------------------------------------------------------------


def test_a_chapter_exports_as_a_markdown_file(client: TestClient) -> None:
    _, document_id = make_project(client)
    write(client, document_id, PROSE)

    response = client.get(f"/api/documents/{document_id}/markdown")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text == "# Arrival\n\nThe harbour was grey.\n"


def test_the_export_is_named_after_the_chapter(client: TestClient) -> None:
    """The title is not in the body - it travels here, so the round trip stays exact."""
    project_id, _ = make_project(client)
    document = client.post(
        f"/api/projects/{project_id}/documents", json={"title": "Departure"}
    ).json()

    response = client.get(f"/api/documents/{document['id']}/markdown")

    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="Departure.md"')
    assert "filename*=UTF-8''Departure.md" in disposition
    assert "Departure" not in response.text


def test_a_title_a_filesystem_would_refuse_still_downloads(client: TestClient) -> None:
    project_id, _ = make_project(client)
    document = client.post(
        f"/api/projects/{project_id}/documents", json={"title": 'A/B: "quoted"; part 2'}
    ).json()

    disposition = client.get(f"/api/documents/{document['id']}/markdown").headers[
        "content-disposition"
    ]

    assert 'filename="A-B-quoted-part 2.md"' in disposition


def test_a_title_with_no_ascii_in_it_still_gets_a_usable_name(client: TestClient) -> None:
    """Both names are given, so a browser that reads neither still saves something findable."""
    project_id, _ = make_project(client)
    document = client.post(f"/api/projects/{project_id}/documents", json={"title": "出発"}).json()

    disposition = client.get(f"/api/documents/{document['id']}/markdown").headers[
        "content-disposition"
    ]

    assert 'filename="__.md"' in disposition
    assert "filename*=UTF-8''%E5%87%BA%E7%99%BA.md" in disposition


def test_an_empty_chapter_exports_as_an_empty_file(client: TestClient) -> None:
    _, document_id = make_project(client)

    response = client.get(f"/api/documents/{document_id}/markdown")

    assert response.status_code == 200
    assert response.text == ""


def test_exporting_a_chapter_that_is_not_there(client: TestClient) -> None:
    response = client.get("/api/documents/doc_doesnotexist/markdown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


def test_exporting_a_deleted_chapter_is_a_404_like_every_other_read(client: TestClient) -> None:
    project_id, first = make_project(client)
    second = client.post(f"/api/projects/{project_id}/documents", json={"title": "Gone"}).json()
    assert client.delete(f"/api/documents/{second['id']}").status_code == 200

    assert client.get(f"/api/documents/{second['id']}/markdown").status_code == 404
    assert client.get(f"/api/documents/{first}/markdown").status_code == 200


# -- exporting the whole manuscript -------------------------------------------------------------


def test_the_combined_export_holds_every_chapter_in_order_under_its_title(
    client: TestClient,
) -> None:
    project_id, first = make_project(client)
    write(client, first, build_document(paragraphs=["The harbour was grey."]))
    second = client.post(f"/api/projects/{project_id}/documents", json={"title": "Away"}).json()
    write(client, second["id"], build_document(paragraphs=["He did not look back."]))

    response = client.get(f"/api/projects/{project_id}/markdown")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text == (
        "# Chapter 1\n\nThe harbour was grey.\n\n# Away\n\nHe did not look back.\n"
    )


def test_the_combined_export_follows_a_reorder(client: TestClient) -> None:
    project_id, first = make_project(client)
    second = client.post(f"/api/projects/{project_id}/documents", json={"title": "Away"}).json()
    client.put(
        f"/api/projects/{project_id}/documents/order",
        json={"document_ids": [second["id"], first]},
    )

    body = client.get(f"/api/projects/{project_id}/markdown").text

    assert body.index("# Away") < body.index("# Chapter 1")


def test_a_deleted_chapter_is_not_in_the_combined_export(client: TestClient) -> None:
    """The leak the phase plan's risk table names: one query that forgets the predicate.

    It would surface as a ghost chapter in a file somebody sent to a reader, which is reported
    as a different bug entirely - so it is asserted where the query is, not only where the
    predicate is.
    """
    project_id, _ = make_project(client)
    doomed = client.post(f"/api/projects/{project_id}/documents", json={"title": "Cut"}).json()
    write(client, doomed["id"], build_document(paragraphs=["This chapter was cut."]))

    assert "This chapter was cut." in client.get(f"/api/projects/{project_id}/markdown").text
    client.delete(f"/api/documents/{doomed['id']}")

    body = client.get(f"/api/projects/{project_id}/markdown").text
    assert "This chapter was cut." not in body
    assert "# Cut" not in body


def test_the_combined_export_is_named_after_the_project(client: TestClient) -> None:
    project_id, _ = make_project(client, "The Long Road")

    disposition = client.get(f"/api/projects/{project_id}/markdown").headers["content-disposition"]

    assert 'filename="The Long Road.md"' in disposition


def test_exporting_a_project_that_is_not_there(client: TestClient) -> None:
    response = client.get("/api/projects/prj_doesnotexist/markdown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


# -- importing -----------------------------------------------------------------------------------


def test_an_import_appends_chapters_at_the_end(client: TestClient) -> None:
    project_id, first = make_project(client)

    response = client.post(
        f"/api/projects/{project_id}/import",
        json={"markdown": "# One\n\nalpha\n\n# Two\n\nbeta\n", "mode": "split-on-h1"},
    )

    assert response.status_code == 201
    assert [document["title"] for document in response.json()["documents"]] == ["One", "Two"]
    listed = client.get(f"/api/projects/{project_id}/documents").json()["documents"]
    assert [document["id"] for document in listed][0] == first
    assert [document["title"] for document in listed] == ["Chapter 1", "One", "Two"]


def test_an_import_replaces_nothing(client: TestClient) -> None:
    """Ruling 5, as an assertion: ``save_content`` stays the only path that changes text."""
    project_id, first = make_project(client)
    version = write(client, first, build_document(paragraphs=["The words already here."]))

    client.post(
        f"/api/projects/{project_id}/import",
        json={"markdown": "Something else entirely.\n"},
    )

    unchanged = client.get(f"/api/documents/{first}").json()
    assert unchanged["version"] == version
    assert unchanged["content_json"] == build_document(paragraphs=["The words already here."])


def test_one_chapter_mode_takes_a_title(client: TestClient) -> None:
    project_id, _ = make_project(client)

    response = client.post(
        f"/api/projects/{project_id}/import",
        json={"markdown": "text\n", "mode": "one-chapter", "title": "Handed a name"},
    )

    assert [document["title"] for document in response.json()["documents"]] == ["Handed a name"]


def test_an_import_with_no_title_is_named_the_way_a_new_chapter_is(client: TestClient) -> None:
    project_id, _ = make_project(client)

    response = client.post(f"/api/projects/{project_id}/import", json={"markdown": "text\n"})

    assert [document["title"] for document in response.json()["documents"]] == ["Chapter 2"]


def test_an_import_reports_what_it_could_not_keep(client: TestClient) -> None:
    project_id, _ = make_project(client)

    response = client.post(
        f"/api/projects/{project_id}/import",
        json={"markdown": "before\n\n```py\nx = 1\n```\n\nSee [the map](http://x/y).\n"},
    )

    dropped = response.json()["dropped"]
    assert [item["element"] for item in dropped] == ["code fence", "link"]
    assert dropped[0]["line"] == 3
    assert all(item["detail"] for item in dropped)


def test_an_ordinary_import_reports_nothing(client: TestClient) -> None:
    project_id, _ = make_project(client)

    response = client.post(
        f"/api/projects/{project_id}/import", json={"markdown": "# One\n\nalpha\n"}
    )

    assert response.json()["dropped"] == []


def test_a_chapter_exported_and_imported_is_the_same_document(client: TestClient) -> None:
    """The phase's sixth exit criterion, end to end, over HTTP rather than over the corpus."""
    project_id, first = make_project(client)
    write(client, first, PROSE)
    markdown = client.get(f"/api/documents/{first}/markdown").text

    created = client.post(f"/api/projects/{project_id}/import", json={"markdown": markdown}).json()[
        "documents"
    ][0]

    assert client.get(f"/api/documents/{created['id']}").json()["content_json"] == PROSE


def test_a_mode_that_is_not_a_mode_is_refused_at_the_wire(client: TestClient) -> None:
    project_id, _ = make_project(client)

    response = client.post(
        f"/api/projects/{project_id}/import", json={"markdown": "x", "mode": "split-on-h2"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_an_undeclared_field_is_refused_like_every_other_request(client: TestClient) -> None:
    project_id, _ = make_project(client)

    response = client.post(
        f"/api/projects/{project_id}/import", json={"markdown": "x", "replace": True}
    )

    assert response.status_code == 422


def test_a_file_too_large_to_read_is_refused_before_anything_is_created(
    client: TestClient,
) -> None:
    project_id, _ = make_project(client)

    response = client.post(
        f"/api/projects/{project_id}/import", json={"markdown": "x" * (MAX_IMPORT_BYTES + 1)}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert len(client.get(f"/api/projects/{project_id}/documents").json()["documents"]) == 1


def test_a_chapter_too_large_to_store_takes_the_whole_import_with_it(client: TestClient) -> None:
    """P2-14 says "refused before anything is created", and a partial import is worse than none.

    The file is under the import limit and the *second* chapter is over the per-chapter one, so
    the first chapter would have been written by an importer that created as it went.
    """
    project_id, _ = make_project(client)
    huge = "word " * 500_000
    markdown = f"# One\n\nsmall\n\n# Two\n\n{huge}\n"

    response = client.post(
        f"/api/projects/{project_id}/import", json={"markdown": markdown, "mode": "split-on-h1"}
    )

    assert response.status_code == 413
    assert len(client.get(f"/api/projects/{project_id}/documents").json()["documents"]) == 1


def test_importing_into_a_project_that_is_not_there(client: TestClient) -> None:
    response = client.post("/api/projects/prj_doesnotexist/import", json={"markdown": "x"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_a_plain_text_file_imports_as_prose(client: TestClient) -> None:
    """A writer will drop one in, and it is valid Markdown, so it must not be an error."""
    project_id, _ = make_project(client)

    response = client.post(
        f"/api/projects/{project_id}/import",
        json={"markdown": "Just some prose,\nwrapped over two lines.\n"},
    )

    assert response.status_code == 201
    assert response.json()["dropped"] == []
    assert response.json()["documents"][0]["word_count"] == 7


def test_an_empty_file_imports_as_an_empty_chapter(client: TestClient) -> None:
    project_id, _ = make_project(client)

    response = client.post(f"/api/projects/{project_id}/import", json={"markdown": ""})

    assert response.status_code == 201
    created = response.json()["documents"][0]
    assert created["word_count"] == 0
    assert client.get(f"/api/documents/{created['id']}").json()["content_json"] == {
        "type": "doc",
        "content": [{"type": "paragraph"}],
    }


def test_the_whole_manuscript_round_trips_through_the_split_mode(client: TestClient) -> None:
    """No fidelity is promised for the combined file (ruling 4); the chapter *titles* are."""
    project_id, first = make_project(client)
    write(client, first, build_document(paragraphs=["The harbour was grey."]))
    second = client.post(f"/api/projects/{project_id}/documents", json={"title": "Away"}).json()
    write(client, second["id"], build_document(paragraphs=["He did not look back."]))
    markdown = client.get(f"/api/projects/{project_id}/markdown").text

    response = client.post(
        f"/api/projects/{project_id}/import",
        json={"markdown": markdown, "mode": "split-on-h1"},
    )

    assert [document["title"] for document in response.json()["documents"]] == [
        "Chapter 1",
        "Away",
    ]
