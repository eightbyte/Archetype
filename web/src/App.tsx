/**
 * The application: the picker, or a project (P1-9, P1-12).
 *
 * There is no router — none is in the dependency budget, and a single-user localhost workspace
 * with two screens does not need one — so which of the two is showing is state. The open project
 * is persisted, so a reload lands the writer back in the manuscript they were in rather than
 * back at the front door. Getting out is the *Projects* control in the workspace header, which
 * flushes before it leaves.
 *
 * The provider order is the lifetime order: toasts and layout outlive everything, a project
 * outlives the documents inside it, and a document is innermost (D10). Remounting
 * `ProjectProvider` on a different project id is deliberate — everything scoped to a project,
 * including the open chapter, should be gone when the project is.
 *
 * `BibleProvider` joins that order in Phase 3, between the project and the document (P3-12): an
 * entry's lifetime is the project's, exactly as an anchor's is, and putting it inside the
 * document layer would make the bible something that resets when a chapter is opened. Being an
 * ancestor of the document layer is also what lets the editor's *Add to bible* tell it that an
 * entry now exists.
 */

import { useCallback, useMemo, useState } from 'react';
import type { ApiClient } from './api';
import { createApiClient } from './api';
import { ProjectPicker } from './panels/ProjectPicker';
import { DocumentProvider } from './state/DocumentContext';
import {
  clearStored,
  readStored,
  reviveString,
  reviveStringArray,
  STORAGE_KEYS,
  withRecentProject,
  writeStored,
} from './state/persistence';
import { BibleProvider } from './state/BibleContext';
import { ProjectProvider } from './state/ProjectContext';
import { ToastProvider } from './state/ToastContext';
import { UiProvider } from './state/UiContext';
import { ErrorBoundary } from './shell/ErrorBoundary';
import { Toasts } from './shell/Toasts';
import { Workspace } from './shell/Workspace';

export interface AppProps {
  /** Injected by tests; the real app builds its own. */
  client?: ApiClient;
  /** Start in a project rather than at the picker. Tests use it; the browser uses storage. */
  initialProjectId?: string | null;
}

export function App({ client, initialProjectId }: AppProps = {}) {
  const api = useMemo(() => client ?? createApiClient(), [client]);

  const [projectId, setProjectId] = useState<string | null>(
    () => initialProjectId ?? readStored(STORAGE_KEYS.openProject, reviveString),
  );
  const [recentIds, setRecentIds] = useState<readonly string[]>(
    () => readStored(STORAGE_KEYS.recentProjects, reviveStringArray) ?? [],
  );

  const open = useCallback((id: string) => {
    setProjectId(id);
    writeStored(STORAGE_KEYS.openProject, id);
    setRecentIds((current) => {
      const next = withRecentProject(current, id);
      writeStored(STORAGE_KEYS.recentProjects, next);
      return next;
    });
  }, []);

  const leave = useCallback(() => {
    setProjectId(null);
    clearStored(STORAGE_KEYS.openProject);
  }, []);

  return (
    <ToastProvider>
      <UiProvider>
        <ErrorBoundary region="Archetype">
          {projectId === null ? (
            <ProjectPicker client={api} onOpen={open} recentIds={recentIds} />
          ) : (
            <ProjectProvider key={projectId} client={api} projectId={projectId}>
              <BibleProvider client={api} projectId={projectId}>
                <DocumentProvider client={api}>
                  <Workspace onLeaveProject={leave} />
                </DocumentProvider>
              </BibleProvider>
            </ProjectProvider>
          )}
        </ErrorBoundary>
        <Toasts />
      </UiProvider>
    </ToastProvider>
  );
}
