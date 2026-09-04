/**
 * One form for seven kinds (P3-13, D26).
 *
 * Name, summary, and body on every kind; the kind's own fields below, in the definition's order,
 * each rendered by whichever of the six inputs its type names. Nothing in this file knows which
 * kinds exist or what fields they have — it is handed a `KindDefinition` and renders it — which
 * is what makes "adding a field to a kind is a change to one server-side definition" true.
 *
 * ## The retcon control sits on the save
 *
 * Not on a menu and not after the fact: the writer sees, before pressing the button, whether
 * this save is going to disturb the entries that depend on this one, and why the box came up the
 * way it did (D27). That is D12's posture applied to the bible — the writer is shown what is
 * about to happen and decides.
 *
 * The box's default is **predicted** here and **decided** by the server. The form sends `retcon`
 * only when the writer has actually moved it, so an ordinary save carries no override and the
 * store's own computation stands; the result then says what really happened. See
 * `retconFields` in `bibleSchema.ts` for why the rule is stated twice and how that stays honest.
 */

import { useCallback, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../api';
import type { Entry, FieldDefinition, KindDefinition } from '../api/types';
import { ERROR_CODES, FIELD_TYPES } from '../api/types';
import { emptyValue, retconFields } from '../bibleSchema';
import { FieldInput } from './EntryFields';

/** What the writer has typed, in the shape a create or an update body takes. */
export interface EntryDraft {
  name: string;
  summary: string;
  body_md: string;
  attributes: Record<string, unknown>;
}

export interface EntryFormProps {
  definition: KindDefinition;
  /** The record being edited, or `null` when this form is making a new one. */
  entry: Entry | null;
  /** Live entries the `entry_ref` pickers may offer. */
  candidates: readonly Entry[];
  busy: boolean;
  /** What the server said, keyed by the field it named. `name` and `summary` appear here too. */
  errors: Record<string, string>;
  submitLabel: string;
  /**
   * Save. `retcon` is `null` unless the writer moved the box, in which case it is an override.
   */
  onSubmit: (draft: EntryDraft, retcon: boolean | null) => void;
  onCancel: (() => void) | null;
}

export function EntryForm({
  definition,
  entry,
  candidates,
  busy,
  errors,
  submitLabel,
  onSubmit,
  onCancel,
}: EntryFormProps) {
  const [draft, setDraft] = useState<EntryDraft>(() => draftOf(entry, definition));
  const [override, setOverride] = useState<boolean | null>(null);

  // Re-seed when a different record — or a different revision of the same one — arrives, which
  // is what happens after a save, after a restore, and after a `409` is answered with a reload.
  // Watching the draft instead would push the writer's own typing back at them.
  const seed = `${entry?.id ?? 'new'}:${entry?.revision ?? 0}:${definition.kind}`;
  const lastSeed = useRef(seed);
  if (lastSeed.current !== seed) {
    lastSeed.current = seed;
    setDraft(draftOf(entry, definition));
    setOverride(null);
  }

  const setField = useCallback((name: string, value: unknown) => {
    setDraft((current) => ({
      ...current,
      attributes: { ...current.attributes, [name]: value },
    }));
  }, []);

  const moved = entry === null ? [] : retconFields(entry, draft);
  const checked = override ?? moved.length > 0;

  const submit = useCallback(
    (event: FormEvent) => {
      event.preventDefault();
      onSubmit({ ...draft, attributes: prune(draft.attributes, definition.fields) }, override);
    },
    [definition.fields, draft, onSubmit, override],
  );

  return (
    <form className="entry-form" onSubmit={submit}>
      <div className={`entry-field${errors['name'] ? ' entry-field-bad' : ''}`}>
        <label htmlFor="entry-name">Name</label>
        <input
          id="entry-name"
          type="text"
          value={draft.name}
          disabled={busy}
          onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
        />
        {errors['name'] && (
          <p className="entry-field-error" role="alert">
            {errors['name']}
          </p>
        )}
      </div>

      <div className={`entry-field${errors['summary'] ? ' entry-field-bad' : ''}`}>
        <label htmlFor="entry-summary">Summary</label>
        <input
          id="entry-summary"
          type="text"
          value={draft.summary}
          disabled={busy}
          onChange={(event) =>
            setDraft((current) => ({ ...current, summary: event.target.value }))
          }
        />
        <p className="entry-field-help">
          One line. What the list shows, and what the agent is given in a context budget.
        </p>
        {errors['summary'] && (
          <p className="entry-field-error" role="alert">
            {errors['summary']}
          </p>
        )}
      </div>

      <div className={`entry-field${errors['body_md'] ? ' entry-field-bad' : ''}`}>
        <label htmlFor="entry-body">Notes</label>
        <textarea
          id="entry-body"
          rows={6}
          value={draft.body_md}
          disabled={busy}
          onChange={(event) =>
            setDraft((current) => ({ ...current, body_md: event.target.value }))
          }
        />
        <p className="entry-field-help">
          Markdown as text, not as a manuscript — an entry is a note.
        </p>
        {errors['body_md'] && (
          <p className="entry-field-error" role="alert">
            {errors['body_md']}
          </p>
        )}
      </div>

      {definition.fields.map((field) => (
        <FieldInput
          key={field.name}
          field={field}
          value={draft.attributes[field.name]}
          onChange={(value) => setField(field.name, value)}
          disabled={busy}
          error={errors[field.name] ?? errors['attributes'] ?? null}
          candidates={candidates}
        />
      ))}

      {entry !== null && (
        <div className="entry-retcon">
          <label>
            <input
              type="checkbox"
              checked={checked}
              disabled={busy}
              onChange={(event) => setOverride(event.target.checked)}
            />
            Treat this as a retcon
          </label>
          <p className="entry-field-help">{retconReason(moved, override)}</p>
        </div>
      )}

      <div className="entry-form-actions">
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : submitLabel}
        </button>
        {onCancel && (
          <button type="button" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

/** The draft an untouched form holds: what is stored, plus an empty input for everything else. */
export function draftOf(entry: Entry | null, definition: KindDefinition): EntryDraft {
  const attributes: Record<string, unknown> = {};
  for (const field of definition.fields) {
    const stored = entry?.attributes[field.name];
    attributes[field.name] = stored === undefined ? emptyValue(field.type) : stored;
  }
  return {
    name: entry?.name ?? '',
    summary: entry?.summary ?? '',
    body_md: entry?.body_md ?? '',
    attributes,
  };
}

/**
 * The attribute map as it goes on the wire.
 *
 * Blank lines are dropped from a `list_of_text` and empty parts from a `story_time`, because a
 * line the writer opened and did not fill in is not an alias. Everything else is sent as it is:
 * the server reads `""`, `[]`, and `{}` as absent and stores neither, so there is one rule about
 * emptiness and it is the store's.
 */
export function prune(
  attributes: Record<string, unknown>,
  fields: readonly FieldDefinition[],
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const field of fields) {
    const value = attributes[field.name];
    if (field.type === FIELD_TYPES.listOfText && Array.isArray(value)) {
      result[field.name] = value.filter((item) => typeof item === 'string' && item.trim() !== '');
    } else if (field.type === FIELD_TYPES.storyTime && isRecord(value)) {
      const part: Record<string, unknown> = {};
      for (const [key, item] of Object.entries(value)) {
        if (item !== undefined && item !== null && item !== '') {
          part[key] = item;
        }
      }
      result[field.name] = part;
    } else if (value !== undefined) {
      result[field.name] = value;
    }
  }
  return result;
}

/** Why the box came up the way it did, in words the writer can act on. */
export function retconReason(moved: readonly string[], override: boolean | null): string {
  const because =
    moved.length === 0
      ? 'Nothing that established facts depend on has moved.'
      : `The ${list(moved)} changed, so entries linked to this one will be asked to be reviewed.`;
  if (override === null) {
    return because;
  }
  return override
    ? `${because} You have asked for this to count as a retcon anyway.`
    : `${because} You have asked for this not to count as a retcon.`;
}

/**
 * A refusal, read as messages against the inputs it named.
 *
 * Two shapes reach here, and both name a field. `invalid_attributes` is the bible's own — an
 * unknown kind, an undeclared attribute, a value of the wrong type, an `enum` outside its set, an
 * `entry_ref` to a kind the field does not allow — and carries the field in `detail`. A
 * `validation_error` is FastAPI's, and carries pydantic's `loc` path, whose second element is the
 * body field.
 *
 * Anything it cannot place lands under the empty key, which the caller shows above the form: a
 * refusal nobody can see is a save that appears to have done nothing.
 */
export function formErrorsOf(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) {
    return { '': error instanceof Error ? error.message : String(error) };
  }

  const invalid = error.invalidAttributes;
  if (invalid !== null) {
    return invalid.field === null ? { '': error.message } : { [invalid.field]: error.message };
  }

  if (error.code === ERROR_CODES.validation && Array.isArray(error.detail)) {
    const errors: Record<string, string> = {};
    for (const item of error.detail) {
      if (!isRecord(item)) {
        continue;
      }
      const location = item['loc'];
      const message = item['msg'];
      const field = Array.isArray(location) ? location[1] : undefined;
      errors[typeof field === 'string' ? field : ''] =
        typeof message === 'string' ? message : error.message;
    }
    return Object.keys(errors).length > 0 ? errors : { '': error.message };
  }

  return { '': error.message };
}

function list(items: readonly string[]): string {
  return items.length < 2 ? (items[0] ?? '') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
