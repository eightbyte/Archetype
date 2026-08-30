/**
 * The list of projects on this machine (P1-8, grown into the picker's list in P1-12).
 *
 * It reads `GET /api/projects`, which scans the projects directory rather than consulting a
 * registry (D17) — so a project file copied in from a backup is simply there, and a file that is
 * not a project is reported beside the list instead of taking it down. Both of those are
 * properties of the store, and this is where a person finds out about them.
 *
 * Sorted by when each was last touched, most recent first, because the project a writer wants is
 * almost always the one they were last in.
 */

import { useEffect, useRef, useState } from 'react';
import type { ApiClient, ProjectList as ProjectListBody, ProjectSummary } from '../api';
import { ApiError } from '../api';
import { formatDateTime, formatRelativeTime, plural } from '../format';

type State =
  | { kind: 'loading' }
  | { kind: 'loaded'; body: ProjectListBody }
  | { kind: 'failed'; message: string };

export interface ProjectListProps {
  client: ApiClient;
  /** Open a project. Without it the list is read-only, which is all Group B needed. */
  onOpen?: (projectId: string) => void;
  /** Ids to mark as recently opened (P1-12). */
  recentIds?: readonly string[];
  /** Changing this re-reads the list — used after a project is created. */
  reloadToken?: number;
  /** Told what came back, so a caller need not fetch the same list a second time. */
  onLoaded?: (body: ProjectListBody) => void;
}

export function ProjectList({
  client,
  onOpen,
  recentIds = [],
  reloadToken = 0,
  onLoaded,
}: ProjectListProps) {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const report = useRef(onLoaded);
  report.current = onLoaded;

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: 'loading' });
    client
      .listProjects(controller.signal)
      .then((body) => {
        if (controller.signal.aborted) return;
        setState({ kind: 'loaded', body });
        report.current?.(body);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: 'failed', message: describeFailure(error) });
      });
    return () => controller.abort();
  }, [client, reloadToken]);

  if (state.kind === 'loading') {
    return (
      <section aria-labelledby="projects-heading">
        <h2 id="projects-heading">Projects</h2>
        <p data-testid="projects-status">Loading projects…</p>
      </section>
    );
  }

  if (state.kind === 'failed') {
    return (
      <section aria-labelledby="projects-heading">
        <h2 id="projects-heading">Projects</h2>
        <p data-testid="projects-status" role="alert">
          Could not load projects — {state.message}
        </p>
      </section>
    );
  }

  const { skipped } = state.body;
  const projects = byMostRecent(state.body.projects);
  const recent = new Set(recentIds);

  return (
    <section aria-labelledby="projects-heading">
      <h2 id="projects-heading">Projects</h2>

      {projects.length === 0 ? (
        <p data-testid="projects-status">No projects yet.</p>
      ) : (
        <ul className="project-list">
          {projects.map((project) => (
            <li key={project.id}>
              <ProjectRow project={project} onOpen={onOpen} recent={recent.has(project.id)} />
            </li>
          ))}
        </ul>
      )}

      {skipped.length > 0 && (
        <p className="project-skipped" data-testid="projects-skipped">
          {plural(skipped.length, 'file')} in the projects folder could not be read:{' '}
          {skipped.map((file) => `${file.name} (${file.reason})`).join(', ')}.
        </p>
      )}
    </section>
  );
}

interface ProjectRowProps {
  project: ProjectSummary;
  recent: boolean;
  onOpen?: ((projectId: string) => void) | undefined;
}

function ProjectRow({ project, recent, onOpen }: ProjectRowProps) {
  const meta = (
    <span className="project-meta">
      {plural(project.chapter_count, 'chapter')} · {plural(project.word_count, 'word')} ·{' '}
      <time dateTime={project.updated_at} title={formatDateTime(project.updated_at)}>
        {formatRelativeTime(project.updated_at)}
      </time>
    </span>
  );

  if (!onOpen) {
    return (
      <>
        <span className="project-title">{project.title}</span>
        {meta}
      </>
    );
  }

  return (
    <button type="button" className="project-open" onClick={() => onOpen(project.id)}>
      <span className="project-title">{project.title}</span>
      {recent && <span className="project-recent">recent</span>}
      {meta}
    </button>
  );
}

/** Most recently touched first. A project's `updated_at` moves when any of its chapters does. */
function byMostRecent(projects: readonly ProjectSummary[]): ProjectSummary[] {
  return [...projects].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

function describeFailure(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
