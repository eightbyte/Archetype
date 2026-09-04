/**
 * P1-8 — the contract fixtures.
 *
 * `server/tests/test_contract.py` drives the real routes and writes representative responses to
 * `server/tests/fixtures/contract/*.json`. This test reads the same files and checks them against
 * the client's TypeScript types, so a backend shape change fails the suite rather than the
 * browser. Small in Phase 1, load-bearing from Phase 4.
 *
 * The checking is done twice over, deliberately:
 *
 * - at compile time, by assigning the parsed value to the client type — `tsc` rejects a type that
 *   no longer describes anything the server sends;
 * - at run time, by comparing the fixture's key set against the keys the client type declares —
 *   `tsc` cannot see into a `JSON.parse`, so without this a field the server dropped would sail
 *   straight through as `undefined`.
 *
 * The run-time check is an **exact** key match, not a subset. Wire schemas are extension-only, so
 * a new field never breaks an old client — but server and client live in one repository and move
 * in one commit, so a field on one side and not the other is drift, and drift is what this test
 * is for.
 */

import { describe, expect, test } from 'vitest';
import type {
  Anchor,
  AnchorEntries,
  AnchorList,
  BibleSchema,
  Citation,
  CitationRemoved,
  Document,
  DocumentList,
  DocumentMeta,
  Entry,
  EntryDetail,
  EntryFromRange,
  EntryLinks,
  EntryList,
  EntryRevision,
  EntryVersionConflictDetail,
  EntryWriteResult,
  ErrorResponse,
  Health,
  InvalidAttributesDetail,
  Link,
  LinkList,
  MarkdownImport,
  Outline,
  ProjectDetail,
  ProjectList,
  ReorderMismatchDetail,
  RevisionList,
  SaveResult,
  Snapshot,
  SnapshotCapture,
  SnapshotList,
  StoryTime,
  VersionConflictDetail,
} from '../api/types';
import { CITATION_ROLES, ERROR_CODES, FIELD_TYPES, LINK_ENDS, isFieldType } from '../api/types';
import { readServerFixture } from './fixtures';

function load<T>(name: string): T {
  return readServerFixture<T>(`contract/${name}.json`);
}

/** Every key the client type declares, in the order the server sends them. */
const KEYS = {
  health: ['status', 'version'],
  projectSummary: ['id', 'title', 'chapter_count', 'word_count', 'created_at', 'updated_at'],
  skippedFile: ['name', 'reason', 'detail'],
  documentMeta: [
    'id',
    'project_id',
    'order_index',
    'title',
    'kind',
    'headings',
    'word_count',
    'version',
    'created_at',
    'updated_at',
    'deleted_at',
  ],
  document: [
    'id',
    'project_id',
    'order_index',
    'title',
    'kind',
    'content_json',
    'headings',
    'word_count',
    'version',
    'created_at',
    'updated_at',
  ],
  heading: ['level', 'text', 'ordinal'],
  saveResult: ['document_id', 'version', 'word_count', 'headings', 'updated_at', 'anchors'],
  anchor: [
    'id',
    'project_id',
    'document_id',
    'from_pos',
    'to_pos',
    'quote',
    'prefix',
    'suffix',
    'status',
    'label',
    'document_version',
    'created_at',
    'updated_at',
    'checked_at',
    'suggestion',
  ],
  anchorSuggestion: ['from_pos', 'to_pos', 'text'],
  importNotice: ['element', 'line', 'detail'],
  outlineChapter: ['document_id', 'title', 'order_index', 'word_count', 'headings'],
  snapshotMeta: [
    'id',
    'project_id',
    'document_id',
    'taken_at',
    'reason',
    'label',
    'word_count',
    'version',
    'size_bytes',
  ],
  snapshot: [
    'id',
    'project_id',
    'document_id',
    'taken_at',
    'reason',
    'label',
    'word_count',
    'version',
    'size_bytes',
    'content_json',
  ],
  errorBody: ['code', 'message', 'detail'],
  versionConflictDetail: [
    'document_id',
    'presented_version',
    'current_version',
    'updated_at',
  ],
  reorderMismatchDetail: ['missing', 'unexpected', 'duplicated'],
  entry: [
    'id',
    'project_id',
    'kind',
    'name',
    'summary',
    'body_md',
    'attributes',
    'status',
    'origin',
    'revision',
    'needs_review',
    'review_reason',
    'created_at',
    'updated_at',
    'deleted_at',
  ],
  narrativePosition: ['entry_id', 'document_id', 'order_index', 'from_pos'],
  citation: ['entry_id', 'anchor', 'role', 'created_at', 'document_id', 'document_title'],
  citingEntry: ['entry_id', 'kind', 'name', 'role', 'created_at'],
  revisionMeta: ['entry_id', 'revision', 'revised_at', 'reason', 'retcon', 'origin'],
  link: [
    'id',
    'project_id',
    'from_entry',
    'to_entry',
    'relation',
    'attributes',
    'since',
    'until',
    'created_at',
    'updated_at',
    'deleted_at',
  ],
  linkView: ['link', 'end', 'other_id', 'other_name', 'other_kind', 'label'],
  storyEvent: ['entry_id', 'name', 'label', 'sort_key', 'era'],
  storyTimeEra: ['era', 'rank'],
  fieldDefinition: ['name', 'type', 'label', 'required', 'help', 'members', 'kinds'],
  kindDefinition: ['kind', 'label', 'plural', 'fields'],
  relationDefinition: [
    'relation',
    'label',
    'inverse_label',
    'from_kinds',
    'to_kinds',
    'symmetric',
  ],
  entryVersionConflictDetail: [
    'entry_id',
    'presented_revision',
    'current_revision',
    'updated_at',
  ],
  invalidAttributesDetail: ['field'],
} as const;

function expectKeys(value: unknown, expected: readonly string[]): void {
  expect(value).toBeTypeOf('object');
  expect(value).not.toBeNull();
  expect(Object.keys(value as object).sort()).toEqual([...expected].sort());
}

describe('the fixtures exist', () => {
  test('reading one does not throw, so the paths are in step with the backend', () => {
    expect(load<Health>('health').status).toBe('ok');
  });
});

describe('project shapes', () => {
  test('health', () => {
    const health: Health = load('health');
    expectKeys(health, KEYS.health);
    expect(typeof health.version).toBe('string');
  });

  test('project_list', () => {
    const body: ProjectList = load('project_list');
    expectKeys(body, ['projects', 'skipped']);
    expect(body.projects.length).toBeGreaterThan(0);
    for (const summary of body.projects) {
      expectKeys(summary, KEYS.projectSummary);
      expect(typeof summary.chapter_count).toBe('number');
      expect(typeof summary.word_count).toBe('number');
    }
    for (const file of body.skipped) {
      expectKeys(file, KEYS.skippedFile);
    }
  });

  test('project_detail', () => {
    const body: ProjectDetail = load('project_detail');
    expectKeys(body, ['project', 'documents']);
    expectKeys(body.project, KEYS.projectSummary);
    expect(body.documents.length).toBeGreaterThan(0);
    for (const meta of body.documents) {
      expectKeys(meta, KEYS.documentMeta);
      expect(meta.project_id).toBe(body.project.id);
    }
  });
});

describe('document shapes', () => {
  test('document_list omits content, deliberately', () => {
    const body: DocumentList = load('document_list');
    expectKeys(body, ['documents']);
    for (const meta of body.documents) {
      expectKeys(meta, KEYS.documentMeta);
      expect(meta).not.toHaveProperty('content_json');
    }
  });

  test('document carries content and no text_plain', () => {
    const body: Document = load('document');
    expectKeys(body, KEYS.document);
    expect(body.content_json.type).toBe('doc');
    expect(body).not.toHaveProperty('text_plain');
    for (const heading of body.headings) {
      expectKeys(heading, KEYS.heading);
    }
  });

  test('document_meta, from a rename', () => {
    const body: DocumentMeta = load('document_meta');
    expectKeys(body, KEYS.documentMeta);
    expect(body.deleted_at).toBeNull();
  });

  test('the deleted list is the one place deleted_at is not null (D22)', () => {
    const body: DocumentList = load('document_list_deleted');
    expectKeys(body, ['documents']);
    expect(body.documents.length).toBeGreaterThan(0);
    for (const meta of body.documents) {
      expectKeys(meta, KEYS.documentMeta);
      expect(typeof meta.deleted_at).toBe('string');
    }
  });

  test('save_result carries the new version and the projection', () => {
    const body: SaveResult = load('save_result');
    expectKeys(body, KEYS.saveResult);
    expect(body.version).toBeGreaterThan(1);
    expect(typeof body.word_count).toBe('number');
    for (const heading of body.headings) {
      expectKeys(heading, KEYS.heading);
      expect(typeof heading.level).toBe('number');
      expect(typeof heading.ordinal).toBe('number');
    }
  });

  test('outline spans chapters', () => {
    const body: Outline = load('outline');
    expectKeys(body, ['project_id', 'chapters']);
    expect(body.chapters.length).toBeGreaterThan(1);
    for (const chapter of body.chapters) {
      expectKeys(chapter, KEYS.outlineChapter);
      for (const heading of chapter.headings) {
        expectKeys(heading, KEYS.heading);
      }
    }
  });
});

describe('anchor shapes (P2-7, D21)', () => {
  test('an anchor the resolver is happy with', () => {
    const body: Anchor = load('anchor');
    expectKeys(body, KEYS.anchor);
    expect(body.status).toBe('ok');
    expect(body.suggestion).toBeNull();
    expect(body.quote.length).toBeGreaterThan(0);
    expect(body.to_pos).toBeGreaterThan(body.from_pos);
  });

  test('a save carries back the anchors it moved, with their suggestions', () => {
    const body: SaveResult = load('save_result_anchors');
    expectKeys(body, KEYS.saveResult);
    expect(body.anchors.length).toBeGreaterThan(0);

    for (const moved of body.anchors) {
      expectKeys(moved, KEYS.anchor);
      expect(moved.status).toBe('stale');
      expect(moved.suggestion).not.toBeNull();
      expectKeys(moved.suggestion, KEYS.anchorSuggestion);
    }
  });

  test('a save that moved nothing sends an empty list, not an absent field', () => {
    const body: SaveResult = load('save_result');
    expect(body.anchors).toEqual([]);
  });

  test('the project list is every anchor, whatever its status', () => {
    const body: AnchorList = load('anchor_list');
    expectKeys(body, ['anchors']);
    expect(body.anchors.length).toBeGreaterThan(0);
    for (const anchor of body.anchors) {
      expectKeys(anchor, KEYS.anchor);
      expect(['ok', 'stale', 'orphaned']).toContain(anchor.status);
    }
  });
});

describe('snapshot shapes (P2-3, D23)', () => {
  test('a capture answers with the snapshot it wrote', () => {
    const body: SnapshotCapture = load('snapshot_capture');
    expectKeys(body, ['captured', 'snapshot']);
    expect(body.captured).toBe(true);
    expectKeys(body.snapshot, KEYS.snapshotMeta);
    expect(body.snapshot?.reason).toBe('manual');
    expect(body.snapshot?.label).toBe('before the rewrite');
  });

  test('the history carries no content, deliberately', () => {
    const body: SnapshotList = load('snapshot_list');
    expectKeys(body, ['snapshots']);
    expect(body.snapshots.length).toBeGreaterThan(0);
    for (const meta of body.snapshots) {
      expectKeys(meta, KEYS.snapshotMeta);
      expect(meta).not.toHaveProperty('content_json');
      expect(meta.size_bytes).toBeGreaterThan(0);
    }
  });

  test('one snapshot read back does carry it — that is what a preview is', () => {
    const body: Snapshot = load('snapshot');
    expectKeys(body, KEYS.snapshot);
    expect(body.content_json.type).toBe('doc');
  });
});

describe('markdown (P2-13, P2-14)', () => {
  test('an import answers with the chapters it made and what it could not keep', () => {
    const body: MarkdownImport = load('markdown_import');
    expectKeys(body, ['documents', 'dropped']);
    expect(body.documents.length).toBeGreaterThan(0);
    for (const meta of body.documents) {
      expectKeys(meta, KEYS.documentMeta);
    }
  });

  test('a dropped element says what it was, where, and what became of it', () => {
    const body: MarkdownImport = load('markdown_import');
    expect(body.dropped.length).toBeGreaterThan(0);
    for (const notice of body.dropped) {
      expectKeys(notice, KEYS.importNotice);
      expect(notice.line).toBeGreaterThan(0);
      expect(notice.detail).not.toHaveLength(0);
    }
  });

  test('the two exports have no fixture, because they are not JSON', () => {
    // Section 2, ruling 9: an export is `text/markdown`, so there is no wire shape for this
    // suite to type-check. Written down here rather than left as a gap somebody fills in later
    // by adding one — the body is asserted in `server/tests/test_markdown_routes.py`.
    expect(() => load('markdown_export')).toThrow(/shared fixture not found/);
  });
});

describe('the error envelope', () => {
  test('a not-found', () => {
    const body: ErrorResponse = load('error_not_found');
    expectKeys(body, ['error']);
    expectKeys(body.error, KEYS.errorBody);
    expect(body.error.code).toBe('document_not_found');
    expect(body.error.detail).toBeNull();
  });

  test('a validation failure', () => {
    const body: ErrorResponse = load('error_validation');
    expectKeys(body.error, KEYS.errorBody);
    expect(body.error.code).toBe('validation_error');
  });

  test('a version conflict carries what the editor needs to offer a reload (D19)', () => {
    const body: ErrorResponse = load('error_version_conflict');
    expectKeys(body.error, KEYS.errorBody);
    expect(body.error.code).toBe('version_conflict');

    const detail = body.error.detail as VersionConflictDetail;
    expectKeys(detail, KEYS.versionConflictDetail);
    expect(detail.current_version).toBeGreaterThan(detail.presented_version);
  });

  test('a refused reorder says which way the list failed to describe the project (P2-2)', () => {
    const body: ErrorResponse = load('error_reorder_mismatch');
    expectKeys(body.error, KEYS.errorBody);
    expect(body.error.code).toBe('reorder_mismatch');

    const detail = body.error.detail as ReorderMismatchDetail;
    expectKeys(detail, KEYS.reorderMismatchDetail);
    expect(detail.missing.length).toBeGreaterThan(0);
  });
});

describe('the bible schema (P3-11, D26)', () => {
  test('the definition carries the kinds, their fields, and the relation vocabulary', () => {
    const body: BibleSchema = load('bible_schema');
    expectKeys(body, ['field_types', 'kinds', 'relations']);
    expect(body.kinds).toHaveLength(7);
    expect(body.relations).toHaveLength(12);
  });

  test('every field type the server declares has a renderer name on this side', () => {
    // The closed-list half D26 asks for, on the client (P3-5). A seventh type added to the
    // server fails here rather than rendering nothing in a form.
    const body: BibleSchema = load('bible_schema');
    expect([...body.field_types].sort()).toEqual([...Object.values(FIELD_TYPES)].sort());
    for (const type of body.field_types) {
      expect(isFieldType(type)).toBe(true);
    }
  });

  test('a field carries every key whatever its type, so the renderer branches on type alone', () => {
    const body: BibleSchema = load('bible_schema');
    const seen = new Set<string>();
    for (const kind of body.kinds) {
      expectKeys(kind, KEYS.kindDefinition);
      expect(kind.fields.length).toBeGreaterThan(0);
      for (const field of kind.fields) {
        expectKeys(field, KEYS.fieldDefinition);
        expect(isFieldType(field.type)).toBe(true);
        seen.add(field.type);
        expect(field.members.length > 0).toBe(field.type === FIELD_TYPES.enum);
        expect(field.kinds.length > 0).toBe(field.type === FIELD_TYPES.entryRef);
      }
    }
    // All six reach the wire, so P3-13's form has something to render for each.
    expect([...seen].sort()).toEqual([...Object.values(FIELD_TYPES)].sort());
  });

  test('a relation says which kinds it joins and whether it is symmetric', () => {
    const body: BibleSchema = load('bible_schema');
    for (const relation of body.relations) {
      expectKeys(relation, KEYS.relationDefinition);
      expect(relation.from_kinds.length).toBeGreaterThan(0);
      expect(relation.to_kinds.length).toBeGreaterThan(0);
      expect(typeof relation.symmetric).toBe('boolean');
    }
  });

  test('the seven kinds are read from the wire and are nowhere in this codebase', () => {
    // D26 stated as a test: the client knows the *shape* of a kind and never its members.
    const body: BibleSchema = load('bible_schema');
    const kinds = body.kinds.map((kind) => kind.kind);
    expect(new Set(kinds).size).toBe(kinds.length);
    expect(kinds).toContain('character');
  });
});

describe('entry shapes (P3-9, D25 – D27)', () => {
  test('an entry is one record whatever its kind', () => {
    const body: Entry = load('entry');
    expectKeys(body, KEYS.entry);
    expect(body.revision).toBe(1);
    expect(body.deleted_at).toBeNull();
    expect(body.needs_review).toBe(false);
  });

  test('the list carries live counts for every kind, unfiltered', () => {
    const body: EntryList = load('entry_list');
    expectKeys(body, ['entries', 'counts', 'truncated']);
    expect(body.entries.length).toBeGreaterThan(0);
    for (const entry of body.entries) {
      expectKeys(entry, KEYS.entry);
    }
    expect(Object.keys(body.counts)).toHaveLength(7);
    expect(body.truncated).toBe(false);
  });

  test('the deleted list is the one place an entry deleted_at is not null (D25)', () => {
    const body: EntryList = load('entry_list_deleted');
    expect(body.entries.length).toBeGreaterThan(0);
    for (const entry of body.entries) {
      expectKeys(entry, KEYS.entry);
      expect(typeof entry.deleted_at).toBe('string');
    }
  });

  test('one entry comes with its citations, its link count, and where it sits', () => {
    const body: EntryDetail = load('entry_detail');
    expectKeys(body, ['entry', 'citations', 'link_count', 'narrative_position']);
    expectKeys(body.entry, KEYS.entry);
    expect(body.link_count).toBeGreaterThan(0);
    expectKeys(body.narrative_position, KEYS.narrativePosition);
    for (const citation of body.citations) {
      expectKeys(citation, KEYS.citation);
      expectKeys(citation.anchor, KEYS.anchor);
    }
  });

  test('a write says what it flagged and which fields moved (D27)', () => {
    const body: EntryWriteResult = load('entry_write_result');
    expectKeys(body, ['entry', 'revision', 'retcon', 'flagged', 'changed_fields']);
    expect(body.retcon).toBe(true);
    expect(body.changed_fields).toEqual(['name']);
    expect(body.flagged.length).toBeGreaterThan(0);
  });

  test('history is metadata only, newest first, complete from creation', () => {
    const body: RevisionList = load('entry_revision_list');
    expectKeys(body, ['revisions']);
    expect(body.revisions.map((meta) => meta.revision)).toEqual([2, 1]);
    for (const meta of body.revisions) {
      expectKeys(meta, KEYS.revisionMeta);
      expect(meta).not.toHaveProperty('state');
    }
  });

  test('one revision carries the state it recorded, and no review flag with it', () => {
    const body: EntryRevision = load('entry_revision');
    expectKeys(body, ['meta', 'state']);
    expectKeys(body.meta, KEYS.revisionMeta);
    expect(body.state.name).toBe('Marlow');
    expect(body.state).not.toHaveProperty('needs_review');
  });
});

describe('link shapes (P3-10, ruling 7)', () => {
  test('a link is one row with its bounds', () => {
    const body: Link = load('link');
    expectKeys(body, KEYS.link);
    expect(body.since).toBe('the first voyage');
    expect(body.until).toBeNull();
    expect(body.deleted_at).toBeNull();
  });

  test('the project list is every live link', () => {
    const body: LinkList = load('link_list');
    expectKeys(body, ['links']);
    expect(body.links.length).toBeGreaterThan(0);
    for (const link of body.links) {
      expectKeys(link, KEYS.link);
    }
  });

  test("an entry's links say which end it is on and how that end reads", () => {
    const body: EntryLinks = load('entry_links');
    expectKeys(body, ['links']);
    expect(body.links.length).toBeGreaterThan(0);
    for (const view of body.links) {
      expectKeys(view, KEYS.linkView);
      expectKeys(view.link, KEYS.link);
      expect([LINK_ENDS.from, LINK_ENDS.to]).toContain(view.end);
      expect(view.other_name).not.toHaveLength(0);
    }
  });
});

describe('citation shapes (P3-7, P3-10)', () => {
  test('a citation carries the anchor as it reads now, status and all', () => {
    const body: Citation = load('citation');
    expectKeys(body, KEYS.citation);
    expectKeys(body.anchor, KEYS.anchor);
    // The fixture cites the anchor a later save broke, so the client is drawn against the case
    // that matters: the passage behind this entry has been rewritten.
    expect(body.anchor.status).toBe('stale');
    expect(body.role).toBe(CITATION_ROLES.mention);
  });

  test('an uncite answers with a count, and zero is an ordinary answer', () => {
    const body: CitationRemoved = load('citation_removed');
    expectKeys(body, ['removed']);
    expect(body.removed).toBeGreaterThanOrEqual(0);
  });

  test('the reverse view says which entries speak for an anchor', () => {
    const body: AnchorEntries = load('anchor_entries');
    expectKeys(body, ['entries']);
    for (const citing of body.entries) {
      expectKeys(citing, KEYS.citingEntry);
    }
  });

  test('Add to bible answers with all three, and the server derived the quote', () => {
    const body: EntryFromRange = load('entry_from_range');
    expectKeys(body, ['entry', 'anchor', 'role']);
    expectKeys(body.entry, KEYS.entry);
    expectKeys(body.anchor, KEYS.anchor);
    expect(body.anchor.quote.length).toBeGreaterThan(0);
    expect(body.role).toBe(CITATION_ROLES.source);
  });
});

describe('story-time (P3-10, D28)', () => {
  test('the order and the unplaced partition the events', () => {
    const body: StoryTime = load('storytime');
    expectKeys(body, ['order', 'unplaced', 'contradictions', 'eras']);
    for (const event of [...body.order, ...body.unplaced]) {
      expectKeys(event, KEYS.storyEvent);
    }
    const ids = [...body.order, ...body.unplaced].map((event) => event.entry_id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test('an event with neither an edge nor a key is unplaced, not ordered arbitrarily (D9)', () => {
    const body: StoryTime = load('storytime');
    expect(body.unplaced.length).toBeGreaterThan(0);
    for (const event of body.unplaced) {
      expect(event.sort_key).toBeNull();
    }
  });

  test('an era ranks by the least key among its members, and may have none', () => {
    const body: StoryTime = load('storytime');
    expect(body.eras.length).toBeGreaterThan(0);
    for (const era of body.eras) {
      expectKeys(era, KEYS.storyTimeEra);
    }
  });
});

describe('the bible envelope', () => {
  test("an entry conflict carries what the form needs to offer a reload (D19, ruling 3)", () => {
    const body: ErrorResponse = load('error_entry_version_conflict');
    expectKeys(body.error, KEYS.errorBody);
    expect(body.error.code).toBe(ERROR_CODES.entryVersionConflict);

    const detail = body.error.detail as EntryVersionConflictDetail;
    expectKeys(detail, KEYS.entryVersionConflictDetail);
    expect(detail.current_revision).toBeGreaterThan(detail.presented_revision);
  });

  test('a refused attribute names the input rather than rejecting the form (D26)', () => {
    const body: ErrorResponse = load('error_invalid_attributes');
    expectKeys(body.error, KEYS.errorBody);
    expect(body.error.code).toBe(ERROR_CODES.invalidAttributes);

    const detail = body.error.detail as InvalidAttributesDetail;
    expectKeys(detail, KEYS.invalidAttributesDetail);
    expect(detail.field).toBe('eye_colour');
  });
});
