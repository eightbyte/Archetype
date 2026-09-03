/**
 * P3-13 — the generic form, the retcon control, and an entry's history.
 *
 * One form for seven kinds is the decision that keeps this phase finishable (D26), so the tests
 * are about the *generic* claim rather than about any one kind: a kind shows its own fields and
 * nothing else, all six types render and round-trip, and a seventh type fails loudly rather than
 * rendering nothing.
 *
 * The other two claims here are the ones a writer would notice if they broke:
 *
 * * a `409` **stops** and keeps the typing on screen. It never merges (D19, ruling 3);
 * * the retcon box comes up with the computed default and the reason it came up that way, and
 *   overriding it changes what the save does (D27).
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { ApiError } from '../api';
import type { FieldDefinition } from '../api/types';
import { FieldInput } from '../panels/EntryFields';
import { Workspace } from '../shell/Workspace';
import { INITIAL_UI_STATE } from '../state/uiReducer';
import { FakeApiClient } from './fakes/fakeApiClient';
import { Harness, prose } from './harness';

interface Seeded {
  client: FakeApiClient;
  projectId: string;
}

async function seed(): Promise<Seeded> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [first] = client.documentIdsOf(projectId);
  await client.saveDocumentContent(first!, prose('The harbour was grey.'), 1);
  return { client, projectId };
}

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

/** Open one entry's detail view by name. */
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

describe('one form, rendered from the definition (D26)', () => {
  test('a kind shows its own fields and nothing else', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');

    // The character's eight, from the served definition.
    for (const label of ['Also known as', 'Role', 'Pronouns', 'Age', 'Appearance', 'Home']) {
      expect(within(panel).getByText(label)).toBeDefined();
    }
    // A fact's required field, which a character does not have.
    expect(within(panel).queryByText('What is true')).toBeNull();
  });

  test('the kind cannot be changed after creation — there is no input for it', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');

    // Refused rather than discouraged: every attribute was validated against this kind's field
    // list, so the wrong kind is fixed by creating the right entry and deleting the wrong one.
    expect(within(panel).queryByLabelText('Kind')).toBeNull();
    expect(within(panel).getByText('Character')).toBeDefined();
  });

  test('text, long text, list-of-text, enum, and entry_ref all round-trip', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'place', name: 'The Quay' });
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');

    await user.type(within(panel).getByLabelText('Pronouns'), 'he/him');
    await user.type(within(panel).getByLabelText('Appearance'), 'Gaunt, and taller than the room.');
    await user.selectOptions(within(panel).getByLabelText('Role'), 'antagonist');
    await user.click(within(panel).getByRole('button', { name: 'Add also known as' }));
    await user.type(within(panel).getByLabelText('Also known as 1'), 'the agent');
    await user.selectOptions(within(panel).getByLabelText('Home'), 'The Quay');
    await user.click(within(panel).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(seeded.client.entryOf(kurtz.id)?.revision).toBe(2);
    });
    const stored = seeded.client.entryOf(kurtz.id)!;
    expect(stored.attributes['pronouns']).toBe('he/him');
    expect(stored.attributes['appearance']).toBe('Gaunt, and taller than the room.');
    expect(stored.attributes['role']).toBe('antagonist');
    expect(stored.attributes['aliases']).toEqual(['the agent']);
    // An entry_ref stores an id, not a name — it is a property of this entry, not a link.
    expect(stored.attributes['home']).toMatch(/^ent_/);
  });

  test('story-time takes a label, a sort key, and an era, all optional (D28)', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const event = seeded.client.seedEntry(seeded.projectId, {
      kind: 'event',
      name: 'The departure',
    });

    const panel = await open(seeded);
    await openEntry(panel, user, 'The departure');

    await user.type(within(panel).getByLabelText('When — how it reads'), 'the first grey morning');
    await user.type(within(panel).getByLabelText('When — sort key'), '2.5');
    await user.type(within(panel).getByLabelText('When — era'), 'Before');
    await user.click(within(panel).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(seeded.client.entryOf(event.id)?.revision).toBe(2);
    });
    expect(seeded.client.entryOf(event.id)?.attributes['story_time']).toEqual({
      label: 'the first grey morning',
      // A float, so an event can be inserted between two others without renumbering.
      sort_key: 2.5,
      era: 'Before',
    });
  });

  test('a blank line in a list is not an alias', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');
    await user.click(within(panel).getByRole('button', { name: 'Add also known as' }));
    await user.click(within(panel).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(seeded.client.entryOf(kurtz.id)?.revision).toBe(2);
    });
    expect(seeded.client.entryOf(kurtz.id)?.attributes['aliases']).toEqual([]);
  });

  test('a field type with no renderer fails loudly rather than rendering nothing', () => {
    // The client half of the closed list (P3-5, D26). A form that silently dropped a field
    // somebody typed into is the failure this closure exists to prevent.
    const field: FieldDefinition = {
      name: 'eye_colour',
      type: 'colour',
      label: 'Eye colour',
      required: false,
      help: '',
      members: [],
      kinds: [],
    };

    expect(() =>
      render(
        <FieldInput
          field={field}
          value=""
          onChange={() => {}}
          disabled={false}
          error={null}
          candidates={[]}
        />,
      ),
    ).toThrow(/no renderer for the field type 'colour'/);
  });
});

describe('the retcon control sits on the save (D27)', () => {
  test('comes up unchecked when nothing established has moved, and says so', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');

    const box = within(panel).getByRole('checkbox', { name: /Treat this as a retcon/ });
    expect((box as HTMLInputElement).checked).toBe(false);
    expect(within(panel).getByText(/Nothing that established facts depend on has moved/)).toBeDefined();
  });

  test('comes up checked when the name moves, with the reason it came up checked', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');
    await user.type(within(panel).getByLabelText('Name'), '!');

    const box = within(panel).getByRole('checkbox', { name: /Treat this as a retcon/ });
    expect((box as HTMLInputElement).checked).toBe(true);
    expect(within(panel).getByText(/The name changed/)).toBeDefined();
  });

  test('a body-only edit does not come up checked', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');
    await user.type(within(panel).getByLabelText('Notes'), 'He is not what the river said.');

    expect(
      (within(panel).getByRole('checkbox', { name: /Treat this as a retcon/ }) as HTMLInputElement)
        .checked,
    ).toBe(false);
  });

  test('an untouched save takes the store’s own answer, and flags the neighbours', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    seeded.client.seedLink(seeded.projectId, marlow.id, 'knows', kurtz.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');
    await user.clear(within(panel).getByLabelText('Name'));
    await user.type(within(panel).getByLabelText('Name'), 'Mister Kurtz');
    await user.click(within(panel).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(seeded.client.entryOf(marlow.id)?.needs_review).toBe(true);
    });
    // The writer is told what the save did at the moment it happens, not by opening the queue.
    expect(await screen.findByText(/Saved as a retcon/)).toBeDefined();
  });

  test('unchecking it changes what the save does — nobody is flagged', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    const marlow = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Marlow' });
    seeded.client.seedLink(seeded.projectId, marlow.id, 'knows', kurtz.id);

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');
    await user.clear(within(panel).getByLabelText('Name'));
    await user.type(within(panel).getByLabelText('Name'), 'Mister Kurtz');
    await user.click(within(panel).getByRole('checkbox', { name: /Treat this as a retcon/ }));
    await user.click(within(panel).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(seeded.client.entryOf(kurtz.id)?.name).toBe('Mister Kurtz');
    });
    expect(seeded.client.entryOf(marlow.id)?.needs_review).toBe(false);
  });
});

describe('when the entry has moved on (D19, ruling 3)', () => {
  test('the save stops, says so, and does not lose the writer’s typing', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');
    // Somebody else wrote in between.
    await seeded.client.updateEntry(kurtz.id, { revision: 1, summary: 'from another window' });

    await user.type(within(panel).getByLabelText('Pronouns'), 'he/him');
    await user.click(within(panel).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(within(panel).getByText(/This entry changed somewhere else/)).toBeDefined();
    });
    // Nothing was written, and nothing was merged.
    expect(seeded.client.entryOf(kurtz.id)?.attributes['pronouns']).toBeUndefined();
    // The typing is still on screen; the writer decides.
    expect((within(panel).getByLabelText('Pronouns') as HTMLInputElement).value).toBe('he/him');
    expect(within(panel).getByRole('button', { name: "Load the server's copy" })).toBeDefined();
  });

  test('taking the server’s copy re-seeds the form from it', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');
    await seeded.client.updateEntry(kurtz.id, { revision: 1, summary: 'from another window' });
    await user.click(within(panel).getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(within(panel).getByRole('button', { name: "Load the server's copy" })).toBeDefined();
    });
    await user.click(within(panel).getByRole('button', { name: "Load the server's copy" }));

    await waitFor(() => {
      expect((within(panel).getByLabelText('Summary') as HTMLInputElement).value).toBe(
        'from another window',
      );
    });
  });
});

describe('a refusal names the field it is about', () => {
  test('the message lands beside the input rather than over the whole form', async () => {
    // § 8's step 3: an `enum` value outside its declared set. The refusal is the server's — the
    // fake holds no validator — and what is tested here is that the client puts it where the
    // writer can act on it.
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Kurtz');
    seeded.client.failNext(
      'updateEntry',
      new ApiError(422, 'invalid_attributes', "role: 'villain' is not one of [...]", {
        field: 'role',
      }),
    );
    await user.type(within(panel).getByLabelText('Pronouns'), 'he/him');
    await user.click(within(panel).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(within(panel).getByRole('alert').textContent).toContain('is not one of');
    });
    expect(document.querySelector('.entry-field-bad')).not.toBeNull();
  });
});

describe('an entry’s history (D27)', () => {
  test('is complete from creation, newest first', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    await seeded.client.updateEntry(kurtz.id, { revision: 1, name: 'Mister Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Mister Kurtz');
    await user.click(within(panel).getByRole('button', { name: /^History/ }));

    await waitFor(() => {
      expect(within(panel).getByText('#2')).toBeDefined();
    });
    // Revision 1 is the entry being made, so restoring the original is an ordinary restore.
    expect(within(panel).getByText('#1')).toBeDefined();
    expect(within(panel).getByText('created')).toBeDefined();
  });

  test('a revision can be previewed, and says what differs from now', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    await seeded.client.updateEntry(kurtz.id, { revision: 1, name: 'Mister Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Mister Kurtz');
    await user.click(within(panel).getByRole('button', { name: /^History/ }));
    await waitFor(() => {
      expect(within(panel).getByText('#1')).toBeDefined();
    });
    const [, older] = within(panel).getAllByRole('button', { name: 'Preview' });
    await user.click(older!);

    const preview = await within(panel).findByTestId('revision-preview');
    // The state **after** that write, so revision 1 is what the entry was at revision 1.
    expect(within(preview).getByText('Kurtz')).toBeDefined();
    expect(within(preview).getByText(/differs from now/)).toBeDefined();
  });

  test('restoring appends a new revision rather than rewriting the history', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const kurtz = seeded.client.seedEntry(seeded.projectId, { kind: 'character', name: 'Kurtz' });
    await seeded.client.updateEntry(kurtz.id, { revision: 1, name: 'Mister Kurtz' });

    const panel = await open(seeded);
    await openEntry(panel, user, 'Mister Kurtz');
    await user.click(within(panel).getByRole('button', { name: /^History/ }));
    await waitFor(() => {
      expect(within(panel).getByText('#1')).toBeDefined();
    });
    const [, older] = within(panel).getAllByRole('button', { name: 'Restore' });
    await user.click(older!);

    await waitFor(() => {
      expect(seeded.client.entryOf(kurtz.id)?.name).toBe('Kurtz');
    });
    // A restore is an ordinary edit: revision 3, not revision 1 again.
    expect(seeded.client.entryOf(kurtz.id)?.revision).toBe(3);
    expect((await seeded.client.listEntryRevisions(kurtz.id)).revisions).toHaveLength(3);
  });
});

describe('making an entry by hand', () => {
  test('choose a kind, fill in its fields, and it opens', async () => {
    const user = userEvent.setup();
    const seeded = await seed();

    const panel = await open(seeded);
    await user.click(within(panel).getByRole('button', { name: 'New entry' }));
    await user.selectOptions(within(panel).getByLabelText('Kind'), 'fact');
    await user.type(within(panel).getByLabelText('Name'), 'The river runs one way');
    await user.type(within(panel).getByLabelText(/What is true/), 'Nobody sails back up it.');
    await user.click(within(panel).getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      expect(
        within(panel).getByRole('heading', { level: 3, name: 'The river runs one way' }),
      ).toBeDefined();
    });
  });

  test('the form only appears once a kind has been chosen', async () => {
    const user = userEvent.setup();
    const seeded = await seed();

    const panel = await open(seeded);
    await user.click(within(panel).getByRole('button', { name: 'New entry' }));

    // A kind is chosen once and is fixed forever, so it is asked for first and on its own.
    expect(within(panel).queryByLabelText('Summary')).toBeNull();
    expect(within(panel).getByText(/A kind cannot be changed afterwards/)).toBeDefined();
  });
});
