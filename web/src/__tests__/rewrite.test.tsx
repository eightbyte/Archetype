/**
 * P4-14 — proofread, tone, and rewrite: the before/after, and the two refusals (D5, D12, D33).
 *
 * These are the phase's eighth exit criterion in miniature: **a result applies through the editor
 * as one ordinary, undoable transaction, or not at all — and never to a `stale` anchor.**
 *
 * Four things are asserted here and each is a rule rather than a behaviour:
 *
 * * an action **mints an anchor first**, through `AnchorStore` and by no other means, so a
 *   suggestion whose passage has since been rewritten can say so (phase-3 § 2, ruling 8);
 * * accepting produces **exactly one editor transaction and one save** — not a proposal row, not
 *   an accept endpoint, not a second save path (D33);
 * * rejecting **writes nothing to the manuscript**;
 * * applying against a `stale` anchor is **refused, with a message naming the passage** — which
 *   is the whole reason Phase 2 was built before this.
 *
 * The anchor's status is the **server's** answer, staged through `stageAnchorResolution` exactly
 * as every other anchor test stages one. Nothing on the client decides whether a passage moved:
 * there is one resolver, it is on the server, and it has a specification and a corpus behind it.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { ApiError } from '../api';
import { Workspace } from '../shell/Workspace';
import { useChat } from '../state/ChatContext';
import { useDocument } from '../state/DocumentContext';
import { INITIAL_UI_STATE } from '../state/uiReducer';
import { FakeApiClient } from './fakes/fakeApiClient';
import { FakeChatSocketFactory } from './fakes/fakeChatSocket';
import { Harness, prose } from './harness';

const PARAGRAPH = 'The harbor was calm.';

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
  await client.saveDocumentContent(documentId!, prose(PARAGRAPH), 1);
  return { client, projectId, documentId: documentId!, sockets: new FakeChatSocketFactory() };
}

/**
 * The two gestures jsdom cannot make, as controls the test presses.
 *
 * *Ask agent* needs a text selection, which jsdom has no native editing for; and rewriting a
 * paragraph by hand is the same problem one step further on. Both reach the state layer exactly
 * where the real controls reach it, and everything below the call is the app's own — the pattern
 * `anchorsInEditor.test.tsx` established.
 */
function Probe({ documentId }: { documentId: string }) {
  const { selectContext } = useChat();
  const { edit } = useDocument();
  return (
    <>
      <button
        type="button"
        onClick={() =>
          selectContext({
            document_id: documentId,
            from_pos: 1,
            to_pos: 1 + PARAGRAPH.length,
            include_chapter: true,
            entry_ids: [],
            include_history: true,
          })
        }
      >
        Ask agent about the passage
      </button>
      <button type="button" onClick={() => edit(prose('Nothing at all like it was.'))}>
        Rewrite the paragraph by hand
      </button>
    </>
  );
}

async function open(seeded: Seeded): Promise<HTMLElement> {
  render(
    <Harness
      client={seeded.client}
      projectId={seeded.projectId}
      socketFactory={seeded.sockets.create}
      ui={INITIAL_UI_STATE}
    >
      <Workspace onLeaveProject={() => {}} />
      <Probe documentId={seeded.documentId} />
    </Harness>,
  );
  const panel = screen.getByRole('region', { name: 'Assistant' });
  await within(panel).findByRole('button', { name: 'New conversation' });
  await surface();
  return panel;
}

/** The writing surface. Queried by class because the composer is a textbox too. */
async function surface(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.querySelector<HTMLElement>('.manuscript');
    if (!element) {
      throw new Error('the editor has not mounted yet');
    }
    return element;
  });
}

/** Point at the passage, open a conversation, and run one action to completion. */
async function runAction(
  seeded: Seeded,
  panel: HTMLElement,
  user: ReturnType<typeof userEvent.setup>,
  action: string,
  answer: string,
): Promise<void> {
  await user.click(screen.getByRole('button', { name: 'Ask agent about the passage' }));
  await user.click(within(panel).getByRole('button', { name: 'New conversation' }));
  await user.click(await within(panel).findByRole('button', { name: action }));

  await waitFor(() => expect(seeded.sockets.last.lastAsk).not.toBeNull());
  const socket = seeded.sockets.last;
  socket.emit({ type: 'delta', text: answer });
  seeded.client.seedTurn(socket.conversationId, {
    role: 'assistant',
    content: answer,
    stop_reason: 'end_turn',
  });
  socket.emit({ type: 'done', stop_reason: 'end_turn', raw_stop_reason: 'end_turn' });
  await within(panel).findByRole('button', { name: 'Accept' });
}

describe('running an action', () => {
  test('offers all three, and only over a passage in the open chapter', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await user.click(within(panel).getByRole('button', { name: 'New conversation' }));

    // Nothing pointed at: `createAnchor` anchors a range of the *open* document, and a range
    // pointed at in one chapter and anchored in another is a suggestion about text nobody
    // looked at.
    expect(within(panel).queryByRole('button', { name: 'Proofread' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Ask agent about the passage' }));

    expect(await within(panel).findByRole('button', { name: 'Proofread' })).toBeDefined();
    expect(within(panel).getByRole('button', { name: 'Adjust tone' })).toBeDefined();
    expect(within(panel).getByRole('button', { name: 'Rewrite' })).toBeDefined();
  });

  test('asks with the action’s own range, and without the earlier turns', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);

    await runAction(seeded, panel, user, 'Proofread', 'The harbour was calm.');

    const ask = seeded.sockets.last.lastAsk!;
    expect(ask.prompt).toContain('Proofread the selected passage');
    expect(ask.context?.from_pos).toBe(1);
    expect(ask.context?.to_pos).toBe(1 + PARAGRAPH.length);
    // A replacement is asked for on its own: earlier turns would put the transcript's own words
    // into a request whose answer goes straight into the manuscript.
    expect(ask.context?.include_history).toBe(false);
  });

  test('the anchor comes first, so a range that cannot be anchored spends nothing', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    seeded.client.failNext(
      'createAnchor',
      new ApiError(409, 'version_conflict', 'the chapter has moved on', null),
    );

    await user.click(screen.getByRole('button', { name: 'Ask agent about the passage' }));
    await user.click(within(panel).getByRole('button', { name: 'New conversation' }));
    await user.click(await within(panel).findByRole('button', { name: 'Proofread' }));

    // The ask never went out. An action mints its anchor **before** it asks, so a stale version
    // or a range with no honest place in the text costs nothing at all.
    await screen.findByText(/Could not start that/);
    expect(seeded.sockets.sockets).toHaveLength(0);
  });

  test('the before/after marks what moved', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);

    await runAction(seeded, panel, user, 'Proofread', 'The harbour was calm.');

    const diff = panel.querySelector('.rewrite-diff-body');
    expect(diff?.querySelector('.diff-removed')?.textContent).toBe('harbor ');
    expect(diff?.querySelector('.diff-added')?.textContent).toBe('harbour ');
  });
});

describe('accepting one', () => {
  test('applies as one editor transaction and one save (D33)', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await runAction(seeded, panel, user, 'Proofread', 'The harbour was calm.');

    const before = seeded.client.versionOf(seeded.documentId)!;
    await user.click(within(panel).getByRole('button', { name: 'Accept' }));

    // The text is in the manuscript, through the ordinary save path — no proposal row, no
    // accept endpoint, and the version moved exactly once.
    await waitFor(() => {
      expect(seeded.client.versionOf(seeded.documentId)).toBe(before + 1);
    });
    await waitFor(async () => {
      expect((await surface()).textContent).toContain('The harbour was calm.');
    });
  });

  test('the anchor it minted is taken away again', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await runAction(seeded, panel, user, 'Proofread', 'The harbour was calm.');

    await user.click(within(panel).getByRole('button', { name: 'Accept' }));

    // The anchor is machinery this action created, not a mark the writer asked for. Leaving one
    // behind per rewrite would fill the *Marks* tab with passages nobody marked.
    await waitFor(() => expect(seeded.client.calls).toContain('deleteAnchor'));
  });
});

describe('throwing one away', () => {
  test('writes nothing to the manuscript', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await runAction(seeded, panel, user, 'Rewrite', 'Nothing moved on the water.');

    const before = seeded.client.versionOf(seeded.documentId)!;
    await user.click(within(panel).getByRole('button', { name: 'Discard' }));

    await waitFor(() => {
      expect(within(panel).queryByRole('button', { name: 'Accept' })).toBeNull();
    });
    expect(seeded.client.versionOf(seeded.documentId)).toBe(before);
    expect((await surface()).textContent).toContain(PARAGRAPH);
  });

  test('the answer stays in the transcript — it was asked for and paid for', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await runAction(seeded, panel, user, 'Rewrite', 'Nothing moved on the water.');

    await user.click(within(panel).getByRole('button', { name: 'Discard' }));

    expect(await within(panel).findByText('Nothing moved on the water.')).toBeDefined();
  });
});

describe('when the passage has moved underneath it', () => {
  test('applying against a stale anchor is refused, and names the passage', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await runAction(seeded, panel, user, 'Proofread', 'The harbour was calm.');

    // The writer keeps working, and rewrites the very passage the suggestion is about. The save
    // that follows re-resolves every anchor of the document inside its own transaction (D21),
    // and the server's answer is staged — there is one resolver and it is not in this suite.
    await rewriteUnderneath(seeded, user);

    await user.click(within(panel).getByRole('button', { name: 'Accept' }));

    const refusal = await within(panel).findByRole('alert');
    expect(refusal.textContent).toContain('has been rewritten since this was suggested');
    // A stale anchor's positions are true at no version, so applying to them would drop the
    // replacement onto whatever now occupies those offsets (`specs/anchors.md` § 1).
    expect(refusal.textContent).toContain('Nothing has been changed');
    expect((await surface()).textContent).not.toContain('The harbour was calm.');
  });

  test('and the suggestion stays on screen, so nothing the writer paid for is lost', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await runAction(seeded, panel, user, 'Proofread', 'The harbour was calm.');

    await rewriteUnderneath(seeded, user);
    await user.click(within(panel).getByRole('button', { name: 'Accept' }));
    await within(panel).findByRole('alert');

    expect(within(panel).getByRole('button', { name: 'Discard' })).toBeDefined();
  });
});

/**
 * Rewrite the passage underneath the suggestion, and let the save land.
 *
 * The staged resolution is what the **server's** resolver answers on that save: this suite has no
 * resolver and must never grow one (`fakeApiClient.ts`). What it stands for is a wholesale
 * rewrite, which is precisely the case that leaves an anchor `stale` with its positions unmoved —
 * phase-3's `E2`, and the reason this refusal exists.
 */
async function rewriteUnderneath(
  seeded: Seeded,
  user: ReturnType<typeof userEvent.setup>,
): Promise<void> {
  const ids = seeded.client.anchorIdsOf(seeded.documentId);
  const anchorId = ids[ids.length - 1];
  if (!anchorId) {
    throw new Error('no anchor was minted');
  }
  seeded.client.stageAnchorResolution(seeded.documentId, [{ id: anchorId, status: 'stale' }]);

  const before = seeded.client.versionOf(seeded.documentId)!;
  await user.click(screen.getByRole('button', { name: 'Rewrite the paragraph by hand' }));
  await waitFor(() => {
    expect(seeded.client.versionOf(seeded.documentId)).toBe(before + 1);
  });
}
