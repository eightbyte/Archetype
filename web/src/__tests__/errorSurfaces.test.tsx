/**
 * P1-13 — what the app does when something goes wrong on this side of the wire.
 *
 * The acceptance bar is that a thrown render error in one panel leaves the other two usable.
 * That is the failure worth designing for: a panel that cannot draw while there is unsaved
 * writing in the editor beside it must not take the editor with it.
 *
 * React logs every caught error to the console, so these tests silence it and assert on the
 * boundary instead. Silencing it is deliberate and narrow — an unexpected console error in any
 * other test is still noise a developer should see.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../api';
import { ErrorBoundary } from '../shell/ErrorBoundary';
import { Toasts } from '../shell/Toasts';
import { Workspace } from '../shell/Workspace';
import { TOAST_TIMEOUT_MS, ToastProvider, useToasts } from '../state/ToastContext';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness } from './harness';

describe('a region that throws', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function Explodes(): never {
    throw new Error('the outline could not be drawn');
  }

  test('takes itself down and says which region failed', () => {
    render(
      <ErrorBoundary region="Outline">
        <Explodes />
      </ErrorBoundary>,
    );

    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('Outline');
    expect(alert.textContent).toContain('the outline could not be drawn');
  });

  test('leaves the other regions usable', async () => {
    function Panel({ label }: { label: string }) {
      return <p>{label} is fine</p>;
    }

    render(
      <>
        <ErrorBoundary region="Outline">
          <Explodes />
        </ErrorBoundary>
        <ErrorBoundary region="Manuscript">
          <Panel label="the editor" />
        </ErrorBoundary>
        <ErrorBoundary region="Assistant">
          <Panel label="the assistant" />
        </ErrorBoundary>
      </>,
    );

    expect(screen.getByRole('alert').textContent).toContain('Outline');
    expect(screen.getByText('the editor is fine')).toBeDefined();
    expect(screen.getByText('the assistant is fine')).toBeDefined();
  });

  test('offers a way to try the region again', async () => {
    const user = userEvent.setup();
    let shouldThrow = true;

    function Flaky() {
      if (shouldThrow) {
        throw new Error('not yet');
      }
      return <p>drawn</p>;
    }

    render(
      <ErrorBoundary region="Outline">
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeDefined();

    shouldThrow = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));

    expect(screen.getByText('drawn')).toBeDefined();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('reports the failure so a developer can see it', () => {
    const onError = vi.fn();
    render(
      <ErrorBoundary region="Outline" onError={onError}>
        <Explodes />
      </ErrorBoundary>,
    );
    expect(onError).toHaveBeenCalledOnce();
    expect(console.error).toHaveBeenCalled();
  });
});

describe('toasts', () => {
  function Pusher() {
    const { push } = useToasts();
    return (
      <button type="button" onClick={() => push('the rename did not take')}>
        break something
      </button>
    );
  }

  test('a transient failure is announced and can be dismissed', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider timeoutMs={0}>
        <Pusher />
        <Toasts />
      </ToastProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'break something' }));

    const log = screen.getByRole('log', { name: 'Notifications' });
    expect(within(log).getByTestId('toast').textContent).toContain('the rename did not take');

    await user.click(within(log).getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByTestId('toast')).toBeNull();
  });

  test('withdraws itself after a while', async () => {
    // A short timeout rather than fake timers: user-event and a real editor both want real ones,
    // and a test that installs fake timers and then times out leaves them installed for every
    // test after it.
    const user = userEvent.setup();
    render(
      <ToastProvider timeoutMs={30}>
        <Pusher />
        <Toasts />
      </ToastProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'break something' }));
    expect(screen.getByTestId('toast')).toBeDefined();

    await waitFor(() => expect(screen.queryByTestId('toast')).toBeNull());
  });

  test('the default timeout is long enough to read', () => {
    expect(TOAST_TIMEOUT_MS).toBeGreaterThanOrEqual(5_000);
  });
});

describe('failures that reach the writer', () => {
  test('a chapter that cannot be added is a toast, not a broken panel', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');

    render(
      <Harness client={client} projectId={projectId}>
        <Workspace onLeaveProject={() => {}} />
      </Harness>,
    );
    await screen.findByRole('button', { name: /^Rename / });

    client.failNext(
      'createDocument',
      new ApiError(500, 'internal_error', 'the server failed', null),
    );
    await user.click(screen.getByRole('button', { name: 'New chapter' }));

    expect((await screen.findByTestId('toast')).textContent).toContain('the server failed');
    // The workspace is intact.
    expect(screen.getByRole('region', { name: 'Manuscript' })).toBeDefined();
  });

  test('a chapter that cannot be opened says so and leaves the rest working', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');
    await client.createDocument(projectId, 'Chapter 2');

    render(
      <Harness client={client} projectId={projectId}>
        <Workspace onLeaveProject={() => {}} />
      </Harness>,
    );
    await screen.findByRole('button', { name: /^Rename / });

    client.failNext(
      'getDocument',
      new ApiError(404, 'document_not_found', "no document 'doc_2' in this workspace", null),
    );
    await user.click(screen.getByRole('button', { name: 'Chapter 2' }));

    await waitFor(() => {
      expect(screen.getByTestId('editor-status').textContent).toContain('could not be opened');
    });
    expect(screen.getByRole('tablist')).toBeDefined();
    expect(screen.getByRole('region', { name: 'Assistant' })).toBeDefined();
  });

  test('a project that cannot be loaded says so in the outline panel', async () => {
    const client = new FakeApiClient();

    render(
      <Harness client={client} projectId="prj_missing">
        <Workspace onLeaveProject={() => {}} />
      </Harness>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('toc-status').textContent).toContain('Could not read the outline');
    });
  });
});
