/**
 * P3-12 — the Bible tab: browsing, the review queue, and the deleted tray.
 *
 * The phase's headline is here. Two of these tests are the exit criteria in miniature:
 *
 * * **the review queue lists exactly the flagged entries and empties as they are cleared** —
 *   which is half of § 5's second criterion, and the reason a retcon is worth flagging at all;
 * * **a deleted entry leaves every list and count and comes back with everything** — § 5's
 *   fourth, and D25's whole justification.
 *
 * The tab renders the **real** served definition: the fake reads the contract fixture, so these
 * are the seven kinds with the fields the server actually declares (D26).
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { ApiError } from '../api';
import { Workspace } from '../shell/Workspace';
import { INITIAL_UI_STATE } from '../state/uiReducer';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness, prose } from './harness';

interface Seeded {
  client: FakeApiClient;
  projectId: string;
  first: string;
}

async function seed(): Promise<Seeded> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [first] = client.documentIdsOf(projectId);
  await client.saveDocumentContent(first!, prose('The harbour was grey.'), 1);
  return { client, projectId, first: first! };
}

/** Mount the workspace with the Bible tab already showing. */
async function open(seeded: Seeded): Promise<HTMLElement> {
  render(
    <Harness
      client={seeded.client}
      projectId={seeded.projectId}
      ui={{ ...INITIAL_UI_STATE, activeOutlineTab: 'bible' }}
      scheduler={{ delayMs: 60_000 }}
    >
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  const panel = screen.getByRole('tabpanel');
  await waitFor(() => {
    expect(within(panel).queryByTestId('bible-status')).toBeNull();
  });
  return panel;
}

describe('browsing the bible', () => {
  test('says so plainly when there is nothing in it yet', async () => {
    const panel = await open(await seed());

    expect(within(panel).getByTestId('bible-empty').textContent).toContain('The bible is empty');
  });

  test('groups entries by kind, in the definition’s order', async () => {
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'place', name: 'The Quay' });
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });

    const panel = await open(seeded);

    const headings = within(panel)
      .getAllByRole('heading', { level: 4 })
      .map((heading) => heading.textContent);
    expect(headings).toEqual(['Characters', 'Places']);
  });

  test('the kind counts are live and unfiltered, so a filtered list still counts everything', async () => {
    // The reason `EntryListOut.counts` exists at all (`C6`): "how many characters are there" is
    // answered while only the places are showing.
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    seeded.client.seedEntry(seeded.projectId, { kind: 'place', name: 'The Quay' });

    const panel = await open(seeded);
    await user.selectOptions(within(panel).getByLabelText('Filter by kind'), 'place');

    await waitFor(() => {
      expect(within(panel).queryByRole('button', { name: 'Marlow' })).toBeNull();
    });
    expect(within(panel).getByRole('button', { name: 'The Quay' })).toBeDefined();
    // Still says there are two characters, while showing none of them.
    expect(within(panel).getByRole('option', { name: 'Characters (2)' })).toBeDefined();
    expect(within(panel).getByTestId('bible-total').textContent).toContain('3 entries');
  });

  test('the search box filters, and does not ask the server once per keystroke', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    seeded.client.seedEntry(seeded.projectId, {
      kind: 'character',
      name: 'Kurtz',
      summary: 'the man at the end of the river',
    });

    const panel = await open(seeded);
    const before = seeded.client.calls.filter((call) => call === 'listEntries').length;
    await user.type(within(panel).getByLabelText('Search the bible'), 'kurtz');

    await waitFor(() => {
      expect(within(panel).queryByRole('button', { name: 'Marlow' })).toBeNull();
    });
    expect(within(panel).getByRole('button', { name: 'Kurtz' })).toBeDefined();
    const after = seeded.client.calls.filter((call) => call === 'listEntries').length;
    // Five keystrokes; the debounce is what P3-12 asks for, so this must be far short of five.
    expect(after - before).toBeLessThan(5);
  });

  test('the search filter reaches names, aliases, and summaries', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, {
      kind: 'character',
      name: 'Kurtz',
      attributes: { aliases: ['the agent'] },
    });

    const panel = await open(seeded);
    await user.type(within(panel).getByLabelText('Search the bible'), 'agent');

    await waitFor(() => {
      expect(within(panel).getByRole('button', { name: 'Kurtz' })).toBeDefined();
    });
  });

  test('a search that matches nothing says so, and says it is a search', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });

    const panel = await open(seeded);
    await user.type(within(panel).getByLabelText('Search the bible'), 'zzz');

    await waitFor(() => {
      expect(within(panel).getByTestId('bible-empty').textContent).toContain('Nothing matches');
    });
  });

  test('the grouped and flat views show the same entries', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'place', name: 'The Quay' });
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });

    const panel = await open(seeded);
    await user.click(within(panel).getByRole('button', { name: 'Grouped' }));

    expect(within(panel).queryByRole('heading', { name: 'Places' })).toBeNull();
    expect(within(panel).getByRole('button', { name: 'Marlow' })).toBeDefined();
    expect(within(panel).getByRole('button', { name: 'The Quay' })).toBeDefined();
  });
});

describe('the review queue (D27)', () => {
  test('is empty when nothing has been disturbed, and says what would fill it', async () => {
    const user = userEvent.setup();
    const panel = await open(await seed());

    await user.click(within(panel).getByRole('button', { name: 'Review (0)' }));

    expect(within(panel).getByTestId('review-empty').textContent).toContain('Nothing is waiting');
  });

  test('lists exactly the flagged entries, with the reason that flagged them', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const quay = seeded.client.seedEntry(seeded.projectId, { kind: 'place', name: 'The Quay' });
    seeded.client.seedLink(seeded.projectId, marlow.id, 'knows', kurtz.id);
    // A retcon: the name moved.
    await seeded.client.updateEntry(kurtz.id, { revision: 1, name: 'Mister Kurtz' });

    const panel = await open(seeded);
    await user.click(within(panel).getByRole('button', { name: 'Review (1)' }));

    expect(within(panel).getByRole('button', { name: 'Marlow' })).toBeDefined();
    expect(within(panel).getByText(/Mister Kurtz changed at revision 2/)).toBeDefined();
    // Nothing unlinked is flagged — the honest limit D27 ships with.
    expect(within(panel).queryByRole('button', { name: 'The Quay' })).toBeNull();
    expect(seeded.client.entryOf(quay.id)?.needs_review).toBe(false);
  });

  test('clearing one empties it, and flags nothing further', async () => {
    // The clause that decides whether the queue is usable at all: clearing a review is never
    // itself a retcon, so working through the queue does not regenerate it (P3-4).
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    seeded.client.seedLink(seeded.projectId, marlow.id, 'knows', kurtz.id);
    await seeded.client.updateEntry(kurtz.id, { revision: 1, name: 'Mister Kurtz' });

    const panel = await open(seeded);
    await user.click(within(panel).getByRole('button', { name: 'Review (1)' }));
    await user.click(within(panel).getByRole('button', { name: 'Reviewed' }));

    await waitFor(() => {
      expect(within(panel).getByTestId('review-empty')).toBeDefined();
    });
    expect(within(panel).getByRole('button', { name: 'Review (0)' })).toBeDefined();
    // Kurtz was not re-flagged by Marlow being cleared.
    expect(seeded.client.entryOf(kurtz.id)?.needs_review).toBe(false);
  });

  test('an edit that is not a retcon flags nobody', async () => {
    // The other half of D27, and the one that keeps the queue worth reading: a body-only edit.
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    seeded.client.seedLink(seeded.projectId, marlow.id, 'knows', kurtz.id);
    await seeded.client.updateEntry(kurtz.id, { revision: 1, body_md: 'A note about the river.' });

    const panel = await open(seeded);

    expect(within(panel).getByRole('button', { name: 'Review (0)' })).toBeDefined();
    expect(seeded.client.entryOf(marlow.id)?.needs_review).toBe(false);
  });
});

describe('the deleted tray (D25)', () => {
  test('holds a deleted entry, which is out of the browse list and the counts', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    await seeded.client.deleteEntry(kurtz.id);

    const panel = await open(seeded);

    expect(within(panel).queryByRole('button', { name: 'Kurtz' })).toBeNull();
    expect(within(panel).getByTestId('bible-total').textContent).toContain('0 entries');

    await user.click(within(panel).getByRole('button', { name: 'Deleted' }));
    expect(within(panel).getByRole('button', { name: 'Kurtz' })).toBeDefined();
  });

  test('restoring one brings it back into the list and the counts', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    await seeded.client.deleteEntry(kurtz.id);

    const panel = await open(seeded);
    await user.click(within(panel).getByRole('button', { name: 'Deleted' }));
    await user.click(within(panel).getByRole('button', { name: 'Restore' }));

    await waitFor(() => {
      expect(seeded.client.entryOf(kurtz.id)?.deleted_at).toBeNull();
    });
    await user.click(within(panel).getByRole('button', { name: /^Entries/ }));
    await waitFor(() => {
      expect(within(panel).getByRole('button', { name: 'Kurtz' })).toBeDefined();
    });
  });

  test('a deleted entry leaves both ends of every link, and its links are not deleted', async () => {
    // Nothing cascades, which is what makes restore exact: the endpoint's deletion *hides* the
    // link through the three-way predicate rather than writing to it (ruling 9).
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    const link = seeded.client.seedLink(seeded.projectId, marlow.id, 'knows', kurtz.id);
    await seeded.client.deleteEntry(kurtz.id);

    expect((await seeded.client.listEntryLinks(marlow.id)).links).toHaveLength(0);
    expect(seeded.client.linksOf(seeded.projectId).find((row) => row.id === link.id)?.deleted_at)
      .toBeNull();

    await seeded.client.restoreEntry(kurtz.id);
    expect((await seeded.client.listEntryLinks(marlow.id)).links).toHaveLength(1);
  });
});

describe('when the bible cannot be read', () => {
  test('the tab says so and offers to try again, and the editor keeps working', async () => {
    // The P1-12 rule, one level in: a bible that cannot draw must not take the table of contents
    // down with it, let alone the editor (P3-12).
    const seeded = await seed();
    seeded.client.failNext(
      'getBibleSchema',
      new ApiError(500, 'internal_error', 'something went wrong', null),
    );

    render(
      <Harness
        client={seeded.client}
        projectId={seeded.projectId}
        ui={{ ...INITIAL_UI_STATE, activeOutlineTab: 'bible' }}
        scheduler={{ delayMs: 60_000 }}
      >
        <Workspace onLeaveProject={() => {}} />
      </Harness>,
    );

    const panel = screen.getByRole('tabpanel');
    await waitFor(() => {
      expect(within(panel).getByTestId('bible-status').textContent).toContain(
        'Could not read the bible',
      );
    });
    expect(within(panel).getByRole('button', { name: 'Try again' })).toBeDefined();
    expect(document.querySelector('.manuscript')).not.toBeNull();
  });

  test('a refresh that does not land leaves the rows that are on screen', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });

    const panel = await open(seeded);
    seeded.client.failNext(
      'listEntries',
      new ApiError(500, 'internal_error', 'the list could not be read', null),
    );
    await user.selectOptions(within(panel).getByLabelText('Filter by kind'), 'place');

    await waitFor(() => {
      expect(within(panel).getByText('the list could not be read')).toBeDefined();
    });
    expect(within(panel).getByRole('button', { name: 'Marlow' })).toBeDefined();
  });
});

describe('story-time (D28)', () => {
  test('shows the order, the unplaced, and a contradiction naming both events', async () => {
    // § 8's steps 6 and 7. The answer is the **server's** — the fake holds no topological sort,
    // and must not grow one.
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.stageStoryTime({
      order: [
        { entry_id: 'ent_a', name: 'The departure', label: 'first light', sort_key: 1, era: 'Before' },
        { entry_id: 'ent_b', name: 'The river', label: 'high summer', sort_key: 2, era: 'Before' },
      ],
      unplaced: [
        { entry_id: 'ent_c', name: 'A rumour', label: 'nobody agrees when', sort_key: null, era: null },
      ],
      contradictions: [
        {
          kind: 'sort_key_inversion',
          events: ['ent_b', 'ent_a'],
          detail: 'The river comes before The departure, but its sort key is the greater',
        },
      ],
      eras: [{ era: 'Before', rank: 1 }],
    });

    const panel = await open(seeded);
    await user.click(within(panel).getByRole('button', { name: 'Story-time' }));

    await waitFor(() => {
      expect(within(panel).getByText(/The order disagrees with the sort keys/)).toBeDefined();
    });
    expect(within(panel).getByText(/its sort key is the greater/)).toBeDefined();
    // A contradiction never costs the rest of the graph.
    const order = within(panel).getByRole('region', { name: 'Story order' });
    expect(within(order).getAllByRole('button').map((button) => button.textContent)).toEqual([
      'The departure — first light',
      'The river — high summer',
    ]);
    // Not ordered arbitrarily, not dropped.
    const unplaced = within(panel).getByRole('region', { name: 'Unplaced events' });
    expect(within(unplaced).getByRole('button', { name: /A rumour/ })).toBeDefined();
  });

  test('says so plainly when there are no events at all', async () => {
    const user = userEvent.setup();
    const panel = await open(await seed());

    await user.click(within(panel).getByRole('button', { name: 'Story-time' }));

    await waitFor(() => {
      expect(within(panel).getByText(/No events yet/)).toBeDefined();
    });
  });
});
