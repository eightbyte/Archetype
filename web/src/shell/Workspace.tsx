/**
 * The three-region workspace (P1-9).
 *
 * Outline panel · editor · agent panel, laid out with CSS grid whose two side columns are driven
 * by `UiContext`. Grid rather than flex because a divider needs a column of its own, and grid is
 * the only layout where the divider's column and the pane's column are separate things that
 * cannot drift apart.
 *
 * A collapsed pane becomes a narrow rail with a button on it rather than disappearing. A pane
 * that vanishes entirely is a pane a writer cannot find again.
 *
 * Each region is wrapped in its own error boundary, so a panel that throws while drawing takes
 * itself down and leaves the editor — which may be holding the only copy of a sentence — alone
 * (P1-13).
 */

import { useCallback } from 'react';
import type { CSSProperties } from 'react';
import { AgentPanel } from '../panels/AgentPanel';
import { OutlinePanel } from '../panels/OutlinePanel';
import { plural } from '../format';
import { useDocument } from '../state/DocumentContext';
import { useProject } from '../state/ProjectContext';
import { useToasts } from '../state/ToastContext';
import { useUi } from '../state/UiContext';
import type { Pane } from '../state/uiReducer';
import { EditorRegion } from './EditorRegion';
import { ErrorBoundary } from './ErrorBoundary';
import { SplitDivider } from './SplitDivider';

/** Width of a collapsed pane's rail, in pixels. Wide enough for the button that reopens it. */
export const RAIL_WIDTH = 28;

export interface WorkspaceProps {
  /** Back to the picker. Called only once it is safe to leave the open chapter. */
  onLeaveProject: () => void;
}

export function Workspace({ onLeaveProject }: WorkspaceProps) {
  const { state: ui, dispatch } = useUi();
  const { state: projectState } = useProject();
  const { canLeave } = useDocument();
  const { push } = useToasts();

  const resize = useCallback(
    (pane: Pane, width: number) => dispatch({ type: 'resize-pane', pane, width }),
    [dispatch],
  );
  const nudge = useCallback(
    (pane: Pane, by: number) => dispatch({ type: 'nudge-pane', pane, by }),
    [dispatch],
  );
  const toggle = useCallback(
    (pane: Pane) => dispatch({ type: 'toggle-pane', pane }),
    [dispatch],
  );

  const leave = useCallback(async () => {
    if (await canLeave()) {
      onLeaveProject();
      return;
    }
    push('Staying here — this chapter has unsaved changes that have not been saved yet.');
  }, [canLeave, onLeaveProject, push]);

  const style = {
    '--outline-width': `${ui.outlineCollapsed ? RAIL_WIDTH : ui.outlineWidth}px`,
    '--agent-width': `${ui.agentCollapsed ? RAIL_WIDTH : ui.agentWidth}px`,
  } as CSSProperties;

  const project = projectState.project;

  return (
    <div className="workspace-frame">
      <header className="workspace-header">
        <button type="button" className="workspace-back" onClick={() => void leave()}>
          ← Projects
        </button>
        <h1>{project?.title ?? 'Loading…'}</h1>
        {project && (
          <span className="workspace-meta">
            {plural(project.chapter_count, 'chapter')} · {plural(project.word_count, 'word')}
          </span>
        )}
      </header>

      <div className="workspace" style={style}>
        <section className="region region-outline" aria-label="Outline">
          {ui.outlineCollapsed ? (
            <Rail label="Show the outline panel" onExpand={() => toggle('outline')} text="Outline" />
          ) : (
            <ErrorBoundary region="Outline">
              <OutlinePanel />
            </ErrorBoundary>
          )}
        </section>

        <SplitDivider
          pane="outline"
          side="left"
          label="Outline panel width"
          width={ui.outlineWidth}
          collapsed={ui.outlineCollapsed}
          onResize={(width) => resize('outline', width)}
          onNudge={(by) => nudge('outline', by)}
          onToggle={() => toggle('outline')}
        />

        <section className="region region-editor" aria-label="Manuscript">
          <ErrorBoundary region="Manuscript">
            <EditorRegion />
          </ErrorBoundary>
        </section>

        <SplitDivider
          pane="agent"
          side="right"
          label="Assistant panel width"
          width={ui.agentWidth}
          collapsed={ui.agentCollapsed}
          onResize={(width) => resize('agent', width)}
          onNudge={(by) => nudge('agent', by)}
          onToggle={() => toggle('agent')}
        />

        <section className="region region-agent" aria-label="Assistant">
          {ui.agentCollapsed ? (
            <Rail
              label="Show the assistant panel"
              onExpand={() => toggle('agent')}
              text="Assistant"
            />
          ) : (
            <ErrorBoundary region="Assistant">
              <AgentPanel />
            </ErrorBoundary>
          )}
        </section>
      </div>
    </div>
  );
}

interface RailProps {
  label: string;
  text: string;
  onExpand: () => void;
}

function Rail({ label, text, onExpand }: RailProps) {
  return (
    <button type="button" className="rail" aria-label={label} onClick={onExpand}>
      <span className="rail-text">{text}</span>
    </button>
  );
}
