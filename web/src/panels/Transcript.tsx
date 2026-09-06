/**
 * One conversation, turn by turn, with the answer that is arriving at the bottom (P4-12, D30).
 *
 * Two sources, deliberately kept apart. The **stored** turns are the server's answer, read back
 * from the project file; the **streaming** turn is what is arriving now and has not been read
 * back yet. They are never merged into one list here: the socket carries D32's five events and no
 * persisted ids, so a locally-built row would be a guess at what the server wrote, and the moment
 * the re-read lands the guess and the row would both be on screen.
 *
 * Instead the stream is drawn *after* the stored turns and disappears when the re-read arrives —
 * the terminator is sent after the row is written, so that read cannot lose the race.
 *
 * Three things a writer must be able to see and this component exists to show:
 *
 * * **what an answer cost**, per turn, with zero meaning *not reported* rather than free;
 * * **that a turn failed, and why** — a failed turn is a stored turn, so the transcript says what
 *   went wrong rather than leaving a gap the writer has to remember;
 * * **that a turn was cancelled** — a `stop_reason` and never an `error_code`, because a
 *   deliberate act is not a failure.
 */

import { useEffect, useRef } from 'react';
import type { ChatMessage } from '../api';
import { providerErrorWords, stopReasonWords, usageWords } from '../chatText';
import { formatRelativeTime } from '../format';
import type { StreamState } from '../state/chatReducer';

export interface TranscriptProps {
  messages: readonly ChatMessage[];
  stream: StreamState;
}

export function Transcript({ messages, stream }: TranscriptProps) {
  const foot = useRef<HTMLDivElement | null>(null);

  // Follow the answer down. Guarded because jsdom implements neither of these.
  useEffect(() => {
    const node = foot.current;
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'end' });
    }
  }, [messages.length, stream.text, stream.phase]);

  const streaming = stream.phase !== 'idle';

  return (
    <div className="chat-transcript" aria-label="Conversation">
      {messages.length === 0 && !streaming && (
        <p className="panel-placeholder">
          Nothing has been asked yet. What is sent is shown below before it goes.
        </p>
      )}

      {messages.map((message) => (
        <StoredTurn key={message.id} message={message} />
      ))}

      {streaming && <StreamingTurn stream={stream} />}
      <div ref={foot} />
    </div>
  );
}

function StoredTurn({ message }: { message: ChatMessage }) {
  const failed = message.error_code !== '';
  const ended = stopReasonWords(message.stop_reason);
  const words = failed ? providerErrorWords(message.error_code) : null;

  return (
    <article className={`chat-turn chat-turn-${message.role}`}>
      <header className="chat-turn-head">
        <span className="chat-turn-role">{message.role === 'user' ? 'You' : 'Assistant'}</span>
        <span className="chat-turn-meta">{formatRelativeTime(message.created_at)}</span>
      </header>

      {message.content !== '' && <p className="chat-turn-body">{message.content}</p>}

      {words && (
        <p className="chat-turn-error" role="alert">
          <strong>{words.title}.</strong> {message.content === '' ? '' : 'The part that arrived is above. '}
          {words.advice}
        </p>
      )}

      {message.role === 'assistant' && (
        <footer className="chat-turn-foot">
          {ended && <span className="chat-turn-stop">{ended}</span>}
          <span className="chat-turn-usage">{usageWords(message.usage)}</span>
          {message.model !== '' && <span className="chat-turn-model">{message.model}</span>}
        </footer>
      )}
    </article>
  );
}

function StreamingTurn({ stream }: { stream: StreamState }) {
  const words = stream.failure ? providerErrorWords(stream.failure.code) : null;
  const ended = stream.stopReason ? stopReasonWords(stream.stopReason) : null;

  return (
    <>
      <article className="chat-turn chat-turn-user">
        <header className="chat-turn-head">
          <span className="chat-turn-role">You</span>
        </header>
        <p className="chat-turn-body">{stream.prompt}</p>
      </article>

      <article className="chat-turn chat-turn-assistant">
        <header className="chat-turn-head">
          <span className="chat-turn-role">Assistant</span>
          {stream.phase === 'waiting' && (
            <span className="chat-turn-meta" role="status">
              {stream.cancelling ? 'Stopping…' : 'Waiting for the first words…'}
            </span>
          )}
        </header>

        {stream.text !== '' && <p className="chat-turn-body">{stream.text}</p>}

        {words && (
          <p className="chat-turn-error" role="alert">
            <strong>{words.title}.</strong> {words.advice}
            {stream.failure?.message ? ` ${stream.failure.message}` : ''}
          </p>
        )}

        {stream.phase === 'done' && (
          <footer className="chat-turn-foot">
            {ended && <span className="chat-turn-stop">{ended}</span>}
            <span className="chat-turn-usage">{usageWords(stream.usage, stream.usageReported)}</span>
            {stream.model !== '' && <span className="chat-turn-model">{stream.model}</span>}
          </footer>
        )}
      </article>
    </>
  );
}
