/**
 * The conversations in this project, and the tray of deleted ones (P4-12, D30).
 *
 * A conversation is stored in the project file, so this is what makes the assistant something a
 * writer comes *back* to rather than something that resets when the page does. The list is the
 * server's answer in the server's order — most recently used first — and it is re-read after
 * every write rather than patched here.
 *
 * The deleted tray is loaded on demand and is the whole of the restore path, for the reason
 * chapters and entries each have one: a soft delete whose only recovery is a toast the writer has
 * to catch before it fades is a delete with a grace period, not a recoverable one.
 */

import { useCallback, useState } from 'react';
import type { Conversation } from '../api';
import { formatRelativeTime, plural } from '../format';
import { useChat } from '../state/ChatContext';
import { useToasts } from '../state/ToastContext';

export function ConversationList() {
  const {
    state,
    openConversation,
    startConversation,
    deleteConversation,
    restoreConversation,
    loadDeleted,
    reload,
  } = useChat();
  const { push } = useToasts();
  const [trayOpen, setTrayOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const openTray = useCallback(async () => {
    const next = !trayOpen;
    setTrayOpen(next);
    if (next) {
      try {
        await loadDeleted();
      } catch (error: unknown) {
        push(`Could not read the deleted conversations — ${message(error)}`, 'error');
      }
    }
  }, [loadDeleted, push, trayOpen]);

  const start = useCallback(async () => {
    setBusy(true);
    try {
      await startConversation();
    } catch (error: unknown) {
      push(`Could not start a conversation — ${message(error)}`, 'error');
    } finally {
      setBusy(false);
    }
  }, [push, startConversation]);

  if (state.status === 'loading') {
    return <p className="panel-placeholder">Reading your conversations…</p>;
  }

  if (state.status === 'failed') {
    return (
      <div className="chat-failed">
        <p role="alert">The conversations could not be read — {state.error}.</p>
        <button type="button" onClick={reload}>
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="chat-list">
      <button type="button" className="chat-new" disabled={busy} onClick={() => void start()}>
        New conversation
      </button>

      {state.conversations.length === 0 ? (
        <p className="panel-placeholder">
          Nothing yet. Select a passage in the manuscript and choose <em>Ask agent</em>, or start a
          conversation here and type a question.
        </p>
      ) : (
        <ul className="chat-rows">
          {state.conversations.map((row) => (
            <li key={row.id} className="chat-row">
              {/* Named for a screen reader, because the visible text is a title *and* a count
                  of turns *and* a date, and "The harbour 4 turns 2 hours ago" is not what the
                  control does. */}
              <button
                type="button"
                aria-label={`Open ${titleOf(row)}`}
                onClick={() => void openConversation(row.id)}
              >
                <span className="chat-row-title">{titleOf(row)}</span>
                <span className="chat-row-meta">
                  {plural(row.message_count, 'turn')} · {formatRelativeTime(row.updated_at)}
                </span>
              </button>
              <button
                type="button"
                className="chat-row-delete"
                aria-label={`Delete ${titleOf(row)}`}
                onClick={() => {
                  void (async () => {
                    try {
                      await deleteConversation(row.id);
                      push('Conversation deleted. It is in the deleted tray.');
                    } catch (error: unknown) {
                      push(`Could not delete that conversation — ${message(error)}`, 'error');
                    }
                  })();
                }}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        className="chat-tray-toggle"
        aria-expanded={trayOpen}
        onClick={() => void openTray()}
      >
        Deleted conversations
      </button>

      {trayOpen && (
        <ul className="chat-rows chat-rows-deleted">
          {state.deleted.length === 0 ? (
            <li className="panel-placeholder">Nothing has been deleted.</li>
          ) : (
            state.deleted.map((row) => (
              <li key={row.id} className="chat-row">
                <span className="chat-row-title">{titleOf(row)}</span>
                <button
                  type="button"
                  aria-label={`Restore ${titleOf(row)}`}
                  onClick={() => {
                    void (async () => {
                      try {
                        await restoreConversation(row.id);
                        push('Conversation restored.');
                      } catch (error: unknown) {
                        push(`Could not restore that conversation — ${message(error)}`, 'error');
                      }
                    })();
                  }}
                >
                  Restore
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

/**
 * What to call a conversation with no name.
 *
 * A conversation is named from its first question, so an unnamed one is one nothing has been
 * asked in yet. Saying that is more use than an empty row.
 */
export function titleOf(conversation: Conversation): string {
  return conversation.title || 'Untitled conversation';
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
