"""``ConversationStore`` - a chat, its turns, and what each one cost (P4-9, D30).

Scoped by the same :class:`~archetype.projects.store.ProjectHandle` every other store is, and
carrying every rule, because a route carries none (api-contract section 1).

Four rules run through this module, and each is a promise migration 004's own comments make:

**A message is appended and never edited.** There is no ``update``, no ``revision`` column, and no
D19 guard, because a conversation has no concurrent-edit surface: the title is the only mutable
field on it. An assistant turn is a record of what was said and what it cost, and editing one
would make the transcript a claim about a conversation that never happened.

**A message is not independently removable.** A conversation is soft-deleted whole; a transcript
with a hole in it records something that did not happen. So the delete surface is the
conversation's, and ``deleted_at IS NULL`` is the whole of the predicate - the same one D22 put on
a chapter and D25 on an entry, applied to a fifth table.

**``ord`` is unique per conversation and is allocated inside the append's own transaction.** The
unique index is what makes a race a failure rather than a silently overwritten turn.

**What was sent is stored beside what came back** (plan section 2, ruling 5). ``context_json``
holds the composed context that produced the message, ``usage_json`` what the provider said it
cost, and ``provider``/``model`` who answered - per message rather than per conversation, because
swapping providers is a settings change with no code change (D34) and two consecutive turns may
legitimately have come from different models.

The stored turn is :class:`ChatMessage` and **not** ``Message``, deliberately: the port already
has a :class:`~archetype.llm.port.Message`, that one is the vocabulary a model is spoken to in,
and two types with one name in one process is how a shape ends up on the wrong side of a wire.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Final

from ..ids import IdPrefix, new_id
from ..projects.db import touch_project, transaction, utc_now
from ..projects.store import ProjectHandle

__all__ = [
    "MAX_CONTENT_BYTES",
    "MAX_TITLE_CHARS",
    "STORED_ROLES",
    "ChatMessage",
    "Conversation",
    "ConversationError",
    "ConversationNotFoundError",
    "ConversationStore",
    "clean_title",
]

#: A conversation's title. The chapter and entry limit; a name is a name.
MAX_TITLE_CHARS: Final[int] = 200

#: One turn's text. Generous, because an assistant answer is bounded by ``llm_max_tokens`` and a
#: writer may paste a passage into a question - and bounded anyway, because a store that accepts
#: an unbounded string is a store that will one day hold a manuscript by accident.
MAX_CONTENT_BYTES: Final[int] = 256 * 1024

#: The roles a stored turn may carry. ``tool`` is in the port's vocabulary and is **absent here**,
#: on the rule ``proposed`` and the ``pre-*`` snapshot reasons already follow: Phase 4 has no tool
#: and therefore no writer for one, and a column that can hold a value nothing writes is a value
#: nobody has decided the meaning of. Phase 6 adds it in the same change that writes one.
STORED_ROLES: Final[frozenset[str]] = frozenset({"user", "assistant", "system"})

_CONVERSATION_COLUMNS: Final[str] = "id, project_id, title, created_at, updated_at, deleted_at"

_MESSAGE_COLUMNS: Final[str] = (
    "id, conversation_id, ord, role, content, context_json, provider, model, usage_json, "
    "stop_reason, error_code, created_at"
)

#: A conversation is live when this holds. That is the whole of it (D22, D25).
_LIVE: Final[str] = "deleted_at IS NULL"


class ConversationError(RuntimeError):
    """A chat operation could not be completed."""


class ConversationNotFoundError(ConversationError):
    """No live conversation with that id exists in this project."""


@dataclass(frozen=True, slots=True)
class Conversation:
    """One chat: its identity, its title, and when it last moved."""

    id: str
    project_id: str
    title: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    #: How many turns it holds. Filled by the list and detail reads; ``0`` elsewhere, because a
    #: count nobody asked for is a second query per row.
    message_count: int = 0

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One stored turn.

    ``usage`` of zero means **not reported** and not free (``specs/providers.md`` section 2), so a
    reader shows the difference rather than drawing a confident zero. ``stop_reason`` is the port's
    normalised vocabulary and is empty until a turn finishes - which is what keeps a **cancelled**
    turn distinguishable from a complete one after a reload (deviation ``A1``). ``error_code`` is
    one of ruling 4's six when a turn failed, and a failed turn is stored rather than dropped.
    """

    id: str
    conversation_id: str
    ord: int
    role: str
    content: str
    created_at: str
    context: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = ""
    error_code: str = ""


def clean_title(title: str) -> str:
    """A trimmed conversation title, bounded.

    Raises:
        ValueError: If it is not a string or is over :data:`MAX_TITLE_CHARS`.
    """
    if not isinstance(title, str):
        raise ValueError(f"a title must be a string, got {type(title).__name__}")
    cleaned = title.strip()
    if len(cleaned) > MAX_TITLE_CHARS:
        raise ValueError(
            f"a title is {len(cleaned)} characters, over the {MAX_TITLE_CHARS}-character limit"
        )
    return cleaned


def _checked_content(content: str) -> str:
    """One turn's text, bounded by bytes rather than characters.

    Raises:
        ValueError: If it is not a string or is over :data:`MAX_CONTENT_BYTES`.
    """
    if not isinstance(content, str):
        raise ValueError(f"message content must be a string, got {type(content).__name__}")
    size = len(content.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise ValueError(f"that message is {size} bytes, over the {MAX_CONTENT_BYTES}-byte limit")
    return content


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _conversation_from_row(row: sqlite3.Row, *, message_count: int = 0) -> Conversation:
    return Conversation(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
        message_count=message_count,
    )


def _message_from_row(row: sqlite3.Row) -> ChatMessage:
    return ChatMessage(
        id=row["id"],
        conversation_id=row["conversation_id"],
        ord=int(row["ord"]),
        role=row["role"],
        content=row["content"],
        context=json.loads(row["context_json"]),
        provider=row["provider"],
        model=row["model"],
        usage=json.loads(row["usage_json"]),
        stop_reason=row["stop_reason"],
        error_code=row["error_code"],
        created_at=row["created_at"],
    )


class ConversationStore:
    """Create, read, rename, soft-delete, and restore the conversations of one project."""

    def __init__(self, handle: ProjectHandle) -> None:
        self.handle = handle

    # -- reading ------------------------------------------------------------------------------

    def list(self) -> list[Conversation]:
        """The live conversations, **newest first** by when each last moved.

        ``updated_at`` rather than ``created_at``: a conversation moves when a turn is appended,
        and the one the writer was last talking in is the one the panel opens on.

        Timestamps have second resolution (``utc_now``), so two conversations touched in the same
        second cannot be told apart by time. The remaining sort keys are there to make that case
        **stable rather than meaningful**: two identical reads answer identically, because a list
        whose rows swap places on a refresh looks broken in a way nobody can reproduce.
        """
        return self._list(deleted=False)

    def list_deleted(self) -> list[Conversation]:
        """The restore surface (D22, D25). The same read, on the other side of the predicate."""
        return self._list(deleted=True)

    def get(self, conversation_id: str, *, include_deleted: bool = False) -> Conversation:
        """One conversation, with its message count.

        Raises:
            ConversationNotFoundError: If this project holds no such conversation, or it is
                deleted and ``include_deleted`` is false.
        """
        with self.handle.connect() as conn:
            return self.require(conn, conversation_id, include_deleted=include_deleted)

    def messages(self, conversation_id: str, *, include_deleted: bool = False) -> list[ChatMessage]:
        """One conversation's turns, in ``ord``.

        The transcript is read whole. There is no pagination and no cap: a conversation is tens of
        turns, the panel renders all of them, and a transcript that silently stopped at *n* would
        be a record of a conversation that did not happen.

        Raises:
            ConversationNotFoundError: As :meth:`get` - the conversation is checked first, so a
                deleted one answers with a refusal rather than with its contents.
        """
        with self.handle.connect() as conn:
            self.require(conn, conversation_id, include_deleted=include_deleted)
            rows = conn.execute(
                f"SELECT {_MESSAGE_COLUMNS} FROM message WHERE conversation_id = ? ORDER BY ord",
                (conversation_id,),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    # -- writing ------------------------------------------------------------------------------

    def create(self, title: str = "") -> Conversation:
        """Start a conversation. An empty title is legitimate - the panel names it from its
        first question, and a title nobody typed is not a title.

        Raises:
            ValueError: If the title is too long.
        """
        cleaned = clean_title(title)
        conversation_id = new_id(IdPrefix.CONVERSATION)
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            conn.execute(
                "INSERT INTO conversation (id, project_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, self.handle.id, cleaned, now, now),
            )
            touch_project(conn, self.handle.id, now)
            return self.require(conn, conversation_id)

    def rename(self, conversation_id: str, title: str) -> Conversation:
        """Retitle a conversation. The only field on one that is mutable.

        Raises:
            ConversationNotFoundError: If this project holds no such live conversation.
            ValueError: If the title is too long.
        """
        cleaned = clean_title(title)
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            self.require(conn, conversation_id)
            conn.execute(
                "UPDATE conversation SET title = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                (cleaned, now, conversation_id, self.handle.id),
            )
            touch_project(conn, self.handle.id, now)
            return self.require(conn, conversation_id)

    def delete(self, conversation_id: str) -> Conversation:
        """Soft-delete a conversation (D22, D25).

        Nothing cascades. The row and every message in it stay exactly as they were, and the
        conversation leaves every read path at once because they all filter one predicate.

        Raises:
            ConversationNotFoundError: If this project holds no such live conversation.
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            self.require(conn, conversation_id)
            conn.execute(
                "UPDATE conversation SET deleted_at = ?, updated_at = ? "
                "WHERE id = ? AND project_id = ?",
                (now, now, conversation_id, self.handle.id),
            )
            touch_project(conn, self.handle.id, now)
            return self.require(conn, conversation_id, include_deleted=True)

    def restore(self, conversation_id: str) -> Conversation:
        """Bring a soft-deleted conversation back, with every turn it had.

        Restoring a live conversation is a no-op rather than an error - the rule
        ``DocumentStore.restore`` and ``EntryStore.restore`` both follow.
        """
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            current = self.require(conn, conversation_id, include_deleted=True)
            if current.deleted_at is None:
                return current
            conn.execute(
                "UPDATE conversation SET deleted_at = NULL, updated_at = ? "
                "WHERE id = ? AND project_id = ?",
                (now, conversation_id, self.handle.id),
            )
            touch_project(conn, self.handle.id, now)
            return self.require(conn, conversation_id)

    def append(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        context: dict[str, Any] | None = None,
        provider: str = "",
        model: str = "",
        usage: dict[str, int] | None = None,
        stop_reason: str = "",
        error_code: str = "",
    ) -> ChatMessage:
        """Append one turn. The only way a ``message`` row is ever written.

        ``ord`` is allocated here, inside the transaction, so two appends racing produce two
        turns or one failure - never one turn silently overwriting another.

        Raises:
            ConversationNotFoundError: If this project holds no such live conversation. A
                deleted conversation refuses an append: it is away, and a turn arriving into it
                would be a record nobody can read.
            ValueError: For a role outside :data:`STORED_ROLES` or content over the limit.
        """
        if role not in STORED_ROLES:
            raise ValueError(
                f"{role!r} is not a role a stored turn may carry; "
                f"expected one of {', '.join(sorted(STORED_ROLES))}"
            )
        checked = _checked_content(content)
        message_id = new_id(IdPrefix.MESSAGE)
        now = utc_now()
        with self.handle.connect() as conn, transaction(conn):
            self.require(conn, conversation_id)
            row = conn.execute(
                "SELECT COALESCE(MAX(ord), -1) AS highest FROM message WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            conn.execute(
                "INSERT INTO message (id, conversation_id, ord, role, content, context_json, "
                "provider, model, usage_json, stop_reason, error_code, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    conversation_id,
                    int(row["highest"]) + 1,
                    role,
                    checked,
                    _dump(context or {}),
                    provider,
                    model,
                    _dump(usage or {}),
                    stop_reason,
                    error_code,
                    now,
                ),
            )
            # A turn is what moves a conversation, which is what the list sorts on.
            conn.execute(
                "UPDATE conversation SET updated_at = ? WHERE id = ? AND project_id = ?",
                (now, conversation_id, self.handle.id),
            )
            touch_project(conn, self.handle.id, now)
            stored = conn.execute(
                f"SELECT {_MESSAGE_COLUMNS} FROM message WHERE id = ?", (message_id,)
            ).fetchone()
            return _message_from_row(stored)

    # -- internals ----------------------------------------------------------------------------

    def require(
        self,
        conn: sqlite3.Connection,
        conversation_id: str,
        *,
        include_deleted: bool = False,
    ) -> Conversation:
        """Read one conversation on an open connection, or refuse.

        Public because every write in this module calls it *inside* its own transaction, before
        anything is written - a refused write must leave nothing behind.

        Raises:
            ConversationNotFoundError: As :meth:`get`.
        """
        predicate = "" if include_deleted else f" AND {_LIVE}"
        row = conn.execute(
            f"SELECT {_CONVERSATION_COLUMNS}, "
            "(SELECT COUNT(*) FROM message WHERE message.conversation_id = conversation.id) "
            "AS message_count FROM conversation "
            f"WHERE id = ? AND project_id = ?{predicate}",
            (conversation_id, self.handle.id),
        ).fetchone()
        if row is None:
            raise ConversationNotFoundError(
                f"no conversation {conversation_id!r} in project {self.handle.id}"
            )
        return _conversation_from_row(row, message_count=int(row["message_count"]))

    def _list(self, *, deleted: bool) -> list[Conversation]:
        predicate = "deleted_at IS NOT NULL" if deleted else _LIVE
        with self.handle.connect() as conn:
            rows = conn.execute(
                f"SELECT {_CONVERSATION_COLUMNS}, "
                "(SELECT COUNT(*) FROM message WHERE message.conversation_id = conversation.id) "
                "AS message_count FROM conversation "
                f"WHERE project_id = ? AND {predicate} "
                "ORDER BY updated_at DESC, created_at DESC, id",
                (self.handle.id,),
            ).fetchall()
        return [
            _conversation_from_row(row, message_count=int(row["message_count"])) for row in rows
        ]
