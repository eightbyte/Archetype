"""The chat half of the ``/api`` router, and the one thing that streams (P4-9, P4-10).

A third route module on the `C1` precedent - the prefix, the error envelope, and the ordering
guarantee belong to the API, and a fourth thousand-line file does not. ``create_app`` includes it
alongside the manuscript's and the bible's, and the static mount is still registered last.

What is here that is nowhere else in this project: **a WebSocket**. api-contract section 12 has
reserved one since Phase 1 and D11 chose it, for the reason this phase exercises - a long answer
to a question the writer has changed their mind about is exactly when they reach for cancel, and
cancel needs a channel that carries a frame *back* while an answer is arriving.

Three rules govern it, and each is written down because each is one small step from being broken.

**One deliberate ask is one provider call** (D13, ruling 6). There is no retry, no reconnect, no
regenerate, and no frame that spends a token without the writer having pressed something. The
autosave backoff ladder is right there and is exactly wrong here: retrying a save costs nothing
and protects the writer's words, and retrying a completion costs money and protects nothing.

**The socket carries D32's five events and nothing else.** Not a sixth type for "your message was
saved", not an envelope wrapped round them. One vocabulary, shared with Phase 6, extended there
and never replaced - so a client that needs the persisted ids re-reads
``GET /api/conversations/{cid}`` once the stream terminates, which is one small request and is
always right. The terminal event is sent **after** the turn is persisted, so a client that refetches
on ``done`` cannot beat the row it is looking for.

**Everything that is not a provider failure closes the socket instead of pretending to be one.**
Ruling 4's taxonomy is closed at six codes and every one of them is about a provider. A malformed
frame, a conversation that is not there, a selection in a chapter that has since been deleted -
none of those is a provider failure, and filing one as ``provider_refused`` would put a lie in the
one column a writer consults when something went wrong. They close the socket with a reason.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from ..bible.entries import EntryNotFoundError
from ..chat.conversations import ChatMessage, ConversationNotFoundError, ConversationStore
from ..config import Settings
from ..llm.budget import check_budget, effective_budget
from ..llm.context import ComposedContext, compose, history_from
from ..llm.port import (
    CompletionRequest,
    LLMProvider,
    Message,
    ProviderError,
    StreamDelta,
    StreamDone,
    StreamError,
    StreamEvent,
    StreamUsage,
)
from ..manuscript.anchors.resolve import AnchorRangeError
from ..manuscript.documents import DocumentNotFoundError
from ..manuscript.projection import InvalidDocumentError
from ..projects.store import ProjectHandle
from .chat_schemas import (
    AskFrame,
    ChatMessageOut,
    ComposedContextOut,
    ContextPreviewIn,
    ConversationCreateIn,
    ConversationDetailOut,
    ConversationListOut,
    ConversationOut,
    ConversationRenameIn,
    parse_client_frame,
)
from .deps import (
    ProviderFactory,
    get_locator,
    get_provider_factory,
    get_settings,
    open_project,
)
from .errors import error_responses

__all__ = ["router"]

logger = logging.getLogger("archetype.api.chat")

router = APIRouter(prefix="/api")

#: How much of a close reason a WebSocket close frame can carry. The frame's payload is capped at
#: 125 bytes and the code takes two of them; this leaves room for the encoder rather than sitting
#: exactly on the edge. A refusal the writer can act on fits easily.
_MAX_CLOSE_REASON_BYTES = 120

#: What a composition can fail on. Each is a real condition rather than a client bug - a chapter
#: deleted since the writer selected in it, a range that no longer has an honest place in the
#: text, an entry somebody removed - and none of them is a provider failure, so none of them may
#: borrow one of ruling 4's six codes.
_CONTEXT_REFUSALS = (
    AnchorRangeError,
    DocumentNotFoundError,
    EntryNotFoundError,
    InvalidDocumentError,
)


def _store(handle: ProjectHandle) -> ConversationStore:
    return ConversationStore(handle)


# -- conversations (P4-9) -----------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/conversations",
    tags=["chat"],
    summary="This project's conversations, newest first",
    response_model=ConversationListOut,
    responses=error_responses(404),
)
def list_conversations(request: Request, project_id: str) -> ConversationListOut:
    """The live conversations, most recently used first."""
    handle = open_project(request, project_id)
    return ConversationListOut(
        conversations=[ConversationOut.of(row) for row in _store(handle).list()]
    )


@router.get(
    "/projects/{project_id}/conversations/deleted",
    tags=["chat"],
    summary="Deleted conversations, for restoring one",
    response_model=ConversationListOut,
    responses=error_responses(404),
)
def list_deleted_conversations(request: Request, project_id: str) -> ConversationListOut:
    """The restore surface (D22, D25).

    A soft delete whose only recovery path is a toast the writer has to catch is not a recovery
    path - it is a delete with a grace period. Chapters and entries each got this list for the
    same reason (deviation ``C1``).
    """
    handle = open_project(request, project_id)
    return ConversationListOut(
        conversations=[ConversationOut.of(row) for row in _store(handle).list_deleted()]
    )


@router.post(
    "/projects/{project_id}/conversations",
    tags=["chat"],
    summary="Start a conversation",
    status_code=status.HTTP_201_CREATED,
    response_model=ConversationOut,
    responses=error_responses(404, 422),
)
def create_conversation(
    request: Request, project_id: str, body: ConversationCreateIn
) -> ConversationOut:
    """Start one. An empty title is fine - the panel names it from its first question."""
    handle = open_project(request, project_id)
    return ConversationOut.of(_store(handle).create(body.title))


@router.get(
    "/conversations/{conversation_id}",
    tags=["chat"],
    summary="One conversation with its turns",
    response_model=ConversationDetailOut,
    responses=error_responses(404),
)
def get_conversation(request: Request, conversation_id: str) -> ConversationDetailOut:
    """One conversation and every turn in it, in ``ord``.

    This is what makes a reload keep what the writer paid for (D30): the transcript, what each
    answer cost, and the context that produced it all come back from the project file.
    """
    handle = get_locator(request).resolve_conversation(conversation_id)
    store = _store(handle)
    return ConversationDetailOut(
        conversation=ConversationOut.of(store.get(conversation_id)),
        messages=[ChatMessageOut.of(row) for row in store.messages(conversation_id)],
    )


@router.patch(
    "/conversations/{conversation_id}",
    tags=["chat"],
    summary="Rename a conversation",
    response_model=ConversationOut,
    responses=error_responses(404, 422),
)
def rename_conversation(
    request: Request, conversation_id: str, body: ConversationRenameIn
) -> ConversationOut:
    handle = get_locator(request).resolve_conversation(conversation_id)
    return ConversationOut.of(_store(handle).rename(conversation_id, body.title))


@router.delete(
    "/conversations/{conversation_id}",
    tags=["chat"],
    summary="Soft-delete a conversation",
    response_model=ConversationOut,
    responses=error_responses(404),
)
def delete_conversation(request: Request, conversation_id: str) -> ConversationOut:
    """Soft delete (D22, D25). Every turn stays; the conversation leaves every read path."""
    handle = get_locator(request).resolve_conversation(conversation_id)
    return ConversationOut.of(_store(handle).delete(conversation_id))


@router.post(
    "/conversations/{conversation_id}/restore",
    tags=["chat"],
    summary="Restore a deleted conversation",
    response_model=ConversationOut,
    responses=error_responses(404),
)
def restore_conversation(request: Request, conversation_id: str) -> ConversationOut:
    handle = get_locator(request).resolve_conversation(conversation_id)
    return ConversationOut.of(_store(handle).restore(conversation_id))


# -- the composed context, before it is sent (P4-10, ruling 5) -----------------------------------


@router.post(
    "/conversations/{conversation_id}/context",
    tags=["chat"],
    summary="What would be sent, without sending it",
    response_model=ComposedContextOut,
    responses=error_responses(404, 422),
)
def preview_context(
    request: Request, conversation_id: str, body: ContextPreviewIn
) -> ComposedContextOut:
    """Compose the context and report it - **spending nothing** (ruling 5).

    "What is being sent is shown before it is sent" needs a server surface, because the alternative
    is a second composer in the browser that agrees with this one until it does not (deviation
    ``C2``). This is that surface: the same :func:`~archetype.llm.context.compose` the socket
    calls, the same estimate the budget check will use, and no provider involved at all.

    An over-budget context is **reported** here rather than refused. The refusal belongs to the
    ask; the preview's whole job is to show the writer the number before they spend it.
    """
    handle = get_locator(request).resolve_conversation(conversation_id)
    store = _store(handle)
    store.get(conversation_id)
    settings = get_settings(request)
    composed = compose(
        handle,
        prompt=body.prompt,
        selector=body.context.to_selector(),
        history=_history(store.messages(conversation_id)),
    )
    return ComposedContextOut.of(
        composed, max_tokens=settings.llm_max_tokens, budget=_budget_for(request, settings)
    )


def _budget_for(request: Request, settings: Settings) -> int:
    """The effective budget, or the writer's own when no provider can be built.

    An unconfigured provider must not stop the preview from drawing: the writer composing a
    question before setting a key is a perfectly ordinary sequence, and the number they are shown
    is still the one their own budget will be measured against.
    """
    try:
        provider = get_provider_factory(request)(settings)
    except ProviderError:
        return settings.llm_context_budget
    return effective_budget(provider.capabilities, settings.llm_context_budget)


def _history(messages: Sequence[ChatMessage]) -> tuple[Message, ...]:
    """The transcript in the port's vocabulary, ready to be composed in."""
    return history_from([(message.role, message.content) for message in messages])


# -- the socket (P4-10, D11, D32) ----------------------------------------------------------------


@router.websocket("/conversations/{conversation_id}/stream")
async def conversation_stream(websocket: WebSocket, conversation_id: str) -> None:
    """One conversation's stream: ``ask`` and ``cancel`` in, D32's events out.

    The connection is **accepted first and closed with a reason** if the conversation is not
    there, rather than refused during the handshake: a browser is told very little about a
    handshake that failed, and the reason is the useful half of the answer.

    Every database call is handed to a thread. SQLite is synchronous and its busy timeout is five
    seconds; a write lock held by an autosave landing at the same moment would otherwise stall the
    event loop and, with it, the answer arriving on this socket.
    """
    await websocket.accept()
    locator = get_locator(websocket)
    settings = get_settings(websocket)
    build = get_provider_factory(websocket)

    try:
        handle = await asyncio.to_thread(locator.resolve_conversation, conversation_id)
        store = _store(handle)
        await asyncio.to_thread(store.get, conversation_id)
    except ConversationNotFoundError as exc:
        logger.info("chat socket refused for %s: %s", conversation_id, exc)
        await _close(websocket, "no such conversation in this workspace")
        return

    frames: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    receiver = asyncio.create_task(_receive(websocket, frames))
    try:
        while True:
            frame = await frames.get()
            if frame is None:
                break
            try:
                parsed = parse_client_frame(frame)
            except ValidationError:
                await _close(websocket, "that frame is not one this build understands")
                break
            if not isinstance(parsed, AskFrame):
                # A cancel with nothing in flight. Late rather than wrong - the answer had already
                # finished - and answering it with a closed socket would punish a race.
                continue
            if not await _run_turn(
                websocket,
                frames=frames,
                handle=handle,
                store=store,
                conversation_id=conversation_id,
                settings=settings,
                build=build,
                ask=parsed,
            ):
                break
    finally:
        receiver.cancel()
        with contextlib.suppress(BaseException):
            await receiver


async def _run_turn(
    websocket: WebSocket,
    *,
    frames: asyncio.Queue[dict[str, Any] | None],
    handle: ProjectHandle,
    store: ConversationStore,
    conversation_id: str,
    settings: Settings,
    build: ProviderFactory,
    ask: AskFrame,
) -> bool:
    """One ask, one answer, one row. Returns False when the socket should close.

    The order is deliberate and each step is where it is for a reason:

    1. **compose**, which can fail on a deleted chapter or an impossible range - before anything
       is written and before anything is spent;
    2. **persist the question**, so a failure from here on is a turn the writer can see rather
       than a gap they have to remember;
    3. **build the provider** and **check the budget**, both of which refuse without calling
       anything - the fake records zero calls when they fire, which is what P4-10 asserts;
    4. **stream**, accumulating;
    5. **persist the answer** with its usage, its stop reason, and the context that produced it;
    6. **send the terminator**, last, so a client refetching on ``done`` finds the row.
    """
    try:
        history = _history(await asyncio.to_thread(store.messages, conversation_id))
        composed = await asyncio.to_thread(
            compose,
            handle,
            prompt=ask.prompt,
            selector=ask.context.to_selector(),
            history=history,
        )
    except _CONTEXT_REFUSALS as exc:
        logger.info("chat context refused for %s: %s", conversation_id, exc)
        await _close(websocket, str(exc))
        return False

    await asyncio.to_thread(store.append, conversation_id, role="user", content=ask.prompt)

    request = CompletionRequest(
        messages=composed.messages,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
    )

    try:
        provider: LLMProvider = build(settings)
    except ProviderError as exc:
        await _finish(
            websocket,
            store=store,
            conversation_id=conversation_id,
            composed=composed,
            settings=settings,
            provider_name=settings.llm_provider,
            text="",
            terminal=StreamError(code=exc.code, message=exc.message),
        )
        return True

    try:
        check_budget(
            request,
            provider.capabilities,
            settings.llm_context_budget,
            provider=provider.name,
        )
    except ProviderError as exc:
        await _finish(
            websocket,
            store=store,
            conversation_id=conversation_id,
            composed=composed,
            settings=settings,
            provider_name=provider.name,
            text="",
            terminal=StreamError(code=exc.code, message=exc.message),
        )
        return True

    return await _pump(
        websocket,
        frames=frames,
        store=store,
        conversation_id=conversation_id,
        settings=settings,
        provider=provider,
        request=request,
        composed=composed,
    )


async def _pump(
    websocket: WebSocket,
    *,
    frames: asyncio.Queue[dict[str, Any] | None],
    store: ConversationStore,
    conversation_id: str,
    settings: Settings,
    provider: LLMProvider,
    request: CompletionRequest,
    composed: ComposedContext,
) -> bool:
    """Read the provider's stream onto the socket, watching for a cancel the whole time."""
    chunks: list[str] = []
    usage: dict[str, int] = {}
    terminal: StreamDone | StreamError | None = None
    deferred: list[dict[str, Any] | None] = []
    keep_open = True

    try:
        iterator = provider.stream(request).__aiter__()
    except ProviderError as exc:
        await _finish(
            websocket,
            store=store,
            conversation_id=conversation_id,
            composed=composed,
            settings=settings,
            provider_name=provider.name,
            text="",
            terminal=StreamError(code=exc.code, message=exc.message),
        )
        return True

    cancel = asyncio.create_task(_await_cancel(frames, deferred))
    try:
        while terminal is None:
            reading = asyncio.create_task(_next_event(iterator))
            finished, _ = await asyncio.wait({reading, cancel}, return_when=asyncio.FIRST_COMPLETED)
            if cancel in finished:
                await _abandon(reading)
                # `cancelled` is written by whoever closed the stream and by nobody else
                # (providers.md section 3). This is that place.
                terminal = StreamDone(stop_reason="cancelled")
                keep_open = cancel.result() is not None
                break
            try:
                event = reading.result()
            except ProviderError as exc:
                terminal = StreamError(code=exc.code, message=exc.message)
                break
            if event is None:
                # A stream that ended without saying so. What a dropped socket looks like from
                # the inside (providers.md section 4), and the partial answer is still real.
                terminal = StreamError(
                    code="provider_unavailable",
                    message="the answer stopped arriving before the provider said it had finished",
                )
                break
            if isinstance(event, StreamDone | StreamError):
                terminal = event
                break
            if isinstance(event, StreamDelta):
                chunks.append(event.text)
            elif isinstance(event, StreamUsage):
                usage = {
                    "input_tokens": event.usage.input_tokens,
                    "output_tokens": event.usage.output_tokens,
                }
            await websocket.send_json(event.model_dump(mode="json"))
    finally:
        await _abandon(cancel)
        await _aclose(iterator)

    for frame in deferred:
        frames.put_nowait(frame)

    await _finish(
        websocket,
        store=store,
        conversation_id=conversation_id,
        composed=composed,
        settings=settings,
        provider_name=provider.name,
        text="".join(chunks),
        terminal=terminal,
        usage=usage,
        send=keep_open,
    )
    return keep_open


async def _finish(
    websocket: WebSocket,
    *,
    store: ConversationStore,
    conversation_id: str,
    composed: ComposedContext,
    settings: Settings,
    provider_name: str,
    text: str,
    terminal: StreamDone | StreamError,
    usage: dict[str, int] | None = None,
    send: bool = True,
) -> None:
    """Persist the assistant turn, then send the terminator. In that order, always.

    A failed turn is persisted too, carrying its ``error_code`` and whatever text had arrived: a
    turn that went wrong is visible in the history rather than being a gap the writer has to
    remember, and the code is what says why.
    """
    stop_reason = terminal.stop_reason if isinstance(terminal, StreamDone) else ""
    error_code = terminal.code if isinstance(terminal, StreamError) else ""
    await asyncio.to_thread(
        store.append,
        conversation_id,
        role="assistant",
        content=text,
        context=composed.record(),
        provider=provider_name,
        model=settings.llm_model,
        usage=usage or {},
        stop_reason=stop_reason,
        error_code=error_code,
    )
    if send:
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.send_json(terminal.model_dump(mode="json"))


# -- socket plumbing -----------------------------------------------------------------------------


async def _receive(websocket: WebSocket, frames: asyncio.Queue[dict[str, Any] | None]) -> None:
    """Read client frames onto the queue until the socket closes.

    One reader for the socket's whole life, so a cancel arriving while an answer is streaming has
    somewhere to land. ``None`` is the sentinel for "the client has gone".
    """
    try:
        while True:
            frames.put_nowait(await websocket.receive_json())
    except (WebSocketDisconnect, RuntimeError, ValueError):
        # A closed socket, a frame that is not JSON, or Starlette refusing to read from a
        # disconnected connection. All three mean the same thing to the loop above.
        frames.put_nowait(None)


async def _await_cancel(
    frames: asyncio.Queue[dict[str, Any] | None], deferred: list[dict[str, Any] | None]
) -> dict[str, Any] | None:
    """Resolve when a cancel arrives - or when the client vanishes, which stops a stream too.

    Anything else that arrives mid-answer is set aside rather than dropped, and re-queued when the
    turn ends. A frame taken off the queue and thrown away is a question the writer asked and never
    got an answer to.
    """
    while True:
        frame = await frames.get()
        if frame is None or (isinstance(frame, dict) and frame.get("type") == "cancel"):
            return frame
        deferred.append(frame)


async def _next_event(iterator: AsyncIterator[StreamEvent]) -> StreamEvent | None:
    """The next event, or ``None`` when the provider's stream has simply stopped."""
    try:
        return await iterator.__anext__()
    except StopAsyncIteration:
        return None


async def _abandon(task: asyncio.Task[Any]) -> None:
    """Cancel a task nobody is going to read, and wait for it to notice.

    Awaiting it matters: a task cancelled and never awaited is one whose failure asyncio reports
    from the garbage collector, in a traceback that names neither the ask nor the socket.
    """
    task.cancel()
    with contextlib.suppress(BaseException):
        await task


async def _aclose(iterator: AsyncIterator[StreamEvent]) -> None:
    """Shut a provider's stream down, whether or not it is a generator.

    The port declares an ``AsyncIterator`` and an adapter may implement it either way (P4-2), so
    the close is asked for and not assumed - and a stream that fails while being closed has
    already told us everything it is going to.
    """
    close = getattr(iterator, "aclose", None)
    if close is None:
        return
    with contextlib.suppress(BaseException):
        await close()


async def _close(websocket: WebSocket, reason: str) -> None:
    """Close with a policy-violation code and a reason short enough to travel.

    Not an ``error`` event: ruling 4's six codes are all about a provider, and a conversation that
    is not there is not a provider failure (see the module docstring).
    """
    trimmed = reason.encode("utf-8")[:_MAX_CLOSE_REASON_BYTES].decode("utf-8", "ignore")
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=trimmed)
