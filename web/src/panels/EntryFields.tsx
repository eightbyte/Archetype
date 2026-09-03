/**
 * One renderer per field type — six, closed (P3-5, P3-13, D26).
 *
 * This file is the client half of the decision that keeps Phase 3 finishable. Seven kinds do not
 * get seven forms; they get **one** form rendered from the served definition, and the only thing
 * that varies between them is which of these six inputs appears and in what order. Adding a
 * field to a kind is a change to `server/archetype/bible/schema.py` and nothing here.
 *
 * The list is closed, and it fails loudly rather than quietly: `assertFieldType` throws for a
 * seventh type, which takes the Bible tab into its own error boundary with a sentence saying the
 * definition and the renderer have parted company. Rendering nothing would be a form that
 * silently drops a field somebody typed into — the failure this closure exists to prevent.
 *
 * Every input is controlled and every one of them reports its own error, because the server
 * refuses an attribute map **naming the field** (`invalid_attributes`), and a form that answers
 * "that did not work" leaves the writer hunting through eight inputs for the one that is wrong.
 */

import { useId } from 'react';
import type { ReactNode } from 'react';
import type { Entry, FieldDefinition } from '../api/types';
import { FIELD_TYPES } from '../api/types';
import { assertFieldType, refCandidates, storyTimeOf } from '../bibleSchema';

export interface FieldInputProps {
  field: FieldDefinition;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
  /** What the server said about this field, or null. */
  error: string | null;
  /** Live entries an `entry_ref` may point at. Ignored by every other type. */
  candidates: readonly Entry[];
}

/**
 * One field of one kind, rendered as its type says.
 *
 * The switch is exhaustive over the six and unreachable past them: `assertFieldType` has already
 * thrown for anything else, so the `default` is a second guard rather than a fallback.
 */
export function FieldInput(props: FieldInputProps) {
  assertFieldType(props.field.type);
  switch (props.field.type) {
    case FIELD_TYPES.text:
      return <TextField {...props} />;
    case FIELD_TYPES.longText:
      return <LongTextField {...props} />;
    case FIELD_TYPES.listOfText:
      return <ListOfTextField {...props} />;
    case FIELD_TYPES.enum:
      return <EnumField {...props} />;
    case FIELD_TYPES.entryRef:
      return <EntryRefField {...props} />;
    case FIELD_TYPES.storyTime:
      return <StoryTimeField {...props} />;
    default:
      // Unreachable while `assertFieldType` holds, and a loud failure rather than a silent pass
      // if it ever does not.
      throw new Error(`unhandled bible field type '${props.field.type}'`);
  }
}

/** The label, the help line, and the message the server sent about this field. */
function FieldShell({
  field,
  htmlFor,
  error,
  children,
}: {
  field: FieldDefinition;
  htmlFor: string;
  error: string | null;
  children: ReactNode;
}) {
  return (
    <div className={`entry-field entry-field-${field.type}${error ? ' entry-field-bad' : ''}`}>
      <label htmlFor={htmlFor}>
        {field.label}
        {field.required && <span className="entry-required"> (required)</span>}
      </label>
      {children}
      {field.help && <p className="entry-field-help">{field.help}</p>}
      {error && (
        <p className="entry-field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function TextField({ field, value, onChange, disabled, error }: FieldInputProps) {
  const id = useId();
  return (
    <FieldShell field={field} htmlFor={id} error={error}>
      <input
        id={id}
        type="text"
        value={asText(value)}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </FieldShell>
  );
}

function LongTextField({ field, value, onChange, disabled, error }: FieldInputProps) {
  const id = useId();
  return (
    <FieldShell field={field} htmlFor={id} error={error}>
      <textarea
        id={id}
        rows={4}
        value={asText(value)}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </FieldShell>
  );
}

/**
 * Aliases, traits, epithets — an add/remove list of lines.
 *
 * A blank line is a line the writer has not filled in yet, not a value: the form prunes them on
 * the way out (`EntryForm.attributesOf`), so leaving one open and saving stores nothing rather
 * than storing an empty alias.
 */
function ListOfTextField({ field, value, onChange, disabled, error }: FieldInputProps) {
  const id = useId();
  const items = asList(value);
  const replace = (index: number, text: string) =>
    onChange(items.map((item, at) => (at === index ? text : item)));

  return (
    <FieldShell field={field} htmlFor={`${id}-0`} error={error}>
      <ul className="entry-list-field">
        {items.map((item, index) => (
          // The index is the identity here on purpose: the values are what the writer is editing,
          // so keying on them would remount the input they are typing into on every keystroke.
          <li key={index}>
            <input
              id={`${id}-${index}`}
              type="text"
              aria-label={`${field.label} ${index + 1}`}
              value={item}
              disabled={disabled}
              onChange={(event) => replace(index, event.target.value)}
            />
            <button
              type="button"
              disabled={disabled}
              aria-label={`Remove ${field.label} ${index + 1}`}
              onClick={() => onChange(items.filter((_, at) => at !== index))}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
      <button type="button" disabled={disabled} onClick={() => onChange([...items, ''])}>
        Add {field.label.toLowerCase()}
      </button>
    </FieldShell>
  );
}

/**
 * One of a fixed set the field declares.
 *
 * The empty option is first and is not one of the members: a field the writer has not answered
 * is absent, and a select with no way back to "not answered" is a field that cannot be undone.
 */
function EnumField({ field, value, onChange, disabled, error }: FieldInputProps) {
  const id = useId();
  return (
    <FieldShell field={field} htmlFor={id} error={error}>
      <select
        id={id}
        value={asText(value)}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">—</option>
        {field.members.map((member) => (
          <option key={member} value={member}>
            {member.replace(/_/g, ' ')}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

/**
 * A picker over another entry, filtered to the kinds the field declares.
 *
 * An `entry_ref` is a **field**, not a link: it is a property of the entry that owns it, it has
 * no story-time bounds, and it has no place of its own in the chart. Where both would be
 * defensible the link wins, because only a link can be dated (`specs/bible.md` § 3).
 *
 * The stored value is an entry id, so a reference whose target this client has not loaded still
 * shows something rather than emptying itself — the id is offered as its own option.
 */
function EntryRefField({ field, value, onChange, disabled, error, candidates }: FieldInputProps) {
  const id = useId();
  const current = asText(value);
  const allowed = refCandidates(field, candidates);
  const known = allowed.some((entry) => entry.id === current);

  return (
    <FieldShell field={field} htmlFor={id} error={error}>
      <select
        id={id}
        value={current}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">—</option>
        {allowed.map((entry) => (
          <option key={entry.id} value={entry.id}>
            {entry.name}
          </option>
        ))}
        {current !== '' && !known && <option value={current}>{current}</option>}
      </select>
    </FieldShell>
  );
}

/**
 * D28's three parts, all optional: a label, a sort key, and an era.
 *
 * The label is what a person reads as "when" and it **never sorts**. `sort_key` is the only
 * number in story-time and it is a float, so an event can be inserted between two others without
 * renumbering. An era is a name on an event, not a stored entity — eras rank by the least key
 * among their members.
 *
 * No calendar is parsed here and none is ever required (D9): a secondary-world calendar does not
 * parse, and demanding one would make story-time unusable for the manuscripts this is for.
 */
function StoryTimeField({ field, value, onChange, disabled, error }: FieldInputProps) {
  const id = useId();
  const current = storyTimeOf(value);
  const change = (part: Record<string, unknown>) => onChange({ ...current, ...part });

  return (
    <FieldShell field={field} htmlFor={`${id}-label`} error={error}>
      <div className="entry-storytime">
        <input
          id={`${id}-label`}
          type="text"
          aria-label={`${field.label} — how it reads`}
          placeholder="the first grey morning"
          value={current.label ?? ''}
          disabled={disabled}
          onChange={(event) => change({ label: event.target.value })}
        />
        <input
          id={`${id}-key`}
          type="number"
          step="any"
          aria-label={`${field.label} — sort key`}
          placeholder="order"
          value={current.sort_key === undefined ? '' : String(current.sort_key)}
          disabled={disabled}
          onChange={(event) => change({ sort_key: numberOrRaw(event.target.value) })}
        />
        <input
          id={`${id}-era`}
          type="text"
          aria-label={`${field.label} — era`}
          placeholder="era"
          value={current.era ?? ''}
          disabled={disabled}
          onChange={(event) => change({ era: event.target.value })}
        />
      </div>
    </FieldShell>
  );
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => (typeof item === 'string' ? item : '')) : [];
}

/**
 * A sort key as the writer typed it: a number when it is one, the raw text when it is not.
 *
 * Deliberately **not** validated here. There is one validator for a story-time value and it is
 * the server's, which answers with a message naming the field; a second one on this side would
 * be a rule nobody wrote down, disagreeing with the first the day one of them changes.
 */
function numberOrRaw(raw: string): unknown {
  if (raw.trim() === '') {
    return undefined;
  }
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : raw;
}
