/**
 * The *Marks* tab: every anchor in the project, and the repair path (P2-10, § 2 ruling 6).
 *
 * Grouped by chapter, filterable by status, so "what is stale" is one click. It is the anchors'
 * only consumer this phase and is deliberately thin — in Phase 3 the Bible tab becomes their
 * real one, and this may narrow to a stale-anchor surface.
 *
 * ## Nothing here repairs anything by itself
 *
 * That is the product promise this whole phase is built around (§ 2, ruling 2). A `stale` mark
 * shows the words it was made over beside the passage the server *suggests*, and the suggestion
 * is a button, not an outcome. Accepting one and choosing a passage by hand send the identical
 * request — a range and the version it was chosen against — so the server cannot tell them apart
 * and does not try.
 *
 * An `orphaned` mark is not repaired at all: its chapter was deleted, its text is untouched, and
 * restoring the chapter brings it back exactly as it was (D22). Offering to re-link it would be
 * offering to solve the wrong problem.
 *
 * The list is the **project** list — the server's cached answers, refreshed for a chapter the
 * moment it is opened or saved (B8). Drawing it does not project every chapter in the
 * manuscript, which is what D2 and P1-5 exist to prevent.
 */

import { useCallback, useMemo, useState } from 'react';
import type { Anchor, AnchorStatus } from '../api';
import { ANCHOR_STATUSES } from '../api';
import { useDocument } from '../state/DocumentContext';
import { useProject } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';
import { plural } from '../format';
import { previewQuote, STATUS_WORDS } from '../anchorText';

type Filter = 'all' | AnchorStatus;

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: ANCHOR_STATUSES.ok, label: 'Found' },
  { id: ANCHOR_STATUSES.stale, label: 'Lost' },
  { id: ANCHOR_STATUSES.orphaned, label: 'Deleted chapters' },
];

export function MarksTab() {
  const { state: projectState, relinkAnchor, removeAnchor, restoreChapter, armRelink } =
    useProject();
  const { state: documentState, goToAnchor } = useDocument();
  const { push } = useToasts();
  const [filter, setFilter] = useState<Filter>('all');
  const [busy, setBusy] = useState<string | null>(null);

  const titles = useMemo(() => {
    const byId = new Map<string, string>();
    for (const meta of projectState.documents) {
      byId.set(meta.id, meta.title);
    }
    for (const meta of projectState.deleted) {
      byId.set(meta.id, meta.title);
    }
    return byId;
  }, [projectState.documents, projectState.deleted]);

  const shown = useMemo(
    () =>
      filter === 'all'
        ? projectState.anchors
        : projectState.anchors.filter((anchor) => anchor.status === filter),
    [filter, projectState.anchors],
  );

  const grouped = useMemo(() => group(shown), [shown]);

  const counts = useMemo(() => {
    const tally: Record<string, number> = { all: projectState.anchors.length };
    for (const anchor of projectState.anchors) {
      tally[anchor.status] = (tally[anchor.status] ?? 0) + 1;
    }
    return tally;
  }, [projectState.anchors]);

  const run = useCallback(
    async (anchorId: string, what: string, action: () => Promise<unknown>) => {
      setBusy(anchorId);
      try {
        await action();
      } catch (error: unknown) {
        push(`${what} — ${error instanceof Error ? error.message : String(error)}`, 'error');
      } finally {
        setBusy(null);
      }
    },
    [push],
  );

  const onGoTo = useCallback(
    async (anchor: Anchor) => {
      if (!(await goToAnchor(anchor.document_id, anchor.id))) {
        push(
          'Staying put — the open chapter has unsaved changes that have not been saved yet.',
          'error',
        );
      }
    },
    [goToAnchor, push],
  );

  const onAcceptSuggestion = useCallback(
    (anchor: Anchor) => {
      const suggestion = anchor.suggestion;
      if (!suggestion) {
        return;
      }
      if (anchor.document_id !== documentState.documentId) {
        // The version presented has to be the one the range was chosen against, and the only
        // version this client is sure of is the open chapter's. So the chapter is opened first
        // and the writer accepts from there — one click more, and never a guess (D19).
        void onGoTo(anchor);
        push('Opened the chapter — accept the suggestion from here.');
        return;
      }
      void run(anchor.id, 'Could not re-link that mark', () =>
        relinkAnchor(anchor.id, {
          from_pos: suggestion.from_pos,
          to_pos: suggestion.to_pos,
          version: documentState.version,
        }),
      );
    },
    [documentState.documentId, documentState.version, onGoTo, push, relinkAnchor, run],
  );

  const onPickManually = useCallback(
    async (anchor: Anchor) => {
      armRelink(anchor.id);
      // Start where the mark is if its chapter still exists; the writer may re-link anywhere,
      // including in another chapter, and arming outlives every switch.
      if (anchor.status !== ANCHOR_STATUSES.orphaned) {
        await goToAnchor(anchor.document_id, anchor.id);
      }
      push('Select the passage in the chapter, then choose “Re-link here”.');
    },
    [armRelink, goToAnchor, push],
  );

  if (projectState.status === 'loading') {
    return <p data-testid="marks-status">Reading the marks…</p>;
  }
  if (projectState.status === 'failed') {
    return (
      <p data-testid="marks-status" role="alert">
        Could not read the marks — {projectState.error}
      </p>
    );
  }

  return (
    <div className="marks">
      <div className="marks-filters" role="group" aria-label="Filter marks by status">
        {FILTERS.map((option) => (
          <button
            key={option.id}
            type="button"
            aria-pressed={filter === option.id}
            onClick={() => setFilter(option.id)}
          >
            {option.label} ({counts[option.id] ?? 0})
          </button>
        ))}
      </div>

      {projectState.anchors.length === 0 && (
        <p className="panel-placeholder" data-testid="marks-status">
          No marks yet. Select a passage in the manuscript and choose “Mark passage”.
        </p>
      )}

      {projectState.anchors.length > 0 && shown.length === 0 && (
        <p className="panel-placeholder" data-testid="marks-status">
          Nothing with that status.
        </p>
      )}

      {grouped.map(([documentId, anchors]) => (
        <section key={documentId} className="marks-chapter">
          <h3>{titles.get(documentId) ?? 'A deleted chapter'}</h3>
          <ul className="marks-list">
            {anchors.map((anchor) => (
              <li key={anchor.id} className={`mark mark-${anchor.status}`}>
                <div className="mark-row">
                  <button
                    type="button"
                    className="mark-quote"
                    onClick={() => void onGoTo(anchor)}
                    disabled={anchor.status === ANCHOR_STATUSES.orphaned}
                  >
                    {previewQuote(anchor.quote) || <em>an empty passage</em>}
                  </button>
                  <span className="mark-status">{STATUS_WORDS[anchor.status]?.name}</span>
                </div>
                {anchor.label && <p className="mark-label">{anchor.label}</p>}

                {anchor.status === ANCHOR_STATUSES.stale && (
                  <div className="mark-repair">
                    <p className="mark-meaning">{STATUS_WORDS['stale']?.meaning}</p>
                    {anchor.suggestion && (
                      <div className="mark-suggestion">
                        <p className="mark-before">
                          <span>Was</span> {previewQuote(anchor.quote)}
                        </p>
                        <p className="mark-after">
                          <span>Suggested</span> {previewQuote(anchor.suggestion.text)}
                        </p>
                      </div>
                    )}
                    <div className="mark-actions">
                      {anchor.suggestion && (
                        <button
                          type="button"
                          disabled={busy === anchor.id}
                          onClick={() => onAcceptSuggestion(anchor)}
                        >
                          Use this
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={busy === anchor.id}
                        onClick={() => void onPickManually(anchor)}
                      >
                        Pick manually
                      </button>
                      <button
                        type="button"
                        disabled={busy === anchor.id}
                        onClick={() =>
                          void run(anchor.id, 'Could not remove that mark', () =>
                            removeAnchor(anchor.id),
                          )
                        }
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                )}

                {anchor.status === ANCHOR_STATUSES.orphaned && (
                  <div className="mark-repair">
                    <p className="mark-meaning">{STATUS_WORDS['orphaned']?.meaning}</p>
                    <div className="mark-actions">
                      <button
                        type="button"
                        disabled={busy === anchor.id}
                        onClick={() =>
                          void run(anchor.id, 'Could not restore that chapter', () =>
                            restoreChapter(anchor.document_id),
                          )
                        }
                      >
                        Restore the chapter
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}

      {projectState.anchors.length > 0 && (
        <p className="marks-total" data-testid="marks-total">
          {plural(projectState.anchors.length, 'mark')}
        </p>
      )}
    </div>
  );
}

/** Anchors by chapter, keeping the order the list already has (chapter, then position). */
function group(anchors: readonly Anchor[]): [string, Anchor[]][] {
  const groups = new Map<string, Anchor[]>();
  for (const anchor of anchors) {
    const existing = groups.get(anchor.document_id);
    if (existing) {
      existing.push(anchor);
    } else {
      groups.set(anchor.document_id, [anchor]);
    }
  }
  return [...groups.entries()];
}
