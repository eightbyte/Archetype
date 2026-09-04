/**
 * P2-9 — the anchor decorations, tested against real ProseMirror and no React.
 *
 * This is where the mechanics of P2-9 live, so this is where they are held down: mapping a range
 * through a transaction, collapsing one whose text has gone, taking the server's answer, and
 * refusing to build a decoration out of bounds.
 *
 * Everything here is deliberately about *positions*, not about status. The plugin never decides
 * that an anchor is `stale` — that is the resolver's answer, arriving with a save (D21) — and a
 * test that made it look otherwise would be describing a client-side resolver that must not
 * exist (§ 2, ruling 2).
 */

import { getSchema } from '@tiptap/react';
import { EditorState } from '@tiptap/pm/state';
import type { Node as ProseMirrorNode } from '@tiptap/pm/model';
import { describe, expect, test } from 'vitest';
import type { Anchor } from '../api/types';
import type { EditorAnchor } from '../editor/anchors';
import {
  anchorPlugin,
  anchorsIn,
  isCollapsed,
  setAnchorsTransaction,
  toEditorAnchors,
} from '../editor/anchors';
import { EDITOR_EXTENSIONS } from '../editor/extensions';

const schema = getSchema(EDITOR_EXTENSIONS);

/** A document of plain paragraphs. */
function doc(...paragraphs: string[]): ProseMirrorNode {
  return schema.nodeFromJSON({
    type: 'doc',
    content: paragraphs.map((text) => ({
      type: 'paragraph',
      ...(text === '' ? {} : { content: [{ type: 'text', text }] }),
    })),
  });
}

function stateOf(node: ProseMirrorNode): EditorState {
  return EditorState.create({ doc: node, schema, plugins: [anchorPlugin()] });
}

/** Apply the plugin's own "here is the server's answer" transaction. */
function withAnchors(state: EditorState, anchors: EditorAnchor[]): EditorState {
  return state.apply(setAnchorsTransaction(state, anchors));
}

function anchor(from: number, to: number, quote: string): EditorAnchor {
  return { id: `anc_${from}_${to}`, from, to, quote, status: 'ok', label: '' };
}

/** The text a range covers, so a test can say *which words* an anchor ended up over. */
function covered(state: EditorState, one: EditorAnchor): string {
  return state.doc.textBetween(one.from, one.to, '\n');
}

/** The first paragraph is `The harbour was grey.`: positions 1..22, text at 1. */
const HARBOUR = 'The harbour was grey.';
const SECOND = 'He did not look back.';

describe('holding the server’s answer', () => {
  test('takes the anchors it is given, at the positions it is given', () => {
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const [held] = anchorsIn(state);
    expect(held).toBeDefined();
    expect(covered(state, held!)).toBe('harbour was');
  });

  test('a later answer replaces the set rather than adding to it', () => {
    let state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);
    state = withAnchors(state, [anchor(1, 4, 'The')]);

    expect(anchorsIn(state).map((held) => covered(state, held))).toEqual(['The']);
  });

  test('the wire shape maps straight onto it, and an unknown status reads as ok', () => {
    const wire: Anchor = {
      id: 'anc_1',
      project_id: 'prj_1',
      document_id: 'doc_1',
      from_pos: 5,
      to_pos: 16,
      quote: 'harbour was',
      prefix: '',
      suffix: '',
      // Wire schemas are extension-only, so a status from a later phase must not throw here.
      status: 'something-new',
      label: 'the ship',
      document_version: 2,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      checked_at: '2026-01-01T00:00:00Z',
      suggestion: null,
    };

    expect(toEditorAnchors([wire])).toEqual([
      { id: 'anc_1', from: 5, to: 16, quote: 'harbour was', status: 'ok', label: 'the ship' },
    ]);
  });
});

describe('following the text as it is edited (D21, display-only)', () => {
  test('typing above an anchor leaves it over the same words', () => {
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const typed = state.apply(state.tr.insertText('Later. ', 1));

    const [held] = anchorsIn(typed);
    expect(covered(typed, held!)).toBe('harbour was');
    expect(held!.from).toBe(12);
  });

  test('typing below an anchor does not move it at all', () => {
    const state = withAnchors(stateOf(doc(HARBOUR, SECOND)), [anchor(5, 16, 'harbour was')]);

    const typed = state.apply(state.tr.insertText('Nothing.', 24));

    expect(anchorsIn(typed)[0]).toMatchObject({ from: 5, to: 16 });
  });

  test('typing at the start of the range stays outside it, not inside', () => {
    // The bias is deliberate: text the writer types at the edge of a marked passage is not part
    // of what they marked, and the server will say so on the next save either way.
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const typed = state.apply(state.tr.insertText('big ', 5));

    expect(covered(typed, anchorsIn(typed)[0]!)).toBe('harbour was');
  });

  test('typing at the end of the range stays outside it too', () => {
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const typed = state.apply(state.tr.insertText(' still', 16));

    expect(covered(typed, anchorsIn(typed)[0]!)).toBe('harbour was');
  });

  test('typing inside the range grows it, because those words are inside what was marked', () => {
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const typed = state.apply(state.tr.insertText(' quay and', 12));

    expect(covered(typed, anchorsIn(typed)[0]!)).toBe('harbour quay and was');
  });

  test('deleting a paragraph above brings the anchor up with it', () => {
    const state = withAnchors(stateOf(doc(SECOND, HARBOUR)), [anchor(28, 39, 'harbour was')]);
    expect(covered(state, anchorsIn(state)[0]!)).toBe('harbour was');

    const cut = state.apply(state.tr.delete(0, 23));

    expect(covered(cut, anchorsIn(cut)[0]!)).toBe('harbour was');
  });

  test('a transaction that changes no text leaves the positions alone', () => {
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const same = state.apply(state.tr.setMeta('anything', true));

    expect(anchorsIn(same)).toEqual(anchorsIn(state));
  });
});

describe('an anchor that spans a block boundary (deviation B4)', () => {
  test('survives a bare paragraph split through it', () => {
    // A split with nothing written into the gap keeps the anchor — ruled by the writer on
    // 2026-08-30. So the decoration has to handle a range covering the end of one block and the
    // start of the next, which is why it is an inline decoration and not one span.
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const split = state.apply(state.tr.split(12));

    const [held] = anchorsIn(split);
    expect(held!.to).toBeGreaterThan(held!.from);
    // The split fell between "harbour" and " was", so the range now covers the end of one
    // paragraph and the start of the next — exactly the case B4 makes legal.
    expect(covered(split, held!)).toBe('harbour\n was');
    expect(split.doc.childCount).toBe(2);
  });
});

describe('a range whose text is deleted', () => {
  test('collapses, and says so rather than drawing nothing', () => {
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const cut = state.apply(state.tr.delete(5, 16));

    const [held] = anchorsIn(cut);
    expect(isCollapsed(held!)).toBe(true);
    expect(held!.from).toBe(held!.to);
  });

  test('and its status is untouched — a status is the server’s to give (§ 2, ruling 2)', () => {
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const cut = state.apply(state.tr.delete(5, 16));

    expect(anchorsIn(cut)[0]!.status).toBe('ok');
  });

  test('deleting the whole document collapses every anchor without throwing', () => {
    const state = withAnchors(stateOf(doc(HARBOUR, SECOND)), [
      anchor(5, 16, 'harbour was'),
      anchor(24, 30, 'He did'),
    ]);

    const cut = state.apply(state.tr.delete(0, state.doc.content.size));

    expect(anchorsIn(cut)).toHaveLength(2);
    expect(anchorsIn(cut).every(isCollapsed)).toBe(true);
  });
});

describe('a passage rewritten wholesale (plan section 8, step 12)', () => {
  // The case the whole Phase 2 corpus was blind to. Every other test here edits a character or
  // a word; the acceptance run replaced a marked passage with new sentences, and that is a
  // different shape. ProseMirror maps a range across a replacement onto the replacement, so the
  // anchor does NOT collapse - which is why no collapsed marker appeared during the run.
  test('typing over the marked passage keeps a range, over the words that replaced it', () => {
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(5, 16, 'harbour was')]);

    const rewritten = state.apply(
      state.tr.replaceWith(5, 16, state.schema.text('sky had turned')),
    );

    const [held] = anchorsIn(rewritten);
    expect(isCollapsed(held!)).toBe(false);
    expect(covered(rewritten, held!)).toBe('sky had turned');
  });

  // And on the reload afterwards: the server leaves a stale anchor's positions exactly where
  // they were (P2-7), so the range lands on whatever now occupies those offsets - here a
  // fragment that starts and ends mid-word. The plugin is right to draw it: a status is the
  // server's to give and the positions are the server's answer. What carries the meaning is the
  // `anchor-stale` class, and it is styled loudly for this reason (styles.css).
  test('the server answer lands the range on text the anchor never referred to', () => {
    const state = withAnchors(stateOf(doc('She counted the masts twice before the rain came.')), [
      { id: 'anc_1', from: 5, to: 16, quote: 'harbour was', status: 'stale', label: 'the ship' },
    ]);

    const [held] = anchorsIn(state);
    expect(isCollapsed(held!)).toBe(false);
    expect(covered(state, held!)).toBe('counted the');
    expect(held!.quote).toBe('harbour was');
    expect(held!.status).toBe('stale');
  });
});

describe('positions that are out of bounds', () => {
  test('are clamped rather than throwing and taking the editor down', () => {
    // The server leaves a `stale` anchor's positions where they were, deliberately (P2-7), and
    // the document may since have got shorter. A decoration built past the end throws, and the
    // one thing a layer over the manuscript must never do is take the manuscript with it.
    const state = withAnchors(stateOf(doc('Short.')), [anchor(500, 900, 'gone')]);

    const [held] = anchorsIn(state);
    expect(held!.from).toBeLessThanOrEqual(state.doc.content.size);
    expect(isCollapsed(held!)).toBe(true);
  });

  test('a reversed range is clamped to a collapsed one, not to a negative span', () => {
    const state = withAnchors(stateOf(doc(HARBOUR)), [anchor(16, 5, 'backwards')]);

    expect(isCollapsed(anchorsIn(state)[0]!)).toBe(true);
  });
});
