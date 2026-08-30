/**
 * Where transient failures appear (P1-13).
 *
 * A live region so a message is announced rather than only shown, and dismissible so it can be
 * got out of the way. It sits above the workspace and takes no layout space, because a message
 * that reflows the editor mid-sentence is its own small disaster.
 */

import { useToasts } from '../state/ToastContext';

export function Toasts() {
  const { toasts, dismiss } = useToasts();

  return (
    <div className="toasts" role="log" aria-live="polite" aria-label="Notifications">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.tone}`} data-testid="toast">
          <span>{toast.message}</span>
          <button type="button" aria-label="Dismiss" onClick={() => dismiss(toast.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
