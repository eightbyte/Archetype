/**
 * The passages an entry points at (P3-14, P3-7).
 *
 * Each citation carries the anchor **as it reads now** — `ok`, `stale`, or `orphaned` — derived
 * server-side in the one place D22 put it, so a citation can never disagree with the *Marks* tab
 * about the same anchor. This is where `stale` stops being an abstraction: the passage that
 * produced this entry has been rewritten, and the writer sees that before trusting the entry.
 *
 * ## Two things it deliberately does not do
 *
 * **It does not repair anything.** A `stale` citation sends the writer to *Marks*, which is where
 * a repair lives and where the suggestion protocol already is (ruling 5). Growing a second repair
 * flow here would mean two surfaces that both re-link an anchor, and the day they disagree about
 * what a suggestion is, one of them is wrong.
 *
 * **It does not delete an anchor.** Removing a citation removes the *join*: the entry keeps what
 * a person typed and loses one reason to believe it, and the anchor stays, because an anchor is a
 * fact about the manuscript and an entry is not. Deleting one is *Marks*' job too.
 */

import { useCallback, useState } from 'react';
import type { Citation } from '../api/types';
import { ANCHOR_STATUSES } from '../api/types';
import { previewQuote, STATUS_WORDS } from '../anchorText';
import { useBible } from '../state/BibleContext';
import { useDocument } from '../state/DocumentContext';
import { describeFailure } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';
import { useUi } from '../state/UiContext';

export interface EntryCitationsProps {
  entryId: string;
  citations: Citation[];
  /** A citation went — the detail view re-reads the entry. */
  onChanged: () => void;
}

export function EntryCitations({ entryId, citations, onChanged }: EntryCitationsProps) {
  const { uncite } = useBible();
  const { goToAnchor } = useDocument();
  const { dispatch: uiDispatch } = useUi();
  const { push } = useToasts();
  const [busy, setBusy] = useState<string | null>(null);

  const onGoTo = useCallback(
    async (citation: Citation) => {
      if (!(await goToAnchor(citation.document_id, citation.anchor.id))) {
        push(
          'Staying put — the open chapter has unsaved changes that have not been saved yet.',
          'error',
        );
      }
    },
    [goToAnchor, push],
  );

  const onRemove = useCallback(
    async (citation: Citation) => {
      setBusy(citation.anchor.id);
      try {
        await uncite(entryId, citation.anchor.id);
        onChanged();
      } catch (failure: unknown) {
        push(`Could not remove that citation — ${describeFailure(failure)}`, 'error');
      } finally {
        setBusy(null);
      }
    },
    [entryId, onChanged, push, uncite],
  );

  return (
    <section className="entry-citations" aria-label="Citations">
      <h4>From the manuscript</h4>

      {citations.length === 0 && (
        <p className="panel-placeholder">
          Nothing cites this yet. Select a passage in the manuscript and choose “Add to bible”, or
          mark it and cite the mark.
        </p>
      )}

      <ul className="entry-citation-list">
        {citations.map((citation) => (
          <li
            key={`${citation.anchor.id}:${citation.role}`}
            className={`entry-citation entry-citation-${citation.anchor.status}`}
          >
            <div className="entry-citation-row">
              <button
                type="button"
                className="entry-citation-quote"
                disabled={citation.anchor.status === ANCHOR_STATUSES.orphaned}
                onClick={() => void onGoTo(citation)}
              >
                {previewQuote(citation.anchor.quote) || <em>an empty passage</em>}
              </button>
              <span className="entry-citation-role">{citation.role}</span>
            </div>
            <p className="entry-citation-where">
              {citation.document_title} ·{' '}
              <span className="entry-citation-status">
                {STATUS_WORDS[citation.anchor.status]?.name ?? citation.anchor.status}
              </span>
            </p>

            {citation.anchor.status !== ANCHOR_STATUSES.ok && (
              <p className="entry-citation-meaning">
                {STATUS_WORDS[citation.anchor.status]?.meaning}
              </p>
            )}

            <div className="entry-citation-actions">
              {citation.anchor.status === ANCHOR_STATUSES.stale && (
                <button
                  type="button"
                  onClick={() => uiDispatch({ type: 'select-outline-tab', tab: 'marks' })}
                >
                  Repair in Marks
                </button>
              )}
              <button
                type="button"
                disabled={busy === citation.anchor.id}
                aria-label={`Remove the citation of “${previewQuote(citation.anchor.quote, 32)}”`}
                onClick={() => void onRemove(citation)}
              >
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
