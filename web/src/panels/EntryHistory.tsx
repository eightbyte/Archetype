/**
 * One entry's revision history (P3-13, D27).
 *
 * Complete from creation — revision 1 is the entry being made — newest first, and nothing in it
 * is ever deduplicated or pruned. That is the deliberate opposite of a chapter's snapshots on
 * both counts (D23): a `handover` snapshot is 300 KB nobody asked for, and a revision is two
 * kilobytes somebody typed.
 *
 * The list carries **metadata only**. A revision's recorded state is read when the writer asks to
 * see one, which is the discipline the snapshot list already follows: a history that pulls every
 * past version of everything to draw a list of dates is a history nobody opens twice.
 *
 * ## What was cut, deliberately
 *
 * A word-level diff. P3-13 pre-marks it as the correct thing to cut if the preview lands and it
 * does not, so that cutting it is a decision rather than a shortfall. What landed instead is a
 * **field-level** marker: the preview says which of the entry's fields the revision holds
 * differently from the record as it stands now, which is the question a writer deciding whether
 * to restore is actually asking.
 *
 * Restoring goes through the ordinary update path, so it bumps the revision, appends to the
 * history rather than rewriting it, is guarded by D19, and computes its own retcon answer.
 */

import { useCallback, useEffect, useState } from 'react';
import type { Entry, EntryRevision, RevisionMeta } from '../api/types';
import { formatRelativeTime, formatDateTime } from '../format';
import { useBible } from '../state/BibleContext';
import { useToasts } from '../state/ToastContext';
import { describeFailure } from '../state/ProjectContext';

export interface EntryHistoryProps {
  entry: Entry;
  /** The history changed the entry — the detail view re-reads it. */
  onRestored: () => void;
}

export function EntryHistory({ entry, onRestored }: EntryHistoryProps) {
  const { listRevisions, readRevision, restoreRevision } = useBible();
  const { push } = useToasts();
  const [revisions, setRevisions] = useState<RevisionMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<EntryRevision | null>(null);
  const [busy, setBusy] = useState(false);

  const entryId = entry.id;
  const revision = entry.revision;

  useEffect(() => {
    let live = true;
    setError(null);
    void (async () => {
      try {
        const listed = await listRevisions(entryId);
        if (live) {
          setRevisions(listed);
        }
      } catch (failure: unknown) {
        if (live) {
          setError(describeFailure(failure));
        }
      }
    })();
    return () => {
      live = false;
    };
    // `revision` is in the list on purpose: every write appends one, so the history is stale the
    // moment the entry is saved.
  }, [entryId, revision, listRevisions]);

  const onPreview = useCallback(
    async (number: number) => {
      if (preview?.meta.revision === number) {
        setPreview(null);
        return;
      }
      try {
        setPreview(await readRevision(entryId, number));
      } catch (failure: unknown) {
        push(`Could not read that revision — ${describeFailure(failure)}`, 'error');
      }
    },
    [entryId, preview, push, readRevision],
  );

  const onRestore = useCallback(
    async (number: number) => {
      setBusy(true);
      try {
        const result = await restoreRevision(entryId, number, revision);
        setPreview(null);
        push(
          `Restored revision ${number} as revision ${result.revision}.` +
            (result.flagged.length > 0
              ? ` ${result.flagged.length} linked ${result.flagged.length === 1 ? 'entry' : 'entries'} asked to be reviewed.`
              : ''),
        );
        onRestored();
      } catch (failure: unknown) {
        push(`Could not restore that revision — ${describeFailure(failure)}`, 'error');
      } finally {
        setBusy(false);
      }
    },
    [entryId, onRestored, push, restoreRevision, revision],
  );

  if (error !== null) {
    return (
      <p className="entry-history-status" role="alert">
        Could not read the history — {error}
      </p>
    );
  }
  if (revisions === null) {
    return <p className="entry-history-status">Reading the history…</p>;
  }

  return (
    <div className="entry-history">
      <ul className="entry-history-list">
        {revisions.map((meta) => (
          <li key={meta.revision} className={meta.retcon ? 'entry-revision retcon' : 'entry-revision'}>
            <div className="entry-revision-row">
              <span className="entry-revision-number">#{meta.revision}</span>
              <span className="entry-revision-when" title={formatDateTime(meta.revised_at)}>
                {formatRelativeTime(meta.revised_at)}
              </span>
              {meta.retcon && <span className="entry-revision-retcon">retcon</span>}
              {meta.revision === entry.revision && (
                <span className="entry-revision-current">current</span>
              )}
            </div>
            {meta.reason && <p className="entry-revision-why">{meta.reason}</p>}
            <div className="entry-revision-actions">
              <button
                type="button"
                aria-expanded={preview?.meta.revision === meta.revision}
                onClick={() => void onPreview(meta.revision)}
              >
                Preview
              </button>
              <button
                type="button"
                disabled={busy || meta.revision === entry.revision}
                onClick={() => void onRestore(meta.revision)}
              >
                Restore
              </button>
            </div>
            {preview?.meta.revision === meta.revision && (
              <RevisionPreview revision={preview} entry={entry} />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * What one revision recorded, with the fields that differ from the record as it stands now
 * marked.
 *
 * The state is the entry **after** that write, so revision *n* is what the entry was at revision
 * *n* — reading a past state is one row rather than a replay of everything before it.
 */
function RevisionPreview({ revision, entry }: { revision: EntryRevision; entry: Entry }) {
  const state = revision.state;
  const rows: { label: string; now: unknown; then: unknown }[] = [
    { label: 'Name', now: entry.name, then: state['name'] },
    { label: 'Summary', now: entry.summary, then: state['summary'] },
    { label: 'Notes', now: entry.body_md, then: state['body_md'] },
    { label: 'Fields', now: entry.attributes, then: state['attributes'] },
  ];
  return (
    <div className="entry-revision-preview" data-testid="revision-preview">
      <dl>
        {rows.map((row) => {
          const changed = JSON.stringify(row.now ?? null) !== JSON.stringify(row.then ?? null);
          return (
            <div key={row.label} className={changed ? 'preview-row changed' : 'preview-row'}>
              <dt>
                {row.label}
                {changed && <span className="preview-changed"> differs from now</span>}
              </dt>
              <dd>{describeValue(row.then)}</dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

/** A stored value in one line of prose. Nothing here parses; it only reads back. */
function describeValue(value: unknown): string {
  if (value === undefined || value === null || value === '') {
    return '—';
  }
  if (typeof value === 'string') {
    return value;
  }
  if (Array.isArray(value)) {
    return value.length === 0 ? '—' : value.map((item) => String(item)).join(', ');
  }
  if (typeof value === 'object') {
    const parts = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined && item !== null && item !== '')
      .map(([key, item]) => `${key}: ${describeValue(item)}`);
    return parts.length === 0 ? '—' : parts.join(' · ');
  }
  return String(value);
}
