/**
 * Vitest setup (P1-1).
 *
 * Unmounts React trees between tests so a component's effects cannot leak into the next one.
 * The typed fake API client and the contract-fixture checks land in P1-8.
 */

import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});
