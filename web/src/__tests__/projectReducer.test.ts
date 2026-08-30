/**
 * P1-9 — the project reducer, tested apart from React.
 *
 * Its job is to keep the chapter list and the whole-manuscript outline true without refetching
 * either on every keystroke, so the cases worth testing are the ones where a save, a rename, or
 * a new chapter has to be reflected in two places at once.
 */

import { describe, expect, test } from 'vitest';
import type { Document, ProjectDetail, SaveResult } from '../api/types';
import {
  headingsOf,
  INITIAL_PROJECT_STATE,
  projectReducer,
  wordCountOf,
} from '../state/projectReducer';
import type { ProjectState } from '../state/projectReducer';

const DETAIL: ProjectDetail = {
  project: {
    id: 'prj_1',
    title: 'The Long Road',
    chapter_count: 2,
    word_count: 30,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  documents: [
    meta('doc_1', 'Chapter 1', 0, 20),
    meta('doc_2', 'Chapter 2', 1, 10),
  ],
};

const CHAPTERS = [
  { document_id: 'doc_1', title: 'Chapter 1', order_index: 0, word_count: 20, headings: [{ level: 1, text: 'One', ordinal: 0 }] },
  { document_id: 'doc_2', title: 'Chapter 2', order_index: 1, word_count: 10, headings: [] },
];

function meta(id: string, title: string, order: number, words: number) {
  return {
    id,
    project_id: 'prj_1',
    order_index: order,
    title,
    kind: 'chapter',
    headings: [],
    word_count: words,
    version: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

function loaded(): ProjectState {
  return projectReducer(INITIAL_PROJECT_STATE, {
    type: 'loaded',
    detail: DETAIL,
    chapters: CHAPTERS,
  });
}

describe('loading', () => {
  test('a loaded project holds its identity, chapters, and outline', () => {
    const state = loaded();
    expect(state.status).toBe('ready');
    expect(state.project?.title).toBe('The Long Road');
    expect(state.documents.map((doc) => doc.id)).toEqual(['doc_1', 'doc_2']);
    expect(state.chapters).toHaveLength(2);
  });

  test('a failed load says why and keeps whatever was on screen', () => {
    const state = projectReducer(loaded(), { type: 'load-failed', message: 'no such project' });
    expect(state.status).toBe('failed');
    expect(state.error).toBe('no such project');
  });
});

describe('a save landing', () => {
  test('updates the chapter in both the document list and the outline', () => {
    const result: SaveResult = {
      document_id: 'doc_1',
      version: 2,
      word_count: 55,
      headings: [{ level: 1, text: 'Arrival', ordinal: 0 }],
      updated_at: '2026-01-02T00:00:00Z',
    };
    const state = projectReducer(loaded(), { type: 'document-saved', result });

    expect(state.documents[0]?.word_count).toBe(55);
    expect(state.documents[0]?.version).toBe(2);
    expect(state.chapters[0]?.headings).toEqual([{ level: 1, text: 'Arrival', ordinal: 0 }]);
    // Untouched chapters stay untouched.
    expect(state.chapters[1]?.word_count).toBe(10);
  });

  test("moves the project's own timestamp and total, which is what the picker sorts on", () => {
    const state = projectReducer(loaded(), {
      type: 'document-saved',
      result: {
        document_id: 'doc_1',
        version: 2,
        word_count: 55,
        headings: [],
        updated_at: '2026-01-02T00:00:00Z',
      },
    });

    expect(state.project?.updated_at).toBe('2026-01-02T00:00:00Z');
    expect(state.project?.word_count).toBe(65);
  });
});

describe('a chapter being added', () => {
  test('appends it in order and counts it', () => {
    const created: Document = {
      ...meta('doc_3', 'Chapter 3', 2, 0),
      content_json: { type: 'doc', content: [{ type: 'paragraph' }] },
    };
    const state = projectReducer(loaded(), { type: 'document-created', document: created });

    expect(state.documents.map((doc) => doc.id)).toEqual(['doc_1', 'doc_2', 'doc_3']);
    expect(state.chapters.map((chapter) => chapter.document_id)).toEqual([
      'doc_1',
      'doc_2',
      'doc_3',
    ]);
    expect(state.project?.chapter_count).toBe(3);
    expect(state.project?.word_count).toBe(30);
  });
});

describe('a rename', () => {
  test('changes the title in the list and the outline together', () => {
    const state = projectReducer(loaded(), {
      type: 'document-renamed',
      documentId: 'doc_2',
      title: 'Departure',
    });
    expect(state.documents[1]?.title).toBe('Departure');
    expect(state.chapters[1]?.title).toBe('Departure');
  });
});

describe('derivations', () => {
  test('the manuscript word count is the sum of its chapters', () => {
    expect(wordCountOf(CHAPTERS)).toBe(30);
  });

  test('every heading in the manuscript comes back in reading order', () => {
    expect(headingsOf(CHAPTERS)).toEqual([{ level: 1, text: 'One', ordinal: 0 }]);
  });
});
