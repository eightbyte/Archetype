/**
 * P4-12 — the assistant panel: the list, the stream, cancel, a failure, and a reload.
 *
 * These are P4-12's *done when*, one test each, through the real provider stack — the app's
 * `ChatProvider` with a fake client and a fake socket, not a simplified stand-in.
 *
 * The socket is a fake for the reason the client is: jsdom would open a real connection, and no
 * test in this project has ever touched the network (outline § 8). It runs no stream of its own
 * — a test says exactly what arrives and when, which is the only way the cadences in § 6 can be
 * produced at all.
 *
 * The join a test has to make by hand is the one a transaction makes on the server: the socket
 * persists the turn and *then* sends the terminator, so a test seeds the turn through the fake
 * client before it emits `done`. That ordering is the point of the whole arrangement, and one
 * test below asserts what the panel does with it.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test } from 'vitest';
import { Workspace } from '../shell/Workspace';
import { FakeApiClient } from './fakes/fakeApiClient';
import { FakeChatSocketFactory } from './fakes/fakeChatSocket';
import { Harness, prose } from './harness';

interface Seeded {
  client: FakeApiClient;
  projectId: string;
  sockets: FakeChatSocketFactory;
}

async function seed(): Promise<Seeded> {
  const client = new FakeApiClient();
  const projectId = client.seedProject('The Long Road');
  const [first] = client.documentIdsOf(projectId);
  await client.saveDocumentContent(first!, prose('The harbour was grey.'), 1);
  return { client, projectId, sockets: new FakeChatSocketFactory() };
}

/** Mount the workspace and hand back the assistant region. */
async function open(seeded: Seeded): Promise<HTMLElement> {
  render(
    <Harness
      client={seeded.client}
      projectId={seeded.projectId}
      socketFactory={seeded.sockets.create}
      scheduler={{ delayMs: 60_000 }}
    >
      <Workspace onLeaveProject={() => {}} />
    </Harness>,
  );
  const panel = screen.getByRole('region', { name: 'Assistant' });
  await within(panel).findByRole('button', { name: 'New conversation' });
  return panel;
}

/** Start a conversation, type a question, and send it. Resolves once the socket has the frame. */
async function ask(
  seeded: Seeded,
  panel: HTMLElement,
  user: ReturnType<typeof userEvent.setup>,
  question = 'what colour is the harbour?',
): Promise<void> {
  await user.click(within(panel).getByRole('button', { name: 'New conversation' }));
  const box = await within(panel).findByLabelText('Your question');
  await user.type(box, question);
  await user.click(within(panel).getByRole('button', { name: 'Ask' }));
  await waitFor(() => expect(seeded.sockets.last.lastAsk).not.toBeNull());
}

describe('a conversation', () => {
  test('starts empty, and says where a question comes from', async () => {
    const panel = await open(await seed());

    expect(within(panel).getByText(/Select a passage/)).toBeDefined();
  });

  test('one is started, named from its first question, and listed', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);

    await ask(seeded, panel, user);

    // A conversation is named from its first question — `title` is the only mutable field it has,
    // which is what makes naming it automatically safe.
    await waitFor(() => {
      expect(panel.querySelector('.chat-conversation-title')?.textContent).toBe(
        'what colour is the harbour?',
      );
    });
  });
});

describe('an answer arriving', () => {
  test('renders progressively, then is replaced by what the server stored', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await ask(seeded, panel, user);

    const socket = seeded.sockets.last;
    socket.emit({ type: 'start', model: 'fake-model' });
    socket.emit({ type: 'delta', text: 'The harbour ' });
    await waitFor(() => expect(within(panel).getByText(/The harbour/)).toBeDefined());

    socket.emit({ type: 'delta', text: 'was grey.' });
    await waitFor(() => {
      expect(within(panel).getByText('The harbour was grey.')).toBeDefined();
    });

    // The turn is written and *then* the terminator is sent, so the re-read cannot lose the race
    // (`chat_routes.py`). A test makes that join by hand, because here they are two fakes.
    seeded.client.seedTurn(socket.conversationId, {
      role: 'user',
      content: 'what colour is the harbour?',
    });
    seeded.client.seedTurn(socket.conversationId, {
      role: 'assistant',
      content: 'The harbour was grey.',
      usage: { input_tokens: 140, output_tokens: 6 },
      stop_reason: 'end_turn',
    });
    socket.emit({ type: 'usage', usage: { input_tokens: 140, output_tokens: 6 } });
    socket.emit({ type: 'done', stop_reason: 'end_turn', raw_stop_reason: 'end_turn' });

    // What an answer cost, per turn. Zero would mean *not reported* rather than free.
    await waitFor(() => {
      expect(within(panel).getByText('140 in · 6 out')).toBeDefined();
    });
  });

  test('one deliberate ask is one frame — the button is unavailable while it arrives', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await ask(seeded, panel, user);

    const socket = seeded.sockets.last;
    socket.emit({ type: 'delta', text: 'The harbour' });

    await waitFor(() => {
      expect(within(panel).getByRole('button', { name: 'Ask' }).hasAttribute('disabled')).toBe(
        true,
      );
    });
    expect(socket.sent.filter((frame) => frame.type === 'ask')).toHaveLength(1);
  });
});

describe('stopping one', () => {
  test('cancel keeps the partial answer, and marks it as stopped', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await ask(seeded, panel, user);

    const socket = seeded.sockets.last;
    socket.emit({ type: 'delta', text: 'The harbour was ' });
    await within(panel).findByRole('button', { name: 'Stop' });
    await user.click(within(panel).getByRole('button', { name: 'Stop' }));

    expect(socket.sent.at(-1)).toEqual({ type: 'cancel' });

    // The server closes the provider stream, keeps what arrived, and terminates with `cancelled`
    // — a stop reason and never an error code, because a deliberate act is not a failure.
    seeded.client.seedTurn(socket.conversationId, {
      role: 'assistant',
      content: 'The harbour was ',
      stop_reason: 'cancelled',
    });
    socket.emit({ type: 'done', stop_reason: 'cancelled', raw_stop_reason: '' });

    await waitFor(() => {
      expect(within(panel).getByText(/you stopped this/)).toBeDefined();
    });
    expect(within(panel).getAllByText(/The harbour was/).length).toBeGreaterThan(0);
  });
});

describe('when it goes wrong', () => {
  test('a mid-stream failure keeps the transcript and says what happened', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await ask(seeded, panel, user);

    const socket = seeded.sockets.last;
    socket.emit({ type: 'delta', text: 'The harbour was ' });
    socket.emit({
      type: 'error',
      code: 'provider_rate_limited',
      message: 'too many requests',
    });

    await waitFor(() => {
      expect(within(panel).getByText(/rate-limiting this key/)).toBeDefined();
    });
    // Our sentence says what kind of thing went wrong; the provider's says what happened, and it
    // is the half that makes a failure diagnosable. Both are shown.
    expect(within(panel).getByText(/too many requests/)).toBeDefined();
    expect(within(panel).getAllByText(/The harbour was/).length).toBeGreaterThan(0);
  });

  test('a socket that drops mid-answer is a failure with no provider blamed', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await ask(seeded, panel, user);

    const socket = seeded.sockets.last;
    socket.emit({ type: 'delta', text: 'The harbour was ' });
    socket.drop();

    await waitFor(() => {
      expect(within(panel).getByText(/The answer stopped/)).toBeDefined();
    });
    // Nothing reconnects by itself: an automatic reconnect that re-sends is ruling 6 violated by
    // accident, so exactly one socket was ever opened.
    expect(seeded.sockets.sockets).toHaveLength(1);
  });

  test('a conversation the server refuses closes the socket with its reason', async () => {
    const user = userEvent.setup();
    const seeded = await seed();
    const panel = await open(seeded);
    await ask(seeded, panel, user);

    // Everything that is not a provider failure closes with `1008` and a sentence rather than
    // borrowing one of the six codes (deviation `C6`).
    seeded.sockets.last.serverClose(1008, 'that chapter has been deleted');

    await waitFor(() => {
      expect(within(panel).getByText(/that chapter has been deleted/)).toBeDefined();
    });
  });
});

describe('coming back to it', () => {
  test('a reload restores the conversation, its turns, and what they cost (D30)', async () => {
    const seeded = await seed();
    const conversationId = seeded.client.seedConversation(seeded.projectId, 'The harbour');
    seeded.client.seedTurn(conversationId, {
      role: 'user',
      content: 'what colour is the harbour?',
    });
    seeded.client.seedTurn(conversationId, {
      role: 'assistant',
      content: 'Grey, and getting darker.',
      usage: { input_tokens: 140, output_tokens: 6 },
      stop_reason: 'end_turn',
    });

    const user = userEvent.setup();
    const panel = await open(seeded);

    // Nothing was streamed in this mount at all. The transcript comes back out of the project
    // file, which is D30's whole point.
    await user.click(await within(panel).findByRole('button', { name: 'Open The harbour' }));

    expect(await within(panel).findByText('Grey, and getting darker.')).toBeDefined();
    // Twice on screen, and both are wanted: what that turn cost, and what the conversation has
    // cost altogether. The header is the second one.
    expect(within(panel).getAllByText('140 in · 6 out')).toHaveLength(2);
    expect(panel.querySelector('.chat-conversation-usage')?.textContent).toBe('140 in · 6 out');
    expect(seeded.sockets.sockets).toHaveLength(0);
  });

  test('a failed turn is a stored turn, and the history says why', async () => {
    const seeded = await seed();
    const conversationId = seeded.client.seedConversation(seeded.projectId, 'The harbour');
    seeded.client.seedTurn(conversationId, { role: 'user', content: 'what colour?' });
    seeded.client.seedTurn(conversationId, {
      role: 'assistant',
      content: '',
      error_code: 'provider_auth_failed',
    });

    const user = userEvent.setup();
    const panel = await open(seeded);
    await user.click(await within(panel).findByRole('button', { name: 'Open The harbour' }));

    // A gap in the transcript is something the writer has to remember; a row that says what went
    // wrong is something they can read.
    expect(await within(panel).findByText(/would not accept the key/)).toBeDefined();
  });

  test('a conversation is deleted recoverably and restored from the tray', async () => {
    const seeded = await seed();
    seeded.client.seedConversation(seeded.projectId, 'The harbour');

    const user = userEvent.setup();
    const panel = await open(seeded);

    await user.click(await within(panel).findByRole('button', { name: 'Delete The harbour' }));
    await waitFor(() => {
      expect(within(panel).queryByRole('button', { name: 'Open The harbour' })).toBeNull();
    });

    await user.click(within(panel).getByRole('button', { name: 'Deleted conversations' }));
    await user.click(await within(panel).findByRole('button', { name: 'Restore The harbour' }));

    expect(await within(panel).findByRole('button', { name: 'Open The harbour' })).toBeDefined();
  });
});
