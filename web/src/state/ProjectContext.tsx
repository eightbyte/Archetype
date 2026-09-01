/**
 * The open project (P1-9, D10), and everything whose lifetime is the project's (P2-10, P2-11).
 *
 * Loads the project, its chapter list, the stitched outline, and its anchors in one pass, and
 * holds them for as long as that project is open. The outline route reads only derived columns,
 * so the whole manuscript's table of contents is drawn without loading a single chapter's
 * content (D2, D18); the project anchor list reports the server's cached answers for the same
 * reason — re-resolving it would mean projecting every chapter to draw one panel (P2-7, B8).
 *
 * `dispatch` is deliberately exposed: the document layer nests inside this one and tells it when
 * a save landed, so the table of contents for the *other* chapters stays true without refetching
 * the outline on every keystroke — and so the anchors a write moved reach the *Marks* tab
 * without a refetch either (D21).
 *
 * The chapter operations live here rather than in a panel because two panels and the editor all
 * act on them: deleting a chapter changes the contents list, the marks list, and possibly which
 * chapter the editor is holding. A component that owned that would own the other two.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer } from 'react';
import type { ReactNode } from 'react';
import type {
  AnchorRange,
  ApiClient,
  Document,
  DocumentMeta,
  ImportMode,
  MarkdownImport,
} from '../api';
import { ApiError, NetworkError } from '../api';
import type { ProjectAction, ProjectState } from './projectReducer';
import { INITIAL_PROJECT_STATE, projectReducer } from './projectReducer';

interface ProjectContextValue {
  state: ProjectState;
  dispatch: (action: ProjectAction) => void;
  /** Append a chapter. The caller decides whether to open it. */
  createChapter: (title?: string) => Promise<Document>;
  /** Rename any chapter. The open one is renamed through `DocumentContext` instead. */
  renameChapter: (documentId: string, title: string) => Promise<void>;
  /**
   * Rewrite the whole chapter order.
   *
   * Takes the complete list, because that completeness is the server's concurrency guard: a
   * client working from a stale chapter list cannot present a complete set (P2-2).
   */
  reorderChapters: (documentIds: string[]) => Promise<void>;
  /** Soft-delete a chapter. Recoverable, and its anchors go `orphaned` rather than away. */
  deleteChapter: (documentId: string) => Promise<DocumentMeta>;
  /** Bring a soft-deleted chapter back, at the end of the order. */
  restoreChapter: (documentId: string) => Promise<DocumentMeta>;
  /** Read the list of soft-deleted chapters. Not loaded until something asks. */
  loadDeleted: () => Promise<void>;
  /**
   * Create chapters from a Markdown file (P2-14).
   *
   * Appends; it never replaces a chapter's text, so nothing open can be pulled out from
   * under the editor and no flush is needed first. What came back is returned as well as
   * dispatched, because the caller has to show what the import could not keep.
   */
  importMarkdown: (markdown: string, mode: ImportMode, title?: string) => Promise<MarkdownImport>;
  /**
   * Where a chapter's Markdown lives, and where the whole manuscript's does (P2-13).
   *
   * Addresses rather than fetches: the export is served as an attachment, so the control
   * for one is a link and the browser does the saving and the naming. They are on the
   * context so that no panel has to rebuild an API path of its own.
   */
  chapterMarkdownUrl: (documentId: string) => string;
  manuscriptMarkdownUrl: () => string;
  /** Point an anchor at a new range — a suggestion accepted, or a passage chosen by hand. */
  relinkAnchor: (anchorId: string, range: AnchorRange) => Promise<void>;
  /** Change an anchor's label. Not a text change, so no version is presented for it. */
  labelAnchor: (anchorId: string, label: string) => Promise<void>;
  /** Remove an anchor. The only way one ever goes away. */
  removeAnchor: (anchorId: string) => Promise<void>;
  /** Start a manual re-link: the writer selects a passage and confirms it in the editor. */
  armRelink: (anchorId: string) => void;
  cancelRelink: () => void;
  /** Re-read the project, its chapters, the outline, and its anchors from the server. */
  reload: () => void;
}

const ProjectContext = createContext<ProjectContextValue | null>(null);

export interface ProjectProviderProps {
  client: ApiClient;
  projectId: string;
  children: ReactNode;
}

export function ProjectProvider({ client, projectId, children }: ProjectProviderProps) {
  const [state, dispatch] = useReducer(projectReducer, INITIAL_PROJECT_STATE);
  const [attempt, retry] = useReducer((count: number) => count + 1, 0);

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: 'load-requested' });

    void (async () => {
      try {
        const [detail, outline, anchors] = await Promise.all([
          client.getProject(projectId, controller.signal),
          client.getOutline(projectId, controller.signal),
          client.listProjectAnchors(projectId, undefined, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        dispatch({
          type: 'loaded',
          detail,
          chapters: outline.chapters,
          anchors: anchors.anchors,
        });
      } catch (error: unknown) {
        if (controller.signal.aborted) return;
        dispatch({ type: 'load-failed', message: describeFailure(error) });
      }
    })();

    return () => controller.abort();
  }, [client, projectId, attempt]);

  const createChapter = useCallback(
    async (title?: string): Promise<Document> => {
      const created = await client.createDocument(projectId, title);
      dispatch({ type: 'document-created', document: created });
      return created;
    },
    [client, projectId],
  );

  const renameChapter = useCallback(
    async (documentId: string, title: string): Promise<void> => {
      const meta = await client.renameDocument(documentId, title);
      dispatch({ type: 'document-renamed', documentId, title: meta.title });
    },
    [client],
  );

  const importMarkdown = useCallback(
    async (markdown: string, mode: ImportMode, title?: string): Promise<MarkdownImport> => {
      const result = await client.importMarkdown(projectId, markdown, mode, title);
      dispatch({ type: 'documents-imported', documents: result.documents });
      return result;
    },
    [client, projectId],
  );

  const chapterMarkdownUrl = useCallback(
    (documentId: string) => client.documentMarkdownUrl(documentId),
    [client],
  );

  const manuscriptMarkdownUrl = useCallback(
    () => client.projectMarkdownUrl(projectId),
    [client, projectId],
  );

  const reorderChapters = useCallback(
    async (documentIds: string[]): Promise<void> => {
      const listed = await client.reorderDocuments(projectId, documentIds);
      dispatch({ type: 'documents-reordered', documents: listed.documents });
    },
    [client, projectId],
  );

  const deleteChapter = useCallback(
    async (documentId: string): Promise<DocumentMeta> => {
      const meta = await client.deleteDocument(documentId);
      dispatch({ type: 'document-deleted', meta });
      return meta;
    },
    [client],
  );

  const restoreChapter = useCallback(
    async (documentId: string): Promise<DocumentMeta> => {
      const meta = await client.restoreDocument(documentId);
      // Its anchors were reading as `orphaned` because the chapter was away, and underneath that
      // each holds `ok` or `stale` — which of the two is the server's to say, so it is asked
      // rather than guessed. Both dispatches land in one continuation, so the panel never draws
      // the moment in between.
      const anchors = await client
        .listDocumentAnchors(documentId)
        .then((listed) => listed.anchors)
        .catch(() => null);
      dispatch({ type: 'document-restored', meta });
      if (anchors !== null) {
        dispatch({ type: 'anchors-resolved', documentId, anchors });
      }
      return meta;
    },
    [client],
  );

  const loadDeleted = useCallback(async (): Promise<void> => {
    const listed = await client.listDeletedDocuments(projectId);
    dispatch({ type: 'deleted-loaded', documents: listed.documents });
  }, [client, projectId]);

  const relinkAnchor = useCallback(
    async (anchorId: string, range: AnchorRange): Promise<void> => {
      // Accepting a suggestion and picking a passage by hand are the same request: a range and
      // the version it was chosen against. Nothing repairs itself (§ 2, ruling 2).
      const anchor = await client.patchAnchor(anchorId, { range });
      dispatch({ type: 'anchor-changed', anchor });
    },
    [client],
  );

  const labelAnchor = useCallback(
    async (anchorId: string, label: string): Promise<void> => {
      const anchor = await client.patchAnchor(anchorId, { label });
      dispatch({ type: 'anchor-changed', anchor });
    },
    [client],
  );

  const removeAnchor = useCallback(
    async (anchorId: string): Promise<void> => {
      await client.deleteAnchor(anchorId);
      dispatch({ type: 'anchor-removed', anchorId });
    },
    [client],
  );

  const armRelink = useCallback(
    (anchorId: string) => dispatch({ type: 'relink-armed', anchorId }),
    [],
  );
  const cancelRelink = useCallback(() => dispatch({ type: 'relink-cancelled' }), []);

  const value = useMemo<ProjectContextValue>(
    () => ({
      state,
      dispatch,
      createChapter,
      renameChapter,
      importMarkdown,
      chapterMarkdownUrl,
      manuscriptMarkdownUrl,
      reorderChapters,
      deleteChapter,
      restoreChapter,
      loadDeleted,
      relinkAnchor,
      labelAnchor,
      removeAnchor,
      armRelink,
      cancelRelink,
      reload: retry,
    }),
    [
      state,
      createChapter,
      renameChapter,
      importMarkdown,
      chapterMarkdownUrl,
      manuscriptMarkdownUrl,
      reorderChapters,
      deleteChapter,
      restoreChapter,
      loadDeleted,
      relinkAnchor,
      labelAnchor,
      removeAnchor,
      armRelink,
      cancelRelink,
    ],
  );
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProject(): ProjectContextValue {
  const value = useContext(ProjectContext);
  if (!value) {
    throw new Error('useProject must be used inside a ProjectProvider');
  }
  return value;
}

/** The sentence to show a person when a request did not work out. */
export function describeFailure(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof NetworkError) {
    return 'the server could not be reached';
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
