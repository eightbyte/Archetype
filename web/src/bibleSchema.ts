/**
 * Reading D26's served definition (P3-12 → P3-14).
 *
 * One place, because four surfaces ask it the same questions: the entry form asks which fields a
 * kind has, the list asks what a kind is called, the link form asks which relations may join two
 * kinds, and the `entry_ref` picker asks which kinds a field may point at.
 *
 * Nothing here holds a copy of the vocabulary. Every answer is computed from the `BibleSchema`
 * the client fetched, so adding a kind, a field, or a relation on the server changes nothing in
 * this file — which is the whole of what D26 bought (`specs/phase-3-plan.md` § 2).
 *
 * It sits beside `anchorText.ts` for the same reason that does: it is the display edge's shared
 * vocabulary, and both the panels and the editor reach it.
 *
 * Pure. No React, no client, no DOM.
 */

import type {
  BibleSchema,
  Entry,
  FieldDefinition,
  KindDefinition,
  LinkEnd,
  RelationDefinition,
} from './api/types';
import { FIELD_TYPES, LINK_ENDS, isFieldType } from './api/types';

/** One kind's definition, or `null` when the schema does not declare it. */
export function kindOf(schema: BibleSchema | null, kind: string): KindDefinition | null {
  return schema?.kinds.find((definition) => definition.kind === kind) ?? null;
}

/** What a kind is called in the singular — its own name if the schema has never heard of it. */
export function kindLabel(schema: BibleSchema | null, kind: string): string {
  return kindOf(schema, kind)?.label ?? kind;
}

/** What a kind is called in the plural, for a heading over a group of them. */
export function kindPlural(schema: BibleSchema | null, kind: string): string {
  return kindOf(schema, kind)?.plural ?? kind;
}

/** The fields a form renders for a kind, in the definition's order. Empty for an unknown kind. */
export function fieldsOf(schema: BibleSchema | null, kind: string): FieldDefinition[] {
  return kindOf(schema, kind)?.fields ?? [];
}

/**
 * One relation a link between two kinds could carry, and which way it would run.
 *
 * `end` is where the **subject** — the entry whose panel this is — would sit: `from` means the
 * link is written subject → target, and `to` means target → subject. `label` is how the subject's
 * side reads it, so the picker offers a sentence rather than a database column.
 */
export interface RelationOption {
  relation: RelationDefinition;
  end: LinkEnd;
  label: string;
}

/**
 * Every relation that may legally join `subjectKind` to `targetKind`, in either direction.
 *
 * This is what makes an illegal link **unbuildable** rather than refused after the fact (P3-14):
 * the picker is built from this list, so a `place` that `knows` an `item` is never on offer. The
 * server refuses it anyway — that is where the rule lives — but a form that offers a choice and
 * then rejects it is a form that taught the writer something untrue.
 *
 * A relation the definition marks **symmetric** yields exactly one option, never two. It is
 * stored once and read from both ends (ruling 7), so offering "knows" and "is known by" would be
 * offering the same row twice and inviting the duplicate the server would refuse.
 */
export function relationOptions(
  schema: BibleSchema | null,
  subjectKind: string,
  targetKind: string,
): RelationOption[] {
  const options: RelationOption[] = [];
  for (const relation of schema?.relations ?? []) {
    if (relation.from_kinds.includes(subjectKind) && relation.to_kinds.includes(targetKind)) {
      options.push({ relation, end: LINK_ENDS.from, label: relation.label });
    }
    // The reverse is a *different statement* for an asymmetric relation — "is a member of" and
    // "has as a member" are not the same claim — so it is offered separately. For a symmetric
    // one it is the same row, and offering it twice is how a duplicate gets typed.
    if (
      !relation.symmetric &&
      relation.from_kinds.includes(targetKind) &&
      relation.to_kinds.includes(subjectKind)
    ) {
      options.push({ relation, end: LINK_ENDS.to, label: relation.inverse_label });
    }
  }
  return options;
}

/** The kinds an `entry_ref` field may point at, as a predicate over a candidate entry. */
export function refCandidates(field: FieldDefinition, entries: readonly Entry[]): Entry[] {
  return entries.filter((entry) => field.kinds.includes(entry.kind));
}

/**
 * D28's story-time value, as it is stored in an attribute map.
 *
 * Three parts, all optional. `label` is what a person reads as "when" and it never sorts;
 * `sort_key` is the only number in story-time; `era` is a name, not an entity.
 */
export interface StoryTimeValue {
  label?: string;
  sort_key?: number;
  era?: string;
}

/** Read a stored `story_time` attribute, tolerating anything that is not one. */
export function storyTimeOf(value: unknown): StoryTimeValue {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return {};
  }
  const raw = value as Record<string, unknown>;
  const result: StoryTimeValue = {};
  if (typeof raw['label'] === 'string') {
    result.label = raw['label'];
  }
  if (typeof raw['sort_key'] === 'number' && Number.isFinite(raw['sort_key'])) {
    result.sort_key = raw['sort_key'];
  }
  if (typeof raw['era'] === 'string') {
    result.era = raw['era'];
  }
  return result;
}

/**
 * The empty value for a field type — what an untouched input holds.
 *
 * The server reads `""`, `[]`, and `{}` as "absent" and stores neither (`bible/schema.py`), so
 * a form that always sends every field still stores only what was filled in. That is why there
 * is one answer here rather than a `null` and a rule about when to prune.
 */
export function emptyValue(type: string): unknown {
  assertFieldType(type);
  switch (type) {
    case FIELD_TYPES.listOfText:
      return [];
    case FIELD_TYPES.storyTime:
      return {};
    default:
      return '';
  }
}

/**
 * Which retcon-bearing fields a draft has moved — D27's rule, restated **for presentation only**.
 *
 * The form has to show the writer what its save is about to do *before* it happens: P3-13 asks
 * for the computed default as a checkbox with the reason it came up checked, so that a retcon is
 * a visible act rather than a silent consequence (D12's posture, one table over). That is not
 * possible without predicting the answer on this side.
 *
 * So this is a second statement of the rule, and it is kept honest by never being the one that
 * decides: the form sends `retcon` **only when the writer has changed the box**, so an
 * un-touched save carries no override and the store's own answer stands. The write result then
 * reports what actually happened, and that is what the writer is told (`changed_fields`).
 *
 * `status` is absent from the comparison because Phase 3 has no route that writes one.
 */
export function retconFields(entry: Entry, draft: { name: string; attributes: unknown }): string[] {
  const moved: string[] = [];
  if (entry.name !== draft.name) {
    moved.push('name');
  }
  if (!sameAttributes(entry.attributes, draft.attributes)) {
    moved.push('attributes');
  }
  return moved;
}

/**
 * Whether two attribute maps say the same thing.
 *
 * Compared through the JSON the wire would carry, with the keys sorted and the values the server
 * reads as absent — `""`, `[]`, `{}` — removed first. Without that, opening a form and saving it
 * untouched would count as a retcon: every field the entry does not hold arrives in the draft as
 * an empty input, and an empty input is not a change.
 */
function sameAttributes(stored: unknown, draft: unknown): boolean {
  return canonicalJson(stored) === canonicalJson(draft);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`;
  }
  if (typeof value === 'object' && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => !isEmptyValue(item))
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, item]) => `${key}:${canonicalJson(item)}`).join(',')}}`;
  }
  return JSON.stringify(value ?? null);
}

/** What the server stores as nothing at all: an emptied field is an absent field. */
function isEmptyValue(value: unknown): boolean {
  if (value === undefined || value === null || value === '') {
    return true;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  if (typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).every(isEmptyValue);
  }
  return false;
}

/**
 * Refuse a field type the client has no renderer for — **loudly** (D26, P3-5).
 *
 * The type list is closed at six on both sides of the wire. If a seventh ever reaches this
 * client it means the server's definition and this renderer have parted company, and the honest
 * answer is a region that fails into its error boundary saying so. Rendering nothing would be a
 * form that silently drops a field somebody typed into.
 */
export function assertFieldType(type: string): void {
  if (!isFieldType(type)) {
    throw new Error(
      `the bible form has no renderer for the field type '${type}'. The type list is closed at ` +
        'six (D26); a seventh is a change to the server definition, this renderer, and the ' +
        'contract fixture together.',
    );
  }
}
