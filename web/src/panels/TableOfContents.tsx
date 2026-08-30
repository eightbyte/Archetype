/**
 * The Contents tab (P1-11).
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
 * document. Anchors do not exist until Phase 2, and this is the seam they replace (P1-11). An
 * ordinal survives editing above it in a way a character offset would not, and it is exactly
 * what the projection already numbers headings by.
 */

import { useCallback, useMemo, useState } from 'react';
import type { OutlineChapter } from '../api';
import type { Heading } from '../editor/projection';
import { plural } from '../format';
import { useDocument } from '../state/DocumentContext';
import { useProject } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';

export function TableOfContents() {
  const { state: projectState, createChapter } = useProject();
  const { state: documentState, openDocument } = useDocument();
  const { push } = useToasts();
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [creating, setCreating] = useState(false);

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
      push(
        `Could not add a chapter — ${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setCreating(false);
    }
  }, [createChapter, openDocument, push]);

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
      <ol className="toc-chapters">
        {chapters.map((chapter) => {
          const isOpen = chapter.document_id === openDocumentId;
          const isCollapsed = collapsed.has(chapter.document_id);
          return (
            <li key={chapter.document_id} className={isOpen ? 'toc-chapter is-open' : 'toc-chapter'}>
              <div className="toc-chapter-row">
                <button
                  type="button"
                  className="toc-twisty"
                  aria-expanded={!isCollapsed}
                  aria-label={`${isCollapsed ? 'Show' : 'Hide'} the headings in ${chapter.title}`}
                  onClick={() => toggle(chapter.document_id)}
                >
                  {isCollapsed ? '▸' : '▾'}
                </button>
                <button
                  type="button"
                  className="toc-chapter-title"
                  aria-current={isOpen ? 'true' : undefined}
                  onClick={() => void goTo(chapter.document_id)}
                >
                  {chapter.title}
                </button>
                <span className="toc-count">{plural(chapter.word_count, 'word')}</span>
              </div>

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
        {/* Create, rename, and open only in Phase 1 — reorder, delete, and snapshots arrive
            together in Phase 2, where the snapshot is what makes deleting safe. */}
        <button type="button" disabled={creating} onClick={() => void addChapter()}>
          {creating ? 'Adding…' : 'New chapter'}
        </button>
      </div>
    </div>
  );
}
