/**
 * The display edge.
 *
 * Timestamps are UTC ISO-8601 everywhere — on the wire, in the database, in state — and are
 * turned into something a person reads only here. Keeping that in one module is what stops a
 * formatted string leaking back into a comparison or a request.
 *
 * `now` is a parameter rather than a call to `Date.now()` inside, so the rules are testable
 * without freezing the clock.
 */

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/**
 * How long ago `iso` was, in words: "just now", "6 minutes ago", "yesterday", or — once it is
 * far enough back that a relative answer stops being useful — the date itself.
 */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) {
    return 'at an unknown time';
  }

  const elapsed = now.getTime() - then;
  if (elapsed < 0) {
    // A clock that disagrees with the server's is not worth a paragraph of explanation.
    return 'just now';
  }
  if (elapsed < 45 * 1_000) {
    return 'just now';
  }
  if (elapsed < 90 * 1_000) {
    return 'a minute ago';
  }
  if (elapsed < HOUR_MS) {
    return plural(Math.round(elapsed / MINUTE_MS), 'minute') + ' ago';
  }
  if (elapsed < 90 * MINUTE_MS) {
    return 'an hour ago';
  }
  if (elapsed < DAY_MS) {
    return plural(Math.round(elapsed / HOUR_MS), 'hour') + ' ago';
  }
  if (elapsed < 2 * DAY_MS) {
    return 'yesterday';
  }
  if (elapsed < 7 * DAY_MS) {
    return plural(Math.floor(elapsed / DAY_MS), 'day') + ' ago';
  }
  return formatDate(iso);
}

/** The date alone, in the reader's locale. Empty for an unparseable timestamp. */
export function formatDate(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return '';
  }
  return parsed.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/** Date and time, for the `title` on a relative timestamp. Empty when unparseable. */
export function formatDateTime(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return '';
  }
  return parsed.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** `3 chapters`, `1 chapter`. */
export function plural(count: number, noun: string, pluralNoun = `${noun}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? noun : pluralNoun}`;
}
