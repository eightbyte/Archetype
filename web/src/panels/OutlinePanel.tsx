/**
 * The outline panel and its tabs (P1-9, P1-11, P2-10).
 *
 * Five tabs, two of which have anything behind them: Contents (P1-11) and Marks (P2-10). The
 * other three are here rather than added later because the tab strip is a layout commitment: a
 * panel that grows a tab strip in Phase 3 is a panel whose every measurement changes in Phase 3.
 * They say which phase they arrive in rather than pretending to be empty.
 *
 * Marks was the one deliberate widening (phase-2-plan section 2, ruling 6): anchors needed a home
 * this phase, and folding them into Contents would have put two unrelated trees in one scroll.
 *
 * The tab strip follows the ARIA tabs pattern, including roving focus: one tab is in the tab
 * order and the arrow keys move between them, so reaching the Contents list does not mean
 * tabbing past three placeholders.
 */

import { useCallback, useRef } from 'react';
import type { KeyboardEvent } from 'react';
import { useUi } from '../state/UiContext';
import type { OutlineTab } from '../state/uiReducer';
import { OUTLINE_TABS } from '../state/uiReducer';
import { MarksTab } from './MarksTab';
import { TableOfContents } from './TableOfContents';

interface TabDefinition {
  id: OutlineTab;
  label: string;
  /** What is behind it, or when it arrives. */
  note: string;
}

const TABS: Record<OutlineTab, TabDefinition> = {
  contents: { id: 'contents', label: 'Contents', note: '' },
  marks: { id: 'marks', label: 'Marks', note: '' },
  timeline: {
    id: 'timeline',
    label: 'Timeline',
    note: 'The narrative timeline is built in Phase 8, once the story bible has events to place.',
  },
  characters: {
    id: 'characters',
    label: 'Characters',
    note: 'The character interaction chart is built in Phase 8 (D14).',
  },
  bible: {
    id: 'bible',
    label: 'Bible',
    note: 'The story bible is built in Phase 3.',
  },
};

export function OutlinePanel() {
  const { state, dispatch } = useUi();
  const active = state.activeOutlineTab;
  const strip = useRef<HTMLDivElement>(null);

  const select = useCallback(
    (tab: OutlineTab) => dispatch({ type: 'select-outline-tab', tab }),
    [dispatch],
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const index = OUTLINE_TABS.indexOf(active);
      let next = index;
      if (event.key === 'ArrowRight') {
        next = (index + 1) % OUTLINE_TABS.length;
      } else if (event.key === 'ArrowLeft') {
        next = (index - 1 + OUTLINE_TABS.length) % OUTLINE_TABS.length;
      } else if (event.key === 'Home') {
        next = 0;
      } else if (event.key === 'End') {
        next = OUTLINE_TABS.length - 1;
      } else {
        return;
      }
      event.preventDefault();
      const tab = OUTLINE_TABS[next];
      if (tab) {
        select(tab);
        strip.current?.querySelector<HTMLButtonElement>(`#outline-tab-${tab}`)?.focus();
      }
    },
    [active, select],
  );

  return (
    <div className="outline-panel">
      <div
        className="tabs"
        role="tablist"
        aria-label="Outline views"
        ref={strip}
        onKeyDown={onKeyDown}
      >
        {OUTLINE_TABS.map((tab) => (
          <button
            key={tab}
            id={`outline-tab-${tab}`}
            type="button"
            role="tab"
            aria-selected={tab === active}
            aria-controls={`outline-panel-${tab}`}
            tabIndex={tab === active ? 0 : -1}
            onClick={() => select(tab)}
          >
            {TABS[tab].label}
          </button>
        ))}
      </div>

      <div
        className="tab-panel"
        role="tabpanel"
        id={`outline-panel-${active}`}
        aria-labelledby={`outline-tab-${active}`}
        tabIndex={0}
      >
        {active === 'contents' && <TableOfContents />}
        {active === 'marks' && <MarksTab />}
        {active !== 'contents' && active !== 'marks' && (
          <p className="panel-placeholder">{TABS[active].note}</p>
        )}
      </div>
    </div>
  );
}
