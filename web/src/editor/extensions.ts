/**
 * The manuscript schema — a closed list (P1-10, D1).
 *
 * Paragraphs, headings 1–3, bold, italic, blockquote, bullet and ordered lists, a horizontal
 * rule that reads as a scene break, hard breaks, and undo/redo. Nothing else.
 *
 * The restraint is the point. Every node type is a case that anchors (Phase 2), chunking
 * (Phase 5), and Markdown export (Phase 9) must each handle correctly, and each of those is
 * harder than it looks. So the schema stays small until something earns its way in, and adding
 * to it is a spec change — the phase plan's closed list and {@link ALLOWED_NODES} below must be
 * edited together, and `schema.test.ts` fails if they disagree with what TipTap actually built.
 *
 * StarterKit brings more than this, so the surplus is switched off by name rather than left to
 * be noticed later: code, code blocks, and strikethrough. Dropcursor and gapcursor stay — they
 * are editing behaviour and contribute no node or mark.
 */

import StarterKit from '@tiptap/starter-kit';
import type { AnyExtension } from '@tiptap/react';

/** Heading levels the editor offers. The projection tolerates 1–6; the writer gets three. */
export const HEADING_LEVELS = [1, 2, 3] as const;

export type HeadingLevel = (typeof HEADING_LEVELS)[number];

/**
 * Every node type the schema may contain, sorted.
 *
 * `doc` and `text` are ProseMirror's own; the rest are the writer's. `hardBreak` is on the list
 * deliberately — verse, epigraphs, and an address block read as one block with line breaks, not
 * as a run of paragraphs, and the projection has always had a rule for it (P1-7).
 */
export const ALLOWED_NODES: readonly string[] = [
  'blockquote',
  'bulletList',
  'doc',
  'hardBreak',
  'heading',
  'horizontalRule',
  'listItem',
  'orderedList',
  'paragraph',
  'text',
];

/** Every mark the schema may carry, sorted. Emphasis only — no colour, no highlight, no code. */
export const ALLOWED_MARKS: readonly string[] = ['bold', 'italic'];

/**
 * The extension list the editor is built from.
 *
 * A module-level constant rather than a factory: TipTap rebuilds the editor when its extensions
 * change identity, and an editor rebuilt mid-sentence loses the undo history the writer is
 * relying on.
 */
export const EDITOR_EXTENSIONS: AnyExtension[] = [
  StarterKit.configure({
    heading: { levels: [...HEADING_LEVELS] },
    // Off by name. A manuscript is prose; these are the parts of StarterKit that are not.
    code: false,
    codeBlock: false,
    strike: false,
  }),
];
