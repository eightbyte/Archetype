/**
 * One chapter's history (P2-12, D23).
 *
 * What was taken, why, and how many words; a preview of any of them; a restore; and *Mark this
 * version* with a label. It opens beside the chapter it belongs to rather than in the outline
 * panel, because a snapshot is of a chapter and the outline spans all of them.
 *
 * Everything here goes through `DocumentContext`, which owns the open chapter — including the
 * flush a mark and a preview both need. A component holding its own client would be a second
 * place that knows when a save has to happen first.
 *
 * ## Why the preview is a preview and not a diff
 *
 * P2-12 records a diff as **desirable, not required**, and this is the plain before-and-after it
 * asks for instead: the snapshot's text and the chapter's current text, both derived with the
 * client's projection mirror. D12's before/after requirement is about *proposed edits* and bites
 * in Phase 4, where the agent proposes and the writer accepts. Here the writer is choosing
 * between two versions they wrote themselves, and reading both is the honest way to choose.
 *
 * The "now" side is the chapter's text after a flush — what a restore from here would replace.
 * Showing the content the editor was *seeded* with would show what the chapter was when it was
 * opened, which is a different chapter by the time anyone reaches for the history.
 *
 * ## What restoring promises
 *
 * The current text is snapshotted first, in the same transaction as the write that replaces it,
 * so nothing is lost and nothing is left behind if it is refused (P2-3, deviation A2). The
 * restore then goes through the ordinary save path: the version moves, the projection is
 * re-derived, and the anchors are re-resolved. The confirmation says so, because a writer about
 * to replace a chapter is entitled to know what happens to what is there.
 */

import { useCallback, useEffect, useState } from 'react';
import type { ProseMirrorDocument, SnapshotMeta } from '../api';
import { useDocument } from '../state/DocumentContext';
import { useToasts } from '../state/ToastContext';
import { formatDateTime, plural } from '../format';
import { project } from '../editor/projection';

/** What a reason means to a person. The `pre-*` ones are the server's, and say what they saved. */
const REASON_WORDS: Record<string, string> = {
  handover: 'On leaving the chapter',
  manual: 'Marked by you',
  'pre-restore': 'Before a restore',
  'pre-delete': 'Before the chapter was deleted',
  'pre-import': 'Before an import',
};

interface Preview {
  snapshotId: string;
  then: string;
  now: string;
}

export interface SnapshotHistoryProps {
  documentId: string;
  onClose: () => void;
}

export function SnapshotHistory({ documentId, onClose }: SnapshotHistoryProps) {
  const { markVersion, listSnapshots, readSnapshot, savedContent, restoreSnapshot } = useDocument();
  const { push } = useToasts();

  const [snapshots, setSnapshots] = useState<SnapshotMeta[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      setSnapshots(await listSnapshots());
      setError(null);
    } catch (caught: unknown) {
      setError(message(caught));
    }
  }, [listSnapshots]);

  // `documentId` is in the dependency list on purpose: the panel stays open across a chapter
  // switch, and a history showing the previous chapter's versions is worse than none.
  useEffect(() => {
    setPreview(null);
    setConfirming(null);
    void reload();
  }, [documentId, reload]);

  const onMark = useCallback(async () => {
    setBusy(true);
    try {
      const captured = await markVersion(label.trim());
      setLabel('');
      await reload();
      // A manual mark is never deduplicated (deviation A3), so it is always there afterwards.
      push(captured ? 'Version marked.' : 'Nothing to mark yet.');
    } catch (caught: unknown) {
      push(`Could not mark this version — ${message(caught)}`, 'error');
    } finally {
      setBusy(false);
    }
  }, [label, markVersion, push, reload]);

  const onPreview = useCallback(
    async (snapshotId: string) => {
      if (preview?.snapshotId === snapshotId) {
        setPreview(null);
        return;
      }
      try {
        const [snapshot, current] = await Promise.all([
          readSnapshot(snapshotId),
          savedContent(),
        ]);
        setPreview({
          snapshotId,
          then: textOf(snapshot.content_json),
          now: current === null ? '' : textOf(current),
        });
      } catch (caught: unknown) {
        push(`Could not read that version — ${message(caught)}`, 'error');
      }
    },
    [preview, push, readSnapshot, savedContent],
  );

  const onRestore = useCallback(
    async (snapshotId: string) => {
      setBusy(true);
      try {
        await restoreSnapshot(snapshotId);
        setConfirming(null);
        setPreview(null);
        await reload();
        push('Restored. The version you replaced is in the history.');
      } catch (caught: unknown) {
        push(`Could not restore that version — ${message(caught)}`, 'error');
      } finally {
        setBusy(false);
      }
    },
    [push, reload, restoreSnapshot],
  );

  return (
    <section className="history" aria-label="Chapter history">
      <header className="history-header">
        <h3>History</h3>
        <button type="button" onClick={onClose}>
          Close history
        </button>
      </header>

      <div className="history-mark">
        <label htmlFor="history-label">Mark this version</label>
        <input
          id="history-label"
          value={label}
          placeholder="What is this version?"
          onChange={(event) => setLabel(event.target.value)}
        />
        <button type="button" disabled={busy} onClick={() => void onMark()}>
          Mark
        </button>
      </div>

      {error !== null && (
        <p role="alert" data-testid="history-error">
          Could not read the history — {error}
        </p>
      )}

      {snapshots === null && error === null && <p data-testid="history-status">Reading…</p>}

      {snapshots !== null && snapshots.length === 0 && (
        <p data-testid="history-status" className="panel-placeholder">
          No versions yet. One is kept whenever you leave the chapter, and whenever you mark it.
        </p>
      )}

      {snapshots !== null && snapshots.length > 0 && (
        <ol className="history-list">
          {snapshots.map((snapshot) => (
            <li key={snapshot.id} className="history-entry">
              <div className="history-entry-row">
                <span className="history-when">{formatDateTime(snapshot.taken_at)}</span>
                <span className="history-why">
                  {snapshot.label || REASON_WORDS[snapshot.reason] || snapshot.reason}
                </span>
                <span className="history-count">{plural(snapshot.word_count, 'word')}</span>
                <button
                  type="button"
                  aria-expanded={preview?.snapshotId === snapshot.id}
                  onClick={() => void onPreview(snapshot.id)}
                >
                  Preview
                </button>
                <button type="button" onClick={() => setConfirming(snapshot.id)}>
                  Restore
                </button>
              </div>

              {confirming === snapshot.id && (
                <div className="history-confirm" role="group" aria-label="Confirm restore">
                  <p>
                    The chapter as it is now will be kept in this history first, then replaced
                    with this version.
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void onRestore(snapshot.id)}
                  >
                    Restore this version
                  </button>
                  <button type="button" onClick={() => setConfirming(null)}>
                    Cancel
                  </button>
                </div>
              )}

              {preview?.snapshotId === snapshot.id && (
                <div className="history-preview">
                  <div>
                    <h4>This version</h4>
                    <pre data-testid="history-preview-then">{preview.then}</pre>
                  </div>
                  <div>
                    <h4>The chapter now</h4>
                    <pre data-testid="history-preview-now">{preview.now}</pre>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function textOf(content: ProseMirrorDocument): string {
  return project(content).text_plain;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
