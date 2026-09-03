/**
 * One entry, whole (P3-13, P3-14).
 *
 * The record itself in the generic form, and beside it the three things that make it more than a
 * note: the passages it came from, the entries it is joined to, and everything it has ever said.
 *
 * ## The `409` is answered, never merged
 *
 * An entry's conflict has a code of its own — `entry_version_conflict`, not `version_conflict` —
 * because the two surfaces recover differently: the editor offers to reload a chapter, this
 * offers to reload a record. When one arrives the form **stops**, says what happened, and keeps
 * the writer's typing on screen. Reloading is the writer's choice and it is the only one offered
 * (D19, ruling 3). Nothing here merges two versions of an entry.
 *
 * ## Deleting is recoverable and does not cascade
 *
 * The row, its revisions, its links, and its citations all stay; the entry leaves every list,
 * count, link view, and the review queue, because all of those filter on one predicate (D25).
 * Restoring brings back exactly the links it had, because nothing ever removed them.
 */

import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '../api';
import type { Entry, EntryDetail, EntryVersionConflictDetail, LinkView } from '../api/types';
import { kindLabel } from '../bibleSchema';
import { formatRelativeTime, formatDateTime, plural } from '../format';
import { useBible } from '../state/BibleContext';
import { describeFailure, useProject } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';
import { EntryCitations } from './EntryCitations';
import { EntryForm, formErrorsOf } from './EntryForm';
import type { EntryDraft } from './EntryForm';
import { EntryHistory } from './EntryHistory';
import { EntryLinksPanel } from './EntryLinksPanel';

export interface EntryDetailViewProps {
  entryId: string;
  onClose: () => void;
  onOpen: (entryId: string) => void;
}

export function EntryDetailView({ entryId, onClose, onOpen }: EntryDetailViewProps) {
  const {
    state,
    readEntry,
    readEntryLinks,
    updateEntry,
    clearReview,
    deleteEntry,
    restoreEntry,
    listCandidates,
  } = useBible();
  const { state: projectState } = useProject();
  const { push } = useToasts();

  const [detail, setDetail] = useState<EntryDetail | null>(null);
  const [links, setLinks] = useState<LinkView[]>([]);
  const [candidates, setCandidates] = useState<Entry[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState<EntryVersionConflictDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [reloads, reload] = useState(0);

  useEffect(() => {
    let live = true;
    setFailure(null);
    void (async () => {
      try {
        const [found, joined, offered] = await Promise.all([
          readEntry(entryId),
          readEntryLinks(entryId),
          listCandidates(),
        ]);
        if (!live) return;
        setDetail(found);
        setLinks(joined);
        setCandidates(offered);
      } catch (error: unknown) {
        if (live) {
          setFailure(describeFailure(error));
        }
      }
    })();
    return () => {
      live = false;
    };
  }, [entryId, reloads, readEntry, readEntryLinks, listCandidates]);

  const again = useCallback(() => reload((count) => count + 1), []);

  const onSubmit = useCallback(
    (draft: EntryDraft, retcon: boolean | null) => {
      if (detail === null) {
        return;
      }
      setBusy(true);
      setErrors({});
      setConflict(null);
      void (async () => {
        try {
          const result = await updateEntry(entryId, {
            revision: detail.entry.revision,
            name: draft.name,
            summary: draft.summary,
            body_md: draft.body_md,
            attributes: draft.attributes,
            // Sent only when the writer moved the box. Left out, the store's own computation
            // stands — which is what keeps the client's prediction presentational (D27).
            ...(retcon === null ? {} : { retcon }),
          });
          push(describeWrite(result.retcon, result.flagged.length, result.changed_fields));
          again();
        } catch (error: unknown) {
          const detailOf409 = error instanceof ApiError ? error.entryVersionConflict : null;
          if (detailOf409 !== null) {
            // Nothing was written. The typing stays on screen; the writer decides.
            setConflict(detailOf409);
          } else {
            setErrors(formErrorsOf(error));
          }
        } finally {
          setBusy(false);
        }
      })();
    },
    [again, detail, entryId, push, updateEntry],
  );

  const onClearReview = useCallback(() => {
    if (detail === null) {
      return;
    }
    setBusy(true);
    void (async () => {
      try {
        await clearReview(entryId, detail.entry.revision);
        again();
      } catch (error: unknown) {
        push(`Could not clear that review — ${describeFailure(error)}`, 'error');
      } finally {
        setBusy(false);
      }
    })();
  }, [again, clearReview, detail, entryId, push]);

  const onDelete = useCallback(() => {
    setBusy(true);
    void (async () => {
      try {
        await deleteEntry(entryId);
        push('Deleted. It is in the deleted tray at the foot of the Bible tab.');
        again();
      } catch (error: unknown) {
        push(`Could not delete that entry — ${describeFailure(error)}`, 'error');
      } finally {
        setBusy(false);
      }
    })();
  }, [again, deleteEntry, entryId, push]);

  const onRestore = useCallback(() => {
    setBusy(true);
    void (async () => {
      try {
        await restoreEntry(entryId);
        push('Restored, with its links and its citations.');
        again();
      } catch (error: unknown) {
        push(`Could not restore that entry — ${describeFailure(error)}`, 'error');
      } finally {
        setBusy(false);
      }
    })();
  }, [again, entryId, push, restoreEntry]);

  if (failure !== null) {
    return (
      <div className="entry-detail">
        <button type="button" className="entry-back" onClick={onClose}>
          ← All entries
        </button>
        <p role="alert" data-testid="entry-status">
          This entry could not be read — {failure}
        </p>
      </div>
    );
  }

  if (detail === null || state.schema === null) {
    return (
      <div className="entry-detail">
        <p data-testid="entry-status">Opening the entry…</p>
      </div>
    );
  }

  const entry = detail.entry;
  const definition = state.schema.kinds.find((kind) => kind.kind === entry.kind) ?? null;
  const chapter =
    detail.narrative_position === null
      ? null
      : (projectState.chapters.find(
          (candidate) => candidate.document_id === detail.narrative_position?.document_id,
        )?.title ?? null);

  return (
    <div className="entry-detail">
      <button type="button" className="entry-back" onClick={onClose}>
        ← All entries
      </button>

      <header className="entry-detail-header">
        <p className="entry-kind">{kindLabel(state.schema, entry.kind)}</p>
        <h3>{entry.name}</h3>
        <p className="entry-meta">
          revision {entry.revision} · {plural(detail.link_count, 'link')} ·{' '}
          <span title={formatDateTime(entry.updated_at)}>
            {formatRelativeTime(entry.updated_at)}
          </span>
          {chapter !== null && <> · first seen in {chapter}</>}
        </p>
      </header>

      {entry.deleted_at !== null && (
        <div className="entry-deleted-banner" role="status">
          <p>
            Deleted {formatRelativeTime(entry.deleted_at)}. Its revisions, links, and citations are
            all still here.
          </p>
          <button type="button" disabled={busy} onClick={onRestore}>
            Restore
          </button>
        </div>
      )}

      {entry.needs_review && (
        <div className="entry-review-banner" role="status">
          <p>{entry.review_reason || 'Something this entry depended on has moved.'}</p>
          <button type="button" disabled={busy} onClick={onClearReview}>
            Reviewed
          </button>
        </div>
      )}

      {conflict !== null && (
        <div className="entry-conflict" role="alert">
          <p>
            This entry changed somewhere else — it is at revision {conflict.current_revision}, and
            you are editing revision {conflict.presented_revision}. Nothing was saved.
          </p>
          <button
            type="button"
            onClick={() => {
              setConflict(null);
              again();
            }}
          >
            Load the server's copy
          </button>
        </div>
      )}

      {errors[''] && (
        <p className="entry-field-error" role="alert">
          {errors['']}
        </p>
      )}

      {definition === null ? (
        <p role="alert">
          The definition does not describe a “{entry.kind}”, so this entry cannot be shown.
        </p>
      ) : (
        <EntryForm
          definition={definition}
          entry={entry}
          candidates={candidates}
          busy={busy}
          errors={errors}
          submitLabel="Save"
          onSubmit={onSubmit}
          onCancel={null}
        />
      )}

      <EntryCitations entryId={entry.id} citations={detail.citations} onChanged={again} />

      <EntryLinksPanel
        entry={entry}
        schema={state.schema}
        links={links}
        onChanged={again}
        onOpen={onOpen}
      />

      <section className="entry-history-section" aria-label="History">
        <button
          type="button"
          className="entry-history-toggle"
          aria-expanded={historyOpen}
          onClick={() => setHistoryOpen((open) => !open)}
        >
          History ({plural(entry.revision, 'revision')})
        </button>
        {historyOpen && <EntryHistory entry={entry} onRestored={again} />}
      </section>

      {entry.deleted_at === null && (
        <div className="entry-danger">
          <button type="button" disabled={busy} onClick={onDelete}>
            Delete this entry
          </button>
        </div>
      )}
    </div>
  );
}

/** What a save actually did, in one sentence — including that it disturbed nothing. */
export function describeWrite(
  retcon: boolean,
  flagged: number,
  changedFields: readonly string[],
): string {
  if (!retcon) {
    return 'Saved. Nothing else was asked to be reviewed.';
  }
  const because = changedFields.length > 0 ? ` The ${changedFields.join(', ')} changed.` : '';
  if (flagged === 0) {
    return `Saved as a retcon. Nothing links to this entry, so nothing was flagged.${because}`;
  }
  return `Saved as a retcon. ${plural(flagged, 'entry', 'entries')} asked to be reviewed.${because}`;
}
