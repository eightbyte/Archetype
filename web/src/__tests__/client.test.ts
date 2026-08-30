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
