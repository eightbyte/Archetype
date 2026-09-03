/**
 * The open project's story bible (P3-12, D10).
 *
 * A fourth context beside the three Phase 1 built, nested inside `ProjectProvider` and outside
 * `DocumentProvider`, because that is the lifetime order: an entry outlives every chapter switch
 * and dies with the project, exactly as an anchor does.
 *
 * Two rules shape everything below.
 *
 * **Every write refreshes the list.** A rename can move a row out of a `q` filter, a retcon can
 * put three entries into the review queue, and a delete removes one from a count. Working out
 * which of those happened on the client means re-implementing the route's filters here, and the
 * second implementation is the one that drifts. One request after a write is cheaper than that,
 * and it is always right.
 *
 * **Reading a filtered list is debounced; nothing else is.** P3-12 asks the list to search
 * "without a refetch per keystroke", so the `q` box is what the debounce exists for. Choosing a
 * kind or a status goes straight out — those are single deliberate clicks, and waiting after one
 * reads as lag.
 *
 * The detail view's reads — an entry's citations, its links, its revisions — are methods here but
 * are **not** held in this state. They belong to the one record being looked at, and holding a
 * second copy of that entry beside the one in the list would only give the two something to
 * disagree about (see `bibleReducer.ts`).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef } from 'react';
import type { ReactNode } from 'react';
import type {
  ApiClient,
  Citation,
  CitationRemoved,
  CitationRole,
  Entry,
  EntryDetail,
  EntryInput,
  EntryPatch,
  EntryRevision,
  EntryWriteResult,
  Link,
  LinkInput,
  LinkPatch,
  LinkView,
  RevisionMeta,
  StoryTime,
} from '../api';
import type { BibleAction, BibleState, EntryFilters } from './bibleReducer';
import { INITIAL_BIBLE_STATE, bibleReducer } from './bibleReducer';
import { describeFailure } from './ProjectContext';

/** How long the search box waits before asking the server. Long enough to type a word into. */
export const SEARCH_DEBOUNCE_MS = 200;

interface BibleContextValue {
  state: BibleState;
  dispatch: (action: BibleAction) => void;
  /** Narrow the browse list. `q` is debounced; the rest go out at once. */
  setFilters: (filters: Partial<EntryFilters>) => void;
  /** Show one entry, or `null` to go back to the list. */
  openEntry: (entryId: string | null) => void;
  /** Re-read the list and the review queue. Called after every write. */
  refresh: () => Promise<void>;
  /** Re-read the whole bible — the definition included. The answer to a failed load. */
  reload: () => void;

  createEntry: (input: EntryInput) => Promise<Entry>;
  /** One entry with its citations, its link count, and where it sits in the book. */
  readEntry: (entryId: string) => Promise<EntryDetail>;
  /** An entry's links, both directions in one answer, each labelled from this entry's end. */
  readEntryLinks: (entryId: string) => Promise<LinkView[]>;
  /**
   * Edit an entry, presenting the revision it was read at (D19, ruling 3).
   *
   * A stale one is refused with a `409` and **nothing is written**; the caller offers the
   * server's copy and never merges.
   */
  updateEntry: (entryId: string, patch: EntryPatch) => Promise<EntryWriteResult>;
  /** The writer has looked. Never a retcon — that clause is what lets the queue empty (P3-4). */
  clearReview: (entryId: string, revision: number) => Promise<EntryWriteResult>;
  deleteEntry: (entryId: string) => Promise<Entry>;
  restoreEntry: (entryId: string) => Promise<Entry>;
  /** Read the soft-deleted entries. Not loaded until something asks (D25). */
  loadDeleted: () => Promise<void>;

  listRevisions: (entryId: string) => Promise<RevisionMeta[]>;
  readRevision: (entryId: string, number: number) => Promise<EntryRevision>;
  /** Write a past state back through the ordinary update path, so history is appended to. */
  restoreRevision: (
    entryId: string,
    number: number,
    revision: number,
  ) => Promise<EntryWriteResult>;

  /**
   * Live entries a picker may offer, optionally of one kind.
   *
   * Read when a picker opens rather than held: the place you want to point at may be the one you
   * created a moment ago, and a cached directory is a picker that cannot see it.
   */
  listCandidates: (kind?: string) => Promise<Entry[]>;
  createLink: (input: LinkInput) => Promise<Link>;
  patchLink: (linkId: string, patch: LinkPatch) => Promise<Link>;
  deleteLink: (linkId: string) => Promise<Link>;

  cite: (entryId: string, anchorId: string, role: CitationRole) => Promise<Citation>;
  uncite: (entryId: string, anchorId: string, role?: CitationRole) => Promise<CitationRemoved>;
  /** Tell the tab about an entry something else created — *Add to bible* from the editor. */
  entryCreated: (entry: Entry) => void;

  /** D28's three answers over the project's events. Phase 3 draws no timeline (Phase 8 does). */
  readStoryTime: () => Promise<StoryTime>;
}

const BibleContext = createContext<BibleContextValue | null>(null);

export interface BibleProviderProps {
  client: ApiClient;
  projectId: string;
  children: ReactNode;
  /** Tests shorten the search debounce. */
  debounceMs?: number;
}

export function BibleProvider({
  client,
  projectId,
  children,
  debounceMs = SEARCH_DEBOUNCE_MS,
}: BibleProviderProps) {
  const [state, dispatch] = useReducer(bibleReducer, INITIAL_BIBLE_STATE);
  const [attempt, retry] = useReducer((count: number) => count + 1, 0);

  const filtersRef = useRef<EntryFilters>(state.filters);
  filtersRef.current = state.filters;

  /** The filters the rows on screen were fetched for, so a settled list is not fetched twice. */
  const fetched = useRef<string | null>(null);

  const listOnce = useCallback(
    async (filters: EntryFilters, signal?: AbortSignal) =>
      client.listEntries(
        projectId,
        {
          ...(filters.kind === null ? {} : { kind: filters.kind }),
          ...(filters.status === null ? {} : { status: filters.status }),
          ...(filters.q.trim() === '' ? {} : { q: filters.q.trim() }),
        },
        signal,
      ),
    [client, projectId],
  );

  // -- the load ------------------------------------------------------------------------------

  useEffect(() => {
    const controller = new AbortController();
    const filters = filtersRef.current;
    dispatch({ type: 'load-requested' });
    fetched.current = keyOf(filters);

    void (async () => {
      try {
        const [schema, listed, review] = await Promise.all([
          client.getBibleSchema(controller.signal),
          listOnce(filters, controller.signal),
          client.listEntries(projectId, { needs_review: true }, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        dispatch({
          type: 'loaded',
          schema,
          entries: listed.entries,
          counts: listed.counts,
          truncated: listed.truncated,
          review: review.entries,
        });
      } catch (error: unknown) {
        if (controller.signal.aborted) return;
        dispatch({ type: 'load-failed', message: describeFailure(error) });
      }
    })();

    return () => controller.abort();
  }, [client, projectId, attempt, listOnce]);

  // -- filters -------------------------------------------------------------------------------

  const filterKey = keyOf(state.filters);
  useEffect(() => {
    // Nothing to refetch until the first load has landed, and nothing to refetch when the rows
    // on screen already answer these filters — which is the case on the tick after a load.
    if (state.status !== 'ready' || fetched.current === filterKey) {
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      const filters = filtersRef.current;
      fetched.current = keyOf(filters);
      dispatch({ type: 'list-requested' });
      void (async () => {
        try {
          const listed = await listOnce(filters, controller.signal);
          if (controller.signal.aborted) return;
          dispatch({
            type: 'listed',
            entries: listed.entries,
            counts: listed.counts,
            truncated: listed.truncated,
          });
        } catch (error: unknown) {
          if (controller.signal.aborted) return;
          // The rows already on screen stay. A refresh that did not land is not a reason to
          // take away the last answer the server gave (P1-12).
          fetched.current = null;
          dispatch({ type: 'list-failed', message: describeFailure(error) });
        }
      })();
    }, debounceMs);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [filterKey, state.status, debounceMs, listOnce]);

  // -- reads ---------------------------------------------------------------------------------

  const refresh = useCallback(async (): Promise<void> => {
    const filters = filtersRef.current;
    fetched.current = keyOf(filters);
    try {
      const [listed, review] = await Promise.all([
        listOnce(filters),
        client.listEntries(projectId, { needs_review: true }),
      ]);
      dispatch({
        type: 'listed',
        entries: listed.entries,
        counts: listed.counts,
        truncated: listed.truncated,
      });
      dispatch({ type: 'review-loaded', entries: review.entries });
    } catch (error: unknown) {
      fetched.current = null;
      dispatch({ type: 'list-failed', message: describeFailure(error) });
    }
  }, [client, listOnce, projectId]);

  const loadDeleted = useCallback(async (): Promise<void> => {
    const listed = await client.listDeletedEntries(projectId);
    dispatch({ type: 'deleted-loaded', entries: listed.entries });
  }, [client, projectId]);

  const readEntry = useCallback(
    (entryId: string): Promise<EntryDetail> => client.getEntry(entryId),
    [client],
  );

  const readEntryLinks = useCallback(
    async (entryId: string): Promise<LinkView[]> => (await client.listEntryLinks(entryId)).links,
    [client],
  );

  const listRevisions = useCallback(
    async (entryId: string): Promise<RevisionMeta[]> =>
      (await client.listEntryRevisions(entryId)).revisions,
    [client],
  );

  const readRevision = useCallback(
    (entryId: string, number: number): Promise<EntryRevision> =>
      client.getEntryRevision(entryId, number),
    [client],
  );

  const listCandidates = useCallback(
    async (kind?: string): Promise<Entry[]> =>
      (await client.listEntries(projectId, kind === undefined ? {} : { kind })).entries,
    [client, projectId],
  );

  const readStoryTime = useCallback(
    (): Promise<StoryTime> => client.getStoryTime(projectId),
    [client, projectId],
  );

  // -- writes --------------------------------------------------------------------------------

  const createEntry = useCallback(
    async (input: EntryInput): Promise<Entry> => {
      const entry = await client.createEntry(projectId, input);
      await refresh();
      return entry;
    },
    [client, projectId, refresh],
  );

  const updateEntry = useCallback(
    async (entryId: string, patch: EntryPatch): Promise<EntryWriteResult> => {
      const result = await client.updateEntry(entryId, patch);
      await refresh();
      return result;
    },
    [client, refresh],
  );

  const clearReview = useCallback(
    async (entryId: string, revision: number): Promise<EntryWriteResult> => {
      const result = await client.clearEntryReview(entryId, revision);
      await refresh();
      return result;
    },
    [client, refresh],
  );

  const restoreRevision = useCallback(
    async (entryId: string, number: number, revision: number): Promise<EntryWriteResult> => {
      const result = await client.restoreEntryRevision(entryId, number, revision);
      await refresh();
      return result;
    },
    [client, refresh],
  );

  const deleteEntry = useCallback(
    async (entryId: string): Promise<Entry> => {
      const entry = await client.deleteEntry(entryId);
      await Promise.all([refresh(), loadDeleted()]);
      return entry;
    },
    [client, loadDeleted, refresh],
  );

  const restoreEntry = useCallback(
    async (entryId: string): Promise<Entry> => {
      const entry = await client.restoreEntry(entryId);
      await Promise.all([refresh(), loadDeleted()]);
      return entry;
    },
    [client, loadDeleted, refresh],
  );

  const createLink = useCallback(
    async (input: LinkInput): Promise<Link> => client.createLink(projectId, input),
    [client, projectId],
  );

  const patchLink = useCallback(
    (linkId: string, patch: LinkPatch): Promise<Link> => client.patchLink(linkId, patch),
    [client],
  );

  const deleteLink = useCallback(
    (linkId: string): Promise<Link> => client.deleteLink(linkId),
    [client],
  );

  const cite = useCallback(
    (entryId: string, anchorId: string, role: CitationRole): Promise<Citation> =>
      client.citeAnchor(entryId, anchorId, role),
    [client],
  );

  const uncite = useCallback(
    (entryId: string, anchorId: string, role?: CitationRole): Promise<CitationRemoved> =>
      client.unciteAnchor(entryId, anchorId, role),
    [client],
  );

  const entryCreated = useCallback(
    (entry: Entry) => {
      // The entry itself is not spliced in: the list is the server's filtered answer, and an
      // entry pushed into it locally would sit there whether or not it matches the filters.
      dispatch({ type: 'entry-opened', entryId: entry.id });
      void refresh();
    },
    [refresh],
  );

  const setFilters = useCallback(
    (filters: Partial<EntryFilters>) => dispatch({ type: 'filters-changed', filters }),
    [],
  );

  const openEntry = useCallback(
    (entryId: string | null) => dispatch({ type: 'entry-opened', entryId }),
    [],
  );

  const value = useMemo<BibleContextValue>(
    () => ({
      state,
      dispatch,
      setFilters,
      openEntry,
      refresh,
      reload: retry,
      createEntry,
      readEntry,
      readEntryLinks,
      updateEntry,
      clearReview,
      deleteEntry,
      restoreEntry,
      loadDeleted,
      listRevisions,
      readRevision,
      restoreRevision,
      listCandidates,
      createLink,
      patchLink,
      deleteLink,
      cite,
      uncite,
      entryCreated,
      readStoryTime,
    }),
    [
      state,
      setFilters,
      openEntry,
      refresh,
      createEntry,
      readEntry,
      readEntryLinks,
      updateEntry,
      clearReview,
      deleteEntry,
      restoreEntry,
      loadDeleted,
      listRevisions,
      readRevision,
      restoreRevision,
      listCandidates,
      createLink,
      patchLink,
      deleteLink,
      cite,
      uncite,
      entryCreated,
      readStoryTime,
    ],
  );

  return <BibleContext.Provider value={value}>{children}</BibleContext.Provider>;
}

export function useBible(): BibleContextValue {
  const value = useContext(BibleContext);
  if (!value) {
    throw new Error('useBible must be used inside a BibleProvider');
  }
  return value;
}

function keyOf(filters: EntryFilters): string {
  return `${filters.kind ?? ''} ${filters.status ?? ''} ${filters.q.trim()}`;
}
