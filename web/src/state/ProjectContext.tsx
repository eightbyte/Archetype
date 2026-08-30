/**
 * The open project (P1-9, D10).
 *
 * Loads the project, its chapter list, and the stitched outline in one pass, and holds them for
 * as long as that project is open. Two requests rather than one: `GET /api/projects/{pid}` for
 * identity and the chapter list, `GET /api/projects/{pid}/outline` for the headings. The outline
 * route reads only derived columns, so the whole manuscript's table of contents is drawn without
 * loading a single chapter's content (D2, D18).
 *
 * `dispatch` is deliberately exposed: the document layer nests inside this one and tells it when
 * a save landed, so the table of contents for the *other* chapters stays true without refetching
 * the outline on every keystroke.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer } from 'react';
import type { ReactNode } from 'react';
import type { ApiClient, Document } from '../api';
import { ApiError, NetworkError } from '../api';
import type { ProjectAction, ProjectState } from './projectReducer';
import { INITIAL_PROJECT_STATE, projectReducer } from './projectReducer';

interface ProjectContextValue {
  state: ProjectState;
  dispatch: (action: ProjectAction) => void;
  /** Append a chapter. The caller decides whether to open it. */
  createChapter: (title?: string) => Promise<Document>;
  /** Re-read the project, its chapters, and the outline from the server. */
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
        const [detail, outline] = await Promise.all([
          client.getProject(projectId, controller.signal),
          client.getOutline(projectId, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        dispatch({ type: 'loaded', detail, chapters: outline.chapters });
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

  const value = useMemo<ProjectContextValue>(
    () => ({ state, dispatch, createChapter, reload: retry }),
    [state, createChapter],
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
