/**
 * Proofread, tone, and rewrite — the three single-pass actions (P4-14, D12, D33).
 *
 * They sit in the panel rather than over the selection, because the selection already carries
 * three controls and *Ask agent* is the fourth (P4-13). What they act on is the passage the panel
 * is pointing at, which is what *Ask agent* put there.
 *
 * ## The anchor is the point
 *
 * Each action **mints an anchor for its range through `AnchorStore` and by no other means**
 * (phase-3 § 2, ruling 8), before it asks. That is not bookkeeping: a suggestion is read, thought
 * about, and accepted some seconds or minutes later, and in between the writer may have rewritten
 * the very passage it is about. An anchor is the one thing in this application that can say so —
 * and an action **never applies to a `stale` one**, which is the whole reason Phase 2 was built
 * before this.
 *
 * The anchor is machinery rather than a mark the writer asked for, so it is removed when the
 * suggestion is dealt with, either way. Leaving one behind per rewrite would fill the *Marks* tab
 * with passages nobody marked.
 *
 * ## Why they are offered only sometimes
 *
 * A passage has to be selected, and it has to be in **the chapter that is open**. `createAnchor`
 * anchors a range of the open document at its current version; a range pointed at in one chapter
 * and anchored in another would be a suggestion about text nobody looked at.
 */

import { useCallback, useState } from 'react';
import { REWRITE_ACTION_DEFINITIONS } from '../rewriteActions';
import { useChat } from '../state/ChatContext';
import type { RewriteAction } from '../state/chatReducer';
import { hasSelection, isStreaming } from '../state/chatReducer';
import { useDocument } from '../state/DocumentContext';
import { useToasts } from '../state/ToastContext';

export function RewriteActions() {
  const { state, runRewrite } = useChat();
  const { state: documentState, createAnchor } = useDocument();
  const { push } = useToasts();
  const [busy, setBusy] = useState(false);

  const selection = state.selection;
  const documentId = documentState.documentId;
  const usable =
    hasSelection(selection) &&
    documentId !== null &&
    selection.document_id === documentId &&
    documentState.status === 'ready';

  const run = useCallback(
    (action: RewriteAction) => {
      if (selection.from_pos === null || selection.to_pos === null) {
        return;
      }
      const from = selection.from_pos;
      const to = selection.to_pos;
      setBusy(true);
      void (async () => {
        try {
          // The anchor first, and the ask second. If the anchor cannot be minted — a stale
          // version, a range with no honest place in the text — nothing has been spent.
          const anchor = await createAnchor(from, to, `${action} suggestion`);
          await runRewrite({
            action,
            anchorId: anchor.id,
            documentId: anchor.document_id,
            before: anchor.quote,
            from_pos: anchor.from_pos,
            to_pos: anchor.to_pos,
          });
        } catch (error: unknown) {
          push(`Could not start that — ${message(error)}`, 'error');
        } finally {
          setBusy(false);
        }
      })();
    },
    [createAnchor, push, runRewrite, selection.from_pos, selection.to_pos],
  );

  if (!usable) {
    return null;
  }

  return (
    <div className="rewrite-actions">
      <span className="rewrite-actions-label">On the selected passage:</span>
      {REWRITE_ACTION_DEFINITIONS.map((definition) => (
        <button
          key={definition.action}
          type="button"
          disabled={busy || isStreaming(state)}
          onClick={() => run(definition.action)}
        >
          {definition.label}
        </button>
      ))}
    </div>
  );
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
