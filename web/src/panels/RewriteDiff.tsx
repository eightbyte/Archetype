/**
 * The before and the after, and the decision the writer makes about it (P4-14, D5, D12, D33).
 *
 * **The writer owns the words.** A proposed replacement is never applied by the thing that
 * proposed it: it is shown as an explicit before/after, and accepting it is a gesture. That is
 * D12, and it is the standing invariant this whole phase is arranged around.
 *
 * ## Accepting
 *
 * One editor transaction, through `applyReplacement` — undoable with one press, autosaved by the
 * loop that already runs, and covered by the snapshot machinery that already exists. There is no
 * proposal row, no accept endpoint, and no second save path (D33). Phase 7 owns the durable
 * proposal, and building half of one here would leave it inheriting a shape nobody designed.
 *
 * ## And the refusal that matters
 *
 * Before anything is applied, the anchor is **re-read from the server**: the flush that goes with
 * it re-resolves every anchor of the document inside its own transaction (D21), so the status
 * that comes back is about the text as it now stands. An action **never applies to a `stale`
 * anchor** — it refuses and names the passage — because the positions of a stale anchor are true
 * at no version, and applying to them would drop a replacement onto whatever now occupies those
 * offsets (`specs/anchors.md` § 1, phase-3 deviation `E2`).
 *
 * Nothing here decides whether the passage moved. That is the resolver's, on the server, with a
 * specification and a corpus behind it.
 */

import { useCallback, useState } from 'react';
import { previewQuote } from '../anchorText';
import { rewriteActionDefinition } from '../rewriteActions';
import { isUnchanged, wordDiff } from '../wordDiff';
import { useChat } from '../state/ChatContext';
import type { RewriteRequest } from '../state/chatReducer';
import { useDocument } from '../state/DocumentContext';
import { useProject } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';

export interface RewriteDiffProps {
  request: RewriteRequest;
  /** What arrived. The replacement, and nothing else — the action's prompt asks for exactly that. */
  after: string;
}

export function RewriteDiff({ request, after }: RewriteDiffProps) {
  const { clearStream } = useChat();
  const { resolveAnchor, applyReplacement } = useDocument();
  const { removeAnchor } = useProject();
  const { push } = useToasts();
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const definition = rewriteActionDefinition(request.action);
  const replacement = after.trim();
  const parts = wordDiff(request.before, replacement);

  /**
   * Take the anchor away, whichever way the writer decided.
   *
   * Best-effort: it is machinery this action created, not something the writer marked, and
   * failing to remove it must not be the reason an accepted rewrite is not applied.
   */
  const forget = useCallback(async () => {
    try {
      await removeAnchor(request.anchorId);
    } catch {
      // Nothing to say. A stray mark is a tidiness problem; the manuscript is unaffected.
    }
    clearStream();
  }, [clearStream, removeAnchor, request.anchorId]);

  const accept = useCallback(() => {
    setBusy(true);
    setRefusal(null);
    void (async () => {
      try {
        const anchor = await resolveAnchor(request.documentId, request.anchorId);
        if (anchor === null) {
          setRefusal('That passage is no longer marked, so there is nothing to apply this to.');
          return;
        }
        if (anchor.status !== 'ok') {
          // The one refusal P4-14 names. The message says which passage, because a writer who
          // has been editing needs to know *what* moved, not only that something did.
          setRefusal(
            `“${previewQuote(anchor.quote)}” has been rewritten since this was suggested, so ` +
              'this no longer describes the passage it was about. Nothing has been changed. ' +
              'Select the passage again and run it once more.',
          );
          return;
        }
        applyReplacement(anchor.from_pos, anchor.to_pos, replacement);
        push('Applied. Undo takes it back.');
        await forget();
      } catch (error: unknown) {
        setRefusal(`This could not be applied — ${message(error)}. Nothing has been changed.`);
      } finally {
        setBusy(false);
      }
    })();
  }, [
    applyReplacement,
    forget,
    push,
    replacement,
    request.anchorId,
    request.documentId,
    resolveAnchor,
  ]);

  const unchanged = isUnchanged(parts) && request.before === replacement;

  return (
    <section className="rewrite-diff" aria-label={`${definition.label} suggestion`}>
      <h3 className="panel-heading">{definition.label}</h3>

      {unchanged ? (
        <p className="rewrite-diff-unchanged">
          Nothing was changed — the passage came back exactly as it went.
        </p>
      ) : (
        <p className="rewrite-diff-body">
          {parts.map((part, index) => (
            <span key={index} className={`diff-${part.type}`}>
              {part.text}
            </span>
          ))}
        </p>
      )}

      {refusal && (
        <p className="rewrite-diff-refusal" role="alert">
          {refusal}
        </p>
      )}

      <div className="rewrite-diff-controls">
        <button type="button" disabled={busy || unchanged} onClick={accept}>
          {busy ? 'Applying…' : 'Accept'}
        </button>
        <button type="button" disabled={busy} onClick={() => void forget()}>
          Discard
        </button>
      </div>
    </section>
  );
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
