/**
 * The assistant panel — the Phase 1 placeholder, replaced (P4-12, P4-14, P4-15).
 *
 * The right-hand region has taken its third of the workspace since P1-9, holding a paragraph
 * about what would arrive in Phase 4. This is what arrived: a conversation list, a transcript, a
 * composer that shows what will be sent before it goes, the three single-pass actions, and the
 * settings screen behind them.
 *
 * ## Three views, and no router
 *
 * The list, one conversation, and the settings. Which is showing is state, exactly as it is in
 * `App.tsx`: there is no router in the dependency budget and a panel with three screens does not
 * need one (D10).
 *
 * ## Its own error boundary, inside the region's
 *
 * `Workspace` already wraps this region, and the Bible tab established the rule one level in
 * (P3-12): the largest surface with the most to go wrong in it takes itself down rather than the
 * panel around it. Here the reason is sharper still — an answer arriving in fragments over a
 * socket is the one thing in this application whose state a render can be caught in the middle
 * of, and a panel that cannot draw must never be the reason the writing surface is not.
 */

import { useState } from 'react';
import { ErrorBoundary } from '../shell/ErrorBoundary';
import { useChat } from '../state/ChatContext';
import { isStreaming, totalUsage } from '../state/chatReducer';
import { usageWords } from '../chatText';
import { ChatComposer } from './ChatComposer';
import { ConversationList, titleOf } from './ConversationList';
import { RewriteActions } from './RewriteActions';
import { RewriteDiff } from './RewriteDiff';
import { SettingsScreen } from './SettingsScreen';
import { Transcript } from './Transcript';

export function AgentPanel() {
  const { state, openConversation } = useChat();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const open = state.conversations.find((row) => row.id === state.openId) ?? null;
  const usage = totalUsage(state.messages);
  // The diff is offered once the answer has finished arriving. A failed action shows its failure
  // in the transcript like any other turn; there is nothing to accept.
  const diff = state.rewrite !== null && state.stream.phase === 'done' ? state.rewrite : null;

  return (
    <div className="agent-panel">
      <header className="agent-panel-head">
        <h2 className="panel-heading">Assistant</h2>
        <button
          type="button"
          className="agent-settings-toggle"
          aria-expanded={settingsOpen}
          onClick={() => setSettingsOpen((showing) => !showing)}
        >
          {settingsOpen ? 'Back' : 'Settings'}
        </button>
      </header>

      <ErrorBoundary region="Assistant panel">
        {settingsOpen ? (
          <SettingsScreen />
        ) : state.openId === null || open === null ? (
          <ConversationList />
        ) : (
          <div className="chat-conversation">
            <div className="chat-conversation-head">
              <button
                type="button"
                className="chat-back"
                disabled={isStreaming(state)}
                onClick={() => void openConversation(null)}
              >
                ← Conversations
              </button>
              <span className="chat-conversation-title">{titleOf(open)}</span>
              <span className="chat-conversation-usage">{usageWords(usage, usage.reported)}</span>
            </div>

            <Transcript messages={state.messages} stream={state.stream} />

            {diff && <RewriteDiff request={diff} after={state.stream.text} />}

            <RewriteActions />
            <ChatComposer autoFocus={state.stream.phase === 'idle'} />
          </div>
        )}
      </ErrorBoundary>
    </div>
  );
}
