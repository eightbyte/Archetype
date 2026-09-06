"""The context composer - what the model is actually given (P4-10, ruling 5).

Two properties carry most of this file.

**The composer takes what the writer pointed at and what they named, and nothing else.** There is
no search here, because there is no index until Phase 5 (plan section 1). A test that a composer
*did* retrieve something would be the first sign it had quietly become retrieval, so the assertion
runs the other way: an entry that was not named is not in the composed context, however relevant
it is to the passage.

**The number shown before sending is the number the refusal uses.** ``ComposedContext``'s estimate
and :func:`~archetype.llm.budget.estimate_request_tokens` over the same messages must agree
exactly, or the preview is telling the writer one thing and the budget check another.
"""

from __future__ import annotations

import pytest

from archetype.bible.entries import EntryStore
from archetype.bible.schema import EntryKind
from archetype.llm.budget import estimate_request_tokens
from archetype.llm.context import (
    MAX_RECORDED_EXCERPT_CHARS,
    PART_KINDS,
    SYSTEM_PROMPT,
    ContextSelector,
    compose,
    history_from,
)
from archetype.llm.port import CompletionRequest, Message
from archetype.manuscript.anchors.resolve import AnchorRangeError
from archetype.manuscript.documents import DocumentNotFoundError, DocumentStore
from archetype.manuscript.projection import project, text_offset_to_pm_position
from archetype.projects.store import ProjectHandle

PARAGRAPHS = [
    "The harbour was grey and the gulls had gone inland.",
    "Mira counted the boats twice and did not look back.",
]


@pytest.fixture
def chapter(make_document):
    """One chapter with prose in it, read back with its content and projection."""
    return make_document(title="Arrival", paragraphs=PARAGRAPHS)


def range_over(document, passage: str) -> tuple[int, int]:
    """The ProseMirror range a client selecting ``passage`` would send."""
    projection = project(document.content)
    start = projection.text_plain.index(passage)
    from_pos = text_offset_to_pm_position(projection, start)
    to_pos = text_offset_to_pm_position(projection, start + len(passage))
    assert from_pos is not None and to_pos is not None
    return from_pos, to_pos


def kinds_of(composed) -> list[str]:
    return [part.kind for part in composed.parts]


def part_named(composed, kind: str):
    for part in composed.parts:
        if part.kind == kind:
            return part
    raise AssertionError(f"no {kind!r} part; composed: {kinds_of(composed)}")


# -- what goes in ------------------------------------------------------------------------------


def test_a_bare_question_composes_instructions_and_the_question(
    project: ProjectHandle,
) -> None:
    composed = compose(project, prompt="who is Mira?", selector=ContextSelector())

    assert kinds_of(composed) == ["instructions", "question"]
    assert composed.messages[0].role == "system"
    assert composed.messages[0].content == SYSTEM_PROMPT
    assert composed.messages[-1].role == "user"
    assert "who is Mira?" in composed.messages[-1].content


def test_the_selection_is_derived_from_stored_content_and_never_sent_by_a_client(
    project: ProjectHandle, chapter
) -> None:
    """``specs/anchors.md`` section 8's rule, one module over: the server owns the text.

    The selector carries a *range*, so a client cannot compose a context around a quote the
    manuscript does not contain - it is never asked what the manuscript says.
    """
    from_pos, to_pos = range_over(chapter, "the gulls had gone inland")
    composed = compose(
        project,
        prompt="is this too much?",
        selector=ContextSelector(
            document_id=chapter.meta.id,
            from_pos=from_pos,
            to_pos=to_pos,
            include_chapter=False,
        ),
    )

    selection = part_named(composed, "selection")
    assert selection.text == "the gulls had gone inland"
    assert selection.ref_id == chapter.meta.id
    assert "Arrival" in selection.label
    assert "the gulls had gone inland" in composed.messages[-1].content


def test_the_chapter_comes_as_the_servers_own_projection(project: ProjectHandle, chapter) -> None:
    composed = compose(
        project,
        prompt="what is the tone here?",
        selector=ContextSelector(document_id=chapter.meta.id),
    )

    chapter_part = part_named(composed, "chapter")
    assert chapter_part.text == chapter.text_plain
    assert "Arrival" in chapter_part.label
    assert f"{chapter.meta.word_count:,} words" in chapter_part.label


def test_the_writer_can_drop_the_chapter(project: ProjectHandle, chapter) -> None:
    """Every flag on the selector exists so a part can be dropped before sending (P4-13)."""
    composed = compose(
        project,
        prompt="what is the tone here?",
        selector=ContextSelector(document_id=chapter.meta.id, include_chapter=False),
    )
    assert "chapter" not in kinds_of(composed)


def test_only_the_entries_the_writer_named_are_included(
    project: ProjectHandle, entries: EntryStore
) -> None:
    """The assertion that would fail first if the composer started retrieving."""
    named = entries.create(EntryKind.CHARACTER, "Mira", summary="A harbour pilot.")
    entries.create(EntryKind.CHARACTER, "Tomas", summary="Her brother, also at the harbour.")

    composed = compose(
        project,
        prompt="what does she want?",
        selector=ContextSelector(entry_ids=(named.id,)),
    )

    entry_parts = [part for part in composed.parts if part.kind == "entry"]
    assert [part.ref_id for part in entry_parts] == [named.id]
    assert "A harbour pilot." in entry_parts[0].text
    assert "Tomas" not in composed.messages[-1].content


def test_an_entrys_attributes_are_rendered_as_prose(
    project: ProjectHandle, entries: EntryStore
) -> None:
    entry = entries.create(
        EntryKind.CHARACTER,
        "Mira",
        attributes={"aliases": ["the pilot", "M"], "role": "protagonist"},
    )
    composed = compose(project, prompt="who?", selector=ContextSelector(entry_ids=(entry.id,)))

    text = part_named(composed, "entry").text
    assert 'aliases: ["the pilot", "M"]' in text
    assert "role: protagonist" in text


def test_history_is_composed_in_because_a_provider_remembers_nothing(
    project: ProjectHandle,
) -> None:
    """providers.md section 10: every request is complete. Conversation state lives in the file."""
    history = history_from([("user", "who is Mira?"), ("assistant", "A harbour pilot.")])
    composed = compose(
        project, prompt="and her brother?", selector=ContextSelector(), history=history
    )

    assert [message.role for message in composed.messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert part_named(composed, "history").label == "2 earlier turns"


def test_the_writer_can_drop_the_history(project: ProjectHandle) -> None:
    history = history_from([("user", "who is Mira?")])
    composed = compose(
        project,
        prompt="start again",
        selector=ContextSelector(include_history=False),
        history=history,
    )
    assert "history" not in kinds_of(composed)
    assert len(composed.messages) == 2


def test_an_empty_turn_is_kept_in_the_transcript_and_left_out_of_the_prompt() -> None:
    """A failed turn is stored with an empty body; sending one is noise at best."""
    assert history_from([("assistant", ""), ("user", "  "), ("user", "real")]) == (
        Message(role="user", content="real"),
    )


# -- what it refuses ---------------------------------------------------------------------------


def test_a_selection_in_a_chapter_that_is_gone_is_refused(
    project: ProjectHandle, documents: DocumentStore, chapter
) -> None:
    documents.delete(chapter.meta.id)
    with pytest.raises(DocumentNotFoundError):
        compose(
            project,
            prompt="what about this?",
            selector=ContextSelector(document_id=chapter.meta.id),
        )


def test_an_impossible_range_is_refused_with_the_resolvers_own_sentence(
    project: ProjectHandle, chapter
) -> None:
    """``extract`` is the anchor resolver's function, so the refusals are the ones already
    written for a writer to read (``specs/anchors.md`` section 8)."""
    with pytest.raises(AnchorRangeError):
        compose(
            project,
            prompt="what about this?",
            selector=ContextSelector(document_id=chapter.meta.id, from_pos=4, to_pos=4),
        )


# -- what it records ---------------------------------------------------------------------------


def test_the_estimate_is_exactly_the_one_the_budget_check_will_use(
    project: ProjectHandle, chapter
) -> None:
    """Otherwise the preview says one number and the refusal uses another."""
    composed = compose(
        project,
        prompt="is this chapter too long?",
        selector=ContextSelector(document_id=chapter.meta.id),
    )
    request = CompletionRequest(messages=composed.messages, model="fake-model", max_tokens=1024)

    assert composed.estimated_tokens == estimate_request_tokens(request)


def test_every_part_records_the_same_keys_whatever_it_is(
    project: ProjectHandle, chapter, entries: EntryStore
) -> None:
    """The P3-11 rule: a shape whose key set depends on its own values is a renderer of branches."""
    entry = entries.create(EntryKind.PLACE, "The Quay")
    from_pos, to_pos = range_over(chapter, "Mira counted the boats twice")
    composed = compose(
        project,
        prompt="does this hold together?",
        selector=ContextSelector(
            document_id=chapter.meta.id,
            from_pos=from_pos,
            to_pos=to_pos,
            entry_ids=(entry.id,),
        ),
        history=history_from([("user", "earlier")]),
    )

    expected = {"kind", "label", "ref_id", "chars", "estimated_tokens", "excerpt"}
    assert {part["kind"] for part in composed.record()["parts"]} <= set(PART_KINDS)
    for part in composed.record()["parts"]:
        assert set(part) == expected


def test_a_part_too_big_to_record_says_how_big_it_was(project: ProjectHandle) -> None:
    """A chapter is not copied into every message; what was withheld is visible, not implied."""
    long_prompt = "x" * (MAX_RECORDED_EXCERPT_CHARS + 1)
    composed = compose(project, prompt=long_prompt, selector=ContextSelector())

    question = next(part for part in composed.record()["parts"] if part["kind"] == "question")
    assert question["excerpt"] == ""
    assert question["chars"] == MAX_RECORDED_EXCERPT_CHARS + 1


def test_the_record_carries_what_was_asked_for_as_well_as_what_was_sent(
    project: ProjectHandle, chapter
) -> None:
    """Ruling 5: a wrong answer is diagnosed from the selector *and* the parts."""
    composed = compose(
        project,
        prompt="why?",
        selector=ContextSelector(document_id=chapter.meta.id, include_chapter=False),
    )
    record = composed.record()

    assert record["selector"]["document_id"] == chapter.meta.id
    assert record["selector"]["include_chapter"] is False
    assert record["estimated_tokens"] == composed.estimated_tokens
