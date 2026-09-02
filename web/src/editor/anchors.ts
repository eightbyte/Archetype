/**
 * Anchors in the editor: decorations that follow the text as it is typed around (P2-9, D21).
 *
 * A ProseMirror plugin holding the open chapter's anchors and drawing each as an inline
 * decoration. On every transaction the stored positions are pushed through `tr.mapping`, so a
 * highlight stays over its passage while the writer adds paragraphs above it, without a save and
 * without a round trip.
 *
 * ## This mapping is display-only, and that is the whole design (D21)
 *
 * The mapped positions are **never sent**. The server re-resolves every anchor of a document
 * from the document's own text inside the save's transaction, and its answer replaces whatever
 * was on screen. ProseMirror's mapping is exact when it exists — but it does not exist for an
 * import, a snapshot restore, a file changed behind the app's back, or a Phase 6 agent proposal,
 * and two resolution paths where the better one is usually absent is worse than one path that is
 * always the same. So this is liveness between saves, nothing more.
 *
 * ## Two things it has to survive
 *
 * **An anchor may span a block boundary.** A bare paragraph split through an anchored range
 * keeps the anchor (phase-2-plan § 7, deviation B4), so the range that comes back can cover the
 * end of one block and the start of the next. `Decoration.inline` handles that natively — it is
 * the reason the decoration is inline rather than one span per anchor.
 *
 * **A range can collapse.** Deleting all of an anchored passage maps `from` and `to` onto the
 * same position. An inline decoration over nothing draws nothing, so a collapsed anchor becomes
 * a widget instead: a visible mark saying the passage went, pending whatever the save answers.
 * It is not decided here — a `stale` status is the server's to give (§ 2, ruling 2).
 */

// `Extension` comes through `@tiptap/react` rather than `@tiptap/core`: react re-exports core,
// and core is not a declared dependency of this package. One fewer line in `package.json` that
// nothing chose (outline § 8).
import { Extension } from '@tiptap/react';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import type { EditorState, Transaction } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import type { Anchor, AnchorStatus } from '../api/types';
import { describeAnchor } from '../anchorText';

/** One anchor as the editor draws it: an id, a range in *this* document, and a status. */
export interface EditorAnchor {
  id: string;
  from: number;
  to: number;
  status: AnchorStatus;
  /** The words the anchor is over, for the decoration's accessible description. */
  quote: string;
  label: string;
}

/** The plugin's whole state: the anchors, and the decorations drawn from them. */
export interface AnchorPluginState {
  anchors: EditorAnchor[];
  decorations: DecorationSet;
}

/** Read the plugin's state out of an editor state. Exported for tests. */
export const anchorPluginKey = new PluginKey<AnchorPluginState>('archetypeAnchors');

/** The meta a transaction carries to replace the anchor set with the server's answer. */
const SET_ANCHORS = 'archetype:setAnchors';

/** Turn the wire shape into what the editor draws. Positions are taken as given. */
export function toEditorAnchors(anchors: readonly Anchor[]): EditorAnchor[] {
  return anchors.map((anchor) => ({
    id: anchor.id,
    from: anchor.from_pos,
    to: anchor.to_pos,
    status: statusOf(anchor.status),
    quote: anchor.quote,
    label: anchor.label,
  }));
}

/**
 * A transaction that replaces the editor's anchors with `anchors`.
 *
 * It changes no text, so it does not mark the document dirty and does not reach the save loop.
 */
export function setAnchorsTransaction(state: EditorState, anchors: EditorAnchor[]): Transaction {
  return state.tr.setMeta(SET_ANCHORS, anchors);
}

/** The anchors the editor currently holds, with their mapped positions. */
export function anchorsIn(state: EditorState): EditorAnchor[] {
  return anchorPluginKey.getState(state)?.anchors ?? [];
}

/** True when the anchored range has been edited away and is waiting on the server's answer. */
export function isCollapsed(anchor: EditorAnchor): boolean {
  return anchor.to <= anchor.from;
}

/**
 * The extension the editor is built with.
 *
 * It contributes no node and no mark, so the closed schema (D1) is untouched: `schema.test.ts`
 * compares node and mark names, and a decoration is neither.
 */
/**
 * The plugin itself, built separately from the extension that installs it.
 *
 * Separate so it can be driven by a test with nothing but an `EditorState` and a transaction —
 * mapping, collapsing, and clamping are the whole of P2-9's mechanics, and they deserve to be
 * tested without a browser between the test and the rule.
 */
export function anchorPlugin(): Plugin<AnchorPluginState> {
  return new Plugin<AnchorPluginState>({
    key: anchorPluginKey,
    state: {
      init: () => ({ anchors: [], decorations: DecorationSet.empty }),
      apply(tr, value, _old, newState) {
        const replacement = tr.getMeta(SET_ANCHORS) as EditorAnchor[] | undefined;
        if (replacement) {
          // The server's answer, in the coordinates of the document it answered about. It
          // arrives with the load or the save that produced it, so it is current.
          const anchors = clampAll(replacement, newState);
          return { anchors, decorations: decorationsFor(anchors, newState) };
        }
        if (!tr.docChanged) {
          return value;
        }
        // A range start belongs to what follows it and an end to what precedes it, so text
        // inserted at either edge falls outside the anchor rather than being swallowed.
        const anchors = clampAll(
          value.anchors.map((anchor) => ({
            ...anchor,
            from: tr.mapping.map(anchor.from, 1),
            to: tr.mapping.map(anchor.to, -1),
          })),
          newState,
        );
        return { anchors, decorations: decorationsFor(anchors, newState) };
      },
    },
    props: {
      decorations(state) {
        return anchorPluginKey.getState(state)?.decorations ?? DecorationSet.empty;
      },
    },
  });
}

export const AnchorDecorations = Extension.create({
  name: 'archetypeAnchors',

  addProseMirrorPlugins() {
    return [anchorPlugin()];
  },
});

function statusOf(status: string): AnchorStatus {
  return status === 'stale' || status === 'orphaned' ? status : 'ok';
}

/**
 * Keep every range inside the document.
 *
 * A stored position can be past the end of the text it is being drawn over — the server's answer
 * for a `stale` anchor is deliberately left where it was, and that document may since have got
 * shorter. A decoration built out of bounds throws and takes the editor down with it, which is
 * the one thing a panel over the manuscript must never do.
 */
function clampAll(anchors: EditorAnchor[], state: EditorState): EditorAnchor[] {
  const end = state.doc.content.size;
  return anchors.map((anchor) => {
    const from = Math.min(Math.max(anchor.from, 0), end);
    return { ...anchor, from, to: Math.min(Math.max(anchor.to, from), end) };
  });
}

function decorationsFor(anchors: readonly EditorAnchor[], state: EditorState): DecorationSet {
  const decorations = anchors.map((anchor) =>
    isCollapsed(anchor)
      ? Decoration.widget(anchor.from, () => collapsedMarker(anchor), {
          key: `anchor-collapsed-${anchor.id}`,
          side: 0,
        })
      : Decoration.inline(anchor.from, anchor.to, {
          class: `anchor-mark anchor-${anchor.status}`,
          'data-anchor-id': anchor.id,
        }),
  );
  return DecorationSet.create(state.doc, decorations);
}

/** What is drawn where an anchored passage used to be. Says so; decides nothing. */
function collapsedMarker(anchor: EditorAnchor): HTMLElement {
  const marker = document.createElement('span');
  marker.className = 'anchor-mark anchor-collapsed';
  marker.setAttribute('data-anchor-id', anchor.id);
  marker.setAttribute('role', 'img');
  marker.setAttribute(
    'aria-label',
    `The passage marked ${describeAnchor(anchor)} has been deleted here — waiting for the save`,
  );
  marker.textContent = '⚑';
  return marker;
}
