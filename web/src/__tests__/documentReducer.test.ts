/**
 * P1-9, P1-10 — the open-document reducer, tested apart from React and apart from timers.
 *
 * This is where the save protocol's client half is specified. The cases that matter are not the
 * happy ones: an edit that arrives while a save is in the air, a `409` that must not be cleared
 * by typing, and a save result for a chapter that is no longer open.
 */

import { describe, expect, test } from 'vitest';
import type { Document, SaveResult, VersionConflictDetail } from '../api/types';
import type { DocumentState } from '../state/documentReducer';
import {
  documentReducer,
  INITIAL_DOCUMENT_STATE,
  isDirty,
  needsFlush,
} from '../state/documentReducer';
import type { ProseMirrorDocument } from '../editor/projection';

function prose(text: string): ProseMirrorDocument {
  return { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] };
}

function withHeading(level: number, text: string): ProseMirrorDocument {
  return {
    type: 'doc',
    content: [{ type: 'heading', attrs: { level }, content: [{ type: 'text', text }] }],
  };
}

function document(overrides: Partial<Document> = {}): Document {
  return {
    id: 'doc_1',
    project_id: 'prj_1',
    order_index: 0,
    title: 'Chapter 1',
    kind: 'chapter',
    content_json: prose('The harbour was grey.'),
    headings: [],
    word_count: 4,
    version: 3,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function opened(overrides: Partial<Document> = {}): DocumentState {
  return documentReducer(INITIAL_DOCUMENT_STATE, {
    type: 'opened',
    document: document(overrides),
  });
}

function saveResult(overrides: Partial<SaveResult> = {}): SaveResult {
  return {
    document_id: 'doc_1',
    version: 4,
    word_count: 4,
    headings: [],
    updated_at: '2026-01-01T00:01:00Z',
    anchors: [],
    ...overrides,
  };
}

const CONFLICT: VersionConflictDetail = {
  document_id: 'doc_1',
  presented_version: 3,
  current_version: 5,
  updated_at: '2026-01-01T00:02:00Z',
};

describe('opening', () => {
  test('a fresh document is ready, clean, and at the server version', () => {
    const state = opened();
    expect(state.status).toBe('ready');
    expect(state.version).toBe(3);
    expect(isDirty(state)).toBe(false);
    expect(state.save.kind).toBe('idle');
  });

  test('requesting a different document clears everything about the last one', () => {
    const dirty = documentReducer(opened(), { type: 'edited', content: prose('More.') });
    const next = documentReducer(dirty, { type: 'open-requested', documentId: 'doc_2' });

    expect(next.status).toBe('loading');
    expect(next.documentId).toBe('doc_2');
    expect(next.content).toBeNull();
    expect(isDirty(next)).toBe(false);
  });

  test('reloading the same document bumps the sequence, so the editor re-seeds', () => {
    const first = opened();
    const again = documentReducer(first, { type: 'opened', document: document() });
    expect(again.sequence).toBe(first.sequence + 1);
  });

  test('a failed load says why and holds no content', () => {
    const state = documentReducer(
      documentReducer(INITIAL_DOCUMENT_STATE, { type: 'open-requested', documentId: 'doc_1' }),
      { type: 'open-failed', message: 'the server could not be reached' },
    );
    expect(state.status).toBe('failed');
    expect(state.loadError).toBe('the server could not be reached');
    expect(state.content).toBeNull();
  });

  test('a heading ordinal asked for at open survives the load', () => {
    const requested = documentReducer(INITIAL_DOCUMENT_STATE, {
      type: 'open-requested',
      documentId: 'doc_1',
      headingOrdinal: 2,
    });
    const loaded = documentReducer(requested, { type: 'opened', document: document() });
    expect(loaded.pendingHeading).toBe(2);
  });
});

describe('editing', () => {
  test('an edit makes the document dirty and says so', () => {
    const state = documentReducer(opened(), { type: 'edited', content: prose('Changed.') });
    expect(isDirty(state)).toBe(true);
    expect(state.save.kind).toBe('unsaved');
  });

  test('an edit re-derives the projection, so the outline moves as the writer types (D18)', () => {
    const state = documentReducer(opened(), {
      type: 'edited',
      content: withHeading(2, 'The Harbour'),
    });
    expect(state.headings).toEqual([{ level: 2, text: 'The Harbour', ordinal: 0 }]);
    expect(state.wordCount).toBe(2);
  });

  test('an edit to a document that is not ready is ignored', () => {
    const loading = documentReducer(INITIAL_DOCUMENT_STATE, {
      type: 'open-requested',
      documentId: 'doc_1',
    });
    expect(documentReducer(loading, { type: 'edited', content: prose('x') })).toBe(loading);
  });
});

describe('saving', () => {
  test('a successful save takes the new version and the server projection (D18)', () => {
    const dirty = documentReducer(opened(), { type: 'edited', content: withHeading(1, 'One') });
    const saving = documentReducer(dirty, { type: 'save-started', revision: dirty.revision });
    const saved = documentReducer(saving, {
      type: 'save-succeeded',
      result: saveResult({ version: 4, word_count: 1, headings: [{ level: 1, text: 'One', ordinal: 0 }] }),
    });

    expect(saved.version).toBe(4);
    expect(saved.wordCount).toBe(1);
    expect(saved.headings).toEqual([{ level: 1, text: 'One', ordinal: 0 }]);
    expect(isDirty(saved)).toBe(false);
    expect(saved.save).toEqual({ kind: 'saved', at: '2026-01-01T00:01:00Z' });
  });

  test('an edit made while a save was in flight leaves the document dirty', () => {
    const dirty = documentReducer(opened(), { type: 'edited', content: prose('First.') });
    const saving = documentReducer(dirty, { type: 'save-started', revision: dirty.revision });
    const editedMidFlight = documentReducer(saving, { type: 'edited', content: prose('Second.') });
    const saved = documentReducer(editedMidFlight, { type: 'save-succeeded', result: saveResult() });

    expect(isDirty(saved)).toBe(true);
    expect(saved.save.kind).toBe('unsaved');
    // ... and the version still moved, so the next save presents the right one.
    expect(saved.version).toBe(4);
  });

  test('a failed save counts its attempts and keeps the content', () => {
    const dirty = documentReducer(opened(), { type: 'edited', content: prose('Kept.') });
    const once = documentReducer(dirty, { type: 'save-failed', message: 'network' });
    const twice = documentReducer(once, { type: 'save-failed', message: 'network' });

    expect(once.save).toEqual({ kind: 'failed', message: 'network', attempt: 1 });
    expect(twice.save).toEqual({ kind: 'failed', message: 'network', attempt: 2 });
    expect(isDirty(twice)).toBe(true);
    expect(twice.content).toEqual(prose('The harbour was grey.'));
  });

  test('a success after failures clears the failure count', () => {
    const failed = documentReducer(
      documentReducer(opened(), { type: 'edited', content: prose('x') }),
      { type: 'save-failed', message: 'network' },
    );
    const saved = documentReducer(
      documentReducer(failed, { type: 'save-started', revision: failed.revision }),
      { type: 'save-succeeded', result: saveResult() },
    );
    expect(saved.save.kind).toBe('saved');
  });
});

describe('a version conflict (D19)', () => {
  test('carries what the writer needs to decide, and nothing is dirty-cleared', () => {
    const dirty = documentReducer(opened(), { type: 'edited', content: prose('Mine.') });
    const conflicted = documentReducer(dirty, { type: 'save-conflicted', detail: CONFLICT });

    expect(conflicted.save).toEqual({ kind: 'conflict', detail: CONFLICT });
    expect(isDirty(conflicted)).toBe(true);
    expect(conflicted.version).toBe(3);
  });

  test('typing more does not clear it — autosave stays stopped until it is answered', () => {
    const conflicted = documentReducer(
      documentReducer(opened(), { type: 'edited', content: prose('Mine.') }),
      { type: 'save-conflicted', detail: CONFLICT },
    );
    const stillTyping = documentReducer(conflicted, { type: 'edited', content: prose('More.') });

    expect(stillTyping.save).toEqual({ kind: 'conflict', detail: CONFLICT });
    expect(isDirty(stillTyping)).toBe(true);
  });

  test('reloading the server copy resolves it', () => {
    const conflicted = documentReducer(
      documentReducer(opened(), { type: 'edited', content: prose('Mine.') }),
      { type: 'save-conflicted', detail: CONFLICT },
    );
    const reloaded = documentReducer(conflicted, {
      type: 'opened',
      document: document({ version: 5, content_json: prose('Theirs.') }),
    });

    expect(reloaded.save.kind).toBe('idle');
    expect(reloaded.version).toBe(5);
    expect(isDirty(reloaded)).toBe(false);
  });

  test('a conflict is not something to flush past', () => {
    const conflicted = documentReducer(
      documentReducer(opened(), { type: 'edited', content: prose('Mine.') }),
      { type: 'save-conflicted', detail: CONFLICT },
    );
    expect(needsFlush(conflicted)).toBe(false);
  });
});

describe('renaming and navigating', () => {
  test('a rename changes the title and nothing about the content', () => {
    const dirty = documentReducer(opened(), { type: 'edited', content: prose('x') });
    const renamed = documentReducer(dirty, { type: 'renamed', title: 'Arrival' });

    expect(renamed.title).toBe('Arrival');
    expect(renamed.version).toBe(dirty.version);
    expect(isDirty(renamed)).toBe(isDirty(dirty));
  });

  test('a jump request is recorded and cleared once', () => {
    const asked = documentReducer(opened(), { type: 'jump-requested', ordinal: 4 });
    expect(asked.pendingHeading).toBe(4);

    const done = documentReducer(asked, { type: 'jump-completed' });
    expect(done.pendingHeading).toBeNull();
    expect(documentReducer(done, { type: 'jump-completed' })).toBe(done);
  });

  test('closing forgets everything', () => {
    const dirty = documentReducer(opened(), { type: 'edited', content: prose('x') });
    expect(documentReducer(dirty, { type: 'closed' })).toEqual(INITIAL_DOCUMENT_STATE);
  });
});

describe('needsFlush', () => {
  test('is false for a clean document and true for a dirty one', () => {
    const clean = opened();
    expect(needsFlush(clean)).toBe(false);
    expect(needsFlush(documentReducer(clean, { type: 'edited', content: prose('x') }))).toBe(true);
  });

  test('is false when nothing is open', () => {
    expect(needsFlush(INITIAL_DOCUMENT_STATE)).toBe(false);
  });
});
