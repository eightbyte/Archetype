/**
 * The display edge (P1-12).
 *
 * `now` is a parameter, so these are ordinary tests rather than clock surgery. Only the relative
 * branches are pinned down exactly: the absolute date goes through the reader's locale, and a
 * test that asserted a particular rendering of it would be asserting the test machine's
 * settings.
 */

import { describe, expect, test } from 'vitest';
import { formatDate, formatDateTime, formatRelativeTime, plural } from '../format';

const NOW = new Date('2026-08-30T12:00:00Z');

function ago(milliseconds: number): string {
  return new Date(NOW.getTime() - milliseconds).toISOString();
}

const SECOND = 1_000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe('relative time', () => {
  test.each([
    ['a moment', 5 * SECOND, 'just now'],
    ['just under a minute', 50 * SECOND, 'a minute ago'],
    ['six minutes', 6 * MINUTE, '6 minutes ago'],
    ['an hour', 65 * MINUTE, 'an hour ago'],
    ['five hours', 5 * HOUR, '5 hours ago'],
    ['yesterday', 30 * HOUR, 'yesterday'],
    ['three days', 3 * DAY, '3 days ago'],
  ])('%s reads as "%s"', (_name, elapsed, expected) => {
    expect(formatRelativeTime(ago(elapsed), NOW)).toBe(expected);
  });

  test('once it is far enough back, the date is more use than the interval', () => {
    const answer = formatRelativeTime(ago(40 * DAY), NOW);
    expect(answer).not.toContain('ago');
    expect(answer).toContain('2026');
  });

  test('a clock ahead of the server does not produce a negative interval', () => {
    expect(formatRelativeTime('2026-08-30T12:00:30Z', NOW)).toBe('just now');
  });

  test('a timestamp that cannot be read says so instead of printing NaN', () => {
    expect(formatRelativeTime('not a timestamp', NOW)).toBe('at an unknown time');
  });

  test('the server ISO-8601 form parses', () => {
    // The exact shape `utc_now` produces server-side.
    expect(formatRelativeTime('2026-08-30T11:59:30Z', NOW)).toBe('just now');
  });
});

describe('absolute forms', () => {
  test('a date is rendered, and an unreadable one is empty rather than "Invalid Date"', () => {
    expect(formatDate('2026-08-30T12:00:00Z')).toContain('2026');
    expect(formatDate('nonsense')).toBe('');
  });

  test('a date-time carries the time as well', () => {
    expect(formatDateTime('2026-08-30T12:00:00Z')).toMatch(/\d{1,2}:\d{2}/);
    expect(formatDateTime('nonsense')).toBe('');
  });
});

describe('counting things', () => {
  test.each([
    [0, '0 chapters'],
    [1, '1 chapter'],
    [2, '2 chapters'],
  ])('%d reads as "%s"', (count, expected) => {
    expect(plural(count, 'chapter')).toBe(expected);
  });

  test('large numbers are grouped so they can be read at a glance', () => {
    expect(plural(12_500, 'word')).toBe('12,500 words');
  });

  test('an irregular plural can be given', () => {
    expect(plural(2, 'entry', 'entries')).toBe('2 entries');
  });
});
