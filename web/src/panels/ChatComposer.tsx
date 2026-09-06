/**
 * The question, and what will go with it (P4-12, P4-13, plan § 2 ruling 5).
 *
 * > What is being sent is shown before it is sent.
 *
 * That is the ruling this component exists for, and it is the reason the preview is a **server**
 * answer rather than something assembled here. `POST /api/conversations/{cid}/context` runs the
 * same `compose()` the socket runs and spends nothing, so the passage, the chapter, the entries,
 * the earlier turns, and the token estimate on screen are the ones the ask will actually carry —
 * and the estimate is the one the budget refusal will use. A composer in the browser that agreed
 * with the server's until it did not is exactly what deviation `C2` added that route to prevent.
 *
 * Every part except the instructions and the question itself can be **dropped**, and dropping one
 * changes what is sent rather than only what is drawn: each control edits the selector, and the
 * preview is re-read from it.
 *
 * The preview is debounced for the reason the bible's search box is — a request per keystroke for
 * a number that changes by three — and the debounce is the *only* thing that waits. Pointing at a
 * passage, dropping a part, or naming an entry are single deliberate acts and go out at once.
 */

import { useCallback, useEffect, useState } from 'react';
import type { ComposedContext, Entry } from '../api';
import { useBible } from '../state/BibleContext';
import { useChat } from '../state/ChatContext';
import type { ContextSelection } from '../state/chatReducer';
import { hasSelection, isStreaming } from '../state/chatReducer';
import { describeFailure } from '../state/ProjectContext';

export interface ChatComposerProps {
  /** Focus the box on mount — what *Ask agent* asks for when it opens the panel (P4-13). */
  autoFocus?: boolean;
}

export function ChatComposer({ autoFocus = false }: ChatComposerProps) {
  const { state, ask, cancel, previewContext, changeContext, previewDebounceMs } = useChat();
  const [prompt, setPrompt] = useState('');
  const [preview, setPreview] = useState<ComposedContext | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const selection = state.selection;
  const conversationId = state.openId;
  const streaming = isStreaming(state);

  // The preview. Keyed on what would actually be sent — the question and the selector — so a
  // dropped part re-reads immediately and a keystroke waits.
  const selectionKey = JSON.stringify(selection);
  useEffect(() => {
    if (conversationId === null) {
      setPreview(null);
      return;
    }
    let abandoned = false;
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const composed = await previewContext(prompt);
          if (abandoned) return;
          setPreview(composed);
          setPreviewError(null);
        } catch (error: unknown) {
          if (abandoned) return;
          // The last answer stays on screen. A preview that did not land is not a reason to take
          // away the writer's only view of what they are about to spend.
          setPreviewError(describeFailure(error));
        }
      })();
    }, previewDebounceMs);
    return () => {
      abandoned = true;
      clearTimeout(timer);
    };
  }, [conversationId, prompt, selectionKey, previewContext, previewDebounceMs]);

  const submit = useCallback(() => {
    const question = prompt.trim();
    if (question === '' || streaming) {
      return;
    }
    setPrompt('');
    void ask(question);
  }, [ask, prompt, streaming]);

  return (
    <div className="chat-composer">
      <ContextPreview
        preview={preview}
        error={previewError}
        selection={selection}
        onChange={changeContext}
      />

      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label className="chat-composer-label" htmlFor="chat-prompt">
          Your question
        </label>
        <textarea
          id="chat-prompt"
          rows={3}
          value={prompt}
          autoFocus={autoFocus}
          disabled={streaming}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends; Shift+Enter is a new line. A question is usually one line, and a box
            // whose only way out is the mouse is a box a writer types into and then hunts for.
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="chat-composer-controls">
          <button type="submit" disabled={streaming || prompt.trim() === ''}>
            Ask
          </button>
          {streaming && (
            <button
              type="button"
              className="chat-cancel"
              disabled={state.stream.cancelling}
              onClick={cancel}
            >
              {state.stream.cancelling ? 'Stopping…' : 'Stop'}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

interface ContextPreviewProps {
  preview: ComposedContext | null;
  error: string | null;
  selection: ContextSelection;
  onChange: (changes: Partial<ContextSelection>) => void;
}

/**
 * What would be sent, with a control on every part that can be left out.
 *
 * The parts come from the server and are rendered by one loop: their shape has the same key set
 * whatever the kind (the P3-11 rule), so there is no branch per kind here — only a lookup for
 * *what dropping this one means*, which is a change to the selector and nothing else.
 */
function ContextPreview({ preview, error, selection, onChange }: ContextPreviewProps) {
  const { state: bibleState, listCandidates } = useBible();
  const [candidates, setCandidates] = useState<Entry[] | null>(null);

  const openPicker = useCallback(async () => {
    // Read when the picker opens rather than held: the entry you want to name may be the one you
    // made a moment ago, and a cached directory is a picker that cannot see it (P3-12).
    setCandidates(await listCandidates());
  }, [listCandidates]);

  if (preview === null) {
    return (
      <div className="chat-context">
        {error ? (
          <p className="chat-context-error" role="alert">
            What would be sent could not be worked out — {error}.
          </p>
        ) : (
          <p className="panel-placeholder">Working out what would be sent…</p>
        )}
      </div>
    );
  }

  const overBudget = !preview.fits;

  return (
    <div className="chat-context">
      <div className="chat-context-head">
        <h3 className="panel-heading">What will be sent</h3>
        <span className={overBudget ? 'chat-context-total chat-over' : 'chat-context-total'}>
          ≈{preview.estimated_tokens.toLocaleString()} tokens
          {preview.budget > 0 && ` of ${preview.budget.toLocaleString()}`}
        </span>
      </div>

      {overBudget && (
        <p className="chat-context-error" role="alert">
          This is over the budget once room for the answer is left. Asking now is refused before
          anything is sent and costs nothing — drop a part below, or narrow the selection.
        </p>
      )}

      <ul className="chat-context-parts">
        {preview.parts.map((part, index) => {
          const drop = dropFor(part.kind, part.ref_id, selection);
          return (
            <li key={`${part.kind}-${part.ref_id}-${index}`} className="chat-context-part">
              <span className="chat-context-kind">{part.kind}</span>
              <span className="chat-context-label">{part.label}</span>
              <span className="chat-context-tokens">≈{part.estimated_tokens.toLocaleString()}</span>
              {drop && (
                <button
                  type="button"
                  aria-label={`Leave out ${part.label}`}
                  onClick={() => onChange(drop)}
                >
                  Drop
                </button>
              )}
            </li>
          );
        })}
      </ul>

      <div className="chat-context-add">
        {hasSelection(selection) && !selection.include_chapter && (
          <button type="button" onClick={() => onChange({ include_chapter: true })}>
            Add the chapter
          </button>
        )}
        {!selection.include_history && (
          <button type="button" onClick={() => onChange({ include_history: true })}>
            Add the earlier turns
          </button>
        )}
        {bibleState.schema !== null && candidates === null && (
          <button type="button" onClick={() => void openPicker()}>
            Add a bible entry
          </button>
        )}
        {candidates !== null && (
          <label className="chat-context-picker">
            <span>Bible entry</span>
            <select
              value=""
              onChange={(event) => {
                const entryId = event.target.value;
                if (entryId !== '' && !selection.entry_ids.includes(entryId)) {
                  onChange({ entry_ids: [...selection.entry_ids, entryId] });
                }
                setCandidates(null);
              }}
            >
              <option value="">Choose…</option>
              {candidates
                .filter((entry) => !selection.entry_ids.includes(entry.id))
                .map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name} ({entry.kind})
                  </option>
                ))}
            </select>
          </label>
        )}
      </div>
    </div>
  );
}

/**
 * What dropping one part means, as a change to the selector.
 *
 * `null` for the two that cannot be dropped: the instructions are what makes the answer an answer
 * about a manuscript, and the question is the ask itself.
 */
function dropFor(
  kind: string,
  refId: string,
  selection: ContextSelection,
): Partial<ContextSelection> | null {
  switch (kind) {
    case 'selection':
      return { from_pos: null, to_pos: null };
    case 'chapter':
      return { include_chapter: false };
    case 'entry':
      return { entry_ids: selection.entry_ids.filter((id) => id !== refId) };
    case 'history':
      return { include_history: false };
    default:
      return null;
  }
}
