/**
 * P4-12 — the chat reducer, and the cadences a component test cannot make.
 *
 * The panel's hard part is not drawing a transcript; it is that an answer arrives in fragments
 * over a channel that can stop halfway (§ 6). Out-of-order events, a duplicate `start`, a `usage`
 * after the last fragment, a terminator that never comes, a cancel that races the final delta —
 * every one of them is a way the transcript ends up subtly wrong, and none of them can be asked
 * of a real provider on demand.
 *
 * So they are asserted here, against the pure function, by handing it sequences of events. No
 * React, no socket, no timers.
 */

import { describe, expect, test } from 'vitest';
import type { ChatMessage, Conversation } from '../api/types';
import type { StreamEvent } from '../api/stream';
import type { ChatState } from '../state/chatReducer';
import {
  INITIAL_CHAT_STATE,
  NO_CONTEXT,
  chatReducer,
  hasContext,
  hasSelection,
  isStreaming,
  openConversation,
  totalUsage,
} from '../state/chatReducer';

function conversation(id: string, title = ''): Conversation {
  return {
    id,
    project_id: 'prj_1',
    title,
    message_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    deleted_at: null,
  };
}

function turn(id: string, role: string, content: string, input = 0, output = 0): ChatMessage {
  return {
    id,
    conversation_id: 'cnv_1',
    ord: 0,
    role,
    content,
    context: {},
    provider: role === 'assistant' ? 'fake' : '',
    model: role === 'assistant' ? 'fake-model' : '',
    usage: { input_tokens: input, output_tokens: output },
    stop_reason: '',
    error_code: '',
    created_at: '2026-01-01T00:00:00Z',
  };
}

/** A conversation open, ready to be asked in. The state every stream test starts from. */
function opened(): ChatState {
  let state = chatReducer(INITIAL_CHAT_STATE, {
    type: 'loaded',
    conversations: [conversation('cnv_1', 'The harbour')],
  });
  state = chatReducer(state, { type: 'conversation-opened', conversationId: 'cnv_1' });
  return state;
}

/** Ask, then play a sequence of events at it. */
function play(events: readonly StreamEvent[], from: ChatState = opened()): ChatState {
  let state = chatReducer(from, { type: 'ask-sent', prompt: 'what colour is it?' });
  for (const event of events) {
    state = chatReducer(state, { type: 'stream-event', event });
  }
  return state;
}

describe('an answer arriving', () => {
  test('fragments concatenate in arrival order and the phase follows them', () => {
    const state = play([
      { type: 'start', model: 'fake-model' },
      { type: 'delta', text: 'The harbour ' },
      { type: 'delta', text: 'was grey.' },
      { type: 'usage', usage: { input_tokens: 120, output_tokens: 8 } },
      { type: 'done', stop_reason: 'end_turn', raw_stop_reason: 'end_turn' },
    ]);

    expect(state.stream.text).toBe('The harbour was grey.');
    expect(state.stream.model).toBe('fake-model');
    expect(state.stream.phase).toBe('done');
    expect(state.stream.stopReason).toBe('end_turn');
    expect(state.stream.usage).toEqual({ input_tokens: 120, output_tokens: 8 });
    expect(state.stream.usageReported).toBe(true);
    expect(isStreaming(state)).toBe(false);
  });

  test('the question is on screen before the first token', () => {
    const state = chatReducer(opened(), { type: 'ask-sent', prompt: 'what colour is it?' });

    // `waiting` is a real state and one the writer notices: a provider's first token can be
    // seconds away, and a panel that shows nothing in that gap looks broken.
    expect(state.stream.phase).toBe('waiting');
    expect(state.stream.prompt).toBe('what colour is it?');
    expect(isStreaming(state)).toBe(true);
  });
});

describe('cadences no provider produces on demand', () => {
  test('a fragment that arrives before `start` is kept, not dropped', () => {
    const state = play([
      { type: 'delta', text: 'The harbour' },
      { type: 'start', model: 'fake-model' },
    ]);

    // Text the provider sent and the writer paid for. Dropping it to enforce an ordering nobody
    // promised would lose words to a rule of our own invention.
    expect(state.stream.text).toBe('The harbour');
    expect(state.stream.model).toBe('fake-model');
  });

  test('a second `start` marks the model again and does not reset the text', () => {
    const state = play([
      { type: 'start', model: 'fake-model' },
      { type: 'delta', text: 'The harbour' },
      { type: 'start', model: 'other-model' },
      { type: 'delta', text: ' was grey.' },
    ]);

    expect(state.stream.text).toBe('The harbour was grey.');
    expect(state.stream.model).toBe('other-model');
  });

  test('a `usage` before the last fragment is still the answer’s usage', () => {
    const state = play([
      { type: 'usage', usage: { input_tokens: 9, output_tokens: 1 } },
      { type: 'delta', text: 'grey' },
      { type: 'done', stop_reason: 'end_turn', raw_stop_reason: 'end_turn' },
    ]);

    expect(state.stream.usage).toEqual({ input_tokens: 9, output_tokens: 1 });
    expect(state.stream.text).toBe('grey');
  });

  test('nothing lands after a terminator', () => {
    const state = play([
      { type: 'delta', text: 'grey' },
      { type: 'done', stop_reason: 'end_turn', raw_stop_reason: 'end_turn' },
      { type: 'delta', text: ' — and cold' },
      { type: 'error', code: 'provider_rate_limited', message: 'slow down' },
    ]);

    // Exactly one terminator is sent per stream (`specs/providers.md` § 4), so anything after one
    // belongs to a stream this panel is no longer listening to.
    expect(state.stream.text).toBe('grey');
    expect(state.stream.phase).toBe('done');
    expect(state.stream.failure).toBeNull();
  });

  test('an error keeps what had arrived and says what went wrong', () => {
    const state = play([
      { type: 'delta', text: 'The harbour was ' },
      { type: 'error', code: 'provider_rate_limited', message: 'too many requests' },
    ]);

    expect(state.stream.phase).toBe('failed');
    expect(state.stream.text).toBe('The harbour was ');
    expect(state.stream.failure).toEqual({
      code: 'provider_rate_limited',
      message: 'too many requests',
    });
  });

  test('a socket that closes mid-answer is a failure with no provider code', () => {
    let state = play([{ type: 'delta', text: 'The harbour was ' }]);
    state = chatReducer(state, { type: 'socket-closed', reason: '' });

    expect(state.stream.phase).toBe('failed');
    expect(state.stream.text).toBe('The harbour was ');
    // `null` rather than one of the six: no provider said anything, and borrowing a code would
    // file a dropped connection as something a provider did.
    expect(state.stream.failure?.code).toBeNull();
    expect(state.stream.failure?.message).toContain('ended before the answer did');
  });

  test('a socket that closes after the answer changes nothing', () => {
    let state = play([
      { type: 'delta', text: 'grey' },
      { type: 'done', stop_reason: 'end_turn', raw_stop_reason: 'end_turn' },
    ]);
    state = chatReducer(state, { type: 'socket-closed', reason: 'closed by the app' });

    expect(state.stream.phase).toBe('done');
    expect(state.stream.failure).toBeNull();
  });
});

describe('cancel', () => {
  test('is marked, and the fragments still in flight are still kept', () => {
    let state = play([{ type: 'delta', text: 'The harbour ' }]);
    state = chatReducer(state, { type: 'cancel-requested' });
    expect(state.stream.cancelling).toBe(true);

    state = chatReducer(state, { type: 'stream-event', event: { type: 'delta', text: 'was' } });
    state = chatReducer(state, {
      type: 'stream-event',
      event: { type: 'done', stop_reason: 'cancelled', raw_stop_reason: '' },
    });

    expect(state.stream.text).toBe('The harbour was');
    // A `stop_reason` and never an `error_code`: a deliberate act is not a failure, and the
    // server writes the same answer to the stored turn.
    expect(state.stream.stopReason).toBe('cancelled');
    expect(state.stream.failure).toBeNull();
    expect(state.stream.cancelling).toBe(false);
  });

  test('does nothing when nothing is arriving', () => {
    const state = chatReducer(opened(), { type: 'cancel-requested' });
    expect(state.stream).toBe(opened().stream);
  });
});

describe('conversations', () => {
  test('opening a different one abandons the answer and empties the transcript', () => {
    let state = play([{ type: 'delta', text: 'The harbour' }]);
    state = chatReducer(state, {
      type: 'conversation-loaded',
      conversationId: 'cnv_1',
      messages: [turn('msg_1', 'user', 'what colour is it?')],
    });
    expect(state.messages).toHaveLength(1);

    state = chatReducer(state, { type: 'conversation-opened', conversationId: 'cnv_2' });

    // Leaving the text on screen under a transcript it did not come from is how a writer ends up
    // reading an answer to somebody else's question.
    expect(state.messages).toEqual([]);
    expect(state.stream.phase).toBe('idle');
    expect(state.rewrite).toBeNull();
  });

  test('a read that lands after the writer moved on is ignored', () => {
    let state = opened();
    state = chatReducer(state, { type: 'conversation-opened', conversationId: 'cnv_2' });
    state = chatReducer(state, {
      type: 'conversation-loaded',
      conversationId: 'cnv_1',
      messages: [turn('msg_1', 'user', 'stale')],
    });

    expect(state.messages).toEqual([]);
  });

  test('a refresh replaces the rows and disturbs nothing else', () => {
    let state = play([{ type: 'delta', text: 'The harbour' }]);
    state = chatReducer(state, {
      type: 'conversations-listed',
      conversations: [conversation('cnv_1', 'The harbour'), conversation('cnv_2')],
    });

    expect(state.conversations).toHaveLength(2);
    expect(state.stream.text).toBe('The harbour');
    expect(openConversation(state)?.title).toBe('The harbour');
  });
});

describe('the context the next question carries', () => {
  test('a selection is pointed at, changed a part at a time, and cleared', () => {
    let state = chatReducer(opened(), {
      type: 'context-selected',
      selection: {
        document_id: 'doc_1',
        from_pos: 5,
        to_pos: 16,
        include_chapter: true,
        entry_ids: [],
        include_history: true,
      },
    });
    expect(hasSelection(state.selection)).toBe(true);
    expect(hasContext(state.selection)).toBe(true);

    state = chatReducer(state, { type: 'context-changed', changes: { include_chapter: false } });
    expect(state.selection.include_chapter).toBe(false);
    expect(state.selection.from_pos).toBe(5);

    state = chatReducer(state, { type: 'context-cleared' });
    expect(state.selection).toEqual(NO_CONTEXT);
    expect(hasContext(state.selection)).toBe(false);
  });
});

describe('what a conversation cost', () => {
  test('zero across every turn means not reported, not free', () => {
    // `specs/providers.md` § 2. The panel says so rather than drawing a confident zero, which a
    // writer would read as "that one was free".
    expect(totalUsage([turn('msg_1', 'assistant', 'grey')]).reported).toBe(false);
  });

  test('reported usage adds up across turns', () => {
    const total = totalUsage([
      turn('msg_1', 'assistant', 'grey', 100, 5),
      turn('msg_2', 'assistant', 'cold', 120, 3),
    ]);

    expect(total).toEqual({ input_tokens: 220, output_tokens: 8, reported: true });
  });
});
