/**
 * The middle region: the open chapter, its title, its save status, its marks, and its history
 * (P1-10, P2-9, P2-12).
 *
 * Everything about *when* a save happens lives in `DocumentContext`; this is what the writer
 * sees of it. The one rule worth stating here is that a failure never removes the writing from
 * the screen: a failed save, a conflict, and a load that did not work all leave the editor
 * exactly where it was, because the content in it may be the only copy.
 *
 * Two Group C surfaces attach here rather than to a panel, because both are about the chapter
 * that is open rather than about the manuscript:
 *
 * * **Marking a passage.** The control lives over the selection (P2-9), and the range it sends
 *   is the writer's own — the server derives the quote.
 * * **The chapter's history.** Snapshots are per chapter (P2-12), so the history opens beside
 *   the chapter it belongs to rather than in the outline panel, which spans all of them.
 *
 * Group D's *Add to bible* attaches here for the first reason (P3-14). This is the one place the
 * three contexts meet: the document layer knows which chapter and which version, the project
 * layer takes the anchor, and the bible layer is told an entry now exists. Doing that join here
 * rather than inside `DocumentContext` keeps the document layer's single upward dependency
 * single — it tells the project a save landed, and nothing else.
 */

import { useCallback, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { toEditorAnchors } from '../editor/anchors';
import { ManuscriptEditor } from '../editor/ManuscriptEditor';
import type { BibleDraft, SelectionRange } from '../editor/SelectionActions';
import { SaveIndicator } from '../editor/SaveIndicator';
import { SnapshotHistory } from '../panels/SnapshotHistory';
import { plural } from '../format';
import { useBible } from '../state/BibleContext';
import { useDocument } from '../state/DocumentContext';
import { useProject } from '../state/ProjectContext';
import { anchorsOf } from '../state/projectReducer';
import { useToasts } from '../state/ToastContext';
import { describeAnchor } from '../anchorText';

export function EditorRegion() {
  const {
    state,
    edit,
    flush,
    retrySave,
    reloadFromServer,
    rename,
    headingReached,
    anchorReached,
    createAnchor,
    addToBible,
  } = useDocument();
  const { state: projectState, relinkAnchor, cancelRelink } = useProject();
  const { state: bibleState, entryCreated } = useBible();
  const { push } = useToasts();
  const [anchorBusy, setAnchorBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const documentId = state.documentId;
  const anchors = toEditorAnchors(anchorsOf(projectState, documentId));
  const relinkingAnchor =
    projectState.anchors.find((anchor) => anchor.id === projectState.relinking) ?? null;

  const onMark = useCallback(
    (range: SelectionRange) => {
      setAnchorBusy(true);
      void (async () => {
        try {
          await createAnchor(range.from, range.to);
        } catch (error: unknown) {
          push(`Could not mark that passage — ${message(error)}`, 'error');
        } finally {
          setAnchorBusy(false);
        }
      })();
    },
    [createAnchor, push],
  );

  const onAddToBible = useCallback(
    (range: SelectionRange, draft: BibleDraft) => {
      setAnchorBusy(true);
      void (async () => {
        try {
          const created = await addToBible(range.from, range.to, draft);
          // One transaction on the server made all three; the client tells the two panels that
          // hold the halves. The anchor reached the project through `addToBible` itself.
          entryCreated(created.entry);
          push(`Added ${created.entry.name} to the bible, citing this passage.`);
        } catch (error: unknown) {
          push(`Could not add that to the bible — ${message(error)}`, 'error');
        } finally {
          setAnchorBusy(false);
        }
      })();
    },
    [addToBible, entryCreated, push],
  );

  const onRelink = useCallback(
    (range: SelectionRange) => {
      if (!relinkingAnchor) {
        return;
      }
      setAnchorBusy(true);
      void (async () => {
        try {
          await relinkAnchor(relinkingAnchor.id, {
            from_pos: range.from,
            to_pos: range.to,
            version: state.version,
          });
          push('Re-linked.');
        } catch (error: unknown) {
          push(`Could not re-link that mark — ${message(error)}`, 'error');
        } finally {
          setAnchorBusy(false);
        }
      })();
    },
    [push, relinkAnchor, relinkingAnchor, state.version],
  );

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
        <button
          type="button"
          className="chapter-history-toggle"
          aria-expanded={historyOpen}
          onClick={() => setHistoryOpen((open) => !open)}
        >
          History
        </button>
        <SaveIndicator
          save={state.save}
          onRetry={() => void retrySave()}
          onReload={() => void reloadFromServer()}
        />
      </header>

      {historyOpen && documentId !== null && (
        <SnapshotHistory documentId={documentId} onClose={() => setHistoryOpen(false)} />
      )}

      <ManuscriptEditor
        content={state.content}
        seedKey={`${documentId ?? 'none'}:${state.sequence}`}
        title={state.title}
        onChange={edit}
        onBlur={() => void flush()}
        pendingHeading={state.pendingHeading}
        onHeadingReached={headingReached}
        anchors={anchors}
        pendingAnchor={state.pendingAnchor}
        onAnchorReached={anchorReached}
        onMark={onMark}
        relinking={
          relinkingAnchor
            ? { anchorId: relinkingAnchor.id, description: describeAnchor(relinkingAnchor) }
            : null
        }
        onRelink={onRelink}
        onCancelRelink={cancelRelink}
        anchorBusy={anchorBusy}
        bibleKinds={bibleState.schema?.kinds ?? []}
        onAddToBible={onAddToBible}
      />
    </div>
  );
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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
