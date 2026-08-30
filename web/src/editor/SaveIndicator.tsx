/**
 * What the save loop is doing, said out loud (P1-10, D19).
 *
 * A writer either trusts autosave or does not, and the difference is whether the app is willing
 * to say when it has failed. So the four ordinary states — saved, unsaved, saving, failed — are
 * always on screen, and the two that need a decision come with the control that makes it:
 *
 * * **Failed** keeps the content, says what went wrong, and offers *Retry now* beside the
 *   backoff that is already running. It is `role="alert"`, because a writer who does not notice
 *   this is a writer who is about to lose work.
 * * **Conflict** (`409`) says the chapter moved and offers exactly one answer: take the server's
 *   copy. There is no merge, and no "save anyway" — the whole point of the version guard is that
 *   this client does not get to overwrite what it has not seen.
 */

import type { SaveState } from '../state/documentReducer';
import { formatDateTime, formatRelativeTime } from '../format';

export interface SaveIndicatorProps {
  save: SaveState;
  onRetry: () => void;
  onReload: () => void;
}

export function SaveIndicator({ save, onRetry, onReload }: SaveIndicatorProps) {
  if (save.kind === 'conflict') {
    return (
      <div className="save-status save-status-conflict" role="alert" data-testid="save-status">
        <span>
          This chapter was changed somewhere else — it is now at version{' '}
          {save.detail.current_version}, and you are editing version{' '}
          {save.detail.presented_version}. Nothing here has been saved over it.
        </span>
        <button type="button" onClick={onReload}>
          Reload the saved version
        </button>
      </div>
    );
  }

  if (save.kind === 'failed') {
    return (
      <div className="save-status save-status-failed" role="alert" data-testid="save-status">
        <span>
          Save failed — {save.message}. Your writing is still here, and this keeps trying
          {save.attempt > 1 ? ` (${save.attempt} attempts)` : ''}.
        </span>
        <button type="button" onClick={onRetry}>
          Retry now
        </button>
      </div>
    );
  }

  return (
    <div className="save-status" role="status" aria-live="polite" data-testid="save-status">
      <span title={savedAtTitle(save)}>{describe(save)}</span>
    </div>
  );
}

function describe(save: SaveState): string {
  switch (save.kind) {
    case 'idle':
      return 'Saved';
    case 'unsaved':
      return 'Unsaved changes';
    case 'saving':
      return 'Saving…';
    case 'saved':
      return `Saved ${formatRelativeTime(save.at)}`;
    default:
      return '';
  }
}

/** The `title` for a saved timestamp — the exact moment, for anyone who wants it. */
export function savedAtTitle(save: SaveState): string | undefined {
  return save.kind === 'saved' ? formatDateTime(save.at) : undefined;
}
