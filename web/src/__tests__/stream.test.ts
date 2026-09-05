/**
 * D32's asymmetry, client half (P4-2).
 *
 * The server half is `server/tests/test_llm_port.py::test_the_server_refuses_a_stream_event_type_
 * it_does_not_know`, and the two are deliberately opposite: strict there, tolerant here. This
 * file is what stops "tolerant" from quietly becoming "credulous" — an unknown event is skipped,
 * but a `done` carrying a stop reason nobody defined is skipped too, rather than rendered.
 *
 * There is no panel yet: P4-12 builds it. What is under test is the reader every consumer of the
 * socket will go through.
 */

import { describe, expect, test } from 'vitest';
import {
  PROVIDER_ERROR_CODES,
  STOP_REASONS,
  isProviderErrorCode,
  isStopReason,
  isTerminal,
  parseStreamEvent,
  type StreamEvent,
} from '../api/stream';

describe('the vocabularies match the port', () => {
  test('seven stop reasons, and cancelled is one of them', () => {
    expect(Object.values(STOP_REASONS)).toEqual([
      'end_turn',
      'max_tokens',
      'stop_sequence',
      'tool_use',
      'refusal',
      'other',
      'cancelled',
    ]);
    expect(isStopReason('cancelled')).toBe(true);
    expect(isStopReason('finished')).toBe(false);
  });

  test('six provider error codes', () => {
    expect(Object.values(PROVIDER_ERROR_CODES)).toEqual([
      'provider_unconfigured',
      'provider_auth_failed',
      'provider_rate_limited',
      'provider_unavailable',
      'provider_refused',
      'context_too_large',
    ]);
    expect(isProviderErrorCode('provider_exploded')).toBe(false);
  });
});

describe('reading an event', () => {
  test('each Phase 4 member parses', () => {
    expect(parseStreamEvent({ type: 'start', model: 'a-model' })).toEqual({
      type: 'start',
      model: 'a-model',
    });
    expect(parseStreamEvent({ type: 'delta', text: 'She ' })).toEqual({
      type: 'delta',
      text: 'She ',
    });
    expect(
      parseStreamEvent({ type: 'usage', usage: { input_tokens: 12, output_tokens: 3 } }),
    ).toEqual({ type: 'usage', usage: { input_tokens: 12, output_tokens: 3 } });
    expect(
      parseStreamEvent({ type: 'done', stop_reason: 'end_turn', raw_stop_reason: 'end_turn' }),
    ).toEqual({ type: 'done', stop_reason: 'end_turn', raw_stop_reason: 'end_turn' });
    expect(
      parseStreamEvent({ type: 'error', code: 'provider_rate_limited', message: 'slow down' }),
    ).toEqual({ type: 'error', code: 'provider_rate_limited', message: 'slow down' });
  });

  test('an empty delta is text, not an absence', () => {
    expect(parseStreamEvent({ type: 'delta', text: '' })).toEqual({ type: 'delta', text: '' });
  });

  test('unreported usage reads as zero rather than as a missing field', () => {
    expect(parseStreamEvent({ type: 'usage', usage: {} })).toEqual({
      type: 'usage',
      usage: { input_tokens: 0, output_tokens: 0 },
    });
  });
});

describe('D32: the client ignores what it does not know', () => {
  test('a Phase 6 event is skipped, not thrown', () => {
    // The whole point: a server ahead of this bundle degrades to less detail, never to a broken
    // panel. `step`, `plan`, `tool_call`, and `tool_result` are all real Phase 6 events.
    for (const type of ['step', 'plan', 'tool_call', 'tool_result']) {
      expect(parseStreamEvent({ type, index: 1 })).toBeNull();
    }
  });

  test('a known type with a shape this bundle cannot read is skipped too', () => {
    expect(parseStreamEvent({ type: 'delta' })).toBeNull();
    expect(parseStreamEvent({ type: 'done', stop_reason: 'finished' })).toBeNull();
    expect(parseStreamEvent({ type: 'error', code: 'provider_exploded', message: 'x' })).toBeNull();
  });

  test('anything that is not an event at all is skipped', () => {
    for (const raw of [null, undefined, 'delta', 42, [], {}]) {
      expect(parseStreamEvent(raw)).toBeNull();
    }
  });

  test('a stream with an unknown event in the middle still reads as an answer', () => {
    const wire: unknown[] = [
      { type: 'start', model: 'a-model' },
      { type: 'delta', text: 'She ' },
      { type: 'step', index: 1 },
      { type: 'delta', text: 'counts.' },
      { type: 'done', stop_reason: 'end_turn' },
    ];
    const events = wire
      .map(parseStreamEvent)
      .filter((event): event is StreamEvent => event !== null);

    expect(events.map((event) => event.type)).toEqual(['start', 'delta', 'delta', 'done']);
    expect(
      events
        .filter((event): event is Extract<StreamEvent, { type: 'delta' }> => event.type === 'delta')
        .map((event) => event.text)
        .join(''),
    ).toBe('She counts.');
    const last = events.at(-1);
    expect(last && isTerminal(last)).toBe(true);
  });
});
