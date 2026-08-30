/**
 * The project list (P1-8, and the seed of the picker in P1-12).
 *
 * Deliberately small: it reads `GET /api/projects` through the typed client and renders what
 * came back. It exists now because P1-8 asks for at least one real component test backed by the
 * hand-written fake, and a component that only ever ran against a fake would not prove much.
 *
 * P1-12 grows this into the entry screen — create-a-project, recent projects, opening into the
 * editor. What is settled here and should survive that: a file the server could not read is
 * reported beside the list rather than replacing it (D17), and a failure to reach the server
 * says so plainly instead of rendering an empty workspace that is a lie.
 */

import { useEffect, useState } from 'react';
import type { ApiClient, ProjectList as ProjectListBody } from '../api';
import { ApiError } from '../api';

type State =
  | { kind: 'loading' }
  | { kind: 'loaded'; body: ProjectListBody }
  | { kind: 'failed'; message: string };

export interface ProjectListProps {
  client: ApiClient;
}

export function ProjectList({ client }: ProjectListProps) {
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    client
      .listProjects(controller.signal)
      .then((body) => setState({ kind: 'loaded', body }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: 'failed', message: describeFailure(error) });
      });
    return () => controller.abort();
  }, [client]);

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

  const { projects, skipped } = state.body;

  return (
    <section aria-labelledby="projects-heading">
      <h2 id="projects-heading">Projects</h2>

      {projects.length === 0 ? (
        <p data-testid="projects-status">No projects yet.</p>
      ) : (
        <ul className="project-list">
          {projects.map((project) => (
            <li key={project.id}>
              <span className="project-title">{project.title}</span>
              <span className="project-meta">
                {countOf(project.chapter_count, 'chapter')} · {project.word_count.toLocaleString()}{' '}
                {project.word_count === 1 ? 'word' : 'words'}
              </span>
            </li>
          ))}
        </ul>
      )}

      {skipped.length > 0 && (
        <p className="project-skipped" data-testid="projects-skipped">
          {countOf(skipped.length, 'file')} in the projects folder could not be read:{' '}
          {skipped.map((file) => `${file.name} (${file.reason})`).join(', ')}.
        </p>
      )}
    </section>
  );
}

function countOf(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
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
