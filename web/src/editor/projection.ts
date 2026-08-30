/**
 * The client mirror of the text projection (P1-7, D18).
 *
 * The server owns the authoritative projection and derives it on every save. This exists so the
 * table of contents stays live *between* saves, on the one document that is open (D2) — and it
 * reconciles to the server's answer whenever a save returns.
 *
 * It must agree with `server/archetype/manuscript/projection.py` on every rule. Both are driven
 * by the same fixture set — `server/tests/fixtures/projection/cases.json` — so drift shows up as
 * a test failure rather than as a table of contents that disagrees with the manuscript. The
 * rules themselves are written down once, in that Python module's docstring; read them there.
 *
 * One deliberate difference: the server *validates* before projecting, because it is about to
 * store what it was given. This one does not. It projects whatever the editor hands it, because
 * throwing here would blank the outline panel over a node type nobody has taught it yet.
 *
 * Field names are snake_case to match the wire, not because TypeScript wants them that way.
 * The point of a mirror is that its output can be compared to the server's without a
 * translation step in between, and a translation step is one more place to drift.
 */

/** What separates two blocks in `text_plain`. Exactly one blank line, always. */
export const BLOCK_SEPARATOR = '\n\n';

/** How a `horizontalRule` reads in `text_plain`. */
export const SCENE_BREAK = '* * *';

const TEXT_BLOCK_TYPES = new Set(['paragraph', 'heading']);
const SCENE_BREAK_TYPES = new Set(['horizontalRule']);
const LINE_BREAK_TYPES = new Set(['hardBreak']);

const MIN_HEADING_LEVEL = 1;
const MAX_HEADING_LEVEL = 6;

/**
 * Unicode letters and digits, optionally joined by an apostrophe (straight or curly) or a dash.
 *
 * `\p{L}` and `\p{N}` rather than `\w`: JavaScript's `\w` is ASCII-only even under the `u` flag,
 * so it would count "naïve" as two words where Python counts one, and the two projections would
 * disagree on word count for any manuscript with an accent in it.
 */
const WORD_PATTERN = /[\p{L}\p{N}]+(?:['\u2019\u2010-\u2015-][\p{L}\p{N}]+)*/gu;

/** One mark on an inline node. The projection drops marks; the type exists so the editor
 * and the wire agree about what it is dropping. */
export type ProseMirrorMark = {
  type: string;
  attrs?: Record<string, unknown>;
};

/**
 * A node in a ProseMirror/TipTap document.
 *
 * Written as a type alias rather than an interface deliberately: an alias carries an implicit
 * index signature, which is what lets these values be handed to TipTap's `JSONContent` without a
 * cast. The two describe the same JSON, and a cast at that boundary would be a place where they
 * could quietly stop describing the same JSON.
 */
export type ProseMirrorNode = {
  type: string;
  attrs?: Record<string, unknown>;
  content?: ProseMirrorNode[];
  marks?: ProseMirrorMark[];
  text?: string;
};

/** A whole document. */
export type ProseMirrorDocument = {
  type: 'doc';
  attrs?: Record<string, unknown>;
  content?: ProseMirrorNode[];
};

/** One heading, addressed by its position among the document's headings. */
export interface Heading {
  level: number;
  text: string;
  /** Index among *all* heading nodes in the document, from zero. Jump-to-heading uses it. */
  ordinal: number;
}

/** Everything derived from a document's content. */
export interface Projection {
  text_plain: string;
  headings: Heading[];
  word_count: number;
}

/** The document TipTap produces for an empty editor. A fresh copy each call. */
export function emptyDocument(): ProseMirrorDocument {
  return { type: 'doc', content: [{ type: 'paragraph' }] };
}

/** The number of words in `text`. The one word-count definition on this side. */
export function countWords(text: string): number {
  return text.match(WORD_PATTERN)?.length ?? 0;
}

/** Derive `text_plain`, the heading list, and the word count from a document. */
export function project(document: ProseMirrorNode | null | undefined): Projection {
  const blocks: string[] = [];
  const headings: Heading[] = [];

  for (const node of childrenOf(document)) {
    walk(node, blocks, headings);
  }

  const textPlain = blocks.join(BLOCK_SEPARATOR);
  return { text_plain: textPlain, headings, word_count: countWords(textPlain) };
}

function childrenOf(node: ProseMirrorNode | null | undefined): ProseMirrorNode[] {
  return Array.isArray(node?.content) ? node.content : [];
}

function walk(node: ProseMirrorNode, blocks: string[], headings: Heading[]): void {
  if (TEXT_BLOCK_TYPES.has(node.type)) {
    const text = inlineText(node);
    if (node.type === 'heading') {
      headings.push({ level: headingLevel(node), text, ordinal: headings.length });
    }
    if (text) {
      blocks.push(text);
    }
    return;
  }

  if (SCENE_BREAK_TYPES.has(node.type)) {
    blocks.push(SCENE_BREAK);
    return;
  }

  for (const child of childrenOf(node)) {
    walk(child, blocks, headings);
  }
}

/** The text of one block: marks dropped, hard breaks kept, blank lines dropped. */
function inlineText(node: ProseMirrorNode): string {
  return tidy(inlineParts(node));
}

function inlineParts(node: ProseMirrorNode): string {
  let text = '';
  for (const child of childrenOf(node)) {
    if (child.type === 'text') {
      if (typeof child.text === 'string') {
        text += child.text;
      }
    } else if (LINE_BREAK_TYPES.has(child.type)) {
      text += '\n';
    } else {
      // An inline node this module does not know contributes whatever text it wraps.
      text += inlineParts(child);
    }
  }
  return text;
}

/** Trim each line and drop the empty ones — a block may not contain a blank line. */
function tidy(text: string): string {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .join('\n');
}

/** The heading's level, clamped to 1–6. A missing or unusable level reads as 1. */
function headingLevel(node: ProseMirrorNode): number {
  const level = node.attrs?.['level'];
  if (typeof level !== 'number' || !Number.isInteger(level)) {
    return MIN_HEADING_LEVEL;
  }
  return Math.max(MIN_HEADING_LEVEL, Math.min(MAX_HEADING_LEVEL, level));
}
