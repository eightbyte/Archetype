/**
 * The story bible of the open project: the served definition, the entries, the review queue, and
 * the deleted tray (P3-12, D10, D25 – D27).
 *
 * Lifetime is one project — the same as `projectReducer`'s, and for the same reason: the Bible
 * tab holds every entry at once, a link may join any two of them, and an entry outlives every
 * document switch. So this is a fourth context beside the three Phase 1 built, not a corner of
 * one of them.
 *
 * ## Three lists, and why they are three
 *
 * `entries` is what the browse list shows, and it is **the server's filtered answer**: the kind,
 * the status, and the `q` filter compose on the route (ruling 4), and the cap is reported rather
 * than merely applied. Re-implementing that filter here would be a second answer to the same
 * question, and the one that drifts.
 *
 * `review` is the retcon queue, read with `needs_review=true` and held separately rather than as
 * a mode of the browse list. It has to be right whatever the writer is currently filtering by:
 * a queue you can only see by clearing your filters is a queue nobody works through (P3-12).
 *
 * `deleted` is the restore tray, read on demand, on the same footing as *Deleted chapters*.
 *
 * ## What is deliberately not here
 *
 * The **open entry's detail** — its citations, its links, its revisions. Those belong to the one
 * entry being looked at, are re-read when it is opened, and would otherwise be a second copy of
 * the entry beside the one in `entries` for the two to disagree about. `openId` is the whole of
 * what this reducer knows about the detail view: which record it is showing.
 *
 * Pure. No React, no client, no `localStorage`.
 */

import type { BibleSchema, Entry } from '../api/types';

/**
 * What the browse list is filtered by.
 *
 * Every one of them is optional and they compose. `q` is a `LIKE` filter over names, aliases,
 * and summaries — a filter, not search: Phase 5 owns search and owns that route name (ruling 4).
 */
export interface EntryFilters {
  kind: string | null;
  status: string | null;
  q: string;
}

export interface BibleState {
  status: 'loading' | 'ready' | 'failed';
  /** What went wrong. Set by a failed load *and* by a failed refresh, which keeps the list. */
  error: string | null;
  /** D26's definition. Read once per project open — it is the product's, not the project's. */
  schema: BibleSchema | null;
  /** The browse list: the server's answer for `filters`. */
  entries: Entry[];
  /** Live entries per kind, **unfiltered**, so the tab counts characters while showing places. */
  counts: Record<string, number>;
  /** The `q` cap was hit and a row was withheld. Exact — the route asks for one more and trims. */
  truncated: boolean;
  filters: EntryFilters;
  /** A list request is in the air. The rows on screen stay put while it is. */
  refreshing: boolean;
  /** The retcon queue (D27). Its own read, so it is right whatever the browse list is showing. */
  review: Entry[];
  /** Soft-deleted entries, most recently deleted first. Read on demand (D25). */
  deleted: Entry[];
  /** The entry the tab has open, or `null` for the list. */
  openId: string | null;
}

export type BibleAction =
  | { type: 'load-requested' }
  | {
      type: 'loaded';
      schema: BibleSchema;
      entries: Entry[];
      counts: Record<string, number>;
      truncated: boolean;
      review: Entry[];
    }
  | { type: 'load-failed'; message: string }
  | { type: 'filters-changed'; filters: Partial<EntryFilters> }
  | { type: 'list-requested' }
  | {
      type: 'listed';
      entries: Entry[];
      counts: Record<string, number>;
      truncated: boolean;
    }
  | { type: 'list-failed'; message: string }
  | { type: 'review-loaded'; entries: Entry[] }
  | { type: 'deleted-loaded'; entries: Entry[] }
  | { type: 'entry-opened'; entryId: string | null };

export const NO_FILTERS: EntryFilters = { kind: null, status: null, q: '' };

export const INITIAL_BIBLE_STATE: BibleState = {
  status: 'loading',
  error: null,
  schema: null,
  entries: [],
  counts: {},
  truncated: false,
  filters: NO_FILTERS,
  refreshing: false,
  review: [],
  deleted: [],
  openId: null,
};

export function bibleReducer(state: BibleState, action: BibleAction): BibleState {
  switch (action.type) {
    case 'load-requested':
      return { ...INITIAL_BIBLE_STATE, status: 'loading' };

    case 'loaded':
      return {
        ...INITIAL_BIBLE_STATE,
        status: 'ready',
        schema: action.schema,
        entries: action.entries,
        counts: action.counts,
        truncated: action.truncated,
        review: action.review,
        // The filters are kept across a reload: a refresh that silently widened what the writer
        // was looking at would look like rows appearing from nowhere.
        filters: state.filters,
      };

    case 'load-failed':
      return { ...state, status: 'failed', refreshing: false, error: action.message };

    case 'filters-changed': {
      const filters = { ...state.filters, ...action.filters };
      return sameFilters(filters, state.filters) ? state : { ...state, filters };
    }

    case 'list-requested':
      return { ...state, refreshing: true };

    case 'listed':
      return {
        ...state,
        // A list that came back after a failed one clears the failure: the rows on screen are
        // now the server's answer again, and an error line over them would be describing an
        // attempt that has since been superseded.
        status: state.status === 'failed' ? 'ready' : state.status,
        refreshing: false,
        error: null,
        entries: action.entries,
        counts: action.counts,
        truncated: action.truncated,
      };

    case 'list-failed':
      // Deliberately **not** `status: 'failed'`: the rows already on screen are the last thing
      // the server said, and blanking a panel over a refresh that did not land is the P1-12
      // rule read backwards. The message goes above them.
      return { ...state, refreshing: false, error: action.message };

    case 'review-loaded':
      return { ...state, review: action.entries };

    case 'deleted-loaded':
      return { ...state, deleted: action.entries };

    case 'entry-opened':
      return state.openId === action.entryId ? state : { ...state, openId: action.entryId };
  }
}

/** The entry with this id, wherever the state happens to be holding it. */
export function entryOf(state: BibleState, entryId: string | null): Entry | null {
  if (entryId === null) {
    return null;
  }
  for (const list of [state.entries, state.review, state.deleted]) {
    const found = list.find((entry) => entry.id === entryId);
    if (found) {
      return found;
    }
  }
  return null;
}

/** How many live entries there are, across every kind. What the tab's footer says. */
export function totalEntries(counts: Record<string, number>): number {
  return Object.values(counts).reduce((total, count) => total + count, 0);
}

/** True when the writer has narrowed the list at all — what an "everything" note keys on. */
export function isFiltered(filters: EntryFilters): boolean {
  return filters.kind !== null || filters.status !== null || filters.q.trim() !== '';
}

/**
 * Entries grouped by kind, in the schema's own kind order.
 *
 * The order is the definition's rather than alphabetical, so the groups read the way the kinds
 * were declared — and a kind the schema does not declare still appears, at the end, rather than
 * having its entries vanish from a list that claims to be everything.
 */
export function groupByKind(
  entries: readonly Entry[],
  schema: BibleSchema | null,
): [string, Entry[]][] {
  const groups = new Map<string, Entry[]>();
  for (const kind of schema?.kinds.map((definition) => definition.kind) ?? []) {
    groups.set(kind, []);
  }
  for (const entry of entries) {
    const existing = groups.get(entry.kind);
    if (existing) {
      existing.push(entry);
    } else {
      groups.set(entry.kind, [entry]);
    }
  }
  return [...groups.entries()].filter(([, members]) => members.length > 0);
}

function sameFilters(a: EntryFilters, b: EntryFilters): boolean {
  return a.kind === b.kind && a.status === b.status && a.q === b.q;
}
