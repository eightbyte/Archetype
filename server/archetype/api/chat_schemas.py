"""Wire shapes for the chat routes and the one socket (P4-9, P4-10).

The Phase 1 rules apply unchanged (:mod:`archetype.api.schemas`): pydantic here, mirrored
TypeScript in ``web/src/api/types.ts``, the two held together by the contract fixtures, and every
response schema **extension-only** while every request model is closed (``extra="forbid"``).

Two things in this file are not like the others.

**The client frames are request models for something that is not a request.** ``ask`` and
``cancel`` arrive over a WebSocket rather than through FastAPI's body parsing, so they are
validated by hand where they arrive - but they are validated by the *same* kind of model, with the
same closure, so a frame carrying a field this build has never heard of is refused rather than
half-understood.

**The stream events are not here at all.** They are the port's own shapes
(:mod:`archetype.llm.port`), dumped onto the socket unchanged, because D32 fixes **one** vocabulary
over one socket shared with Phase 6. A second copy of them in this file would be the place the two
drift apart, and the client already mirrors the port directly in ``web/src/api/stream.ts``.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import Field, TypeAdapter, field_validator, model_validator

from ..chat.conversations import MAX_TITLE_CHARS, ChatMessage, Conversation, clean_title
from ..llm.context import ComposedContext, ContextPart, ContextSelector
from .schemas import Wire

__all__ = [
    "MAX_ENTRY_REFS",
    "MAX_PROMPT_CHARS",
    "AskFrame",
    "CancelFrame",
    "ChatMessageOut",
    "ClientFrame",
    "CLIENT_FRAME_ADAPTER",
    "ComposedContextOut",
    "ContextPartOut",
    "ContextPreviewIn",
    "ContextSelectorIn",
    "ConversationCreateIn",
    "ConversationDetailOut",
    "ConversationListOut",
    "ConversationOut",
    "ConversationRenameIn",
    "UsageOut",
    "parse_client_frame",
]

#: The longest question the composer will accept. A question with a passage pasted into it is a
#: legitimate thing to send; a manuscript is not, and the store's own limit is two orders of
#: magnitude larger so that this refusal happens at the edge with a sentence about questions.
MAX_PROMPT_CHARS: Final[int] = 20_000

#: How many bible entries one request may name. The writer names them one at a time from the
#: panel (D31's "what they pointed at and named"), so this is a guard against a malformed client
#: rather than a limit anybody will meet.
MAX_ENTRY_REFS: Final[int] = 25


# -- conversations (P4-9) -----------------------------------------------------------------------


class UsageOut(Wire):
    """What one turn cost, as the provider reported it.

    Both zero means **not reported**, not free (``specs/providers.md`` section 2). The panel says
    so rather than drawing a confident zero, which is why the field is always present rather than
    absent when unknown - an absent field is a shape change, and this is a fact about the answer.
    """

    input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def of(cls, usage: dict[str, int]) -> UsageOut:
        return cls(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )


class ChatMessageOut(Wire):
    """One stored turn.

    ``context`` is what was composed to produce it (ruling 5) and is empty on a user turn: the
    user turn is the question, and what the *question* was sent with is recorded on the answer it
    produced. ``stop_reason`` is empty until a turn finishes and is ``cancelled`` when the writer
    stopped it; ``error_code`` is one of ruling 4's six when it failed. A failed turn is a stored
    turn, so the history says what went wrong rather than leaving a gap.
    """

    id: str
    conversation_id: str
    ord: int
    role: str
    content: str
    context: dict[str, Any]
    provider: str
    model: str
    usage: UsageOut
    stop_reason: str
    error_code: str
    created_at: str

    @classmethod
    def of(cls, message: ChatMessage) -> ChatMessageOut:
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            ord=message.ord,
            role=message.role,
            content=message.content,
            context=message.context,
            provider=message.provider,
            model=message.model,
            usage=UsageOut.of(message.usage),
            stop_reason=message.stop_reason,
            error_code=message.error_code,
            created_at=message.created_at,
        )


class ConversationOut(Wire):
    """One chat, without its turns. What the conversation list is made of."""

    id: str
    project_id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str
    deleted_at: str | None

    @classmethod
    def of(cls, conversation: Conversation) -> ConversationOut:
        return cls(
            id=conversation.id,
            project_id=conversation.project_id,
            title=conversation.title,
            message_count=conversation.message_count,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            deleted_at=conversation.deleted_at,
        )


class ConversationListOut(Wire):
    """``GET /api/projects/{pid}/conversations`` and its deleted twin."""

    conversations: list[ConversationOut]


class ConversationDetailOut(Wire):
    """``GET /api/conversations/{cid}`` - one conversation and every turn in it, in ``ord``."""

    conversation: ConversationOut
    messages: list[ChatMessageOut]


class ConversationCreateIn(Wire):
    """An empty title is legitimate: the panel names a conversation from its first question."""

    title: str = Field(default="", max_length=MAX_TITLE_CHARS)

    @field_validator("title")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_title(value)


class ConversationRenameIn(Wire):
    """The only field on a conversation that is mutable."""

    title: str = Field(max_length=MAX_TITLE_CHARS)

    @field_validator("title")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_title(value)


# -- the composed context (P4-10, ruling 5) ------------------------------------------------------


class ContextSelectorIn(Wire):
    """What the writer pointed at and named.

    A range is a ProseMirror range and the **server** derives the text from stored content: this
    model carries no quote, because a client that could send one could send a quote the manuscript
    does not contain (``specs/anchors.md`` section 8, the same rule an anchor is created under).
    """

    document_id: str = ""
    from_pos: int | None = Field(default=None, ge=0)
    to_pos: int | None = Field(default=None, ge=0)
    include_chapter: bool = True
    entry_ids: list[str] = Field(default_factory=list, max_length=MAX_ENTRY_REFS)
    include_history: bool = True

    @model_validator(mode="after")
    def _coherent(self) -> ContextSelectorIn:
        if (self.from_pos is None) != (self.to_pos is None):
            raise ValueError("a selection needs both from_pos and to_pos, or neither")
        if self.from_pos is not None and not self.document_id:
            raise ValueError("a selection needs the document it is in")
        return self

    def to_selector(self) -> ContextSelector:
        return ContextSelector(
            document_id=self.document_id,
            from_pos=self.from_pos,
            to_pos=self.to_pos,
            include_chapter=self.include_chapter,
            entry_ids=tuple(self.entry_ids),
            include_history=self.include_history,
        )


class ContextPartOut(Wire):
    """One thing that was included, and what it cost.

    Every key is present whatever the ``kind`` - the P3-11 rule, because a shape whose key set
    depends on its own values is a renderer full of branches. ``excerpt`` is the part's text when
    it is short enough to record and empty when it is not; ``chars`` always says how big it really
    was, so what was withheld is visible rather than implied.
    """

    kind: str
    label: str
    ref_id: str
    chars: int
    estimated_tokens: int
    excerpt: str

    @classmethod
    def of(cls, part: ContextPart) -> ContextPartOut:
        return cls(**part.record())


class ComposedContextOut(Wire):
    """What would be sent, before it is sent (ruling 5).

    ``fits`` is the budget check's own answer computed without calling anything: a request over
    budget is a **hard refusal** naming what was too big, never a truncation (ruling 7), so the
    panel can say so before the writer spends anything. ``budget`` of zero means no budget is in
    force - our own check is off and the provider declared no window.
    """

    parts: list[ContextPartOut]
    estimated_tokens: int
    max_tokens: int
    budget: int
    fits: bool

    @classmethod
    def of(cls, composed: ComposedContext, *, max_tokens: int, budget: int) -> ComposedContextOut:
        estimate = composed.estimated_tokens
        return cls(
            parts=[ContextPartOut.of(part) for part in composed.parts],
            estimated_tokens=estimate,
            max_tokens=max_tokens,
            budget=budget,
            fits=not budget or estimate + max_tokens <= budget,
        )


class ContextPreviewIn(Wire):
    """``POST /api/conversations/{cid}/context`` - compose without sending."""

    prompt: str = Field(default="", max_length=MAX_PROMPT_CHARS)
    context: ContextSelectorIn = Field(default_factory=ContextSelectorIn)


# -- the client frames (P4-10) -------------------------------------------------------------------


class AskFrame(Wire):
    """One deliberate ask - and one bill (D13, ruling 6).

    There is no ``regenerate``, no ``retry``, and no frame that spends tokens without the writer
    having pressed something. That is the rule this vocabulary is small on purpose to keep.
    """

    type: Literal["ask"] = "ask"
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    context: ContextSelectorIn = Field(default_factory=ContextSelectorIn)


class CancelFrame(Wire):
    """Stop the answer that is arriving. D11's stated reason for choosing a socket."""

    type: Literal["cancel"] = "cancel"


#: What a client may send. Discriminated on ``type``, exactly as the port's stream union is - and
#: refused when it is not one of these, for the server half of D32's asymmetry: an unrecognised
#: frame going *to* the server is a client this build cannot serve, and answering it by guessing
#: is how tokens get spent on something nobody asked for.
ClientFrame = Annotated[AskFrame | CancelFrame, Field(discriminator="type")]

CLIENT_FRAME_ADAPTER: Final[TypeAdapter[ClientFrame]] = TypeAdapter(ClientFrame)


def parse_client_frame(payload: Any) -> ClientFrame:
    """Validate one client frame.

    Raises:
        pydantic.ValidationError: If ``type`` is missing, unknown, or the frame does not match
            that type's shape.
    """
    return CLIENT_FRAME_ADAPTER.validate_python(payload)
