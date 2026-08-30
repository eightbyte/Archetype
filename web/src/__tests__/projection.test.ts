/**
 * P1-7 — the client mirror of the text projection, against the shared cases (D18).
 *
 * The fixture file is the server's: `server/tests/fixtures/projection/cases.json`, read by
 * `server/tests/test_projection.py` as well. One set of cases, two implementations. A rule that
 * changes on one side and not the other fails here rather than confusing a writer's table of
 * contents.
 *
 * Read from disk rather than imported: the file lives outside `web/src`, and a JSON import would
 * pull a very large literal type through `tsc` for no benefit. See `./fixtures.ts` for how the
 * path is resolved.
 */

import { describe, expect, test } from 'vitest';
import type { Heading, ProseMirrorNode } from '../editor/projection';
import {
  BLOCK_SEPARATOR,
  SCENE_BREAK,
  countWords,
  emptyDocument,
  project,
} from '../editor/projection';
import { readServerFixture } from './fixtures';

interface ProjectionCase {
  name: string;
  doc: ProseMirrorNode;
  text_plain: string;
  headings: Heading[];
  word_count: number;
}

const cases: ProjectionCase[] = readServerFixture<{ cases: ProjectionCase[] }>(
  'projection/cases.json',
).cases;

describe('the shared projection cases', () => {
  test('the fixture file was found and is not empty', () => {
    expect(cases.length).toBeGreaterThan(10);
  });

  test.each(cases.map((one) => [one.name, one] as const))('%s', (_name, one) => {
    const projection = project(one.doc);

    expect(projection.text_plain).toBe(one.text_plain);
    expect(projection.headings).toEqual(one.headings);
    expect(projection.word_count).toBe(one.word_count);
  });

  test.each(cases.map((one) => [one.name, one] as const))(
    'a block never contains a blank line: %s',
    (_name, one) => {
      for (const block of project(one.doc).text_plain.split(BLOCK_SEPARATOR)) {
        expect(block).toBe(block.trim());
        expect(block).not.toContain('\n\n');
      }
    },
  );

  test.each(cases.map((one) => [one.name, one] as const))(
    'heading ordinals are dense and in document order: %s',
    (_name, one) => {
      const headings = project(one.doc).headings;
      expect(headings.map((heading) => heading.ordinal)).toEqual(headings.map((_, index) => index));
    },
  );
});

describe('the projection on its own', () => {
  test('an empty editor projects to nothing', () => {
    expect(project(emptyDocument())).toEqual({ text_plain: '', headings: [], word_count: 0 });
  });

  test('emptyDocument returns a fresh copy each time', () => {
    const first = emptyDocument();
    first.content?.push({ type: 'paragraph' });
    expect(emptyDocument().content).toHaveLength(1);
  });

  test('it does not throw on rubbish, because the outline panel must still render', () => {
    expect(project(null)).toEqual({ text_plain: '', headings: [], word_count: 0 });
    expect(project(undefined)).toEqual({ text_plain: '', headings: [], word_count: 0 });
    expect(project({ type: 'doc', content: [{ type: 'mystery' }] })).toEqual({
      text_plain: '',
      headings: [],
      word_count: 0,
    });
  });

  test('a scene break is visible in the text and costs no words', () => {
    const projection = project({
      type: 'doc',
      content: [
        { type: 'paragraph', content: [{ type: 'text', text: 'Before.' }] },
        { type: 'horizontalRule' },
        { type: 'paragraph', content: [{ type: 'text', text: 'After.' }] },
      ],
    });

    expect(projection.text_plain.split(BLOCK_SEPARATOR)).toContain(SCENE_BREAK);
    expect(projection.word_count).toBe(2);
  });
});

describe('countWords', () => {
  const expectations: ReadonlyArray<readonly [string, number]> = [
    ['', 0],
    ['   ', 0],
    ['word', 1],
    ['two words', 2],
    ["don't", 1],
    ['don’t', 1],
    ['well-known', 1],
    ['mother-in-law', 1],
    ['* * *', 0],
    ['--', 0],
    ['...', 0],
    ['—', 0],
    ['1984', 1],
    ['café naïve', 2],
    ['line\nline', 2],
    ['hyphen- ', 1],
  ];

  test.each(expectations)('%j is %i words', (text, expected) => {
    expect(countWords(text)).toBe(expected);
  });
});
