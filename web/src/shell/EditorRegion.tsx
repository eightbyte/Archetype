/**
 * The middle region: the open chapter, its title, and its save status (P1-10).
 *
 * Everything about *when* a save happens lives in `DocumentContext`; this is what the writer
 * sees of it. The one rule worth stating here is that a failure never removes the writing from
 * the screen: a failed save, a conflict, and a load that did not work all leave the editor
 * exactly where it was, because the content in it may be the only copy.
 */

import { useCallback, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { ManuscriptEditor } from '../editor/ManuscriptEditor';
import { SaveIndicator } from '../editor/SaveIndicator';
import { plural } from '../format';
import { useDocument } from '../state/DocumentContext';
import { useToasts } from '../state/ToastContext';

export function EditorRegion() {
  const { state, edit, flush, retrySave, reloadFromServer, rename, headingReached } = useDocument();

  if (state.status === 'empty') {
    return (
      <div className="editor-region editor-region-empty">
        <p className="panel-placeholder">Choose a chapter from the contents to start writing.</p>
      </div>
    );
  }

  if (state.status === 'loading') {
    return (
      <div className="editor-region editor-region-empty">
        <p data-testid="editor-status">Opening the chapter…</p>
      </div>
    );
  }

  if (state.status === 'failed' || state.content === null) {
    return (
      <div className="editor-region editor-region-empty">
        <p data-testid="editor-status" role="alert">
          This chapter could not be opened — {state.loadError ?? 'no content came back'}.
        </p>
      </div>
    );
  }

  return (
    <div className="editor-region">
      <header className="chapter-header">
        <ChapterTitle title={state.title} onRename={rename} />
        <span className="chapter-count">{plural(state.wordCount, 'word')}</span>
        <SaveIndicator
          save={state.save}
          onRetry={() => void retrySave()}
          onReload={() => void reloadFromServer()}
        />
      </header>

      <ManuscriptEditor
        content={state.content}
        seedKey={`${state.documentId ?? 'none'}:${state.sequence}`}
        title={state.title}
        onChange={edit}
        onBlur={() => void flush()}
        pendingHeading={state.pendingHeading}
        onHeadingReached={headingReached}
      />
    </div>
  );
}

interface ChapterTitleProps {
  title: string;
  onRename: (title: string) => Promise<void>;
}

/**
 * The chapter title, renamed in place.
 *
 * A rename is not a text edit, so it does not move the content version and cannot invalidate an
 * autosave that is in flight (P1-6). Committing on Enter or blur and abandoning on Escape is the
 * behaviour a writer already expects from every other place they rename a thing.
 */
function ChapterTitle({ title, onRename }: ChapterTitleProps) {
  const { push } = useToasts();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);

  const start = useCallback(() => {
    setDraft(title);
    setEditing(true);
  }, [title]);

  const commit = useCallback(
    async (event?: FormEvent) => {
      event?.preventDefault();
      setEditing(false);
      const next = draft.trim();
      if (next.length === 0 || next === title) {
        return;
      }
      try {
        await onRename(next);
      } catch (error: unknown) {
        push(
          `Could not rename the chapter — ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    },
    [draft, onRename, push, title],
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setEditing(false);
        setDraft(title);
      }
    },
    [title],
  );

  if (!editing) {
    return (
      <h2 className="chapter-title">
        {/* The accessible name says what the button does and still contains the visible text,
            so a screen reader is told this is a rename rather than left to guess. */}
        <button type="button" aria-label={`Rename ${title}`} onClick={start}>
          {title}
        </button>
      </h2>
    );
  }

  return (
    <h2 className="chapter-title">
      <form onSubmit={(event) => void commit(event)}>
        {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the writer just asked to type here */}
        <input
          autoFocus
          aria-label="Chapter title"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => void commit()}
          onKeyDown={onKeyDown}
        />
      </form>
    </h2>
  );
}
