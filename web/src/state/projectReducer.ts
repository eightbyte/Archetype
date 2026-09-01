/**
 * The open project: its identity, its chapter list, the stitched outline, and its anchors
 * (P1-9, P1-11, P2-9 → P2-12).
 *
 * Lifetime is one project. It survives every document switch, which is why the chapter list and
 * the whole-manuscript outline live here rather than beside the open document (D10).
 *
 * The outline is the server's (D18, D2): it spans every chapter while only one is loaded, so it
 * cannot be derived from editor state. What the client mirror derives for the *open* document
 * lives in `documentReducer.ts` and is layered over this one at the point of display — the two
 * are kept separate so it is always obvious which answer is being shown.
 *
 * ## Why the anchors are here and not beside the open document
 *
 * An anchor's lifetime is the project's: the *Marks* tab holds every chapter's at once, a save
 * of one chapter can only move that chapter's, and a manual re-link is allowed to cross from
 * one chapter to another. Holding them beside the open document would mean two lists to
 * reconcile — the open one and the panel's — and the reconciliation would be the bug. So there
 * is **one** list here, and the open document's anchors are the slice of it whose `document_id`
 * matches. The editor's decorations are a third thing again and belong to neither: they are
 * mapped positions, display-only, and never sent (D21).
 *
 * `relinking` is here for the same reason. Repairing a stale anchor by hand starts in the panel
 * and finishes in the editor, possibly in a different chapter, so the fact that a repair is in
 * progress outlives every document switch it might involve.
 *
 * Pure. No React, no client.
 */

import type { Heading } from '../editor/projection';
import type {
  Anchor,
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
  /** Soft-deleted chapters, most recently deleted first. Read on demand (D22). */
  deleted: DocumentMeta[];
  /** Every anchor in the project, in chapter order then position order (P2-10). */
  anchors: Anchor[];
  /** The anchor the writer is re-linking by selecting text, or `null` (P2-10). */
  relinking: string | null;
  error: string | null;
}

export type ProjectAction =
  | { type: 'load-requested' }
  | { type: 'loaded'; detail: ProjectDetail; chapters: OutlineChapter[]; anchors: Anchor[] }
  | { type: 'load-failed'; message: string }
  | { type: 'document-created'; document: Document }
  | { type: 'document-renamed'; documentId: string; title: string }
  | { type: 'document-saved'; result: SaveResult }
  | { type: 'documents-reordered'; documents: DocumentMeta[] }
  | { type: 'document-deleted'; meta: DocumentMeta }
  | { type: 'document-restored'; meta: DocumentMeta }
  | { type: 'deleted-loaded'; documents: DocumentMeta[] }
  | { type: 'anchors-resolved'; documentId: string; anchors: Anchor[] }
  | { type: 'anchor-changed'; anchor: Anchor }
  | { type: 'anchor-removed'; anchorId: string }
  | { type: 'relink-armed'; anchorId: string }
  | { type: 'relink-cancelled' };

export const INITIAL_PROJECT_STATE: ProjectState = {
  status: 'loading',
  project: null,
  documents: [],
  chapters: [],
  deleted: [],
  anchors: [],
  relinking: null,
  error: null,
};

export function projectReducer(state: ProjectState, action: ProjectAction): ProjectState {
  switch (action.type) {
    case 'load-requested':
      return { ...INITIAL_PROJECT_STATE, status: 'loading' };

    case 'loaded':
      return {
        ...INITIAL_PROJECT_STATE,
        status: 'ready',
        project: action.detail.project,
        documents: action.detail.documents,
        chapters: action.chapters,
        anchors: action.anchors,
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
        deleted_at: null,
      };
      const documents = ordered([...state.documents, meta]);
      const chapters = ordered([...state.chapters, chapterOf(meta)]);
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
        meta.id === document_id ? { ...meta, version, word_count, headings, updated_at } : meta,
      );
      const chapters = state.chapters.map((chapter) =>
        chapter.document_id === document_id ? { ...chapter, word_count, headings } : chapter,
      );
      return {
        ...state,
        documents,
        chapters,
        // D21: the server re-resolved every anchor of this document inside the save's own
        // transaction and reported the ones that moved. Its answer replaces whatever the
        // editor's mapping had them at — the mapping is for liveness, this is the truth.
        anchors: mergeAnchors(state.anchors, action.result.anchors),
        // The picker sorts on the project's own timestamp, and a chapter that changed a minute
        // ago must not leave the project claiming it was last touched when it was created.
        project: withCounts(
          state.project ? { ...state.project, updated_at } : null,
          documents.length,
          chapters,
        ),
      };
    }

    case 'documents-reordered': {
      // The server answered with the complete live set, so it replaces the list rather than
      // patching it: a reorder that half-landed would be worse than one that did not.
      const documents = ordered(action.documents);
      const byId = new Map(documents.map((meta) => [meta.id, meta]));
      const chapters = ordered(
        state.chapters
          .filter((chapter) => byId.has(chapter.document_id))
          .map((chapter) => ({
            ...chapter,
            order_index: byId.get(chapter.document_id)!.order_index,
          })),
      );
      return { ...state, documents, chapters };
    }

    case 'document-deleted': {
      const documents = state.documents.filter((meta) => meta.id !== action.meta.id);
      const chapters = state.chapters.filter(
        (chapter) => chapter.document_id !== action.meta.id,
      );
      return {
        ...state,
        documents,
        chapters,
        deleted: [action.meta, ...state.deleted.filter((meta) => meta.id !== action.meta.id)],
        // Nothing is written to an anchor row by a delete (D22) — the status a reader sees is
        // derived from the chapter, so it is derived here too rather than stored twice.
        anchors: state.anchors.map((anchor) =>
          anchor.document_id === action.meta.id ? { ...anchor, status: 'orphaned' } : anchor,
        ),
        project: withCounts(state.project, documents.length, chapters),
      };
    }

    case 'document-restored': {
      const documents = ordered([
        ...state.documents.filter((meta) => meta.id !== action.meta.id),
        action.meta,
      ]);
      const chapters = ordered([
        ...state.chapters.filter((chapter) => chapter.document_id !== action.meta.id),
        chapterOf(action.meta),
      ]);
      return {
        ...state,
        documents,
        chapters,
        deleted: state.deleted.filter((meta) => meta.id !== action.meta.id),
        // The anchors are deliberately **not** touched here. `orphaned` was the chapter showing
        // through a stored `ok` or `stale`, and which of the two it was is something only the
        // server knows — so guessing `ok` would be this client deciding an anchor's status,
        // which is the one thing nothing on this side may do (§ 2, ruling 2). `restoreChapter`
        // reads them back and dispatches `anchors-resolved` in the same breath.
        project: withCounts(state.project, documents.length, chapters),
      };
    }

    case 'deleted-loaded':
      return { ...state, deleted: action.documents };

    case 'anchors-resolved': {
      // A document's anchors were read fresh and resolved against its current text, so this
      // document's slice is replaced wholesale — an anchor missing from the answer is one that
      // is gone, not one that stayed the same.
      const others = state.anchors.filter((anchor) => anchor.document_id !== action.documentId);
      return { ...state, anchors: sortAnchors([...others, ...action.anchors], state.documents) };
    }

    case 'anchor-changed':
      return {
        ...state,
        anchors: sortAnchors(
          [
            ...state.anchors.filter((anchor) => anchor.id !== action.anchor.id),
            action.anchor,
          ],
          state.documents,
        ),
        // Repairing the anchor being re-linked ends the repair; repairing another does not.
        relinking: state.relinking === action.anchor.id ? null : state.relinking,
      };

    case 'anchor-removed':
      return {
        ...state,
        anchors: state.anchors.filter((anchor) => anchor.id !== action.anchorId),
        relinking: state.relinking === action.anchorId ? null : state.relinking,
      };

    case 'relink-armed':
      return { ...state, relinking: action.anchorId };

    case 'relink-cancelled':
      return state.relinking === null ? state : { ...state, relinking: null };
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

/** One document's anchors, in position order. The open document's decorations read this. */
export function anchorsOf(state: ProjectState, documentId: string | null): Anchor[] {
  if (documentId === null) {
    return [];
  }
  return state.anchors.filter((anchor) => anchor.document_id === documentId);
}

/** How many anchors point into a chapter — what the delete confirmation has to say. */
export function anchorCountOf(state: ProjectState, documentId: string): number {
  return state.anchors.reduce(
    (total, anchor) => (anchor.document_id === documentId ? total + 1 : total),
    0,
  );
}

function ordered<T extends { order_index: number }>(items: T[]): T[] {
  return [...items].sort((a, b) => a.order_index - b.order_index);
}

function chapterOf(meta: DocumentMeta): OutlineChapter {
  return {
    document_id: meta.id,
    title: meta.title,
    order_index: meta.order_index,
    word_count: meta.word_count,
    headings: meta.headings,
  };
}

/** Replace the anchors a write moved, leaving every other one exactly as it was. */
function mergeAnchors(current: readonly Anchor[], moved: readonly Anchor[]): Anchor[] {
  if (moved.length === 0) {
    return current as Anchor[];
  }
  const byId = new Map(moved.map((anchor) => [anchor.id, anchor]));
  const merged = current.map((anchor) => byId.get(anchor.id) ?? anchor);
  const known = new Set(current.map((anchor) => anchor.id));
  return [...merged, ...moved.filter((anchor) => !known.has(anchor.id))];
}

/** Chapter order, then position — the order the server lists them in, kept locally. */
function sortAnchors(anchors: Anchor[], documents: readonly DocumentMeta[]): Anchor[] {
  const order = new Map(documents.map((meta) => [meta.id, meta.order_index]));
  return [...anchors].sort(
    (a, b) =>
      (order.get(a.document_id) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(b.document_id) ?? Number.MAX_SAFE_INTEGER) ||
      a.from_pos - b.from_pos ||
      (a.id < b.id ? -1 : 1),
  );
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
