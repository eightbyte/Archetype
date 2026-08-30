/**
 * P1-10 — the editor and autosave, against a real TipTap instance.
 *
 * These run the actual editor: real ProseMirror, real transactions, real keystrokes through
 * `user-event`. jsdom has no layout engine, so anything that needs a measurement is out of
 * reach — but everything the acceptance bar names is reachable, and testing a mock of the editor
 * would have proved nothing about the thing a writer types into.
 *
 * The four cases P1-10 says it is not done without:
 *
 * * the formatting set round-trips through save and reload;
 * * a document switch with pending edits flushes first;
 * * a simulated save failure preserves the content and shows the failed state;
 * * a simulated `409` prompts rather than clobbers (D19).
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { describe, expect, test } from 'vitest';
import { NetworkError } from '../api';
import type { ProseMirrorDocument } from '../api';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness, prose } from './harness';

/** Every node and mark the closed schema allows, in one document. */
const EVERYTHING: ProseMirrorDocument = {
  type: 'doc',
  content: [
    { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Arrival' }] },
    { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'The harbour' }] },
    { type: 'heading', attrs: { level: 3 }, content: [{ type: 'text', text: 'At dusk' }] },
    {
      type: 'paragraph',
      content: [
        { type: 'text', marks: [{ type: 'bold' }], text: 'Grey' },
        { type: 'text', text: ' and ' },
        { type: 'text', marks: [{ type: 'italic' }], text: 'cold' },
        { type: 'hardBreak' },
        { type: 'text', text: 'and late.' },
      ],
    },
    {
      type: 'blockquote',
      content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Nothing to declare.' }] }],
    },
    {
      type: 'bulletList',
      content: [
        {
          type: 'listItem',
          content: [{ type: 'paragraph', content: [{ type: 'text', text: 'a rope' }] }],
        },
      ],
    },
    {
      type: 'orderedList',
      attrs: { start: 1 },
      content: [
        {
          type: 'listItem',
          content: [{ type: 'paragraph', content: [{ type: 'text', text: 'a lamp' }] }],
        },
      ],
    },
    { type: 'horizontalRule' },
    { type: 'paragraph', content: [{ type: 'text', text: 'Later.' }] },
  ],
};

interface Mounted {
  client: FakeApiClient;
  projectId: string;
  documentId: string;
}

interface MountOptions {
  /** Content for the first chapter, saved before the app ever sees it. */
  content?: ProseMirrorDocument;
  /** Extra chapters, created before the render so the app loads them with the project. */
  chapters?: readonly string[];
  scheduler?: { delayMs?: number; retryDelaysMs?: readonly number[] };
}

/** A project, opened, with the editor mounted on its first chapter. */
async function mount(options: MountOptions = {}): Promise<Mounted> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [documentId] = client.documentIdsOf(projectId);
  if (options.content) {
    await client.saveDocumentContent(documentId!, options.content, 1);
  }
  for (const title of options.chapters ?? []) {
    await client.createDocument(projectId, title);
  }

  render(
    <Harness
      client={client}
      projectId={projectId}
      {...(options.scheduler ? { scheduler: options.scheduler } : {})}
    >
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  await surface();
  return { client, projectId, documentId: documentId! };
}

/** The contenteditable the writer types into, once TipTap has built it. */
async function surface(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.querySelector<HTMLElement>('.manuscript');
    if (!element) {
      throw new Error('the editor has not mounted yet');
    }
    return element;
  });
}

function status(): string {
  return screen.getByTestId('save-status').textContent ?? '';
}

/** The chapter title in the editor header, which doubles as the rename control. */
function renameControl(): HTMLElement {
  return screen.getByRole('button', { name: /^Rename / });
}

describe('the writing surface', () => {
  test('renders the whole formatting set, and it round-trips through save and reload', async () => {
    const { client, documentId } = await mount({ content: EVERYTHING });
    const written = await surface();

    // Rendered: every node type the schema allows is on screen.
    expect(within(written).getByRole('heading', { level: 1 }).textContent).toBe('Arrival');
    expect(within(written).getByRole('heading', { level: 2 }).textContent).toBe('The harbour');
    expect(within(written).getByRole('heading', { level: 3 }).textContent).toBe('At dusk');
    expect(written.querySelector('strong')?.textContent).toBe('Grey');
    expect(written.querySelector('em')?.textContent).toBe('cold');
    expect(written.querySelector('br')).not.toBeNull();
    expect(written.querySelector('blockquote')?.textContent).toContain('Nothing to declare');
    expect(written.querySelector('ul li')?.textContent).toBe('a rope');
    expect(written.querySelector('ol li')?.textContent).toBe('a lamp');
    expect(written.querySelector('hr')).not.toBeNull();

    // Stored: byte for byte what went in.
    expect((await client.getDocument(documentId)).content_json).toEqual(EVERYTHING);
  });

  test('typing is saved, and the version moves once', async () => {
    const user = userEvent.setup();
    const { client, documentId } = await mount({});
    const written = await surface();

    await user.click(written);
    await user.keyboard('The harbour was grey.');

    expect(status()).toBe('Unsaved changes');
    await waitFor(() => expect(client.versionOf(documentId)).toBe(2));
    await waitFor(() => expect(status()).toMatch(/^Saved/));
    expect((await client.getDocument(documentId)).content_json).toEqual(
      prose('The harbour was grey.'),
    );
  });

  test('the toolbar turns a paragraph into a heading, and that is an edit', async () => {
    const user = userEvent.setup();
    const { client, documentId } = await mount({});
    const written = await surface();

    await user.click(written);
    await user.keyboard('The harbour');
    await user.click(screen.getByRole('button', { name: 'H2' }));

    await waitFor(() => {
      expect(within(written).getByRole('heading', { level: 2 }).textContent).toBe('The harbour');
    });
    await waitFor(async () => {
      expect((await client.getDocument(documentId)).headings).toEqual([
        { level: 2, text: 'The harbour', ordinal: 0 },
      ]);
    });
  });

  test('leaving the editor saves without waiting out the debounce', async () => {
    const user = userEvent.setup();
    const { client, documentId } = await mount({
      // Long enough that only the blur can be what saved it.
      scheduler: { delayMs: 60_000 },
    });
    const written = await surface();

    await user.click(written);
    await user.keyboard('Grey.');
    await user.click(screen.getByRole('button', { name: 'Bold' }));

    await waitFor(() => expect(client.versionOf(documentId)).toBe(2));
  });
});

describe('under StrictMode', () => {
  test('the editor survives the double mount, and still saves', async () => {
    // `main.tsx` renders in StrictMode, which mounts, unmounts, and remounts every component.
    // TipTap's `useEditor` handles that by waiting a tick before destroying, so nothing else may
    // destroy the editor on unmount — an unmount effect that did would tear down the instance
    // the manager is about to reuse, and the writing surface would be gone in the real app while
    // every test that does not use StrictMode still passed.
    const user = userEvent.setup();
    const client = new FakeApiClient();
    const projectId = client.seedProject('The Long Road');
    const [documentId] = client.documentIdsOf(projectId);

    render(
      <StrictMode>
        <Harness client={client} projectId={projectId}>
          <Workspace onLeaveProject={() => {}} />
        </Harness>
      </StrictMode>,
    );

    const written = await surface();
    await user.click(written);
    await user.keyboard('Still here.');

    await waitFor(() => expect(written.textContent).toContain('Still here.'));
    await waitFor(() => expect(client.versionOf(documentId!)).toBe(2));
  });
});

describe('switching chapters', () => {
  test('flushes the pending save before it loads the next one', async () => {
    const user = userEvent.setup();
    const { client, projectId } = await mount({
      chapters: ['Chapter 2'],
      scheduler: { delayMs: 60_000 },
    });
    const second = client.documentIdsOf(projectId)[1]!;
    const written = await surface();

    await user.click(written);
    await user.keyboard('Unsaved words.');
    expect(status()).toBe('Unsaved changes');

    const before = client.calls.length;
    await user.click(await screen.findByRole('button', { name: 'Chapter 2' }));
    await waitFor(() => {
      expect(renameControl().textContent).toBe(
        'Chapter 2',
      );
    });

    // The order is the whole point: saved, and only then loaded.
    const after = client.calls.slice(before);
    expect(after.indexOf('saveDocumentContent')).toBeGreaterThanOrEqual(0);
    expect(after.indexOf('saveDocumentContent')).toBeLessThan(after.indexOf('getDocument'));
    expect((await client.getDocument(second)).content_json).not.toEqual(prose('Unsaved words.'));
  });

  test('a switch is refused when the pending save could not be written', async () => {
    const user = userEvent.setup();
    const { client } = await mount({
      chapters: ['Chapter 2'],
      scheduler: { delayMs: 60_000, retryDelaysMs: [60_000] },
    });
    const written = await surface();

    await user.click(written);
    await user.keyboard('Words that must not be lost.');
    client.failAlways('saveDocumentContent', new NetworkError('the server went away', null));

    await user.click(await screen.findByRole('button', { name: 'Chapter 2' }));

    await waitFor(() => {
      expect(screen.getByText(/have not been saved yet/)).toBeDefined();
    });
    // Still in the first chapter, still holding the words.
    expect(renameControl().textContent).toBe(
      'Chapter 1',
    );
    expect((await surface()).textContent).toContain('must not be lost');
  });
});

describe('a save that fails', () => {
  test('keeps the writing, says so, and offers to try again', async () => {
    const user = userEvent.setup();
    const { client, documentId } = await mount({
      // No automatic retry inside this test, so the button is the only thing that can succeed.
      scheduler: { retryDelaysMs: [60_000] },
    });
    const written = await surface();

    client.failAlways('saveDocumentContent', new NetworkError('the server went away', null));
    await user.click(written);
    await user.keyboard('Precious words.');

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Save failed');
    expect(alert.textContent).toContain('the server could not be reached');
    expect(written.textContent).toContain('Precious words.');
    expect(client.versionOf(documentId)).toBe(1);

    client.stopFailing('saveDocumentContent');
    await user.click(screen.getByRole('button', { name: 'Retry now' }));

    await waitFor(() => expect(client.versionOf(documentId)).toBe(2));
    expect(status()).toMatch(/^Saved/);
    expect((await client.getDocument(documentId)).content_json).toEqual(prose('Precious words.'));
  });
});

describe('a version conflict (D19)', () => {
  test('prompts rather than clobbers, and reloading takes the saved version', async () => {
    const user = userEvent.setup();
    const { client, documentId } = await mount({});
    const written = await surface();

    await user.click(written);
    await user.keyboard('Mine.');
    await waitFor(() => expect(client.versionOf(documentId)).toBe(2));

    // Someone else — another window, or the agent in Phase 6 — writes to the same chapter.
    client.writeBehindTheScenes(documentId, prose('Theirs.'));

    await user.keyboard(' More of mine.');

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('changed somewhere else');
    expect(alert.textContent).toContain('version 3');

    // Nothing was overwritten.
    expect((await client.getDocument(documentId)).content_json).toEqual(prose('Theirs.'));

    await user.click(screen.getByRole('button', { name: 'Reload the saved version' }));

    await waitFor(() => expect((document.querySelector('.manuscript'))?.textContent).toBe('Theirs.'));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('typing on does not sneak past the conflict', async () => {
    const user = userEvent.setup();
    const { client, documentId } = await mount({});
    const written = await surface();

    await user.click(written);
    await user.keyboard('Mine.');
    await waitFor(() => expect(client.versionOf(documentId)).toBe(2));

    client.writeBehindTheScenes(documentId, prose('Theirs.'));
    await user.keyboard(' More.');
    await screen.findByRole('alert');

    await user.keyboard(' And more.');
    await new Promise((resolve) => setTimeout(resolve, 80));

    expect(client.versionOf(documentId)).toBe(3);
    expect((await client.getDocument(documentId)).content_json).toEqual(prose('Theirs.'));
  });
});

describe('leaving the page', () => {
  test('unsaved work makes the browser ask, and starts the save anyway', async () => {
    const user = userEvent.setup();
    const { client, documentId } = await mount({ scheduler: { delayMs: 60_000 } });
    const written = await surface();

    await user.click(written);
    await user.keyboard('Not yet saved.');

    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(client.versionOf(documentId)).toBe(2));
  });

  test('a clean document does not ask', async () => {
    await mount({ content: prose('Already saved.') });
    await surface();

    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });
});

describe('renaming a chapter', () => {
  test('commits on Enter and does not move the content version', async () => {
    const user = userEvent.setup();
    const { client, documentId } = await mount({});
    await surface();

    await user.click(renameControl());
    const input = screen.getByRole('textbox', { name: 'Chapter title' });
    await user.clear(input);
    await user.type(input, 'Arrival{Enter}');

    await waitFor(() => {
      expect(renameControl().textContent).toBe(
        'Arrival',
      );
    });
    expect(client.versionOf(documentId)).toBe(1);
    // The outline is told too, without refetching it.
    expect(screen.getByRole('button', { name: 'Arrival' })).toBeDefined();
  });

  test('Escape abandons the rename', async () => {
    const user = userEvent.setup();
    await mount({});
    await surface();

    await user.click(renameControl());
    const input = screen.getByRole('textbox', { name: 'Chapter title' });
    await user.clear(input);
    await user.type(input, 'Discarded{Escape}');

    expect(renameControl().textContent).toBe(
      'Chapter 1',
    );
  });
});
