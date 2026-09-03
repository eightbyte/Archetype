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
  AnchorEntries,
  AnchorList,
  BibleSchema,
  Citation,
  CitationRemoved,
  CitationRole,
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
  Health,
  ImportMode,
  InvalidAttributesDetail,
  Link,
  LinkList,
  MarkdownImport,
  Outline,
  ProjectDetail,
  ProjectList,
  ProseMirrorDocument,
  ReorderMismatchDetail,
  RevisionList,
  SaveResult,
  Snapshot,
  SnapshotCapture,
  SnapshotList,
  SnapshotReasonIn,
  StoryTime,
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

/* -------------------------------------------------------------------------------------------
 * The bible's request shapes (P3-9 … P3-11, D25 – D28).
 *
 * `kind` and `relation` are plain strings here for the same reason they are plain strings on the
 * wire: the seven kinds and the twelve relations are written down in **one** place, the served
 * definition, and the client fetches it (D26). A union type here would be the second copy.
 * ---------------------------------------------------------------------------------------- */

/**
 * What a new entry carries.
 *
 * `status` and `origin` are absent, not defaulted: everything a person types is `accepted` and
 * `user`, and the other values have no writer in this phase. A client that could send one would
 * be that writer.
 */
export interface EntryInput {
  kind: string;
  name: string;
  summary?: string;
  body_md?: string;
  attributes?: Record<string, unknown>;
}

/**
 * What a `PUT /api/entries/{eid}` may change (D19, ruling 3).
 *
 * `revision` is the one the form was read at; a stale one is refused with `409` and nothing is
 * written. An **absent** field keeps what is stored and a present one replaces it, so a patch
 * that sends `attributes: {}` clears them — the distinction is `undefined` versus a value, and
 * `JSON.stringify` drops the first.
 *
 * `kind` is absent because it is immutable, and `status` because Phase 3 has no writer for the
 * three that are not `accepted`.
 */
export interface EntryPatch {
  revision: number;
  name?: string;
  summary?: string;
  body_md?: string;
  attributes?: Record<string, unknown>;
  /** Override the store's computed retcon answer, in either direction. `null` takes it. */
  retcon?: boolean | null;
  reason?: string;
}

/**
 * The entry list's filters. They compose; every one of them is optional (ruling 4).
 *
 * A type rather than an interface so that it carries an implicit index signature and can be
 * handed straight to the query-string builder — an interface cannot, and the workaround would
 * be a second shape whose only job is to be copied into.
 */
export type EntryFilter = {
  kind?: string;
  status?: string;
  needs_review?: boolean;
  /** A `LIKE` filter over names, aliases, and summaries. A filter, not search — Phase 5 owns it. */
  q?: string;
  include_deleted?: boolean;
};

/** A new link. The field order is the sentence: *from* **relation** *to*. */
export interface LinkInput {
  from_entry: string;
  relation: string;
  to_entry: string;
  since?: string | null;
  until?: string | null;
  attributes?: Record<string, unknown>;
}

/**
 * What a `PATCH /api/links/{lid}` may change: the bounds and the attributes, and nothing else.
 *
 * The endpoints and the relation are absent on purpose — changing either is a delete and a
 * create, and both are recoverable. A bound genuinely is nullable, so `null` clears one.
 */
export interface LinkPatch {
  since?: string | null;
  until?: string | null;
  attributes?: Record<string, unknown>;
}

/**
 * *Add to bible*: a range, a version, and the entry to make from it (P3-7, ruling 8).
 *
 * A range and never a quote. The server derives the words out of the text it holds, so an entry
 * created from a selection cannot cite a passage the manuscript does not contain.
 */
export interface EntryFromRangeInput extends EntryInput {
  from_pos: number;
  to_pos: number;
  version: number;
  /** The anchor's label. The entry's name is `name`; this is what the *Marks* tab shows. */
  label?: string;
  role?: CitationRole;
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

  /**
   * Where a chapter's Markdown lives, as a URL rather than as text (P2-13).
   *
   * The export is the one non-JSON response in the API and it is served as an attachment, so
   * the honest client for it is an ordinary link: the browser saves the file, names it from the
   * `Content-Disposition` the server already set, and the app neither holds the bytes nor
   * reimplements a filename. Everything else here fetches; these two are addresses.
   */
  documentMarkdownUrl(documentId: string): string;
  /** Where the whole manuscript's Markdown lives. Same reasoning. */
  projectMarkdownUrl(projectId: string): string;
  /**
   * Create chapters from a Markdown file (P2-14).
   *
   * Appends; never replaces. `title` names the single chapter of `one-chapter` mode and is
   * ignored by `split-on-h1`, which takes each title from its own heading.
   */
  importMarkdown(
    projectId: string,
    markdown: string,
    mode: ImportMode,
    title?: string,
    signal?: AbortSignal,
  ): Promise<MarkdownImport>;

  listSnapshots(documentId: string, signal?: AbortSignal): Promise<SnapshotList>;
  captureSnapshot(
    documentId: string,
    reason: SnapshotReasonIn,
    label?: string,
    signal?: AbortSignal,
  ): Promise<SnapshotCapture>;
  getSnapshot(snapshotId: string, signal?: AbortSignal): Promise<Snapshot>;
  restoreSnapshot(snapshotId: string, version: number, signal?: AbortSignal): Promise<SaveResult>;

  /* -- the bible (P3-9 … P3-11) ------------------------------------------------------------ */

  /**
   * D26's definition: the seven kinds with their fields, and the relation vocabulary.
   *
   * The one route in the API with **no project scope** — the vocabulary is the product's, not a
   * manuscript's. Everything in the Bible tab renders from it, so it is read once per project
   * open and held.
   */
  getBibleSchema(signal?: AbortSignal): Promise<BibleSchema>;
  listEntries(projectId: string, filter?: EntryFilter, signal?: AbortSignal): Promise<EntryList>;
  listDeletedEntries(projectId: string, signal?: AbortSignal): Promise<EntryList>;
  createEntry(projectId: string, input: EntryInput, signal?: AbortSignal): Promise<Entry>;
  getEntry(entryId: string, signal?: AbortSignal): Promise<EntryDetail>;
  updateEntry(entryId: string, patch: EntryPatch, signal?: AbortSignal): Promise<EntryWriteResult>;
  deleteEntry(entryId: string, signal?: AbortSignal): Promise<Entry>;
  restoreEntry(entryId: string, signal?: AbortSignal): Promise<Entry>;
  /** The writer says they have looked. Never a retcon — that is what lets the queue empty. */
  clearEntryReview(
    entryId: string,
    revision: number,
    signal?: AbortSignal,
  ): Promise<EntryWriteResult>;

  listEntryRevisions(entryId: string, signal?: AbortSignal): Promise<RevisionList>;
  getEntryRevision(entryId: string, number: number, signal?: AbortSignal): Promise<EntryRevision>;
  /** `revision` is the entry's **current** one: a restore goes through the ordinary update path. */
  restoreEntryRevision(
    entryId: string,
    number: number,
    revision: number,
    signal?: AbortSignal,
  ): Promise<EntryWriteResult>;

  listLinks(projectId: string, relation?: string, signal?: AbortSignal): Promise<LinkList>;
  createLink(projectId: string, input: LinkInput, signal?: AbortSignal): Promise<Link>;
  listEntryLinks(entryId: string, signal?: AbortSignal): Promise<EntryLinks>;
  patchLink(linkId: string, patch: LinkPatch, signal?: AbortSignal): Promise<Link>;
  deleteLink(linkId: string, signal?: AbortSignal): Promise<Link>;
  restoreLink(linkId: string, signal?: AbortSignal): Promise<Link>;

  citeAnchor(
    entryId: string,
    anchorId: string,
    role: CitationRole,
    signal?: AbortSignal,
  ): Promise<Citation>;
  /** Without a role, every role this entry cites that anchor in. The **anchor stays**. */
  unciteAnchor(
    entryId: string,
    anchorId: string,
    role?: CitationRole,
    signal?: AbortSignal,
  ): Promise<CitationRemoved>;
  listAnchorEntries(anchorId: string, signal?: AbortSignal): Promise<AnchorEntries>;
  createEntryFromRange(
    documentId: string,
    input: EntryFromRangeInput,
    signal?: AbortSignal,
  ): Promise<EntryFromRange>;

  /** D28's three answers over the project's events, and the eras. Phase 3 draws no timeline. */
  getStoryTime(projectId: string, signal?: AbortSignal): Promise<StoryTime>;
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

  /**
   * True when an entry write was refused because the entry had moved on (D19, ruling 3).
   *
   * A code of its own rather than `version_conflict`, because the two surfaces recover
   * differently: the editor offers to reload a chapter, the entry form offers to reload a
   * record. One code for both would make that a branch on which request was in flight.
   */
  get isEntryVersionConflict(): boolean {
    return this.code === ERROR_CODES.entryVersionConflict;
  }

  /** The entry `409` payload, when this is one. */
  get entryVersionConflict(): EntryVersionConflictDetail | null {
    if (!this.isEntryVersionConflict || !isRecord(this.detail)) {
      return null;
    }
    const { entry_id, presented_revision, current_revision, updated_at } = this.detail;
    if (
      typeof entry_id !== 'string' ||
      typeof presented_revision !== 'number' ||
      typeof current_revision !== 'number' ||
      typeof updated_at !== 'string'
    ) {
      return null;
    }
    return { entry_id, presented_revision, current_revision, updated_at };
  }

  /**
   * Which input a refused kind, attribute, relation, or role was about.
   *
   * The form shows the message beside that field rather than rejecting the whole record: the
   * acceptance run's step 3 asks for a message naming the field, and a form that says only "that
   * did not work" leaves a writer hunting through eight inputs.
   */
  get invalidAttributes(): InvalidAttributesDetail | null {
    if (this.code !== ERROR_CODES.invalidAttributes || !isRecord(this.detail)) {
      return null;
    }
    const field = this.detail['field'];
    return { field: typeof field === 'string' ? field : null };
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

    documentMarkdownUrl: (documentId) =>
      `${baseUrl}/api/documents/${encodeURIComponent(documentId)}/markdown`,
    projectMarkdownUrl: (projectId) =>
      `${baseUrl}/api/projects/${encodeURIComponent(projectId)}/markdown`,
    importMarkdown: (projectId, markdown, mode, title, signal) =>
      request(
        'POST',
        `/api/projects/${encodeURIComponent(projectId)}/import`,
        { markdown, mode, title: title ?? null },
        signal,
      ),

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

    // -- the bible (P3-9 … P3-11) -----------------------------------------------------------

    getBibleSchema: (signal) => request('GET', '/api/bible/schema', undefined, signal),
    listEntries: (projectId, filter, signal) =>
      request(
        'GET',
        `/api/projects/${encodeURIComponent(projectId)}/entries${query(filter)}`,
        undefined,
        signal,
      ),
    listDeletedEntries: (projectId, signal) =>
      request(
        'GET',
        `/api/projects/${encodeURIComponent(projectId)}/entries/deleted`,
        undefined,
        signal,
      ),
    createEntry: (projectId, input, signal) =>
      request('POST', `/api/projects/${encodeURIComponent(projectId)}/entries`, input, signal),
    getEntry: (entryId, signal) =>
      request('GET', `/api/entries/${encodeURIComponent(entryId)}`, undefined, signal),
    updateEntry: (entryId, patch, signal) =>
      // `JSON.stringify` drops an `undefined` property, which is exactly the "absent keeps it"
      // rule the server reads through `model_fields_set`. Nothing here has to prune the body.
      request('PUT', `/api/entries/${encodeURIComponent(entryId)}`, patch, signal),
    deleteEntry: (entryId, signal) =>
      request('DELETE', `/api/entries/${encodeURIComponent(entryId)}`, undefined, signal),
    restoreEntry: (entryId, signal) =>
      request('POST', `/api/entries/${encodeURIComponent(entryId)}/restore`, undefined, signal),
    clearEntryReview: (entryId, revision, signal) =>
      request(
        'POST',
        `/api/entries/${encodeURIComponent(entryId)}/review/clear`,
        { revision },
        signal,
      ),

    listEntryRevisions: (entryId, signal) =>
      request('GET', `/api/entries/${encodeURIComponent(entryId)}/revisions`, undefined, signal),
    getEntryRevision: (entryId, number, signal) =>
      request(
        'GET',
        `/api/entries/${encodeURIComponent(entryId)}/revisions/${number}`,
        undefined,
        signal,
      ),
    restoreEntryRevision: (entryId, number, revision, signal) =>
      request(
        'POST',
        `/api/entries/${encodeURIComponent(entryId)}/revisions/${number}/restore`,
        { revision },
        signal,
      ),

    listLinks: (projectId, relation, signal) =>
      request(
        'GET',
        `/api/projects/${encodeURIComponent(projectId)}/links${query({ relation })}`,
        undefined,
        signal,
      ),
    createLink: (projectId, input, signal) =>
      request('POST', `/api/projects/${encodeURIComponent(projectId)}/links`, input, signal),
    listEntryLinks: (entryId, signal) =>
      request('GET', `/api/entries/${encodeURIComponent(entryId)}/links`, undefined, signal),
    patchLink: (linkId, patch, signal) =>
      request('PATCH', `/api/links/${encodeURIComponent(linkId)}`, patch, signal),
    deleteLink: (linkId, signal) =>
      request('DELETE', `/api/links/${encodeURIComponent(linkId)}`, undefined, signal),
    restoreLink: (linkId, signal) =>
      request('POST', `/api/links/${encodeURIComponent(linkId)}/restore`, undefined, signal),

    citeAnchor: (entryId, anchorId, role, signal) =>
      request(
        'POST',
        `/api/entries/${encodeURIComponent(entryId)}/citations`,
        { anchor_id: anchorId, role },
        signal,
      ),
    unciteAnchor: (entryId, anchorId, role, signal) =>
      request(
        'DELETE',
        `/api/entries/${encodeURIComponent(entryId)}/citations/` +
          `${encodeURIComponent(anchorId)}${query({ role })}`,
        undefined,
        signal,
      ),
    listAnchorEntries: (anchorId, signal) =>
      request('GET', `/api/anchors/${encodeURIComponent(anchorId)}/entries`, undefined, signal),
    createEntryFromRange: (documentId, input, signal) =>
      request('POST', `/api/documents/${encodeURIComponent(documentId)}/entries`, input, signal),

    getStoryTime: (projectId, signal) =>
      request('GET', `/api/projects/${encodeURIComponent(projectId)}/storytime`, undefined, signal),
  };
}

/**
 * A query string from the parameters that were actually given.
 *
 * An absent filter is absent from the URL rather than sent as an empty value: the routes read
 * `None` as "no filter", and `?kind=` would be a request for entries of the kind named by the
 * empty string, which is a `422` rather than everything.
 */
function query(params?: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== '') {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : '';
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
