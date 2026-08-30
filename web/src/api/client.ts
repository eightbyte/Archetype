/**
 * The typed API client (P1-8).
 *
 * One interface, `ApiClient`, with two implementations: this one, which talks to the server, and
 * a hand-written fake in `src/__tests__/fakes/fakeApiClient.ts` that component tests run against.
 * No MSW and no extra dependency — a fake that implements the same interface is enough, and it
 * fails to compile when the interface changes, which a request interceptor would not (outline § 8).
 *
 * Every failure arrives as an `ApiError` carrying the envelope's `code`, so callers branch on a
 * stable name rather than on a status number or an error message. The `409` from the save
 * protocol is the one the editor must handle by name (D19).
 */

import type {
  Document,
  DocumentList,
  DocumentMeta,
  Health,
  Outline,
  ProjectDetail,
  ProjectList,
  ProseMirrorDocument,
  SaveResult,
  VersionConflictDetail,
} from './types';
import { ERROR_CODES } from './types';

/** Everything the app can ask the server for. The fake implements exactly this. */
export interface ApiClient {
  health(signal?: AbortSignal): Promise<Health>;
  listProjects(signal?: AbortSignal): Promise<ProjectList>;
  createProject(title: string, signal?: AbortSignal): Promise<ProjectDetail>;
  getProject(projectId: string, signal?: AbortSignal): Promise<ProjectDetail>;
  listDocuments(projectId: string, signal?: AbortSignal): Promise<DocumentList>;
  createDocument(projectId: string, title?: string, signal?: AbortSignal): Promise<Document>;
  getOutline(projectId: string, signal?: AbortSignal): Promise<Outline>;
  getDocument(documentId: string, signal?: AbortSignal): Promise<Document>;
  saveDocumentContent(
    documentId: string,
    content: ProseMirrorDocument,
    version: number,
    signal?: AbortSignal,
  ): Promise<SaveResult>;
  renameDocument(documentId: string, title: string, signal?: AbortSignal): Promise<DocumentMeta>;
}

/** A failing response, carrying the envelope the server sent. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: unknown;

  constructor(status: number, code: string, message: string, detail: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }

  /** True when a save was refused because the document had moved on (D19). */
  get isVersionConflict(): boolean {
    return this.code === ERROR_CODES.versionConflict;
  }

  /** The `409` payload, when this is one. */
  get versionConflict(): VersionConflictDetail | null {
    if (!this.isVersionConflict || !isRecord(this.detail)) {
      return null;
    }
    const { document_id, presented_version, current_version, updated_at } = this.detail;
    if (
      typeof document_id !== 'string' ||
      typeof presented_version !== 'number' ||
      typeof current_version !== 'number' ||
      typeof updated_at !== 'string'
    ) {
      return null;
    }
    return { document_id, presented_version, current_version, updated_at };
  }
}

/** Thrown when the server could not be reached at all — no response, so no envelope. */
export class NetworkError extends Error {
  readonly cause: unknown;

  constructor(message: string, cause: unknown) {
    super(message);
    this.name = 'NetworkError';
    this.cause = cause;
  }
}

/** Build a client. `baseUrl` exists for tests; in the browser `/api` is proxied to the server. */
export function createApiClient(baseUrl = ''): ApiClient {
  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    const init: RequestInit = { method };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
      init.headers = { 'Content-Type': 'application/json' };
    }
    if (signal) {
      init.signal = signal;
    }

    let response: Response;
    try {
      response = await fetch(`${baseUrl}${path}`, init);
    } catch (error) {
      // An abort is the caller's own doing — it is not a failure to report as one.
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw error;
      }
      throw new NetworkError(`${method} ${path} could not reach the server`, error);
    }

    if (!response.ok) {
      throw await toApiError(method, path, response);
    }
    return (await response.json()) as T;
  }

  return {
    health: (signal) => request('GET', '/api/health', undefined, signal),
    listProjects: (signal) => request('GET', '/api/projects', undefined, signal),
    createProject: (title, signal) => request('POST', '/api/projects', { title }, signal),
    getProject: (projectId, signal) =>
      request('GET', `/api/projects/${encodeURIComponent(projectId)}`, undefined, signal),
    listDocuments: (projectId, signal) =>
      request(
        'GET',
        `/api/projects/${encodeURIComponent(projectId)}/documents`,
        undefined,
        signal,
      ),
    createDocument: (projectId, title, signal) =>
      request(
        'POST',
        `/api/projects/${encodeURIComponent(projectId)}/documents`,
        { title: title ?? null },
        signal,
      ),
    getOutline: (projectId, signal) =>
      request('GET', `/api/projects/${encodeURIComponent(projectId)}/outline`, undefined, signal),
    getDocument: (documentId, signal) =>
      request('GET', `/api/documents/${encodeURIComponent(documentId)}`, undefined, signal),
    saveDocumentContent: (documentId, content, version, signal) =>
      request(
        'PUT',
        `/api/documents/${encodeURIComponent(documentId)}/content`,
        { content_json: content, version },
        signal,
      ),
    renameDocument: (documentId, title, signal) =>
      request('PATCH', `/api/documents/${encodeURIComponent(documentId)}`, { title }, signal),
  };
}

/**
 * Turn a failing response into an `ApiError`.
 *
 * The server's envelope is uniform, but a proxy or a crash can still produce a body that is not
 * one — so a body that does not parse becomes an error that says the status plainly rather than
 * an error about JSON.
 */
async function toApiError(method: string, path: string, response: Response): Promise<ApiError> {
  let envelope: unknown = null;
  try {
    envelope = await response.json();
  } catch {
    envelope = null;
  }

  if (isRecord(envelope)) {
    const body = envelope['error'];
    if (isRecord(body)) {
      const code = body['code'];
      const message = body['message'];
      if (typeof code === 'string' && typeof message === 'string') {
        return new ApiError(response.status, code, message, body['detail'] ?? null);
      }
    }
  }

  return new ApiError(
    response.status,
    'unexpected_response',
    `${method} ${path} returned ${response.status}`,
    null,
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
