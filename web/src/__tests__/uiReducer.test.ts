/**
 * P1-9 — the layout reducer, tested apart from React.
 *
 * The rules here are the ones a divider, a keyboard, and a restored `localStorage` value all have
 * to obey identically. Testing them at the reducer is what makes that true for all three rather
 * than for whichever one was tested through the DOM.
 */

import { describe, expect, test } from 'vitest';
import {
  clampWidth,
  collapsedOf,
  initialUiState,
  INITIAL_UI_STATE,
  MAX_PANE_WIDTH,
  MIN_PANE_WIDTH,
  uiReducer,
  widthOf,
} from '../state/uiReducer';
import type { UiState } from '../state/uiReducer';

describe('resizing', () => {
  test('a width within range is taken as given', () => {
    const next = uiReducer(INITIAL_UI_STATE, { type: 'resize-pane', pane: 'outline', width: 300 });
    expect(next.outlineWidth).toBe(300);
  });

  test('a width below the minimum is clamped, not rejected', () => {
    const next = uiReducer(INITIAL_UI_STATE, { type: 'resize-pane', pane: 'outline', width: 20 });
    expect(next.outlineWidth).toBe(MIN_PANE_WIDTH);
  });

  test('a side pane may not eat the writing surface', () => {
    const next = uiReducer(INITIAL_UI_STATE, { type: 'resize-pane', pane: 'agent', width: 5_000 });
    expect(next.agentWidth).toBe(MAX_PANE_WIDTH);
  });

  test('a width that is not a number falls back rather than poisoning the layout', () => {
    expect(clampWidth(Number.NaN)).toBe(MIN_PANE_WIDTH);
    expect(clampWidth(Number.POSITIVE_INFINITY)).toBe(MIN_PANE_WIDTH);
  });

  test('resizing one pane leaves the other alone', () => {
    const next = uiReducer(INITIAL_UI_STATE, { type: 'resize-pane', pane: 'outline', width: 400 });
    expect(next.agentWidth).toBe(INITIAL_UI_STATE.agentWidth);
  });

  test('a nudge moves from where the pane is now', () => {
    const next = uiReducer(INITIAL_UI_STATE, { type: 'nudge-pane', pane: 'outline', by: 16 });
    expect(next.outlineWidth).toBe(INITIAL_UI_STATE.outlineWidth + 16);
  });

  test('a nudge past the end stops at the end', () => {
    const next = uiReducer(INITIAL_UI_STATE, { type: 'nudge-pane', pane: 'outline', by: -10_000 });
    expect(next.outlineWidth).toBe(MIN_PANE_WIDTH);
  });

  test('a resize to the width it already has returns the same object', () => {
    const state = uiReducer(INITIAL_UI_STATE, { type: 'resize-pane', pane: 'outline', width: 300 });
    expect(uiReducer(state, { type: 'resize-pane', pane: 'outline', width: 300 })).toBe(state);
  });
});

describe('collapsing', () => {
  test('toggling collapses and expands', () => {
    const collapsed = uiReducer(INITIAL_UI_STATE, { type: 'toggle-pane', pane: 'agent' });
    expect(collapsedOf(collapsed, 'agent')).toBe(true);
    expect(collapsedOf(uiReducer(collapsed, { type: 'toggle-pane', pane: 'agent' }), 'agent')).toBe(
      false,
    );
  });

  test('collapsing keeps the width, so expanding restores what the writer chose', () => {
    const wide = uiReducer(INITIAL_UI_STATE, { type: 'resize-pane', pane: 'outline', width: 420 });
    const collapsed = uiReducer(wide, { type: 'toggle-pane', pane: 'outline' });
    const expanded = uiReducer(collapsed, { type: 'toggle-pane', pane: 'outline' });

    expect(widthOf(collapsed, 'outline')).toBe(420);
    expect(expanded.outlineCollapsed).toBe(false);
    expect(widthOf(expanded, 'outline')).toBe(420);
  });

  test('setting a pane to the state it is in returns the same object', () => {
    expect(
      uiReducer(INITIAL_UI_STATE, { type: 'set-pane-collapsed', pane: 'agent', collapsed: false }),
    ).toBe(INITIAL_UI_STATE);
  });
});

describe('the outline tab', () => {
  test('selecting a tab changes it', () => {
    const next = uiReducer(INITIAL_UI_STATE, { type: 'select-outline-tab', tab: 'bible' });
    expect(next.activeOutlineTab).toBe('bible');
  });

  test('selecting the current tab returns the same object', () => {
    expect(uiReducer(INITIAL_UI_STATE, { type: 'select-outline-tab', tab: 'contents' })).toBe(
      INITIAL_UI_STATE,
    );
  });
});

describe('starting from what was persisted', () => {
  test('a full stored state comes back', () => {
    const stored: UiState = {
      outlineWidth: 300,
      agentWidth: 260,
      outlineCollapsed: true,
      agentCollapsed: false,
      activeOutlineTab: 'timeline',
    };
    expect(initialUiState(stored)).toEqual(stored);
  });

  test('nothing stored is the default layout', () => {
    expect(initialUiState(null)).toEqual(INITIAL_UI_STATE);
    expect(initialUiState(undefined)).toEqual(INITIAL_UI_STATE);
  });

  test.each([['a string', '{}'], ['a number', 7], ['an array', [1, 2]]])(
    '%s is not a layout',
    (_name, stored) => {
      expect(initialUiState(stored)).toEqual(INITIAL_UI_STATE);
    },
  );

  test('a field of the wrong type falls back on its own, not on the whole layout', () => {
    const restored = initialUiState({ outlineWidth: 'wide', agentWidth: 240 });
    expect(restored.outlineWidth).toBe(INITIAL_UI_STATE.outlineWidth);
    expect(restored.agentWidth).toBe(240);
  });

  test('a stored width outside the range is clamped on the way in', () => {
    expect(initialUiState({ outlineWidth: 9_000 }).outlineWidth).toBe(MAX_PANE_WIDTH);
  });

  test('a tab name from a future version is not believed', () => {
    expect(initialUiState({ activeOutlineTab: 'revisions' }).activeOutlineTab).toBe('contents');
  });
});
