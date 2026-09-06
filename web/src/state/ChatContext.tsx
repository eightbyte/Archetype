/**
 * The open project's conversations, and the socket that carries an answer (P4-12, D10, D11, D30).
 *
 * A fifth context, nested inside `BibleProvider` and outside `DocumentProvider`. That is the
 * lifetime order and it is also the reach the two Group D features need: a conversation lives in
 * the project file and outlives every chapter switch, the panel reads bible entries to name them
 * as context, and the editor's *Ask agent* — which sits inside the document layer — has to be
 * able to hand a selection **up** to this one.
 *
 * ## The socket is an effect with one owner
 *
 * There is exactly one live socket at a time and it belongs to the conversation on screen. It is
 * opened on the first ask, closed when the conversation changes or this provider unmounts, and
 * **never reopened by itself**. A dropped socket mid-answer surfaces as a failure the writer can
 * retry from, because an automatic reconnect that re-sends the question is D13 and ruling 6
 * violated by accident (`api/socket.ts` says the same thing from the other side).
 *
 * Frames are buffered until the socket opens. A browser socket refuses a send before its
 * handshake finishes, and dropping the writer's first question because of that would be a bug
 * they could only reproduce on a slow connection.
 *
 * ## What the socket does not carry, and what is re-read instead
 *
 * D32's five events and nothing else — no sixth type announcing that a turn was saved. So when a
 * stream terminates the panel re-reads `GET /api/conversations/{cid}`, which is one small request
 * and is always right. The server sends the terminator **after** the row is written, so that read
 * cannot lose the race (`chat_routes.py`).
 *
 * ## Every write refreshes the list
 *
 * `BibleContext`'s rule, for its reason: a turn moves `message_count` and `updated_at`, which is
 * what the list is ordered by, and working out on the client which rows moved means
 * re-implementing the route's ordering here — and the second implementation is the one that
 * drifts.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from 'react';
import type { ReactNode } from 'react';
import type {
  ApiClient,
  ChatSocket,
  ChatSocketFactory,
  ComposedContext,
  Conversation,
  SettingsDocument,
  SettingsPatch,
} from '../api';
import { createChatSocket } from '../api';
import type { ClientFrame } from '../api/types';
import type {
  ChatAction,
  ChatState,
  ContextSelection,
  RewriteAction,
  RewriteRequest,
} from './chatReducer';
import { INITIAL_CHAT_STATE, chatReducer, isStreaming } from './chatReducer';
import { rewriteActionDefinition } from '../rewriteActions';
import { describeFailure } from './ProjectContext';

/** How much of a first question becomes the conversation's name. Enough to recognise it by. */
export const TITLE_FROM_PROMPT_CHARS = 60;

/**
 * How long the composer waits before asking the server what it would send.
 *
 * The bible's search debounce, for the bible's reason: a request per keystroke for a number that
 * moves by three. Nothing else waits — pointing at a passage, dropping a part, and naming an
 * entry are single deliberate acts and go out at once.
 */
export const PREVIEW_DEBOUNCE_MS = 250;

/** What an action needs before it can ask: a passage the server has already anchored (P4-14). */
export interface RewriteContext {
  action: RewriteAction;
  anchorId: string;
  documentId: string;
  /** The anchor's quote, as the server derived it. The "before" half of the diff. */
  before: string;
  from_pos: number;
  to_pos: number;
}

interface ChatContextValue {
  state: ChatState;
  dispatch: (action: ChatAction) => void;

  /** Re-read the conversation list. Called after every write. */
  refresh: () => Promise<void>;
  /** Re-read everything. The answer offered when the first load failed. */
  reload: () => void;
  /** Read the soft-deleted conversations. Not loaded until something asks (D22, D25). */
  loadDeleted: () => Promise<void>;

  /** Show one conversation and read its turns, or `null` to go back to the list. */
  openConversation: (conversationId: string | null) => Promise<void>;
  /** Start one. An empty title is fine — it is named from its first question. */
  startConversation: (title?: string) => Promise<Conversation>;
  renameConversation: (conversationId: string, title: string) => Promise<Conversation>;
  deleteConversation: (conversationId: string) => Promise<Conversation>;
  restoreConversation: (conversationId: string) => Promise<Conversation>;

  /** Point the next question at a passage, a chapter, and entries (P4-13). */
  selectContext: (selection: ContextSelection) => void;
  /** Drop or restore one part of it. This is what "the writer can drop any part" means. */
  changeContext: (changes: Partial<ContextSelection>) => void;
  clearContext: () => void;
  /**
   * What would be sent, before it is sent — and spending nothing (ruling 5).
   *
   * The server's own `compose()`, so the number on screen is the number the refusal will use.
   * Resolves `null` when there is no conversation to compose against yet.
   */
  previewContext: (prompt: string) => Promise<ComposedContext | null>;

  /**
   * Ask. One deliberate act, one provider call, one bill (D13, ruling 6).
   *
   * Creates a conversation if none is open, opens a socket if none is live, and sends one `ask`
   * frame carrying the question and the current selection. There is no retry and no regenerate:
   * asking again is the writer pressing the button again.
   */
  ask: (prompt: string) => Promise<void>;
  /**
   * Run one of the three actions over an already-anchored passage (P4-14).
   *
   * The anchor is the caller's to mint, through `AnchorStore` and by no other means, so this
   * takes one that exists rather than a range.
   */
  runRewrite: (context: RewriteContext) => Promise<void>;
  /** Stop the answer that is arriving. The partial text stays, here and in the history (D11). */
  cancel: () => void;
  /** Put the panel back to no answer on screen — after a diff is accepted or thrown away. */
  clearStream: () => void;

  /**
   * The settings, and a change to the provider block (P4-11, P4-15, D34).
   *
   * They live on this context rather than on a sixth one because the settings screen is a view of
   * *this* panel: the block it can change is the assistant's own, and the sentence it shows when
   * nothing is configured is the same sentence the transcript shows as `provider_unconfigured`.
   * Neither call ever carries a key — there is no route that would accept one.
   */
  readSettings: (signal?: AbortSignal) => Promise<SettingsDocument>;
  writeSettings: (patch: SettingsPatch) => Promise<SettingsDocument>;

  /** How long the composer's preview waits. A test seam, exactly as the bible's debounce is. */
  previewDebounceMs: number;
}

const ChatContext = createContext<ChatContextValue | null>(null);

export interface ChatProviderProps {
  client: ApiClient;
  projectId: string;
  children: ReactNode;
  /** Injected by tests. The app opens real WebSockets; no test has ever touched the network. */
  socketFactory?: ChatSocketFactory;
  /** Tests shorten the composer's preview debounce. */
  previewDebounceMs?: number;
}

export function ChatProvider({
  client,
  projectId,
  children,
  socketFactory = createChatSocket,
  previewDebounceMs = PREVIEW_DEBOUNCE_MS,
}: ChatProviderProps) {
  const [state, dispatch] = useReducer(chatReducer, INITIAL_CHAT_STATE);
  const [attempt, retry] = useReducer((count: number) => count + 1, 0);

  const stateRef = useRef<ChatState>(INITIAL_CHAT_STATE);
  stateRef.current = state;

  const clientRef = useRef(client);
  clientRef.current = client;

  /** The one live socket, the conversation it belongs to, and what is waiting to go out on it. */
  const socketRef = useRef<{
    conversationId: string;
    socket: ChatSocket;
    open: boolean;
    queued: ClientFrame[];
  } | null>(null);

  // -- the list -------------------------------------------------------------------------------

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: 'load-requested' });
    void (async () => {
      try {
        const listed = await clientRef.current.listConversations(projectId, controller.signal);
        if (controller.signal.aborted) return;
        dispatch({ type: 'loaded', conversations: listed.conversations });
      } catch (error: unknown) {
        if (controller.signal.aborted) return;
        dispatch({ type: 'load-failed', message: describeFailure(error) });
      }
    })();
    return () => controller.abort();
  }, [projectId, attempt]);

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const listed = await clientRef.current.listConversations(projectId);
      dispatch({ type: 'conversations-listed', conversations: listed.conversations });
    } catch (error: unknown) {
      // The rows already on screen stay. A refresh that did not land is not a reason to take away
      // the last answer the server gave (P1-12).
      dispatch({ type: 'load-failed', message: describeFailure(error) });
    }
  }, [projectId]);

  const loadDeleted = useCallback(async (): Promise<void> => {
    const listed = await clientRef.current.listDeletedConversations(projectId);
    dispatch({ type: 'deleted-listed', conversations: listed.conversations });
  }, [projectId]);

  const readMessages = useCallback(async (conversationId: string): Promise<void> => {
    try {
      const detail = await clientRef.current.getConversation(conversationId);
      dispatch({ type: 'conversation-loaded', conversationId, messages: detail.messages });
    } catch (error: unknown) {
      // Deliberately not fatal, and deliberately not blanking. The transcript on screen is the
      // last answer the server gave, and a failed re-read is not a reason to take it away.
      dispatch({ type: 'load-failed', message: describeFailure(error) });
    }
  }, []);

  // -- the socket -----------------------------------------------------------------------------

  const closeSocket = useCallback(() => {
    const live = socketRef.current;
    socketRef.current = null;
    live?.socket.close();
  }, []);

  /** Open the socket for `conversationId`, or hand back the one already open for it. */
  const socketFor = useCallback(
    (conversationId: string) => {
      const live = socketRef.current;
      if (live && live.conversationId === conversationId) {
        return live;
      }
      // A socket for a different conversation is not reused. The route is per conversation and
      // the server reads the id out of the path, so there is nothing to reuse.
      live?.socket.close();

      const entry: {
        conversationId: string;
        socket: ChatSocket;
        open: boolean;
        queued: ClientFrame[];
      } = {
        conversationId,
        socket: { send: () => {}, close: () => {} },
        open: false,
        queued: [],
      };

      entry.socket = socketFactory(conversationId, {
        onOpen: () => {
          entry.open = true;
          const waiting = entry.queued;
          entry.queued = [];
          for (const frame of waiting) {
            entry.socket.send(frame);
          }
        },
        onEvent: (event) => {
          dispatch({ type: 'stream-event', event });
          if (event.type === 'done' || event.type === 'error') {
            // The turn is on disk by now — the server persists before it terminates — so the
            // persisted ids, the usage, and the stored context are one read away (D30).
            void readMessages(conversationId);
            void refresh();
          }
        },
        onClose: ({ reason }) => {
          if (socketRef.current === entry) {
            socketRef.current = null;
          }
          // Only meaningful mid-answer: the reducer ignores a close after a terminator, because
          // a socket closing once the answer is complete is the ordinary end of one.
          dispatch({ type: 'socket-closed', reason });
        },
      });

      socketRef.current = entry;
      return entry;
    },
    [readMessages, refresh, socketFactory],
  );

  const send = useCallback(
    (conversationId: string, frame: ClientFrame) => {
      const live = socketFor(conversationId);
      if (live.open) {
        live.socket.send(frame);
      } else {
        live.queued.push(frame);
      }
    },
    [socketFor],
  );

  // One owner, one teardown. The socket does not outlive the project it belongs to, and a panel
  // that has been unmounted must not go on receiving an answer nobody can read.
  useEffect(() => closeSocket, [closeSocket]);

  // -- conversations --------------------------------------------------------------------------

  const openConversation = useCallback(
    async (conversationId: string | null): Promise<void> => {
      if (conversationId !== stateRef.current.openId) {
        closeSocket();
      }
      dispatch({ type: 'conversation-opened', conversationId });
      if (conversationId !== null) {
        await readMessages(conversationId);
      }
    },
    [closeSocket, readMessages],
  );

  const startConversation = useCallback(
    async (title?: string): Promise<Conversation> => {
      const created = await clientRef.current.createConversation(projectId, title ?? '');
      await refresh();
      await openConversation(created.id);
      return created;
    },
    [openConversation, projectId, refresh],
  );

  const renameConversation = useCallback(
    async (conversationId: string, title: string): Promise<Conversation> => {
      const renamed = await clientRef.current.renameConversation(conversationId, title);
      await refresh();
      return renamed;
    },
    [refresh],
  );

  const deleteConversation = useCallback(
    async (conversationId: string): Promise<Conversation> => {
      const deleted = await clientRef.current.deleteConversation(conversationId);
      if (stateRef.current.openId === conversationId) {
        closeSocket();
        dispatch({ type: 'conversation-opened', conversationId: null });
      }
      await Promise.all([refresh(), loadDeleted()]);
      return deleted;
    },
    [closeSocket, loadDeleted, refresh],
  );

  const restoreConversation = useCallback(
    async (conversationId: string): Promise<Conversation> => {
      const restored = await clientRef.current.restoreConversation(conversationId);
      await Promise.all([refresh(), loadDeleted()]);
      return restored;
    },
    [loadDeleted, refresh],
  );

  // -- the context the next question carries --------------------------------------------------

  const selectContext = useCallback(
    (selection: ContextSelection) => dispatch({ type: 'context-selected', selection }),
    [],
  );
  const changeContext = useCallback(
    (changes: Partial<ContextSelection>) => dispatch({ type: 'context-changed', changes }),
    [],
  );
  const clearContext = useCallback(() => dispatch({ type: 'context-cleared' }), []);

  const previewContext = useCallback(
    async (prompt: string): Promise<ComposedContext | null> => {
      const conversationId = stateRef.current.openId;
      if (conversationId === null) {
        return null;
      }
      return clientRef.current.previewContext(
        conversationId,
        prompt,
        stateRef.current.selection,
      );
    },
    [],
  );

  // -- asking ---------------------------------------------------------------------------------

  /** The conversation to ask in, creating one if the panel has none open. */
  const conversationForAsk = useCallback(
    async (prompt: string): Promise<string> => {
      const openId = stateRef.current.openId;
      if (openId !== null) {
        return openId;
      }
      const created = await clientRef.current.createConversation(projectId, titleFrom(prompt));
      await refresh();
      dispatch({ type: 'conversation-opened', conversationId: created.id });
      return created.id;
    },
    [projectId, refresh],
  );

  /** Name a conversation from its first question, once, and never again. */
  const nameIfUnnamed = useCallback(
    (conversationId: string, prompt: string) => {
      const row = stateRef.current.conversations.find((one) => one.id === conversationId);
      if (!row || row.title !== '') {
        return;
      }
      // Best-effort: a conversation that could not be named is still a conversation. Failing an
      // ask over its label would trade the thing the writer wanted for the thing they did not.
      void clientRef.current
        .renameConversation(conversationId, titleFrom(prompt))
        .then(() => refresh())
        .catch(() => {});
    },
    [refresh],
  );

  const sendAsk = useCallback(
    async (prompt: string, rewrite: RewriteRequest | null): Promise<void> => {
      if (isStreaming(stateRef.current)) {
        // One answer at a time. A second ask while one is arriving would be a second bill for a
        // gesture the writer probably made because the first looked stuck.
        return;
      }
      const conversationId = await conversationForAsk(prompt);
      const selection = stateRef.current.selection;
      dispatch({ type: 'ask-sent', prompt, rewrite });
      nameIfUnnamed(conversationId, prompt);
      send(conversationId, { type: 'ask', prompt, context: selection });
    },
    [conversationForAsk, nameIfUnnamed, send],
  );

  const ask = useCallback(
    (prompt: string): Promise<void> => sendAsk(prompt, null),
    [sendAsk],
  );

  const runRewrite = useCallback(
    async (context: RewriteContext): Promise<void> => {
      const definition = rewriteActionDefinition(context.action);
      // The action's own range, and never whatever the panel happened to be pointing at: the
      // passage this is about is the one the anchor was minted over.
      dispatch({
        type: 'context-selected',
        selection: {
          document_id: context.documentId,
          from_pos: context.from_pos,
          to_pos: context.to_pos,
          include_chapter: true,
          entry_ids: [],
          // A replacement is asked for on its own. Earlier turns would put the transcript's own
          // words into a request whose answer goes straight into the manuscript.
          include_history: false,
        },
      });
      await sendAsk(definition.prompt, {
        action: context.action,
        anchorId: context.anchorId,
        documentId: context.documentId,
        before: context.before,
      });
    },
    [sendAsk],
  );

  const cancel = useCallback(() => {
    const conversationId = stateRef.current.openId;
    if (conversationId === null || !isStreaming(stateRef.current)) {
      return;
    }
    dispatch({ type: 'cancel-requested' });
    send(conversationId, { type: 'cancel' });
  }, [send]);

  const clearStream = useCallback(() => dispatch({ type: 'stream-cleared' }), []);

  // -- settings -------------------------------------------------------------------------------

  const readSettings = useCallback(
    (signal?: AbortSignal): Promise<SettingsDocument> => clientRef.current.getSettings(signal),
    [],
  );

  const writeSettings = useCallback(
    (patch: SettingsPatch): Promise<SettingsDocument> => clientRef.current.patchSettings(patch),
    [],
  );

  const value = useMemo<ChatContextValue>(
    () => ({
      state,
      dispatch,
      refresh,
      reload: retry,
      loadDeleted,
      openConversation,
      startConversation,
      renameConversation,
      deleteConversation,
      restoreConversation,
      selectContext,
      changeContext,
      clearContext,
      previewContext,
      ask,
      runRewrite,
      cancel,
      clearStream,
      readSettings,
      writeSettings,
      previewDebounceMs,
    }),
    [
      state,
      refresh,
      loadDeleted,
      openConversation,
      startConversation,
      renameConversation,
      deleteConversation,
      restoreConversation,
      selectContext,
      changeContext,
      clearContext,
      previewContext,
      ask,
      runRewrite,
      cancel,
      clearStream,
      readSettings,
      writeSettings,
      previewDebounceMs,
    ],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatContextValue {
  const value = useContext(ChatContext);
  if (!value) {
    throw new Error('useChat must be used inside a ChatProvider');
  }
  return value;
}

/**
 * A conversation's name, from the question that started it.
 *
 * The first line, trimmed, cut at a word boundary where there is one. A label a writer can find
 * a conversation by, and one they can change — `title` is the only mutable field a conversation
 * has, which is what makes naming it automatically safe.
 */
export function titleFrom(prompt: string): string {
  const firstLine = prompt.trim().split('\n')[0]?.trim() ?? '';
  if (firstLine.length <= TITLE_FROM_PROMPT_CHARS) {
    return firstLine;
  }
  const cut = firstLine.slice(0, TITLE_FROM_PROMPT_CHARS);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > 20 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
