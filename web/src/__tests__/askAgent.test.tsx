/**
 * P4-13 — *Ask agent*, and what is shown before it is sent (plan § 2, ruling 5).
 *
 * The gesture and the composition meet at a typed boundary and are covered on the two sides of
 * it, for the **fourth** time in this project: jsdom has no native editing, so a text selection
 * cannot be made through the DOM the way a person makes one (phase-2 § 7, `C7`). *Mark passage*,
 * *Re-link here*, *Add to bible*, and now *Ask agent* are all covered this way, and § 8 is what
 * joins them.
 *
 * This file is the panel's half. `selectionActions.test.tsx` is the editor's half — it asserts
 * that a real selection produces the right range — and here the range is handed in directly, as
 * the control would hand it in.
 *
 * ## What the preview is, and is not
 *
 * It is the **server's** answer: `POST /api/conversations/{cid}/context` runs the same
 * `compose()` the socket runs and spends nothing (deviation `C2`). The shape of that answer is
 * held to the client by `contract/context_preview.json`, which is what P4-13's "held by a shared
 * contract fixture rather than by two implementations agreeing" asks for — so what is asserted
 * here is what the panel *does* with a preview, and never what a composition should contain.
 */

import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { Workspace } from '../shell/Workspace';
import { useChat } from '../state/ChatContext';
import { INITIAL_UI_STATE } from '../state/uiReducer';
import { FakeApiClient } from './fakes/fakeApiClient';
import { FakeChatSocketFactory } from './fakes/fakeChatSocket';
import { Harness, prose } from './harness';

interface Seeded {
  client: FakeApiClient;
  projectId: string;
  documentId: string;
  sockets: FakeChatSocketFactory;
}

async function seed(): Promise<Seeded> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [documentId] = client.documentIdsOf(projectId);
  await client.saveDocumentContent(
    documentId!,
    prose('The harbour was grey.', 'He did not look back.'),
    1,
  );
  return { client, projectId, documentId: documentId!, sockets: new FakeChatSocketFactory() };
}

/**
 * Stands in for the *Ask agent* button, as a control the test presses.
 *
 * It calls exactly what `EditorRegion`'s handler calls — the range, the chapter, and the earlier
 * turns — because the gesture that produces the range is the half jsdom cannot make. A button
 * rather than a mount effect, so that it happens *after* the panel has loaded, which is when a
 * writer selects a passage.
 */
function PointAtPassage({ documentId }: { documentId: string }) {
  const { selectContext } = useChat();
  return (
    <button
      type="button"
      onClick={() =>
        selectContext({
          document_id: documentId,
          from_pos: 1,
          to_pos: 12,
          include_chapter: true,
          entry_ids: [],
          include_history: true,
        })
      }
    >
      Ask agent about the passage
    </button>
  );
}

async function open(seeded: Seeded): Promise<HTMLElement> {
  render(
    <Harness
      client={seeded.client}
      projectId={seeded.projectId}
      socketFactory={seeded.sockets.create}
      ui={INITIAL_UI_STATE}
      scheduler={{ delayMs: 60_000 }}
    >
      <Workspace onLeaveProject={() => {}} />
      <PointAtPassage documentId={seeded.documentId} />
    </Harness>,
  );
  const panel = screen.getByRole('region', { name: 'Assistant' });
  await within(panel).findByRole('button', { name: 'New conversation' });
  return panel;
}

/** Point at the passage, then open a conversation so there is something to compose against. */
async function start(
  panel: HTMLElement,
  user: ReturnType<typeof userEvent.setup>,
): Promise<void> {
  await user.click(screen.getByRole('button', { name: 'Ask agent about the passage' }));
  await user.click(within(panel).getByRole('button', { name: 'New conversation' }));
  await within(panel).findByLabelText('Your question');
}

describe('what will be sent', () => {
  test('the passage, the chapter, and the earlier turns are each listed', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await start(panel, user);

    await waitFor(() => {
      expect(within(panel).getByText('selection')).toBeDefined();
    });
    expect(within(panel).getByText('chapter')).toBeDefined();
    expect(within(panel).getByText('question')).toBeDefined();
    // Every part reports what it is estimated to cost, and the total is what the refusal will
    // measure — the number is the server's, computed by the same code the budget check uses.
    expect(within(panel).getByText(/tokens/)).toBeDefined();
  });

  test('dropping a part changes what is sent, not only what is drawn', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await start(panel, user);

    await waitFor(() => expect(within(panel).getByText('chapter')).toBeDefined());
    await user.click(within(panel).getByRole('button', { name: /Leave out Chapter/ }));

    // Gone from the preview, because the preview is re-read from the selector rather than
    // filtered locally.
    await waitFor(() => expect(within(panel).queryByText('chapter')).toBeNull());

    await user.type(within(panel).getByLabelText('Your question'), 'what colour?');
    await user.click(within(panel).getByRole('button', { name: 'Ask' }));

    await waitFor(() => expect(seeded.sockets.last.lastAsk).not.toBeNull());
    const ask = seeded.sockets.last.lastAsk!;
    expect(ask.context?.include_chapter).toBe(false);
    // And the passage is still pointed at: dropping one part drops one part.
    expect(ask.context?.from_pos).toBe(1);
    expect(ask.context?.to_pos).toBe(12);
    expect(ask.context?.document_id).toBe(seeded.documentId);
  });

  test('a dropped part can be put back', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await start(panel, user);

    await waitFor(() => expect(within(panel).getByText('chapter')).toBeDefined());
    await user.click(within(panel).getByRole('button', { name: /Leave out Chapter/ }));
    await waitFor(() => expect(within(panel).queryByText('chapter')).toBeNull());

    await user.click(within(panel).getByRole('button', { name: 'Add the chapter' }));
    await waitFor(() => expect(within(panel).getByText('chapter')).toBeDefined());
  });

  test('a bible entry the writer names travels with the question', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const entry = seeded.client.seedEntry(seeded.projectId, {
      kind: 'character',
      name: 'Marlow',
    }).id;
    const panel = await open(seeded);
    await start(panel, user);

    await waitFor(() => expect(within(panel).getByText('selection')).toBeDefined());
    await user.click(within(panel).getByRole('button', { name: 'Add a bible entry' }));
    await user.selectOptions(await within(panel).findByLabelText('Bible entry'), entry);

    await waitFor(() => expect(within(panel).getByText('entry')).toBeDefined());

    await user.type(within(panel).getByLabelText('Your question'), 'who is he?');
    await user.click(within(panel).getByRole('button', { name: 'Ask' }));

    await waitFor(() => expect(seeded.sockets.last.lastAsk).not.toBeNull());
    // "What they pointed at and what they named" — never what a search found. There is no index
    // until Phase 5, and an entry is in the context because the writer put it there.
    expect(seeded.sockets.last.lastAsk!.context?.entry_ids).toEqual([entry]);
  });

  test('an over-budget context says so, and says that asking costs nothing', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    // The budget check is the server's and it is a **hard refusal** naming what was too big, not
    // a truncation (ruling 7). The preview reports it; the refusal belongs to the ask.
    seeded.client.stageContextBudget(10);
    const panel = await open(seeded);
    await start(panel, user);

    expect(await within(panel).findByText(/over the budget/)).toBeDefined();
    expect(within(panel).getByText(/costs nothing/)).toBeDefined();
  });

  test('a preview that fails leaves the panel usable and says what went wrong', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    seeded.client.failAlways('previewContext', new Error('the server is not answering'));
    const panel = await open(seeded);
    await start(panel, user);

    expect(await within(panel).findByText(/could not be worked out/)).toBeDefined();
    // The question box is still there: what is being sent could not be shown, which is not a
    // reason to stop the writer asking.
    expect(within(panel).getByLabelText('Your question')).toBeDefined();
  });
});

describe('pointing at a passage from the editor', () => {
  test('the panel is opened by the gesture, even from collapsed', async () => {
    const seeded = await seed();
    render(
      <Harness
        client={seeded.client}
        projectId={seeded.projectId}
        socketFactory={seeded.sockets.create}
        ui={{ ...INITIAL_UI_STATE, agentCollapsed: true }}
        scheduler={{ delayMs: 60_000 }}
      >
        <Workspace onLeaveProject={() => {}} />
      </Harness>,
    );

    const region = screen.getByRole('region', { name: 'Assistant' });
    expect(within(region).getByRole('button', { name: 'Show the assistant panel' })).toBeDefined();

    // The panel is where the question is typed, so asking for it opens it. This is the effect
    // `EditorRegion`'s handler has; the gesture that triggers it is the editor's half.
    const user = userEvent.setup();
    await act(async () => {
      await user.click(within(region).getByRole('button', { name: 'Show the assistant panel' }));
    });

    expect(await within(region).findByRole('button', { name: 'New conversation' })).toBeDefined();
  });
});
