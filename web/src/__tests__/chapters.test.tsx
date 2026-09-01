/**
 * P2-11 — chapter management in the Contents tab.
 *
 * Reorder by drag **and** by keyboard, rename in place, delete with a confirmation, and restore.
 *
 * The keyboard path gets as many tests as the pointer one, deliberately. jsdom has no layout
 * engine, so a drag here is a synthetic event sequence and proves only that the handlers are
 * wired; the keyboard path is the one a person can actually complete, and P1-9 says an
 * interaction without one is a feature only some people have.
 *
 * The other thing being held down is that the *complete* order is sent every time. That
 * completeness is the server's concurrency guard (P2-2) — a client that sent a partial list
 * would be refused, and a client that sent a stale one would drop a chapter out of the order.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { ApiError, ERROR_CODES } from '../api';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness, prose } from './harness';

interface Seeded {
  client: FakeApiClient;
  projectId: string;
  ids: string[];
}

/** A project of three written chapters, with the workspace mounted on the first. */
async function mount(options: { markOn?: number } = {}): Promise<Seeded> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const ids = [...client.documentIdsOf(projectId)];
  for (const title of ['Departure', 'The Crossing']) {
    ids.push((await client.createDocument(projectId, title)).id);
  }
  for (const [index, id] of ids.entries()) {
    await client.saveDocumentContent(id, prose(`Chapter ${index} was written.`), 1);
  }
  // Before the render, so the project state loads it the way a reload would.
  if (options.markOn !== undefined) {
    client.seedAnchor(ids[options.markOn]!, { quote: 'was written' });
  }

  render(
    <Harness client={client} projectId={projectId} scheduler={{ delayMs: 60_000 }}>
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  await waitFor(() => {
    if (!document.querySelector('.manuscript')) {
      throw new Error('the editor has not mounted yet');
    }
  });
  return { client, projectId, ids };
}

function toc(): HTMLElement {
  return screen.getByRole('tabpanel');
}

/** The chapter titles as the Contents tab is showing them, in order. */
function titles(): string[] {
  return [...toc().querySelectorAll('.toc-chapter-title')].map(
    (element) => element.textContent ?? '',
  );
}

describe('reordering', () => {
  test('by keyboard: the move controls do it, and the order persists', async () => {
    const user = userEvent.setup();
    const { client, projectId, ids } = await mount();
    expect(titles()).toEqual(['Chapter 1', 'Departure', 'The Crossing']);

    await user.click(screen.getByRole('button', { name: 'The Crossing: move up' }));

    await waitFor(() => {
      expect(titles()).toEqual(['Chapter 1', 'The Crossing', 'Departure']);
    });
    expect(client.documentIdsOf(projectId)).toEqual([ids[0], ids[2], ids[1]]);
  });

  test('by keyboard: the arrow keys move a chapter and focus follows it', async () => {
    const user = userEvent.setup();
    const { client, projectId, ids } = await mount();

    screen.getByRole('button', { name: 'Chapter 1: move down' }).focus();
    await user.keyboard('{ArrowDown}');

    await waitFor(() => {
      expect(titles()).toEqual(['Departure', 'Chapter 1', 'The Crossing']);
    });
    // Focus has to follow, or a second press goes nowhere and the interaction is unusable.
    await waitFor(() => {
      expect(document.activeElement?.getAttribute('aria-label')).toBe('Chapter 1: move down');
    });

    await user.keyboard('{ArrowDown}');
    await waitFor(() => {
      expect(client.documentIdsOf(projectId)).toEqual([ids[1], ids[2], ids[0]]);
    });
  });

  test('the first chapter cannot move up and the last cannot move down', async () => {
    await mount();

    expect(
      screen.getByRole('button', { name: 'Chapter 1: move up' }).hasAttribute('disabled'),
    ).toBe(true);
    expect(
      screen.getByRole('button', { name: 'The Crossing: move down' }).hasAttribute('disabled'),
    ).toBe(true);
  });

  test('by drag: dropping a chapter on another one puts it there', async () => {
    const { client, projectId, ids } = await mount();
    const rows = toc().querySelectorAll<HTMLElement>('.toc-chapter');
    const dragged = rows[2]!.querySelector<HTMLElement>('.toc-chapter-row')!;
    // jsdom has no DataTransfer, so the parts the handlers use stand in for it. What this can
    // prove is that the events are wired to the same reorder the keyboard uses — the pointer
    // gesture itself needs a layout engine and a person.
    const stored = new Map<string, string>();
    const dataTransfer = {
      setData: (kind: string, value: string) => stored.set(kind, value),
      getData: (kind: string) => stored.get(kind) ?? '',
      effectAllowed: 'move',
    };

    dragged.dispatchEvent(
      Object.assign(new Event('dragstart', { bubbles: true }), { dataTransfer }),
    );
    rows[0]!.dispatchEvent(Object.assign(new Event('drop', { bubbles: true }), { dataTransfer }));

    await waitFor(() => {
      expect(client.documentIdsOf(projectId)).toEqual([ids[2], ids[0], ids[1]]);
    });
  });

  test('the whole order is sent, because that completeness is the guard (P2-2)', async () => {
    const user = userEvent.setup();
    const { client, ids } = await mount();
    let sent: string[] = [];
    const real = client.reorderDocuments.bind(client);
    client.reorderDocuments = async (pid: string, documentIds: string[]) => {
      sent = documentIds;
      return real(pid, documentIds);
    };

    await user.click(screen.getByRole('button', { name: 'Departure: move up' }));

    await waitFor(() => expect(sent).toHaveLength(3));
    expect([...sent].sort()).toEqual([...ids].sort());
  });

  test('a refused reorder re-reads the list rather than correcting a field', async () => {
    const user = userEvent.setup();
    const { client } = await mount();
    client.failNext(
      'reorderDocuments',
      new ApiError(409, ERROR_CODES.reorderMismatch, 'the list had moved on', {
        missing: ['doc_x'],
        unexpected: [],
        duplicated: [],
      }),
    );

    await user.click(screen.getByRole('button', { name: 'Departure: move up' }));

    await waitFor(() => {
      expect(screen.getByRole('log').textContent).toContain('moved on');
    });
    // The reload put the server's order back on screen, unchanged.
    await waitFor(() => {
      expect(titles()).toEqual(['Chapter 1', 'Departure', 'The Crossing']);
    });
  });
});

describe('renaming in the list', () => {
  test('commits on Enter and shows the new title everywhere', async () => {
    const user = userEvent.setup();
    const { client, ids } = await mount();

    await user.click(screen.getByRole('button', { name: 'Departure: rename' }));
    await user.clear(screen.getByRole('textbox', { name: 'Departure: new name' }));
    await user.keyboard('Leaving{Enter}');

    await waitFor(() => {
      expect(titles()).toContain('Leaving');
    });
    expect((await client.getDocument(ids[1]!)).title).toBe('Leaving');
  });

  test('Escape abandons it', async () => {
    const user = userEvent.setup();
    const { client, ids } = await mount();

    await user.click(screen.getByRole('button', { name: 'Departure: rename' }));
    await user.clear(screen.getByRole('textbox', { name: 'Departure: new name' }));
    await user.keyboard('Leaving{Escape}');

    expect(titles()).toContain('Departure');
    expect((await client.getDocument(ids[1]!)).title).toBe('Departure');
  });

  test('renaming the open chapter also renames it in the editor header', async () => {
    const user = userEvent.setup();
    await mount();

    await user.click(screen.getByRole('button', { name: 'Chapter 1: rename' }));
    await user.clear(screen.getByRole('textbox', { name: 'Chapter 1: new name' }));
    await user.keyboard('Arrival{Enter}');

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^Rename / }).textContent).toBe('Arrival');
    });
  });
});

describe('deleting a chapter (D22)', () => {
  test('asks first, and says what becomes of the chapter’s marks', async () => {
    const user = userEvent.setup();
    await mount({ markOn: 1 });

    await user.click(screen.getByRole('button', { name: 'Departure: delete' }));

    const confirmation = screen.getByRole('group', { name: 'Confirm deleting Departure' });
    expect(confirmation.textContent).toContain('1 mark');
    expect(confirmation.textContent).toContain('restored');

    await user.click(within(confirmation).getByRole('button', { name: 'Cancel' }));

    expect(titles()).toContain('Departure');
  });

  test('removes it from the contents and from every count', async () => {
    const user = userEvent.setup();
    const { client, projectId } = await mount();

    await user.click(screen.getByRole('button', { name: 'Departure: delete' }));
    await user.click(screen.getByRole('button', { name: 'Delete chapter' }));

    await waitFor(() => {
      expect(titles()).toEqual(['Chapter 1', 'The Crossing']);
    });
    expect(screen.getByTestId('toc-total').textContent).toContain('2 chapters');
    expect(client.documentIdsOf(projectId)).toHaveLength(2);
  });

  test('deleting the open chapter moves the editor to its neighbour, not to a ghost', async () => {
    const user = userEvent.setup();
    await mount();
    expect(screen.getByRole('button', { name: /^Rename / }).textContent).toBe('Chapter 1');

    await user.click(screen.getByRole('button', { name: 'Chapter 1: delete' }));
    await user.click(screen.getByRole('button', { name: 'Delete chapter' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^Rename / }).textContent).toBe('Departure');
    });
  });

  test('the last chapter cannot be deleted — a project always has one', async () => {
    const user = userEvent.setup();
    await mount();

    await user.click(screen.getByRole('button', { name: 'Departure: delete' }));
    await user.click(screen.getByRole('button', { name: 'Delete chapter' }));
    await waitFor(() => expect(titles()).toHaveLength(2));
    await user.click(screen.getByRole('button', { name: 'The Crossing: delete' }));
    await user.click(screen.getByRole('button', { name: 'Delete chapter' }));
    await waitFor(() => expect(titles()).toHaveLength(1));

    expect(
      screen.getByRole('button', { name: 'Chapter 1: delete' }).hasAttribute('disabled'),
    ).toBe(true);
  });
});

describe('restoring a deleted chapter', () => {
  test('it is listed with when it went, and comes back at the end of the order', async () => {
    const user = userEvent.setup();
    const { client, projectId, ids } = await mount();

    await user.click(screen.getByRole('button', { name: 'Departure: delete' }));
    await user.click(screen.getByRole('button', { name: 'Delete chapter' }));
    await waitFor(() => expect(titles()).toEqual(['Chapter 1', 'The Crossing']));

    await user.click(screen.getByRole('button', { name: 'Deleted chapters' }));

    const restore = await screen.findByRole('button', { name: 'Departure: restore' });
    await user.click(restore);

    await waitFor(() => {
      expect(titles()).toEqual(['Chapter 1', 'The Crossing', 'Departure']);
    });
    expect(client.documentIdsOf(projectId)).toEqual([ids[0], ids[2], ids[1]]);
  });

  test('with nothing deleted, the list says so rather than looking broken', async () => {
    const user = userEvent.setup();
    await mount();

    await user.click(screen.getByRole('button', { name: 'Deleted chapters' }));

    expect((await screen.findByTestId('toc-deleted-status')).textContent).toContain(
      'Nothing has been deleted',
    );
  });

  test('a restored chapter keeps its text, byte for byte', async () => {
    const user = userEvent.setup();
    const { client, ids } = await mount();
    const before = (await client.getDocument(ids[1]!)).content_json;

    await user.click(screen.getByRole('button', { name: 'Departure: delete' }));
    await user.click(screen.getByRole('button', { name: 'Delete chapter' }));
    await user.click(screen.getByRole('button', { name: 'Deleted chapters' }));
    await user.click(await screen.findByRole('button', { name: 'Departure: restore' }));

    await waitFor(() => expect(titles()).toContain('Departure'));
    expect((await client.getDocument(ids[1]!)).content_json).toEqual(before);
  });
});
