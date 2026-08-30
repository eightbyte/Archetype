/**
 * P1-12 — the entry screen.
 *
 * Three of these are the acceptance bar: creating a project lands in a writable editor, a
 * project that appeared in the directory without this app's help is simply listed (D17), and a
 * file that could not be read is reported beside the list rather than instead of it.
 *
 * They run against the whole `App`, not the picker alone, because "opens into an editor" is a
 * claim about the two screens together.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { ApiError, NetworkError } from '../api';
import { App } from '../App';
import { ProjectPicker } from '../panels/ProjectPicker';
import { STORAGE_KEYS } from '../state/persistence';
import { FakeApiClient } from './fakes/fakeApiClient';

describe('creating a project', () => {
  test('opens into an editor with one chapter already in it', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient();

    render(<App client={client} />);
    await screen.findByRole('heading', { name: 'Projects' });

    await user.type(screen.getByLabelText('New project'), 'Test Manuscript');
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    // The workspace, on a real chapter, with a writing surface.
    await screen.findByRole('heading', { name: 'Test Manuscript' });
    expect(screen.getByRole('button', { name: 'Rename Chapter 1' })).toBeDefined();
    await waitFor(() => {
      expect(document.querySelector('.manuscript')).not.toBeNull();
    });
  });

  test('an empty title is not a project', async () => {
    const user = userEvent.setup();
    render(<App client={new FakeApiClient()} />);
    await screen.findByRole('heading', { name: 'Projects' });

    const create = screen.getByRole('button', { name: 'Create project' });
    expect(create.hasAttribute('disabled')).toBe(true);

    await user.type(screen.getByLabelText('New project'), '   ');
    expect(create.hasAttribute('disabled')).toBe(true);
  });

  test('a failure to create says so and stays on the picker', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient();
    client.failNext('createProject', new ApiError(500, 'internal_error', 'the disk is full', null));

    render(<App client={client} />);
    await screen.findByRole('heading', { name: 'Projects' });

    await user.type(screen.getByLabelText('New project'), 'Doomed');
    await user.click(screen.getByRole('button', { name: 'Create project' }));

    expect((await screen.findByRole('alert')).textContent).toContain('the disk is full');
    expect(screen.getByRole('heading', { name: 'Projects' })).toBeDefined();
  });
});

describe('the list', () => {
  test('shows a project that appeared without this app creating it (D17)', async () => {
    // The store scans the directory, so a file copied in from a backup is simply there.
    const client = new FakeApiClient();
    client.seedProject('Restored From Backup');

    render(<App client={client} />);

    expect(await screen.findByText('Restored From Backup')).toBeDefined();
  });

  test('reports a file it could not read beside the list, not instead of it', async () => {
    const client = new FakeApiClient({ projects: ['Readable'] });
    client.seedSkipped({
      name: 'notes.sqlite',
      reason: 'not an archetype project',
      detail: 'no project table',
    });

    render(<App client={client} />);

    expect(await screen.findByText('Readable')).toBeDefined();
    const skipped = screen.getByTestId('projects-skipped');
    expect(skipped.textContent).toContain('notes.sqlite');
    expect(skipped.textContent).toContain('not an archetype project');
  });

  test('says when the server is unreachable rather than showing an empty workspace', async () => {
    const client = new FakeApiClient({ projects: ['The Long Road'] });
    client.failNext('health', new NetworkError('could not reach the server', null));

    render(<App client={client} />);

    await waitFor(() => {
      expect(screen.getByTestId('server-status').textContent).toContain('Server unreachable');
    });
    expect(screen.queryByRole('heading', { name: 'Projects' })).toBeNull();
  });

  test('shows chapter count, word count, and when each was last touched', async () => {
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');
    const [documentId] = client.documentIdsOf(projectId);
    await client.saveDocumentContent(
      documentId!,
      { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'One two three.' }] }] },
      1,
    );

    render(<App client={client} />);

    const row = await screen.findByRole('button', { name: /The Long Road/ });
    expect(row.textContent).toContain('1 chapter');
    expect(row.textContent).toContain('3 words');
    expect(within(row).getByText((_, node) => node?.tagName === 'TIME')).toBeDefined();
  });

  test('a project opens when its row is clicked', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient({ projects: ['The Long Road'] });

    render(<App client={client} />);
    await user.click(await screen.findByRole('button', { name: /The Long Road/ }));

    await screen.findByRole('heading', { name: 'The Long Road' });
  });
});

describe('the recent shortcut', () => {
  test('offers a project that was opened before, and opens it', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');
    client.seedProject('Another Book');
    localStorage.setItem(STORAGE_KEYS.recentProjects, JSON.stringify([projectId]));

    render(<App client={client} />);

    const recent = await screen.findByRole('navigation', { name: 'Recently opened' });
    expect(within(recent).getAllByRole('button')).toHaveLength(1);

    await user.click(within(recent).getByRole('button', { name: 'The Long Road' }));
    await screen.findByRole('heading', { name: 'The Long Road' });
  });

  test('an id whose project is gone is silently not offered', async () => {
    const client = new FakeApiClient({ projects: ['The Long Road'] });
    localStorage.setItem(
      STORAGE_KEYS.recentProjects,
      JSON.stringify(['prj_deleted', 'prj_moved']),
    );

    render(<App client={client} />);
    await screen.findByText('The Long Road');

    expect(screen.queryByRole('navigation', { name: 'Recently opened' })).toBeNull();
  });

  test('a stored value that is not a list of ids is ignored', async () => {
    localStorage.setItem(STORAGE_KEYS.recentProjects, '"not an array"');
    const client = new FakeApiClient({ projects: ['The Long Road'] });

    render(<App client={client} />);

    expect(await screen.findByText('The Long Road')).toBeDefined();
  });
});

describe('the picker on its own', () => {
  test('reports the server version once health answers', async () => {
    render(
      <ProjectPicker client={new FakeApiClient({ version: '9.9.9' })} onOpen={() => {}} />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('server-status').textContent).toBe('Server ok — version 9.9.9');
    });
  });

  test('an empty workspace says so rather than rendering nothing', async () => {
    render(<ProjectPicker client={new FakeApiClient()} onOpen={() => {}} />);

    await waitFor(() => {
      expect(screen.getByTestId('projects-status').textContent).toBe('No projects yet.');
    });
  });
});
