/**
 * P1-8 — a real component test backed by the hand-written fake client.
 *
 * The point of this test is as much the wiring as the component: it proves the fake satisfies the
 * same interface the real client does, which is what makes every later component test (the
 * editor, the TOC, the picker) trustworthy.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { ApiError, NetworkError } from '../api';
import { ProjectList } from '../panels/ProjectList';
import { FakeApiClient } from './fakes/fakeApiClient';

describe('the project list', () => {
  test('renders the projects the server reports', async () => {
    const client = new FakeApiClient({ projects: ['The Long Road', 'Test Manuscript'] });

    render(<ProjectList client={client} />);

    await waitFor(() => {
      expect(screen.getByText('The Long Road')).toBeDefined();
    });
    expect(screen.getByText('Test Manuscript')).toBeDefined();
    expect(client.calls).toEqual(['listProjects']);
  });

  test('a project reports its chapter and word counts', async () => {
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');
    const [documentId] = client.documentIdsOf(projectId);
    await client.saveDocumentContent(documentId!, prose('The harbour was grey.'), 1);

    render(<ProjectList client={client} />);

    await waitFor(() => {
      expect(screen.getByText(/1 chapter · 4 words/)).toBeDefined();
    });
  });

  test('an empty workspace says so rather than rendering nothing', async () => {
    render(<ProjectList client={new FakeApiClient()} />);

    await waitFor(() => {
      expect(screen.getByTestId('projects-status').textContent).toBe('No projects yet.');
    });
  });

  test('a file the server could not read is reported beside the list, not instead of it', async () => {
    const client = new FakeApiClient({ projects: ['Readable'] });
    client.seedSkipped({ name: 'junk.sqlite', reason: 'unreadable', detail: 'file is not a database' });

    render(<ProjectList client={client} />);

    await waitFor(() => {
      expect(screen.getByText('Readable')).toBeDefined();
    });
    expect(screen.getByTestId('projects-skipped').textContent).toContain('junk.sqlite');
    expect(screen.getByTestId('projects-skipped').textContent).toContain('unreadable');
  });

  test('a failing request says so instead of showing an empty workspace', async () => {
    const client = new FakeApiClient({ projects: ['The Long Road'] });
    client.failNext('listProjects', new NetworkError('could not reach the server', null));

    render(<ProjectList client={client} />);

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('Could not load projects');
    });
    expect(screen.queryByText('The Long Road')).toBeNull();
  });

  test('a server error surfaces the envelope message', async () => {
    const client = new FakeApiClient();
    client.failNext('listProjects', new ApiError(500, 'internal_error', 'the server failed', null));

    render(<ProjectList client={client} />);

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('the server failed');
    });
  });
});

describe('the fake itself', () => {
  test('a save at the wrong version is refused the way the server refuses it (D19)', async () => {
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');
    const [documentId] = client.documentIdsOf(projectId);
    await client.saveDocumentContent(documentId!, prose('First.'), 1);

    const failure = await client
      .saveDocumentContent(documentId!, prose('Clobbered.'), 1)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).isVersionConflict).toBe(true);
    expect((failure as ApiError).versionConflict?.current_version).toBe(2);
    expect(client.versionOf(documentId!)).toBe(2);
    expect((await client.getDocument(documentId!)).content_json).toEqual(prose('First.'));
  });

  test('a rename does not move the version', async () => {
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');
    const [documentId] = client.documentIdsOf(projectId);

    const meta = await client.renameDocument(documentId!, 'Arrival');

    expect(meta.title).toBe('Arrival');
    expect(meta.version).toBe(1);
  });

  test('creating a document appends it', async () => {
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');

    const created = await client.createDocument(projectId, 'Departure');

    expect(created.order_index).toBe(1);
    expect((await client.listDocuments(projectId)).documents.map((doc) => doc.title)).toEqual([
      'Chapter 1',
      'Departure',
    ]);
  });

  test('an unknown project is a 404 with the same code the server uses', async () => {
    const failure = await new FakeApiClient()
      .getProject('prj_nope')
      .catch((error: unknown) => error);

    expect((failure as ApiError).status).toBe(404);
    expect((failure as ApiError).code).toBe('project_not_found');
  });
});

function prose(text: string) {
  return {
    type: 'doc' as const,
    content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
  };
}
