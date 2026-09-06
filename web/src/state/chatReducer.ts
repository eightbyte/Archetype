/**
 * The assistant's conversations, and the answer that is arriving (P4-12, D10, D30, D32).
 *
 * A fifth reducer beside the project's, the document's, the bible's, and the UI's. Its lifetime
 * is the project's — a conversation is stored in the project file and outlives every chapter
 * switch — so it sits where `bibleReducer`'s state sits.
 *
 * ## The stream is state, and that is the whole difficulty
 *
 * Nothing else in this application has had a value that arrives in pieces over a channel that
 * can stop halfway. Out-of-order events, a duplicate `start`, a `usage` that lands after the last
 * fragment, a terminator that never comes, a cancel that races the final delta — every one of
 * them shows up as a transcript that is subtly wrong or a panel that is stuck, and none of them
 * shows up in a test of a component (§ 6).
 *
 * So the rules are here, in a pure function, and they are tested by handing this reducer event
 * sequences directly:
 *
 * * **A fragment is always appended, whenever it arrives.** A `delta` before `start` is text the
 *   provider sent and the writer paid for; dropping it to enforce an ordering nobody promised
 *   would lose words to a rule of our own invention.
 * * **A second `start` does not reset the text.** It marks the model, and nothing else.
 * * **After a terminator, nothing lands.** `done` and `error` are the two ways a stream ends
 *   (`specs/providers.md` § 4) and exactly one of them arrives; anything after one belongs to a
 *   stream this panel is no longer listening to.
 * * **A stream that stops without a terminator is a failure, and the partial answer is kept.**
 *   The socket's close is what says so, because a close is not one of D32's five events and
 *   inventing one for it would file a dropped connection as something a provider did.
 * * **Cancel keeps what arrived.** It is a `stop_reason` and never an `error_code`: a deliberate
 *   act is not a failure (`specs/providers.md` § 3), and the server writes the same answer to
 *   the stored turn.
 *
 * ## What this reducer does not hold
 *
 * The socket. A reducer is pure and holds no `localStorage`, no client, and no DOM, and a
 * WebSocket is all three problems at once — so it lives in the provider as an effect with one
 * owner and an explicit teardown (P4-12).
 *
 * The composed context **preview**, either. That is the server's answer to a question the writer
 * is about to ask, it is re-read whenever what they pointed at changes, and holding a copy of it
 * here would give the two something to disagree about — the rule `bibleReducer` follows for an
 * open entry's citations. What *is* held is the {@link ContextSelection}: the writer's own
 * choices about what to send, which is an input rather than an answer.
 */

import type { ChatMessage, ContextSelector, Conversation } from '../api/types';
import type { ProviderErrorCode, StopReason, StreamEvent, Usage } from '../api/stream';

/** No usage reported. Zero means **not reported**, never free (`specs/providers.md` § 2). */
export const NO_USAGE: Usage = { input_tokens: 0, output_tokens: 0 };

/**
 * What the next question will be sent with.
 *
 * The wire's own shape with every field present, rather than a renamed one: a translation layer
 * between this and `ContextSelector` would exist only to be a place the two could drift apart
 * (`api/types.ts`). A client never sends a quote — the server derives the passage from the text
 * it holds — so this is positions and flags and nothing else.
 */
export type ContextSelection = Required<ContextSelector>;

/** Nothing pointed at and nothing named: the whole chapter is not sent unless a chapter is. */
export const NO_CONTEXT: ContextSelection = {
  document_id: '',
  from_pos: null,
  to_pos: null,
  include_chapter: false,
  entry_ids: [],
  include_history: true,
};

/** The three single-pass actions over an anchored range (P4-14, D12). */
export const REWRITE_ACTIONS = {
  proofread: 'proofread',
  tone: 'tone',
  rewrite: 'rewrite',
} as const;

export type RewriteAction = (typeof REWRITE_ACTIONS)[keyof typeof REWRITE_ACTIONS];

/**
 * An action in flight, and the "before" half of the diff it will produce.
 *
 * The anchor is minted through `AnchorStore` and by no other means (phase-3 § 2 ruling 8), so a
 * suggestion whose passage has since been rewritten reports itself `stale` rather than applying
 * to the wrong text. `before` is what the **server** derived when the anchor was created, which
 * is why it is carried here rather than read out of the editor: the editor's copy is the client's
 * and the anchor's quote is the manuscript's.
 *
 * It is not durable and is not meant to be (D33). An accepted rewrite is an ordinary editor
 * transaction; the durable proposal record, its dedup, and its merge are Phase 7's, and building
 * half of one here would leave that phase inheriting a shape nobody designed for it.
 */
export interface RewriteRequest {
  action: RewriteAction;
  anchorId: string;
  documentId: string;
  /** The passage as the server derived it. The "before". */
  before: string;
}

/**
 * Where an answer has got to.
 *
 * `waiting` is after the ask and before the first token — a real state, and one a writer notices,
 * because a provider's first token can be seconds away and a panel that shows nothing in that
 * gap looks broken.
 */
export type StreamPhase = 'idle' | 'waiting' | 'streaming' | 'done' | 'failed';

/** What went wrong, in the taxonomy the writer is shown. */
export interface StreamFailure {
  /** One of the six provider codes, or `null` when the socket ended without a provider saying so. */
  code: ProviderErrorCode | null;
  message: string;
}

/** The answer that is arriving, or the one that just did. */
export interface StreamState {
  phase: StreamPhase;
  /** The question that produced it, shown as the pending user turn until the reload lands. */
  prompt: string;
  /** Everything that has arrived, concatenated in arrival order. */
  text: string;
  /** What the provider said it was, from `start`. Empty until it says. */
  model: string;
  usage: Usage;
  /** True once a `usage` event has landed — which is what tells zero from "not reported". */
  usageReported: boolean;
  stopReason: StopReason | null;
  failure: StreamFailure | null;
  /** Cancel has been sent and the socket told; fragments already in flight may still land. */
  cancelling: boolean;
}

export const IDLE_STREAM: StreamState = {
  phase: 'idle',
  prompt: '',
  text: '',
  model: '',
  usage: NO_USAGE,
  usageReported: false,
  stopReason: null,
  failure: null,
  cancelling: false,
};

export interface ChatState {
  status: 'loading' | 'ready' | 'failed';
  /** What went wrong loading the list. A failed refresh sets it and keeps the rows. */
  error: string | null;
  /** The live conversations, most recently used first. The server's order, unchanged. */
  conversations: Conversation[];
  /** Soft-deleted conversations, read on demand (D22, D25). */
  deleted: Conversation[];
  /** The conversation on screen, or `null` when the panel is showing the list. */
  openId: string | null;
  /** Its turns, in `ord`. The server's answer — never spliced into locally. */
  messages: ChatMessage[];
  stream: StreamState;
  /** What the next ask carries. The writer's own choices; the preview is the server's answer. */
  selection: ContextSelection;
  /** The action the streaming answer belongs to, or `null` for an ordinary question (P4-14). */
  rewrite: RewriteRequest | null;
}

export type ChatAction =
  | { type: 'load-requested' }
  | { type: 'loaded'; conversations: Conversation[] }
  | { type: 'load-failed'; message: string }
  | { type: 'conversations-listed'; conversations: Conversation[] }
  | { type: 'deleted-listed'; conversations: Conversation[] }
  | { type: 'conversation-opened'; conversationId: string | null }
  | { type: 'conversation-loaded'; conversationId: string; messages: ChatMessage[] }
  | { type: 'context-selected'; selection: ContextSelection }
  | { type: 'context-changed'; changes: Partial<ContextSelection> }
  | { type: 'context-cleared' }
  | { type: 'ask-sent'; prompt: string; rewrite?: RewriteRequest | null }
  | { type: 'stream-event'; event: StreamEvent }
  | { type: 'cancel-requested' }
  | { type: 'socket-closed'; reason: string }
  | { type: 'stream-cleared' };

export const INITIAL_CHAT_STATE: ChatState = {
  status: 'loading',
  error: null,
  conversations: [],
  deleted: [],
  openId: null,
  messages: [],
  stream: IDLE_STREAM,
  selection: NO_CONTEXT,
  rewrite: null,
};

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'load-requested':
      return { ...INITIAL_CHAT_STATE, status: 'loading' };

    case 'loaded':
      return { ...state, status: 'ready', error: null, conversations: action.conversations };

    case 'load-failed':
      return { ...state, status: 'failed', error: action.message };

    case 'conversations-listed':
      // The rows are replaced and nothing else is. A refresh happens after every write and while
      // a transcript is open, and it must not disturb the answer that is arriving.
      return { ...state, error: null, conversations: action.conversations };

    case 'deleted-listed':
      return { ...state, deleted: action.conversations };

    case 'conversation-opened':
      // Opening a different conversation abandons whatever was streaming: the socket is per
      // conversation and the provider closes it. Leaving the text on screen under a transcript it
      // did not come from is how a writer ends up reading an answer to somebody else's question.
      return {
        ...state,
        openId: action.conversationId,
        messages: action.conversationId === state.openId ? state.messages : [],
        stream: IDLE_STREAM,
        rewrite: null,
      };

    case 'conversation-loaded':
      // A read that landed after the writer moved on belongs to a conversation nobody is looking
      // at. Ignored rather than rendered, for the reason a save's result is ignored when the
      // chapter has been switched (`DocumentContext`).
      return action.conversationId === state.openId
        ? { ...state, messages: action.messages }
        : state;

    case 'context-selected':
      return { ...state, selection: action.selection };

    case 'context-changed':
      return { ...state, selection: { ...state.selection, ...action.changes } };

    case 'context-cleared':
      return { ...state, selection: NO_CONTEXT };

    case 'ask-sent':
      return {
        ...state,
        stream: { ...IDLE_STREAM, phase: 'waiting', prompt: action.prompt },
        rewrite: action.rewrite ?? null,
      };

    case 'stream-event':
      return { ...state, stream: applyEvent(state.stream, action.event) };

    case 'cancel-requested':
      // Marked, not ended. The provider stream is closed by the *server*, which then writes the
      // turn and sends `done` with `cancelled`; until that arrives, fragments already in flight
      // are still real text the writer paid for.
      return state.stream.phase === 'waiting' || state.stream.phase === 'streaming'
        ? { ...state, stream: { ...state.stream, cancelling: true } }
        : state;

    case 'socket-closed':
      return { ...state, stream: closed(state.stream, action.reason) };

    case 'stream-cleared':
      return { ...state, stream: IDLE_STREAM, rewrite: null };

    default: {
      const impossible: never = action;
      return impossible;
    }
  }
}

/**
 * One event onto the accumulating answer.
 *
 * Split out because this is the part with rules in it, and because the sequences worth testing
 * are sequences of *events* rather than of actions.
 */
function applyEvent(stream: StreamState, event: StreamEvent): StreamState {
  if (stream.phase === 'idle' || stream.phase === 'done' || stream.phase === 'failed') {
    // Nothing is listening. Either the ask has not been made, or a terminator has already
    // arrived and exactly one of those is sent per stream (`specs/providers.md` § 4).
    return stream;
  }

  switch (event.type) {
    case 'start':
      // A second `start` marks the model again and touches nothing else — resetting the text
      // would throw away fragments that have already arrived and been paid for.
      return { ...stream, model: event.model || stream.model };

    case 'delta':
      return { ...stream, phase: 'streaming', text: stream.text + event.text };

    case 'usage':
      return { ...stream, usage: event.usage, usageReported: true };

    case 'done':
      return { ...stream, phase: 'done', stopReason: event.stop_reason, cancelling: false };

    case 'error':
      // The partial text stays. A turn that failed halfway is still a turn the writer paid for,
      // and the server stores it with its code for the same reason.
      return {
        ...stream,
        phase: 'failed',
        failure: { code: event.code, message: event.message },
        cancelling: false,
      };

    default: {
      const impossible: never = event;
      return impossible;
    }
  }
}

/**
 * The socket ended.
 *
 * If a terminator had already arrived this changes nothing: the stream finished and the socket
 * closing afterwards is the ordinary end of a conversation. If one had not, the stream stopped
 * without saying so — which is a failure with **no provider code**, because no provider said
 * anything. `code: null` is that distinction, and it is why the field is nullable.
 */
function closed(stream: StreamState, reason: string): StreamState {
  if (stream.phase !== 'waiting' && stream.phase !== 'streaming') {
    return stream;
  }
  return {
    ...stream,
    phase: 'failed',
    cancelling: false,
    failure: {
      code: null,
      message: reason || 'the connection to the assistant ended before the answer did',
    },
  };
}

/** True while an answer is on its way and a cancel would do something. */
export function isStreaming(state: ChatState): boolean {
  return state.stream.phase === 'waiting' || state.stream.phase === 'streaming';
}

/** The conversation on screen, or `null`. */
export function openConversation(state: ChatState): Conversation | null {
  return state.conversations.find((row) => row.id === state.openId) ?? null;
}

/** True when the writer has pointed at a passage — which is what *Ask agent* sets (P4-13). */
export function hasSelection(selection: ContextSelection): boolean {
  return selection.document_id !== '' && selection.from_pos !== null && selection.to_pos !== null;
}

/** True when anything at all would travel with the question besides the question. */
export function hasContext(selection: ContextSelection): boolean {
  return (
    hasSelection(selection) ||
    (selection.document_id !== '' && selection.include_chapter) ||
    selection.entry_ids.length > 0
  );
}

/**
 * What every stored turn in this conversation has cost, added up.
 *
 * Zeros are counted as zeros and `reported` says whether any turn reported anything at all, so
 * the panel can distinguish a conversation that cost nothing from one whose provider does not
 * say — the same distinction `usageReported` makes for the answer arriving now.
 */
export function totalUsage(messages: readonly ChatMessage[]): Usage & { reported: boolean } {
  let input = 0;
  let output = 0;
  let reported = false;
  for (const message of messages) {
    input += message.usage.input_tokens;
    output += message.usage.output_tokens;
    if (message.usage.input_tokens > 0 || message.usage.output_tokens > 0) {
      reported = true;
    }
  }
  return { input_tokens: input, output_tokens: output, reported };
}
