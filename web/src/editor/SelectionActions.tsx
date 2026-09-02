/**
 * The control that appears over a selection (P2-9, P2-10).
 *
 * Two jobs, and which one it offers depends on whether a repair is in progress:
 *
 * * ordinarily, **Mark passage** — anchor what is selected;
 * * while the *Marks* tab has armed a manual re-link, **Re-link here** — point that anchor at
 *   what is selected instead, in whichever chapter the writer has ended up in.
 *
 * Both send a range and the document version, and nothing else. The server reads the quote and
 * its context out of the text it holds, so a client cannot create or repair an anchor whose
 * quote disagrees with the manuscript — it is never asked what the manuscript says.
 *
 * Positioned from `coordsAtPos` rather than from a library: a bubble menu would be a dependency
 * and a positioning engine for one small control (outline § 8, D10). It is placed above the
 * start of the selection and clamped into the editor's own box, and it is a real button in the
 * document either way — so it is reachable by keyboard and assertable in a test whether or not
 * the layout engine has opinions.
 */

import { useCallback, useEffect, useState } from 'react';
import type { Editor } from '@tiptap/react';

export interface SelectionRange {
  from: number;
  to: number;
}

export interface SelectionActionsProps {
  editor: Editor | null;
  /** Anchor the selection. */
  onMark: (range: SelectionRange) => void;
  /** The anchor being re-linked by hand, described for the writer, or null. */
  relinking: { anchorId: string; description: string } | null;
  onRelink: (range: SelectionRange) => void;
  onCancelRelink: () => void;
  /** True while a request is in the air, so the control cannot be pressed twice. */
  busy: boolean;
}

interface Placement {
  range: SelectionRange;
  top: number;
  left: number;
}

export function SelectionActions({
  editor,
  onMark,
  relinking,
  onRelink,
  onCancelRelink,
  busy,
}: SelectionActionsProps) {
  const [placement, setPlacement] = useState<Placement | null>(null);

  const recompute = useCallback((instance: Editor) => {
    const { from, to, empty } = instance.state.selection;
    if (empty) {
      setPlacement(null);
      return;
    }
    setPlacement({ range: { from, to }, ...pointAbove(instance, from) });
  }, []);

  useEffect(() => {
    if (!editor) {
      return;
    }
    const update = () => recompute(editor);
    update();
    // `transaction` as well as `selectionUpdate`: typing inside a selection replaces it, and a
    // control left hanging over text that is no longer selected is worse than none at all.
    editor.on('selectionUpdate', update);
    editor.on('transaction', update);
    return () => {
      editor.off('selectionUpdate', update);
      editor.off('transaction', update);
    };
  }, [editor, recompute]);

  if (!placement) {
    // A repair in progress still needs a way out, even with nothing selected — otherwise the
    // only way to abandon one is to go back to the panel and find the anchor again.
    return relinking ? (
      <div
        className="selection-actions selection-actions-idle"
        role="status"
        aria-label="Re-linking a mark"
      >
        <span>Select the passage for {relinking.description}.</span>
        <button type="button" onClick={onCancelRelink}>
          Cancel
        </button>
      </div>
    ) : null;
  }

  return (
    <div
      className="selection-actions"
      style={{ top: `${placement.top}px`, left: `${placement.left}px` }}
    >
      {relinking ? (
        <>
          <span>Re-link {relinking.description}</span>
          <button type="button" disabled={busy} onClick={() => onRelink(placement.range)}>
            Re-link here
          </button>
          <button type="button" onClick={onCancelRelink}>
            Cancel
          </button>
        </>
      ) : (
        <button type="button" disabled={busy} onClick={() => onMark(placement.range)}>
          {busy ? 'Marking…' : 'Mark passage'}
        </button>
      )}
    </div>
  );
}

/**
 * Where to draw the control, in the coordinates of the editor's scrolling box.
 *
 * `coordsAtPos` answers in viewport coordinates, so the editor's own box is subtracted back
 * out. jsdom reports zeros for every rectangle, which places the control at the top left and
 * changes nothing about whether it is there — the position is a nicety, the button is the
 * feature.
 */
function pointAbove(editor: Editor, position: number): { top: number; left: number } {
  const box = editor.view.dom.getBoundingClientRect();
  const coords = editor.view.coordsAtPos(position);
  return {
    top: Math.max(0, coords.top - box.top - 34),
    left: Math.max(0, coords.left - box.left),
  };
}
