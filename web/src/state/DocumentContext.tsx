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
import type { Anchor, ApiClient, Snapshot, SnapshotMeta } from '../api';
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
  /**
   * Open an anchor's chapter and scroll to it (P2-10).
   *
   * Resolves `false` when the chapter could not be switched to — unsaved work, or an unanswered
   * conflict. Nothing was moved and nothing was lost; the caller says so.
   */
  goToAnchor: (documentId: string, anchorId: string) => Promise<boolean>;
  /** The editor found the decoration and scrolled to it; clear the request. */
  anchorReached: () => void;
  /**
   * Anchor a range of the open chapter (P2-9).
   *
   * Sends the ProseMirror range and the document version, and nothing else: the server reads
   * the quote and its context out of the stored text, so an anchor cannot disagree with the
   * manuscript. Flushes first, because a range against text the server has not been told about
   * is a range against text nobody looked at (D19).
   */
  createAnchor: (fromPos: number, toPos: number, label?: string) => Promise<Anchor>;
  /** Mark this version of the open chapter, with a label (D23). */
  markVersion: (label: string) => Promise<SnapshotMeta | null>;
  /** The open chapter's history, newest first. Metadata only — never content. */
  listSnapshots: () => Promise<SnapshotMeta[]>;
  /** One snapshot with its content, for a preview. */
  readSnapshot: (snapshotId: string) => Promise<Snapshot>;
  /**
   * Flush, then hand back the open chapter's text as this client has it.
   *
   * What a restore from here would replace, which is the honest "before" to show beside a
   * snapshot — the content the editor was *seeded* with is what the chapter was when it was
   * opened, not what it is now. If another window has since written, this client's copy is
   * behind, and the restore it is offering would be refused as stale either way (D19).
   */
  savedContent: () => Promise<ProseMirrorDocument | null>;
  /**
   * Restore a snapshot of the open chapter.
   *
   * An ordinary save on the server (D23): the current text is snapshotted as `pre-restore`
   * inside the same transaction, the version moves, and the anchors are re-resolved. The
   * editor then reloads to the restored content.
   */
  restoreSnapshot: (snapshotId: string) => Promise<void>;
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

  /**
   * Read a document's anchors, resolved against its current text, into the project's list.
   *
   * Deliberately not fatal. Anchors are a layer over the manuscript; a panel that could not be
   * drawn must never be the reason the writing surface is not, and the editor may be holding
   * the only copy of a sentence (P1-9's per-region rule, applied to a request).
   */
  const loadAnchors = useCallback(async (documentId: string): Promise<void> => {
    try {
      const listed = await clientRef.current.listDocumentAnchors(documentId);
      projectDispatchRef.current({ type: 'anchors-resolved', documentId, anchors: listed.anchors });
    } catch {
      // Leave whatever the project list already had: a cached answer beats an empty panel.
    }
  }, []);

  /**
   * Snapshot the chapter being left behind (D23).
   *
   * Best-effort by design: a handover snapshot is a convenience, and a chapter whose text has
   * not changed since the last one writes nothing at all — the server deduplicates it. Failing
   * a chapter switch over one would trade a real thing for a spare copy.
   */
  const captureHandover = useCallback(async (documentId: string): Promise<void> => {
    try {
      await clientRef.current.captureSnapshot(documentId, 'handover');
    } catch {
      // Nothing to say and nothing to do: the writer asked to change chapters, not to snapshot.
    }
  }, []);

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
        return;
      }
      await loadAnchors(documentId);
    },
    [applyAction, loadAnchors, saver],
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
      const leaving = current.documentId;
      if (leaving !== null && current.status === 'ready') {
        await captureHandover(leaving);
      }
      await loadDocument(documentId, headingOrdinal);
      return true;
    },
    [applyAction, captureHandover, flushForHandover, loadDocument],
  );

  /** Flush, snapshot the chapter being left, and say whether unsaved work is still here. */
  const canLeave = useCallback(async (): Promise<boolean> => {
    const current = stateRef.current;
    if (!(await flushForHandover())) {
      return false;
    }
    if (current.documentId !== null && current.status === 'ready') {
      await captureHandover(current.documentId);
    }
    return true;
  }, [captureHandover, flushForHandover]);

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

  const goToAnchor = useCallback(
    async (documentId: string, anchorId: string): Promise<boolean> => {
      if (!(await openDocument(documentId))) {
        return false;
      }
      // After the open, not with it: the decoration does not exist until the anchors have been
      // read, which is one request behind the document.
      applyAction({ type: 'anchor-jump-requested', anchorId });
      return true;
    },
    [applyAction, openDocument],
  );
  const anchorReached = useCallback(
    () => applyAction({ type: 'anchor-jump-completed' }),
    [applyAction],
  );

  const createAnchor = useCallback(
    async (fromPos: number, toPos: number, label?: string): Promise<Anchor> => {
      // Flush first. The server derives the quote from the text it holds, so anchoring a range
      // it has not been told about would anchor the wrong words — or be refused as stale.
      await saver.flush();
      const current = stateRef.current;
      if (current.documentId === null || current.status !== 'ready') {
        throw new Error('no chapter is open to anchor');
      }
      const anchor = await clientRef.current.createAnchor(
        current.documentId,
        { from_pos: fromPos, to_pos: toPos, version: current.version },
        label ?? '',
      );
      projectDispatchRef.current({ type: 'anchor-changed', anchor });
      return anchor;
    },
    [saver],
  );

  const markVersion = useCallback(
    async (label: string): Promise<SnapshotMeta | null> => {
      // A mark records what is on screen, so what is on screen has to be what is stored.
      await saver.flush();
      const documentId = stateRef.current.documentId;
      if (documentId === null) {
        return null;
      }
      const captured = await clientRef.current.captureSnapshot(documentId, 'manual', label);
      return captured.snapshot;
    },
    [saver],
  );

  const listSnapshots = useCallback(async (): Promise<SnapshotMeta[]> => {
    const documentId = stateRef.current.documentId;
    if (documentId === null) {
      return [];
    }
    return (await clientRef.current.listSnapshots(documentId)).snapshots;
  }, []);

  const readSnapshot = useCallback(
    (snapshotId: string): Promise<Snapshot> => clientRef.current.getSnapshot(snapshotId),
    [],
  );

  const savedContent = useCallback(async (): Promise<ProseMirrorDocument | null> => {
    await saver.flush();
    return contentRef.current;
  }, [saver]);

  const restoreSnapshot = useCallback(
    async (snapshotId: string): Promise<void> => {
      await saver.flush();
      const current = stateRef.current;
      const documentId = current.documentId;
      if (documentId === null || current.status !== 'ready') {
        return;
      }
      const result = await clientRef.current.restoreSnapshot(snapshotId, current.version);
      // The restore is a save like any other, so the rest of the app hears about it the same
      // way — including the anchors it moved (D21).
      projectDispatchRef.current({ type: 'document-saved', result });
      // And then the editor takes the restored text, through the ordinary load path: the
      // content came from the server, so the server is where it is read back from.
      await loadDocument(documentId);
    },
    [loadDocument, saver],
  );

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
      canLeave,
      edit,
      flush,
      retrySave,
      reloadFromServer,
      rename,
      jumpToHeading,
      headingReached,
      goToAnchor,
      anchorReached,
      createAnchor,
      markVersion,
      listSnapshots,
      readSnapshot,
      savedContent,
      restoreSnapshot,
    }),
    [
      state,
      openDocument,
      canLeave,
      edit,
      flush,
      retrySave,
      reloadFromServer,
      rename,
      jumpToHeading,
      headingReached,
      goToAnchor,
      anchorReached,
      createAnchor,
      markVersion,
      listSnapshots,
      readSnapshot,
      savedContent,
      restoreSnapshot,
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
