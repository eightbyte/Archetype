"""P2-5 - the block index and the two conversions between the coordinate systems.

``specs/anchors.md`` section 2 is the specification. The shared projection cases carry a
hand-derived ``blocks`` key, so the index is asserted against the same file that fixes
``text_plain`` - one specification, seen twice.

What only these tests can check is the part the fixture cannot state: that the two conversions
are inverses wherever an anchor may live, and that they refuse - rather than guess - everywhere
else. An index that is *plausible* is exactly as dangerous as a resolver that is plausible.
"""

from __future__ import annotations

from typing import Any

import pytest

from archetype.manuscript.projection import (
    BLOCK_SEPARATOR,
    SCENE_BREAK,
    Projection,
    pm_range_to_text_span,
    project,
    text_offset_to_pm_position,
)

from .conftest import load_projection_cases

CASES = load_projection_cases()
CASE_IDS = [case["name"] for case in CASES]


def paragraphs(*texts: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}] if text else []}
            for text in texts
        ],
    }


def mappable_offsets(projection: Projection) -> list[int]:
    """Every ``text_plain`` offset an anchor may name, ends included."""
    offsets: list[int] = []
    for block in projection.blocks:
        if block.mappable:
            offsets.extend(range(block.text_from, block.text_to + 1))
    return sorted(set(offsets))


# -- the shared specification ---------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_shared_case_block_index(case: dict[str, Any]) -> None:
    assert project(case["doc"]).blocks_as_dicts() == case["blocks"]


def test_every_shared_case_states_its_index() -> None:
    """A case added without a ``blocks`` key would be silently exempt from all of this."""
    missing = [case["name"] for case in CASES if "blocks" not in case]
    assert missing == []


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_the_index_describes_the_text_it_indexes(case: dict[str, Any]) -> None:
    """The one failure that would make every anchor in a project wrong at once."""
    projection = project(case["doc"])
    text = projection.text_plain

    previous_end = 0
    for block in projection.blocks:
        assert 0 <= block.text_from <= block.text_to <= len(text)
        assert block.text_from >= previous_end
        previous_end = block.text_to
        assert block.pm_from <= block.pm_to
        if block.mappable:
            # A mappable block is linear: its content spans the same number of positions as
            # the untrimmed text it holds.
            assert block.pm_to - block.pm_from == len(block.raw)
            assert BLOCK_SEPARATOR not in text[block.text_from : block.text_to]

    emitted = [
        text[block.text_from : block.text_to]
        for block in projection.blocks
        if block.text_to > block.text_from
    ]
    assert BLOCK_SEPARATOR.join(emitted) == text


# -- the two conversions ----------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_every_mappable_offset_round_trips(case: dict[str, Any]) -> None:
    """The property P2-5 is for: the conversions are inverses wherever an anchor may live."""
    projection = project(case["doc"])

    for offset in mappable_offsets(projection):
        position = text_offset_to_pm_position(projection, offset)
        assert position is not None, offset
        span = pm_range_to_text_span(projection, position, position)
        assert span == (offset, offset), (offset, position, span)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_every_mappable_range_round_trips(case: dict[str, Any]) -> None:
    """Not just the ends: a range over real text comes back as the same characters."""
    projection = project(case["doc"])
    offsets = mappable_offsets(projection)

    for start in offsets:
        for end in offsets:
            if end < start:
                continue
            from_pos = text_offset_to_pm_position(projection, start)
            to_pos = text_offset_to_pm_position(projection, end)
            assert from_pos is not None and to_pos is not None
            span = pm_range_to_text_span(projection, from_pos, to_pos)
            if span is None:
                # Only a range across a scene break may be refused.
                assert SCENE_BREAK in projection.text_plain[start:end]
                continue
            assert projection.text_plain[span[0] : span[1]] == projection.text_plain[start:end]


def test_a_position_is_the_content_of_its_block_not_the_node() -> None:
    """Two paragraphs are two positions apart; the same two are two characters apart."""
    projection = project(paragraphs("One.", "Two."))
    first, second = projection.blocks

    assert (first.pm_from, first.pm_to) == (1, 5)
    assert (second.pm_from, second.pm_to) == (7, 11)
    assert second.pm_from - first.pm_to == 2
    assert second.text_from - first.text_to == len(BLOCK_SEPARATOR)


def test_a_paragraph_closing_a_blockquote_is_three_positions_from_the_next() -> None:
    """The reason the two spaces cannot be related by arithmetic (anchors.md section 2)."""
    document = {
        "type": "doc",
        "content": [
            {
                "type": "blockquote",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Inside."}]}
                ],
            },
            {"type": "paragraph", "content": [{"type": "text", "text": "After."}]},
        ],
    }
    inside, after = project(document).blocks

    assert after.pm_from - inside.pm_to == 3
    assert after.text_from - inside.text_to == 2


def test_a_blockquoted_list_is_walked_to_its_paragraphs() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "blockquote",
                "content": [
                    {
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "Salt."}],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    projection = project(document)
    (block,) = projection.blocks

    # doc > blockquote > bulletList > listItem > paragraph: four opens before the content.
    assert (block.pm_from, block.pm_to) == (4, 9)
    assert (block.text_from, block.text_to) == (0, 5)
    assert text_offset_to_pm_position(projection, 0) == 4


def test_a_hard_break_is_one_position_and_one_newline() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Roses"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "violets"},
                ],
            }
        ],
    }
    projection = project(document)
    (block,) = projection.blocks

    assert projection.text_plain == "Roses\nviolets"
    assert block.pm_to - block.pm_from == len(projection.text_plain)
    assert text_offset_to_pm_position(projection, 6) == block.pm_from + 6


def test_an_offset_in_the_separator_reads_as_the_end_of_the_preceding_block() -> None:
    """Never the start of the following one, so a range cannot straddle a boundary."""
    projection = project(paragraphs("One.", "Two."))
    first = projection.blocks[0]

    assert text_offset_to_pm_position(projection, 4) == first.pm_to
    assert text_offset_to_pm_position(projection, 5) == first.pm_to


def test_an_empty_block_takes_a_zero_length_entry_and_is_not_mappable() -> None:
    projection = project(paragraphs("One.", "", "Two."))
    first, empty, last = projection.blocks

    assert (empty.text_from, empty.text_to) == (4, 4)
    assert empty.mappable is False
    assert projection.text_plain == "One.\n\nTwo."
    # The positions on either side of it still convert.
    assert text_offset_to_pm_position(projection, 4) == first.pm_to
    assert text_offset_to_pm_position(projection, 6) == last.pm_from


def test_a_position_inside_an_empty_block_reads_as_the_text_around_it() -> None:
    projection = project(paragraphs("One.", "", "Two."))
    _, empty, last = projection.blocks

    # As a range start it snaps forward to real text; as an end, backward.
    assert pm_range_to_text_span(projection, empty.pm_from, last.pm_to) == (6, 10)
    assert pm_range_to_text_span(projection, 0, empty.pm_to) == (0, 4)


# -- what has no honest answer ---------------------------------------------------------------


def test_an_offset_inside_a_scene_break_has_no_position() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Before."}]},
            {"type": "horizontalRule"},
            {"type": "paragraph", "content": [{"type": "text", "text": "After."}]},
        ],
    }
    projection = project(document)
    start = projection.text_plain.index(SCENE_BREAK)

    for offset in range(start, start + len(SCENE_BREAK) + 1):
        assert text_offset_to_pm_position(projection, offset) is None


def test_a_range_that_spans_a_scene_break_is_refused() -> None:
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Before."}]},
            {"type": "horizontalRule"},
            {"type": "paragraph", "content": [{"type": "text", "text": "After."}]},
        ],
    }
    projection = project(document)
    before, rule, after = projection.blocks

    assert pm_range_to_text_span(projection, before.pm_from, after.pm_to) is None
    assert pm_range_to_text_span(projection, rule.pm_from, rule.pm_to) is None
    # Either side of it on its own is fine.
    assert pm_range_to_text_span(projection, before.pm_from, before.pm_to) == (0, 7)
    assert pm_range_to_text_span(projection, after.pm_from, after.pm_to) == (16, 22)


def test_an_offset_outside_the_text_has_no_position() -> None:
    projection = project(paragraphs("One."))

    assert text_offset_to_pm_position(projection, -1) is None
    assert text_offset_to_pm_position(projection, len(projection.text_plain) + 1) is None
    assert text_offset_to_pm_position(projection, len(projection.text_plain)) is not None


def test_a_backwards_range_is_refused() -> None:
    projection = project(paragraphs("One.", "Two."))

    assert pm_range_to_text_span(projection, 9, 2) is None


def test_a_document_with_no_text_has_no_span_to_give() -> None:
    projection = project(paragraphs(""))

    assert projection.blocks[0].mappable is False
    assert pm_range_to_text_span(projection, 0, 2) is None


def test_select_all_describes_the_text_it_encloses() -> None:
    """A start before the first block snaps forward, an end past the last snaps back."""
    projection = project(paragraphs("One.", "Two."))

    assert pm_range_to_text_span(projection, 0, 12) == (0, len(projection.text_plain))


# -- trimmed blocks: where arithmetic would be wrong ------------------------------------------


def test_a_trimmed_block_is_walked_not_calculated() -> None:
    """The projection trims each line, so raw and projected offsets part company."""
    projection = project(paragraphs("   The harbour was grey.   "))
    (block,) = projection.blocks

    assert projection.text_plain == "The harbour was grey."
    assert len(block.raw) != block.text_to - block.text_from
    # Arithmetic would say pm_from + 0; the walk says pm_from + 3, past the trimmed spaces.
    assert text_offset_to_pm_position(projection, 0) == block.pm_from + 3
    assert text_offset_to_pm_position(projection, 21) == block.pm_from + 24
    assert pm_range_to_text_span(projection, block.pm_from + 3, block.pm_from + 24) == (0, 21)


def test_a_position_inside_trimmed_whitespace_reads_as_the_text_beside_it() -> None:
    projection = project(paragraphs("  Padded.  "))
    (block,) = projection.blocks

    assert projection.text_plain == "Padded."
    assert pm_range_to_text_span(projection, block.pm_from, block.pm_to) == (0, 7)
    assert pm_range_to_text_span(projection, block.pm_from + 1, block.pm_from + 2) == (0, 0)


def test_a_dropped_line_inside_a_block_does_not_shift_what_follows_it() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "One"},
                    {"type": "hardBreak"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "Two"},
                ],
            }
        ],
    }
    projection = project(document)
    (block,) = projection.blocks

    assert projection.text_plain == "One\nTwo"
    # "Two" starts after both hard breaks in the document, but after one newline in the text.
    assert text_offset_to_pm_position(projection, 4) == block.pm_from + 5
    assert pm_range_to_text_span(projection, block.pm_from + 5, block.pm_to) == (4, 7)


def test_an_unknown_inline_node_makes_its_block_unmappable() -> None:
    """It costs two positions and contributes none, so the block stops being linear."""
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Before "},
                    {"type": "footnote", "content": [{"type": "text", "text": "aside"}]},
                    {"type": "text", "text": " after"},
                ],
            }
        ],
    }
    projection = project(document)
    (block,) = projection.blocks

    assert projection.text_plain == "Before aside after"
    assert block.mappable is False
    assert text_offset_to_pm_position(projection, 3) is None
