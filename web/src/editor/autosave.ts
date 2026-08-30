/**
 * When a save happens (P1-10).
 *
 * This is the *timing* of autosave and nothing else: debounce, one-save-at-a-time, retry with
 * backoff, and a flush that can be awaited. What a save actually does — read the editor, call
 * the API, move the state — is the `perform` callback, supplied by whoever owns that state.
 * Splitting it this way is what lets the rules P1-10 cares about be tested with fake timers and
 * no React, no network, and no editor.
 *
 * Two properties matter more than the rest, because between them they are the difference
 * between an app a writer trusts and one they do not:
 *
 * * **`flush()` can be awaited, and resolves only when nothing is left to write.** Switching
 *   documents, navigating, and unloading all await it, so switching chapters with unsaved
 *   changes cannot lose a keystroke.
 * * **Attempts are serialised.** Every attempt goes on one chain, so two flushes, or a flush
 *   racing the debounce timer, can never put two saves in the air presenting the same version —
 *   which the server would rightly refuse as a conflict (D19) over a race the client caused.
 *
 * A failed save is retried with backoff and never discards content: `perform` keeps the content,
 * this decides when to ask again. A conflict stops the loop entirely — the writer is asked what
 * to do rather than having the retry quietly overwrite whatever moved.
 *
 * There are two independent stops, and they are not the same thing: {@link dispose} is the
 * component's lifetime, undone by {@link activate}; `stop` is a conflict, undone by
 * {@link resume}. Conflating them would mean a remount cleared a conflict, or that answering a
 * conflict revived a scheduler whose component had gone.
 */

import type { SaveResult, VersionConflictDetail } from '../api/types';

export type { SaveResult, VersionConflictDetail };

/** Idle time before an edit is saved. The plan asks for about a second and a half. */
export const AUTOSAVE_DELAY_MS = 1500;

/**
 * Backoff between retries, in milliseconds; the last is used for every attempt beyond it.
 *
 * It tops out at half a minute rather than growing without bound: the usual cause of a failing
 * save here is a server that was stopped and will be started again, and a writer who fixes it
 * should not wait ten minutes to find out that they did.
 */
export const RETRY_DELAYS_MS: readonly number[] = [1_000, 2_000, 5_000, 10_000, 30_000];

/** What one attempt did, and therefore what should happen next. */
export type SaveOutcome =
  /** Written. Reset the backoff. */
  | 'saved'
  /** Nothing was dirty. Not a failure, and not worth a retry. */
  | 'nothing-to-do'
  /** Failed in a way that might succeed later. Try again after a backoff. */
  | 'retry'
  /** Failed in a way retrying cannot fix — a conflict. Stop until told otherwise. */
  | 'stop';

export interface SaveSchedulerOptions {
  /** Idle delay before a scheduled save runs. Defaults to {@link AUTOSAVE_DELAY_MS}. */
  delayMs?: number;
  /** Backoff schedule. Defaults to {@link RETRY_DELAYS_MS}. */
  retryDelaysMs?: readonly number[];
}

export class SaveScheduler {
  private readonly perform: () => Promise<SaveOutcome>;
  private readonly delayMs: number;
  private readonly retryDelaysMs: readonly number[];

  private timer: ReturnType<typeof setTimeout> | null = null;
  /** Attempts run one after another on this chain, which never rejects. */
  private chain: Promise<void> = Promise.resolve();
  private failures = 0;
  private stopped = false;
  private disposed = false;

  constructor(perform: () => Promise<SaveOutcome>, options: SaveSchedulerOptions = {}) {
    this.perform = perform;
    this.delayMs = options.delayMs ?? AUTOSAVE_DELAY_MS;
    this.retryDelaysMs = options.retryDelaysMs ?? RETRY_DELAYS_MS;
  }

  /** True once a conflict has stopped the loop; `resume()` is the only way back. */
  get isStopped(): boolean {
    return this.stopped;
  }

  /** How many consecutive failures the backoff is counting. Zero after any success. */
  get failureCount(): number {
    return this.failures;
  }

  /** An edit happened: save once the writer has been idle for the debounce delay. */
  schedule(): void {
    if (this.disposed || this.stopped) {
      return;
    }
    this.arm(this.delayMs);
  }

  /**
   * Save now, and resolve when there is nothing left to write.
   *
   * Awaited before switching documents, before navigating, and on unload. Safe to call when
   * nothing is dirty — `perform` answers `nothing-to-do` and this resolves immediately.
   */
  flush(): Promise<void> {
    this.cancelTimer();
    if (this.disposed) {
      return this.chain;
    }
    return this.enqueue();
  }

  /**
   * Let the loop run again after a conflict stopped it.
   *
   * Called once the writer has resolved the conflict — by reloading the server's copy, which
   * makes the editor's version current again. It does not itself save.
   */
  resume(): void {
    this.stopped = false;
    this.failures = 0;
  }

  /** Forget any pending save without writing. Used when the document is being replaced. */
  cancel(): void {
    this.cancelTimer();
    this.failures = 0;
    this.stopped = false;
  }

  /**
   * Stop: cancel what is pending and refuse further work.
   *
   * Reversible, because React can unmount and remount a component without rebuilding what its
   * refs hold — `StrictMode` does exactly that on every mount. A one-way `dispose` would leave a
   * scheduler that is alive, reachable, and permanently refusing to save, in the real app only.
   */
  dispose(): void {
    this.disposed = true;
    this.cancelTimer();
  }

  /** Undo {@link dispose}. Called when the component that owns this scheduler (re)mounts. */
  activate(): void {
    this.disposed = false;
  }

  private arm(delayMs: number): void {
    this.cancelTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.enqueue();
    }, delayMs);
  }

  private enqueue(): Promise<void> {
    const next = this.chain.then(() => this.attempt());
    // The chain must never reject, or every later attempt chained onto it would be skipped.
    this.chain = next;
    return next;
  }

  private async attempt(): Promise<void> {
    if (this.disposed || this.stopped) {
      return;
    }
    let outcome: SaveOutcome;
    try {
      outcome = await this.perform();
    } catch {
      // `perform` is expected to handle its own failures and answer with an outcome. One that
      // throws anyway is treated as a failure worth retrying rather than as a reason to stop.
      outcome = 'retry';
    }

    switch (outcome) {
      case 'saved':
      case 'nothing-to-do':
        this.failures = 0;
        return;
      case 'retry':
        this.failures += 1;
        if (!this.disposed) {
          this.arm(this.backoffMs());
        }
        return;
      case 'stop':
        this.stopped = true;
        this.cancelTimer();
        return;
    }
  }

  private backoffMs(): number {
    const index = Math.min(this.failures - 1, this.retryDelaysMs.length - 1);
    return this.retryDelaysMs[Math.max(0, index)] ?? AUTOSAVE_DELAY_MS;
  }

  private cancelTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}
