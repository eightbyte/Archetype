/**
 * The open project: its identity, its chapter list, and the stitched outline (P1-9, P1-11).
 *
 * Lifetime is one project. It survives every document switch, which is why the chapter list and
 * the whole-manuscript outline live here rather than beside the open document (D10).
 *
 * The outline is the server's (D18, D2): it spans every chapter while only one is loaded, so it
 * cannot be derived from editor state. What the client mirror derives for the *open* document
 * lives in `documentReducer.ts` and is layered over this one at the point of display — the two
 * are kept separate so it is always obvious which answer is being shown.
 *
 * Pure. No React, no client.
 */

import type { Heading } from '../editor/projection';
import type {
  Document,
  DocumentMeta,
  OutlineChapter,
  ProjectDetail,
  ProjectSummary,
  SaveResult,
} from '../api/types';

export interface ProjectState {
  status: 'loading' | 'ready' | 'failed';
  project: ProjectSummary | null;
  documents: DocumentMeta[];
  /** The table of contents across the whole manuscript, as the server derived it. */
  chapters: OutlineChapter[];
  error: string | null;
}

export type ProjectAction =
  | { type: 'load-requested' }
  | { type: 'loaded'; detail: ProjectDetail; chapters: OutlineChapter[] }
  | { type: 'load-failed'; message: string }
  | { type: 'document-created'; document: Document }
  | { type: 'document-renamed'; documentId: string; title: string }
  | { type: 'document-saved'; result: SaveResult };

export const INITIAL_PROJECT_STATE: ProjectState = {
  status: 'loading',
  project: null,
  documents: [],
  chapters: [],
  error: null,
};

export function projectReducer(state: ProjectState, action: ProjectAction): ProjectState {
  switch (action.type) {
    case 'load-requested':
      return { ...INITIAL_PROJECT_STATE, status: 'loading' };

    case 'loaded':
      return {
        status: 'ready',
        project: action.detail.project,
        documents: action.detail.documents,
        chapters: action.chapters,
        error: null,
      };

    case 'load-failed':
      return { ...state, status: 'failed', error: action.message };

    case 'document-created': {
      const created = action.document;
      const meta: DocumentMeta = {
        id: created.id,
        project_id: created.project_id,
        order_index: created.order_index,
        title: created.title,
        kind: created.kind,
        headings: created.headings,
        word_count: created.word_count,
        version: created.version,
        created_at: created.created_at,
        updated_at: created.updated_at,
      };
      const documents = ordered([...state.documents, meta]);
      const chapters = ordered([
        ...state.chapters,
        {
          document_id: created.id,
          title: created.title,
          order_index: created.order_index,
          word_count: created.word_count,
          headings: created.headings,
        },
      ]);
      return {
        ...state,
        documents,
        chapters,
        project: withCounts(state.project, documents.length, chapters),
      };
    }

    case 'document-renamed':
      return {
        ...state,
        documents: state.documents.map((meta) =>
          meta.id === action.documentId ? { ...meta, title: action.title } : meta,
        ),
        chapters: state.chapters.map((chapter) =>
          chapter.document_id === action.documentId
            ? { ...chapter, title: action.title }
            : chapter,
        ),
      };

    case 'document-saved': {
      const { document_id, version, word_count, headings, updated_at } = action.result;
      const documents = state.documents.map((meta) =>
        meta.id === document_id
          ? { ...meta, version, word_count, headings, updated_at }
          : meta,
      );
      const chapters = state.chapters.map((chapter) =>
        chapter.document_id === document_id ? { ...chapter, word_count, headings } : chapter,
      );
      return {
        ...state,
        documents,
        chapters,
        // The picker sorts on the project's own timestamp, and a chapter that changed a minute
        // ago must not leave the project claiming it was last touched when it was created.
        project: withCounts(
          state.project ? { ...state.project, updated_at } : null,
          documents.length,
          chapters,
        ),
      };
    }
  }
}

/** Total words across the manuscript, from the outline the server derived. */
export function wordCountOf(chapters: readonly OutlineChapter[]): number {
  return chapters.reduce((total, chapter) => total + chapter.word_count, 0);
}

/** Every heading in the manuscript, chapter by chapter, in reading order. */
export function headingsOf(chapters: readonly OutlineChapter[]): Heading[] {
  return chapters.flatMap((chapter) => chapter.headings);
}

function ordered<T extends { order_index: number }>(items: T[]): T[] {
  return [...items].sort((a, b) => a.order_index - b.order_index);
}

function withCounts(
  project: ProjectSummary | null,
  chapterCount: number,
  chapters: readonly OutlineChapter[],
): ProjectSummary | null {
  if (!project) {
    return null;
  }
  return { ...project, chapter_count: chapterCount, word_count: wordCountOf(chapters) };
}
