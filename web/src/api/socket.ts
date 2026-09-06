/**
 * The chat socket, and the seam that lets a test drive one (P4-12, D11, D32).
 *
 * `WS /api/conversations/{cid}/stream` is the only WebSocket in this project. It carries two
 * client frames — `ask` and `cancel` — and D32's five events back, and nothing else.
 *
 * ## Why this is an interface with a factory
 *
 * The same reason `ApiClient` is (P1-8): jsdom has a `WebSocket` constructor and it would try to
 * open a real connection, so a component test needs a stand-in. A hand-written fake that
 * implements this interface fails to compile when the interface changes, which a global stub
 * would not — and no test in this project has ever touched the network (outline § 8).
 *
 * ## What this module deliberately does not do
 *
 * **It does not reconnect.** Not on a drop, not on a close, not on an error. A dropped socket
 * mid-answer surfaces as a failure the writer can retry from, because an automatic reconnect
 * that re-sends the question is D13 and ruling 6 violated by accident — the autosave's backoff
 * ladder is right there and is exactly wrong here. Retrying a save costs nothing and protects
 * the writer's words; retrying a completion costs money and protects nothing.
 *
 * **It does not accumulate, interpret, or reorder anything.** It parses each frame with
 * {@link parseStreamEvent} and hands it on. What a sequence of events *means* is the reducer's,
 * which is pure and testable without a socket at all.
 *
 * **It does not turn a close into an event.** A close is not one of D32's five, and inventing an
 * `error` event for one would put a code from the provider taxonomy on something no provider
 * did. The server closes with `1008` and a reason for everything that is not a provider failure
 * (deviation `C6`); that reason arrives here as a close and is reported as one.
 */

import type { ClientFrame } from './types';
import type { StreamEvent } from './stream';
import { parseStreamEvent } from './stream';

/** How a socket ended. `code` is the WebSocket close code; `reason` is the server's sentence. */
export interface ChatSocketClosed {
  code: number;
  reason: string;
  /** False when the close was not a clean handshake — a dropped connection rather than a refusal. */
  clean: boolean;
}

/** What the owner of a socket is told. Every one of them may be called more than once. */
export interface ChatSocketHandlers {
  /** The socket is open and a frame may be sent. */
  onOpen: () => void;
  /**
   * One event this bundle understood.
   *
   * An event type this bundle does *not* understand never arrives: `parseStreamEvent` returns
   * `null` and it is skipped here, which is the client half of D32's asymmetry — a stale bundle
   * degrades to less detail, never to a broken panel.
   */
  onEvent: (event: StreamEvent) => void;
  /** The socket ended, for any reason at all. Always the last thing called. */
  onClose: (closed: ChatSocketClosed) => void;
}

/** A live socket, from the outside. */
export interface ChatSocket {
  /** Send one frame. Silently does nothing once the socket has closed. */
  send: (frame: ClientFrame) => void;
  /** Close it. `onClose` still fires, so one teardown path serves both endings. */
  close: () => void;
}

/** Opens one. Injected, so the app builds real sockets and tests build fakes. */
export type ChatSocketFactory = (
  conversationId: string,
  handlers: ChatSocketHandlers,
) => ChatSocket;

/**
 * Where the socket for a conversation lives.
 *
 * Derived from the page's own origin rather than configured: the API and the app are one process
 * in the shape the product ships in (P1-14, D7), and in development Vite proxies `/api` to the
 * server — including the WebSocket upgrade. So the same relative path is right in both run modes,
 * exactly as it is for every other route.
 */
export function chatSocketUrl(conversationId: string, origin?: string): string {
  const base = origin ?? window.location.origin;
  const url = new URL(`/api/conversations/${encodeURIComponent(conversationId)}/stream`, base);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

/** The real factory: one browser `WebSocket`, parsed on the way in. */
export const createChatSocket: ChatSocketFactory = (conversationId, handlers) => {
  const socket = new WebSocket(chatSocketUrl(conversationId));
  let ended = false;

  const end = (closed: ChatSocketClosed) => {
    if (ended) {
      return;
    }
    ended = true;
    handlers.onClose(closed);
  };

  socket.onopen = () => handlers.onOpen();

  socket.onmessage = (message: MessageEvent<unknown>) => {
    if (typeof message.data !== 'string') {
      return;
    }
    let payload: unknown;
    try {
      payload = JSON.parse(message.data);
    } catch {
      // Not JSON at all. Nothing on this socket sends anything else, so this is a proxy or a
      // corrupted frame — and the rule for a frame we cannot read is the rule for one we do not
      // recognise: skip it and keep rendering what did arrive.
      return;
    }
    const event = parseStreamEvent(payload);
    if (event !== null) {
      handlers.onEvent(event);
    }
  };

  // An `error` on a WebSocket carries nothing useful by design — the browser will not say why,
  // for the same reasons it will not say why a handshake failed. The close that follows is
  // where the report happens, and `wasClean` is what distinguishes a drop from a refusal.
  socket.onerror = () => {};

  socket.onclose = (event: CloseEvent) =>
    end({ code: event.code, reason: event.reason, clean: event.wasClean });

  return {
    send: (frame: ClientFrame) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(frame));
      }
    },
    close: () => {
      // 1000 is a normal closure: the writer left, or the panel switched conversations. Nothing
      // went wrong, and the server's own `finally` tears the read loop down either way.
      socket.close(1000, 'closed by the app');
      // A socket closed before it ever opened never fires `onclose` in some browsers, so the
      // owner is told here rather than being left waiting for a teardown that will not come.
      if (socket.readyState === WebSocket.CLOSED) {
        end({ code: 1000, reason: 'closed by the app', clean: true });
      }
    },
  };
};
