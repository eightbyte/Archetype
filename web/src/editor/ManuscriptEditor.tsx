/**
 * The writing surface (P1-10).
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
 */

import { EditorContent, useEditor } from '@tiptap/react';
import type { Editor } from '@tiptap/react';
import { useEffect, useRef } from 'react';
import type { ProseMirrorDocument } from './projection';
import { EDITOR_EXTENSIONS } from './extensions';
import { EditorToolbar } from './EditorToolbar';

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
}

export function ManuscriptEditor({
  content,
  seedKey,
  title,
  onChange,
  onBlur,
  pendingHeading,
  onHeadingReached,
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

  // Jump to a heading by ordinal — the index among all headings in the document, which is what
  // the projection numbers them by (P1-7). Anchors do not exist until Phase 2; this is the seam
  // they replace.
  useEffect(() => {
    if (!editor || pendingHeading === null) {
      return;
    }
    scrollToHeading(editor, pendingHeading);
    onHeadingReached();
  }, [editor, pendingHeading, onHeadingReached, seedKey]);

  return (
    <div className="editor">
      <EditorToolbar editor={editor} />
      <div className="editor-scroll">
        <EditorContent editor={editor} aria-label={`${title} — manuscript`} />
      </div>
    </div>
  );
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
  if (typeof target.scrollIntoView === 'function') {
    target.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
}
