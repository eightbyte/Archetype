/**
 * The stream event vocabulary, client side (P4-2, D32).
 *
 * Mirrored from `server/archetype/llm/port.py` and specified in `specs/providers.md` § 4. One
 * vocabulary travels over the one WebSocket D11 chose, and Phase 6 **extends** it — `plan`,
 * `tool_call`, `tool_result`, `step` — rather than replacing it.
 *
 * The asymmetry this file exists for
 * ----------------------------------
 *
 * > The server rejects an event type it does not know. The client ignores one.
 *
 * On the server an unrecognised event means an adapter and the port have parted company, and the
 * only safe answer is to stop. Here it means the browser is holding a bundle older than the
 * server — and a stale bundle must degrade to *less detail*, never to a broken panel. A Phase 6
 * server emitting `step` events at a Phase 4 bundle has to still show the answer.
 *
 * So {@link parseStreamEvent} returns `null` for anything it does not understand, and the caller
 * skips it. That is deliberate, it is written down in providers.md § 4, and the server half of
 * the same rule is asserted in `server/tests/test_llm_port.py`.
 *
 * Every field is checked one at a time, for the reason every value read back from `localStorage`
 * is: this data crosses a boundary, and a shape that is *nearly* right is how a transcript ends
 * up rendering `undefined`.
 */

/** Why generation stopped (providers.md § 3). `cancelled` is written by whoever closed the stream. */
export const STOP_REASONS = {
  endTurn: 'end_turn',
  maxTokens: 'max_tokens',
  stopSequence: 'stop_sequence',
  toolUse: 'tool_use',
  refusal: 'refusal',
  other: 'other',
  cancelled: 'cancelled',
} as const;

export type StopReason = (typeof STOP_REASONS)[keyof typeof STOP_REASONS];

/** The provider error taxonomy (providers.md § 6). Six, closed, and each says a different thing. */
export const PROVIDER_ERROR_CODES = {
  unconfigured: 'provider_unconfigured',
  authFailed: 'provider_auth_failed',
  rateLimited: 'provider_rate_limited',
  unavailable: 'provider_unavailable',
  refused: 'provider_refused',
  contextTooLarge: 'context_too_large',
} as const;

export type ProviderErrorCode = (typeof PROVIDER_ERROR_CODES)[keyof typeof PROVIDER_ERROR_CODES];

/**
 * What an answer cost, as the provider reported it.
 *
 * Zero means **not reported**, not free — the panel says so rather than drawing a confident zero.
 */
export interface Usage {
  input_tokens: number;
  output_tokens: number;
}

/** First event of every stream, before any text. */
export interface StreamStart {
  type: 'start';
  model: string;
}

/** A fragment. Fragments concatenate in arrival order; this is never the accumulated answer. */
export interface StreamDelta {
  type: 'delta';
  text: string;
}

/** What it cost, when the provider says so. At most once, before or after the last delta. */
export interface StreamUsageEvent {
  type: 'usage';
  usage: Usage;
}

/** The last event of a stream that completed. */
export interface StreamDone {
  type: 'done';
  stop_reason: StopReason;
  raw_stop_reason: string;
}

/** The last event of a stream that failed, carrying the code the envelope would have carried. */
export interface StreamErrorEvent {
  type: 'error';
  code: ProviderErrorCode;
  message: string;
}

/** D32's Phase 4 union. Phase 6 adds to it; nothing here changes when it does. */
export type StreamEvent =
  | StreamStart
  | StreamDelta
  | StreamUsageEvent
  | StreamDone
  | StreamErrorEvent;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function text(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function count(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0;
}

/** True when `value` is one of the seven stop reasons — anything else is a server we do not know. */
export function isStopReason(value: unknown): value is StopReason {
  return (
    typeof value === 'string' && (Object.values(STOP_REASONS) as string[]).includes(value)
  );
}

/** True when `value` is one of the six provider error codes. */
export function isProviderErrorCode(value: unknown): value is ProviderErrorCode {
  return (
    typeof value === 'string' && (Object.values(PROVIDER_ERROR_CODES) as string[]).includes(value)
  );
}

function readUsage(value: unknown): Usage {
  if (!isRecord(value)) return { input_tokens: 0, output_tokens: 0 };
  return { input_tokens: count(value.input_tokens), output_tokens: count(value.output_tokens) };
}

/**
 * One event, or `null` for anything this bundle does not understand (D32).
 *
 * `null` covers three cases and deliberately does not distinguish them, because the caller does
 * the same thing with all three — skip it and keep rendering:
 *
 * - an event type from a newer server (`step`, `tool_call`, …);
 * - a known type whose shape is wrong;
 * - something that is not an event at all.
 */
export function parseStreamEvent(raw: unknown): StreamEvent | null {
  if (!isRecord(raw)) return null;

  switch (raw.type) {
    case 'start':
      return { type: 'start', model: text(raw.model) ?? '' };
    case 'delta': {
      const fragment = text(raw.text);
      return fragment === null ? null : { type: 'delta', text: fragment };
    }
    case 'usage':
      return { type: 'usage', usage: readUsage(raw.usage) };
    case 'done':
      return isStopReason(raw.stop_reason)
        ? {
            type: 'done',
            stop_reason: raw.stop_reason,
            raw_stop_reason: text(raw.raw_stop_reason) ?? '',
          }
        : null;
    case 'error':
      return isProviderErrorCode(raw.code)
        ? { type: 'error', code: raw.code, message: text(raw.message) ?? '' }
        : null;
    default:
      return null;
  }
}

/** True for the two events that end a well-formed stream. Exactly one of them arrives (§ 4). */
export function isTerminal(event: StreamEvent): event is StreamDone | StreamErrorEvent {
  return event.type === 'done' || event.type === 'error';
}
