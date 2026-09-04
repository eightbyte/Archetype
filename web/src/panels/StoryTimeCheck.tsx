/**
 * What story-time currently says — and what it says cannot all be true (D28).
 *
 * ## This is not the timeline
 *
 * Phase 8 owns the timeline and the interaction chart, and Phase 3's non-goals say so in as many
 * words. What is here is a **readout of the ordering module's three answers**: the order, the
 * events it could not place, and the contradictions. No axis, no scale, no drawing, nothing
 * positioned by a number.
 *
 * It exists because § 8's acceptance run has to be runnable: two of its fifteen steps are "the
 * contradiction is reported naming both events, and the rest of the events are still ordered" and
 * "it is listed as unplaced, not ordered arbitrarily and not dropped". Neither is demonstrable
 * against a route nothing calls, and a phase whose exit criteria cannot be exercised is a phase
 * that ships its riskiest decision unproven — which is the argument P3-8 already made for
 * building the ordering module in this phase rather than in Phase 8.
 *
 * Three things it shows, and nothing added to them:
 *
 * * **the order** — every event the edges and keys could place, in that order;
 * * **the unplaced** — an event with neither an edge nor a key. Not appended, not dropped, and
 *   never guessed at (D9);
 * * **the contradictions** — exactly two kinds, a cycle in `precedes` and a `sort_key` inversion
 *   across an edge, reported independently because a writer fixes them differently.
 *
 * A contradiction never costs the rest of the graph: a cycle is reported *and* everything outside
 * it is still ordered, because a timeline that refuses to draw anything until two events agree is
 * a timeline nobody can use to find the disagreement.
 */

import { useCallback, useEffect, useState } from 'react';
import type { StoryEvent, StoryTime } from '../api/types';
import { CONTRADICTION_KINDS } from '../api/types';
import { useBible } from '../state/BibleContext';
import { describeFailure } from '../state/ProjectContext';

export interface StoryTimeCheckProps {
  /** Bumped by the tab when an entry is written, so the reading follows the bible. */
  refreshKey: number;
  /** Open one of the events. */
  onOpen: (entryId: string) => void;
}

export function StoryTimeCheck({ refreshKey, onOpen }: StoryTimeCheckProps) {
  const { readStoryTime } = useBible();
  const [storyTime, setStoryTime] = useState<StoryTime | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    void (async () => {
      try {
        const answer = await readStoryTime();
        if (live) {
          setStoryTime(answer);
        }
      } catch (failure: unknown) {
        if (live) {
          setError(describeFailure(failure));
        }
      }
    })();
    return () => {
      live = false;
    };
  }, [readStoryTime, refreshKey]);

  const name = useCallback(
    (event: StoryEvent) => (event.label === '' ? event.name : `${event.name} — ${event.label}`),
    [],
  );

  if (error !== null) {
    return (
      <p className="panel-placeholder" role="alert">
        Could not read story-time — {error}
      </p>
    );
  }
  if (storyTime === null) {
    return <p className="panel-placeholder">Reading story-time…</p>;
  }
  if (storyTime.order.length === 0 && storyTime.unplaced.length === 0) {
    return (
      <p className="panel-placeholder">
        No events yet. Give an event a “when” or a <em>comes before</em> link and it appears here.
      </p>
    );
  }

  return (
    <div className="storytime">
      {storyTime.contradictions.length > 0 && (
        <section className="storytime-contradictions" aria-label="Contradictions">
          <h4>Cannot all be true</h4>
          <ul>
            {storyTime.contradictions.map((contradiction, index) => (
              <li key={`${contradiction.kind}-${index}`} className="storytime-contradiction">
                <span className="storytime-contradiction-kind">
                  {contradiction.kind === CONTRADICTION_KINDS.cycle
                    ? 'A loop in “comes before”'
                    : 'The order disagrees with the sort keys'}
                </span>
                <p>{contradiction.detail}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="storytime-order" aria-label="Story order">
        <h4>In order</h4>
        {storyTime.order.length === 0 ? (
          <p className="panel-placeholder">Nothing could be placed.</p>
        ) : (
          <ol>
            {storyTime.order.map((event) => (
              <li key={event.entry_id}>
                <button type="button" onClick={() => onOpen(event.entry_id)}>
                  {name(event)}
                </button>
                {event.era !== null && <span className="storytime-era">{event.era}</span>}
              </li>
            ))}
          </ol>
        )}
      </section>

      {storyTime.unplaced.length > 0 && (
        <section className="storytime-unplaced" aria-label="Unplaced events">
          <h4>Not placed</h4>
          <p className="panel-placeholder">
            Neither a sort key nor a “comes before” says where these go. They are not guessed at.
          </p>
          <ul>
            {storyTime.unplaced.map((event) => (
              <li key={event.entry_id}>
                <button type="button" onClick={() => onOpen(event.entry_id)}>
                  {name(event)}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {storyTime.eras.length > 0 && (
        <section className="storytime-eras" aria-label="Eras">
          <h4>Eras</h4>
          <ul>
            {storyTime.eras.map((era) => (
              <li key={era.era}>
                {era.era}
                {era.rank === null && <span className="storytime-era-unranked"> — unplaced</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
