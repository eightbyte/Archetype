/**
 * P3-14 — links, citations, and *Add to bible*.
 *
 * The three surfaces that connect the bible to everything else, and the phase's first exit
 * criterion lives in the third of them: an entry created from a selection, carrying an anchor
 * whose quote the **server** derived.
 *
 * ## Why the *Add to bible* gesture is covered in two halves
 *
 * jsdom has no native editing, so a text selection cannot be made through the DOM — the Phase 2
 * deviation `C7`, unchanged. So the control itself is covered against a real editor in
 * `selectionActions.test.tsx`, and everything below the gesture is covered here through a probe
 * that calls exactly what `EditorRegion` calls. The two halves meet at a typed boundary, which is
 * what keeps them honest: a change to either side stops compiling rather than quietly passing.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { useBible } from '../state/BibleContext';
import { useDocument } from '../state/DocumentContext';
import { Workspace } from '../shell/Workspace';
import { INITIAL_UI_STATE } from '../state/uiReducer';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness, prose } from './harness';

const HARBOUR = 'The harbour was grey.';
/** `The harbour was grey.` in one paragraph: text starts at 1, so `harbour was grey` is 5..21. */
const RANGE = { from: 5, to: 21 };
const QUOTE = 'harbour was grey';

interface Seeded {
  client: FakeApiClient;
  projectId: string;
  first: string;
  second: string;
}

async function seed(): Promise<Seeded> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [first] = client.documentIdsOf(projectId);
  await client.saveDocumentContent(first!, prose(HARBOUR), 1);
  const created = await client.createDocument(projectId, 'Departure');
  await client.saveDocumentContent(created.id, prose('He did not look back.'), 1);
  return { client, projectId, first: first!, second: created.id };
}

/**
 * The gesture's stand-in: exactly the two calls `EditorRegion` makes, and nothing else.
 *
 * `addToBible` is the document layer's, because only it can answer which chapter and which
 * version after a flush; `entryCreated` is the bible layer's. Everything below them is the app's.
 */
function AddProbe({ kind, name }: { kind: string; name: string }) {
  const { addToBible } = useDocument();
  const { entryCreated } = useBible();
  return (
    <button
      type="button"
      onClick={() =>
        void addToBible(RANGE.from, RANGE.to, { kind, name })
          .then((created) => entryCreated(created.entry))
          .catch(() => {})
      }
    >
      Add to bible (probe)
    </button>
  );
}

async function open(seeded: Seeded, probe?: { kind: string; name: string }): Promise<HTMLElement> {
  render(
    <Harness
      client={seeded.client}
      projectId={seeded.projectId}
      ui={{ ...INITIAL_UI_STATE, activeOutlineTab: 'bible' }}
      scheduler={{ delayMs: 60_000 }}
    >
      <Workspace onLeaveProject={() => {}} />
      {probe && <AddProbe kind={probe.kind} name={probe.name} />}
    </Harness>,
  );
  const panel = screen.getByRole('tabpanel');
  await waitFor(() => {
    expect(within(panel).queryByTestId('bible-status')).toBeNull();
  });
  return panel;
}

async function openEntry(
  panel: HTMLElement,
  user: ReturnType<typeof userEvent.setup>,
  name: string,
): Promise<void> {
  await waitFor(() => {
    expect(within(panel).getByRole('button', { name })).toBeDefined();
  });
  await user.click(within(panel).getByRole('button', { name }));
  await waitFor(() => {
    expect(within(panel).getByRole('heading', { level: 3, name })).toBeDefined();
  });
}

describe('links on an entry (ruling 7)', () => {
  test('both directions in one list, each labelled from this entry’s end', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const company = seeded.client.seedEntry(seeded.projectId, { kind: 'faction', name: 'The Company' });
    seeded.client.seedLink(seeded.projectId, marlow.id, 'member_of', company.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');

    const links = within(panel).getByRole('region', { name: 'Links' });
    expect(within(links).getByText('is a member of')).toBeDefined();
    expect(within(links).getByRole('button', { name: 'The Company' })).toBeDefined();

    // The same row from the other end, reading the other way round.
    await user.click(within(links).getByRole('button', { name: 'The Company' }));
    await waitFor(() => {
      expect(within(panel).getByRole('heading', { level: 3, name: 'The Company' })).toBeDefined();
    });
    expect(
      within(within(panel).getByRole('region', { name: 'Links' })).getByText('has as a member'),
    ).toBeDefined();
  });

  test('a symmetric relation appears once from each side, never twice from either', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    seeded.client.seedLink(seeded.projectId, marlow.id, 'knows', kurtz.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');

    const links = within(panel).getByRole('region', { name: 'Links' });
    expect(within(links).getAllByText('knows')).toHaveLength(1);
  });

  test('a link is added in the direction the sentence runs, and shows on both entries', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const company = seeded.client.seedEntry(seeded.projectId, { kind: 'faction', name: 'The Company' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');
    await waitFor(() => {
      expect(within(panel).getByLabelText('Link to')).toBeDefined();
    });
    await user.selectOptions(within(panel).getByLabelText('Link to'), company.id);
    await user.selectOptions(within(panel).getByLabelText('Relation'), 'member_of:from');
    await user.type(within(panel).getByLabelText('From (story time)'), 'the first voyage');
    await user.click(within(panel).getByRole('button', { name: 'Add link' }));

    await waitFor(() => {
      expect(seeded.client.linksOf(seeded.projectId)).toHaveLength(1);
    });
    const [link] = seeded.client.linksOf(seeded.projectId);
    // The direction the vocabulary declares: character → faction, never silently reversed.
    expect(link?.from_entry).toBe(marlow.id);
    expect(link?.to_entry).toBe(company.id);
    // Stored, displayed, never interpreted (D9).
    expect(link?.since).toBe('the first voyage');
  });

  test('an illegal relation is never offered, so an illegal link cannot be built', async () => {
    // § 8's step 5. The server refuses it too — that is where the rule lives — but a form that
    // offers a choice and then rejects it has taught the writer something untrue.
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'thread', name: 'The reckoning' });
    const knife = seeded.client.seedEntry(seeded.projectId, { kind: 'item', name: 'The knife' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'The reckoning');
    await waitFor(() => {
      expect(within(panel).getByLabelText('Link to')).toBeDefined();
    });
    await user.selectOptions(within(panel).getByLabelText('Link to'), knife.id);

    expect(within(panel).queryByLabelText('Relation')).toBeNull();
    expect(within(panel).getByText(/Nothing in the vocabulary joins a thread to a item/)).toBeDefined();
  });

  test('a link can be removed, and neither endpoint is touched', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    seeded.client.seedLink(seeded.projectId, marlow.id, 'knows', kurtz.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');
    await user.click(within(panel).getByRole('button', { name: 'Remove knows Kurtz' }));

    await waitFor(() => {
      expect(seeded.client.linksOf(seeded.projectId)[0]?.deleted_at).not.toBeNull();
    });
    expect(seeded.client.entryOf(marlow.id)?.deleted_at).toBeNull();
    expect(seeded.client.entryOf(kurtz.id)?.deleted_at).toBeNull();
  });

  test('a link’s bounds can be changed without touching its endpoints or its relation', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    const link = seeded.client.seedLink(seeded.projectId, marlow.id, 'knows', kurtz.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');
    await user.click(within(panel).getByRole('button', { name: 'Change when knows Kurtz holds' }));
    await user.type(within(panel).getByLabelText('Until (story time)'), 'the inner station');
    await user.click(within(panel).getByRole('button', { name: 'Save when this link holds' }));

    await waitFor(() => {
      const stored = seeded.client.linksOf(seeded.projectId).find((row) => row.id === link.id);
      expect(stored?.until).toBe('the inner station');
    });
    const stored = seeded.client.linksOf(seeded.projectId).find((row) => row.id === link.id);
    expect(stored?.relation).toBe('knows');
    expect(stored?.from_entry).toBe(marlow.id);
  });
});

describe('citations on an entry (P3-7)', () => {
  test('each shows its quote, its chapter, its role, and its status', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const entry = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const anchor = seeded.client.seedAnchor(seeded.first, {
      quote: QUOTE,
      from_pos: RANGE.from,
      to_pos: RANGE.to,
    });
    seeded.client.seedCitation(entry.id, anchor.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');

    const citations = within(panel).getByRole('region', { name: 'Citations' });
    expect(within(citations).getByRole('button', { name: QUOTE })).toBeDefined();
    expect(within(citations).getByText('source')).toBeDefined();
    expect(within(citations).getByText(/Chapter 1/)).toBeDefined();
    expect(within(citations).getByText('Found')).toBeDefined();
  });

  test('a stale citation says so and reaches the *Marks* repair flow rather than growing one', async () => {
    // Ruling 5: *Marks* is where an anchor is repaired, and it stays exactly as it is. Two
    // surfaces that both re-link an anchor is two suggestion protocols to keep in step.
    const user = userEvent.setup();
    const seeded = await seed();
    const entry = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const anchor = seeded.client.seedAnchor(seeded.first, { quote: QUOTE, status: 'stale' });
    seeded.client.seedCitation(entry.id, anchor.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');

    const citations = within(panel).getByRole('region', { name: 'Citations' });
    expect(within(citations).getByText('Lost')).toBeDefined();
    await user.click(within(citations).getByRole('button', { name: 'Repair in Marks' }));

    expect(screen.getByRole('tab', { name: 'Marks' }).getAttribute('aria-selected')).toBe('true');
  });

  test('an orphaned citation says its chapter was deleted, and does not offer to navigate', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const entry = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const anchor = seeded.client.seedAnchor(seeded.second, { quote: 'did not look' });
    seeded.client.seedCitation(entry.id, anchor.id);
    await seeded.client.deleteDocument(seeded.second);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');

    const citations = within(panel).getByRole('region', { name: 'Citations' });
    expect(within(citations).getByText('Chapter deleted')).toBeDefined();
    expect(
      within(citations).getByRole('button', { name: 'did not look' }).hasAttribute('disabled'),
    ).toBe(true);
  });

  test('clicking a citation opens its chapter', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const entry = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const anchor = seeded.client.seedAnchor(seeded.second, { quote: 'did not look' });
    seeded.client.seedCitation(entry.id, anchor.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');
    await user.click(within(panel).getByRole('button', { name: 'did not look' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Rename Departure' })).toBeDefined();
    });
  });

  test('removing a citation leaves the anchor exactly where it was', async () => {
    // The entry keeps what a person typed and loses one reason to believe it; the anchor is a
    // fact about the manuscript, and *Marks* is where one is deleted.
    const user = userEvent.setup();
    const seeded = await seed();
    const entry = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const anchor = seeded.client.seedAnchor(seeded.first, { quote: QUOTE });
    seeded.client.seedCitation(entry.id, anchor.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Marlow');
    await user.click(
      within(panel).getByRole('button', { name: `Remove the citation of “${QUOTE}”` }),
    );

    await waitFor(() => {
      expect(within(panel).queryByRole('button', { name: QUOTE })).toBeNull();
    });
    expect(seeded.client.anchorOf(anchor.id)).toBeDefined();
    expect(seeded.client.entryOf(entry.id)?.deleted_at).toBeNull();
  });
});

describe('Add to bible (P3-7, ruling 8)', () => {
  test('makes the entry, the anchor, and the citation, and the quote is the server’s', async () => {
    const user = userEvent.setup();
    const seeded = await seed();

    const panel = await open(seeded, { kind: 'character', name: 'Marlow' });
    await user.click(screen.getByRole('button', { name: 'Add to bible (probe)' }));

    // The new entry opens: the writer has just made it and the next thing they want is the form
    // with the rest of its fields on it.
    await waitFor(() => {
      expect(within(panel).getByRole('heading', { level: 3, name: 'Marlow' })).toBeDefined();
    });

    const citations = within(panel).getByRole('region', { name: 'Citations' });
    // The client sent a range and never a quote; these are the words the store read out of the
    // text it holds, so an entry created from a selection cannot cite a passage the manuscript
    // does not contain.
    expect(within(citations).getByRole('button', { name: QUOTE })).toBeDefined();
  });

  test('the anchor it mints is an ordinary mark, and reaches the *Marks* tab', async () => {
    const user = userEvent.setup();
    const seeded = await seed();

    await open(seeded, { kind: 'character', name: 'Marlow' });
    await user.click(screen.getByRole('button', { name: 'Add to bible (probe)' }));

    await user.click(screen.getByRole('tab', { name: 'Marks' }));
    const marks = screen.getByRole('tabpanel');
    await waitFor(() => {
      expect(within(marks).getByRole('button', { name: QUOTE })).toBeDefined();
    });
  });

  test('a stale document version leaves no anchor, no entry, and no citation', async () => {
    // One transaction over three tables (`B1`). The guard runs first, so a refusal writes
    // nothing at all — not the anchor, not the entry, not the join.
    const user = userEvent.setup();
    const seeded = await seed();

    const panel = await open(seeded, { kind: 'character', name: 'Marlow' });
    // Somebody else wrote the chapter behind the app's back.
    seeded.client.writeBehindTheScenes(seeded.first, prose('The harbour was calm.'));
    await user.click(screen.getByRole('button', { name: 'Add to bible (probe)' }));

    await waitFor(() => {
      expect(seeded.client.calls).toContain('createEntryFromRange');
    });
    expect((await seeded.client.listProjectAnchors(seeded.projectId)).anchors).toHaveLength(0);
    expect((await seeded.client.listEntries(seeded.projectId)).entries).toHaveLength(0);
    expect(within(panel).getByTestId('bible-empty')).toBeDefined();
  });
});
