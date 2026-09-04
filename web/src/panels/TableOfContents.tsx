/**
 * The Contents tab (P1-11, P2-11).
 *
 * Chapters in order, each opening into its heading tree, with word counts. It comes from
 * `GET /api/projects/{pid}/outline`, which reads only derived columns — so the table of contents
 * spans the whole manuscript while exactly one chapter is loaded in the editor (D2, D18).
 *
 * The open chapter is the exception, and deliberately so: its headings and word count come from
 * the client mirror of the projection, so they move as the writer types rather than lurching at
 * every save. When a save returns, the server's answer replaces the mirror's (D18). Which of the
 * two is showing is never in doubt — the mirror is only ever consulted for the one document
 * whose id matches the open one.
 *
 * Jump targets are heading **ordinals**: the index of a heading among all headings in its
 * document. This is not a seam anchors replace and never was (phase-2-plan § 2, ruling 1) — a
 * heading is a structural position the projection already numbers and re-derives on every save,
 * and an ordinal survives editing above it in a way a character offset would not. Anchors are
 * for cited passages that no derived structure names, and they live in the *Marks* tab.
 *
 * ## Chapter management (P2-11, D22)
 *
 * Reorder by drag **and** by keyboard, rename in place, delete with a confirmation that says
 * what becomes of the chapter's marks, and a list of deleted chapters to restore from.
 *
 * The keyboard path is not an afterthought bolted onto the drag: each chapter carries a *Move
 * up* / *Move down* pair that does exactly what a drag does, because a hand-rolled drag with no
 * keyboard equivalent is a feature only some people have (P1-9). Both send the **complete**
 * order, which is the server's concurrency guard (P2-2).
 *
 * Deleting is recoverable, so the confirmation is brief — the undo path carries the safety, not
 * the dialogue. What it does say is the one thing a writer cannot see for themselves: how many
 * marks point into the chapter and what happens to them.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent, FormEvent, KeyboardEvent } from 'react';
import type { OutlineChapter } from '../api';
import { ApiError } from '../api';
import type { Heading } from '../editor/projection';
import { formatDateTime, plural } from '../format';
import { useDocument } from '../state/DocumentContext';
import { useProject } from '../state/ProjectContext';
import { anchorCountOf } from '../state/projectReducer';
import { MarkdownTransfer } from './MarkdownTransfer';
import { useToasts } from '../state/ToastContext';

export function TableOfContents() {
  const {
    state: projectState,
    createChapter,
    renameChapter,
    reorderChapters,
    deleteChapter,
    restoreChapter,
    loadDeleted,
    chapterMarkdownUrl,
    reload,
  } = useProject();
  const { state: documentState, openDocument, rename: renameOpen } = useDocument();
  const { push } = useToasts();
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [showDeleted, setShowDeleted] = useState(false);
  const list = useRef<HTMLOListElement>(null);
  /** The chapter whose reorder control should hold focus after the list re-renders. */
  const refocus = useRef<string | null>(null);

  const openDocumentId = documentState.documentId;

  /** The outline as it should be shown: the server's, with the open chapter's kept live. */
  const chapters = useMemo<OutlineChapter[]>(
    () =>
      projectState.chapters.map((chapter) =>
        chapter.document_id === openDocumentId && documentState.status === 'ready'
          ? {
              ...chapter,
              title: documentState.title,
              headings: documentState.headings,
              word_count: documentState.wordCount,
            }
          : chapter,
      ),
    [
      projectState.chapters,
      openDocumentId,
      documentState.status,
      documentState.title,
      documentState.headings,
      documentState.wordCount,
    ],
  );

  // A reorder redraws the list, and a button that has moved has lost focus. Keyboard reordering
  // is unusable without this: the second press would go nowhere.
  useEffect(() => {
    const target = refocus.current;
    if (target === null) {
      return;
    }
    refocus.current = null;
    list.current?.querySelector<HTMLButtonElement>(`[data-move-down="${target}"]`)?.focus();
  }, [chapters]);

  const goTo = useCallback(
    async (documentId: string, ordinal?: number) => {
      const switched = await openDocument(documentId, ordinal);
      if (!switched) {
        push(
          'Staying put — this chapter has unsaved changes that have not been saved yet.',
          'error',
        );
      }
    },
    [openDocument, push],
  );

  const addChapter = useCallback(async () => {
    setCreating(true);
    try {
      const created = await createChapter();
      await openDocument(created.id);
    } catch (error: unknown) {
      push(`Could not add a chapter — ${message(error)}`);
    } finally {
      setCreating(false);
    }
  }, [createChapter, openDocument, push]);

  /** Move a chapter to a new index and send the whole order. */
  const move = useCallback(
    async (documentId: string, to: number) => {
      const order = chapters.map((chapter) => chapter.document_id);
      const from = order.indexOf(documentId);
      if (from < 0 || to < 0 || to >= order.length || to === from) {
        return;
      }
      order.splice(to, 0, ...order.splice(from, 1));
      try {
        await reorderChapters(order);
      } catch (error: unknown) {
        if (error instanceof ApiError && error.isReorderMismatch) {
          // The list this client is holding is not the project as it is now. Re-reading is the
          // only correct answer — there is nothing here to correct field by field (P2-2).
          push('The chapter list had moved on — reloading it.', 'error');
          reload();
          return;
        }
        push(`Could not reorder the chapters — ${message(error)}`, 'error');
      }
    },
    [chapters, push, reload, reorderChapters],
  );

  const onMoveKey = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>, documentId: string, index: number) => {
      // The arrows are on the control that already moves the chapter, so the same gesture works
      // whether the writer clicks it or reaches it by tab.
      const delta = event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0;
      if (delta === 0) {
        return;
      }
      event.preventDefault();
      refocus.current = documentId;
      void move(documentId, index + delta);
    },
    [move],
  );

  const onDrop = useCallback(
    (event: DragEvent<HTMLLIElement>, index: number) => {
      event.preventDefault();
      const documentId = dragging ?? event.dataTransfer.getData('text/plain');
      setDragging(null);
      if (documentId) {
        void move(documentId, index);
      }
    },
    [dragging, move],
  );

  const onRename = useCallback(
    async (documentId: string, title: string) => {
      setRenaming(null);
      try {
        // The open chapter is renamed through the document layer, which also holds the title
        // the editor header is showing. Two writers of one title is one too many.
        if (documentId === openDocumentId) {
          await renameOpen(title);
        } else {
          await renameChapter(documentId, title);
        }
      } catch (error: unknown) {
        push(`Could not rename the chapter — ${message(error)}`, 'error');
      }
    },
    [openDocumentId, push, renameChapter, renameOpen],
  );

  const onDelete = useCallback(
    async (documentId: string) => {
      setConfirming(null);
      // Where the editor goes if it is holding the chapter about to disappear: the next one, or
      // the one before it. Leaving it holding a ghost is the failure this prevents.
      const order = chapters.map((chapter) => chapter.document_id);
      const index = order.indexOf(documentId);
      const successor = order[index + 1] ?? order[index - 1] ?? null;
      try {
        await deleteChapter(documentId);
        if (documentId === openDocumentId && successor !== null) {
          await openDocument(successor);
        }
        push('Chapter deleted. It can be restored from Deleted chapters.');
      } catch (error: unknown) {
        push(`Could not delete the chapter — ${message(error)}`, 'error');
      }
    },
    [chapters, deleteChapter, openDocument, openDocumentId, push],
  );

  const onShowDeleted = useCallback(async () => {
    const next = !showDeleted;
    setShowDeleted(next);
    if (next) {
      try {
        await loadDeleted();
      } catch (error: unknown) {
        push(`Could not read the deleted chapters — ${message(error)}`, 'error');
      }
    }
  }, [loadDeleted, push, showDeleted]);

  const onRestore = useCallback(
    async (documentId: string) => {
      try {
        const meta = await restoreChapter(documentId);
        await openDocument(meta.id);
      } catch (error: unknown) {
        push(`Could not restore the chapter — ${message(error)}`, 'error');
      }
    },
    [openDocument, push, restoreChapter],
  );

  const toggle = useCallback((documentId: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(documentId)) {
        next.add(documentId);
      }
      return next;
    });
  }, []);

  if (projectState.status === 'loading') {
    return <p data-testid="toc-status">Reading the manuscript…</p>;
  }
  if (projectState.status === 'failed') {
    return (
      <p data-testid="toc-status" role="alert">
        Could not read the outline — {projectState.error}
      </p>
    );
  }
  if (chapters.length === 0) {
    return <p data-testid="toc-status">No chapters yet.</p>;
  }

  const total = chapters.reduce((sum, chapter) => sum + chapter.word_count, 0);

  return (
    <div className="toc">
      <ol className="toc-chapters" ref={list}>
        {chapters.map((chapter, index) => {
          const isOpen = chapter.document_id === openDocumentId;
          const isCollapsed = collapsed.has(chapter.document_id);
          const marks = anchorCountOf(projectState, chapter.document_id);
          return (
            <li
              key={chapter.document_id}
              className={[
                'toc-chapter',
                isOpen ? 'is-open' : '',
                dragging === chapter.document_id ? 'is-dragging' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => onDrop(event, index)}
            >
              <div
                className="toc-chapter-row"
                draggable
                onDragStart={(event) => {
                  setDragging(chapter.document_id);
                  event.dataTransfer.setData('text/plain', chapter.document_id);
                  event.dataTransfer.effectAllowed = 'move';
                }}
                onDragEnd={() => setDragging(null)}
              >
                <button
                  type="button"
                  className="toc-twisty"
                  aria-expanded={!isCollapsed}
                  aria-label={`${isCollapsed ? 'Show' : 'Hide'} the headings in ${chapter.title}`}
                  onClick={() => toggle(chapter.document_id)}
                >
                  {isCollapsed ? '▸' : '▾'}
                </button>

                {renaming === chapter.document_id ? (
                  <ChapterName
                    title={chapter.title}
                    onCommit={(title) => void onRename(chapter.document_id, title)}
                    onAbandon={() => setRenaming(null)}
                  />
                ) : (
                  <button
                    type="button"
                    className="toc-chapter-title"
                    aria-current={isOpen ? 'true' : undefined}
                    onClick={() => void goTo(chapter.document_id)}
                  >
                    {chapter.title}
                  </button>
                )}

                <span className="toc-count">{plural(chapter.word_count, 'word')}</span>

                <span className="toc-chapter-actions">
                  <button
                    type="button"
                    data-move-up={chapter.document_id}
                    aria-label={`${chapter.title}: move up`}
                    disabled={index === 0}
                    onClick={() => void move(chapter.document_id, index - 1)}
                    onKeyDown={(event) => onMoveKey(event, chapter.document_id, index)}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    data-move-down={chapter.document_id}
                    aria-label={`${chapter.title}: move down`}
                    disabled={index === chapters.length - 1}
                    onClick={() => void move(chapter.document_id, index + 1)}
                    onKeyDown={(event) => onMoveKey(event, chapter.document_id, index)}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    aria-label={`${chapter.title}: rename`}
                    onClick={() => setRenaming(chapter.document_id)}
                  >
                    Rename
                  </button>
                  <a
                    className="toc-export"
                    href={chapterMarkdownUrl(chapter.document_id)}
                    download
                    aria-label={`${chapter.title}: export as Markdown`}
                  >
                    Export
                  </a>
                  <button
                    type="button"
                    aria-label={`${chapter.title}: delete`}
                    disabled={chapters.length === 1}
                    onClick={() => setConfirming(chapter.document_id)}
                  >
                    Delete
                  </button>
                </span>
              </div>

              {confirming === chapter.document_id && (
                <div
                  className="toc-confirm"
                  role="group"
                  aria-label={`Confirm deleting ${chapter.title}`}
                >
                  <p>
                    Delete {chapter.title}? It can be restored, and its text is kept.
                    {marks > 0 &&
                      ` Its ${plural(marks, 'mark')} will show as belonging to a deleted ` +
                        'chapter until you restore it.'}
                  </p>
                  <button type="button" onClick={() => void onDelete(chapter.document_id)}>
                    Delete chapter
                  </button>
                  <button type="button" onClick={() => setConfirming(null)}>
                    Cancel
                  </button>
                </div>
              )}

              {!isCollapsed && chapter.headings.length > 0 && (
                <ul className="toc-headings">
                  {chapter.headings.map((heading: Heading) => (
                    <li key={heading.ordinal} data-level={heading.level}>
                      <button
                        type="button"
                        className="toc-heading"
                        style={{ paddingLeft: `${0.5 + (heading.level - 1) * 0.75}rem` }}
                        onClick={() => void goTo(chapter.document_id, heading.ordinal)}
                      >
                        {heading.text || <span className="toc-untitled">Untitled heading</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>

      <div className="toc-footer">
        <p className="toc-total" data-testid="toc-total">
          {plural(chapters.length, 'chapter')} · {plural(total, 'word')}
        </p>
        <button type="button" disabled={creating} onClick={() => void addChapter()}>
          {creating ? 'Adding…' : 'New chapter'}
        </button>
        <button
          type="button"
          className="toc-deleted-toggle"
          aria-expanded={showDeleted}
          onClick={() => void onShowDeleted()}
        >
          Deleted chapters
        </button>
      </div>

      <MarkdownTransfer onOpen={(documentId) => void goTo(documentId)} />

      {showDeleted && (
        <div className="toc-deleted">
          {projectState.deleted.length === 0 ? (
            <p className="panel-placeholder" data-testid="toc-deleted-status">
              Nothing has been deleted.
            </p>
          ) : (
            <ul>
              {projectState.deleted.map((meta) => (
                <li key={meta.id}>
                  <span className="toc-deleted-title">{meta.title}</span>
                  <span className="toc-count">
                    {plural(meta.word_count, 'word')}
                    {meta.deleted_at !== null && ` · ${formatDateTime(meta.deleted_at)}`}
                  </span>
                  <button
                    type="button"
                    aria-label={`${meta.title}: restore`}
                    onClick={() => void onRestore(meta.id)}
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface ChapterNameProps {
  title: string;
  onCommit: (title: string) => void;
  onAbandon: () => void;
}

/** A chapter title, renamed in the list. Enter or blur commits; Escape abandons. */
function ChapterName({ title, onCommit, onAbandon }: ChapterNameProps) {
  const [draft, setDraft] = useState(title);

  const commit = useCallback(
    (event?: FormEvent) => {
      event?.preventDefault();
      const next = draft.trim();
      if (next.length === 0 || next === title) {
        onAbandon();
        return;
      }
      onCommit(next);
    },
    [draft, onAbandon, onCommit, title],
  );

  return (
    <form className="toc-rename" onSubmit={commit}>
      {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the writer just asked to type here */}
      <input
        autoFocus
        aria-label={`${title}: new name`}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => commit()}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            onAbandon();
          }
        }}
      />
    </form>
  );
}
