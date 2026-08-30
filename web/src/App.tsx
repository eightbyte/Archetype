/**
 * Placeholder shell (P1-1).
 *
 * The three-region workspace - outline panel, editor, agent panel - with resizable dividers and
 * persisted pane widths is P1-9. This is deliberately not that: it renders enough to confirm the
 * dev server, the `/api` proxy, and the test harness all work, and nothing more.
 */

import { useEffect, useState } from 'react';
import { fetchHealth } from './health';

type ServerState =
  | { kind: 'checking' }
  | { kind: 'ok'; version: string }
  | { kind: 'unreachable'; message: string };

export function App() {
  const [server, setServer] = useState<ServerState>({ kind: 'checking' });

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((health) => setServer({ kind: 'ok', version: health.version }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setServer({ kind: 'unreachable', message: String(error) });
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="shell">
      <h1>Archetype</h1>
      <p className="tagline">A workspace for writing and maintaining a long narrative.</p>
      <p data-testid="server-status">{describe(server)}</p>
      <p className="phase">Phase 1, Group A — foundations. The editor arrives in P1-10.</p>
    </main>
  );
}

function describe(server: ServerState): string {
  switch (server.kind) {
    case 'checking':
      return 'Contacting the server…';
    case 'ok':
      return `Server ok — version ${server.version}`;
    case 'unreachable':
      return `Server unreachable — ${server.message}`;
  }
}
