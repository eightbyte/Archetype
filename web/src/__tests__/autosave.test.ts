/**
 * P1-10 — when a save happens.
 *
 * Fake timers, a `perform` that records what it was asked to do, and no React. The properties
 * being pinned down are the ones that decide whether a writer loses a keystroke: that a flush
 * can be awaited, that two saves are never in the air at once, that a failure retries with
 * backoff, and that a conflict stops the loop instead of retrying into an overwrite.
 */

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { AUTOSAVE_DELAY_MS, SaveScheduler } from '../editor/autosave';
import type { SaveOutcome } from '../editor/autosave';

const RETRIES = [10, 20, 40] as const;

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

/** A `perform` whose answers are scripted, with the calls it received recorded. */
function scripted(...outcomes: SaveOutcome[]) {
  const calls: number[] = [];
  let index = 0;
  const perform = vi.fn(async (): Promise<SaveOutcome> => {
    calls.push(index);
    const outcome = outcomes[index] ?? outcomes[outcomes.length - 1] ?? 'saved';
    index += 1;
    return outcome;
  });
  return { perform, calls };
}

function build(perform: () => Promise<SaveOutcome>): SaveScheduler {
  return new SaveScheduler(perform, { delayMs: 100, retryDelaysMs: RETRIES });
}

describe('the debounce', () => {
  test('nothing is saved until the writer has been idle', async () => {
    const { perform } = scripted('saved');
    const saver = build(perform);

    saver.schedule();
    await vi.advanceTimersByTimeAsync(99);
    expect(perform).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(perform).toHaveBeenCalledTimes(1);
  });

  test('typing again restarts the wait rather than queueing a second save', async () => {
    const { perform } = scripted('saved');
    const saver = build(perform);

    saver.schedule();
    await vi.advanceTimersByTimeAsync(80);
    saver.schedule();
    await vi.advanceTimersByTimeAsync(80);
    expect(perform).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(20);
    expect(perform).toHaveBeenCalledTimes(1);
  });

  test('the default idle delay is the one the plan asks for', () => {
    expect(AUTOSAVE_DELAY_MS).toBe(1500);
  });
});

describe('flushing', () => {
  test('saves now, without waiting out the debounce', async () => {
    const { perform } = scripted('saved');
    const saver = build(perform);

    saver.schedule();
    await saver.flush();

    expect(perform).toHaveBeenCalledTimes(1);
  });

  test('a flush cancels the pending debounce, so the save does not happen twice', async () => {
    const { perform } = scripted('saved', 'nothing-to-do');
    const saver = build(perform);

    saver.schedule();
    await saver.flush();
    await vi.advanceTimersByTimeAsync(500);

    expect(perform).toHaveBeenCalledTimes(1);
  });

  test('resolves only once the save it started has finished', async () => {
    let release = () => {};
    const inFlight = new Promise<void>((resolve) => {
      release = resolve;
    });
    let finished = false;
    const saver = build(async () => {
      await inFlight;
      finished = true;
      return 'saved';
    });

    const flushed = saver.flush().then(() => {
      expect(finished).toBe(true);
    });
    expect(finished).toBe(false);
    release();
    await flushed;
  });

  test('two flushes at once are serialised, never overlapped', async () => {
    let active = 0;
    let overlapped = false;
    const saver = build(async () => {
      active += 1;
      if (active > 1) {
        overlapped = true;
      }
      await Promise.resolve();
      active -= 1;
      return 'saved';
    });

    await Promise.all([saver.flush(), saver.flush()]);
    expect(overlapped).toBe(false);
  });

  test('a flush that races the debounce timer does not put two saves in the air', async () => {
    let active = 0;
    let overlapped = false;
    const saver = build(async () => {
      active += 1;
      if (active > 1) overlapped = true;
      await vi.advanceTimersByTimeAsync(0);
      active -= 1;
      return 'saved';
    });

    saver.schedule();
    const flushed = saver.flush();
    await vi.advanceTimersByTimeAsync(200);
    await flushed;

    expect(overlapped).toBe(false);
  });
});

describe('failure', () => {
  test('retries after a backoff and keeps trying', async () => {
    const { perform } = scripted('retry', 'retry', 'saved');
    const saver = build(perform);

    await saver.flush();
    expect(perform).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(RETRIES[0]);
    expect(perform).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(RETRIES[1]);
    expect(perform).toHaveBeenCalledTimes(3);
  });

  test('the backoff grows and then holds at its longest', async () => {
    const { perform } = scripted('retry');
    const saver = build(perform);

    await saver.flush();
    await vi.advanceTimersByTimeAsync(RETRIES[0]);
    await vi.advanceTimersByTimeAsync(RETRIES[1]);
    await vi.advanceTimersByTimeAsync(RETRIES[2]);
    expect(perform).toHaveBeenCalledTimes(4);

    // Beyond the schedule it keeps using the last delay rather than growing without bound.
    await vi.advanceTimersByTimeAsync(RETRIES[2]);
    expect(perform).toHaveBeenCalledTimes(5);
  });

  test('a success resets the backoff', async () => {
    const { perform } = scripted('retry', 'saved', 'retry', 'saved');
    const saver = build(perform);

    await saver.flush();
    expect(saver.failureCount).toBe(1);
    await vi.advanceTimersByTimeAsync(RETRIES[0]);
    expect(saver.failureCount).toBe(0);

    await saver.flush();
    expect(saver.failureCount).toBe(1);
    // Back to the first delay, not the second.
    await vi.advanceTimersByTimeAsync(RETRIES[0]);
    expect(perform).toHaveBeenCalledTimes(4);
  });

  test('a `perform` that throws is treated as a failure worth retrying, not as a stop', async () => {
    const perform = vi.fn(async (): Promise<SaveOutcome> => {
      throw new Error('unexpected');
    });
    const saver = build(perform);

    await saver.flush();
    await vi.advanceTimersByTimeAsync(RETRIES[0]);

    expect(perform).toHaveBeenCalledTimes(2);
    expect(saver.isStopped).toBe(false);
  });
});

describe('a conflict', () => {
  test('stops the loop rather than retrying into an overwrite (D19)', async () => {
    const { perform } = scripted('stop');
    const saver = build(perform);

    await saver.flush();
    expect(saver.isStopped).toBe(true);

    saver.schedule();
    await vi.advanceTimersByTimeAsync(1_000);
    await saver.flush();

    expect(perform).toHaveBeenCalledTimes(1);
  });

  test('resuming lets it save again — which is what reloading the server copy does', async () => {
    const { perform } = scripted('stop', 'saved');
    const saver = build(perform);

    await saver.flush();
    saver.resume();
    await saver.flush();

    expect(perform).toHaveBeenCalledTimes(2);
    expect(saver.isStopped).toBe(false);
  });
});

describe('shutting down', () => {
  test('cancel forgets a pending save without writing', async () => {
    const { perform } = scripted('saved');
    const saver = build(perform);

    saver.schedule();
    saver.cancel();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(perform).not.toHaveBeenCalled();
  });

  test('dispose stops everything, including a retry that was armed', async () => {
    const { perform } = scripted('retry');
    const saver = build(perform);

    await saver.flush();
    saver.dispose();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(perform).toHaveBeenCalledTimes(1);
  });

  test('dispose is reversible, because a component can unmount and come back', async () => {
    // React's StrictMode mounts, unmounts, and remounts, and a ref survives that. A one-way
    // dispose would leave autosave permanently off in the real app and nowhere else.
    const { perform } = scripted('saved');
    const saver = build(perform);

    saver.dispose();
    await saver.flush();
    expect(perform).not.toHaveBeenCalled();

    saver.activate();
    await saver.flush();
    expect(perform).toHaveBeenCalledTimes(1);
  });

  test('coming back does not clear a conflict', async () => {
    const { perform } = scripted('stop', 'saved');
    const saver = build(perform);

    await saver.flush();
    expect(saver.isStopped).toBe(true);

    saver.dispose();
    saver.activate();

    expect(saver.isStopped).toBe(true);
    await saver.flush();
    expect(perform).toHaveBeenCalledTimes(1);
  });
});
