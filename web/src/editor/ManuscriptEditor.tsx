/**
 * The writing surface (P1-10, P2-9).
 *
 * TipTap over the closed schema in `extensions.ts`. The component owns the editor instance and
 * nothing else: what a change *means* — dirty, saving, saved, refused — belongs to
 * `DocumentContext`, and this only reports that one happened.
 *
 * Three things here are easy to get subtly wrong, so they are spelled out:
 *
 * * **The editor is built once.** TipTap rebuilds when the options passed to `useEditor` change
 *   identity, and a rebuild discards the undo history. So the callbacks are read through a ref
 *   and the dependency list stays empty.
 * * **Re-seeding is keyed on the load, not on the content.** `seedKey` changes when a different
 *   chapter is opened *or* the same one is reloaded after a conflict (D19). Watching `content`
 *   instead would push the writer's own keystrokes back into the editor.
 * * **`setContent` is told not to emit an update.** Seeding is not an edit, and treating it as
 *   one would mark a freshly opened chapter dirty and save it straight back.
 *
 * Nothing here destroys the editor. `useEditor` owns that, and it deliberately waits a tick
 * before doing it so that a `StrictMode` mount-unmount-remount keeps the same instance — which is
 * exactly what `main.tsx` does. Destroying it from an unmount effect would tear down the editor
 * that manager is about to reuse.
 *
 * ## Anchors (P2-9, D21)
 *
 * The anchors handed in are the server's answer, in the server's coordinates. They are pushed
 * into the plugin whenever that answer changes — a load, a save that moved one, a repair — and
 * between those the plugin maps them through each transaction so a highlight follows the words.
 * That mapping is display-only and never leaves the browser: the ranges this component sends are
 * only ever the writer's own selection.
 *
 * ## Applying a replacement (P4-14, D33)
 *
 * An accepted rewrite arrives the way a heading jump does — as pending state this component
 * clears once it has acted — and it is applied as **one** ProseMirror transaction. That is the
 * whole of D33: the result is undoable with one press, it marks the document dirty exactly once,
 * and the autosave that already runs is what writes it. There is no second save path and no
 * durable proposal record; Phase 7 owns those.
 */

import { EditorContent, useEditor } from '@tiptap/react';
import type { Editor } from '@tiptap/react';
import { useEffect, useMemo, useRef } from 'react';
import type { ProseMirrorDocument } from './projection';
import type { PendingReplacement } from '../state/documentReducer';
import type { EditorAnchor } from './anchors';
import { setAnchorsTransaction } from './anchors';
import { EDITOR_EXTENSIONS } from './extensions';
import { EditorToolbar } from './EditorToolbar';
import { SelectionActions } from './SelectionActions';
import type { BibleDraft, SelectionRange } from './SelectionActions';
import type { KindDefinition } from '../api/types';

export interface ManuscriptEditorProps {
  /** The document to seed. Only read when `seedKey` changes. */
  content: ProseMirrorDocument;
  /** Identity of *this load* of *this document*. */
  seedKey: string;
  /** The chapter title, used to name the writing surface for a screen reader. */
  title: string;
  onChange: (content: ProseMirrorDocument) => void;
  onBlur: () => void;
  /** A heading ordinal to scroll to, or null. Cleared through `onHeadingReached` (P1-11). */
  pendingHeading: number | null;
  onHeadingReached: () => void;
  /** The open chapter's anchors, as the server last answered (P2-9). */
  anchors: readonly EditorAnchor[];
  /** An anchor to scroll to, or null. Cleared through `onAnchorReached` (P2-10). */
  pendingAnchor: string | null;
  onAnchorReached: () => void;
  /** Anchor the selection. */
  onMark: (range: SelectionRange) => void;
  /** The anchor being re-linked by hand, or null (P2-10). */
  relinking: { anchorId: string; description: string } | null;
  onRelink: (range: SelectionRange) => void;
  onCancelRelink: () => void;
  /** True while an anchor request is in the air. */
  anchorBusy: boolean;
  /** The kinds an entry may be, from the served definition (P3-14, D26). */
  bibleKinds: readonly KindDefinition[];
  /** Anchor the selection *and* make an entry out of it, in one act. */
  onAddToBible: (range: SelectionRange, draft: BibleDraft) => void;
  /** Hand the selection to the assistant panel as the context for a question (P4-13). */
  onAskAgent: (range: SelectionRange) => void;
  /** A replacement to apply as one transaction, or null (P4-14). */
  pendingReplacement: PendingReplacement | null;
  /** It has been applied; clear the request. */
  onReplacementApplied: () => void;
}

export function ManuscriptEditor({
  content,
  seedKey,
  title,
  onChange,
  onBlur,
  pendingHeading,
  onHeadingReached,
  anchors,
  pendingAnchor,
  onAnchorReached,
  onMark,
  relinking,
  onRelink,
  onCancelRelink,
  anchorBusy,
  bibleKinds,
  onAddToBible,
  onAskAgent,
  pendingReplacement,
  onReplacementApplied,
}: ManuscriptEditorProps) {
  const callbacks = useRef({ onChange, onBlur });
  callbacks.current = { onChange, onBlur };

  const seeded = useRef<ProseMirrorDocument>(content);
  seeded.current = content;

  const editor = useEditor({
    extensions: EDITOR_EXTENSIONS,
    content,
    editorProps: {
      attributes: {
        class: 'manuscript',
        role: 'textbox',
        'aria-multiline': 'true',
      },
    },
    onUpdate: ({ editor: instance }) => {
      callbacks.current.onChange(instance.getJSON() as ProseMirrorDocument);
    },
    onBlur: () => {
      callbacks.current.onBlur();
    },
  });

  // Re-seed on a new load of a document. `false` keeps it from counting as an edit.
  const lastSeed = useRef<string | null>(null);
  useEffect(() => {
    if (!editor || lastSeed.current === seedKey) {
      return;
    }
    lastSeed.current = seedKey;
    editor.commands.setContent(seeded.current, false);
  }, [editor, seedKey]);

  // Push the server's answer into the plugin. Keyed on what the answer *is* rather than on the
  // array's identity: the anchors come out of the project state, which is rebuilt on every save,
  // and a transaction per keystroke would undo the mapping this exists to keep.
  const signature = useMemo(() => anchorSignature(anchors), [anchors]);
  useEffect(() => {
    if (!editor) {
      return;
    }
    editor.view.dispatch(setAnchorsTransaction(editor.state, [...anchors]));
    // `anchors` is deliberately absent: `signature` is what says the answer changed, and
    // `seedKey` re-applies it after a load has replaced the document under the decorations.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, signature, seedKey]);

  // Jump to a heading by ordinal — the index among all headings in the document, which is what
  // the projection numbers them by (P1-7). Anchors do not replace this and never will: a heading
  // is a structural position the projection already numbers, and minting an anchor row per
  // heading on every save would buy an answer that is already free (phase-2-plan § 2, ruling 1).
  useEffect(() => {
    if (!editor || pendingHeading === null) {
      return;
    }
    scrollToHeading(editor, pendingHeading);
    onHeadingReached();
  }, [editor, pendingHeading, onHeadingReached, seedKey]);

  // Jump to an anchor. Unlike a heading this waits for the decoration to exist — the anchors
  // arrive one request after the document does, so on a cross-chapter jump the mark is not
  // drawn yet on the first pass. Left pending until it is found, and cleared by the open.
  useEffect(() => {
    if (!editor || pendingAnchor === null) {
      return;
    }
    if (scrollToAnchor(editor, pendingAnchor)) {
      onAnchorReached();
    }
  }, [editor, pendingAnchor, onAnchorReached, signature, seedKey]);

  // Apply an accepted rewrite. One transaction, and the `onUpdate` it fires is what marks the
  // document dirty — so the ordinary autosave writes it and the ordinary undo takes it back.
  useEffect(() => {
    if (!editor || pendingReplacement === null) {
      return;
    }
    applyReplacement(editor, pendingReplacement);
    onReplacementApplied();
  }, [editor, pendingReplacement, onReplacementApplied]);

  return (
    <div className="editor">
      <EditorToolbar editor={editor} />
      <div className="editor-scroll">
        <EditorContent editor={editor} aria-label={`${title} — manuscript`} />
        <SelectionActions
          editor={editor}
          onMark={onMark}
          relinking={relinking}
          onRelink={onRelink}
          onCancelRelink={onCancelRelink}
          busy={anchorBusy}
          kinds={bibleKinds}
          onAddToBible={onAddToBible}
          onAskAgent={onAskAgent}
        />
      </div>
    </div>
  );
}

/**
 * What makes one answer about anchors different from another.
 *
 * Positions are part of it, and have to be: a re-link moves an `ok` anchor to a new range
 * without changing its status, and a signature that ignored the range would leave the highlight
 * on the passage the writer just replaced. Between saves the answer does not change, so the
 * mapping this exists to preserve is never disturbed by a keystroke.
 */
function anchorSignature(anchors: readonly EditorAnchor[]): string {
  return anchors
    .map((anchor) => `${anchor.id}:${anchor.status}:${anchor.from}:${anchor.to}`)
    .join('|');
}

/**
 * Replace a range with new text, as exactly one transaction (P4-14, D33).
 *
 * Two shapes, and the difference is what the answer actually contains:
 *
 * * **no blank line in it** — a text node straight into the range, so replacing part of a
 *   sentence stays part of that paragraph rather than splitting it into two;
 * * **blank lines in it** — one paragraph per block, because a model asked to rewrite a passage
 *   that spanned paragraphs will answer with paragraphs, and putting those newlines into a single
 *   text node would produce one long paragraph the writer then has to break up by hand.
 *
 * The range is clamped into the document first, for the reason a decoration is: these positions
 * are an anchor's, the server leaves a `stale` anchor's positions where they were, and a
 * transaction built out of bounds throws and takes the writing surface with it. An action never
 * applies to a `stale` anchor — that is refused before it reaches here — but the clamp is the
 * cheap guard that keeps a mistake from being a crash.
 */
export function applyReplacement(editor: Editor, replacement: PendingReplacement): void {
  const end = editor.state.doc.content.size;
  const from = Math.min(Math.max(replacement.from, 0), end);
  const to = Math.min(Math.max(replacement.to, from), end);
  const text = replacement.text;

  const paragraphs = text.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
  if (paragraphs.length > 1) {
    editor
      .chain()
      .focus()
      .insertContentAt(
        { from, to },
        paragraphs.map((block) => ({
          type: 'paragraph',
          content: [{ type: 'text', text: block }],
        })),
      )
      .run();
    return;
  }

  const single = text.trim();
  const transaction =
    single === ''
      ? editor.state.tr.delete(from, to)
      : editor.state.tr.replaceWith(from, to, editor.schema.text(single));
  editor.view.dispatch(transaction);
}

/**
 * Scroll the `ordinal`-th heading of the open document into view.
 *
 * Reads the rendered DOM rather than the document model: every heading level the schema allows
 * renders as an `h1`–`h3` in order, so their document order and their DOM order are the same
 * thing. `scrollIntoView` is guarded because jsdom does not implement it.
 */
export function scrollToHeading(editor: Editor, ordinal: number): void {
  const headings = editor.view.dom.querySelectorAll<HTMLElement>('h1, h2, h3');
  const target = headings.item(ordinal);
  if (!target) {
    return;
  }
  reveal(target);
}

/**
 * Scroll an anchor's decoration into view and select it, answering whether it was there.
 *
 * Selecting as well as scrolling is the point: the writer clicked a passage in a list and
 * expects to arrive *at* it, ready to work on it — and a selection is also what the re-link
 * control reads, so arriving at a stale anchor leaves the repair one click away.
 */
export function scrollToAnchor(editor: Editor, anchorId: string): boolean {
  const target = editor.view.dom.querySelector<HTMLElement>(`[data-anchor-id="${anchorId}"]`);
  if (!target) {
    return false;
  }
  reveal(target);
  return true;
}

function reveal(target: HTMLElement): void {
  if (typeof target.scrollIntoView === 'function') {
    target.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
}
