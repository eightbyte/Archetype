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
 *
 * Group C added the controls the editor tests need on top of that: a failure that persists across
 * retries, and a write that happens behind the app's back so a real conflict can be staged
 * rather than simulated.
 *
 * ## What this fake deliberately does not do (P2-9 → P2-12)
 *
 * **It does not resolve anchors.** There is one resolver, it lives on the server, and it has a
 * specification and a corpus behind it (`specs/anchors.md`, P2-8). A fake that decided for itself
 * whether an edit broke an anchor would be a second one with neither — and every client test
 * would then be asserting against a rule nobody wrote down. So a save reports **no** moved
 * anchors unless a test has said what the server answers, through
 * {@link FakeApiClient.stageAnchorResolution}. That is the client's actual contract: it draws
 * what the save response tells it, whatever that is (D21).
 *
 * What it *does* do is **extract**: `createAnchor` reads the quote out of the stored content at
 * the range it was given, because that is a store's job and because a client never sends a
 * quote. Extraction has no thresholds, no candidates, and no status in it.
 *
 * **It does not parse Markdown either, for the same reason** (P2-14). There is one parser, it is
 * `markdown-it-py` behind the server's importer, and it has a round-trip corpus behind it. So
 * `importMarkdown` records what it was asked and creates whatever a test has staged through
 * {@link FakeApiClient.stageImport} - one plainly-named chapter by default. What the client is
 * responsible for is collecting the file, sending the mode, and drawing what came back; that is
 * what these tests are for.
 */

import type { AnchorPatch, AnchorRange, ApiClient } from '../../api/client';
import { ApiError } from '../../api/client';
import type {
  Anchor,
  AnchorList,
  AnchorStatus,
  AnchorSuggestion,
  Document,
  DocumentList,
  DocumentMeta,
  Health,
  ImportMode,
  ImportNotice,
  MarkdownImport,
  Outline,
  ProjectDetail,
  ProjectList,
  ProjectSummary,
  ProseMirrorDocument,
  ProseMirrorNode,
  SaveResult,
  SkippedFile,
  Snapshot,
  SnapshotCapture,
  SnapshotList,
  SnapshotMeta,
  SnapshotReasonIn,
} from '../../api/types';
import { ERROR_CODES } from '../../api/types';
import { emptyDocument, project } from '../../editor/projection';

const FIXED_NOW = '2026-01-01T00:00:00Z';

/** How much of `text_plain` either side of a quote is kept as context. Matches `CONTEXT_CHARS`. */
const CONTEXT_CHARS = 48;

interface StoredDocument {
  meta: DocumentMeta;
  content: ProseMirrorDocument;
}

interface StoredSnapshot {
  meta: SnapshotMeta;
  content: ProseMirrorDocument;
}

/** What a test says the server's resolver will answer for one anchor on the next save. */
export interface StagedResolution {
  id: string;
  status: AnchorStatus;
  from_pos?: number;
  to_pos?: number;
  suggestion?: AnchorSuggestion | null;
}

/** What a test says an import creates, standing in for a parser the fake does not have. */
export interface StagedImport {
  /** One entry per chapter the server would create, in order. */
  chapters: { title?: string; paragraphs?: string[] }[];
  /** What the server reports it could not keep. Empty unless a test says otherwise. */
  dropped?: ImportNotice[];
}

/** What an import was asked to do, so a test can assert the client sent the right thing. */
export interface ImportCall {
  projectId: string;
  markdown: string;
  mode: ImportMode;
  title: string | null;
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
  /** Every import the app asked for, in order. */
  readonly imports: ImportCall[] = [];

  private readonly version: string;
  private readonly projects = new Map<string, ProjectSummary>();
  private readonly documents = new Map<string, StoredDocument>();
  private readonly anchors = new Map<string, Anchor>();
  private readonly snapshots = new Map<string, StoredSnapshot>();
  private readonly staged = new Map<string, StagedResolution[]>();
  private readonly stagedImports: StagedImport[] = [];
  private skipped: SkippedFile[];
  private failures = new Map<string, ApiError | Error>();
  private readonly persistentFailures = new Map<string, ApiError | Error>();
  private counter = 0;
  private clock = 0;

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

  /**
   * Make every call to `method` reject until {@link stopFailing}.
   *
   * `failNext` is not enough for a retry loop, which by definition calls again (P1-10).
   */
  failAlways(method: keyof ApiClient, error: Error): void {
    this.persistentFailures.set(method, error);
  }

  /** Let `method` work again. */
  stopFailing(method: keyof ApiClient): void {
    this.persistentFailures.delete(method);
    this.failures.delete(method);
  }

  /**
   * Change a document behind the app's back, the way another window or the agent would.
   *
   * This is how a version conflict is staged: the store moves on, and the next save from a
   * client still holding the old version is refused with a `409` (D19).
   */
  writeBehindTheScenes(documentId: string, content: ProseMirrorDocument): number {
    const stored = this.requireDocument(documentId);
    const projection = project(content);
    stored.content = content;
    stored.meta = {
      ...stored.meta,
      version: stored.meta.version + 1,
      word_count: projection.word_count,
      headings: projection.headings,
      updated_at: FIXED_NOW,
    };
    return stored.meta.version;
  }

  /**
   * Say what the server's resolver answers for these anchors on the next save of `documentId`.
   *
   * The fake has no resolver and must not grow one (see the module docstring). A test that
   * needs the *client* to reconcile — an anchor that goes `stale` and comes back with a
   * suggestion, one that moved — says so here, and the next save reports exactly that.
   */
  stageAnchorResolution(documentId: string, updates: StagedResolution[]): void {
    this.staged.set(documentId, updates);
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

  /**
   * Put an anchor in the store directly, with the quote and status a test needs.
   *
   * The *Marks* tab's subject is triage — what is stale, what is orphaned, what can be
   * repaired — so its tests need those states to exist without a save having produced them.
   */
  seedAnchor(
    documentId: string,
    fields: {
      quote: string;
      status?: AnchorStatus;
      label?: string;
      from_pos?: number;
      to_pos?: number;
      suggestion?: AnchorSuggestion | null;
    },
  ): Anchor {
    const stored = this.documents.get(documentId);
    if (!stored) {
      throw new Error(`fake: no document ${documentId} to anchor`);
    }
    const id = this.nextId('anc');
    const anchor: Anchor = {
      id,
      project_id: stored.meta.project_id,
      document_id: documentId,
      from_pos: fields.from_pos ?? 1,
      to_pos: fields.to_pos ?? 1 + fields.quote.length,
      quote: fields.quote,
      prefix: '',
      suffix: '',
      status: fields.status ?? 'ok',
      label: fields.label ?? '',
      document_version: stored.meta.version,
      created_at: FIXED_NOW,
      updated_at: FIXED_NOW,
      checked_at: FIXED_NOW,
      suggestion: fields.suggestion ?? null,
    };
    this.anchors.set(id, anchor);
    return anchor;
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

  /** The stored anchor, for asserting that a re-link or a delete actually landed. */
  anchorOf(anchorId: string): Anchor | undefined {
    const anchor = this.anchors.get(anchorId);
    return anchor ? this.withEffectiveStatus(anchor) : undefined;
  }

  /** Every snapshot of a document, newest first — what the history route would return. */
  snapshotsOf(documentId: string): SnapshotMeta[] {
    return this.orderedSnapshots(documentId).map((stored) => ({ ...stored.meta }));
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

  async listDeletedDocuments(projectId: string): Promise<DocumentList> {
    this.record('listDeletedDocuments');
    this.requireProject(projectId);
    const deleted = [...this.documents.values()]
      .filter((stored) => stored.meta.project_id === projectId && stored.meta.deleted_at !== null)
      .sort((a, b) => (a.meta.deleted_at! < b.meta.deleted_at! ? 1 : -1));
    return { documents: deleted.map((stored) => ({ ...stored.meta })) };
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
    this.requireLiveDocument(documentId);
    return this.documentOf(documentId);
  }

  async saveDocumentContent(
    documentId: string,
    content: ProseMirrorDocument,
    version: number,
  ): Promise<SaveResult> {
    this.record('saveDocumentContent');
    const stored = this.requireLiveDocument(documentId);

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
      // Only what a test staged. The fake holds no resolver; see the module docstring.
      anchors: this.applyStagedResolution(documentId, stored.meta.version),
    };
  }

  async renameDocument(documentId: string, title: string): Promise<DocumentMeta> {
    this.record('renameDocument');
    const stored = this.requireDocument(documentId);
    // A rename is not a text edit, so the version does not move.
    stored.meta = { ...stored.meta, title, updated_at: FIXED_NOW };
    return { ...stored.meta };
  }

  async reorderDocuments(projectId: string, documentIds: string[]): Promise<DocumentList> {
    this.record('reorderDocuments');
    this.requireProject(projectId);
    const live = this.documentIdsOf(projectId);
    const presented = new Set(documentIds);
    const missing = live.filter((id) => !presented.has(id));
    const unexpected = documentIds.filter((id) => !live.includes(id));
    const duplicated = documentIds.filter((id, index) => documentIds.indexOf(id) !== index);

    if (missing.length || unexpected.length || duplicated.length) {
      // The completeness check is the concurrency guard (P2-2). Nothing is written.
      throw new ApiError(
        409,
        ERROR_CODES.reorderMismatch,
        "a reorder must present exactly this project's live chapters",
        { missing, unexpected, duplicated },
      );
    }

    documentIds.forEach((id, index) => {
      const stored = this.requireDocument(id);
      // No version bump and no updated_at: an order belongs to the project, not to a chapter.
      stored.meta = { ...stored.meta, order_index: index };
    });
    return { documents: this.orderedDocuments(projectId).map((stored) => ({ ...stored.meta })) };
  }

  async deleteDocument(documentId: string): Promise<DocumentMeta> {
    this.record('deleteDocument');
    const stored = this.requireLiveDocument(documentId);
    this.captureWithin(stored, 'pre-delete', '');
    stored.meta = { ...stored.meta, deleted_at: this.tick(), updated_at: FIXED_NOW };
    return { ...stored.meta };
  }

  async restoreDocument(documentId: string): Promise<DocumentMeta> {
    this.record('restoreDocument');
    const stored = this.requireDocument(documentId);
    if (stored.meta.deleted_at !== null) {
      // At the end of the order, counting deleted chapters too — exactly as the store does
      // (`MAX(order_index) + 1`). Counting only the live ones would hand the restored chapter
      // an index another chapter already holds.
      const last = [...this.documents.values()]
        .filter((other) => other.meta.project_id === stored.meta.project_id)
        .reduce((highest, other) => Math.max(highest, other.meta.order_index), -1);
      stored.meta = { ...stored.meta, deleted_at: null, order_index: last + 1 };
    }
    return { ...stored.meta };
  }

  // -- anchors ------------------------------------------------------------------------------

  async listDocumentAnchors(documentId: string): Promise<AnchorList> {
    this.record('listDocumentAnchors');
    this.requireLiveDocument(documentId);
    return {
      anchors: [...this.anchors.values()]
        .filter((anchor) => anchor.document_id === documentId)
        .sort((a, b) => a.from_pos - b.from_pos)
        .map((anchor) => this.withEffectiveStatus(anchor)),
    };
  }

  async listProjectAnchors(projectId: string, status?: string): Promise<AnchorList> {
    this.record('listProjectAnchors');
    this.requireProject(projectId);
    const order = new Map(
      [...this.documents.values()].map((stored) => [stored.meta.id, stored.meta.order_index]),
    );
    const anchors = [...this.anchors.values()]
      .filter((anchor) => anchor.project_id === projectId)
      .map((anchor) => this.withEffectiveStatus(anchor))
      .filter((anchor) => status === undefined || anchor.status === status)
      .sort(
        (a, b) =>
          (order.get(a.document_id) ?? 0) - (order.get(b.document_id) ?? 0) ||
          a.from_pos - b.from_pos,
      );
    return { anchors };
  }

  async createAnchor(documentId: string, range: AnchorRange, label?: string): Promise<Anchor> {
    this.record('createAnchor');
    const stored = this.guardedDocument(documentId, range.version);
    const anchor = this.seedAnchor(documentId, {
      ...this.extract(stored, range),
      status: 'ok',
      label: label ?? '',
      from_pos: range.from_pos,
      to_pos: range.to_pos,
    });
    return { ...anchor };
  }

  async patchAnchor(anchorId: string, patch: AnchorPatch): Promise<Anchor> {
    this.record('patchAnchor');
    const anchor = this.requireAnchor(anchorId);
    let next = anchor;
    if (patch.range) {
      const stored = this.guardedDocument(anchor.document_id, patch.range.version);
      // A re-linked anchor is `ok` by construction: the writer just looked at the passage.
      next = {
        ...next,
        ...this.extract(stored, patch.range),
        from_pos: patch.range.from_pos,
        to_pos: patch.range.to_pos,
        status: 'ok',
        suggestion: null,
        document_version: patch.range.version,
      };
    }
    if (patch.label !== undefined) {
      next = { ...next, label: patch.label };
    }
    this.anchors.set(anchorId, next);
    return this.withEffectiveStatus(next);
  }

  async deleteAnchor(anchorId: string): Promise<void> {
    this.record('deleteAnchor');
    this.requireAnchor(anchorId);
    this.anchors.delete(anchorId);
  }

  // -- markdown -----------------------------------------------------------------------------

  documentMarkdownUrl(documentId: string): string {
    return `/api/documents/${encodeURIComponent(documentId)}/markdown`;
  }

  projectMarkdownUrl(projectId: string): string {
    return `/api/projects/${encodeURIComponent(projectId)}/markdown`;
  }

  /** Say what the next import creates. Without one it makes a single, plainly-named chapter. */
  stageImport(staged: StagedImport): void {
    this.stagedImports.push(staged);
  }

  async importMarkdown(
    projectId: string,
    markdown: string,
    mode: ImportMode,
    title?: string,
  ): Promise<MarkdownImport> {
    this.record('importMarkdown');
    this.requireProject(projectId);
    this.imports.push({ projectId, markdown, mode, title: title ?? null });

    const staged: StagedImport =
      this.stagedImports.shift() ?? { chapters: [title === undefined ? {} : { title }] };
    const documents = staged.chapters.map((chapter) => {
      const id = this.addDocument(projectId, chapter.title);
      const stored = this.documents.get(id)!;
      if (chapter.paragraphs?.length) {
        stored.content = {
          type: 'doc',
          content: chapter.paragraphs.map((text) => ({
            type: 'paragraph',
            content: [{ type: 'text', text }],
          })),
        };
        const projection = project(stored.content);
        stored.meta = {
          ...stored.meta,
          headings: projection.headings,
          word_count: projection.word_count,
        };
      }
      return stored.meta;
    });
    return { documents, dropped: staged.dropped ?? [] };
  }

  // -- snapshots ----------------------------------------------------------------------------

  async listSnapshots(documentId: string): Promise<SnapshotList> {
    this.record('listSnapshots');
    this.requireDocument(documentId);
    return { snapshots: this.snapshotsOf(documentId) };
  }

  async captureSnapshot(
    documentId: string,
    reason: SnapshotReasonIn,
    label?: string,
  ): Promise<SnapshotCapture> {
    this.record('captureSnapshot');
    const stored = this.requireLiveDocument(documentId);
    const meta = this.captureWithin(stored, reason, label ?? '');
    return { captured: meta !== null, snapshot: meta };
  }

  async getSnapshot(snapshotId: string): Promise<Snapshot> {
    this.record('getSnapshot');
    const stored = this.requireSnapshot(snapshotId);
    return { ...stored.meta, content_json: stored.content };
  }

  async restoreSnapshot(snapshotId: string, version: number): Promise<SaveResult> {
    this.record('restoreSnapshot');
    const snapshot = this.requireSnapshot(snapshotId);
    const document = this.requireLiveDocument(snapshot.meta.document_id);
    if (document.meta.version !== version) {
      // Refused before the pre-restore snapshot is written, so nothing is left behind (A2).
      throw new ApiError(
        409,
        ERROR_CODES.versionConflict,
        `document ${document.meta.id} is at version ${document.meta.version}, not ${version}`,
        {
          document_id: document.meta.id,
          presented_version: version,
          current_version: document.meta.version,
          updated_at: document.meta.updated_at,
        },
      );
    }
    this.captureWithin(document, 'pre-restore', '');
    // A restore is an ordinary save: it goes through the same path and bumps the version.
    return this.saveDocumentContent(document.meta.id, snapshot.content, version);
  }

  // -- internals ----------------------------------------------------------------------------

  private record(method: keyof ApiClient): void {
    this.calls.push(method);
    const persistent = this.persistentFailures.get(method);
    if (persistent) {
      throw persistent;
    }
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

  /** A distinct, ordered timestamp, so "most recently deleted first" means something. */
  private tick(): string {
    this.clock += 1;
    return `2026-01-01T00:00:${String(this.clock).padStart(2, '0')}Z`;
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
        deleted_at: null,
      },
    });
    return id;
  }

  private orderedDocuments(projectId: string): StoredDocument[] {
    return [...this.documents.values()]
      .filter((stored) => stored.meta.project_id === projectId && stored.meta.deleted_at === null)
      .sort((a, b) => a.meta.order_index - b.meta.order_index);
  }

  private orderedSnapshots(documentId: string): StoredSnapshot[] {
    return [...this.snapshots.values()]
      .filter((stored) => stored.meta.document_id === documentId)
      .sort((a, b) => (a.meta.taken_at < b.meta.taken_at ? 1 : -1));
  }

  /**
   * Write a snapshot, deduplicating only the automatic ones (D23, deviation A3).
   *
   * A `manual` mark carries a label and is always written; a `pre-*` snapshot is a recovery
   * guarantee and is never suppressed. `handover` is the only one nobody asked for.
   */
  private captureWithin(stored: StoredDocument, reason: string, label: string): SnapshotMeta | null {
    const serialized = JSON.stringify(stored.content);
    const newest = this.orderedSnapshots(stored.meta.id)[0];
    if (reason === 'handover' && newest && JSON.stringify(newest.content) === serialized) {
      return null;
    }
    const meta: SnapshotMeta = {
      id: this.nextId('snp'),
      project_id: stored.meta.project_id,
      document_id: stored.meta.id,
      taken_at: this.tick(),
      reason,
      label,
      word_count: stored.meta.word_count,
      version: stored.meta.version,
      size_bytes: serialized.length,
    };
    this.snapshots.set(meta.id, { meta, content: stored.content });
    return { ...meta };
  }

  /** Apply what a test staged for this save, and report exactly those anchors (D21). */
  private applyStagedResolution(documentId: string, version: number): Anchor[] {
    const updates = this.staged.get(documentId);
    if (!updates) {
      return [];
    }
    this.staged.delete(documentId);
    return updates.map((update) => {
      const anchor = this.requireAnchor(update.id);
      const moved: Anchor = {
        ...anchor,
        status: update.status,
        from_pos: update.from_pos ?? anchor.from_pos,
        to_pos: update.to_pos ?? anchor.to_pos,
        suggestion: update.suggestion ?? null,
        // Only an `ok` anchor's version advances: a stale one's positions are true at no
        // version at all (P2-7).
        document_version: update.status === 'ok' ? version : anchor.document_version,
        checked_at: FIXED_NOW,
      };
      this.anchors.set(moved.id, moved);
      return this.withEffectiveStatus(moved);
    });
  }

  /**
   * The text at a ProseMirror range, with the context either side.
   *
   * An **extraction**, not a resolution: it reads what is there rather than deciding where
   * something went. The client never sends a quote, so a store — real or fake — has to be able
   * to answer this.
   */
  private extract(
    stored: StoredDocument,
    range: AnchorRange,
  ): { quote: string; prefix: string; suffix: string } {
    const runs = textRuns(stored.content);
    const slice = (from: number, to: number) =>
      runs
        .map((run) => {
          const start = Math.max(from, run.from);
          const end = Math.min(to, run.to);
          return end > start ? run.text.slice(start - run.from, end - run.from) : '';
        })
        .join('');
    return {
      quote: slice(range.from_pos, range.to_pos),
      prefix: slice(Math.max(0, range.from_pos - CONTEXT_CHARS), range.from_pos),
      suffix: slice(range.to_pos, range.to_pos + CONTEXT_CHARS),
    };
  }

  /** `orphaned` is derived from the chapter, never stored (D22). */
  private withEffectiveStatus(anchor: Anchor): Anchor {
    const document = this.documents.get(anchor.document_id);
    const orphaned = document ? document.meta.deleted_at !== null : false;
    return { ...anchor, status: orphaned ? 'orphaned' : anchor.status };
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

  /** A soft-deleted chapter is out of every list, and out of the editor's reach (D22). */
  private requireLiveDocument(documentId: string): StoredDocument {
    const stored = this.requireDocument(documentId);
    if (stored.meta.deleted_at !== null) {
      throw new ApiError(
        404,
        ERROR_CODES.documentNotFound,
        `no document '${documentId}' in this workspace`,
        null,
      );
    }
    return stored;
  }

  private guardedDocument(documentId: string, version: number): StoredDocument {
    const stored = this.requireLiveDocument(documentId);
    if (stored.meta.version !== version) {
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
    return stored;
  }

  private requireAnchor(anchorId: string): Anchor {
    const anchor = this.anchors.get(anchorId);
    if (!anchor) {
      throw new ApiError(
        404,
        ERROR_CODES.anchorNotFound,
        `no anchor '${anchorId}' in this workspace`,
        null,
      );
    }
    return anchor;
  }

  private requireSnapshot(snapshotId: string): StoredSnapshot {
    const stored = this.snapshots.get(snapshotId);
    if (!stored) {
      throw new ApiError(
        404,
        ERROR_CODES.snapshotNotFound,
        `no snapshot '${snapshotId}' in this workspace`,
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
    const { deleted_at: _deleted, ...meta } = stored.meta;
    return { ...meta, content_json: stored.content };
  }
}

interface TextRun {
  from: number;
  to: number;
  text: string;
}

/**
 * Every text node of a document with the ProseMirror positions it occupies.
 *
 * A block opens at its position and closes one past its content, and a `hardBreak` is one
 * position that reads as a newline — the same walk `projection.py` does, kept to what an
 * extraction needs. Not a block index and not a projection: no trimming, no separators, no
 * scene breaks. The two coordinate systems are the server's problem (`specs/anchors.md` § 2).
 */
function textRuns(document: ProseMirrorDocument): TextRun[] {
  const runs: TextRun[] = [];
  let position = 0;

  const walk = (node: ProseMirrorNode): void => {
    if (node.type === 'text') {
      const text = node.text ?? '';
      runs.push({ from: position, to: position + text.length, text });
      position += text.length;
      return;
    }
    if (node.type === 'hardBreak') {
      runs.push({ from: position, to: position + 1, text: '\n' });
      position += 1;
      return;
    }
    // Everything else is a node with a position either side of its content.
    position += 1;
    for (const child of node.content ?? []) {
      walk(child);
    }
    position += 1;
  };

  // The document node itself occupies no position; its children start at 0.
  for (const child of document.content ?? []) {
    walk(child);
  }
  return runs;
}
