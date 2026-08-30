/**
 * P1-1 - the frontend toolchain works end to end: TSX compiles, jsdom renders, effects settle.
 *
 * The fetch stub here is deliberately local. It is not the hand-written typed fake API client
 * from P1-8 - that arrives with the routes it needs to fake.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { App } from '../App';

function stubFetch(responder: () => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(responder));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test('renders the application name', () => {
  stubFetch(() => new Promise<Response>(() => {}));
  render(<App />);
  expect(screen.getByRole('heading', { name: 'Archetype' })).toBeDefined();
});

test('reports the server version once health answers', async () => {
  stubFetch(async () => new Response(JSON.stringify({ status: 'ok', version: '0.1.0' })));
  render(<App />);

  await waitFor(() => {
    expect(screen.getByTestId('server-status').textContent).toBe('Server ok — version 0.1.0');
  });
});

test('says so plainly when the server cannot be reached', async () => {
  stubFetch(async () => {
    throw new Error('connection refused');
  });
  render(<App />);

  await waitFor(() => {
    expect(screen.getByTestId('server-status').textContent).toContain('Server unreachable');
  });
});

test('a failing status code is an error, not a silent success', async () => {
  stubFetch(async () => new Response('nope', { status: 500 }));
  render(<App />);

  await waitFor(() => {
    expect(screen.getByTestId('server-status').textContent).toContain('500');
  });
});
