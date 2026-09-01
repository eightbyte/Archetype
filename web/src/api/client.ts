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
  Anchor,
  AnchorList,
  Document,
  DocumentList,
  DocumentMeta,
  Health,
  Outline,
  ProjectDetail,
  ProjectList,
  ProseMirrorDocument,
  ReorderMismatchDetail,
  SaveResult,
  Snapshot,
  SnapshotCapture,
  SnapshotList,
  SnapshotReasonIn,
  VersionConflictDetail,
} from './types';
import { ERROR_CODES } from './types';

/**
 * A range being anchored, and the document version it was selected against (P2-7).
 *
 * The client sends *where*, never *what*: the server reads the quote and its context out of the
 * stored content, so an anchor can never disagree with the manuscript. A range against a stale
 * version is refused with the same `409` a save is.
 */
export interface AnchorRange {
  from_pos: number;
  to_pos: number;
  version: number;
}

/**
 * What a `PATCH /api/anchors/{aid}` may change.
 *
 * A re-link carries all three of `from_pos`, `to_pos`, and `version` or none of them: two of
 * the three is a client that has lost track of which version it is looking at, and guessing the
 * third is how an anchor ends up over text nobody looked at (D19). The server refuses the
 * half-formed version with a `422`; this type is shaped so it cannot be built.
 */
export interface AnchorPatch {
  range?: AnchorRange;
  label?: string;
}

/** Everything the app can ask the server for. The fake implements exactly this. */
export interface ApiClient {
  health(signal?: AbortSignal): Promise<Health>;
  listProjects(signal?: AbortSignal): Promise<ProjectList>;
  createProject(title: string, signal?: AbortSignal): Promise<ProjectDetail>;
  getProject(projectId: string, signal?: AbortSignal): Promise<ProjectDetail>;
  listDocuments(projectId: string, signal?: AbortSignal): Promise<DocumentList>;
  listDeletedDocuments(projectId: string, signal?: AbortSignal): Promise<DocumentList>;
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
  /** The complete ordered list of live chapters. A partial one is refused with a `409`. */
  reorderDocuments(
    projectId: string,
    documentIds: string[],
    signal?: AbortSignal,
  ): Promise<DocumentList>;
  deleteDocument(documentId: string, signal?: AbortSignal): Promise<DocumentMeta>;
  restoreDocument(documentId: string, signal?: AbortSignal): Promise<DocumentMeta>;

  listDocumentAnchors(documentId: string, signal?: AbortSignal): Promise<AnchorList>;
  listProjectAnchors(
    projectId: string,
    status?: string,
    signal?: AbortSignal,
  ): Promise<AnchorList>;
  createAnchor(
    documentId: string,
    range: AnchorRange,
    label?: string,
    signal?: AbortSignal,
  ): Promise<Anchor>;
  patchAnchor(anchorId: string, patch: AnchorPatch, signal?: AbortSignal): Promise<Anchor>;
  deleteAnchor(anchorId: string, signal?: AbortSignal): Promise<void>;

  listSnapshots(documentId: string, signal?: AbortSignal): Promise<SnapshotList>;
  captureSnapshot(
    documentId: string,
    reason: SnapshotReasonIn,
    label?: string,
    signal?: AbortSignal,
  ): Promise<SnapshotCapture>;
  getSnapshot(snapshotId: string, signal?: AbortSignal): Promise<Snapshot>;
  restoreSnapshot(snapshotId: string, version: number, signal?: AbortSignal): Promise<SaveResult>;
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

  /** True when a reorder did not describe the project as it is now (P2-2). */
  get isReorderMismatch(): boolean {
    return this.code === ERROR_CODES.reorderMismatch;
  }

  /** The `409` payload of a refused reorder, when this is one. */
  get reorderMismatch(): ReorderMismatchDetail | null {
    if (!this.isReorderMismatch || !isRecord(this.detail)) {
      return null;
    }
    const missing = stringsOrNull(this.detail['missing']);
    const unexpected = stringsOrNull(this.detail['unexpected']);
    const duplicated = stringsOrNull(this.detail['duplicated']);
    if (!missing || !unexpected || !duplicated) {
      return null;
    }
    return { missing, unexpected, duplicated };
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
    // A `204` has no body at all, so parsing one would throw where nothing went wrong. The
    // caller's type is `void` in that case, and this is the one place that knows it.
    if (response.status === 204) {
      return undefined as T;
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

    listDeletedDocuments: (projectId, signal) =>
      request(
        'GET',
        `/api/projects/${encodeURIComponent(projectId)}/documents/deleted`,
        undefined,
        signal,
      ),
    reorderDocuments: (projectId, documentIds, signal) =>
      request(
        'PUT',
        `/api/projects/${encodeURIComponent(projectId)}/documents/order`,
        { document_ids: documentIds },
        signal,
      ),
    deleteDocument: (documentId, signal) =>
      request('DELETE', `/api/documents/${encodeURIComponent(documentId)}`, undefined, signal),
    restoreDocument: (documentId, signal) =>
      request(
        'POST',
        `/api/documents/${encodeURIComponent(documentId)}/restore`,
        undefined,
        signal,
      ),

    listDocumentAnchors: (documentId, signal) =>
      request(
        'GET',
        `/api/documents/${encodeURIComponent(documentId)}/anchors`,
        undefined,
        signal,
      ),
    listProjectAnchors: (projectId, status, signal) =>
      request(
        'GET',
        `/api/projects/${encodeURIComponent(projectId)}/anchors` +
          (status ? `?status=${encodeURIComponent(status)}` : ''),
        undefined,
        signal,
      ),
    createAnchor: (documentId, range, label, signal) =>
      request(
        'POST',
        `/api/documents/${encodeURIComponent(documentId)}/anchors`,
        { ...range, label: label ?? '' },
        signal,
      ),
    patchAnchor: (anchorId, patch, signal) =>
      request(
        'PATCH',
        `/api/anchors/${encodeURIComponent(anchorId)}`,
        { ...(patch.range ?? {}), ...(patch.label === undefined ? {} : { label: patch.label }) },
        signal,
      ),
    deleteAnchor: (anchorId, signal) =>
      request('DELETE', `/api/anchors/${encodeURIComponent(anchorId)}`, undefined, signal),

    listSnapshots: (documentId, signal) =>
      request(
        'GET',
        `/api/documents/${encodeURIComponent(documentId)}/snapshots`,
        undefined,
        signal,
      ),
    captureSnapshot: (documentId, reason, label, signal) =>
      request(
        'POST',
        `/api/documents/${encodeURIComponent(documentId)}/snapshots`,
        { reason, label: label ?? '' },
        signal,
      ),
    getSnapshot: (snapshotId, signal) =>
      request('GET', `/api/snapshots/${encodeURIComponent(snapshotId)}`, undefined, signal),
    restoreSnapshot: (snapshotId, version, signal) =>
      request(
        'POST',
        `/api/snapshots/${encodeURIComponent(snapshotId)}/restore`,
        { version },
        signal,
      ),
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

function stringsOrNull(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : null;
}
