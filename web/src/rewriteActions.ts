/**
 * Proofread, tone, and rewrite — the three single-pass actions, and the one place their wording
 * lives (P4-14, D12).
 *
 * Each is a question with a fixed phrasing. It travels as an ordinary `ask` frame, so there is
 * no second path to a model and no route that spends tokens differently from the one the panel
 * uses — the standing invariant that every AI feature drives the same API the UI does.
 *
 * ## Why the wording is here rather than on the server
 *
 * Phase 4's socket takes the writer's question **verbatim**, and an action is a question the app
 * asks on their behalf. Putting these strings behind a new frame field or a new route would be a
 * surface the phase did not budget, and it would fix a vocabulary of actions before Phase 6 knows
 * what its tools want to say. So they are one exported table on the client, named as such, and
 * moving them server-side when the agent needs them is a change to one file.
 *
 * The system prompt they land under is the server's (`archetype/llm/context.py`) and already says
 * the half that matters: *never rewrite the manuscript unless you are explicitly asked for a
 * replacement, and when you are, give the replacement and nothing else.* These say the other
 * half — which kind of replacement is being asked for.
 *
 * **Prompt tuning is out of scope for 1.0** (outline § 2). These are a starting point that § 8
 * assesses by hand, not a tuned artefact, and a wording that turns out to be poor is a finding
 * recorded there rather than a bug.
 */

import type { RewriteAction } from './state/chatReducer';

export interface RewriteActionDefinition {
  action: RewriteAction;
  /** What the button says. */
  label: string;
  /** What the panel calls the answer while it is arriving. */
  running: string;
  /** The instruction, which the passage is appended to by the composer's own labelled block. */
  prompt: string;
}

/**
 * The three, closed.
 *
 * Each prompt asks for the replacement **and nothing else**, because the answer is put straight
 * into a before/after and applied as one editor transaction if the writer accepts it. An answer
 * wrapped in "Here is the revised passage:" would put those words into the manuscript.
 */
export const REWRITE_ACTION_DEFINITIONS: readonly RewriteActionDefinition[] = [
  {
    action: 'proofread',
    label: 'Proofread',
    running: 'Proofreading',
    prompt:
      'Proofread the selected passage. Correct spelling, grammar, punctuation, and obvious ' +
      'typos, and change nothing else — not the wording, not the voice, not the paragraphing. ' +
      'Reply with the corrected passage and nothing else: no preamble, no explanation, no ' +
      'quotation marks around it. If the passage needs no correction, reply with it unchanged.',
  },
  {
    action: 'tone',
    label: 'Adjust tone',
    running: 'Adjusting the tone',
    prompt:
      'Rewrite the selected passage so that it reads in the same voice as the rest of the ' +
      'chapter it came from. Keep every event, every fact, and every name exactly as they are; ' +
      'change only how it sounds. Reply with the rewritten passage and nothing else: no ' +
      'preamble, no explanation, no quotation marks around it.',
  },
  {
    action: 'rewrite',
    label: 'Rewrite',
    running: 'Rewriting',
    prompt:
      'Rewrite the selected passage to say the same thing more clearly and more strongly. Keep ' +
      'every event, every fact, and every name. Reply with the rewritten passage and nothing ' +
      'else: no preamble, no explanation, no quotation marks around it.',
  },
];

/** One definition by name. Throws for an action that is not one of the three. */
export function rewriteActionDefinition(action: RewriteAction): RewriteActionDefinition {
  const found = REWRITE_ACTION_DEFINITIONS.find((definition) => definition.action === action);
  if (!found) {
    // The list is closed and the type is a union of its members, so this is unreachable unless
    // one of the two changed without the other. Loudly, for the reason `assertFieldType` is loud.
    throw new Error(`no such rewrite action: ${action}`);
  }
  return found;
}
