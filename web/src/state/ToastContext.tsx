/**
 * Transient failure messages (P1-13).
 *
 * A toast is for something that failed and will not otherwise be visible — a rename that did
 * not take, a chapter that could not be created. It is deliberately *not* how save failures are
 * reported: those have a persistent status indicator (P1-10), because a message that fades is
 * the wrong shape for a condition that has not gone away.
 *
 * Modest by design; Phase 9 hardens error surfaces properly.
 */

import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export type ToastTone = 'error' | 'notice';

export interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastContextValue {
  toasts: readonly Toast[];
  push: (message: string, tone?: ToastTone) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/** How long a toast stays before it withdraws itself. */
export const TOAST_TIMEOUT_MS = 6_000;

export interface ToastProviderProps {
  children: ReactNode;
  timeoutMs?: number;
}

export function ToastProvider({ children, timeoutMs = TOAST_TIMEOUT_MS }: ToastProviderProps) {
  const [toasts, setToasts] = useState<readonly Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (message: string, tone: ToastTone = 'error') => {
      const id = nextId.current;
      nextId.current += 1;
      setToasts((current) => [...current, { id, message, tone }]);
      if (timeoutMs > 0) {
        setTimeout(() => dismiss(id), timeoutMs);
      }
    },
    [dismiss, timeoutMs],
  );

  const value = useMemo<ToastContextValue>(
    () => ({ toasts, push, dismiss }),
    [toasts, push, dismiss],
  );
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToasts(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) {
    throw new Error('useToasts must be used inside a ToastProvider');
  }
  return value;
}
