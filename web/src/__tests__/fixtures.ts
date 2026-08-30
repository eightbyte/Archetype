/**
 * Reading the backend's shared fixtures from the frontend suite (P1-7, P1-8).
 *
 * Two fixture sets are deliberately shared across the two suites rather than duplicated:
 * `projection/cases.json`, which specifies what both projections must do (D18), and `contract/`,
 * which is what makes a wire-shape change fail the tests instead of the browser. Duplicating
 * either would defeat the point — a copy can be updated on one side only.
 *
 * Paths resolve from the working directory rather than from `import.meta.url`: under Vitest the
 * module URL is not a `file:` URL, so `fileURLToPath` cannot be used here. `npm test` runs from
 * `web/`, which is where the Vite config lives and therefore what Vitest makes the working
 * directory. If that ever stops being true, `serverFixture` says so plainly rather than failing
 * with a bare ENOENT.
 */

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SERVER_FIXTURES = resolve(process.cwd(), '..', 'server', 'tests', 'fixtures');

/** The absolute path of a fixture under `server/tests/fixtures/`. */
export function serverFixture(relativePath: string): string {
  const path = resolve(SERVER_FIXTURES, relativePath);
  if (!existsSync(path)) {
    throw new Error(
      `shared fixture not found: ${path}\n` +
        `(resolved from ${process.cwd()}; run the frontend suite from web/, and run the ` +
        `backend suite first if the contract fixtures have never been written)`,
    );
  }
  return path;
}

/** Parse a shared fixture as JSON. */
export function readServerFixture<T>(relativePath: string): T {
  return JSON.parse(readFileSync(serverFixture(relativePath), 'utf-8')) as T;
}
