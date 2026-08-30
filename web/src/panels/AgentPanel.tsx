/**
 * The agent panel — a placeholder with a real region behind it (P1-9).
 *
 * There is no AI in Phase 1 and not even a stub route for one. The panel exists anyway, taking
 * its third of the workspace, because a layout that has never had three regions in it is a
 * layout that will be rebuilt around the third one when it arrives. It resizes, collapses, and
 * persists exactly like the outline panel does.
 *
 * What it says is what is true: the agent arrives in Phase 4, and every token it will spend will
 * be spent because the writer asked for it (D13).
 */

export function AgentPanel() {
  return (
    <div className="agent-panel">
      <h2 className="panel-heading">Assistant</h2>
      <p className="panel-placeholder">
        The assistant arrives in Phase 4. It will read what you point it at — a selection, a
        chapter, the story bible — and answer with findings you accept or reject. It never
        rewrites your manuscript on its own.
      </p>
      <p className="panel-placeholder">
        Nothing here runs in the background: every request to a model will be one you made
        deliberately.
      </p>
    </div>
  );
}
