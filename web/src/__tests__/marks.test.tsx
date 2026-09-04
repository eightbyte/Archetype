/**
 * P2-10 — the *Marks* tab and the repair path.
 *
 * The tab exists so that "what is stale" is one click and so that a broken mark can be repaired
 * **by hand**. Every test here is really one assertion in different clothes: nothing repairs
 * itself. A suggestion is shown and is a button; accepting one sends the same request choosing a
 * passage by hand sends; an orphaned mark is not repaired at all, its chapter is restored.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness, prose } from './harness';

const HARBOUR = 'The harbour was grey.';
const QUOTE = 'harbour was grey';
const RANGE = { from_pos: 5, to_pos: 21 };

interface Seeded {
  client: FakeApiClient;
  projectId: string;
  first: string;
  second: string;
}

/** A project of two written chapters, with the workspace mounted on the first. */
async function mount(): Promise<Seeded> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [first] = client.documentIdsOf(projectId);
  await client.saveDocumentContent(first!, prose(HARBOUR), 1);
  const created = await client.createDocument(projectId, 'Departure');
  await client.saveDocumentContent(created.id, prose('He did not look back.'), 1);
  return { client, projectId, first: first!, second: created.id };
}

async function open(seeded: Seeded) {
  render(
    <Harness client={seeded.client} projectId={seeded.projectId} scheduler={{ delayMs: 60_000 }}>
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  await waitFor(() => {
    if (!document.querySelector('.manuscript')) {
      throw new Error('the editor has not mounted yet');
    }
  });
  return seeded;
}

async function marksTab(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  await user.click(screen.getByRole('tab', { name: 'Marks' }));
  return screen.getByRole('tabpanel');
}

describe('listing the marks', () => {
  test('groups them by chapter and says nothing when there are none', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    await open(seeded);

    const panel = await marksTab(user);

    expect(within(panel).getByTestId('marks-status').textContent).toContain('No marks yet');
  });

  test('shows each mark’s passage under its chapter, with its status', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    seeded.client.seedAnchor(seeded.first, { quote: QUOTE, ...RANGE });
    seeded.client.seedAnchor(seeded.second, { quote: 'did not look', status: 'stale' });
    await open(seeded);

    const panel = await marksTab(user);

    await waitFor(() => {
      expect(within(panel).getByRole('button', { name: QUOTE })).toBeDefined();
    });
    expect(within(panel).getByRole('heading', { name: 'Chapter 1' })).toBeDefined();
    expect(within(panel).getByRole('heading', { name: 'Departure' })).toBeDefined();
    expect(within(panel).getByTestId('marks-total').textContent).toBe('2 marks');
  });

  test('filtering by status is one click', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    seeded.client.seedAnchor(seeded.first, { quote: QUOTE, ...RANGE });
    seeded.client.seedAnchor(seeded.second, { quote: 'did not look', status: 'stale' });
    await open(seeded);
    const panel = await marksTab(user);
    await within(panel).findByRole('button', { name: QUOTE });

    await user.click(within(panel).getByRole('button', { name: 'Lost (1)' }));

    expect(within(panel).queryByRole('button', { name: QUOTE })).toBeNull();
    expect(within(panel).getByRole('button', { name: 'did not look' })).toBeDefined();
  });

  test('a filter that matches nothing says so rather than looking empty', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    seeded.client.seedAnchor(seeded.first, { quote: QUOTE, ...RANGE });
    await open(seeded);
    const panel = await marksTab(user);
    await within(panel).findByRole('button', { name: QUOTE });

    await user.click(within(panel).getByRole('button', { name: 'Lost (0)' }));

    expect(within(panel).getByTestId('marks-status').textContent).toContain('Nothing with that');
  });

  test('clicking a mark opens its chapter and scrolls to it', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    const anchor = seeded.client.seedAnchor(seeded.second, {
      quote: 'did not look',
      from_pos: 4,
      to_pos: 16,
    });
    await open(seeded);
    const panel = await marksTab(user);

    await user.click(await within(panel).findByRole('button', { name: 'did not look' }));

    await waitFor(() => {
      expect(
        document.querySelector(`.manuscript [data-anchor-id="${anchor.id}"]`),
      ).not.toBeNull();
    });
  });
});

describe('repairing a stale mark', () => {
  test('shows the old passage beside the suggestion, and accepting it re-links', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    // The chapter now reads differently, and the server has said so and offered a passage.
    await seeded.client.saveDocumentContent(seeded.first, prose('The harbour was calm.'), 2);
    const anchor = seeded.client.seedAnchor(seeded.first, {
      quote: QUOTE,
      status: 'stale',
      ...RANGE,
      suggestion: { from_pos: 5, to_pos: 21, text: 'harbour was calm' },
    });
    await open(seeded);
    const panel = await marksTab(user);

    const mark = await within(panel).findByRole('button', { name: QUOTE });
    const entry = mark.closest('li')!;
    expect(entry.textContent).toContain('harbour was calm');

    await user.click(within(entry).getByRole('button', { name: 'Use this' }));

    await waitFor(() => {
      expect(seeded.client.anchorOf(anchor.id)?.status).toBe('ok');
    });
    // The server re-derived the quote from the range, exactly as it does for any other re-link.
    expect(seeded.client.anchorOf(anchor.id)?.quote).toBe('harbour was calm');
  });

  test('a mark with no suggestion offers no shortcut, only the manual paths', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    seeded.client.seedAnchor(seeded.first, { quote: QUOTE, status: 'stale', ...RANGE });
    await open(seeded);
    const panel = await marksTab(user);

    const entry = (await within(panel).findByRole('button', { name: QUOTE })).closest('li')!;

    expect(within(entry).queryByRole('button', { name: 'Use this' })).toBeNull();
    expect(within(entry).getByRole('button', { name: 'Pick manually' })).toBeDefined();
    expect(within(entry).getByRole('button', { name: 'Delete' })).toBeDefined();
  });

  test('picking manually asks for a passage in the editor, and survives a chapter switch', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    seeded.client.seedAnchor(seeded.first, { quote: QUOTE, status: 'stale', ...RANGE });
    await open(seeded);
    const panel = await marksTab(user);
    const entry = (await within(panel).findByRole('button', { name: QUOTE })).closest('li')!;

    await user.click(within(entry).getByRole('button', { name: 'Pick manually' }));

    const prompt = await screen.findByRole('status', { name: 'Re-linking a mark' });
    expect(prompt.textContent).toContain(QUOTE);

    // A repair may finish in a different chapter, so arming outlives the switch (P2-10).
    await user.click(screen.getByRole('tab', { name: 'Contents' }));
    await user.click(screen.getByRole('button', { name: 'Departure' }));

    await waitFor(() => {
      expect(screen.getByRole('status', { name: 'Re-linking a mark' }).textContent).toContain(QUOTE);
    });
  });

  test('and can be abandoned without changing anything', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    const anchor = seeded.client.seedAnchor(seeded.first, {
      quote: QUOTE,
      status: 'stale',
      ...RANGE,
    });
    await open(seeded);
    const panel = await marksTab(user);
    const entry = (await within(panel).findByRole('button', { name: QUOTE })).closest('li')!;
    await user.click(within(entry).getByRole('button', { name: 'Pick manually' }));
    await screen.findByRole('status', { name: 'Re-linking a mark' });

    await user.click(
      within(screen.getByRole('status', { name: 'Re-linking a mark' })).getByRole('button', {
        name: 'Cancel',
      }),
    );

    await waitFor(() =>
      expect(screen.queryByRole('status', { name: 'Re-linking a mark' })).toBeNull(),
    );
    expect(seeded.client.anchorOf(anchor.id)?.status).toBe('stale');
  });

  test('deleting a mark removes it, and is the only way one goes away', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    const anchor = seeded.client.seedAnchor(seeded.first, {
      quote: QUOTE,
      status: 'stale',
      ...RANGE,
    });
    await open(seeded);
    const panel = await marksTab(user);
    const entry = (await within(panel).findByRole('button', { name: QUOTE })).closest('li')!;

    await user.click(within(entry).getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(seeded.client.anchorOf(anchor.id)).toBeUndefined();
    });
    expect(within(panel).getByTestId('marks-status').textContent).toContain('No marks yet');
  });
});

describe('a mark whose chapter was deleted (D22)', () => {
  test('reads as orphaned and offers to restore the chapter, not to re-link', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    const anchor = seeded.client.seedAnchor(seeded.second, {
      quote: 'did not look',
      from_pos: 4,
      to_pos: 16,
    });
    await open(seeded);

    // Delete the chapter from the Contents tab, the way a writer would.
    await user.click(screen.getByRole('button', { name: 'Departure: delete' }));
    await user.click(screen.getByRole('button', { name: 'Delete chapter' }));

    const panel = await marksTab(user);
    const entry = (await within(panel).findByRole('button', { name: 'did not look' })).closest(
      'li',
    )!;
    expect(entry.textContent).toContain('Chapter deleted');
    expect(within(entry).queryByRole('button', { name: 'Pick manually' })).toBeNull();

    await user.click(within(entry).getByRole('button', { name: 'Restore the chapter' }));

    await waitFor(() => {
      expect(seeded.client.anchorOf(anchor.id)?.status).toBe('ok');
    });
    await waitFor(() => {
      expect(within(panel).getByText('Found')).toBeDefined();
    });
  });

  test('a mark that was already lost is still lost after its chapter comes back', async () => {
    const user = userEvent.setup();
    const seeded = await mount();
    // `orphaned` is the chapter showing through a stored `ok` or `stale`, and which of the two
    // it is underneath is the server's to say. A client that answered `ok` here would be
    // deciding an anchor's status, which is the one thing nothing on this side may do.
    seeded.client.seedAnchor(seeded.second, { quote: 'did not look', status: 'stale' });
    await open(seeded);

    await user.click(screen.getByRole('button', { name: 'Departure: delete' }));
    await user.click(screen.getByRole('button', { name: 'Delete chapter' }));
    const panel = await marksTab(user);
    const entry = (await within(panel).findByRole('button', { name: 'did not look' })).closest(
      'li',
    )!;
    await user.click(within(entry).getByRole('button', { name: 'Restore the chapter' }));

    await waitFor(() => {
      expect(within(panel).getByText('Lost')).toBeDefined();
    });
    expect(within(panel).queryByText('Found')).toBeNull();
  });
});
