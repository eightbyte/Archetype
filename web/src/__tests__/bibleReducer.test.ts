/**
 * P3-12, P3-13 — the bible's pure halves.
 *
 * The reducer and the readers over the served definition, tested without React, without a client,
 * and without a DOM. Two of these are load-bearing beyond their size:
 *
 * * `relationOptions` is what makes an illegal link **unbuildable** rather than refused after the
 *   fact, so it is tested against the real definition rather than a hand-made one;
 * * `assertFieldType` is the client half of D26's closed list — the seventh type has to fail
 *   loudly here, or a form silently drops a field somebody typed into.
 */

import { describe, expect, test } from 'vitest';
import type { BibleSchema, Entry } from '../api/types';
import { FIELD_TYPES, LINK_ENDS } from '../api/types';
import {
  assertFieldType,
  emptyValue,
  kindLabel,
  kindPlural,
  fieldsOf,
  refCandidates,
  relationOptions,
  retconFields,
  storyTimeOf,
} from '../bibleSchema';
import type { BibleState } from '../state/bibleReducer';
import {
  INITIAL_BIBLE_STATE,
  bibleReducer,
  entryOf,
  groupByKind,
  isFiltered,
  totalEntries,
} from '../state/bibleReducer';
import { readServerFixture } from './fixtures';

/** The real definition — the same bytes the route serves and the client renders (D26). */
const SCHEMA = readServerFixture<BibleSchema>('contract/bible_schema.json');

function entry(id: string, fields: Partial<Entry> = {}): Entry {
  return {
    id,
    project_id: 'prj_1',
    kind: 'character',
    name: id,
    summary: '',
    body_md: '',
    attributes: {},
    status: 'accepted',
    origin: 'user',
    revision: 1,
    needs_review: false,
    review_reason: '',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    deleted_at: null,
    ...fields,
  };
}

function loaded(entries: Entry[], review: Entry[] = []): BibleState {
  return bibleReducer(INITIAL_BIBLE_STATE, {
    type: 'loaded',
    schema: SCHEMA,
    entries,
    counts: { character: entries.length },
    truncated: false,
    review,
  });
}

describe('the reducer', () => {
  test('a load replaces everything but the filters', () => {
    const narrowed = bibleReducer(INITIAL_BIBLE_STATE, {
      type: 'filters-changed',
      filters: { kind: 'place' },
    });
    const state = bibleReducer(narrowed, {
      type: 'loaded',
      schema: SCHEMA,
      entries: [entry('ent_1')],
      counts: { character: 1 },
      truncated: false,
      review: [],
    });

    expect(state.status).toBe('ready');
    expect(state.entries).toHaveLength(1);
    // A refresh that silently widened what the writer was looking at would look like rows
    // appearing from nowhere.
    expect(state.filters.kind).toBe('place');
  });

  test('a failed refresh keeps the rows already on screen', () => {
    const state = bibleReducer(loaded([entry('ent_1')]), {
      type: 'list-failed',
      message: 'the server could not be reached',
    });

    // Deliberately not `failed`: the rows are still the last thing the server said, and blanking
    // a panel over a refresh that did not land is the P1-12 rule read backwards.
    expect(state.status).toBe('ready');
    expect(state.entries).toHaveLength(1);
    expect(state.error).toBe('the server could not be reached');
  });

  test('a list that lands clears the failure it followed', () => {
    const failed = bibleReducer(loaded([entry('ent_1')]), {
      type: 'list-failed',
      message: 'gone',
    });
    const state = bibleReducer(failed, {
      type: 'listed',
      entries: [entry('ent_2')],
      counts: { character: 1 },
      truncated: false,
    });

    expect(state.error).toBeNull();
    expect(state.refreshing).toBe(false);
    expect(state.entries[0]?.id).toBe('ent_2');
  });

  test('a load that failed outright says so, and says why', () => {
    const state = bibleReducer(INITIAL_BIBLE_STATE, {
      type: 'load-failed',
      message: 'no project',
    });

    expect(state.status).toBe('failed');
    expect(state.error).toBe('no project');
  });

  test('setting a filter to what it already is changes nothing at all', () => {
    const state = loaded([]);
    expect(bibleReducer(state, { type: 'filters-changed', filters: { kind: null } })).toBe(state);
  });

  test('opening the entry that is already open changes nothing at all', () => {
    const state = bibleReducer(loaded([]), { type: 'entry-opened', entryId: 'ent_1' });
    expect(bibleReducer(state, { type: 'entry-opened', entryId: 'ent_1' })).toBe(state);
  });

  test('the review queue is its own list, not a slice of the browse list', () => {
    // Which is the point of holding it separately: it has to be right whatever the writer is
    // filtering the browse list by (P3-12).
    const flagged = entry('ent_2', { needs_review: true, review_reason: 'Kurtz changed' });
    const state = loaded([entry('ent_1')], [flagged]);

    expect(state.entries.map((row) => row.id)).toEqual(['ent_1']);
    expect(state.review.map((row) => row.id)).toEqual(['ent_2']);
  });

  test('an entry is found wherever the state happens to be holding it', () => {
    const state = bibleReducer(loaded([entry('ent_1')], [entry('ent_2')]), {
      type: 'deleted-loaded',
      entries: [entry('ent_3', { deleted_at: '2026-01-02T00:00:00Z' })],
    });

    expect(entryOf(state, 'ent_1')?.id).toBe('ent_1');
    expect(entryOf(state, 'ent_2')?.id).toBe('ent_2');
    expect(entryOf(state, 'ent_3')?.id).toBe('ent_3');
    expect(entryOf(state, 'ent_9')).toBeNull();
    expect(entryOf(state, null)).toBeNull();
  });
});

describe('reading the list', () => {
  test('counts add up across every kind', () => {
    expect(totalEntries({ character: 3, place: 2, item: 0 })).toBe(5);
  });

  test('a filter is anything narrower than everything', () => {
    expect(isFiltered({ kind: null, status: null, q: '' })).toBe(false);
    expect(isFiltered({ kind: null, status: null, q: '   ' })).toBe(false);
    expect(isFiltered({ kind: 'place', status: null, q: '' })).toBe(true);
    expect(isFiltered({ kind: null, status: null, q: 'kurtz' })).toBe(true);
  });

  test('groups follow the definition’s kind order, not the alphabet', () => {
    const groups = groupByKind(
      [entry('a', { kind: 'place' }), entry('b', { kind: 'character' })],
      SCHEMA,
    );

    expect(groups.map(([kind]) => kind)).toEqual(['character', 'place']);
  });

  test('an entry of a kind the schema does not declare still appears, at the end', () => {
    const groups = groupByKind(
      [entry('a', { kind: 'sandwich' }), entry('b', { kind: 'character' })],
      SCHEMA,
    );

    expect(groups.map(([kind]) => kind)).toEqual(['character', 'sandwich']);
  });

  test('empty groups are left out', () => {
    expect(groupByKind([entry('a')], SCHEMA).map(([kind]) => kind)).toEqual(['character']);
  });
});

describe('reading the served definition', () => {
  test('a kind is named in the singular and the plural', () => {
    expect(kindLabel(SCHEMA, 'character')).toBe('Character');
    expect(kindPlural(SCHEMA, 'character')).toBe('Characters');
  });

  test('a kind the schema has never heard of is called by its own name', () => {
    expect(kindLabel(SCHEMA, 'sandwich')).toBe('sandwich');
    expect(fieldsOf(SCHEMA, 'sandwich')).toEqual([]);
  });

  test('every field of every kind has a type this client can render', () => {
    // The client half of D26's closed list. A seventh type on the server fails here rather than
    // rendering nothing in a form.
    for (const kind of SCHEMA.kinds) {
      for (const field of kind.fields) {
        expect(() => assertFieldType(field.type)).not.toThrow();
      }
    }
  });

  test('a field type with no renderer fails loudly, naming it', () => {
    expect(() => assertFieldType('colour')).toThrow(/no renderer for the field type 'colour'/);
  });

  test('an untouched input holds what the server reads as absent', () => {
    expect(emptyValue(FIELD_TYPES.text)).toBe('');
    expect(emptyValue(FIELD_TYPES.listOfText)).toEqual([]);
    expect(emptyValue(FIELD_TYPES.storyTime)).toEqual({});
  });

  test('an entry_ref offers only the kinds its field declares', () => {
    const home = fieldsOf(SCHEMA, 'character').find((field) => field.name === 'home');
    const candidates = [
      entry('ent_1', { kind: 'place' }),
      entry('ent_2', { kind: 'character' }),
      entry('ent_3', { kind: 'item' }),
    ];

    expect(refCandidates(home!, candidates).map((row) => row.id)).toEqual(['ent_1']);
  });

  test('a story-time value tolerates anything that is not one', () => {
    expect(storyTimeOf({ label: 'the grey morning', sort_key: 2, era: 'Before' })).toEqual({
      label: 'the grey morning',
      sort_key: 2,
      era: 'Before',
    });
    expect(storyTimeOf(null)).toEqual({});
    expect(storyTimeOf('the grey morning')).toEqual({});
    expect(storyTimeOf({ sort_key: 'two' })).toEqual({});
  });
});

describe('which relations may join two kinds', () => {
  test('a symmetric relation is offered once, never twice', () => {
    // It is one row, read from both ends (ruling 7). Offering "knows" and "is known by" would be
    // offering the same row twice and inviting the duplicate the server refuses.
    const knows = relationOptions(SCHEMA, 'character', 'character').filter(
      (option) => option.relation.relation === 'knows',
    );

    expect(knows).toHaveLength(1);
    expect(knows[0]?.end).toBe(LINK_ENDS.from);
  });

  test('an asymmetric relation is offered in both directions, as two different statements', () => {
    const opposes = relationOptions(SCHEMA, 'character', 'character').filter(
      (option) => option.relation.relation === 'opposes',
    );

    expect(opposes.map((option) => [option.end, option.label])).toEqual([
      [LINK_ENDS.from, 'opposes'],
      [LINK_ENDS.to, 'is opposed by'],
    ]);
  });

  test('a relation is offered on the side it runs from, and reads that way', () => {
    const fromCharacter = relationOptions(SCHEMA, 'character', 'faction').find(
      (option) => option.relation.relation === 'member_of',
    );
    const fromFaction = relationOptions(SCHEMA, 'faction', 'character').find(
      (option) => option.relation.relation === 'member_of',
    );

    expect(fromCharacter?.end).toBe(LINK_ENDS.from);
    expect(fromCharacter?.label).toBe('is a member of');
    // The same row, offered from the faction's side and reading the other way round.
    expect(fromFaction?.end).toBe(LINK_ENDS.to);
    expect(fromFaction?.label).toBe('has as a member');
  });

  test('a relation is never offered for a pair it does not join', () => {
    // Section 8's step 5, in a unit test: a place that *knows* an item cannot be built, rather
    // than being refused after the fact. What a place and an item legitimately do have is
    // containment, and that is still offered — the picker narrows, it does not go blank.
    const offered = relationOptions(SCHEMA, 'place', 'item');

    expect(offered.map((option) => option.relation.relation)).not.toContain('knows');
    expect(offered.map((option) => option.label)).toEqual(['contains']);
  });

  test('a pair the vocabulary joins in no direction at all is offered nothing', () => {
    expect(relationOptions(SCHEMA, 'thread', 'item')).toEqual([]);
  });

  test('nothing is offered before the definition has arrived', () => {
    expect(relationOptions(null, 'character', 'character')).toEqual([]);
  });
});

describe('predicting the retcon default (D27)', () => {
  const stored = entry('ent_1', { name: 'Kurtz', attributes: { role: 'antagonist' } });

  test('an untouched form is not a retcon', () => {
    // Every field the entry does not hold arrives in the draft as an empty input, and an empty
    // input is not a change — without that rule, opening a form and saving it would flag.
    expect(
      retconFields(stored, {
        name: 'Kurtz',
        attributes: { role: 'antagonist', aliases: [], pronouns: '', home: '', voice: '' },
      }),
    ).toEqual([]);
  });

  test('a changed name is a retcon, and says so', () => {
    expect(retconFields(stored, { name: 'Mister Kurtz', attributes: { role: 'antagonist' } })).toEqual(
      ['name'],
    );
  });

  test('a changed attribute is a retcon', () => {
    expect(retconFields(stored, { name: 'Kurtz', attributes: { role: 'supporting' } })).toEqual([
      'attributes',
    ]);
  });

  test('an emptied attribute is a change, because the entry held one', () => {
    expect(retconFields(stored, { name: 'Kurtz', attributes: { role: '' } })).toEqual([
      'attributes',
    ]);
  });

  test('both moving is reported as both', () => {
    expect(retconFields(stored, { name: 'Marlow', attributes: { role: 'minor' } })).toEqual([
      'name',
      'attributes',
    ]);
  });

  test('a summary or body edit is nobody’s business — neither field is compared', () => {
    // This is the half of D27 that keeps the queue worth reading: fixing a typo in a body must
    // not flag every neighbour.
    expect(retconFields(stored, { name: 'Kurtz', attributes: { role: 'antagonist' } })).toEqual([]);
  });
});
