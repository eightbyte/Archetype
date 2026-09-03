/**
 * The control that appears over a selection (P2-9, P2-10, P3-14).
 *
 * Three jobs, and which of them it offers depends on whether a repair is in progress:
 *
 * * ordinarily, **Mark passage** — anchor what is selected — and **Add to bible**, which anchors
 *   it *and* makes an entry out of it in one act;
 * * while the *Marks* tab has armed a manual re-link, **Re-link here** — point that anchor at
 *   what is selected instead, in whichever chapter the writer has ended up in.
 *
 * All three send a range and the document version, and nothing else. The server reads the quote
 * and its context out of the text it holds, so a client cannot create, repair, or cite an anchor
 * whose quote disagrees with the manuscript — it is never asked what the manuscript says.
 *
 * *Add to bible* is the interaction the whole product is arranged around — the outline's
 * "selecting text and asking a question about it", in its manual form — so it is two fields and a
 * button rather than a dialog: choose a kind, type a name, done. Everything else about the entry
 * is filled in afterwards, in the Bible tab, on a form that has room for it.
 *
 * **The range is frozen when that form opens.** Typing into the name field takes focus out of the
 * editor and a stray transaction would otherwise move the selection under the writer's hands, so
 * the control keeps the range and the position it had at the moment they asked.
 *
 * Positioned from `coordsAtPos` rather than from a library: a bubble menu would be a dependency
 * and a positioning engine for one small control (outline § 8, D10). It is placed above the
 * start of the selection and clamped into the editor's own box, and it is a real button in the
 * document either way — so it is reachable by keyboard and assertable in a test whether or not
 * the layout engine has opinions.
 */

import { useCallback, useEffect, useState } from 'react';
import type { Editor } from '@tiptap/react';
import type { KindDefinition } from '../api/types';

export interface SelectionRange {
  from: number;
  to: number;
}

/** What *Add to bible* was asked for: a kind from the served definition, and a name. */
export interface BibleDraft {
  kind: string;
  name: string;
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
  /**
   * The kinds an entry may be, from the served definition (D26).
   *
   * Empty when the bible's definition has not arrived — in which case *Add to bible* is not
   * offered at all, rather than offering a picker with nothing in it.
   */
  kinds: readonly KindDefinition[];
  onAddToBible: (range: SelectionRange, draft: BibleDraft) => void;
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
  kinds,
  onAddToBible,
}: SelectionActionsProps) {
  const [placement, setPlacement] = useState<Placement | null>(null);
  const [adding, setAdding] = useState<Placement | null>(null);

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

  // The *Add to bible* form outlives the selection that opened it, at the position it opened at.
  if (adding) {
    return (
      <div
        className="selection-actions selection-actions-form"
        style={{ top: `${adding.top}px`, left: `${adding.left}px` }}
      >
        <AddToBibleForm
          kinds={kinds}
          busy={busy}
          onCancel={() => setAdding(null)}
          onSubmit={(draft) => {
            setAdding(null);
            onAddToBible(adding.range, draft);
          }}
        />
      </div>
    );
  }

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
        <>
          <button type="button" disabled={busy} onClick={() => onMark(placement.range)}>
            {busy ? 'Marking…' : 'Mark passage'}
          </button>
          {kinds.length > 0 && (
            <button type="button" disabled={busy} onClick={() => setAdding(placement)}>
              Add to bible
            </button>
          )}
        </>
      )}
    </div>
  );
}

interface AddToBibleFormProps {
  kinds: readonly KindDefinition[];
  busy: boolean;
  onSubmit: (draft: BibleDraft) => void;
  onCancel: () => void;
}

/**
 * A kind and a name, and nothing else.
 *
 * The name is not derived from the selected words. A passage that says "the woman at the rail"
 * is not a character called *the woman at the rail*, and a form that guessed would have the
 * writer correcting it every time — the selection becomes the entry's **citation**, which is the
 * part the server derives.
 */
function AddToBibleForm({ kinds, busy, onSubmit, onCancel }: AddToBibleFormProps) {
  const [kind, setKind] = useState(kinds[0]?.kind ?? '');
  const [name, setName] = useState('');

  return (
    <form
      className="add-to-bible"
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim() !== '' && kind !== '') {
          onSubmit({ kind, name: name.trim() });
        }
      }}
    >
      <label htmlFor="add-to-bible-kind">Kind</label>
      <select
        id="add-to-bible-kind"
        value={kind}
        disabled={busy}
        onChange={(event) => setKind(event.target.value)}
      >
        {kinds.map((definition) => (
          <option key={definition.kind} value={definition.kind}>
            {definition.label}
          </option>
        ))}
      </select>

      <label htmlFor="add-to-bible-name">Name</label>
      {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the writer just asked to type here */}
      <input
        id="add-to-bible-name"
        autoFocus
        type="text"
        value={name}
        disabled={busy}
        onChange={(event) => setName(event.target.value)}
      />

      <button type="submit" disabled={busy || name.trim() === ''}>
        {busy ? 'Adding…' : 'Add to bible'}
      </button>
      <button type="button" disabled={busy} onClick={onCancel}>
        Cancel
      </button>
    </form>
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
