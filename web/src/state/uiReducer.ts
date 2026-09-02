/**
 * Workspace layout state (P1-9, D10).
 *
 * Pane widths, which panes are collapsed, and which outline tab is showing. Split by lifetime,
 * not by screen: this outlives every project and every document, which is why it is its own
 * reducer rather than a corner of one of the others.
 *
 * Pure — no React, no `localStorage`, no DOM. The provider wires those in; the rules live here
 * where they can be tested directly (P1-9's "reducers have direct tests").
 *
 * Clamping belongs to the reducer rather than to the divider that calls it. A pointer drag, an
 * arrow key, and a value restored from storage all arrive by different paths, and a pane width
 * that only some of them check is a pane width that is sometimes wrong.
 */

/**
 * The outline panel's tabs.
 *
 * `marks` was added in Phase 2 (P2-10, phase-2-plan section 2 ruling 6) and is a deliberate act:
 * the four were fixed in P1-9 precisely so the tab strip would not be re-measured later.
 * Anchors needed a home this phase — the exit criteria are not demonstrable without one — and
 * folding them into Contents would have put two unrelated trees in one scroll.
 *
 * It sits next to Contents because the two are the manuscript's two indexes: one of structure,
 * one of cited passages. `timeline`, `characters`, and `bible` still have nothing behind them.
 */
export const OUTLINE_TABS = ['contents', 'marks', 'timeline', 'characters', 'bible'] as const;

export type OutlineTab = (typeof OUTLINE_TABS)[number];

/** The two panes that flank the editor. The editor itself takes whatever is left. */
export type Pane = 'outline' | 'agent';

export interface UiState {
  outlineWidth: number;
  agentWidth: number;
  outlineCollapsed: boolean;
  agentCollapsed: boolean;
  activeOutlineTab: OutlineTab;
}

export type UiAction =
  | { type: 'resize-pane'; pane: Pane; width: number }
  | { type: 'nudge-pane'; pane: Pane; by: number }
  | { type: 'toggle-pane'; pane: Pane }
  | { type: 'set-pane-collapsed'; pane: Pane; collapsed: boolean }
  | { type: 'select-outline-tab'; tab: OutlineTab };

/** Narrow enough to be worth having, wide enough to read a chapter title in. */
export const MIN_PANE_WIDTH = 180;

/** A side pane may not eat the writing surface. At 1280px this still leaves a usable measure. */
export const MAX_PANE_WIDTH = 560;

/** How far one arrow key moves a divider. Shift multiplies it — see `nudge-pane`. */
export const PANE_STEP = 16;

export const INITIAL_UI_STATE: UiState = {
  outlineWidth: 280,
  agentWidth: 320,
  outlineCollapsed: false,
  agentCollapsed: false,
  activeOutlineTab: 'contents',
};

export function uiReducer(state: UiState, action: UiAction): UiState {
  switch (action.type) {
    case 'resize-pane':
      return withWidth(state, action.pane, clampWidth(action.width));

    case 'nudge-pane': {
      // Dragging a collapsed pane open by keyboard would be a surprise; widening it is not.
      const current = widthOf(state, action.pane);
      return withWidth(state, action.pane, clampWidth(current + action.by));
    }

    case 'toggle-pane':
      return withCollapsed(state, action.pane, !collapsedOf(state, action.pane));

    case 'set-pane-collapsed':
      return collapsedOf(state, action.pane) === action.collapsed
        ? state
        : withCollapsed(state, action.pane, action.collapsed);

    case 'select-outline-tab':
      return state.activeOutlineTab === action.tab ? state : { ...state, activeOutlineTab: action.tab };
  }
}

/** A width the layout will accept, whatever it was asked for. */
export function clampWidth(width: number): number {
  if (!Number.isFinite(width)) {
    return MIN_PANE_WIDTH;
  }
  return Math.round(Math.min(MAX_PANE_WIDTH, Math.max(MIN_PANE_WIDTH, width)));
}

export function widthOf(state: UiState, pane: Pane): number {
  return pane === 'outline' ? state.outlineWidth : state.agentWidth;
}

export function collapsedOf(state: UiState, pane: Pane): boolean {
  return pane === 'outline' ? state.outlineCollapsed : state.agentCollapsed;
}

/**
 * Build the starting state from whatever was persisted, ignoring anything unusable.
 *
 * Deliberately field by field: a stored object missing a key, carrying a key from a future
 * version, or holding a width someone typed into the console all resolve to a workspace that
 * opens. There is no version number on this because there is nothing here worth migrating —
 * a layout that cannot be read is a layout that goes back to the default.
 */
export function initialUiState(stored: unknown): UiState {
  if (typeof stored !== 'object' || stored === null || Array.isArray(stored)) {
    return INITIAL_UI_STATE;
  }
  const raw = stored as Record<string, unknown>;
  return {
    outlineWidth: numberOr(raw['outlineWidth'], INITIAL_UI_STATE.outlineWidth),
    agentWidth: numberOr(raw['agentWidth'], INITIAL_UI_STATE.agentWidth),
    outlineCollapsed: booleanOr(raw['outlineCollapsed'], INITIAL_UI_STATE.outlineCollapsed),
    agentCollapsed: booleanOr(raw['agentCollapsed'], INITIAL_UI_STATE.agentCollapsed),
    activeOutlineTab: tabOr(raw['activeOutlineTab'], INITIAL_UI_STATE.activeOutlineTab),
  };
}

function withWidth(state: UiState, pane: Pane, width: number): UiState {
  if (widthOf(state, pane) === width) {
    return state;
  }
  return pane === 'outline' ? { ...state, outlineWidth: width } : { ...state, agentWidth: width };
}

function withCollapsed(state: UiState, pane: Pane, collapsed: boolean): UiState {
  return pane === 'outline'
    ? { ...state, outlineCollapsed: collapsed }
    : { ...state, agentCollapsed: collapsed };
}

function numberOr(raw: unknown, fallback: number): number {
  return typeof raw === 'number' && Number.isFinite(raw) ? clampWidth(raw) : fallback;
}

function booleanOr(raw: unknown, fallback: boolean): boolean {
  return typeof raw === 'boolean' ? raw : fallback;
}

function tabOr(raw: unknown, fallback: OutlineTab): OutlineTab {
  return OUTLINE_TABS.includes(raw as OutlineTab) ? (raw as OutlineTab) : fallback;
}
