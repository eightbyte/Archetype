/**
 * P1-9, P1-12 — what outlives a reload, and what happens when it cannot be trusted.
 *
 * `localStorage` is a string bucket that a previous version of this app, an extension, or a
 * person with the console open can write to. Every read has to survive that, and none of what is
 * stored here is worth failing over — so the tests are mostly about the bad cases.
 */

import { describe, expect, test, vi } from 'vitest';
import {
  clearStored,
  RECENT_PROJECT_LIMIT,
  readStored,
  reviveString,
  reviveStringArray,
  STORAGE_KEYS,
  withRecentProject,
  writeStored,
} from '../state/persistence';

describe('reading and writing', () => {
  test('a value round-trips', () => {
    writeStored('archetype.test', { a: 1 });
    expect(readStored('archetype.test', (raw) => raw)).toEqual({ a: 1 });
  });

  test('nothing stored is null, not a throw', () => {
    expect(readStored('archetype.absent', (raw) => raw)).toBeNull();
  });

  test('a value that is not JSON is forgotten rather than repaired', () => {
    localStorage.setItem('archetype.test', '{ not json');
    expect(readStored('archetype.test', (raw) => raw)).toBeNull();
  });

  test('a reviver that rejects the value gets null through', () => {
    writeStored('archetype.test', 42);
    expect(readStored('archetype.test', reviveString)).toBeNull();
  });

  test('clearing forgets it', () => {
    writeStored('archetype.test', 'x');
    clearStored('archetype.test');
    expect(readStored('archetype.test', reviveString)).toBeNull();
  });

  test('a storage that refuses the write costs a preference, not the app', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError');
    });
    try {
      expect(() => writeStored('archetype.test', { a: 1 })).not.toThrow();
    } finally {
      setItem.mockRestore();
    }
  });

  test('a storage that refuses the read is the same as an empty one', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('SecurityError');
    });
    try {
      expect(readStored('archetype.test', (raw) => raw)).toBeNull();
    } finally {
      getItem.mockRestore();
    }
  });

  test('the keys this app owns are namespaced', () => {
    for (const key of Object.values(STORAGE_KEYS)) {
      expect(key.startsWith('archetype.')).toBe(true);
    }
  });
});

describe('revivers', () => {
  test('a string is a string, and an empty one is not', () => {
    expect(reviveString('prj_1')).toBe('prj_1');
    expect(reviveString('')).toBeNull();
    expect(reviveString(7)).toBeNull();
    expect(reviveString(null)).toBeNull();
  });

  test('a list of ids drops whatever in it is not one', () => {
    expect(reviveStringArray(['a', 2, '', null, 'b'])).toEqual(['a', 'b']);
    expect(reviveStringArray('a')).toBeNull();
    expect(reviveStringArray({ 0: 'a' })).toBeNull();
  });
});

describe('the recent-projects list', () => {
  test('the newest goes to the front', () => {
    expect(withRecentProject(['b', 'c'], 'a')).toEqual(['a', 'b', 'c']);
  });

  test('reopening moves it to the front rather than duplicating it', () => {
    expect(withRecentProject(['a', 'b', 'c'], 'c')).toEqual(['c', 'a', 'b']);
  });

  test('it does not grow without bound', () => {
    let recent: string[] = [];
    for (let index = 0; index < RECENT_PROJECT_LIMIT + 5; index += 1) {
      recent = withRecentProject(recent, `prj_${index}`);
    }
    expect(recent).toHaveLength(RECENT_PROJECT_LIMIT);
    expect(recent[0]).toBe(`prj_${RECENT_PROJECT_LIMIT + 4}`);
  });

  test('it does not modify what it was given', () => {
    const existing = ['a', 'b'];
    withRecentProject(existing, 'c');
    expect(existing).toEqual(['a', 'b']);
  });
});
