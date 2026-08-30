/**
 * The one call the Group A frontend makes (P1-1).
 *
 * It exists to prove the toolchain end to end: the dev server proxies `/api` to uvicorn, and the
 * built app served from the same process reaches the same route. The typed API client proper -
 * and the hand-written fake that backs the component tests - is P1-8.
 */

export interface Health {
  status: string;
  version: string;
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch('/api/health', signal ? { signal } : undefined);
  if (!response.ok) {
    throw new Error(`GET /api/health returned ${response.status}`);
  }
  return (await response.json()) as Health;
}
