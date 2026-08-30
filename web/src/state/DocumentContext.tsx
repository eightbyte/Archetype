/**
 * The open document, and the autosave loop that keeps it saved (P1-9, P1-10, D19).
 *
 * Nested inside {@link ProjectContext} because a document's lifetime sits inside a project's:
 * opening another chapter resets everything here and nothing there.
 *
 * ## Why there is a ref as well as a reducer
 *
 * The save loop runs on timers and promises, so it needs to read the current state *now* — but
 * a `useReducer` state is not readable synchronously after a dispatch, and a save that read a
 * stale `version` would be refused as a conflict over a race the client caused. So every action
 * goes through {@link applyAction}, which runs the same pure reducer against a ref and then
 * dispatches it for rendering. One set of rules, two readers: the ref for the loop, React's copy
 * for the screen. Nothing dispatches to this reducer except through that function.
 *
 * The one thing the reducer deliberately does not hold is the live content: putting a whole
 * ProseMirror document into React state on every keystroke would re-render the tree to store
 * something only the save loop reads. It lives in a ref, and the reducer keeps the *projection*
 * of it, which is what the table of contents needs (D18).
 *
 * ## What the writer is promised
 *
 * * Nothing switches chapters over unsaved work. {@link openDocument} flushes first, and if the
 *   flush did not leave the document clean it refuses to switch rather than dropping the edit.
 * * A failed save is loud, keeps the content, and retries with backoff.
 * * A `409` stops the loop and asks (D19). It never merges and never overwrites.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from 'react';
import type { ReactNode } from 'react';
import type { ApiClient } from '../api';
import { ApiError } from '../api';
import type { SaveOutcome, SaveSchedulerOptions } from '../editor/autosave';
import { SaveScheduler } from '../editor/autosave';
import type { ProseMirrorDocument } from '../editor/projection';
import type { DocumentAction, DocumentState } from './documentReducer';
import { documentReducer, INITIAL_DOCUMENT_STATE, isDirty, needsFlush } from './documentReducer';
import { describeFailure, useProject } from './ProjectContext';

interface DocumentContextValue {
  state: DocumentState;
  /** True when the editor holds something the server has not been told about. */
  dirty: boolean;
  /**
   * Open a chapter, flushing any pending save first.
   *
   * Resolves `false` when the flush left the document dirty — a failed save, or an unresolved
   * conflict. Nothing was switched and nothing was lost; the caller says so.
   */
  openDocument: (documentId: string, headingOrdinal?: number) => Promise<boolean>;
  /**
   * Flush, and report whether it is safe to leave this document behind entirely.
   *
   * Same guard as {@link openDocument}, for the paths that are not a document switch — closing
   * the project, going back to the picker. `false` means unsaved work is still here.
   */
  canLeave: () => Promise<boolean>;
  /** The editor changed. Records it and arms the debounce. */
  edit: (content: ProseMirrorDocument) => void;
  /** Save now and wait for it. Called on blur, before a switch, and before unload. */
  flush: () => Promise<void>;
  /** Try a failed save again immediately. */
  retrySave: () => Promise<void>;
  /** Discard local edits and take the server's copy — the only answer offered to a `409`. */
  reloadFromServer: () => Promise<void>;
  /** Rename the open chapter. Does not touch the content version — a rename is not an edit. */
  rename: (title: string) => Promise<void>;
  /** Ask the editor to scroll to a heading of the open document by ordinal (P1-11). */
  jumpToHeading: (ordinal: number) => void;
  /** The editor has scrolled; clear the request. */
  headingReached: () => void;
}

const DocumentContext = createContext<DocumentContextValue | null>(null);

export interface DocumentProviderProps {
  client: ApiClient;
  children: ReactNode;
  /** Tests shorten the debounce and the backoff. */
  scheduler?: SaveSchedulerOptions;
  /** Open the project's first chapter on load. Off in tests that drive it by hand. */
  autoOpenFirst?: boolean;
}

export function DocumentProvider({
  client,
  children,
  scheduler: schedulerOptions,
  autoOpenFirst = true,
}: DocumentProviderProps) {
  const { state: projectState, dispatch: projectDispatch } = useProject();
  const [state, dispatch] = useReducer(documentReducer, INITIAL_DOCUMENT_STATE);

  const stateRef = useRef<DocumentState>(INITIAL_DOCUMENT_STATE);
  const contentRef = useRef<ProseMirrorDocument | null>(null);
  const clientRef = useRef(client);
  clientRef.current = client;
  const projectDispatchRef = useRef(projectDispatch);
  projectDispatchRef.current = projectDispatch;

  /** The only way an action reaches this reducer. See the module docstring. */
  const applyAction = useCallback((action: DocumentAction) => {
    stateRef.current = documentReducer(stateRef.current, action);
    dispatch(action);
  }, []);

  const performSave = useCallback(async (): Promise<SaveOutcome> => {
    const current = stateRef.current;
    const content = contentRef.current;
    if (current.status !== 'ready' || current.documentId === null || content === null) {
      return 'nothing-to-do';
    }
    if (current.save.kind === 'conflict') {
      return 'stop';
    }
    if (!isDirty(current)) {
      return 'nothing-to-do';
    }

    const documentId = current.documentId;
    const revision = current.revision;
    applyAction({ type: 'save-started', revision });

    try {
      const result = await clientRef.current.saveDocumentContent(
        documentId,
        content,
        current.version,
      );
      // The document may have been closed or switched while this was in the air; a result for a
      // chapter that is no longer open must not be written over the one that is.
      if (stateRef.current.documentId !== documentId) {
        return 'nothing-to-do';
      }
      applyAction({ type: 'save-succeeded', result });
      projectDispatchRef.current({ type: 'document-saved', result });
      return 'saved';
    } catch (error: unknown) {
      if (stateRef.current.documentId !== documentId) {
        return 'nothing-to-do';
      }
      const conflict = error instanceof ApiError ? error.versionConflict : null;
      if (conflict) {
        // D19: nothing was written and nothing is merged. The writer is asked.
        applyAction({ type: 'save-conflicted', detail: conflict });
        return 'stop';
      }
      applyAction({ type: 'save-failed', message: describeFailure(error) });
      return 'retry';
    }
  }, [applyAction]);

  const performSaveRef = useRef(performSave);
  performSaveRef.current = performSave;

  // Built once and left alone: a new scheduler would abandon a pending save. It reaches the
  // current `perform` through a ref, and `schedulerOptions` is a test seam fixed for the life of
  // the mount.
  const saverRef = useRef<SaveScheduler | null>(null);
  if (saverRef.current === null) {
    saverRef.current = new SaveScheduler(() => performSaveRef.current(), schedulerOptions ?? {});
  }
  const saver = saverRef.current;

  // The ref survives an unmount, so the scheduler has to be switched back on when the component
  // comes back. `StrictMode` mounts, unmounts, and remounts every component — and `main.tsx`
  // uses it — so a one-way dispose here would silently disable autosave in the browser while
  // every test that does not use StrictMode carried on passing.
  useEffect(() => {
    saver.activate();
    return () => saver.dispose();
  }, [saver]);

  const flush = useCallback(() => saver.flush(), [saver]);

  /** Save what is pending and answer whether anything unsaved is left. */
  const flushForHandover = useCallback(async (): Promise<boolean> => {
    const current = stateRef.current;
    if (current.status !== 'ready' || !isDirty(current)) {
      return true;
    }
    await saver.flush();
    return !isDirty(stateRef.current);
  }, [saver]);

  const loadDocument = useCallback(
    async (documentId: string, headingOrdinal?: number): Promise<void> => {
      saver.cancel();
      contentRef.current = null;
      applyAction(
        headingOrdinal === undefined
          ? { type: 'open-requested', documentId }
          : { type: 'open-requested', documentId, headingOrdinal },
      );
      try {
        const document = await clientRef.current.getDocument(documentId);
        if (stateRef.current.documentId !== documentId) {
          return;
        }
        contentRef.current = document.content_json;
        applyAction(
          headingOrdinal === undefined
            ? { type: 'opened', document }
            : { type: 'opened', document, headingOrdinal },
        );
      } catch (error: unknown) {
        if (stateRef.current.documentId !== documentId) {
          return;
        }
        applyAction({ type: 'open-failed', message: describeFailure(error) });
      }
    },
    [applyAction, saver],
  );

  const openDocument = useCallback(
    async (documentId: string, headingOrdinal?: number): Promise<boolean> => {
      const current = stateRef.current;
      if (current.documentId === documentId && current.status === 'ready') {
        if (headingOrdinal !== undefined) {
          applyAction({ type: 'jump-requested', ordinal: headingOrdinal });
        }
        return true;
      }
      // The save did not land — a failure, or a conflict the writer has not answered. Switching
      // now would throw the edit away, so it does not.
      if (!(await flushForHandover())) {
        return false;
      }
      await loadDocument(documentId, headingOrdinal);
      return true;
    },
    [applyAction, flushForHandover, loadDocument],
  );

  const edit = useCallback(
    (content: ProseMirrorDocument) => {
      if (stateRef.current.status !== 'ready') {
        return;
      }
      contentRef.current = content;
      applyAction({ type: 'edited', content });
      saver.schedule();
    },
    [applyAction, saver],
  );

  const retrySave = useCallback(() => saver.flush(), [saver]);

  const reloadFromServer = useCallback(async () => {
    const documentId = stateRef.current.documentId;
    if (documentId === null) {
      return;
    }
    saver.resume();
    await loadDocument(documentId);
  }, [loadDocument, saver]);

  const rename = useCallback(
    async (title: string) => {
      const documentId = stateRef.current.documentId;
      if (documentId === null) {
        return;
      }
      const meta = await clientRef.current.renameDocument(documentId, title);
      applyAction({ type: 'renamed', title: meta.title });
      projectDispatchRef.current({ type: 'document-renamed', documentId, title: meta.title });
    },
    [applyAction],
  );

  const jumpToHeading = useCallback(
    (ordinal: number) => applyAction({ type: 'jump-requested', ordinal }),
    [applyAction],
  );
  const headingReached = useCallback(() => applyAction({ type: 'jump-completed' }), [applyAction]);

  // Open the first chapter once the project is ready. A project always has one (P1-12 seeds it
  // server-side), so a writer lands in the editor rather than in an empty state.
  const firstDocumentId = projectState.chapters[0]?.document_id ?? null;
  useEffect(() => {
    if (!autoOpenFirst || firstDocumentId === null) {
      return;
    }
    if (stateRef.current.status === 'empty') {
      void loadDocument(firstDocumentId);
    }
  }, [autoOpenFirst, firstDocumentId, loadDocument]);

  // Navigating away with unsaved work asks the browser to confirm, and starts the save anyway.
  // The save cannot be awaited here — nothing can — but it usually wins the race, and the prompt
  // is what makes the outcome the writer's decision rather than a silent loss (P1-10).
  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!needsFlush(stateRef.current)) {
        return;
      }
      void saver.flush();
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [saver]);

  const value = useMemo<DocumentContextValue>(
    () => ({
      state,
      dirty: isDirty(state),
      openDocument,
      canLeave: flushForHandover,
      edit,
      flush,
      retrySave,
      reloadFromServer,
      rename,
      jumpToHeading,
      headingReached,
    }),
    [
      state,
      openDocument,
      flushForHandover,
      edit,
      flush,
      retrySave,
      reloadFromServer,
      rename,
      jumpToHeading,
      headingReached,
    ],
  );

  return <DocumentContext.Provider value={value}>{children}</DocumentContext.Provider>;
}

export function useDocument(): DocumentContextValue {
  const value = useContext(DocumentContext);
  if (!value) {
    throw new Error('useDocument must be used inside a DocumentProvider');
  }
  return value;
}
