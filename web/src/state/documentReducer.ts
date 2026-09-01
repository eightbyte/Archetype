/**
 * The open document: what it is, whether it is dirty, and what the last save did (P1-9, P1-10).
 *
 * Lifetime is one chapter. It is its own reducer because opening a different chapter resets all
 * of it and none of the project's state, which is exactly the split D10 asks for.
 *
 * Pure. The autosave loop that drives it is split between `editor/autosave.ts` (when a save
 * happens) and `state/DocumentContext.tsx` (what one does); the rules about what a save *means*
 * are here, where they can be tested without a timer or a network.
 *
 * **Dirtiness is a revision comparison, not a flag.** Every edit bumps `revision`; a save
 * records which revision it is writing and, when it lands, marks that one saved. An edit made
 * *while* a save is in flight therefore leaves the document dirty when the save returns, which
 * is the honest answer — and a flag set to `false` on success would have lost that keystroke's
 * worth of change until the next one arrived.
 */

import type { Heading, ProseMirrorDocument } from '../editor/projection';
import { project } from '../editor/projection';
import type { Document, SaveResult, VersionConflictDetail } from '../api/types';

/** What the status indicator shows (P1-10). */
export type SaveState =
  | { kind: 'idle' }
  | { kind: 'unsaved' }
  | { kind: 'saving' }
  | { kind: 'saved'; at: string }
  | { kind: 'failed'; message: string; attempt: number }
  | { kind: 'conflict'; detail: VersionConflictDetail };

export interface DocumentState {
  status: 'empty' | 'loading' | 'ready' | 'failed';
  documentId: string | null;
  title: string;
  version: number;
  /** What the editor is seeded with. Replaced on load and on reload, never on save. */
  content: ProseMirrorDocument | null;
  /** Bumped on each load, so the editor re-seeds when the same document is reloaded. */
  sequence: number;
  /** Bumped on every edit. `revision === savedRevision` is what "clean" means. */
  revision: number;
  savedRevision: number;
  /** The revision the in-flight save is writing, or null when nothing is in flight. */
  savingRevision: number | null;
  /** The live projection of the open document (D18) — the server's answer replaces it on save. */
  headings: Heading[];
  wordCount: number;
  save: SaveState;
  loadError: string | null;
  /** A heading ordinal the editor should scroll to once the document is on screen (P1-11). */
  pendingHeading: number | null;
  /**
   * An anchor the editor should scroll to and select once its decoration exists (P2-10).
   *
   * Separate from {@link pendingHeading} because it clears differently: a heading is found on
   * the first pass or not at all, while an anchor arrives one request after the document does,
   * so this stays set until the decoration is actually there.
   */
  pendingAnchor: string | null;
}

export type DocumentAction =
  | { type: 'open-requested'; documentId: string; headingOrdinal?: number }
  | { type: 'opened'; document: Document; headingOrdinal?: number }
  | { type: 'open-failed'; message: string }
  | { type: 'edited'; content: ProseMirrorDocument }
  | { type: 'save-started'; revision: number }
  | { type: 'save-succeeded'; result: SaveResult }
  | { type: 'save-failed'; message: string }
  | { type: 'save-conflicted'; detail: VersionConflictDetail }
  | { type: 'renamed'; title: string }
  | { type: 'jump-requested'; ordinal: number }
  | { type: 'jump-completed' }
  | { type: 'anchor-jump-requested'; anchorId: string }
  | { type: 'anchor-jump-completed' }
  | { type: 'closed' };

export const INITIAL_DOCUMENT_STATE: DocumentState = {
  status: 'empty',
  documentId: null,
  title: '',
  version: 0,
  content: null,
  sequence: 0,
  revision: 0,
  savedRevision: 0,
  savingRevision: null,
  headings: [],
  wordCount: 0,
  save: { kind: 'idle' },
  loadError: null,
  pendingHeading: null,
  pendingAnchor: null,
};

/** True when the editor holds something the server has not been told about. */
export function isDirty(state: DocumentState): boolean {
  return state.revision !== state.savedRevision;
}

/** True while the document must not be replaced without flushing first (P1-10). */
export function needsFlush(state: DocumentState): boolean {
  return state.status === 'ready' && isDirty(state) && state.save.kind !== 'conflict';
}

export function documentReducer(state: DocumentState, action: DocumentAction): DocumentState {
  switch (action.type) {
    case 'open-requested':
      return {
        ...INITIAL_DOCUMENT_STATE,
        status: 'loading',
        documentId: action.documentId,
        sequence: state.sequence + 1,
        pendingHeading: action.headingOrdinal ?? null,
      };

    case 'opened': {
      const document = action.document;
      return {
        ...INITIAL_DOCUMENT_STATE,
        status: 'ready',
        documentId: document.id,
        title: document.title,
        version: document.version,
        content: document.content_json,
        // Every load gets its own sequence number, so the editor re-seeds even when the same
        // chapter is loaded again — which is what resolving a conflict does (D19).
        sequence: state.sequence + 1,
        headings: document.headings,
        wordCount: document.word_count,
        save: { kind: 'idle' },
        pendingHeading: action.headingOrdinal ?? state.pendingHeading,
      };
    }

    case 'open-failed':
      return { ...state, status: 'failed', loadError: action.message, content: null };

    case 'edited': {
      if (state.status !== 'ready') {
        return state;
      }
      const projection = project(action.content);
      return {
        ...state,
        revision: state.revision + 1,
        headings: projection.headings,
        wordCount: projection.word_count,
        // A conflict is not cleared by typing more. Autosave stays stopped until the writer
        // reloads or discards, because the alternative is a silent overwrite (D19).
        save: state.save.kind === 'conflict' ? state.save : { kind: 'unsaved' },
      };
    }

    case 'save-started':
      return { ...state, save: { kind: 'saving' }, savingRevision: action.revision };

    case 'save-succeeded': {
      const savedRevision = state.savingRevision ?? state.revision;
      const stillDirty = state.revision !== savedRevision;
      return {
        ...state,
        version: action.result.version,
        savedRevision,
        savingRevision: null,
        // D18: the server owns the projection. Whatever the mirror said, this is the answer.
        headings: action.result.headings,
        wordCount: action.result.word_count,
        save: stillDirty ? { kind: 'unsaved' } : { kind: 'saved', at: action.result.updated_at },
      };
    }

    case 'save-failed':
      return {
        ...state,
        savingRevision: null,
        save: {
          kind: 'failed',
          message: action.message,
          attempt: state.save.kind === 'failed' ? state.save.attempt + 1 : 1,
        },
      };

    case 'save-conflicted':
      return { ...state, savingRevision: null, save: { kind: 'conflict', detail: action.detail } };

    case 'renamed':
      return { ...state, title: action.title };

    case 'jump-requested':
      return { ...state, pendingHeading: action.ordinal };

    case 'jump-completed':
      return state.pendingHeading === null ? state : { ...state, pendingHeading: null };

    case 'anchor-jump-requested':
      return { ...state, pendingAnchor: action.anchorId };

    case 'anchor-jump-completed':
      return state.pendingAnchor === null ? state : { ...state, pendingAnchor: null };

    case 'closed':
      return INITIAL_DOCUMENT_STATE;
  }
}
