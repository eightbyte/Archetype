/**
 * The one place a provider's answer is put into words for a writer (P4-12).
 *
 * `anchorText.ts`'s job, one layer over: the panel, the transcript, and the settings screen all
 * need to say the same thing about the same condition, and three components each writing their
 * own sentence is three sentences that drift.
 *
 * ## What is here and what is not
 *
 * The six error codes and the seven stop reasons are the port's, closed, and mirrored in
 * `api/stream.ts` (D32). This file does not restate either list — it maps over them, and a code
 * it has no words for falls back to the provider's own message, which is always carried.
 *
 * **The provider's message is never thrown away.** Our sentence says what *kind* of thing went
 * wrong and what the writer can do about it; the provider's says what actually happened, and it
 * is the half that makes a wrong answer diagnosable. Both are shown.
 */

import type { ProviderErrorCode, StopReason, Usage } from './api/stream';

/**
 * What each provider failure means, and what the writer can do about it.
 *
 * Six, because the taxonomy is six (`specs/providers.md` § 6). Each says a different thing, which
 * is the point of having six rather than one: an expired key and a rate limit and a prompt too
 * long are three different afternoons.
 */
export const PROVIDER_ERROR_WORDS: Record<ProviderErrorCode, { title: string; advice: string }> = {
  provider_unconfigured: {
    title: 'No assistant is configured',
    advice:
      'An API key comes from the environment only. Set ARCHETYPE_ANTHROPIC_API_KEY or ' +
      'ARCHETYPE_OPENAI_API_KEY and restart the server.',
  },
  provider_auth_failed: {
    title: 'The provider would not accept the key',
    advice: 'The key is set but was refused. Check that it is current and is for this provider.',
  },
  provider_rate_limited: {
    title: 'The provider is rate-limiting this key',
    advice: 'Nothing was lost. Wait a moment and ask again.',
  },
  provider_unavailable: {
    title: 'The provider could not be reached',
    advice: 'Nothing was retried automatically — asking again is one deliberate request.',
  },
  provider_refused: {
    title: 'The provider refused the request',
    advice: 'The message below is theirs, in their words.',
  },
  context_too_large: {
    title: 'Too much was being sent',
    advice:
      'Nothing was sent and nothing was spent. Narrow the selection, drop the chapter, or drop ' +
      'an entry, and the estimate above will say whether it now fits.',
  },
};

/**
 * How an answer ended, for a reader.
 *
 * `end_turn` is absent on purpose: an answer that finished normally needs no label, and putting
 * one on every turn would make the two that matter — a truncation and a cancel — invisible among
 * them. `stopReasonWords` returns `null` for it.
 */
const STOP_REASON_WORDS: Partial<Record<StopReason, string>> = {
  max_tokens: 'cut off at the answer-length limit',
  stop_sequence: 'stopped at a stop sequence',
  tool_use: 'stopped to call a tool',
  refusal: 'the model declined to answer',
  other: 'stopped for a reason this build does not recognise',
  cancelled: 'you stopped this',
};

/** A label for how an answer ended, or `null` when it simply finished. */
export function stopReasonWords(stopReason: string): string | null {
  return STOP_REASON_WORDS[stopReason as StopReason] ?? null;
}

/** The title and advice for a code, or a plain fallback for one this build does not know. */
export function providerErrorWords(code: string | null): { title: string; advice: string } {
  const known = code === null ? undefined : PROVIDER_ERROR_WORDS[code as ProviderErrorCode];
  return (
    known ?? {
      title: 'The answer stopped',
      advice: 'Whatever had arrived is kept. Asking again is one deliberate request.',
    }
  );
}

/**
 * What a turn cost, in words.
 *
 * **Zero means "not reported", never "free"** (`specs/providers.md` § 2). A provider that reports
 * no usage is one whose bill this app cannot show, and saying so is more honest than drawing a
 * confident zero — which is what a writer would read as "that one was free".
 */
export function usageWords(usage: Usage, reported = usage.input_tokens + usage.output_tokens > 0): string {
  if (!reported) {
    return 'usage not reported';
  }
  return `${usage.input_tokens.toLocaleString()} in · ${usage.output_tokens.toLocaleString()} out`;
}
