"""Markdown export and import (P2-13, P2-14, D15).

Three kinds of test, and the order matters.

**The corpus** is the acceptance bar. Every case states a chapter twice - as ProseMirror JSON and
as the Markdown it must export to - and both directions are asserted against it. Asserting the
Markdown itself, rather than only that a document survives a round trip, is what keeps the two
halves from agreeing with each other on a syntax nobody chose.

**Totality** is asserted against the shared closed-schema fixture, not against the serializer's
own idea of the schema. A node added to the editor and not taught here fails on both sides of the
wire in the commit that adds it.

**The normalisations** - the three places Markdown cannot hold what the schema can, and the two
places import tidies what a person wrote - are each asserted directly, because a limit that is
only described is a limit nobody has checked.
"""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

import pytest
from markdown_it import MarkdownIt

from archetype.manuscript.markdown import (
    IMPORT_MODES,
    ImportMode,
    UnknownMarkError,
    UnknownNodeError,
    chapters_to_markdown,
    document_to_markdown,
    read_manuscript,
)
from archetype.manuscript.markdown.schema import ALLOWED_MARKS, ALLOWED_NODES, ATTR_DEFAULTS
from archetype.manuscript.markdown.serialize import HANDLED_NODES
from archetype.manuscript.projection import project

from .conftest import load_closed_schema, load_markdown_cases

CASES = load_markdown_cases()
CASE_IDS = [case["name"] for case in CASES]


def imported(markdown: str, **kwargs: Any) -> dict[str, Any]:
    """The single chapter a one-chapter import produces."""
    return read_manuscript(markdown, **kwargs).chapters[0].content


# -- the corpus, both directions --------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_export_writes_the_markdown_the_corpus_states(case: dict[str, Any]) -> None:
    assert document_to_markdown(case["doc"]) == case["markdown"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_import_reads_the_corpus_markdown_back_as_the_document(case: dict[str, Any]) -> None:
    assert imported(case["markdown"]) == case["doc"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_chapter_survives_the_round_trip(case: dict[str, Any]) -> None:
    """The promise itself, stated the way P2-14 states it."""
    assert imported(document_to_markdown(case["doc"])) == case["doc"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_import_reports_nothing_lost_for_a_document_this_schema_wrote(case: dict[str, Any]) -> None:
    """A file the exporter wrote holds nothing the importer has to drop. If it did, the round
    trip above would be passing while quietly telling the writer something went missing."""
    assert read_manuscript(document_to_markdown(case["doc"])).notices == ()


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_any_markdown_reader_sees_the_words_the_chapter_says(case: dict[str, Any]) -> None:
    """Every word of the chapter reaches the file, in order, as *words* and not as syntax.

    The corpus fixes the syntax and the round trip fixes the document; neither would notice a
    chapter exported into a file only this project can read. So the file is rendered by the
    parser's own renderer - nothing of ours - and what a reader would see is compared to
    ``text_plain``, the project's one answer to "what does this chapter say" (P1-7, D18). A
    scene break is dropped from both sides: five characters in ``text_plain``, a horizontal rule
    in the file, and words in neither.
    """
    assert _rendered_text(document_to_markdown(case["doc"])) == _said(case["doc"])


def _rendered_text(markdown: str) -> str:
    """The words a Markdown reader would see, taken from rendered HTML rather than guessed at.

    Emphasis tags close up - ``<em>grey</em>,`` is one word and a comma - and every other tag
    becomes a break, which is what a block boundary is.
    """
    html = MarkdownIt("commonmark", {"html": False}).render(markdown)
    text = re.sub(r"<[^>]*>", "\n", re.sub(r"</?(?:em|strong)>", "", html))
    return " ".join(unescape(text).split())


def _said(document: dict[str, Any]) -> str:
    """What the chapter says, from the projection, with the scene breaks taken out.

    The rules are dropped from the *document*, not from the projected text: a paragraph the
    writer typed as three asterisks projects to the same five characters a scene break does, and
    filtering on the text would quietly excuse the one case that exists to tell them apart.
    """
    without_rules = {
        "type": "doc",
        "content": [
            child for child in document.get("content", []) if child.get("type") != "horizontalRule"
        ],
    }
    return " ".join(project(without_rules).text_plain.split())


# -- totality over the closed schema ----------------------------------------------------------


def test_the_server_mirrors_the_editor_schema() -> None:
    """The mirror is held to the declaration by the shared fixture, not by discipline."""
    declared = load_closed_schema()
    assert list(ALLOWED_NODES) == declared["nodes"]
    assert list(ALLOWED_MARKS) == declared["marks"]
    assert ATTR_DEFAULTS == declared["attr_defaults"]


def test_every_node_in_the_schema_has_a_case_in_the_serializer() -> None:
    """P2-13's own acceptance sentence, as an assertion.

    The set comparison rather than a spot check: a node added to the schema shows up here as a
    failure whether or not anybody thought to write a test for it.
    """
    assert HANDLED_NODES == set(load_closed_schema()["nodes"])


def test_every_mark_in_the_schema_has_a_delimiter() -> None:
    from archetype.manuscript.markdown.serialize import EMPHASIS

    assert set(EMPHASIS) == set(load_closed_schema()["marks"])


def test_a_node_outside_the_schema_is_refused_rather_than_guessed_at() -> None:
    document = {"type": "doc", "content": [{"type": "codeBlock", "content": []}]}
    with pytest.raises(UnknownNodeError):
        document_to_markdown(document)


def test_a_mark_outside_the_schema_is_refused_rather_than_guessed_at() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "marks": [{"type": "strike"}], "text": "gone"}],
            }
        ],
    }
    with pytest.raises(UnknownMarkError):
        document_to_markdown(document)


# -- what Markdown cannot hold ------------------------------------------------------------------


def test_an_empty_paragraph_between_two_blocks_is_dropped() -> None:
    """A blank line is how Markdown separates blocks, so a block made of one cannot survive.

    Stated here rather than left to be discovered: it is the projection's rule too, and it is
    the one thing an exported chapter does not carry back.
    """
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "One."}]},
            {"type": "paragraph"},
            {"type": "paragraph", "content": [{"type": "text", "text": "Two."}]},
        ],
    }
    assert document_to_markdown(document) == "One.\n\nTwo."
    assert imported(document_to_markdown(document)) == {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "One."}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Two."}]},
        ],
    }


def test_a_line_break_inside_a_heading_becomes_a_space() -> None:
    """An ATX heading is one line by definition."""
    document = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [
                    {"type": "text", "text": "Part One"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "Departure"},
                ],
            }
        ],
    }
    assert document_to_markdown(document) == "## Part One Departure"


def test_a_newline_inside_a_text_node_is_a_line_break() -> None:
    """Exactly as the projection reads it. The editor cannot produce one; a payload can."""
    document = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one\ntwo"}]}],
    }
    assert document_to_markdown(document) == "one\\\ntwo"
    assert imported("one\\\ntwo") == {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "one"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "two"},
                ],
            }
        ],
    }


def test_whitespace_at_the_edge_of_an_emphasis_run_moves_outside_it() -> None:
    """``** bold **`` is not emphasis, so the mark gives up the spaces rather than the text."""
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "text", "marks": [{"type": "bold"}], "text": " bold "},
                    {"type": "text", "text": "b"},
                ],
            }
        ],
    }
    markdown = document_to_markdown(document)
    assert markdown == "a **bold** b"
    # Not one character of text is lost - only which of them the mark covers.
    assert project(imported(markdown)).text_plain == project(document).text_plain


# -- import: what it reports --------------------------------------------------------------------


def test_a_code_fence_keeps_its_text_and_reports_the_formatting() -> None:
    result = read_manuscript("before\n\n```py\nx = 1\n```\n")
    assert [notice.element for notice in result.notices] == ["code fence"]
    assert result.notices[0].line == 3
    assert project(result.chapters[0].content).text_plain == "before\n\nx = 1"


def test_an_indented_code_block_is_reported_too() -> None:
    result = read_manuscript("before\n\n    indented\n")
    assert [notice.element for notice in result.notices] == ["indented code block"]


def test_a_link_keeps_its_words_and_reports_its_target() -> None:
    result = read_manuscript("See [the map](http://example.test/x) here.\n")
    assert [notice.element for notice in result.notices] == ["link"]
    assert "http://example.test/x" in result.notices[0].detail
    assert project(result.chapters[0].content).text_plain == "See the map here."


def test_an_image_is_reported_and_leaves_its_alt_text_behind() -> None:
    result = read_manuscript("Look: ![a grey ship](ship.png)\n")
    assert [notice.element for notice in result.notices] == ["image"]
    assert project(result.chapters[0].content).text_plain == "Look: a grey ship"


def test_inline_code_keeps_the_text_and_reports_the_formatting() -> None:
    result = read_manuscript("Type `git status` now.\n")
    assert [notice.element for notice in result.notices] == ["inline code"]
    assert project(result.chapters[0].content).text_plain == "Type git status now."


def test_a_heading_below_the_levels_the_editor_offers_is_taken_down_and_reported() -> None:
    result = read_manuscript("#### four\n")
    assert [notice.element for notice in result.notices] == ["heading level 4"]
    assert result.chapters[0].content["content"][0]["attrs"]["level"] == 3


def test_a_construct_that_is_not_markdown_at_all_arrives_as_prose() -> None:
    """A table, raw HTML and a footnote are not syntax under the strict preset.

    Nothing is dropped, so nothing is reported - which is why the notice list stays a list of
    real losses rather than a mix of those and things that merely looked like one.
    """
    result = read_manuscript("| a | b |\n\n<div>x</div>\n\nA note.[^1]\n")
    assert result.notices == ()
    text = project(result.chapters[0].content).text_plain
    assert "| a | b |" in text
    assert "<div>x</div>" in text
    assert "[^1]" in text


# -- import: reading a file a person wrote ------------------------------------------------------


def test_a_plain_text_file_produces_prose_rather_than_an_error() -> None:
    """P2-14 says so explicitly, because a writer will try one."""
    result = read_manuscript("Just some prose,\nwrapped over two lines.\n\nAnd a second one.\n")
    assert result.notices == ()
    assert project(result.chapters[0].content).text_plain == (
        "Just some prose, wrapped over two lines.\n\nAnd a second one."
    )


def test_an_empty_file_is_an_empty_chapter_rather_than_nothing() -> None:
    """A ProseMirror document is ``block+`` and can never be empty."""
    assert imported("") == {"type": "doc", "content": [{"type": "paragraph"}]}


def test_a_setext_heading_is_a_heading() -> None:
    """The kind of corner the ruling to use a real parser was made for."""
    document = imported("Chapter One\n===========\n\ntext\n")
    assert document["content"][0] == {
        "type": "heading",
        "attrs": {"level": 1},
        "content": [{"type": "text", "text": "Chapter One"}],
    }


def test_runs_carrying_the_same_marks_are_merged_into_one_text_node() -> None:
    """What makes the round trip an equality rather than a rendering that looks the same."""
    document = imported("**one** **two**\n")
    assert document["content"][0]["content"] == [
        {"type": "text", "marks": [{"type": "bold"}], "text": "one"},
        {"type": "text", "text": " "},
        {"type": "text", "marks": [{"type": "bold"}], "text": "two"},
    ]


# -- the two modes ------------------------------------------------------------------------------


def test_one_chapter_keeps_a_leading_heading_in_the_text() -> None:
    """Eating it would be reasonable and would break the round trip, which is the stronger rule."""
    result = read_manuscript("# Departure\n\nThe harbour was grey.\n", mode=ImportMode.ONE_CHAPTER)
    assert len(result.chapters) == 1
    assert result.chapters[0].title is None
    assert result.chapters[0].content["content"][0]["type"] == "heading"


def test_one_chapter_takes_the_title_it_is_given() -> None:
    result = read_manuscript("text\n", mode=ImportMode.ONE_CHAPTER, title="Departure")
    assert result.chapters[0].title == "Departure"


def test_split_on_h1_cuts_at_every_top_level_heading() -> None:
    result = read_manuscript(
        "# One\n\nalpha\n\n# Two\n\nbeta\n\n## Not a chapter\n", mode=ImportMode.SPLIT_ON_H1
    )
    assert [chapter.title for chapter in result.chapters] == ["One", "Two"]
    assert project(result.chapters[0].content).text_plain == "alpha"
    assert project(result.chapters[1].content).text_plain == "beta\n\nNot a chapter"


def test_split_on_h1_gives_text_before_the_first_heading_a_chapter_of_its_own() -> None:
    """Losing it would be silent, and it is usually the front matter of a manuscript."""
    result = read_manuscript("front matter\n\n# One\n\nalpha\n", mode=ImportMode.SPLIT_ON_H1)
    assert [chapter.title for chapter in result.chapters] == [None, "One"]
    assert project(result.chapters[0].content).text_plain == "front matter"


def test_split_on_h1_with_no_heading_at_all_is_one_chapter() -> None:
    result = read_manuscript("just prose\n", mode=ImportMode.SPLIT_ON_H1)
    assert len(result.chapters) == 1
    assert result.chapters[0].title is None


def test_a_heading_too_long_to_be_a_title_is_cut_and_reported() -> None:
    result = read_manuscript(f"# {'a' * 400}\n", mode=ImportMode.SPLIT_ON_H1)
    assert [notice.element for notice in result.notices] == ["chapter title"]
    assert len(result.chapters[0].title or "") == 200


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown import mode"):
        read_manuscript("text", mode="split-on-h2")


def test_the_modes_are_spelled_once() -> None:
    assert IMPORT_MODES == {ImportMode.ONE_CHAPTER, ImportMode.SPLIT_ON_H1}


# -- the combined export ------------------------------------------------------------------------


def test_the_combined_export_precedes_each_chapter_with_its_title() -> None:
    chapters = [
        ("Departure", CASES[1]["doc"]),
        ("Arrival", CASES[2]["doc"]),
    ]
    assert chapters_to_markdown(chapters) == (
        "# Departure\n\nThe harbour was grey.\n\n# Arrival\n\nOne.\n\nTwo."
    )


def test_a_chapter_title_is_escaped_like_any_other_text() -> None:
    """It reaches the file as a heading, so a title of ``* * *`` must not become a scene break."""
    assert chapters_to_markdown([("* * *", {"type": "doc", "content": []})]) == "# \\* \\* \\*"


def test_an_empty_chapter_in_the_combined_export_is_still_a_heading() -> None:
    assert chapters_to_markdown([("Empty", {"type": "doc", "content": []})]) == "# Empty"


def test_the_combined_export_can_be_split_back_into_its_chapters() -> None:
    """No round trip is promised (ruling 4), but the split mode is the reason for the shape."""
    chapters = [("Departure", CASES[1]["doc"]), ("Arrival", CASES[2]["doc"])]
    result = read_manuscript(chapters_to_markdown(chapters), mode=ImportMode.SPLIT_ON_H1)
    assert [chapter.title for chapter in result.chapters] == ["Departure", "Arrival"]
    assert [chapter.content for chapter in result.chapters] == [CASES[1]["doc"], CASES[2]["doc"]]


# -- the combined export's heading levels (D15) ---------------------------------------------------


def _heading(level: int, text: str) -> dict[str, Any]:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [{"type": "text", "text": text}],
    }


def _paragraph(text: str) -> dict[str, Any]:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


#: A chapter that opens with a heading of its own, which is what the section 8 acceptance run was
#: holding when it found D15. The closed schema permits it and a writer will type it.
_OPENS_WITH_A_HEADING: dict[str, Any] = {
    "type": "doc",
    "content": [_heading(1, "This is the start"), _paragraph("Prow scuttle parrel provost.")],
}


def test_the_combined_export_writes_every_body_heading_one_level_down() -> None:
    """Level 1 belongs to the chapter titles there, so the body begins at level 2."""
    assert chapters_to_markdown([("Departure", CASES[3]["doc"])]) == (
        "# Departure\n\n## One\n\n### Two\n\n#### Three"
    )


def test_one_chapter_export_leaves_the_levels_the_writer_chose() -> None:
    """The demotion is the combined export's alone - this one promises a round trip."""
    assert document_to_markdown(CASES[3]["doc"]) == CASES[3]["markdown"]


def test_a_heading_inside_a_chapter_does_not_become_a_chapter() -> None:
    """The section 8 acceptance run's finding, as a test (D15, 2026-09-01).

    Before the demotion this exported two ``#`` lines that no reader could tell apart, so the
    split made three chapters out of two: an empty one under the title, and one whose title was
    a heading from the middle of somebody's prose.
    """
    chapters = [("Chapter 1", _OPENS_WITH_A_HEADING), ("Chapter 2", CASES[1]["doc"])]
    result = read_manuscript(chapters_to_markdown(chapters), mode=ImportMode.SPLIT_ON_H1)

    assert [chapter.title for chapter in result.chapters] == ["Chapter 1", "Chapter 2"]
    # And the heading's own words stayed in the chapter that had them. They are what the run saw
    # leave as a word count four short of the chapter it came from.
    assert (
        project(result.chapters[0].content).word_count == project(_OPENS_WITH_A_HEADING).word_count
    )
    assert result.chapters[0].content["content"][0] == _heading(2, "This is the start")


def test_a_body_heading_at_the_editors_floor_comes_back_at_the_floor_and_says_so() -> None:
    """The cost of the demotion, in the one file that never promised a round trip."""
    chapter = {"type": "doc", "content": [_heading(3, "Deep")]}
    markdown = chapters_to_markdown([("Departure", chapter)])
    assert markdown == "# Departure\n\n#### Deep"

    result = read_manuscript(markdown, mode=ImportMode.SPLIT_ON_H1)
    assert result.chapters[0].content["content"][0] == _heading(3, "Deep")
    assert [notice.element for notice in result.notices] == ["heading level 4"]


def test_the_demotion_reaches_a_heading_inside_a_blockquote() -> None:
    """It travels with the walk, not with the top level: a heading anywhere is subordinate."""
    chapter = {
        "type": "doc",
        "content": [{"type": "blockquote", "content": [_heading(1, "Quoted")]}],
    }
    assert chapters_to_markdown([("Departure", chapter)]) == "# Departure\n\n> ## Quoted"


def test_the_corpus_is_valid_json_and_states_both_halves() -> None:
    """Cheap, and it catches a fixture edited into something the parametrize would skip."""
    assert len(CASES) >= 20
    for case in CASES:
        assert set(case) == {"name", "doc", "markdown"}
        assert json.dumps(case["doc"])
