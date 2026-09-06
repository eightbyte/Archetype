"""Composing what the model is given (P4-10, plan section 2 ruling 5).

This module is the answer to "what did it actually see?", and it is deliberately **dumb**:

    The composer takes what the writer **pointed at** and what they **named**. It searches for
    nothing, ranks nothing, and guesses at nothing.

That is not a simplification to be improved on later - it is the phase's own boundary (section 1,
"it is not retrieval"). There is no index until Phase 5, so a composer that started deciding which
bible entries were *relevant* would be shipping retrieval with no embeddings, no chunking, and no
way to measure whether it retrieved the right thing. The preview (ruling 5) is what makes a
composer that started guessing immediately obvious on screen.

It lives here rather than in a route for the reason ``bible/timeline.py`` lives outside one:
composition that is not HTTP does not belong in a request handler, and Phase 6's agent needs the
same answer without a request.

What it produces
----------------

:class:`ComposedContext` carries two things and they are for two different readers:

* ``messages`` - the port's vocabulary, handed straight to a :class:`CompletionRequest`;
* ``parts`` - one row per thing that was included, with what it is, what it refers to, how big it
  was, and what it is estimated to cost. That is what the panel shows **before** sending and what
  :meth:`ComposedContext.record` stores on the message afterwards, because the outline's standing
  invariant is that the composed context is recorded and Phase 4 has no run record to put it on.

``estimated_tokens`` is computed over the messages exactly as :mod:`archetype.llm.budget` computes
it, so the number the writer is shown before sending is the number the budget check will use. The
per-part figures are indicative and sum to approximately - not exactly - the total, because a
token estimate over three pieces of text is not the estimate over their concatenation.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ..bible.entries import Entry, EntryStore
from ..manuscript.anchors.resolve import extract
from ..manuscript.documents import Document, DocumentStore
from ..manuscript.projection import project
from ..projects.store import ProjectHandle
from .budget import PER_MESSAGE_OVERHEAD, estimate_tokens
from .port import Message

__all__ = [
    "MAX_RECORDED_EXCERPT_CHARS",
    "PART_KINDS",
    "SYSTEM_PROMPT",
    "ComposedContext",
    "ContextPart",
    "ContextSelector",
    "compose",
    "history_from",
]

#: What the assistant is told it is. Short, and deliberately about *reading*: Phase 4 answers
#: questions and proposes replacements a writer accepts (D5, D12). Prompt tuning is explicitly out
#: of scope for 1.0 (outline section 2), so this is a starting point that section 8 assesses by
#: hand rather than a tuned artefact.
SYSTEM_PROMPT: Final[str] = (
    "You are assisting the author of a long narrative work. You are given passages from their "
    "manuscript and entries from their story bible, and you answer questions about them.\n\n"
    "Ground every answer in the text you were given. If the passages do not settle a question, "
    "say so plainly rather than inventing detail - the author will send more. Never rewrite the "
    "manuscript unless you are explicitly asked for a replacement, and when you are, give the "
    "replacement and nothing else. The author owns the words."
)

#: What a part of a composed context can be. Closed, so the panel renders one row per kind and a
#: seventh cannot appear without a decision.
PART_KINDS: Final[tuple[str, ...]] = (
    "instructions",
    "selection",
    "chapter",
    "entry",
    "history",
    "question",
)

#: How much of a part's text is recorded verbatim on the message. A selection and an entry fit
#: inside this and are the crux of diagnosing a wrong answer; a chapter does not, and storing one
#: per turn would put a copy of the manuscript in the project file for every question asked. A
#: part over the limit records an empty ``excerpt`` and its true ``chars``, so what was withheld
#: is visible rather than implied.
MAX_RECORDED_EXCERPT_CHARS: Final[int] = 2_000


@dataclass(frozen=True, slots=True)
class ContextSelector:
    """What the writer pointed at and named - the whole of the composer's input.

    A range is a ProseMirror range against a document, exactly as an anchor's is, and **the
    server derives the text from the stored content**: a client is never asked what the manuscript
    says (``specs/anchors.md`` section 8, applied one module over).

    Every flag exists so the writer can drop a part of the context before sending (P4-13).
    """

    document_id: str = ""
    from_pos: int | None = None
    to_pos: int | None = None
    #: Include the whole chapter the selection is in. Effective only when a document is named.
    include_chapter: bool = True
    #: Bible entries the writer named. Never entries somebody searched for - see the module note.
    entry_ids: tuple[str, ...] = ()
    #: Include the conversation so far. A model is asked to remember nothing (providers.md
    #: section 10), so the history is composed in on the way out or it is not there at all.
    include_history: bool = True

    def record(self) -> dict[str, Any]:
        """The selector as it is stored beside the parts it produced."""
        return {
            "document_id": self.document_id,
            "from_pos": self.from_pos,
            "to_pos": self.to_pos,
            "include_chapter": self.include_chapter,
            "entry_ids": list(self.entry_ids),
            "include_history": self.include_history,
        }


@dataclass(frozen=True, slots=True)
class ContextPart:
    """One thing that was included, what it cost, and enough of it to recognise.

    ``text`` is what actually goes to the model. ``record`` is what is stored and shown, and it
    holds the same key set whatever the kind - a shape whose keys depend on its own values is a
    renderer full of branches (the P3-11 rule, one module over).
    """

    kind: str
    label: str
    text: str
    ref_id: str = ""

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(self.text)

    def record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "ref_id": self.ref_id,
            "chars": self.chars,
            "estimated_tokens": self.estimated_tokens,
            "excerpt": self.text if self.chars <= MAX_RECORDED_EXCERPT_CHARS else "",
        }


@dataclass(frozen=True, slots=True)
class ComposedContext:
    """What will be sent, in both the shapes it is needed in."""

    parts: tuple[ContextPart, ...]
    messages: tuple[Message, ...]
    selector: ContextSelector = field(default_factory=ContextSelector)

    @property
    def estimated_tokens(self) -> int:
        """The whole request's estimate, computed as :mod:`archetype.llm.budget` computes it.

        Identical to ``estimate_request_tokens`` for any Phase 4 request, because Phase 4 declares
        no tools (D31) - so the number shown before sending is the number the refusal uses.
        """
        return sum(PER_MESSAGE_OVERHEAD + estimate_tokens(m.content) for m in self.messages)

    def record(self) -> dict[str, Any]:
        """What is stored in ``message.context_json`` (ruling 5)."""
        return {
            "selector": self.selector.record(),
            "parts": [part.record() for part in self.parts],
            "estimated_tokens": self.estimated_tokens,
        }


def history_from(turns: Sequence[tuple[str, str]]) -> tuple[Message, ...]:
    """Stored ``(role, content)`` turns as port messages, skipping the ones with nothing in them.

    A failed turn is stored with its error code and an empty body (P4-10), and sending an empty
    assistant message to a provider is at best noise and at worst a refusal - so it is dropped
    from the *prompt* while staying in the *transcript*, which is where the writer needs it.
    """
    return tuple(
        Message(role=role, content=content)  # type: ignore[arg-type]
        for role, content in turns
        if content.strip() and role in {"user", "assistant", "system"}
    )


def compose(
    handle: ProjectHandle,
    *,
    prompt: str,
    selector: ContextSelector,
    history: Sequence[Message] = (),
    system_prompt: str = SYSTEM_PROMPT,
) -> ComposedContext:
    """Compose one request: the instructions, what was pointed at, what was named, the question.

    Args:
        handle: The project everything is read from.
        prompt: The writer's question, verbatim.
        selector: What to include.
        history: Earlier turns, already in the port's vocabulary. Passed in rather than read here
            so this module never imports the chat store: composition is not persistence, and
            Phase 6 will compose from a run's own turns.
        system_prompt: Overridable so a caller with different instructions is not a second
            composer.

    Raises:
        DocumentNotFoundError: If a named document is not in this project, or is deleted.
        AnchorRangeError: For a range with no honest place in the text - the same refusals an
            anchor's range gets, from the same function.
        EntryNotFoundError: If a named entry is not in this project, or is deleted.
    """
    parts: list[ContextPart] = [
        ContextPart(kind="instructions", label="Instructions", text=system_prompt)
    ]

    document: Document | None = None
    if selector.document_id:
        document = DocumentStore(handle).get(selector.document_id)

    if document is not None and selector.from_pos is not None and selector.to_pos is not None:
        parts.append(_selection_part(document, selector.from_pos, selector.to_pos))

    if document is not None and selector.include_chapter:
        parts.append(_chapter_part(document))

    if selector.entry_ids:
        entries = EntryStore(handle)
        parts.extend(_entry_part(entries.get(entry_id)) for entry_id in selector.entry_ids)

    turns = tuple(history) if selector.include_history else ()
    if turns:
        parts.append(
            ContextPart(
                kind="history",
                label=f"{len(turns)} earlier turn{'s' if len(turns) != 1 else ''}",
                text="\n\n".join(turn.content for turn in turns),
            )
        )

    question = ContextPart(kind="question", label="Your question", text=prompt)
    parts.append(question)

    included = [part for part in parts if part.kind in {"selection", "chapter", "entry"}]
    user_content = "\n\n".join([*(_block(part) for part in included), _block(question)])

    messages = (
        Message(role="system", content=system_prompt),
        *turns,
        Message(role="user", content=user_content),
    )
    return ComposedContext(parts=tuple(parts), messages=messages, selector=selector)


# -- the parts ---------------------------------------------------------------------------------


def _selection_part(document: Document, from_pos: int, to_pos: int) -> ContextPart:
    """The passage the writer pointed at, derived from the stored content and never from a body.

    ``extract`` is the anchor resolver's own function, so a range this composer accepts is a range
    an anchor could be minted over, and a range it refuses is refused with the sentence a writer
    can act on (``specs/anchors.md`` section 8).
    """
    found = extract(project(document.content), from_pos, to_pos)
    return ContextPart(
        kind="selection",
        label=f"Selected passage in {document.meta.title or 'an untitled chapter'}",
        text=found.quote,
        ref_id=document.meta.id,
    )


def _chapter_part(document: Document) -> ContextPart:
    """The chapter the selection is in, as the server's own projection of it (D18).

    ``text_plain`` rather than ``content_json``: the model is being shown prose, and the document
    JSON would spend a third of the budget on node names.
    """
    return ContextPart(
        kind="chapter",
        label=f"Chapter: {document.meta.title or 'Untitled'} ({document.meta.word_count:,} words)",
        text=document.text_plain,
        ref_id=document.meta.id,
    )


def _entry_part(entry: Entry) -> ContextPart:
    """One bible entry, rendered as prose rather than as the JSON it is stored in."""
    lines = [f"{entry.name} ({entry.kind})"]
    if entry.summary:
        lines.append(entry.summary)
    for name, value in entry.attributes.items():
        lines.append(f"{name}: {_attribute_text(value)}")
    if entry.body_md:
        lines.append(entry.body_md)
    return ContextPart(
        kind="entry",
        label=f"{entry.name} ({entry.kind})",
        text="\n".join(lines),
        ref_id=entry.id,
    )


def _attribute_text(value: Any) -> str:
    """One attribute value as a line of text.

    The six field types (D26) are a string, a list of strings, or a small mapping; anything that
    is not already a string is rendered as compact JSON rather than as Python's ``repr``, so a
    list arrives as ``["one", "two"]`` and not as ``['one', 'two']``.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _block(part: ContextPart) -> str:
    """One labelled block in the user message. The label is what makes the answer diagnosable."""
    return f"[{part.label}]\n{part.text}"
