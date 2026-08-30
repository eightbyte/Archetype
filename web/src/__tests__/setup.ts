/**
 * Vitest setup (P1-1, extended in P1-9 → P1-13).
 *
 * Unmounts React trees between tests so a component's effects cannot leak into the next one, and
 * clears the storage the workspace persists its layout to, so a test that resizes a pane does
 * not decide what the next test starts with.
 *
 * The rest is the small set of DOM methods jsdom does not implement but ProseMirror expects.
 * They are *stubs*, not implementations: jsdom has no layout engine, so anything that depends on
 * a real measurement cannot be tested here and is not. What they buy is the ability to mount a
 * real TipTap editor and drive real commands against it, which is worth considerably more than
 * testing a mock of one.
 */

import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(() => {
  cleanup();
  localStorage.clear();
});

// ProseMirror scrolls the selection into view after most transactions, and jump-to-heading calls
// this directly (P1-11). jsdom has no such method at all.
if (typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = vi.fn();
}

// ProseMirror measures the DOM to place the cursor. jsdom returns a zero rect from
// `getBoundingClientRect`, but omits these two from `Range` entirely.
if (typeof Range.prototype.getBoundingClientRect !== 'function') {
  Range.prototype.getBoundingClientRect = () => new DOMRect();
}
if (typeof Range.prototype.getClientRects !== 'function') {
  Range.prototype.getClientRects = () =>
    Object.assign([] as unknown as DOMRectList, { item: () => null });
}

// Used by ProseMirror's drop and gap cursors.
if (typeof document.elementFromPoint !== 'function') {
  document.elementFromPoint = () => null;
}
