"""P1-7 - the text projection and heading extraction (D18).

The shared cases in ``fixtures/projection/cases.json`` are the specification; the frontend suite
runs the same file against its mirror. The tests here add what only the server can check: the
rejections, and the properties the shared cases imply but do not state.
"""

from __future__ import annotations

from typing import Any

import pytest

from archetype.manuscript.projection import (
    BLOCK_SEPARATOR,
    MAX_DEPTH,
    SCENE_BREAK,
    InvalidDocumentError,
    count_words,
    empty_document,
    project,
    validate_document,
)

from .conftest import load_projection_cases

CASES = load_projection_cases()
CASE_IDS = [case["name"] for case in CASES]


# -- the shared specification ---------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_shared_case(case: dict[str, Any]) -> None:
    projection = project(case["doc"])

    assert projection.text_plain == case["text_plain"]
    assert projection.headings_as_dicts() == case["headings"]
    assert projection.word_count == case["word_count"]


def test_the_shared_cases_cover_what_the_plan_asks_for() -> None:
    """A guard on the fixture set itself, so coverage cannot quietly erode.

    P1-7 names nesting, empty documents, marks inside headings, blockquotes, lists, and scene
    breaks. If a case is dropped, this fails rather than the suite silently getting weaker.
    """
    names = " ".join(CASE_IDS)
    for required in ("empty", "nesting", "marks inside a heading", "blockquote", "list", "scene"):
        assert required in names, f"the shared projection cases no longer cover {required!r}"


# -- properties the cases imply ---------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_block_never_contains_a_blank_line(case: dict[str, Any]) -> None:
    """The invariant chunking will rely on in Phase 5: a blank line means a block boundary."""
    for block in project(case["doc"]).text_plain.split(BLOCK_SEPARATOR):
        assert block == block.strip()
        assert "\n\n" not in block


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_heading_ordinals_are_dense_and_in_document_order(case: dict[str, Any]) -> None:
    headings = project(case["doc"]).headings
    assert [heading.ordinal for heading in headings] == list(range(len(headings)))


def test_an_empty_document_is_empty() -> None:
    projection = project(empty_document())
    assert projection.text_plain == ""
    assert projection.headings == ()
    assert projection.word_count == 0


def test_empty_document_returns_a_fresh_copy_each_time() -> None:
    """Callers mutate what they get - a shared default would leak between documents."""
    first = empty_document()
    first["content"].append({"type": "paragraph"})
    assert len(empty_document()["content"]) == 1


def test_a_scene_break_is_visible_in_the_text_and_costs_no_words() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Before."}]},
            {"type": "horizontalRule"},
            {"type": "paragraph", "content": [{"type": "text", "text": "After."}]},
        ],
    }
    projection = project(document)
    assert SCENE_BREAK in projection.text_plain.split(BLOCK_SEPARATOR)
    assert projection.word_count == 2


# -- word counting --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("   ", 0),
        ("word", 1),
        ("two words", 2),
        ("don't", 1),
        ("don’t", 1),
        ("well-known", 1),
        ("mother-in-law", 1),
        ("* * *", 0),
        ("--", 0),
        ("...", 0),
        ("—", 0),
        ("1984", 1),
        ("café naïve", 2),
        ("line\nline", 2),
        ("hyphen- ", 1),
    ],
)
def test_count_words(text: str, expected: int) -> None:
    assert count_words(text) == expected


# -- rejections -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        None,
        "a string",
        42,
        [],
        {},
        {"type": "paragraph"},
        {"type": "doc", "content": "not a list"},
        {"type": "doc", "content": [None]},
        {"type": "doc", "content": ["a string"]},
        {"type": "doc", "content": [{"no": "type"}]},
        {"type": "doc", "content": [{"type": ""}]},
        {"type": "doc", "content": [{"type": 7}]},
        {"type": "doc", "content": [{"type": "paragraph", "attrs": []}]},
        {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text"}]}]},
        {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": 7}]}],
        },
    ],
)
def test_a_malformed_document_is_rejected(value: Any) -> None:
    with pytest.raises(InvalidDocumentError):
        project(value)


def test_the_rejection_message_names_where_the_problem_is() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph"},
            {"type": "blockquote", "content": [{"type": "paragraph", "content": "no"}]},
        ],
    }
    with pytest.raises(
        InvalidDocumentError, match=r"doc\.content\[1\]\(blockquote\)\.content\[0\]"
    ):
        project(document)


def test_nesting_past_the_limit_is_rejected_rather_than_recursed() -> None:
    node: dict[str, Any] = {"type": "paragraph", "content": [{"type": "text", "text": "deep"}]}
    for _ in range(MAX_DEPTH + 2):
        node = {"type": "blockquote", "content": [node]}
    document = {"type": "doc", "content": [node]}

    with pytest.raises(InvalidDocumentError, match="nests deeper"):
        validate_document(document)


def test_nesting_inside_the_limit_is_fine() -> None:
    node: dict[str, Any] = {"type": "paragraph", "content": [{"type": "text", "text": "deep"}]}
    for _ in range(MAX_DEPTH - 4):
        node = {"type": "blockquote", "content": [node]}

    assert project({"type": "doc", "content": [node]}).text_plain == "deep"
