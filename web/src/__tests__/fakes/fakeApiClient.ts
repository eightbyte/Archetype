/**
 * A hand-written, typed fake of `ApiClient` (P1-8).
 *
 * It implements the same interface as the real client, so it fails to compile the moment the
 * interface changes — which is the whole reason it is hand-written rather than a request
 * interceptor. No MSW, no extra dependency (outline § 8).
 *
 * It keeps real state rather than returning canned answers: creating a project puts it in the
 * list, saving a document bumps its version, and a save at the wrong version rejects the way the
 * server does (D19). A component test that passes against this one is testing the flow, not a
 * script.
 */

import type { ApiClient } from '../../api/client';
import { ApiError } from '../../api/client';
import type {
  Document,
  DocumentList,
  DocumentMeta,
  Health,
  Outline,
  ProjectDetail,
  ProjectList,
  ProjectSummary,
  ProseMirrorDocument,
  SaveResult,
  SkippedFile,
} from '../../api/types';
import { ERROR_CODES } from '../../api/types';
import { emptyDocument, project } from '../../editor/projection';

const FIXED_NOW = '2026-01-01T00:00:00Z';

interface StoredDocument {
  meta: DocumentMeta;
  content: ProseMirrorDocument;
}

/** Options for seeding a fake with something already in it. */
export interface FakeApiOptions {
  /** Titles of projects that already exist, each with one empty chapter. */
  projects?: string[];
  /** Files the server would report as unreadable (P1-12). */
  skipped?: SkippedFile[];
  /** Version reported by `health`. */
  version?: string;
}

/**
 * A fake `ApiClient` with inspectable state.
 *
 * Beyond the interface it exposes `calls` (what was asked, in order) and `failNext` (make the
 * next call of one method fail), which is what tests need to assert on a save that failed or a
 * conflict that was surfaced rather than swallowed.
 */
export class FakeApiClient implements ApiClient {
  readonly calls: string[] = [];

  private readonly version: string;
  private readonly projects = new Map<string, ProjectSummary>();
  private readonly documents = new Map<string, StoredDocument>();
  private skipped: SkippedFile[];
  private failures = new Map<string, ApiError | Error>();
  private counter = 0;

  constructor(options: FakeApiOptions = {}) {
    this.version = options.version ?? '0.1.0';
    this.skipped = options.skipped ?? [];
    for (const title of options.projects ?? []) {
      this.seedProject(title);
    }
  }

  // -- test controls ------------------------------------------------------------------------

  /** Make the next call to `method` reject with `error`. */
  failNext(method: keyof ApiClient, error: Error): void {
    this.failures.set(method, error);
  }

  /** Create a project directly, without going through the client. Returns its id. */
  seedProject(title: string): string {
    const id = this.nextId('prj');
    this.projects.set(id, {
      id,
      title,
      chapter_count: 0,
      word_count: 0,
      created_at: FIXED_NOW,
      updated_at: FIXED_NOW,
    });
    this.addDocument(id, 'Chapter 1');
    return id;
  }

  /** Report a file the server could not read (P1-12). */
  seedSkipped(file: SkippedFile): void {
    this.skipped = [...this.skipped, file];
  }

  /** The stored version of a document, for asserting that a save actually landed. */
  versionOf(documentId: string): number | undefined {
    return this.documents.get(documentId)?.meta.version;
  }

  /** The document ids of a project, in order. */
  documentIdsOf(projectId: string): string[] {
    return this.orderedDocuments(projectId).map((stored) => stored.meta.id);
  }

  // -- ApiClient ----------------------------------------------------------------------------

  async health(): Promise<Health> {
    this.record('health');
    return { status: 'ok', version: this.version };
  }

  async listProjects(): Promise<ProjectList> {
    this.record('listProjects');
    return {
      projects: [...this.projects.values()].map((summary) => this.summaryOf(summary.id)),
      skipped: [...this.skipped],
    };
  }

  async createProject(title: string): Promise<ProjectDetail> {
    this.record('createProject');
    const id = this.seedProject(title);
    return this.detailOf(id);
  }

  async getProject(projectId: string): Promise<ProjectDetail> {
    this.record('getProject');
    this.requireProject(projectId);
    return this.detailOf(projectId);
  }

  async listDocuments(projectId: string): Promise<DocumentList> {
    this.record('listDocuments');
    this.requireProject(projectId);
    return { documents: this.orderedDocuments(projectId).map((stored) => ({ ...stored.meta })) };
  }

  async createDocument(projectId: string, title?: string): Promise<Document> {
    this.record('createDocument');
    this.requireProject(projectId);
    return this.documentOf(this.addDocument(projectId, title));
  }

  async getOutline(projectId: string): Promise<Outline> {
    this.record('getOutline');
    this.requireProject(projectId);
    return {
      project_id: projectId,
      chapters: this.orderedDocuments(projectId).map((stored) => ({
        document_id: stored.meta.id,
        title: stored.meta.title,
        order_index: stored.meta.order_index,
        word_count: stored.meta.word_count,
        headings: stored.meta.headings.map((heading) => ({ ...heading })),
      })),
    };
  }

  async getDocument(documentId: string): Promise<Document> {
    this.record('getDocument');
    this.requireDocument(documentId);
    return this.documentOf(documentId);
  }

  async saveDocumentContent(
    documentId: string,
    content: ProseMirrorDocument,
    version: number,
  ): Promise<SaveResult> {
    this.record('saveDocumentContent');
    const stored = this.requireDocument(documentId);

    if (stored.meta.version !== version) {
      // D19: nothing is written, and the caller is handed what it needs to offer a reload.
      throw new ApiError(
        409,
        ERROR_CODES.versionConflict,
        `document ${documentId} is at version ${stored.meta.version}, not ${version}`,
        {
          document_id: documentId,
          presented_version: version,
          current_version: stored.meta.version,
          updated_at: stored.meta.updated_at,
        },
      );
    }

    const projection = project(content);
    stored.content = content;
    stored.meta = {
      ...stored.meta,
      version: stored.meta.version + 1,
      word_count: projection.word_count,
      headings: projection.headings,
      updated_at: FIXED_NOW,
    };
    return {
      document_id: documentId,
      version: stored.meta.version,
      word_count: stored.meta.word_count,
      headings: stored.meta.headings.map((heading) => ({ ...heading })),
      updated_at: stored.meta.updated_at,
    };
  }

  async renameDocument(documentId: string, title: string): Promise<DocumentMeta> {
    this.record('renameDocument');
    const stored = this.requireDocument(documentId);
    // A rename is not a text edit, so the version does not move.
    stored.meta = { ...stored.meta, title, updated_at: FIXED_NOW };
    return { ...stored.meta };
  }

  // -- internals ----------------------------------------------------------------------------

  private record(method: keyof ApiClient): void {
    this.calls.push(method);
    const failure = this.failures.get(method);
    if (failure) {
      this.failures.delete(method);
      throw failure;
    }
  }

  private nextId(prefix: string): string {
    this.counter += 1;
    return `${prefix}_${String(this.counter).padStart(12, '0')}`;
  }

  private addDocument(projectId: string, title?: string): string {
    const existing = this.orderedDocuments(projectId);
    const id = this.nextId('doc');
    this.documents.set(id, {
      content: emptyDocument(),
      meta: {
        id,
        project_id: projectId,
        order_index: existing.length,
        title: title ?? `Chapter ${existing.length + 1}`,
        kind: 'chapter',
        headings: [],
        word_count: 0,
        version: 1,
        created_at: FIXED_NOW,
        updated_at: FIXED_NOW,
      },
    });
    return id;
  }

  private orderedDocuments(projectId: string): StoredDocument[] {
    return [...this.documents.values()]
      .filter((stored) => stored.meta.project_id === projectId)
      .sort((a, b) => a.meta.order_index - b.meta.order_index);
  }

  private requireProject(projectId: string): ProjectSummary {
    const summary = this.projects.get(projectId);
    if (!summary) {
      throw new ApiError(
        404,
        ERROR_CODES.projectNotFound,
        `no project '${projectId}' in this workspace`,
        null,
      );
    }
    return summary;
  }

  private requireDocument(documentId: string): StoredDocument {
    const stored = this.documents.get(documentId);
    if (!stored) {
      throw new ApiError(
        404,
        ERROR_CODES.documentNotFound,
        `no document '${documentId}' in this workspace`,
        null,
      );
    }
    return stored;
  }

  private summaryOf(projectId: string): ProjectSummary {
    const summary = this.projects.get(projectId);
    if (!summary) {
      throw new Error(`fake: no project ${projectId}`);
    }
    const chapters = this.orderedDocuments(projectId);
    return {
      ...summary,
      chapter_count: chapters.length,
      word_count: chapters.reduce((total, stored) => total + stored.meta.word_count, 0),
    };
  }

  private detailOf(projectId: string): ProjectDetail {
    return {
      project: this.summaryOf(projectId),
      documents: this.orderedDocuments(projectId).map((stored) => ({ ...stored.meta })),
    };
  }

  private documentOf(documentId: string): Document {
    const stored = this.requireDocument(documentId);
    return {
      ...stored.meta,
      content_json: stored.content,
    };
  }
}
