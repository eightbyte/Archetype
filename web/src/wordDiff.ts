/**
 * A word-level diff, for the before/after a rewrite is accepted from (P4-14, D12).
 *
 * P4-14 calls this **desirable, not required** — the before/after is the requirement, and showing
 * two paragraphs side by side would have satisfied it. It is here because a proofread changes
 * four characters in two hundred words, and two paragraphs that differ in four characters are two
 * paragraphs a writer has to compare by eye before they can accept anything. Marking what moved
 * is what makes the acceptance a decision rather than a leap.
 *
 * ## What it is, exactly
 *
 * A longest-common-subsequence over **words**, where a word is a run of non-space characters and
 * the space that follows it. Nothing smarter: no character-level refinement inside a word, no
 * move detection, no similarity heuristics. Those are the parts of a diff that need tuning, and a
 * tuned diff with no corpus behind it is a thing that is wrong in ways nobody notices — the same
 * argument that keeps the anchor resolver on the server and out of the fake client.
 *
 * The table is O(*n*·*m*) in words. A rewrite is over an anchored passage, which is a paragraph
 * or a few — {@link MAX_DIFF_WORDS} is the point past which this gives up and reports the whole
 * thing as one replacement, because a diff nobody can read is not worth a full second of anyone's
 * afternoon.
 *
 * Pure. No React, no DOM.
 */

/** Past this many words on either side, the two texts are reported as one replacement. */
export const MAX_DIFF_WORDS = 1_200;

/** One run of the diff: text that stayed, text that went, or text that arrived. */
export interface DiffPart {
  type: 'same' | 'removed' | 'added';
  text: string;
}

/**
 * Split into words, each carrying the whitespace that follows it.
 *
 * Keeping the trailing space attached is what lets the parts be concatenated back into the
 * original text exactly — which is the property that makes the rendering trustworthy: what the
 * diff draws as "unchanged plus added" *is* the replacement, character for character.
 */
export function splitWords(text: string): string[] {
  return text.match(/\S+\s*|\s+/g) ?? [];
}

/**
 * The diff of two passages, as a flat list of runs in reading order.
 *
 * Adjacent runs of the same type are merged, so a sentence that was replaced wholesale reads as
 * one removal and one addition rather than as forty of each.
 */
export function wordDiff(before: string, after: string): DiffPart[] {
  if (before === after) {
    return before === '' ? [] : [{ type: 'same', text: before }];
  }

  const left = splitWords(before);
  const right = splitWords(after);

  if (left.length > MAX_DIFF_WORDS || right.length > MAX_DIFF_WORDS) {
    return merge([
      ...(before === '' ? [] : [{ type: 'removed' as const, text: before }]),
      ...(after === '' ? [] : [{ type: 'added' as const, text: after }]),
    ]);
  }

  // The classic LCS table, built bottom-up so the walk that reads it out runs forwards and the
  // parts come out in reading order without a reversal.
  const lengths: number[][] = Array.from({ length: left.length + 1 }, () =>
    new Array<number>(right.length + 1).fill(0),
  );
  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      lengths[i]![j]! =
        left[i] === right[j]
          ? lengths[i + 1]![j + 1]! + 1
          : Math.max(lengths[i + 1]![j]!, lengths[i]![j + 1]!);
    }
  }

  const parts: DiffPart[] = [];
  let i = 0;
  let j = 0;
  while (i < left.length && j < right.length) {
    if (left[i] === right[j]) {
      parts.push({ type: 'same', text: left[i]! });
      i += 1;
      j += 1;
    } else if (lengths[i + 1]![j]! >= lengths[i]![j + 1]!) {
      parts.push({ type: 'removed', text: left[i]! });
      i += 1;
    } else {
      parts.push({ type: 'added', text: right[j]! });
      j += 1;
    }
  }
  for (; i < left.length; i += 1) {
    parts.push({ type: 'removed', text: left[i]! });
  }
  for (; j < right.length; j += 1) {
    parts.push({ type: 'added', text: right[j]! });
  }

  return merge(parts);
}

/** True when the two passages are the same text — a proofread that found nothing to correct. */
export function isUnchanged(parts: readonly DiffPart[]): boolean {
  return parts.every((part) => part.type === 'same');
}

function merge(parts: readonly DiffPart[]): DiffPart[] {
  const merged: DiffPart[] = [];
  for (const part of parts) {
    const last = merged[merged.length - 1];
    if (last && last.type === part.type) {
      last.text += part.text;
    } else {
      merged.push({ ...part });
    }
  }
  return merged;
}
