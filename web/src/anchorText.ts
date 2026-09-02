/**
 * How an anchor is put into words (P2-9, P2-10).
 *
 * One place, because the same anchor is named in three: the *Marks* list, the re-link control
 * over the selection, and the decoration's accessible label. A passage called one thing in the
 * panel and another in the editor is the same passage to everyone except the writer.
 *
 * It sits beside `format.ts` rather than under `panels/` for the same reason that does: this is
 * the display edge, and the editor reaches it as well as the panels do.
 */

import type { Anchor } from './api/types';

/** How long a quote is allowed to be before it is cut short in a list. */
const QUOTE_PREVIEW_CHARS = 80;

/** An anchor's name: its label if the writer gave it one, else the words it is over. */
export function describeAnchor(anchor: Pick<Anchor, 'label' | 'quote'>): string {
  return anchor.label || `“${truncate(anchor.quote, QUOTE_PREVIEW_CHARS)}”`;
}

/** The quote as a list shows it: one line, elided in the middle of a word if it must be. */
export function previewQuote(quote: string, limit = QUOTE_PREVIEW_CHARS): string {
  return truncate(quote.replace(/\s+/g, ' ').trim(), limit);
}

/** What each status means, said once, where a writer can read it. */
export const STATUS_WORDS: Record<string, { name: string; meaning: string }> = {
  ok: {
    name: 'Found',
    meaning: 'The passage is where this mark says it is.',
  },
  stale: {
    name: 'Lost',
    meaning:
      'The passage this mark was made over is no longer in the chapter. It has not been moved ' +
      'anywhere — a mark is never re-pointed by guesswork.',
  },
  orphaned: {
    name: 'Chapter deleted',
    meaning: 'The chapter this mark lives in has been deleted. Restore it and the mark returns.',
  },
};

function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}
