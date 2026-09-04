"""P2-6 and P2-8 - the resolver, its corpus, and the properties that stand under it.

``specs/anchors.md`` is the specification and ``fixtures/anchors/cases.json`` is written from it,
not recorded from this code. The whole phase rests on one promise:

    An anchor that reports ``ok`` points at text equal to its quote. There is no case in which
    the resolver returns ``ok`` and is wrong.

That is :func:`test_an_ok_anchor_always_points_at_its_quote`, asserted **once over the whole
corpus** rather than per case, so a case added later is covered by it without anyone
remembering, and :func:`test_random_edits_never_produce_a_wrong_ok`, which asserts the same
thing over generated edits that deliberately do touch the anchored text.
"""

from __future__ import annotations

import ast
import importlib
import random
from pathlib import Path
from typing import Any

import pytest

from archetype.manuscript.anchors.resolve import (
    CONTEXT_CHARS,
    MAX_QUOTE_CHARS,
    MIN_CONTEXT_SCORE,
    WIN_MARGIN,
    AnchorRangeError,
    AnchorRecord,
    Resolution,
    collapse,
    context_for,
    extract,
    max_suggestion_chars,
    normalise,
    resolve,
    resolve_all,
)
from archetype.manuscript.anchors.status import AnchorStatus
from archetype.manuscript.projection import (
    Projection,
    pm_range_to_text_span,
    project,
    text_offset_to_pm_position,
)

from .conftest import build_blocks, load_anchor_cases

CASES = load_anchor_cases()
CASE_IDS = [case["name"] for case in CASES]


def anchor_over(projection: Projection, passage: str) -> AnchorRecord:
    """Create an anchor over ``passage``, the way a client selecting it would.

    The corpus names the words; the harness turns them into the ProseMirror range the client
    sends and lets the server derive the quote and its context, which is the real creation path.
    """
    text_from = projection.text_plain.index(passage)
    from_pos = text_offset_to_pm_position(projection, text_from)
    to_pos = text_offset_to_pm_position(projection, text_from + len(passage))
    assert from_pos is not None and to_pos is not None, passage

    found = extract(projection, from_pos, to_pos)
    return AnchorRecord(
        from_pos=found.from_pos,
        to_pos=found.to_pos,
        quote=found.quote,
        prefix=found.prefix,
        suffix=found.suffix,
    )


def text_at(projection: Projection, resolution: Resolution) -> str:
    """The text a resolution's positions actually point at."""
    span = pm_range_to_text_span(projection, resolution.from_pos, resolution.to_pos)
    assert span is not None, resolution
    return projection.text_plain[span[0] : span[1]]


def run_case(case: dict[str, Any]) -> list[tuple[Projection, AnchorRecord, Resolution, dict]]:
    """Resolve one corpus case, and its ``then`` follow-up, as consecutive saves would.

    Returns one ``(projection, anchor, resolution, expected)`` tuple per stage, so that a test
    can assert on the outcome and a property can walk every stage of every case.
    """
    before = project(build_blocks(case["before"]))
    anchor = anchor_over(before, case["anchor"])
    assert anchor.quote == case["quote"], case["name"]

    stages = []
    stage = case
    while True:
        after = project(build_blocks(stage["after"]))
        resolution = resolve(anchor, context_for(after))
        stages.append((after, anchor, resolution, stage["expect"]))
        stage = stage.get("then")
        if stage is None:
            return stages
        # The next save resolves what the last one stored, which is how a status stops being
        # latched: the anchor carries the positions the previous resolution concluded.
        anchor = AnchorRecord(
            from_pos=resolution.from_pos,
            to_pos=resolution.to_pos,
            quote=anchor.quote,
            prefix=anchor.prefix,
            suffix=anchor.suffix,
        )


# -- the corpus -------------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_corpus_case(case: dict[str, Any]) -> None:
    for after, anchor, resolution, expected in run_case(case):
        where = f"{case['name']} (step {resolution.step})"

        assert resolution.status == expected["status"], where
        assert resolution.step == expected["step"], where
        assert resolution.moved_from(anchor) is expected["moved"], where

        if "preceded_by" in expected:
            span = pm_range_to_text_span(after, resolution.from_pos, resolution.to_pos)
            assert span is not None, where
            assert after.text_plain[: span[0]].endswith(expected["preceded_by"]), where

        if "suggestion" in expected:
            suggested = None if resolution.suggestion is None else resolution.suggestion.text
            assert suggested == expected["suggestion"], where


def test_the_corpus_covers_what_the_specification_asks_for() -> None:
    """A guard on the fixture set itself, so its coverage cannot quietly erode.

    ``specs/anchors.md`` section 10 names these; if a case is dropped this fails rather than the
    suite silently getting weaker.
    """
    names = " ".join(CASE_IDS)
    for required in (
        "far above",
        "far below",
        "immediately before",
        "immediately after",
        "inside the range",
        "deleted",
        "duplicated",
        "twice",
        "split",
        "merged",
        "reflow",
        "emptied",
        "whitespace",
        "scene break",
    ):
        assert required in names, f"the anchor corpus no longer covers {required!r}"


def test_every_rung_of_the_ladder_is_reached_by_the_corpus() -> None:
    """A step nobody reaches is a step nobody tests."""
    reached = {resolution.step for case in CASES for _, _, resolution, _ in run_case(case)}
    assert reached == {1, 2, 3, 4, 5}


# -- the properties ---------------------------------------------------------------------------


def test_an_ok_anchor_always_points_at_its_quote() -> None:
    """**The promise.** Asserted once over the whole corpus, not per case.

    Everything else in this phase can be fixed later; this one cannot be detected later, because
    an anchor that is wrong does not fail - it quietly cites the wrong paragraph forever.
    """
    checked = 0
    for case in CASES:
        for after, anchor, resolution, _ in run_case(case):
            if resolution.status != AnchorStatus.OK:
                continue
            assert collapse(text_at(after, resolution)) == collapse(anchor.quote), case["name"]
            checked += 1
    assert checked > 0, "no case in the corpus resolved to ok, so the property proved nothing"


def test_a_stale_anchor_keeps_the_positions_it_had() -> None:
    """It does not move to somewhere approximately right. That is the whole product promise."""
    for case in CASES:
        for _, anchor, resolution, _ in run_case(case):
            if resolution.status == AnchorStatus.STALE:
                assert (resolution.from_pos, resolution.to_pos) == (
                    anchor.from_pos,
                    anchor.to_pos,
                ), case["name"]


def test_a_suggestion_is_never_applied() -> None:
    """A suggestion only ever rides on a ``stale`` resolution; it never becomes the answer.

    Deliberately not asserted: that the suggested range differs from the anchor's own. A
    replacement the same length as the passage it replaced lands on exactly the same positions -
    the contract fixture has one - and the anchor is still ``stale`` and still unmoved. What
    matters is the status, not the arithmetic.
    """
    for case in CASES:
        for _, anchor, resolution, _ in run_case(case):
            if resolution.suggestion is None:
                continue
            assert resolution.status == AnchorStatus.STALE, case["name"]
            assert (resolution.from_pos, resolution.to_pos) == (
                anchor.from_pos,
                anchor.to_pos,
            ), case["name"]


# -- generated edits --------------------------------------------------------------------------

QUOTE = "the Kestrel rode low in the grey water"

_FILLER_WORDS = (
    "morning tide rope canvas lantern gull anchor bell fog rail plank barrel "
    "keel sail hawser oakum tallow sextant chart compass"
).split()


def _filler(rng: random.Random) -> str:
    return " ".join(rng.choice(_FILLER_WORDS) for _ in range(rng.randint(4, 12))).capitalize() + "."


def _base_document(rng: random.Random) -> tuple[list[str], int]:
    """A document with the anchored passage in a paragraph of its own, and its index."""
    blocks = [_filler(rng) for _ in range(rng.randint(1, 4))]
    anchored = rng.randint(0, len(blocks))
    blocks.insert(anchored, f"Marlow saw that {QUOTE} before the bell rang.")
    blocks.extend(_filler(rng) for _ in range(rng.randint(1, 4)))
    return blocks, anchored


def _edit_elsewhere(blocks: list[str], anchored: int, rng: random.Random) -> tuple[list[str], int]:
    """One random edit that does not touch the anchored paragraph."""
    choice = rng.choice(("insert", "delete", "rewrite"))
    if choice == "insert":
        at = rng.randint(0, len(blocks))
        blocks = blocks[:at] + [_filler(rng)] + blocks[at:]
        return blocks, anchored + (1 if at <= anchored else 0)
    others = [index for index in range(len(blocks)) if index != anchored]
    if not others:
        return blocks, anchored
    at = rng.choice(others)
    if choice == "delete":
        return blocks[:at] + blocks[at + 1 :], anchored - (1 if at < anchored else 0)
    blocks = list(blocks)
    blocks[at] = _filler(rng)
    return blocks, anchored


@pytest.mark.parametrize("seed", range(40))
def test_edits_that_do_not_touch_the_passage_leave_it_ok_and_on_the_same_characters(
    seed: int,
) -> None:
    """The exit criterion, stated as a property rather than as an anecdote (P2-8).

    Seeded, so a failure is a case a developer can re-run rather than a story about one run.
    """
    rng = random.Random(seed)
    blocks, anchored = _base_document(rng)
    before = project(build_blocks(blocks))
    anchor = anchor_over(before, QUOTE)

    for _ in range(rng.randint(1, 8)):
        blocks, anchored = _edit_elsewhere(blocks, anchored, rng)

    after = project(build_blocks(blocks))
    resolution = resolve(anchor, context_for(after))

    assert resolution.status == AnchorStatus.OK, (seed, blocks)
    assert text_at(after, resolution) == QUOTE, (seed, blocks)


@pytest.mark.parametrize("seed", range(40))
def test_random_edits_never_produce_a_wrong_ok(seed: int) -> None:
    """The negative property over edits that **do** reach into the anchored text.

    The outcome may legitimately be either, and this asserts nothing about which - only that an
    ``ok`` is never wrong. That is the one thing no later phase could detect.
    """
    rng = random.Random(1000 + seed)
    blocks, anchored = _base_document(rng)
    before = project(build_blocks(blocks))
    anchor = anchor_over(before, QUOTE)

    for _ in range(rng.randint(1, 6)):
        if rng.random() < 0.4:
            blocks = list(blocks)
            blocks[anchored] = blocks[anchored].replace(
                rng.choice(("Kestrel", "rode", "grey", "water", "Marlow")), _filler(rng)[:6], 1
            )
        else:
            blocks, anchored = _edit_elsewhere(blocks, anchored, rng)

    after = project(build_blocks(blocks))
    resolution = resolve(anchor, context_for(after))

    if resolution.status == AnchorStatus.OK:
        assert collapse(text_at(after, resolution)) == collapse(anchor.quote), (seed, blocks)
    else:
        assert (resolution.from_pos, resolution.to_pos) == (anchor.from_pos, anchor.to_pos)


# -- the normal form (specs/anchors.md section 4) ---------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ""),
        ("one two", "one two"),
        ("one  two", "one two"),
        ("one\n\ntwo", "one two"),
        ("one\t\n two", "one two"),
        ("  padded  ", " padded "),
        ("\n", " "),
    ],
)
def test_normalise_collapses_every_run_of_whitespace(text: str, expected: str) -> None:
    assert normalise(text).normal == expected
    assert collapse(text) == expected


def test_normalise_trims_nothing_from_the_ends() -> None:
    """Trimming would silently shift every offset after it."""
    result = normalise("  The harbour.  ")
    assert result.normal == " The harbour. "
    assert result.starts[0] == 0
    assert result.ends[0] == 2


def test_normalise_remembers_the_whole_run_each_space_came_from() -> None:
    result = normalise("a   b")
    assert result.normal == "a b"
    assert (result.starts[1], result.ends[1]) == (1, 4)
    assert len(result.starts) == len(result.ends) == len(result.normal)


def test_matching_is_case_sensitive() -> None:
    """A quote is the writer's words, and ``Grey`` is not ``grey``."""
    before = project(build_blocks(["The harbour was grey."]))
    anchor = anchor_over(before, "grey")
    after = project(build_blocks(["The harbour was Grey."]))

    assert resolve(anchor, context_for(after)).status == AnchorStatus.STALE


# -- step 4's thresholds ----------------------------------------------------------------------


def test_the_thresholds_are_the_values_the_specification_names() -> None:
    """They are written down with their reasoning; a quiet change to one is a product change."""
    assert (CONTEXT_CHARS, MAX_QUOTE_CHARS, MIN_CONTEXT_SCORE, WIN_MARGIN) == (48, 4000, 12, 8)
    assert max_suggestion_chars("x" * 10) == 4 * 10 + 2 * CONTEXT_CHARS


def test_a_clear_winner_takes_the_ambiguous_quote() -> None:
    """The surroundings are damaged enough that step 2 cannot answer, and still decide it."""
    before = project(
        build_blocks(
            ["He turned the key slowly.", "The door was locked.", "He waited in the hall."]
        )
    )
    anchor = anchor_over(before, "The door was locked.")
    after = project(
        build_blocks(
            [
                "Later.",
                "He turned the key slowly.",
                "The door was locked.",
                "She pushed the window open.",
                "The door was locked.",
            ]
        )
    )
    resolution = resolve(anchor, context_for(after))
    span = pm_range_to_text_span(after, resolution.from_pos, resolution.to_pos)

    assert resolution.status == AnchorStatus.OK
    assert resolution.step == 4
    assert span is not None
    assert after.text_plain[: span[0]].endswith("He turned the key slowly.\n\n")


def test_context_below_the_minimum_score_does_not_decide() -> None:
    """Two or three words of agreement is evidence; one common word is a coincidence."""
    before = project(build_blocks(["Yes.", "The door was locked."]))
    anchor = anchor_over(before, "The door was locked.")
    after = project(
        build_blocks(["Later.", "Yes.", "The door was locked.", "Yes.", "The door was locked."])
    )

    assert len(collapse(anchor.prefix)) < MIN_CONTEXT_SCORE
    assert resolve(anchor, context_for(after)).status == AnchorStatus.STALE


# -- the suggestion protocol (specs/anchors.md section 6) --------------------------------------


def test_a_suggestion_needs_surroundings_that_are_still_unique() -> None:
    before = project(build_blocks(["A quiet morning on the water.", "The bell rang twice."]))
    anchor = anchor_over(before, "The bell rang twice.")
    after = project(build_blocks(["A quiet morning on the water.", "The bell rang once."]))
    resolution = resolve(anchor, context_for(after))

    assert resolution.status == AnchorStatus.STALE
    assert resolution.suggestion is not None
    assert resolution.suggestion.text == "The bell rang once."


def test_a_replacement_far_larger_than_the_quote_is_not_suggested() -> None:
    """Beyond the cap the writer replaced far more than the passage; pointing at it is noise."""
    before = project(build_blocks(["A quiet morning.", "Yes.", "The bell rang twice."]))
    anchor = anchor_over(before, "Yes.")
    replacement = " ".join(["something entirely different"] * 30)
    after = project(build_blocks(["A quiet morning.", replacement, "The bell rang twice."]))
    resolution = resolve(anchor, context_for(after))

    assert resolution.status == AnchorStatus.STALE
    assert len(replacement) > max_suggestion_chars(anchor.quote)
    assert resolution.suggestion is None


def test_an_anchor_with_no_surroundings_is_never_suggested_for() -> None:
    """Otherwise the "suggestion" would be the whole document."""
    before = project(build_blocks(["The door was locked."]))
    anchor = anchor_over(before, "The door was locked.")
    after = project(build_blocks(["Something else entirely."]))
    resolution = resolve(anchor, context_for(after))

    assert (anchor.prefix, anchor.suffix) == ("", "")
    assert resolution.status == AnchorStatus.STALE
    assert resolution.suggestion is None


# -- what is refused at creation (specs/anchors.md section 8) ----------------------------------


def test_a_zero_length_range_is_refused() -> None:
    projection = project(build_blocks(["The harbour was grey."]))
    with pytest.raises(AnchorRangeError, match="cursor position"):
        extract(projection, 5, 5)


def test_a_backwards_range_is_refused() -> None:
    projection = project(build_blocks(["The harbour was grey."]))
    with pytest.raises(AnchorRangeError, match="ends before it begins"):
        extract(projection, 9, 5)


def test_a_range_outside_the_document_is_refused() -> None:
    projection = project(build_blocks(["The harbour was grey."]))
    with pytest.raises(AnchorRangeError):
        extract(projection, 900, 950)


def test_a_range_inside_a_scene_break_is_refused() -> None:
    projection = project(build_blocks(["Before.", "---", "After."]))
    _, rule, _ = projection.blocks
    with pytest.raises(AnchorRangeError, match="scene break"):
        extract(projection, rule.pm_from, rule.pm_to)


def test_a_range_spanning_a_scene_break_is_refused() -> None:
    """Its quote would carry five characters nobody typed."""
    projection = project(build_blocks(["Before.", "---", "After."]))
    first, _, last = projection.blocks
    with pytest.raises(AnchorRangeError, match="scene break"):
        extract(projection, first.pm_from, last.pm_to)


def test_a_range_holding_only_whitespace_is_refused() -> None:
    projection = project(build_blocks(["One two"]))
    with pytest.raises(AnchorRangeError, match="no text to anchor"):
        extract(projection, 4, 5)


def test_a_quote_over_the_cap_is_refused() -> None:
    long_paragraph = "word " * (MAX_QUOTE_CHARS // 2)
    projection = project(build_blocks([long_paragraph]))
    (block,) = projection.blocks
    with pytest.raises(AnchorRangeError, match=str(MAX_QUOTE_CHARS)):
        extract(projection, block.pm_from, block.pm_to)


def test_a_quote_at_the_cap_is_allowed() -> None:
    projection = project(build_blocks(["x" * MAX_QUOTE_CHARS]))
    (block,) = projection.blocks
    found = extract(projection, block.pm_from, block.pm_to)

    assert len(found.quote) == MAX_QUOTE_CHARS


def test_creation_stores_the_context_the_specification_names() -> None:
    projection = project(build_blocks(["x" * 200 + "QUOTE" + "y" * 200]))
    text_from = projection.text_plain.index("QUOTE")
    from_pos = text_offset_to_pm_position(projection, text_from)
    to_pos = text_offset_to_pm_position(projection, text_from + 5)
    assert from_pos is not None and to_pos is not None
    found = extract(projection, from_pos, to_pos)

    assert found.quote == "QUOTE"
    assert found.prefix == "x" * CONTEXT_CHARS
    assert found.suffix == "y" * CONTEXT_CHARS


def test_context_at_the_edges_of_a_document_is_simply_shorter() -> None:
    projection = project(build_blocks(["QUOTE"]))
    (block,) = projection.blocks
    found = extract(projection, block.pm_from, block.pm_to)

    assert (found.prefix, found.suffix) == ("", "")


# -- storage the resolver did not write --------------------------------------------------------


def test_an_anchor_with_no_quote_is_stale_without_a_search() -> None:
    """Refused at creation, so a row like this came from somewhere else. It gets no answer."""
    projection = project(build_blocks(["The harbour was grey."]))
    anchor = AnchorRecord(from_pos=1, to_pos=4, quote="   ", prefix="", suffix="")
    resolution = resolve(anchor, context_for(projection))

    assert resolution.status == AnchorStatus.STALE
    assert resolution.step == 0
    assert resolution.suggestion is None


def test_resolve_all_answers_every_anchor_against_one_document() -> None:
    projection = project(build_blocks(["The harbour was grey.", "He did not look back."]))
    anchors = [
        anchor_over(projection, "harbour"),
        anchor_over(projection, "look back"),
        AnchorRecord(from_pos=1, to_pos=5, quote="gone", prefix="", suffix=""),
    ]
    statuses = [resolution.status for resolution in resolve_all(anchors, projection)]

    assert statuses == [AnchorStatus.OK, AnchorStatus.OK, AnchorStatus.STALE]


def test_the_resolver_imports_nothing_it_should_not() -> None:
    """Pure means pure: no storage, no framework, so the corpus can drive it directly (P2-6).

    Read from the module's own syntax rather than from a grep, because a docstring that names
    ``archetype.projects`` in prose is not an import and must not read as one.
    """
    module = importlib.import_module("archetype.manuscript.anchors.resolve")
    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    absolute: set[str] = set()
    relative: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            absolute.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative.add((node.level, node.module or ""))
            else:
                absolute.add(node.module or "")

    assert absolute == {"__future__", "collections.abc", "dataclasses", "re", "typing"}
    assert relative == {(1, "status"), (2, "projection")}
