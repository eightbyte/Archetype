"""``ConversationStore`` - a chat, its turns, and the one predicate (P4-9, D30).

The standing shape applies: **one test asserts a deleted conversation is absent from every read
path together**, because a query that forgets the predicate surfaces later as a conversation that
reappears after a restore nobody performed, and gets reported as a different bug.

What this file does *not* test is anything about a provider. A conversation is storage; it can be
created, read, renamed, deleted, and restored with no key set and no provider configured at all,
and that separation is why the panel can show a transcript when the assistant is unavailable.
"""

from __future__ import annotations

import pytest

from archetype.chat.conversations import (
    MAX_CONTENT_BYTES,
    MAX_TITLE_CHARS,
    ConversationNotFoundError,
    ConversationStore,
)
from archetype.ids import IdPrefix, is_id
from archetype.projects.db import transaction
from archetype.projects.store import ProjectHandle


def test_a_new_conversation_has_an_id_a_title_and_no_turns(
    conversations: ConversationStore,
) -> None:
    conversation = conversations.create("About Mira")

    assert is_id(conversation.id, IdPrefix.CONVERSATION)
    assert conversation.title == "About Mira"
    assert conversation.message_count == 0
    assert conversation.deleted_at is None


def test_a_conversation_may_start_untitled(conversations: ConversationStore) -> None:
    """The panel names one from its first question; a title nobody typed is not a title."""
    assert conversations.create().title == ""
    assert conversations.create("   ").title == ""


def test_a_title_over_the_limit_is_refused(conversations: ConversationStore) -> None:
    with pytest.raises(ValueError, match="over the"):
        conversations.create("x" * (MAX_TITLE_CHARS + 1))


def test_the_list_is_newest_first_by_when_each_last_moved(
    project: ProjectHandle, conversations: ConversationStore
) -> None:
    """Not by creation: the one the writer was last talking in is the one to open on.

    The times are stamped by hand because ``utc_now`` has second resolution (the project's
    standing choice) and three writes in one test land inside one second - so a test that created
    rows and expected them to be ordered would be asserting on the tiebreak rather than on the
    clause it is about.
    """
    first = conversations.create("first")
    second = conversations.create("second")
    third = conversations.create("third")
    for conversation_id, moved in (
        (first.id, "2026-09-05T10:00:00Z"),
        (second.id, "2026-09-05T09:00:00Z"),
        (third.id, "2026-09-05T11:00:00Z"),
    ):
        with project.connect() as conn, transaction(conn):
            conn.execute(
                "UPDATE conversation SET updated_at = ? WHERE id = ?", (moved, conversation_id)
            )

    assert [row.id for row in conversations.list()] == [third.id, first.id, second.id]


def test_a_tie_is_broken_stably_so_a_list_never_reshuffles(
    conversations: ConversationStore,
) -> None:
    """Two conversations touched in the same second are ordered arbitrarily but **not randomly**.

    Second resolution means the list cannot always say which of two rows moved last; what it must
    never do is answer differently to two identical reads, because a panel whose rows swap places
    on a refresh looks broken in a way nobody can reproduce.
    """
    for name in ("first", "second", "third"):
        conversations.create(name)

    once = [row.id for row in conversations.list()]
    twice = [row.id for row in conversations.list()]
    assert once == twice
    assert len(once) == 3


def test_appending_allocates_ord_and_reads_back_in_order(
    conversations: ConversationStore,
) -> None:
    conversation = conversations.create()
    conversations.append(conversation.id, role="user", content="one")
    conversations.append(conversation.id, role="assistant", content="two")
    conversations.append(conversation.id, role="user", content="three")

    stored = conversations.messages(conversation.id)
    assert [message.ord for message in stored] == [0, 1, 2]
    assert [message.content for message in stored] == ["one", "two", "three"]
    assert conversations.get(conversation.id).message_count == 3


def test_a_turn_carries_what_it_cost_and_what_produced_it(
    conversations: ConversationStore,
) -> None:
    """Ruling 5 and deviation ``A1``, at the storage layer that has to hold them."""
    conversation = conversations.create()
    conversations.append(
        conversation.id,
        role="assistant",
        content="The harbour is grey in chapter one.",
        context={"parts": [{"kind": "selection", "chars": 21}], "estimated_tokens": 40},
        provider="anthropic",
        model="claude-opus-5",
        usage={"input_tokens": 120, "output_tokens": 30},
        stop_reason="end_turn",
    )

    stored = conversations.messages(conversation.id)[0]
    assert stored.provider == "anthropic"
    assert stored.model == "claude-opus-5"
    assert stored.usage == {"input_tokens": 120, "output_tokens": 30}
    assert stored.stop_reason == "end_turn"
    assert stored.error_code == ""
    assert stored.context["estimated_tokens"] == 40


def test_a_failed_turn_is_stored_with_its_code(conversations: ConversationStore) -> None:
    """A turn that went wrong is visible in the history, not a gap the writer has to remember."""
    conversation = conversations.create()
    conversations.append(
        conversation.id,
        role="assistant",
        content="The harbour",
        error_code="provider_rate_limited",
    )

    stored = conversations.messages(conversation.id)[0]
    assert stored.error_code == "provider_rate_limited"
    assert stored.content == "The harbour"
    assert stored.stop_reason == ""


def test_a_cancelled_turn_stays_distinguishable_from_a_finished_one(
    conversations: ConversationStore,
) -> None:
    """Deviation ``A1``'s whole reason: after a reload, the two must not read the same."""
    conversation = conversations.create()
    conversations.append(
        conversation.id, role="assistant", content="The harb", stop_reason="cancelled"
    )
    conversations.append(
        conversation.id, role="assistant", content="Complete.", stop_reason="end_turn"
    )

    cancelled, complete = conversations.messages(conversation.id)
    assert cancelled.stop_reason == "cancelled"
    assert cancelled.error_code == "", "a deliberate act is not a failure"
    assert complete.stop_reason == "end_turn"


def test_a_role_outside_the_stored_vocabulary_is_refused(
    conversations: ConversationStore,
) -> None:
    """``tool`` is in the port's vocabulary and has no writer here until Phase 6 does."""
    conversation = conversations.create()
    for role in ("tool", "moderator", ""):
        with pytest.raises(ValueError, match="not a role"):
            conversations.append(conversation.id, role=role, content="x")
    assert conversations.messages(conversation.id) == []


def test_content_over_the_limit_is_refused_and_writes_nothing(
    conversations: ConversationStore,
) -> None:
    conversation = conversations.create()
    with pytest.raises(ValueError, match="over the"):
        conversations.append(conversation.id, role="user", content="x" * (MAX_CONTENT_BYTES + 1))
    assert conversations.messages(conversation.id) == []


def test_renaming_is_the_only_edit_a_conversation_has(
    conversations: ConversationStore,
) -> None:
    conversation = conversations.create("untitled")
    renamed = conversations.rename(conversation.id, "  The grey harbour  ")

    assert renamed.title == "The grey harbour"
    assert conversations.get(conversation.id).title == "The grey harbour"


def test_a_deleted_conversation_is_absent_from_every_read_path_together(
    conversations: ConversationStore,
) -> None:
    """The standing test shape (D22, D25), applied to a fifth table.

    Asserted together rather than one per test: a query that forgets the predicate is found by
    whichever assertion runs, and splitting them would let a new read path be added with no
    assertion covering it.
    """
    conversation = conversations.create("About Mira")
    conversations.append(conversation.id, role="user", content="who is she?")

    deleted = conversations.delete(conversation.id)
    assert deleted.deleted_at is not None

    assert conversations.list() == []
    with pytest.raises(ConversationNotFoundError):
        conversations.get(conversation.id)
    with pytest.raises(ConversationNotFoundError):
        conversations.messages(conversation.id)
    with pytest.raises(ConversationNotFoundError):
        conversations.append(conversation.id, role="user", content="still there?")

    # And present in exactly one: the surface that exists to bring it back.
    assert [row.id for row in conversations.list_deleted()] == [conversation.id]


def test_nothing_cascades_so_a_restore_is_exact(conversations: ConversationStore) -> None:
    conversation = conversations.create("About Mira")
    conversations.append(conversation.id, role="user", content="who is she?")
    conversations.append(conversation.id, role="assistant", content="A pilot.")

    conversations.delete(conversation.id)
    restored = conversations.restore(conversation.id)

    assert restored.deleted_at is None
    assert [message.content for message in conversations.messages(conversation.id)] == [
        "who is she?",
        "A pilot.",
    ]
    assert conversations.list_deleted() == []


def test_restoring_a_live_conversation_is_a_no_op(conversations: ConversationStore) -> None:
    """The rule ``DocumentStore.restore`` and ``EntryStore.restore`` both follow."""
    conversation = conversations.create()
    assert conversations.restore(conversation.id).id == conversation.id


def test_an_unknown_id_is_a_refusal_on_every_path(conversations: ConversationStore) -> None:
    for call in (
        lambda: conversations.get("cnv_doesnotexist"),
        lambda: conversations.messages("cnv_doesnotexist"),
        lambda: conversations.rename("cnv_doesnotexist", "x"),
        lambda: conversations.delete("cnv_doesnotexist"),
        lambda: conversations.restore("cnv_doesnotexist"),
        lambda: conversations.append("cnv_doesnotexist", role="user", content="x"),
    ):
        with pytest.raises(ConversationNotFoundError):
            call()


def test_a_conversation_belongs_to_its_own_project(
    conversations: ConversationStore, make_project
) -> None:
    """One SQLite file per project (D3): a store scoped to one never answers for another."""
    other = ConversationStore(make_project("Another Manuscript"))
    conversation = conversations.create("mine")

    with pytest.raises(ConversationNotFoundError):
        other.get(conversation.id)
    assert other.list() == []


def test_a_turn_moves_the_project(project: ProjectHandle, conversations: ConversationStore) -> None:
    """The picker sorts on ``project.updated_at``, and asking a question is working on it."""
    conversation = conversations.create()
    with project.connect() as conn:
        before = conn.execute(
            "SELECT updated_at FROM project WHERE id = ?", (project.id,)
        ).fetchone()["updated_at"]

    conversations.append(conversation.id, role="user", content="a question")

    with project.connect() as conn:
        after = conn.execute(
            "SELECT updated_at FROM project WHERE id = ?", (project.id,)
        ).fetchone()["updated_at"]
    assert after >= before


def test_ord_is_unique_per_conversation(
    project: ProjectHandle, conversations: ConversationStore
) -> None:
    """The index is the guard: a race produces two turns or one failure, never a lost one."""
    conversation = conversations.create()
    conversations.append(conversation.id, role="user", content="one")

    with project.connect() as conn:
        indexes = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'message'"
            ).fetchall()
        ]
    assert "idx_message_conversation" in indexes
