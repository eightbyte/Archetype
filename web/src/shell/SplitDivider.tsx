/**
 * A resize handle between two regions (P1-9).
 *
 * Hand-rolled, and keyboard-accessible rather than mouse-only, which is the part that gets
 * skipped when a splitter is pulled off a shelf. It is a real `separator` with a value, a range,
 * and an orientation, so a screen reader announces the width it is announcing a change to:
 *
 * * **Arrow keys** move it by {@link PANE_STEP}, and by ten times that with Shift.
 * * **Home / End** take it to its narrowest and widest.
 * * **Enter / Space** collapse and expand the pane.
 *
 * Pointer dragging is the same reducer action, computed from the pointer's distance to the
 * workspace edge. Capture is taken on the handle so a fast drag that outruns the pointer does
 * not drop the gesture over a neighbouring element.
 */

import { useCallback, useRef } from 'react';
import type { KeyboardEvent, PointerEvent } from 'react';
import type { Pane } from '../state/uiReducer';
import { MAX_PANE_WIDTH, MIN_PANE_WIDTH, PANE_STEP } from '../state/uiReducer';

/** Shift makes an arrow key move the divider a paragraph's worth rather than a word's. */
export const COARSE_STEP_MULTIPLIER = 10;

export interface SplitDividerProps {
  pane: Pane;
  /** Which side of the workspace the pane is on — it decides which way the arrows read. */
  side: 'left' | 'right';
  label: string;
  width: number;
  collapsed: boolean;
  onResize: (width: number) => void;
  onNudge: (by: number) => void;
  onToggle: () => void;
}

export function SplitDivider({
  pane,
  side,
  label,
  width,
  collapsed,
  onResize,
  onNudge,
  onToggle,
}: SplitDividerProps) {
  const dragging = useRef(false);

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const step = PANE_STEP * (event.shiftKey ? COARSE_STEP_MULTIPLIER : 1);
      // A left-hand pane grows when the divider moves right; a right-hand pane does the reverse.
      const outward = side === 'left' ? step : -step;

      switch (event.key) {
        case 'ArrowRight':
          onNudge(outward);
          break;
        case 'ArrowLeft':
          onNudge(-outward);
          break;
        case 'Home':
          onResize(side === 'left' ? MIN_PANE_WIDTH : MAX_PANE_WIDTH);
          break;
        case 'End':
          onResize(side === 'left' ? MAX_PANE_WIDTH : MIN_PANE_WIDTH);
          break;
        case 'Enter':
        case ' ':
          onToggle();
          break;
        default:
          return;
      }
      event.preventDefault();
    },
    [onNudge, onResize, onToggle, side],
  );

  const onPointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }, []);

  const onPointerMove = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (!dragging.current) {
        return;
      }
      const workspace = event.currentTarget.parentElement;
      if (!workspace) {
        return;
      }
      const bounds = workspace.getBoundingClientRect();
      onResize(
        side === 'left' ? event.clientX - bounds.left : bounds.right - event.clientX,
      );
    },
    [onResize, side],
  );

  const endDrag = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) {
      return;
    }
    dragging.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  return (
    <div
      className="split-divider"
      data-pane={pane}
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={collapsed ? 0 : width}
      aria-valuemin={0}
      aria-valuemax={MAX_PANE_WIDTH}
      aria-valuetext={collapsed ? 'collapsed' : `${width} pixels`}
      onKeyDown={onKeyDown}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={onToggle}
    />
  );
}
