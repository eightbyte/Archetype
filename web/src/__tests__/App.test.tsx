/**
 * The shell renders, and reports honestly what it can and cannot reach.
 *
 * Written in P1-1 against a locally stubbed `fetch`, with a note that it would move to the
 * hand-written fake API client when P1-8 brought one. This is that move: the assertions are the
 * same, the stand-in is now the typed fake, and the last direct use of `fetch` in a component
 * test is gone. `client.test.ts` is where `fetch` itself is exercised.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { expect, test } from 'vitest';
import { NetworkError } from '../api';
import { App } from '../App';
import { FakeApiClient } from './fakes/fakeApiClient';

test('renders the application name', () => {
  render(<App client={new FakeApiClient()} />);
  expect(screen.getByRole('heading', { name: 'Archetype' })).toBeDefined();
});

test('reports the server version once health answers', async () => {
  render(<App client={new FakeApiClient({ version: '0.1.0' })} />);

  await waitFor(() => {
    expect(screen.getByTestId('server-status').textContent).toBe('Server ok — version 0.1.0');
  });
});

test('says so plainly when the server cannot be reached', async () => {
  const client = new FakeApiClient();
  client.failNext('health', new NetworkError('GET /api/health could not reach the server', null));

  render(<App client={client} />);

  await waitFor(() => {
    expect(screen.getByTestId('server-status').textContent).toContain('Server unreachable');
  });
});

test('the project list only appears once the server has answered', async () => {
  const client = new FakeApiClient({ projects: ['The Long Road'] });

  render(<App client={client} />);

  expect(screen.queryByRole('heading', { name: 'Projects' })).toBeNull();
  await waitFor(() => {
    expect(screen.getByText('The Long Road')).toBeDefined();
  });
});

test('an unreachable server shows no project list to mislead with', async () => {
  const client = new FakeApiClient({ projects: ['The Long Road'] });
  client.failNext('health', new NetworkError('could not reach the server', null));

  render(<App client={client} />);

  await waitFor(() => {
    expect(screen.getByTestId('server-status').textContent).toContain('Server unreachable');
  });
  expect(screen.queryByRole('heading', { name: 'Projects' })).toBeNull();
});
