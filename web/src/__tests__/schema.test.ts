/**
 * The editor schema is a closed list, and stays one (P1-10, D1).
 *
 * These tests exist because the failure they catch is silent. StarterKit gains a node in a minor
 * release, or someone adds an extension to fix one thing, and suddenly anchors (Phase 2),
 * chunking (Phase 5), and Markdown export (Phase 9) each have a case they were never written
 * for — discovered, at best, in Phase 9. The declared list and the built schema are compared
 * here so that arrives as a red test in the commit that causes it.
 *
 * `getSchema` builds the schema from the extension list without an editor or a DOM, which is why
 * this file needs neither.
 *
 * From P2-13 the comparison runs against a **shared fixture** rather than only against the
 * declaration beside the extensions. `server/tests/fixtures/schema/closed_schema.json` states
 * the vocabulary once; this file holds the schema TipTap actually built to it, and
 * `server/tests/test_markdown.py` holds the Markdown serializer to the same file. So a node
 * added to the editor fails a test on both sides of the wire in the commit that adds it, which
 * is what the closed list is for — the serializer cannot invent syntax for a node it has never
 * heard of, and the failure that catches is otherwise silent until somebody exports a chapter.
 */

import { getSchema } from '@tiptap/react';
import { describe, expect, test } from 'vitest';
import { ALLOWED_MARKS, ALLOWED_NODES, EDITOR_EXTENSIONS, HEADING_LEVELS } from '../editor/extensions';
import { readServerFixture } from './fixtures';

/** The vocabulary both suites are held to. */
interface ClosedSchema {
  nodes: string[];
  marks: string[];
  attr_defaults: Record<string, Record<string, unknown>>;
  heading_levels: number[];
}

const declared = readServerFixture<ClosedSchema>('schema/closed_schema.json');

const schema = getSchema(EDITOR_EXTENSIONS);

describe('the manuscript schema', () => {
  test('contains exactly the declared nodes', () => {
    expect(Object.keys(schema.nodes).sort()).toEqual([...ALLOWED_NODES]);
  });

  test('contains exactly the declared marks', () => {
    expect(Object.keys(schema.marks).sort()).toEqual([...ALLOWED_MARKS]);
  });

  test('offers three heading levels and no more', () => {
    expect([...HEADING_LEVELS]).toEqual([1, 2, 3]);
  });

  test('is exactly the vocabulary the server was written against', () => {
    expect(Object.keys(schema.nodes).sort()).toEqual(declared.nodes);
    expect(Object.keys(schema.marks).sort()).toEqual(declared.marks);
    expect([...HEADING_LEVELS]).toEqual(declared.heading_levels);
  });

  test('emits the attributes the Markdown importer fills in, defaults included', () => {
    // ProseMirror's `toJSON` writes an `attrs` object whenever the node type declares one, so
    // an ordered list is always `{start, type}` and a heading is always `{level}`. The importer
    // builds nodes from this same table (P2-14); if it drifted, an imported chapter would
    // render correctly and compare unequal, and the round-trip corpus would be asserting
    // against a document the editor never produces.
    const document = schema.nodeFromJSON({
      type: 'doc',
      content: [
        { type: 'heading', content: [{ type: 'text', text: 'One' }] },
        {
          type: 'orderedList',
          content: [
            {
              type: 'listItem',
              content: [{ type: 'paragraph', content: [{ type: 'text', text: 'a' }] }],
            },
          ],
        },
      ],
    });

    const json = document.toJSON() as { content: { type: string; attrs?: unknown }[] };
    for (const node of json.content) {
      expect(node.attrs).toEqual(declared.attr_defaults[node.type]);
    }
    for (const type of Object.keys(schema.nodes)) {
      const declaredAttrs = declared.attr_defaults[type];
      const built = Object.keys(schema.nodes[type]!.spec.attrs ?? {}).sort();
      expect(built).toEqual(declaredAttrs ? Object.keys(declaredAttrs).sort() : []);
    }
  });

  test.each(['code', 'codeBlock', 'strike', 'image', 'table', 'link', 'taskList'])(
    'has no %s',
    (name) => {
      expect(schema.nodes[name]).toBeUndefined();
      expect(schema.marks[name]).toBeUndefined();
    },
  );

  test('a horizontal rule is in the schema, because a scene break is a real boundary', () => {
    // The projection renders it as `* * *` and counts it as zero words (P1-7).
    expect(schema.nodes['horizontalRule']).toBeDefined();
  });

  test('the whole formatting set survives a round trip through the schema', () => {
    // Every node and mark the toolbar can produce, in one document. If the schema drops one, the
    // parsed document will not equal what went in.
    const document = {
      type: 'doc',
      content: [
        { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'One' }] },
        { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: 'Two' }] },
        { type: 'heading', attrs: { level: 3 }, content: [{ type: 'text', text: 'Three' }] },
        {
          type: 'paragraph',
          content: [
            { type: 'text', marks: [{ type: 'bold' }], text: 'bold' },
            { type: 'text', text: ' and ' },
            { type: 'text', marks: [{ type: 'italic' }], text: 'italic' },
            { type: 'hardBreak' },
            { type: 'text', text: 'after a break' },
          ],
        },
        {
          type: 'blockquote',
          content: [{ type: 'paragraph', content: [{ type: 'text', text: 'quoted' }] }],
        },
        {
          type: 'bulletList',
          content: [
            {
              type: 'listItem',
              content: [{ type: 'paragraph', content: [{ type: 'text', text: 'first' }] }],
            },
          ],
        },
        {
          type: 'orderedList',
          attrs: { start: 1 },
          content: [
            {
              type: 'listItem',
              content: [{ type: 'paragraph', content: [{ type: 'text', text: 'one' }] }],
            },
          ],
        },
        { type: 'horizontalRule' },
        { type: 'paragraph', content: [{ type: 'text', text: 'after the break' }] },
      ],
    };

    const parsed = schema.nodeFromJSON(document);

    expect(parsed.textContent).toContain('bold');
    expect(parsed.childCount).toBe(document.content.length);
    expect(parsed.child(3).firstChild?.marks.map((mark) => mark.type.name)).toEqual(['bold']);
  });
});
