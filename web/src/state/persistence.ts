/**
 * Reading and writing the small amount of state that outlives a reload (P1-9, P1-12).
 *
 * Three things persist, and they are all conveniences rather than manuscript data: the pane
 * layout, which project was open, and which projects were opened recently. Nothing here is a
 * source of truth — the manuscript lives in the project file, and every value read back is
 * validated before it is believed, because `localStorage` is a string bucket that a previous
 * version of this app, a browser extension, or a person with the console open can write to.
 *
 * Every access is wrapped: a browser with storage disabled, a private window, or a quota that
 * is full must cost the writer a remembered pane width, not the workspace.
 */

/** The keys this app owns. Namespaced so a shared origin cannot collide with them. */
export const STORAGE_KEYS = {
  ui: 'archetype.ui',
  openProject: 'archetype.openProject',
  recentProjects: 'archetype.recentProjects',
} as const;

/** How many recently-opened projects the picker offers as a shortcut (P1-12). */
export const RECENT_PROJECT_LIMIT = 5;

/**
 * Read a stored value and hand it to `revive`, which decides whether it is usable.
 *
 * `revive` receives whatever was parsed — including `null`, a number, or an object of the wrong
 * shape — and returns `null` for anything it does not recognise. A stored value that is no
 * longer valid is simply forgotten; it is never repaired into something half-right.
 */
export function readStored<T>(key: string, revive: (raw: unknown) => T | null): T | null {
  const storage = storageOrNull();
  if (!storage) {
    return null;
  }
  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    return null;
  }
  if (raw === null) {
    return null;
  }
  try {
    return revive(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

/** Store a value as JSON. A storage that refuses the write is not an error worth surfacing. */
export function writeStored(key: string, value: unknown): void {
  const storage = storageOrNull();
  if (!storage) {
    return;
  }
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota, private mode, or a policy that forbids it. The app works without this.
  }
}

/** Forget a stored value. */
export function clearStored(key: string): void {
  const storage = storageOrNull();
  if (!storage) {
    return;
  }
  try {
    storage.removeItem(key);
  } catch {
    // As above.
  }
}

/** Read a string, or null if what is stored is not one. */
export function reviveString(raw: unknown): string | null {
  return typeof raw === 'string' && raw.length > 0 ? raw : null;
}

/** Read an array of strings, dropping anything in it that is not one. */
export function reviveStringArray(raw: unknown): string[] | null {
  if (!Array.isArray(raw)) {
    return null;
  }
  return raw.filter((item): item is string => typeof item === 'string' && item.length > 0);
}

/**
 * Put `id` at the front of `existing`, without duplicates, capped at
 * {@link RECENT_PROJECT_LIMIT}. Pure, so the ordering rule is testable on its own.
 */
export function withRecentProject(existing: readonly string[], id: string): string[] {
  return [id, ...existing.filter((item) => item !== id)].slice(0, RECENT_PROJECT_LIMIT);
}

/**
 * `localStorage`, or null where it cannot be reached.
 *
 * Accessing the property itself throws in some configurations, which is why this is a function
 * with a `try` around it rather than a module-level constant.
 */
function storageOrNull(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}
