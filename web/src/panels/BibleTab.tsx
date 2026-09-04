/**
 * The Bible tab (P3-12).
 *
 * Four surfaces behind one tab, because they answer four different questions and putting them in
 * one scroll would mean the review queue lives below however many characters this manuscript has:
 *
 * * **Entries** — the browse list, filtered and searched, grouped by kind or flat;
 * * **Review** — the retcon queue (D27). Not a badge on a list: a retcon's whole point is that
 *   the writer walks the consequences, so this is a place they can work through, and it empties;
 * * **Story-time** — the ordering module's three answers (D28). A readout, not a timeline;
 * * **Deleted** — the restore tray, on the same footing as *Deleted chapters* (D25).
 *
 * Opening an entry replaces all four with its detail view, and *← All entries* comes back. A
 * master–detail inside the panel rather than a dialog: the panel is resizable to a form's width,
 * the workspace already has a place for every surface, and a modal over the manuscript would be
 * the one thing the writer cannot type behind.
 *
 * The search box does not refetch per keystroke — `BibleContext` debounces it — and the kind
 * counts beside the filters are the server's **live, unfiltered** answer, so "how many characters
 * are there" is answered while only the places are showing.
 */

import { useCallback, useMemo, useState } from 'react';
import type { Entry } from '../api/types';
import { kindLabel, kindPlural } from '../bibleSchema';
import { formatRelativeTime, plural } from '../format';
import { useBible } from '../state/BibleContext';
import type { EntryFilters } from '../state/bibleReducer';
import { groupByKind, isFiltered, totalEntries } from '../state/bibleReducer';
import { describeFailure } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';
import { EntryDetailView } from './EntryDetailView';
import { EntryForm, formErrorsOf } from './EntryForm';
import type { EntryDraft } from './EntryForm';
import { StoryTimeCheck } from './StoryTimeCheck';

type View = 'browse' | 'review' | 'storytime' | 'deleted';

export function BibleTab() {
  const { state, setFilters, openEntry, reload, loadDeleted, clearReview, restoreEntry } =
    useBible();
  const { push } = useToasts();
  const [view, setView] = useState<View>('browse');
  const [grouped, setGrouped] = useState(true);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [written, setWritten] = useState(0);

  const noteWritten = useCallback(() => setWritten((count) => count + 1), []);

  const show = useCallback(
    (next: View) => {
      setView(next);
      if (next === 'deleted') {
        void loadDeleted().catch((error: unknown) =>
          push(`Could not read the deleted entries — ${describeFailure(error)}`, 'error'),
        );
      }
    },
    [loadDeleted, push],
  );

  const onOpen = useCallback(
    (entryId: string) => {
      setCreating(false);
      openEntry(entryId);
    },
    [openEntry],
  );

  const onReviewed = useCallback(
    async (entry: Entry) => {
      setBusy(entry.id);
      try {
        await clearReview(entry.id, entry.revision);
        noteWritten();
      } catch (error: unknown) {
        push(`Could not clear that review — ${describeFailure(error)}`, 'error');
      } finally {
        setBusy(null);
      }
    },
    [clearReview, noteWritten, push],
  );

  const onRestore = useCallback(
    async (entry: Entry) => {
      setBusy(entry.id);
      try {
        await restoreEntry(entry.id);
        noteWritten();
        push(`${entry.name} is back, with its links and its citations.`);
      } catch (error: unknown) {
        push(`Could not restore that entry — ${describeFailure(error)}`, 'error');
      } finally {
        setBusy(null);
      }
    },
    [noteWritten, push, restoreEntry],
  );

  if (state.status === 'loading') {
    return <p data-testid="bible-status">Reading the bible…</p>;
  }
  if (state.status === 'failed') {
    return (
      <div className="bible">
        <p data-testid="bible-status" role="alert">
          Could not read the bible — {state.error}
        </p>
        <button type="button" onClick={reload}>
          Try again
        </button>
      </div>
    );
  }

  if (state.openId !== null) {
    return (
      <EntryDetailView
        entryId={state.openId}
        onClose={() => {
          openEntry(null);
          noteWritten();
        }}
        onOpen={onOpen}
      />
    );
  }

  return (
    <div className="bible">
      <div className="bible-views" role="group" aria-label="Bible views">
        <button type="button" aria-pressed={view === 'browse'} onClick={() => show('browse')}>
          Entries ({totalEntries(state.counts)})
        </button>
        <button type="button" aria-pressed={view === 'review'} onClick={() => show('review')}>
          Review ({state.review.length})
        </button>
        <button type="button" aria-pressed={view === 'storytime'} onClick={() => show('storytime')}>
          Story-time
        </button>
        <button type="button" aria-pressed={view === 'deleted'} onClick={() => show('deleted')}>
          Deleted
        </button>
      </div>

      {state.error !== null && (
        <p className="bible-error" role="alert">
          {state.error}
        </p>
      )}

      {view === 'browse' && (
        <BrowseView
          grouped={grouped}
          onToggleGrouped={() => setGrouped((current) => !current)}
          creating={creating}
          onCreating={setCreating}
          onOpen={onOpen}
          onCreated={noteWritten}
          setFilters={setFilters}
        />
      )}

      {view === 'review' && (
        <section className="bible-review" aria-label="Review queue">
          {state.review.length === 0 ? (
            <p className="panel-placeholder" data-testid="review-empty">
              Nothing is waiting to be reviewed. A retcon — a change to a name or a field — asks
              the entries linked to it to be looked at again.
            </p>
          ) : (
            <ul className="bible-list">
              {state.review.map((entry) => (
                <li key={entry.id} className="bible-row bible-row-review">
                  <button type="button" className="bible-row-name" onClick={() => onOpen(entry.id)}>
                    {entry.name}
                  </button>
                  <span className="bible-row-kind">{kindLabel(state.schema, entry.kind)}</span>
                  <p className="bible-row-reason">
                    {entry.review_reason || 'Something this entry depended on has moved.'}
                  </p>
                  <button
                    type="button"
                    disabled={busy === entry.id}
                    onClick={() => void onReviewed(entry)}
                  >
                    Reviewed
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {view === 'storytime' && <StoryTimeCheck refreshKey={written} onOpen={onOpen} />}

      {view === 'deleted' && (
        <section className="bible-deleted" aria-label="Deleted entries">
          {state.deleted.length === 0 ? (
            <p className="panel-placeholder">Nothing has been deleted.</p>
          ) : (
            <ul className="bible-list">
              {state.deleted.map((entry) => (
                <li key={entry.id} className="bible-row">
                  <button type="button" className="bible-row-name" onClick={() => onOpen(entry.id)}>
                    {entry.name}
                  </button>
                  <span className="bible-row-kind">{kindLabel(state.schema, entry.kind)}</span>
                  {entry.deleted_at !== null && (
                    <span className="bible-row-when">
                      deleted {formatRelativeTime(entry.deleted_at)}
                    </span>
                  )}
                  <button
                    type="button"
                    disabled={busy === entry.id}
                    onClick={() => void onRestore(entry)}
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

interface BrowseViewProps {
  grouped: boolean;
  onToggleGrouped: () => void;
  creating: boolean;
  onCreating: (creating: boolean) => void;
  onOpen: (entryId: string) => void;
  onCreated: () => void;
  setFilters: (filters: Partial<EntryFilters>) => void;
}

function BrowseView({
  grouped,
  onToggleGrouped,
  creating,
  onCreating,
  onOpen,
  onCreated,
  setFilters,
}: BrowseViewProps) {
  const { state } = useBible();
  const schema = state.schema;

  const groups = useMemo<[string, Entry[]][]>(
    () => (grouped ? groupByKind(state.entries, schema) : [['', [...state.entries]]]),
    [grouped, schema, state.entries],
  );

  return (
    <div className="bible-browse">
      <div className="bible-filters">
        <label htmlFor="bible-search" className="visually-hidden">
          Search the bible
        </label>
        <input
          id="bible-search"
          type="search"
          placeholder="Search names, aliases, summaries"
          value={state.filters.q}
          onChange={(event) => setFilters({ q: event.target.value })}
        />

        <label htmlFor="bible-kind" className="visually-hidden">
          Filter by kind
        </label>
        <select
          id="bible-kind"
          value={state.filters.kind ?? ''}
          onChange={(event) => setFilters({ kind: event.target.value || null })}
        >
          <option value="">Every kind ({totalEntries(state.counts)})</option>
          {(schema?.kinds ?? []).map((definition) => (
            <option key={definition.kind} value={definition.kind}>
              {definition.plural} ({state.counts[definition.kind] ?? 0})
            </option>
          ))}
        </select>

        <label htmlFor="bible-status" className="visually-hidden">
          Filter by status
        </label>
        <select
          id="bible-status"
          value={state.filters.status ?? ''}
          onChange={(event) => setFilters({ status: event.target.value || null })}
        >
          <option value="">Any status</option>
          <option value="accepted">Accepted</option>
          <option value="proposed">Proposed</option>
          <option value="rejected">Rejected</option>
          <option value="superseded">Superseded</option>
        </select>

        <button type="button" aria-pressed={grouped} onClick={onToggleGrouped}>
          {grouped ? 'Grouped' : 'Flat'}
        </button>
      </div>

      {state.truncated && (
        <p className="bible-truncated" role="status">
          There are more matches than this list shows. Narrow the search.
        </p>
      )}

      {state.entries.length === 0 && (
        <p className="panel-placeholder" data-testid="bible-empty">
          {isFiltered(state.filters)
            ? 'Nothing matches that.'
            : 'The bible is empty. Select a passage in the manuscript and choose “Add to bible”, or start one here.'}
        </p>
      )}

      {groups.map(([kind, entries]) => (
        <section key={kind || 'all'} className="bible-group">
          {kind !== '' && <h4>{kindPlural(schema, kind)}</h4>}
          <ul className="bible-list">
            {entries.map((entry) => (
              <li key={entry.id} className="bible-row">
                <button type="button" className="bible-row-name" onClick={() => onOpen(entry.id)}>
                  {entry.name}
                </button>
                {!grouped && (
                  <span className="bible-row-kind">{kindLabel(schema, entry.kind)}</span>
                )}
                {entry.needs_review && <span className="bible-row-flag">needs review</span>}
                {entry.summary && <p className="bible-row-summary">{entry.summary}</p>}
              </li>
            ))}
          </ul>
        </section>
      ))}

      <p className="bible-total" data-testid="bible-total">
        {plural(totalEntries(state.counts), 'entry', 'entries')} in the bible
      </p>

      {creating ? (
        <NewEntry onCancel={() => onCreating(false)} onOpen={onOpen} onCreated={onCreated} />
      ) : (
        <button type="button" className="bible-new" onClick={() => onCreating(true)}>
          New entry
        </button>
      )}
    </div>
  );
}

interface NewEntryProps {
  onCancel: () => void;
  onOpen: (entryId: string) => void;
  onCreated: () => void;
}

/**
 * Making an entry by hand.
 *
 * The kind is chosen first and is then **fixed forever** — it is immutable after creation,
 * refused rather than discouraged, because every attribute the entry holds was validated against
 * that kind's field list. The wrong kind is fixed by creating the right entry and deleting the
 * wrong one, which is recoverable both ways.
 */
function NewEntry({ onCancel, onOpen, onCreated }: NewEntryProps) {
  const { state, createEntry, listCandidates } = useBible();
  const [kind, setKind] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [candidates, setCandidates] = useState<Entry[]>([]);

  const definition = state.schema?.kinds.find((item) => item.kind === kind) ?? null;

  const onPickKind = useCallback(
    (next: string) => {
      setKind(next);
      setErrors({});
      // The pickers want what exists *now* — including the place made a moment ago, which is
      // exactly the one a writer reaches for while filling in the character who lives there.
      void listCandidates()
        .then(setCandidates)
        .catch(() => setCandidates([]));
    },
    [listCandidates],
  );

  const onSubmit = useCallback(
    (draft: EntryDraft) => {
      setBusy(true);
      setErrors({});
      void (async () => {
        try {
          const created = await createEntry({
            kind,
            name: draft.name,
            summary: draft.summary,
            body_md: draft.body_md,
            attributes: draft.attributes,
          });
          onCreated();
          onOpen(created.id);
        } catch (error: unknown) {
          setErrors(formErrorsOf(error));
        } finally {
          setBusy(false);
        }
      })();
    },
    [createEntry, kind, onCreated, onOpen],
  );

  return (
    <div className="bible-new-entry">
      <h4>New entry</h4>
      <div className="entry-field">
        <label htmlFor="new-entry-kind">Kind</label>
        <select
          id="new-entry-kind"
          value={kind}
          disabled={busy}
          onChange={(event) => onPickKind(event.target.value)}
        >
          <option value="">Choose a kind…</option>
          {(state.schema?.kinds ?? []).map((item) => (
            <option key={item.kind} value={item.kind}>
              {item.label}
            </option>
          ))}
        </select>
        <p className="entry-field-help">Chosen once. A kind cannot be changed afterwards.</p>
      </div>

      {errors[''] && (
        <p className="entry-field-error" role="alert">
          {errors['']}
        </p>
      )}

      {definition !== null && (
        <EntryForm
          definition={definition}
          entry={null}
          candidates={candidates}
          busy={busy}
          errors={errors}
          submitLabel="Create"
          onSubmit={onSubmit}
          onCancel={onCancel}
        />
      )}

      {definition === null && (
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      )}
    </div>
  );
}
