/**
 * P4-14 — the word diff behind the before/after.
 *
 * The property that matters and is asserted over every case here: **the parts concatenate back
 * to both texts.** Everything a diff draws as "unchanged plus removed" must be exactly the
 * before, and "unchanged plus added" exactly the after — because what the writer accepts is the
 * second of those, and a diff that drew a replacement it could not reconstruct would be showing
 * them one thing and applying another.
 */

import { describe, expect, test } from 'vitest';
import type { DiffPart } from '../wordDiff';
import { MAX_DIFF_WORDS, isUnchanged, splitWords, wordDiff } from '../wordDiff';

/** What the diff says the before was. */
function before(parts: readonly DiffPart[]): string {
  return parts
    .filter((part) => part.type !== 'added')
    .map((part) => part.text)
    .join('');
}

/** What the diff says the after is — and what accepting it puts into the manuscript. */
function after(parts: readonly DiffPart[]): string {
  return parts
    .filter((part) => part.type !== 'removed')
    .map((part) => part.text)
    .join('');
}

const CASES: [string, string, string][] = [
  ['identical', 'The harbour was calm.', 'The harbour was calm.'],
  ['one word corrected', 'The harbor was calm.', 'The harbour was calm.'],
  ['a word inserted', 'The harbour was calm.', 'The harbour was very calm.'],
  ['a word removed', 'The harbour was very calm.', 'The harbour was calm.'],
  ['rewritten wholesale', 'The harbour was calm.', 'Nothing moved on the water.'],
  ['emptied', 'The harbour was calm.', ''],
  ['from nothing', '', 'The harbour was calm.'],
  [
    'two paragraphs, one changed',
    'He did not look back.\n\nThe gulls were quiet.',
    'He did not look back.\n\nThe gulls were screaming.',
  ],
  ['punctuation only', 'She said "no".', 'She said “no”.'],
];

describe('the diff reconstructs both texts', () => {
  test.each(CASES)('%s', (_name, left, right) => {
    const parts = wordDiff(left, right);
    expect(before(parts)).toBe(left);
    expect(after(parts)).toBe(right);
  });
});

describe('what it marks', () => {
  test('a proofread of one word leaves everything else alone', () => {
    const parts = wordDiff('The harbor was calm.', 'The harbour was calm.');

    expect(parts.filter((part) => part.type === 'removed')).toEqual([
      { type: 'removed', text: 'harbor ' },
    ]);
    expect(parts.filter((part) => part.type === 'added')).toEqual([
      { type: 'added', text: 'harbour ' },
    ]);
  });

  test('identical texts are one unchanged run, and say so', () => {
    const parts = wordDiff('The harbour was calm.', 'The harbour was calm.');

    expect(parts).toEqual([{ type: 'same', text: 'The harbour was calm.' }]);
    expect(isUnchanged(parts)).toBe(true);
  });

  test('adjacent runs of one type are merged rather than reported word by word', () => {
    const parts = wordDiff('a b c d e', 'a x y z e');

    // Three runs, not seven: a sentence replaced wholesale reads as one removal and one addition.
    expect(parts.map((part) => part.type)).toEqual(['same', 'removed', 'added', 'same']);
  });

  test('two empty texts are no parts at all', () => {
    expect(wordDiff('', '')).toEqual([]);
  });
});

describe('the limit', () => {
  test('past it the two are reported as one replacement, and still reconstruct', () => {
    const left = Array.from({ length: MAX_DIFF_WORDS + 10 }, (_, index) => `w${index}`).join(' ');
    const right = `${left} and one more`;

    const parts = wordDiff(left, right);

    expect(parts.map((part) => part.type)).toEqual(['removed', 'added']);
    expect(before(parts)).toBe(left);
    expect(after(parts)).toBe(right);
  });
});

describe('splitting', () => {
  test('each word carries the whitespace that follows it', () => {
    // This is the property the reconstruction rests on: joining the pieces is the original text.
    const words = splitWords('The harbour\n\nwas calm. ');
    expect(words.join('')).toBe('The harbour\n\nwas calm. ');
  });
});
