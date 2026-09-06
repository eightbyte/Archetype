/**
 * A hand-written fake of the chat socket (P4-12).
 *
 * The same discipline as `fakeApiClient.ts`, and for the same two reasons: it implements the real
 * interface, so it fails to compile when that interface changes, and **no test in this project
 * has ever touched the network** (outline § 8). jsdom has a `WebSocket` constructor and it would
 * try to open a real connection, so a component test needs this.
 *
 * ## What it does not do
 *
 * It **runs no stream of its own.** It does not decide what a `done` follows, when usage arrives,
 * whether a `cancel` is honoured, or what a provider would have said — those are the server's,
 * they are tested there (`test_chat_socket.py`), and a second set of rules here would be a second
 * server with neither a specification nor a corpus behind it. It records what was sent and emits
 * exactly what a test says to emit.
 *
 * That is what makes it useful for the thing the panel actually has to get right: **cadence**.
 * Out-of-order events, a duplicate `start`, a `usage` after the last fragment, a stream that
 * stops without a terminator, a close that races the final delta — none of those can be asked of
 * a real provider on demand, and every one of them is a way the panel can end up subtly wrong
 * (§ 6). `FakeProvider` may stage cadence on the server for the identical reason.
 */

import type { ChatSocket, ChatSocketFactory, ChatSocketHandlers } from '../../api/socket';
import type { StreamEvent } from '../../api/stream';
import type { ClientFrame } from '../../api/types';

/** One socket, from the test's side of it. */
export class FakeChatSocket implements ChatSocket {
  /** Every frame the panel sent, in order. `ask` and `cancel` are the only two there can be. */
  readonly sent: ClientFrame[] = [];
  /** True once `close()` was called by the panel, or once a test closed it. */
  closed = false;

  private opened = false;

  constructor(
    readonly conversationId: string,
    private readonly handlers: ChatSocketHandlers,
  ) {}

  // -- the ChatSocket interface ----------------------------------------------------------------

  send(frame: ClientFrame): void {
    if (this.closed) {
      // The real socket drops a send on a closed connection rather than throwing, because a
      // frame racing a close is an ordinary thing rather than a defect.
      return;
    }
    this.sent.push(frame);
  }

  close(): void {
    this.end(1000, 'closed by the app', true);
  }

  // -- what a test drives it with ----------------------------------------------------------------

  /** Complete the handshake. Anything the panel queued goes out now, exactly as it really would. */
  open(): void {
    if (this.opened || this.closed) {
      return;
    }
    this.opened = true;
    this.handlers.onOpen();
  }

  /** Deliver one event. A test may deliver them in any order at all — that is the point. */
  emit(event: StreamEvent): void {
    if (this.closed) {
      return;
    }
    this.handlers.onEvent(event);
  }

  /** Deliver several, in order. */
  emitAll(events: readonly StreamEvent[]): void {
    for (const event of events) {
      this.emit(event);
    }
  }

  /**
   * End the socket from the far side.
   *
   * `1008` and a reason is what the server sends for everything that is **not** a provider
   * failure — a malformed frame, a conversation that is not there, a selection in a chapter
   * deleted since the writer selected in it (deviation `C6`). A drop is `1006` and not clean.
   */
  serverClose(code = 1008, reason = 'closed by the server'): void {
    this.end(code, reason, code !== 1006);
  }

  /** The connection went away mid-answer, with nothing said about why. */
  drop(): void {
    this.end(1006, '', false);
  }

  /** The last `ask` frame the panel sent, or `null`. What a test asserts the context against. */
  get lastAsk(): Extract<ClientFrame, { type: 'ask' }> | null {
    for (let index = this.sent.length - 1; index >= 0; index -= 1) {
      const frame = this.sent[index];
      if (frame && frame.type === 'ask') {
        return frame;
      }
    }
    return null;
  }

  private end(code: number, reason: string, clean: boolean): void {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.handlers.onClose({ code, reason, clean });
  }
}

/**
 * A factory, and the record of every socket it opened.
 *
 * Sockets are kept rather than replaced so a test can assert the one that matters — including
 * that a *second* one was never opened, which is what "nothing reconnects by itself" looks like
 * from the outside.
 */
export class FakeChatSocketFactory {
  readonly sockets: FakeChatSocket[] = [];

  /**
   * Open sockets already open. `false` leaves the handshake to the test, so a frame sent before
   * the socket opens can be checked to have been buffered rather than dropped.
   */
  constructor(private readonly autoOpen = true) {}

  /** The factory itself, ready to hand to `ChatProvider` or the harness. */
  readonly create: ChatSocketFactory = (conversationId, handlers) => {
    const socket = new FakeChatSocket(conversationId, handlers);
    this.sockets.push(socket);
    if (this.autoOpen) {
      // A microtask, not synchronously: a real handshake never completes inside the constructor,
      // and a fake that opened instantly would hide the buffering the provider does.
      void Promise.resolve().then(() => socket.open());
    }
    return socket;
  };

  /** The most recently opened socket. Throws rather than returning null — a test wants the row. */
  get last(): FakeChatSocket {
    const socket = this.sockets[this.sockets.length - 1];
    if (!socket) {
      throw new Error('no chat socket has been opened');
    }
    return socket;
  }
}
