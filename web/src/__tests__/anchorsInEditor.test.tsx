/**
 * P2-9 — anchors in the running app.
 *
 * The mechanics of the decoration plugin are held down in `anchorPlugin.test.ts`, against real
 * ProseMirror and no React. These are about the other half: that the server's answer reaches the
 * plugin, that it is *replaced* by what a save says rather than merged with it (D21), and that a
 * mark made in the editor becomes an anchor the rest of the app can see.
 *
 * The fake client has no resolver and must not grow one, so a save that moves an anchor is
 * staged: the test says what the server answers and the assertion is about what the client draws.
 * That is the actual contract — the client obeys the save response, whatever it contains.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import type { ProseMirrorDocument } from '../api';
import { useDocument } from '../state/DocumentContext';
import { useProject } from '../state/ProjectContext';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness, prose } from './harness';

const HARBOUR = 'The harbour was grey.';
/** `The harbour was grey.` in one paragraph: text starts at 1, so `harbour was grey` is 5..21. */
const RANGE = { from: 5, to: 21 };
const QUOTE = 'harbour was grey';

interface MountOptions {
  content?: ProseMirrorDocument;
  chapters?: readonly string[];
  scheduler?: { delayMs?: number; retryDelaysMs?: readonly number[] };
  /** Seed an anchor over `QUOTE` in the first chapter before the app ever loads. */
  seedAnchor?: boolean;
}

/**
 * Probes that reach the state layer the way the editor's controls do.
 *
 * jsdom has no native editing, so a text selection cannot be made through the DOM (see
 * `selectionActions.test.tsx`, which covers the control itself against a real editor). These
 * stand in for the gesture and nothing else — everything below the call is the app's own.
 */
function MarkProbe() {
  const { createAnchor } = useDocument();
  const { state, relinkAnchor } = useProject();
  const { state: documentState } = useDocument();
  const first = state.anchors[0];
  return (
    <>
      <button type="button" onClick={() => void createAnchor(RANGE.from, RANGE.to, 'the harbour')}>
        Mark it
      </button>
      <button
        type="button"
        disabled={!first}
        onClick={() =>
          void relinkAnchor(first!.id, {
            from_pos: 27,
            to_pos: 39,
            version: documentState.version,
          })
        }
      >
        Re-link it elsewhere
      </button>
    </>
  );
}

async function mount(options: MountOptions = {}) {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [documentId] = client.documentIdsOf(projectId);
  await client.saveDocumentContent(documentId!, options.content ?? prose(HARBOUR), 1);
  for (const title of options.chapters ?? []) {
    const id = await client.createDocument(projectId, title);
    await client.saveDocumentContent(id.id, prose('Elsewhere entirely.'), 1);
  }
  let anchorId: string | null = null;
  if (options.seedAnchor) {
    anchorId = client.seedAnchor(documentId!, {
      quote: QUOTE,
      from_pos: RANGE.from,
      to_pos: RANGE.to,
      label: 'the harbour',
    }).id;
  }

  render(
    <Harness
      client={client}
      projectId={projectId}
      {...(options.scheduler ? { scheduler: options.scheduler } : {})}
    >
      <Workspace onLeaveProject={() => {}} />
      <MarkProbe />
    </Harness>,
  );
  await surface();
  return { client, projectId, documentId: documentId!, anchorId };
}

async function surface(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.querySelector<HTMLElement>('.manuscript');
    if (!element) {
      throw new Error('the editor has not mounted yet');
    }
    return element;
  });
}

/** Every anchor decoration currently drawn, as `[id, the words it covers]`. */
function decorations(): [string, string][] {
  return [...document.querySelectorAll<HTMLElement>('.manuscript [data-anchor-id]')].map(
    (element) => [element.getAttribute('data-anchor-id') ?? '', element.textContent ?? ''],
  );
}

async function decoration(anchorId: string): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.querySelector<HTMLElement>(
      `.manuscript [data-anchor-id="${anchorId}"]`,
    );
    if (!element) {
      throw new Error(`no decoration for ${anchorId}`);
    }
    return element;
  });
}

describe('drawing the server’s answer', () => {
  test('an anchor is underlined over its passage when the chapter opens', async () => {
    const { anchorId } = await mount({ seedAnchor: true });

    const drawn = await decoration(anchorId!);
    expect(drawn.textContent).toBe(QUOTE);
    expect(drawn.className).toContain('anchor-ok');
  });

  test('a chapter with no anchors draws none', async () => {
    await mount();

    expect(decorations()).toEqual([]);
  });
});

describe('following the text between saves (D21)', () => {
  test('typing above an anchor leaves it over the same words, with nothing saved', async () => {
    const user = userEvent.setup();
    // A debounce long enough that no save can happen: what is being tested is the client's own
    // mapping, and a save would replace it with the server's answer.
    const { client, documentId, anchorId } = await mount({
      seedAnchor: true,
      scheduler: { delayMs: 60_000 },
    });
    const written = await surface();

    await user.click(written);
    await user.keyboard('Later that year. ');

    await waitFor(() => {
      expect(written.textContent).toContain('Later that year.');
    });
    expect((await decoration(anchorId!)).textContent).toBe(QUOTE);
    expect(client.versionOf(documentId)).toBe(2);
  });
});

describe('reconciling with what the save answers', () => {
  test('an anchor the server calls stale is redrawn as stale', async () => {
    const user = userEvent.setup();
    const { client, documentId, anchorId } = await mount({
      seedAnchor: true,
      scheduler: { delayMs: 5 },
    });
    const written = await surface();

    // What the server's resolver will say about this write. The fake has none of its own.
    client.stageAnchorResolution(documentId, [
      {
        id: anchorId!,
        status: 'stale',
        suggestion: { from_pos: 5, to_pos: 21, text: 'harbour was calm' },
      },
    ]);

    await user.click(written);
    await user.keyboard('X');

    await waitFor(() => {
      expect(decorations()).toHaveLength(1);
    });
    await waitFor(async () => {
      expect((await decoration(anchorId!)).className).toContain('anchor-stale');
    });
  });

  test('and the Marks tab shows the same answer without a refetch', async () => {
    const user = userEvent.setup();
    const { client, documentId, anchorId } = await mount({
      seedAnchor: true,
      scheduler: { delayMs: 5 },
    });
    const written = await surface();
    const before = client.calls.length;

    client.stageAnchorResolution(documentId, [{ id: anchorId!, status: 'stale' }]);
    await user.click(written);
    await user.keyboard('X');
    await waitFor(() => expect(client.versionOf(documentId)).toBe(3));

    await user.click(screen.getByRole('tab', { name: 'Marks' }));

    await waitFor(() => {
      expect(screen.getByText('Lost')).toBeDefined();
    });
    expect(client.calls.slice(before)).not.toContain('listProjectAnchors');
  });
});

describe('a mark that is re-linked while its chapter is open', () => {
  test('the highlight moves to the new passage, not the one it replaced', async () => {
    const user = userEvent.setup();
    const { client, documentId, anchorId } = await mount({
      content: prose('The harbour was grey.', 'He did not look back.'),
      seedAnchor: true,
    });
    expect((await decoration(anchorId!)).textContent).toBe(QUOTE);

    // The repair path's request, exactly as the Marks tab and the selection control send it:
    // a range and the version it was chosen against. The status does not change — it was `ok`
    // and it stays `ok` — so only the range tells the editor anything has happened.
    await user.click(screen.getByRole('button', { name: 'Re-link it elsewhere' }));

    await waitFor(async () => {
      expect((await decoration(anchorId!)).textContent).toBe('did not look');
    });
    expect(client.anchorOf(anchorId!)?.quote).toBe('did not look');
    expect(client.anchorOf(anchorId!)?.document_id).toBe(documentId);
  });
});

describe('marking a passage', () => {
  test('sends the range and the version, and the server’s quote comes back', async () => {
    const user = userEvent.setup();
    const { client, documentId } = await mount();

    await user.click(screen.getByRole('button', { name: 'Mark it' }));

    await waitFor(() => {
      expect(decorations()).toHaveLength(1);
    });
    const [[anchorId, covered]] = decorations() as [[string, string]];
    expect(covered).toBe(QUOTE);

    // The client sent where, not what: the quote is the server's reading of its own text.
    const stored = client.anchorOf(anchorId)!;
    expect(stored.quote).toBe(QUOTE);
    expect(stored.label).toBe('the harbour');
    expect(stored.document_id).toBe(documentId);
    expect(stored.document_version).toBe(client.versionOf(documentId));
  });

  test('the mark survives leaving the chapter and coming back', async () => {
    const user = userEvent.setup();
    const { anchorId } = await mount({ seedAnchor: true, chapters: ['Departure'] });

    await user.click(screen.getByRole('button', { name: 'Departure' }));
    await waitFor(() => expect(decorations()).toEqual([]));

    await user.click(screen.getByRole('button', { name: 'Chapter 1' }));

    await waitFor(async () => {
      expect((await decoration(anchorId!)).textContent).toBe(QUOTE);
    });
  });
});
