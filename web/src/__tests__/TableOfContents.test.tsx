/**
 * P1-11 — the table of contents, and jumping by heading ordinal.
 *
 * The three things this has to do, and all three are here: render across the whole manuscript
 * while one chapter is loaded (D2), move as headings are typed in the open chapter (D18), and
 * take a click on a heading in *another* chapter to that heading.
 *
 * Jumping is verified through `scrollIntoView`, spied on rather than implemented: jsdom has no
 * scrolling. What is actually being asserted is the part that can be wrong — that the right
 * element was chosen, by ordinal, after the right document finished loading.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { chapter, Harness } from './harness';

/** Elements `scrollIntoView` was called on, most recent last. */
let scrolled: Element[] = [];

beforeEach(() => {
  scrolled = [];
  vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(function (this: Element) {
    scrolled.push(this);
  });
});

/** Two chapters with headings, opened on the first. */
async function manuscript(options: { scheduler?: { delayMs?: number } } = {}) {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [first] = client.documentIdsOf(projectId);

  await client.saveDocumentContent(
    first!,
    chapter([1, 'Arrival'], 'The harbour was grey and cold.', [2, 'The Customs House']),
    1,
  );
  const second = await client.createDocument(projectId, 'Chapter 2');
  await client.saveDocumentContent(
    second.id,
    chapter([1, 'Departure'], 'A rope, a lamp.', [2, 'The Road North']),
    1,
  );

  render(
    <Harness
      client={client}
      projectId={projectId}
      {...(options.scheduler ? { scheduler: options.scheduler } : {})}
    >
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  await screen.findByRole('button', { name: /^Rename / });
  return { client, projectId, first: first!, second: second.id };
}

/**
 * The same two chapters, but the open one is empty — a chapter being drafted.
 *
 * The live-outline tests need to type headings *into* a chapter, and they need to do it without
 * anything being saved, which rules out reaching for the toolbar: clicking it blurs the editor,
 * and a blur flushes (P1-10). So they type, and the heading comes from the markdown input rule.
 */
async function draft(options: { scheduler?: { delayMs?: number } } = {}) {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [first] = client.documentIdsOf(projectId);
  const second = await client.createDocument(projectId, 'Chapter 2');
  await client.saveDocumentContent(
    second.id,
    chapter([1, 'Departure'], 'A rope, a lamp.', [2, 'The Road North']),
    1,
  );

  render(
    <Harness
      client={client}
      projectId={projectId}
      {...(options.scheduler ? { scheduler: options.scheduler } : {})}
    >
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  await screen.findByRole('button', { name: /^Rename / });
  return { client, projectId, first: first!, second: second.id };
}

function toc(): HTMLElement {
  return screen.getByRole('tabpanel');
}

async function surface(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.querySelector<HTMLElement>('.manuscript');
    if (!element) throw new Error('the editor has not mounted yet');
    return element;
  });
}

describe('rendering', () => {
  test('spans every chapter while only one is loaded', async () => {
    await manuscript();
    const panel = toc();

    expect(within(panel).getByRole('button', { name: 'Chapter 1' })).toBeDefined();
    expect(within(panel).getByRole('button', { name: 'Chapter 2' })).toBeDefined();
    // Headings from the chapter that is *not* open — they came from the outline route.
    expect(within(panel).getByRole('button', { name: 'Departure' })).toBeDefined();
    expect(within(panel).getByRole('button', { name: 'The Road North' })).toBeDefined();
  });

  test('shows word counts per chapter and for the manuscript', async () => {
    await manuscript();

    expect(within(toc()).getByTestId('toc-total').textContent).toBe('2 chapters · 18 words');
  });

  test('a chapter can be collapsed and reopened', async () => {
    const user = userEvent.setup();
    await manuscript();

    await user.click(
      within(toc()).getByRole('button', { name: 'Hide the headings in Chapter 2' }),
    );
    expect(within(toc()).queryByRole('button', { name: 'Departure' })).toBeNull();

    await user.click(
      within(toc()).getByRole('button', { name: 'Show the headings in Chapter 2' }),
    );
    expect(within(toc()).getByRole('button', { name: 'Departure' })).toBeDefined();
  });

  test('the open chapter is marked as the current one', async () => {
    await manuscript();
    expect(
      within(toc()).getByRole('button', { name: 'Chapter 1' }).getAttribute('aria-current'),
    ).toBe('true');
  });
});

describe('staying live as the writer types (D18)', () => {
  test('a heading typed into the open chapter appears before anything is saved', async () => {
    const user = userEvent.setup();
    // Long debounce and no blur: nothing can have been saved, so only the client mirror can be
    // the source of what the outline is showing.
    const { client, first } = await draft({ scheduler: { delayMs: 60_000 } });
    const written = await surface();

    await user.click(written);
    await user.keyboard('# The Harbour');

    await waitFor(() => {
      expect(within(toc()).getByRole('button', { name: 'The Harbour' })).toBeDefined();
    });
    expect(within(written).getByRole('heading', { level: 1 }).textContent).toBe('The Harbour');
    expect(client.versionOf(first)).toBe(1);
  });

  test('the word count moves with the mirror too', async () => {
    const user = userEvent.setup();
    const { client, first } = await draft({ scheduler: { delayMs: 60_000 } });
    const written = await surface();

    expect(within(toc()).getByTestId('toc-total').textContent).toBe('2 chapters · 8 words');

    await user.click(written);
    await user.keyboard('The harbour was grey.');

    await waitFor(() => {
      expect(within(toc()).getByTestId('toc-total').textContent).toBe('2 chapters · 12 words');
    });
    expect(client.versionOf(first)).toBe(1);
  });

  test('a chapter that is not open keeps the outline the server gave it', async () => {
    const user = userEvent.setup();
    await draft({ scheduler: { delayMs: 60_000 } });
    const written = await surface();

    await user.click(written);
    await user.keyboard('# Arrival');

    expect(within(toc()).getByRole('button', { name: 'Departure' })).toBeDefined();
    expect(within(toc()).getByRole('button', { name: 'The Road North' })).toBeDefined();
  });
});

describe('jumping to a heading', () => {
  test('within the open chapter, scrolls straight to it', async () => {
    const user = userEvent.setup();
    await manuscript();
    await surface();

    await user.click(within(toc()).getByRole('button', { name: 'The Customs House' }));

    await waitFor(() => expect(scrolled.length).toBeGreaterThan(0));
    expect(scrolled[scrolled.length - 1]?.textContent).toBe('The Customs House');
  });

  test('across chapters, loads the other one first and then scrolls', async () => {
    const user = userEvent.setup();
    const { client } = await manuscript();
    await surface();

    const before = client.calls.length;
    await user.click(within(toc()).getByRole('button', { name: 'The Road North' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^Rename / }).textContent).toBe('Chapter 2');
    });
    expect(client.calls.slice(before)).toContain('getDocument');

    await waitFor(() => {
      expect(scrolled[scrolled.length - 1]?.textContent).toBe('The Road North');
    });
  });

  test('the target is the nth heading, not the nth matching text', async () => {
    const user = userEvent.setup();
    const client = new FakeApiClient();
    const projectId = client.seedProject('Echoes');
    const [documentId] = client.documentIdsOf(projectId);
    // Three headings with the same words: only the ordinal tells them apart, which is exactly
    // the case an anchor will have to handle properly in Phase 2.
    await client.saveDocumentContent(
      documentId!,
      chapter([1, 'The Room'], 'a', [1, 'The Room'], 'b', [1, 'The Room']),
      1,
    );

    render(
      <Harness client={client} projectId={projectId}>
        <Workspace onLeaveProject={() => {}} />
      </Harness>,
    );
    await surface();

    const targets = within(toc()).getAllByRole('button', { name: 'The Room' });
    expect(targets).toHaveLength(3);
    await user.click(targets[2]!);

    await waitFor(() => expect(scrolled.length).toBeGreaterThan(0));
    const headings = [...document.querySelectorAll('.manuscript h1')];
    expect(scrolled[scrolled.length - 1]).toBe(headings[2]);
  });

  test('an empty heading is still a target, and still numbered', async () => {
    const client = new FakeApiClient();
    const projectId = client.seedProject('Drafting');
    const [documentId] = client.documentIdsOf(projectId);
    await client.saveDocumentContent(
      documentId!,
      chapter([1, ''], 'a paragraph', [2, 'Named']),
      1,
    );

    render(
      <Harness client={client} projectId={projectId}>
        <Workspace onLeaveProject={() => {}} />
      </Harness>,
    );
    await surface();

    // Skipping the empty one would renumber every heading below it (P1-7).
    expect(within(toc()).getByText('Untitled heading')).toBeDefined();
    expect(within(toc()).getByRole('button', { name: 'Named' })).toBeDefined();
  });
});

describe('adding a chapter', () => {
  test('appends it, opens it, and shows it in the contents', async () => {
    const user = userEvent.setup();
    await manuscript();

    await user.click(within(toc()).getByRole('button', { name: 'New chapter' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^Rename / }).textContent).toBe('Chapter 3');
    });
    expect(within(toc()).getByTestId('toc-total').textContent).toBe('3 chapters · 18 words');
  });
});
