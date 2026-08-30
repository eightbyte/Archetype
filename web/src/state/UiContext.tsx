/**
 * Layout state, and the one place it is persisted (P1-9, D10).
 *
 * `useReducer` over `uiReducer`, plus an effect that writes the result to `localStorage`. The
 * persistence is deliberately here rather than in the reducer: a reducer that wrote to storage
 * would not be a pure function, and the direct reducer tests P1-9 asks for would need a fake
 * `localStorage` to run.
 */

import { createContext, useContext, useEffect, useMemo, useReducer } from 'react';
import type { ReactNode } from 'react';
import { readStored, STORAGE_KEYS, writeStored } from './persistence';
import type { UiAction, UiState } from './uiReducer';
import { initialUiState, uiReducer } from './uiReducer';

interface UiContextValue {
  state: UiState;
  dispatch: (action: UiAction) => void;
}

const UiContext = createContext<UiContextValue | null>(null);

export interface UiProviderProps {
  children: ReactNode;
  /** Tests pass a starting layout instead of reaching for storage. */
  initialState?: UiState;
}

export function UiProvider({ children, initialState }: UiProviderProps) {
  const [state, dispatch] = useReducer(
    uiReducer,
    initialState,
    (given) => given ?? initialUiState(readStored(STORAGE_KEYS.ui, (raw) => raw)),
  );

  useEffect(() => {
    writeStored(STORAGE_KEYS.ui, state);
  }, [state]);

  const value = useMemo<UiContextValue>(() => ({ state, dispatch }), [state]);
  return <UiContext.Provider value={value}>{children}</UiContext.Provider>;
}

export function useUi(): UiContextValue {
  const value = useContext(UiContext);
  if (!value) {
    throw new Error('useUi must be used inside a UiProvider');
  }
  return value;
}
