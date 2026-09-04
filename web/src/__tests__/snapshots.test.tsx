/**
 * P2-12 — the chapter's history in the app.
 *
 * What it has to do: list what was taken and why, mark a version with a label, preview one
 * beside the current text, and restore — warning first that what is on screen will be kept
 * before it is replaced.
 *
 * The restore is the case worth the most care, because it is the one that replaces a chapter's
 * words. Three things have to be true afterwards and each is asserted: the text came back, the
 * version moved, and the copy that was replaced is in the history where the writer can get it.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness, prose } from './harness';

const FIRST_DRAFT = 'The harbour was grey.';
const REWRITTEN = 'The harbour was calm and the light had gone.';

interface Seeded {
  client: FakeApiClient;
  projectId: string;
  first: string;
  second: string;
}

async function mount(options: { delayMs?: number } = {}): Promise<Seeded> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [first] = client.documentIdsOf(projectId);
  await client.saveDocumentContent(first!, prose(FIRST_DRAFT), 1);
  const created = await client.createDocument(projectId, 'Departure');
  await client.saveDocumentContent(created.id, prose('He did not look back.'), 1);

  render(
    <Harness
      client={client}
      projectId={projectId}
      scheduler={{ delayMs: options.delayMs ?? 60_000 }}
    >
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  await waitFor(() => {
    if (!document.querySelector('.manuscript')) {
      throw new Error('the editor has not mounted yet');
    }
  });
  return { client, projectId, first: first!, second: created.id };
}

async function history(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  await user.click(screen.getByRole('button', { name: 'History' }));
  return screen.getByRole('region', { name: 'Chapter history' });
}

async function mark(
  user: ReturnType<typeof userEvent.setup>,
  panel: HTMLElement,
  label: string,
): Promise<void> {
  await user.clear(within(panel).getByLabelText('Mark this version'));
  await user.type(within(panel).getByLabelText('Mark this version'), label);
  await user.click(within(panel).getByRole('button', { name: 'Mark' }));
}

describe('the history', () => {
  test('a chapter with no versions says so rather than showing an empty box', async () => {
    const user = userEvent.setup();
    await mount();

    const panel = await history(user);

    expect((await within(panel).findByTestId('history-status')).textContent).toContain(
      'No versions yet',
    );
  });

  test('a manual mark appears immediately, with its label', async () => {
    const user = userEvent.setup();
    const { client, first } = await mount();
    const panel = await history(user);

    await mark(user, panel, 'before the rewrite');

    await waitFor(() => {
      expect(within(panel).getByText('before the rewrite')).toBeDefined();
    });
    expect(client.snapshotsOf(first).map((snapshot) => snapshot.reason)).toEqual(['manual']);
  });

  test('says why each version was kept when the writer did not name it', async () => {
    const user = userEvent.setup();
    const { client, first, second } = await mount();
    // A handover is what happens on the way out of a chapter (D23) — no one asked for it, so it
    // has to explain itself in the list.
    await client.captureSnapshot(first, 'handover');
    await client.saveDocumentContent(second, prose('Elsewhere.'), 2);

    const panel = await history(user);

    await waitFor(() => {
      expect(within(panel).getByText('On leaving the chapter')).toBeDefined();
    });
  });

  test('a preview shows the version beside the chapter as it is now', async () => {
    const user = userEvent.setup();
    const { client, first } = await mount({ delayMs: 5 });
    const panel = await history(user);
    await mark(user, panel, 'the first draft');

    // The writer carries on writing, and the preview has to show that rather than the text the
    // chapter was opened with — the "now" side is what a restore would replace.
    await user.click(document.querySelector<HTMLElement>('.manuscript')!);
    await user.keyboard('Later. ');
    await waitFor(() => expect(client.versionOf(first)).toBe(3));

    await user.click(within(panel).getByRole('button', { name: 'Preview' }));

    await waitFor(() => {
      expect(screen.getByTestId('history-preview-then').textContent).toBe(FIRST_DRAFT);
    });
    expect(screen.getByTestId('history-preview-now').textContent).toBe(`Later. ${FIRST_DRAFT}`);
  });
});

describe('handover snapshots (D23)', () => {
  test('leaving a chapter keeps a copy of it', async () => {
    const user = userEvent.setup();
    const { client, first } = await mount();

    await user.click(screen.getByRole('button', { name: 'Departure' }));

    await waitFor(() => {
      expect(client.snapshotsOf(first).map((snapshot) => snapshot.reason)).toEqual(['handover']);
    });
  });

  test('and leaving it again writes nothing, because nothing changed', async () => {
    const user = userEvent.setup();
    const { client, first } = await mount();

    await user.click(screen.getByRole('button', { name: 'Departure' }));
    await waitFor(() => expect(client.snapshotsOf(first)).toHaveLength(1));
    await user.click(screen.getByRole('button', { name: 'Chapter 1' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^Rename / }).textContent).toBe(
      'Chapter 1',
    ));
    await user.click(screen.getByRole('button', { name: 'Departure' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^Rename / }).textContent).toBe('Departure');
    });
    expect(client.snapshotsOf(first)).toHaveLength(1);
  });
});

describe('restoring a version', () => {
  test('warns what happens to the current text before it replaces it', async () => {
    const user = userEvent.setup();
    const { client, first } = await mount();
    const panel = await history(user);
    await mark(user, panel, 'the first draft');

    await user.click(within(panel).getByRole('button', { name: 'Restore' }));

    const confirmation = screen.getByRole('group', { name: 'Confirm restore' });
    expect(confirmation.textContent).toContain('kept in this history first');

    await user.click(within(confirmation).getByRole('button', { name: 'Cancel' }));

    expect(client.snapshotsOf(first)).toHaveLength(1);
  });

  test('brings the text back, moves the version, and keeps what it replaced', async () => {
    const user = userEvent.setup();
    const { client, first } = await mount({ delayMs: 5 });
    const panel = await history(user);
    await mark(user, panel, 'the first draft');
    const versionBefore = client.versionOf(first)!;

    // The chapter is rewritten; the mark still holds the first draft.
    await user.click(document.querySelector<HTMLElement>('.manuscript')!);
    await user.keyboard(REWRITTEN);
    await waitFor(() => expect(client.versionOf(first)).toBe(versionBefore + 1));

    await user.click(within(panel).getByRole('button', { name: 'Restore' }));
    await user.click(screen.getByRole('button', { name: 'Restore this version' }));

    await waitFor(() => {
      expect(document.querySelector('.manuscript')?.textContent).toBe(FIRST_DRAFT);
    });
    expect((await client.getDocument(first)).content_json).toEqual(prose(FIRST_DRAFT));
    expect(client.versionOf(first)).toBeGreaterThan(versionBefore + 1);
    // The words that were replaced are recoverable — that is the whole promise (P2-3).
    expect(client.snapshotsOf(first).map((snapshot) => snapshot.reason)).toContain('pre-restore');
  });

  test('the writer is left where they were, in the same chapter and the same panel', async () => {
    const user = userEvent.setup();
    const { client, first } = await mount({ delayMs: 5 });
    const panel = await history(user);
    await mark(user, panel, 'the first draft');
    await user.click(document.querySelector<HTMLElement>('.manuscript')!);
    await user.keyboard(REWRITTEN);
    await waitFor(() => expect(client.versionOf(first)).toBe(3));

    await user.click(within(panel).getByRole('button', { name: 'Restore' }));
    await user.click(screen.getByRole('button', { name: 'Restore this version' }));

    await waitFor(() => {
      expect(document.querySelector('.manuscript')?.textContent).toBe(FIRST_DRAFT);
    });
    expect(screen.getByRole('button', { name: /^Rename / }).textContent).toBe('Chapter 1');
    expect(screen.getByRole('region', { name: 'Chapter history' })).toBeDefined();
    expect(within(panel).getByText('the first draft')).toBeDefined();
  });

  test('a restore refused as stale says so and changes nothing', async () => {
    const user = userEvent.setup();
    const { client, first } = await mount();
    const panel = await history(user);
    await mark(user, panel, 'the first draft');
    const { ApiError, ERROR_CODES } = await import('../api');
    client.failNext(
      'restoreSnapshot',
      new ApiError(409, ERROR_CODES.versionConflict, 'the chapter has moved on', {
        document_id: first,
        presented_version: 2,
        current_version: 3,
        updated_at: '2026-01-01T00:00:00Z',
      }),
    );

    await user.click(within(panel).getByRole('button', { name: 'Restore' }));
    await user.click(screen.getByRole('button', { name: 'Restore this version' }));

    await waitFor(() => {
      expect(screen.getByRole('log').textContent).toContain('Could not restore');
    });
    expect(client.snapshotsOf(first).map((snapshot) => snapshot.reason)).toEqual(['manual']);
  });
});
