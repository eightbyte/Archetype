/**
 * The application shell — still a placeholder (P1-1, extended in P1-8).
 *
 * The three-region workspace (outline panel, editor, agent panel) with resizable dividers and
 * persisted pane widths is P1-9; the editor is P1-10; the picker proper is P1-12. This renders
 * only what Group B has actually built: whether the server answers, and what is in the projects
 * directory — enough to confirm by hand that the API, the store, and the client all work
 * together.
 */

import { useEffect, useMemo, useState } from 'react';
import type { ApiClient } from './api';
import { createApiClient } from './api';
import { ProjectList } from './panels/ProjectList';

type ServerState =
  | { kind: 'checking' }
  | { kind: 'ok'; version: string }
  | { kind: 'unreachable'; message: string };

export interface AppProps {
  /** Injected by tests; the real app builds its own. */
  client?: ApiClient;
}

export function App({ client }: AppProps = {}) {
  const api = useMemo(() => client ?? createApiClient(), [client]);
  const [server, setServer] = useState<ServerState>({ kind: 'checking' });

  useEffect(() => {
    const controller = new AbortController();
    api
      .health(controller.signal)
      .then((health) => setServer({ kind: 'ok', version: health.version }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setServer({ kind: 'unreachable', message: describe(error) });
      });
    return () => controller.abort();
  }, [api]);

  return (
    <main className="shell">
      <h1>Archetype</h1>
      <p className="tagline">A workspace for writing and maintaining a long narrative.</p>
      <p data-testid="server-status">{describeServer(server)}</p>

      {server.kind === 'ok' && <ProjectList client={api} />}

      <p className="phase">
        Phase 1, Group B — the API, the save protocol, and the text projection. The editor arrives
        in P1-10.
      </p>
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

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
