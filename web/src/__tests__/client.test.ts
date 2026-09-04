/**
 * P1-8 — the typed API client.
 *
 * Against a stubbed `fetch`, because what is under test is the client's own behaviour: the URLs
 * and bodies it sends, and what it makes of a failing response. The flows that use the client are
 * tested against the hand-written fake instead (see `ProjectList.test.tsx`).
 */

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ApiError, NetworkError, createApiClient } from '../api';
import { emptyDocument } from '../editor/projection';

interface Sent {
  url: string;
  method: string;
  body: unknown;
}

let sent: Sent[] = [];

function stubFetch(responder: (request: Sent) => Response | Promise<Response>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const request: Sent = {
        url,
        method: init.method ?? 'GET',
        body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
      };
      sent.push(request);
      return responder(request);
    }),
  );
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  sent = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the requests it sends', () => {
  test('listing projects is a plain GET', async () => {
    stubFetch(() => json({ projects: [], skipped: [] }));

    await createApiClient().listProjects();

    expect(sent).toEqual([{ url: '/api/projects', method: 'GET', body: undefined }]);
  });

  test('creating a project posts the title', async () => {
    stubFetch(() => json({ project: {}, documents: [] }));

    await createApiClient().createProject('The Long Road');

    expect(sent[0]).toEqual({
      url: '/api/projects',
      method: 'POST',
      body: { title: 'The Long Road' },
    });
  });

  test('saving content sends content_json and the version (P1-6)', async () => {
    stubFetch(() =>
      json({
        document_id: 'doc_1',
        version: 3,
        word_count: 0,
        headings: [],
        updated_at: '2026-01-01T00:00:00Z',
      }),
    );
    const content = emptyDocument();

    const result = await createApiClient().saveDocumentContent('doc_1', content, 2);

    expect(sent[0]).toEqual({
      url: '/api/documents/doc_1/content',
      method: 'PUT',
      body: { content_json: content, version: 2 },
    });
    expect(result.version).toBe(3);
  });

  test('ids are escaped rather than pasted into the path', async () => {
    stubFetch(() => json({}));

    await createApiClient().getDocument('doc_/../secret');

    expect(sent[0]?.url).toBe('/api/documents/doc_%2F..%2Fsecret');
  });

  test('a base url is honoured, for a client pointed somewhere else', async () => {
    stubFetch(() => json({ status: 'ok', version: '0.1.0' }));

    await createApiClient('http://127.0.0.1:8787').health();

    expect(sent[0]?.url).toBe('http://127.0.0.1:8787/api/health');
  });
});

describe('what it makes of a failure', () => {
  test('the envelope becomes an ApiError with its code', async () => {
    stubFetch(() =>
      json({ error: { code: 'document_not_found', message: 'no document', detail: null } }, 404),
    );

    await expect(createApiClient().getDocument('doc_1')).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      code: 'document_not_found',
      message: 'no document',
    });
  });

  test('a 409 is recognisable and carries the current version (D19)', async () => {
    stubFetch(() =>
      json(
        {
          error: {
            code: 'version_conflict',
            message: 'stale',
            detail: {
              document_id: 'doc_1',
              presented_version: 2,
              current_version: 5,
              updated_at: '2026-01-01T00:00:00Z',
            },
          },
        },
        409,
      ),
    );

    const failure = await createApiClient()
      .saveDocumentContent('doc_1', emptyDocument(), 2)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.isVersionConflict).toBe(true);
    expect(apiError.versionConflict).toEqual({
      document_id: 'doc_1',
      presented_version: 2,
      current_version: 5,
      updated_at: '2026-01-01T00:00:00Z',
    });
  });

  test('a body that is not an envelope still yields a usable error', async () => {
    stubFetch(() => new Response('<html>502 Bad Gateway</html>', { status: 502 }));

    const failure = (await createApiClient()
      .listProjects()
      .catch((error: unknown) => error)) as ApiError;

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(502);
    expect(failure.code).toBe('unexpected_response');
    expect(failure.message).toContain('502');
  });

  test('an unreachable server is a NetworkError, not a parse error', async () => {
    stubFetch(() => {
      throw new TypeError('Failed to fetch');
    });

    const failure = await createApiClient()
      .health()
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(NetworkError);
    expect((failure as NetworkError).cause).toBeInstanceOf(TypeError);
  });

  test('an abort is passed through as an abort', async () => {
    stubFetch(() => {
      throw new DOMException('aborted', 'AbortError');
    });

    const failure = await createApiClient()
      .health(new AbortController().signal)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(DOMException);
    expect((failure as DOMException).name).toBe('AbortError');
  });

  test('a version conflict on some other error code reads as absent', () => {
    const error = new ApiError(404, 'document_not_found', 'gone', null);

    expect(error.isVersionConflict).toBe(false);
    expect(error.versionConflict).toBeNull();
  });
});

describe('the bible requests it sends (P3-9 … P3-11)', () => {
  test('the served definition has no project in its path', async () => {
    // The one route in the API with no project scope: the vocabulary is the product's, not a
    // manuscript's (D26).
    stubFetch(() => json({ field_types: [], kinds: [], relations: [] }));

    await createApiClient().getBibleSchema();

    expect(sent[0]?.url).toBe('/api/bible/schema');
  });

  test('an absent filter is absent from the URL, not sent empty', async () => {
    // The routes read a missing parameter as "no filter"; `?kind=` would be a request for the
    // kind named by the empty string, which is a refusal rather than everything.
    stubFetch(() => json({ entries: [], counts: {}, truncated: false }));
    const client = createApiClient();

    await client.listEntries('prj_1');
    await client.listEntries('prj_1', { kind: 'character', q: 'kurtz' });

    expect(sent[0]?.url).toBe('/api/projects/prj_1/entries');
    expect(sent[1]?.url).toBe('/api/projects/prj_1/entries?kind=character&q=kurtz');
  });

  test('a false filter is a filter, and survives', async () => {
    // `needs_review=false` asks for the entries that are *not* flagged, which is a different
    // question from asking for all of them.
    stubFetch(() => json({ entries: [], counts: {}, truncated: false }));

    await createApiClient().listEntries('prj_1', { needs_review: false });

    expect(sent[0]?.url).toBe('/api/projects/prj_1/entries?needs_review=false');
  });

  test('an update presents the revision, and omits what it is not changing', async () => {
    // The absent-versus-empty distinction the server reads through `model_fields_set`: a request
    // that does not mention `summary` keeps it, and one that sends `attributes: {}` clears them.
    stubFetch(() =>
      json({ entry: {}, revision: 2, retcon: false, flagged: [], changed_fields: [] }),
    );

    await createApiClient().updateEntry('ent_1', { revision: 1, name: 'Kurtz', attributes: {} });

    expect(sent[0]).toEqual({
      url: '/api/entries/ent_1',
      method: 'PUT',
      body: { revision: 1, name: 'Kurtz', attributes: {} },
    });
  });

  test('a restore presents the entry’s current revision, not the one being restored', async () => {
    stubFetch(() =>
      json({ entry: {}, revision: 4, retcon: false, flagged: [], changed_fields: [] }),
    );

    await createApiClient().restoreEntryRevision('ent_1', 2, 3);

    expect(sent[0]).toEqual({
      url: '/api/entries/ent_1/revisions/2/restore',
      method: 'POST',
      body: { revision: 3 },
    });
  });

  test('a link is posted as the sentence reads: from, relation, to', async () => {
    stubFetch(() => json({}));

    await createApiClient().createLink('prj_1', {
      from_entry: 'ent_1',
      relation: 'member_of',
      to_entry: 'ent_2',
      since: 'the first voyage',
    });

    expect(sent[0]?.body).toEqual({
      from_entry: 'ent_1',
      relation: 'member_of',
      to_entry: 'ent_2',
      since: 'the first voyage',
    });
  });

  test('an uncite without a role names none, and with one names it', async () => {
    stubFetch(() => json({ removed: 1 }));
    const client = createApiClient();

    await client.unciteAnchor('ent_1', 'anc_1');
    await client.unciteAnchor('ent_1', 'anc_1', 'mention');

    expect(sent[0]?.url).toBe('/api/entries/ent_1/citations/anc_1');
    expect(sent[1]?.url).toBe('/api/entries/ent_1/citations/anc_1?role=mention');
  });

  test('Add to bible sends a range and a version, and never a quote', async () => {
    stubFetch(() => json({ entry: {}, anchor: {}, role: 'source' }));

    await createApiClient().createEntryFromRange('doc_1', {
      from_pos: 5,
      to_pos: 21,
      version: 3,
      kind: 'character',
      name: 'Marlow',
    });

    expect(sent[0]?.url).toBe('/api/documents/doc_1/entries');
    expect(sent[0]?.body).toEqual({
      from_pos: 5,
      to_pos: 21,
      version: 3,
      kind: 'character',
      name: 'Marlow',
    });
  });
});

describe('what it makes of the bible’s refusals', () => {
  test('an entry conflict has its own code and carries what a reload needs', async () => {
    // Not `version_conflict`: the editor offers to reload a chapter and the entry form offers to
    // reload a record, and one code for both would make that a branch on the request in flight.
    stubFetch(() =>
      json(
        {
          error: {
            code: 'entry_version_conflict',
            message: 'entry ent_1 is at revision 2, not 1',
            detail: {
              entry_id: 'ent_1',
              presented_revision: 1,
              current_revision: 2,
              updated_at: '2026-01-01T00:00:00Z',
            },
          },
        },
        409,
      ),
    );

    const failure = await createApiClient()
      .updateEntry('ent_1', { revision: 1, name: 'Kurtz' })
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const error = failure as ApiError;
    expect(error.isEntryVersionConflict).toBe(true);
    // The document conflict's reader must not answer for this one.
    expect(error.isVersionConflict).toBe(false);
    expect(error.versionConflict).toBeNull();
    expect(error.entryVersionConflict?.current_revision).toBe(2);
  });

  test('a refused attribute names the field the form has to point at', async () => {
    stubFetch(() =>
      json(
        {
          error: {
            code: 'invalid_attributes',
            message: "character does not declare 'eye_colour'",
            detail: { field: 'eye_colour' },
          },
        },
        422,
      ),
    );

    const failure = (await createApiClient()
      .createEntry('prj_1', { kind: 'character', name: 'Kurtz' })
      .catch((error: unknown) => error)) as ApiError;

    expect(failure.invalidAttributes?.field).toBe('eye_colour');
  });

  test('a conflict of the wrong kind reads as absent rather than as a guess', () => {
    const error = new ApiError(409, 'duplicate_link', 'that link already exists', {
      link_id: 'lnk_1',
    });

    expect(error.entryVersionConflict).toBeNull();
    expect(error.invalidAttributes).toBeNull();
  });
});
