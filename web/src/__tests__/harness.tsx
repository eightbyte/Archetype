/**
 * Mounting the workspace in a test (P1-9 → P1-13).
 *
 * The provider stack is the app's, not a simplified stand-in: a test that assembled its own
 * would stop proving that the real one is wired up. What changes is the client — the
 * hand-written fake — and the autosave timings, which are shortened so a test does not sit for a
 * second and a half.
 */

import { render } from '@testing-library/react';
import type { ReactNode } from 'react';
import type { ApiClient, ProseMirrorDocument } from '../api';
import type { SaveSchedulerOptions } from '../editor/autosave';
import { DocumentProvider } from '../state/DocumentContext';
import { ProjectProvider } from '../state/ProjectContext';
import { ToastProvider } from '../state/ToastContext';
import { UiProvider } from '../state/UiContext';
import type { UiState } from '../state/uiReducer';
import { Toasts } from '../shell/Toasts';

/** Short enough that a test does not wait, long enough that a debounce is still a debounce. */
export const TEST_AUTOSAVE_DELAY_MS = 20;
export const TEST_RETRY_DELAYS_MS = [20, 40] as const;

export interface HarnessOptions {
  client: ApiClient;
  projectId: string;
  children: ReactNode;
  ui?: UiState;
  autoOpenFirst?: boolean;
  /** Override the hurried defaults — a test that needs the retry loop *not* to fire. */
  scheduler?: SaveSchedulerOptions;
}

/** The real provider stack, with a fake client and a hurried autosave. */
export function Harness({
  client,
  projectId,
  children,
  ui,
  autoOpenFirst,
  scheduler,
}: HarnessOptions) {
  return (
    <ToastProvider>
      <UiProvider {...(ui ? { initialState: ui } : {})}>
        <ProjectProvider client={client} projectId={projectId}>
          <DocumentProvider
            client={client}
            scheduler={{
              delayMs: TEST_AUTOSAVE_DELAY_MS,
              retryDelaysMs: TEST_RETRY_DELAYS_MS,
              ...scheduler,
            }}
            {...(autoOpenFirst === undefined ? {} : { autoOpenFirst })}
          >
            {children}
          </DocumentProvider>
        </ProjectProvider>
        <Toasts />
      </UiProvider>
    </ToastProvider>
  );
}

export function renderInWorkspace(options: HarnessOptions) {
  return render(<Harness {...options} />);
}

/** A ProseMirror document of plain paragraphs. */
export function prose(...paragraphs: string[]): ProseMirrorDocument {
  return {
    type: 'doc',
    content: paragraphs.map((text) => ({
      type: 'paragraph',
      content: [{ type: 'text', text }],
    })),
  };
}

/**
 * A ProseMirror document whose blocks are given as `[level, text]` headings or plain strings.
 *
 * An empty string produces a block with no content at all, which is what TipTap makes of an
 * empty paragraph or a heading the writer has not typed into yet. A zero-length *text node* is
 * not the same thing and ProseMirror refuses it outright — so building one here would feed the
 * editor a document it cannot open, and the test would be measuring the fallback.
 */
export function chapter(...blocks: (string | [number, string])[]): ProseMirrorDocument {
  return {
    type: 'doc',
    content: blocks.map((block) => {
      const [type, text, level] =
        typeof block === 'string'
          ? (['paragraph', block, undefined] as const)
          : (['heading', block[1], block[0]] as const);
      return {
        type,
        ...(level === undefined ? {} : { attrs: { level } }),
        ...(text === '' ? {} : { content: [{ type: 'text', text }] }),
      };
    }),
  };
}
