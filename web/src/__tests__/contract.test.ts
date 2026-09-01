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
  AnchorList,
  Document,
  DocumentList,
  DocumentMeta,
  ErrorResponse,
  Health,
  Outline,
  ProjectDetail,
  ProjectList,
  ReorderMismatchDetail,
  SaveResult,
  Snapshot,
  SnapshotCapture,
  SnapshotList,
  VersionConflictDetail,
} from '../api/types';
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
