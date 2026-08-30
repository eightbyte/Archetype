/**
 * The entry screen (P1-12, D6).
 *
 * Projects are project-scoped from day one, so there is a picker from day one: every route,
 * table, and panel below this screen already takes a project as its scope, and nothing has to be
 * retrofitted when a second project appears.
 *
 * Creating a project opens it immediately, and it opens into a writable editor rather than an
 * empty state — the server seeds one chapter as part of `POST /api/projects` (P1-5), so that is
 * true for any client, not just this one.
 *
 * The health check is here rather than deeper in: a list that renders empty because the server
 * is not running looks exactly like a list that is empty, and one of those is a lie. Nothing
 * about the workspace is shown until the server has answered.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import type { ApiClient, ProjectList as ProjectListBody } from '../api';
import { ProjectList } from './ProjectList';
import { describeFailure } from '../state/ProjectContext';

type ServerState =
  | { kind: 'checking' }
  | { kind: 'ok'; version: string }
  | { kind: 'unreachable'; message: string };

export interface ProjectPickerProps {
  client: ApiClient;
  onOpen: (projectId: string) => void;
  /** Ids of projects opened recently, most recent first (P1-12). */
  recentIds?: readonly string[];
}

export function ProjectPicker({ client, onOpen, recentIds = [] }: ProjectPickerProps) {
  const [server, setServer] = useState<ServerState>({ kind: 'checking' });
  const [title, setTitle] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [known, setKnown] = useState<Map<string, string>>(new Map());

  useEffect(() => {
    const controller = new AbortController();
    client
      .health(controller.signal)
      .then((health) => setServer({ kind: 'ok', version: health.version }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setServer({ kind: 'unreachable', message: describeFailure(error) });
      });
    return () => controller.abort();
  }, [client]);

  // Titles for the recent-projects shortcut, taken from the list the component below already
  // fetched rather than asking for it twice. The ids come from this browser's storage and the
  // titles from the server, so an id whose project has been deleted or moved simply does not
  // appear — the shortcut can never offer something that is not there.
  const noteProjects = useCallback((body: ProjectListBody) => {
    setKnown(new Map(body.projects.map((project) => [project.id, project.title])));
  }, []);

  const recent = useMemo(
    () =>
      recentIds
        .map((id) => ({ id, title: known.get(id) }))
        .filter((entry): entry is { id: string; title: string } => entry.title !== undefined),
    [recentIds, known],
  );

  const create = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      const trimmed = title.trim();
      if (trimmed.length === 0 || creating) {
        return;
      }
      setCreating(true);
      setCreateError(null);
      try {
        const detail = await client.createProject(trimmed);
        setTitle('');
        setReloadToken((token) => token + 1);
        onOpen(detail.project.id);
      } catch (error: unknown) {
        setCreateError(describeFailure(error));
      } finally {
        setCreating(false);
      }
    },
    [client, creating, onOpen, title],
  );

  return (
    <main className="picker">
      <h1>Archetype</h1>
      <p className="tagline">A workspace for writing and maintaining a long narrative.</p>
      <p data-testid="server-status" className="server-status">
        {describeServer(server)}
      </p>

      {server.kind === 'ok' && (
        <>
          {recent.length > 0 && (
            <nav className="recent" aria-label="Recently opened">
              <span className="recent-label">Recent</span>
              {recent.map((entry) => (
                <button key={entry.id} type="button" onClick={() => onOpen(entry.id)}>
                  {entry.title}
                </button>
              ))}
            </nav>
          )}

          <form className="create-project" onSubmit={(event) => void create(event)}>
            <label htmlFor="new-project-title">New project</label>
            <input
              id="new-project-title"
              value={title}
              placeholder="Working title"
              onChange={(event) => setTitle(event.target.value)}
            />
            <button type="submit" disabled={creating || title.trim().length === 0}>
              {creating ? 'Creating…' : 'Create project'}
            </button>
          </form>

          {createError !== null && (
            <p className="create-error" role="alert">
              Could not create the project — {createError}
            </p>
          )}

          <ProjectList
            client={client}
            onOpen={onOpen}
            recentIds={recentIds}
            reloadToken={reloadToken}
            onLoaded={noteProjects}
          />
        </>
      )}
    </main>
  );
}

function describeServer(server: ServerState): string {
  switch (server.kind) {
    case 'checking':
      return 'Contacting the server…';
    case 'ok':
      return `Server ok — version ${server.version}`;
    case 'unreachable':
      return `Server unreachable — ${server.message}`;
  }
}
