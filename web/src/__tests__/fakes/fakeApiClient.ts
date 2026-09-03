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
 *
 * ## The bible (P3-12 - P3-14), and where the same rule lands differently
 *
 * The bible half keeps real state too: entries with complete revision histories, links with the
 * three-way live predicate, and citations that carry an anchor's current status.
 *
 * **It does not validate attributes, kinds, or relations.** Those are one closed vocabulary with
 * one validator, `bible/schema.py`, and it has its own tests; a second one here would be the copy
 * D26 exists to prevent. A test that needs a refusal - an `enum` outside its set, an `entry_ref`
 * to the wrong kind, a duplicate link - stages one with {@link FakeApiClient.failNext}, exactly
 * as a test that needs a `409` does.
 *
 * **It does compute the retcon answer and the entries it flags**, which is the one place this
 * fake goes further than the resolver rule allows - deliberately, and for a reason that does not
 * generalise. The resolver was refused a place here because it is a ladder with thresholds and a
 * corpus, so a second one would be "a rule nobody wrote down". D27's is not that: it is two
 * sentences - a write is a retcon when the name, the attributes, or the status changed, and a
 * dependent is an entry joined by a live link in either direction - and the review queue is the
 * phase's headline surface, which cannot be exercised end to end against a staged answer. The
 * rule is transcribed here and nothing is inferred beyond it.
 *
 * The served definition is **not** hand-written either: `getBibleSchema` returns the contract
 * fixture, so these tests render the real seven kinds with their real fields, and a kind that
 * gains a field reaches the client tests in the same commit it reaches the wire (D26).
 */

import type {
  AnchorPatch,
  AnchorRange,
  ApiClient,
  EntryFilter,
  EntryFromRangeInput,
  EntryInput,
  EntryPatch,
  LinkInput,
  LinkPatch,
} from '../../api/client';
import { ApiError } from '../../api/client';
import type {
  Anchor,
  AnchorEntries,
  AnchorList,
  BibleSchema,
  Citation,
  CitationRemoved,
  CitationRole,
  CitingEntry,
  Entry,
  EntryDetail,
  EntryFromRange,
  EntryLinks,
  EntryList,
  EntryRevision,
  EntryWriteResult,
  Link,
  LinkList,
  LinkView,
  RelationDefinition,
  RevisionList,
  StoryTime,
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
import { readServerFixture } from '../fixtures';

const FIXED_NOW = '2026-01-01T00:00:00Z';

/** How much of `text_plain` either side of a quote is kept as context. Matches `CONTEXT_CHARS`. */
const CONTEXT_CHARS = 48;

/** The entry list's cap, matching `bible.entries.SEARCH_LIMIT`. Reported, not merely applied. */
const SEARCH_LIMIT = 200;

interface StoredDocument {
  meta: DocumentMeta;
  content: ProseMirrorDocument;
}

interface StoredSnapshot {
  meta: SnapshotMeta;
  content: ProseMirrorDocument;
}

/** An entry and everything it has ever said. Nothing here is deduplicated or pruned (D27). */
interface StoredEntry {
  entry: Entry;
  revisions: EntryRevision[];
}

/** One row of `entry_anchor`: an entry pointing at a passage, in a role. */
interface StoredCitation {
  entry_id: string;
  anchor_id: string;
  role: string;
  created_at: string;
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
  private readonly entries = new Map<string, StoredEntry>();
  private readonly links = new Map<string, Link>();
  private citations: StoredCitation[] = [];
  private readonly stagedImports: StagedImport[] = [];
  private stagedStoryTime: StoryTime | null = null;
  private schemaCache: BibleSchema | null = null;
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

  /**
   * Put an entry in the store directly, without going through the client.
   *
   * The bible tests need a populated bible to browse, filter, link, and retcon; building one
   * through `createEntry` would make every test's arrangement three times its assertion.
   */
  seedEntry(
    projectId: string,
    fields: {
      kind: string;
      name: string;
      summary?: string;
      body_md?: string;
      attributes?: Record<string, unknown>;
    },
  ): Entry {
    this.requireProject(projectId);
    return copyEntry(this.addEntry(projectId, fields, 'created'));
  }

  /** Join two entries directly. The vocabulary is the server's to enforce; see the docstring. */
  seedLink(
    projectId: string,
    fromEntry: string,
    relation: string,
    toEntry: string,
  ): Link {
    const id = this.nextId('lnk');
    const link: Link = {
      id,
      project_id: projectId,
      from_entry: fromEntry,
      to_entry: toEntry,
      relation,
      attributes: {},
      since: null,
      until: null,
      created_at: FIXED_NOW,
      updated_at: FIXED_NOW,
      deleted_at: null,
    };
    this.links.set(id, link);
    return { ...link };
  }

  /** Point an entry at an anchor directly, in a role. */
  seedCitation(entryId: string, anchorId: string, role: CitationRole = 'source'): void {
    this.citations.push({ entry_id: entryId, anchor_id: anchorId, role, created_at: FIXED_NOW });
  }

  /**
   * Say what the ordering module answers.
   *
   * The fake does not order events and must not learn to — see the module docstring. Without a
   * staged answer every event is reported unplaced, which is the honest thing for a fake with no
   * topological sort in it to say.
   */
  stageStoryTime(answer: StoryTime): void {
    this.stagedStoryTime = answer;
  }

  /** The stored entry, for asserting that a write actually landed. */
  entryOf(entryId: string): Entry | undefined {
    const stored = this.entries.get(entryId);
    return stored ? copyEntry(stored.entry) : undefined;
  }

  /** Every link in the project, deleted ones included — what a soft delete has to leave behind. */
  linksOf(projectId: string): Link[] {
    return [...this.links.values()]
      .filter((link) => link.project_id === projectId)
      .map((link) => ({ ...link }));
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
    // Deleting an anchor removes its citations and leaves the entries (`B2`). On the server this
    // is not a courtesy: `entry_anchor.anchor_id` is a real foreign key, so without it deleting
    // a cited anchor fails. The entry keeps what a person typed and loses one reason to believe
    // it.
    this.citations = this.citations.filter((citation) => citation.anchor_id !== anchorId);
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

  // -- the bible (P3-12 - P3-14) ------------------------------------------------------------

  /**
   * D26's definition, read from the **contract fixture** rather than written out here.
   *
   * So the client tests render the real seven kinds with their real fields, and a kind that
   * gains one reaches them in the commit that puts it on the wire. A hand-written copy would be
   * the second copy that decision exists to prevent - and it would be the stale one.
   */
  async getBibleSchema(): Promise<BibleSchema> {
    this.record('getBibleSchema');
    return this.bibleSchema();
  }

  async listEntries(projectId: string, filter?: EntryFilter): Promise<EntryList> {
    this.record('listEntries');
    this.requireProject(projectId);
    const wanted = (filter?.q ?? '').trim().toLowerCase();
    const found = [...this.entries.values()]
      .map((stored) => stored.entry)
      .filter((entry) => entry.project_id === projectId)
      .filter((entry) => (filter?.include_deleted ? true : entry.deleted_at === null))
      .filter((entry) => filter?.kind === undefined || entry.kind === filter.kind)
      .filter((entry) => filter?.status === undefined || entry.status === filter.status)
      .filter(
        (entry) => filter?.needs_review === undefined || entry.needs_review === filter.needs_review,
      )
      .filter((entry) => wanted === '' || matches(entry, wanted))
      .sort(byName);
    return {
      entries: found.slice(0, SEARCH_LIMIT).map(copyEntry),
      counts: this.countsByKind(projectId),
      truncated: found.length > SEARCH_LIMIT,
    };
  }

  async listDeletedEntries(projectId: string): Promise<EntryList> {
    this.record('listDeletedEntries');
    this.requireProject(projectId);
    const deleted = [...this.entries.values()]
      .map((stored) => stored.entry)
      .filter((entry) => entry.project_id === projectId && entry.deleted_at !== null)
      .sort((a, b) => (a.deleted_at! < b.deleted_at! ? 1 : -1));
    return {
      entries: deleted.map(copyEntry),
      counts: this.countsByKind(projectId),
      truncated: false,
    };
  }

  async createEntry(projectId: string, input: EntryInput): Promise<Entry> {
    this.record('createEntry');
    this.requireProject(projectId);
    return copyEntry(this.addEntry(projectId, input, 'created'));
  }

  async getEntry(entryId: string): Promise<EntryDetail> {
    this.record('getEntry');
    const entry = this.requireEntry(entryId).entry;
    const citations = this.citationsOf(entryId);
    return {
      entry: copyEntry(entry),
      citations,
      link_count: this.liveLinksOf(entryId).length,
      narrative_position: this.narrativePosition(entryId, citations),
    };
  }

  async updateEntry(entryId: string, patch: EntryPatch): Promise<EntryWriteResult> {
    this.record('updateEntry');
    const stored = this.requireEntry(entryId);
    this.guardRevision(stored.entry, patch.revision);

    // D27's rule, transcribed: `status` is absent because no route in this phase writes one.
    const changed: string[] = [];
    if (patch.name !== undefined && patch.name !== stored.entry.name) {
      changed.push('name');
    }
    if (
      patch.attributes !== undefined &&
      JSON.stringify(patch.attributes) !== JSON.stringify(stored.entry.attributes)
    ) {
      changed.push('attributes_json');
    }
    const retcon = patch.retcon ?? changed.length > 0;

    stored.entry = {
      ...stored.entry,
      ...(patch.name === undefined ? {} : { name: patch.name }),
      ...(patch.summary === undefined ? {} : { summary: patch.summary }),
      ...(patch.body_md === undefined ? {} : { body_md: patch.body_md }),
      ...(patch.attributes === undefined ? {} : { attributes: patch.attributes }),
      revision: stored.entry.revision + 1,
      updated_at: this.tick(),
    };
    this.writeRevision(stored, patch.reason ?? '', retcon);

    // A dependent is an entry joined by a **live** link in either direction - the only
    // relationship the data actually knows. Flagging writes no revision on the dependent: it is
    // a note about that entry's surroundings, not a claim it makes.
    const flagged = retcon ? this.flagDependents(stored.entry) : [];
    return {
      entry: copyEntry(stored.entry),
      revision: stored.entry.revision,
      retcon,
      flagged,
      changed_fields: changed,
    };
  }

  async deleteEntry(entryId: string): Promise<Entry> {
    this.record('deleteEntry');
    const stored = this.requireEntry(entryId);
    stored.entry = {
      ...stored.entry,
      deleted_at: this.tick(),
      updated_at: FIXED_NOW,
      revision: stored.entry.revision + 1,
    };
    this.writeRevision(stored, 'deleted', false);
    return copyEntry(stored.entry);
  }

  async restoreEntry(entryId: string): Promise<Entry> {
    this.record('restoreEntry');
    const stored = this.requireEntry(entryId, true);
    if (stored.entry.deleted_at === null) {
      return copyEntry(stored.entry);
    }
    // Nothing is written to a link: an endpoint's deletion *hid* them through the predicate, so
    // restoring brings back exactly the links it had (D25, ruling 9).
    stored.entry = {
      ...stored.entry,
      deleted_at: null,
      updated_at: FIXED_NOW,
      revision: stored.entry.revision + 1,
    };
    this.writeRevision(stored, 'restored', false);
    return copyEntry(stored.entry);
  }

  async clearEntryReview(entryId: string, revision: number): Promise<EntryWriteResult> {
    this.record('clearEntryReview');
    const stored = this.requireEntry(entryId);
    this.guardRevision(stored.entry, revision);
    stored.entry = {
      ...stored.entry,
      needs_review: false,
      review_reason: '',
      revision: stored.entry.revision + 1,
      updated_at: this.tick(),
    };
    this.writeRevision(stored, 'review cleared', false);
    // Never a retcon, not by default and not by override: a queue that re-flags every neighbour
    // as it is worked through is a queue that never empties (P3-4).
    return {
      entry: copyEntry(stored.entry),
      revision: stored.entry.revision,
      retcon: false,
      flagged: [],
      changed_fields: [],
    };
  }

  async listEntryRevisions(entryId: string): Promise<RevisionList> {
    this.record('listEntryRevisions');
    const stored = this.requireEntry(entryId, true);
    return {
      revisions: [...stored.revisions]
        .sort((a, b) => b.meta.revision - a.meta.revision)
        .map((revision) => ({ ...revision.meta })),
    };
  }

  async getEntryRevision(entryId: string, number: number): Promise<EntryRevision> {
    this.record('getEntryRevision');
    const stored = this.requireEntry(entryId, true);
    const found = stored.revisions.find((revision) => revision.meta.revision === number);
    if (!found) {
      throw new ApiError(
        404,
        ERROR_CODES.revisionNotFound,
        `entry ${entryId} has no revision ${number}`,
        null,
      );
    }
    return { meta: { ...found.meta }, state: { ...found.state } };
  }

  async restoreEntryRevision(
    entryId: string,
    number: number,
    revision: number,
  ): Promise<EntryWriteResult> {
    this.record('restoreEntryRevision');
    const past = await this.getEntryRevision(entryId, number);
    // Through the ordinary update path, so it bumps the revision, appends to the history rather
    // than rewriting it, is guarded by D19, and computes its own retcon answer.
    return this.updateEntry(entryId, {
      revision,
      name: String(past.state['name'] ?? ''),
      summary: String(past.state['summary'] ?? ''),
      body_md: String(past.state['body_md'] ?? ''),
      attributes: (past.state['attributes'] as Record<string, unknown>) ?? {},
      reason: `restored revision ${number}`,
    });
  }

  // -- links --------------------------------------------------------------------------------

  async listLinks(projectId: string, relation?: string): Promise<LinkList> {
    this.record('listLinks');
    this.requireProject(projectId);
    return {
      links: [...this.links.values()]
        .filter((link) => link.project_id === projectId && this.isLiveLink(link))
        .filter((link) => relation === undefined || link.relation === relation)
        .map((link) => ({ ...link })),
    };
  }

  async createLink(projectId: string, input: LinkInput): Promise<Link> {
    this.record('createLink');
    this.requireProject(projectId);
    if (input.from_entry === input.to_entry) {
      throw new ApiError(
        422,
        ERROR_CODES.invalidAttributes,
        'an entry cannot be linked to itself',
        { field: 'to_entry' },
      );
    }
    const duplicate = [...this.links.values()].find(
      (link) => this.isLiveLink(link) && this.sameStatement(link, input),
    );
    if (duplicate) {
      throw new ApiError(409, ERROR_CODES.duplicateLink, 'that link already exists', {
        link_id: duplicate.id,
      });
    }
    const id = this.nextId('lnk');
    const link: Link = {
      id,
      project_id: projectId,
      from_entry: input.from_entry,
      to_entry: input.to_entry,
      relation: input.relation,
      attributes: input.attributes ?? {},
      since: input.since ?? null,
      until: input.until ?? null,
      created_at: FIXED_NOW,
      updated_at: FIXED_NOW,
      deleted_at: null,
    };
    this.links.set(id, link);
    return { ...link };
  }

  async listEntryLinks(entryId: string): Promise<EntryLinks> {
    this.record('listEntryLinks');
    // Deliberately not an error for a deleted or unknown entry: the predicate is what hides a
    // link, and a read path that raised instead would be a second answer to the same question.
    return { links: this.liveLinksOf(entryId).map((link) => this.viewOf(link, entryId)) };
  }

  async patchLink(linkId: string, patch: LinkPatch): Promise<Link> {
    this.record('patchLink');
    const link = this.requireLink(linkId);
    const next: Link = {
      ...link,
      ...('since' in patch ? { since: patch.since ?? null } : {}),
      ...('until' in patch ? { until: patch.until ?? null } : {}),
      ...(patch.attributes === undefined ? {} : { attributes: patch.attributes }),
      updated_at: FIXED_NOW,
    };
    this.links.set(linkId, next);
    return { ...next };
  }

  async deleteLink(linkId: string): Promise<Link> {
    this.record('deleteLink');
    const link = this.requireLink(linkId);
    const next: Link = { ...link, deleted_at: this.tick(), updated_at: FIXED_NOW };
    this.links.set(linkId, next);
    return { ...next };
  }

  async restoreLink(linkId: string): Promise<Link> {
    this.record('restoreLink');
    const link = this.requireLink(linkId);
    const duplicate = [...this.links.values()].find(
      (other) => other.id !== linkId && this.isLiveLink(other) && this.sameStatement(other, link),
    );
    if (duplicate) {
      throw new ApiError(409, ERROR_CODES.duplicateLink, 'that link already exists', {
        link_id: duplicate.id,
      });
    }
    const next: Link = { ...link, deleted_at: null, updated_at: FIXED_NOW };
    this.links.set(linkId, next);
    return { ...next };
  }

  // -- citations ----------------------------------------------------------------------------

  async citeAnchor(entryId: string, anchorId: string, role: CitationRole): Promise<Citation> {
    this.record('citeAnchor');
    this.requireEntry(entryId);
    this.requireAnchor(anchorId);
    if (
      !this.citations.some(
        (citation) =>
          citation.entry_id === entryId &&
          citation.anchor_id === anchorId &&
          citation.role === role,
      )
    ) {
      this.citations.push({
        entry_id: entryId,
        anchor_id: anchorId,
        role,
        created_at: FIXED_NOW,
      });
    }
    const found = this.citationsOf(entryId).find(
      (citation) => citation.anchor.id === anchorId && citation.role === role,
    );
    if (!found) {
      throw new Error('fake: a citation was written but could not be read back');
    }
    return found;
  }

  async unciteAnchor(
    entryId: string,
    anchorId: string,
    role?: CitationRole,
  ): Promise<CitationRemoved> {
    this.record('unciteAnchor');
    this.requireEntry(entryId, true);
    const before = this.citations.length;
    // The **anchor stays**: it is a fact about the manuscript, and *Marks* is where one is
    // removed. Removing a citation that is not there is zero, not a `404`.
    this.citations = this.citations.filter(
      (citation) =>
        !(
          citation.entry_id === entryId &&
          citation.anchor_id === anchorId &&
          (role === undefined || citation.role === role)
        ),
    );
    return { removed: before - this.citations.length };
  }

  async listAnchorEntries(anchorId: string): Promise<AnchorEntries> {
    this.record('listAnchorEntries');
    this.requireAnchor(anchorId);
    const entries: CitingEntry[] = [];
    for (const citation of this.citations) {
      if (citation.anchor_id !== anchorId) {
        continue;
      }
      const entry = this.entries.get(citation.entry_id)?.entry;
      if (entry && entry.deleted_at === null) {
        entries.push({
          entry_id: entry.id,
          kind: entry.kind,
          name: entry.name,
          role: citation.role,
          created_at: citation.created_at,
        });
      }
    }
    return { entries };
  }

  /**
   * *Add to bible* - the anchor, the entry, and the citation, in one act (P3-7, `B1`).
   *
   * The version guard runs **first**, so a stale one leaves no anchor, no entry, and no
   * citation. The client sends a range and never a quote; this reads the words out of the
   * stored content, which is an extraction and not a resolution.
   */
  async createEntryFromRange(
    documentId: string,
    input: EntryFromRangeInput,
  ): Promise<EntryFromRange> {
    this.record('createEntryFromRange');
    const stored = this.guardedDocument(documentId, input.version);
    const anchor = this.seedAnchor(documentId, {
      ...this.extract(stored, { from_pos: input.from_pos, to_pos: input.to_pos, version: input.version }),
      status: 'ok',
      label: input.label ?? '',
      from_pos: input.from_pos,
      to_pos: input.to_pos,
    });
    const entry = this.addEntry(
      stored.meta.project_id,
      {
        kind: input.kind,
        name: input.name,
        ...(input.summary === undefined ? {} : { summary: input.summary }),
        ...(input.body_md === undefined ? {} : { body_md: input.body_md }),
        ...(input.attributes === undefined ? {} : { attributes: input.attributes }),
      },
      'created from a selection',
    );
    const role = input.role ?? 'source';
    this.citations.push({
      entry_id: entry.id,
      anchor_id: anchor.id,
      role,
      created_at: FIXED_NOW,
    });
    return { entry: copyEntry(entry), anchor: { ...anchor }, role };
  }

  /**
   * D28's answer - **staged, never computed**.
   *
   * The ordering module is a topological sort with a stated tiebreak, two independent
   * contradiction kinds, and a twenty-case corpus behind it. A second one here would be exactly
   * the second resolver this fake refuses to grow. So every event is reported unplaced until a
   * test says what the server answered, through {@link FakeApiClient.stageStoryTime}.
   */
  async getStoryTime(projectId: string): Promise<StoryTime> {
    this.record('getStoryTime');
    this.requireProject(projectId);
    if (this.stagedStoryTime !== null) {
      return this.stagedStoryTime;
    }
    return {
      order: [],
      unplaced: [...this.entries.values()]
        .map((stored) => stored.entry)
        .filter(
          (entry) =>
            entry.project_id === projectId && entry.deleted_at === null && entry.kind === 'event',
        )
        .sort(byName)
        .map((entry) => ({
          entry_id: entry.id,
          name: entry.name,
          label: '',
          sort_key: null,
          era: null,
        })),
      contradictions: [],
      eras: [],
    };
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

  // -- bible internals ----------------------------------------------------------------------

  private bibleSchema(): BibleSchema {
    this.schemaCache ??= readServerFixture<BibleSchema>('contract/bible_schema.json');
    return this.schemaCache;
  }

  private countsByKind(projectId: string): Record<string, number> {
    // Every kind appears, including the ones with none - so a tab showing only the places can
    // still say how many characters there are.
    const counts: Record<string, number> = {};
    for (const definition of this.bibleSchema().kinds) {
      counts[definition.kind] = 0;
    }
    for (const stored of this.entries.values()) {
      const entry = stored.entry;
      if (entry.project_id === projectId && entry.deleted_at === null) {
        counts[entry.kind] = (counts[entry.kind] ?? 0) + 1;
      }
    }
    return counts;
  }

  private addEntry(projectId: string, input: EntryInput, reason: string): Entry {
    const id = this.nextId('ent');
    const entry: Entry = {
      id,
      project_id: projectId,
      kind: input.kind,
      name: input.name,
      summary: input.summary ?? '',
      body_md: input.body_md ?? '',
      attributes: input.attributes ?? {},
      // Everything a person types is `accepted` and `user`. The other three statuses and `agent`
      // have no writer in this phase.
      status: 'accepted',
      origin: 'user',
      revision: 1,
      needs_review: false,
      review_reason: '',
      created_at: FIXED_NOW,
      updated_at: FIXED_NOW,
      deleted_at: null,
    };
    const stored: StoredEntry = { entry, revisions: [] };
    this.entries.set(id, stored);
    // Revision 1 is the creation, so the history is complete from the beginning and restoring
    // the original is an ordinary restore rather than a special case.
    this.writeRevision(stored, reason, false);
    return stored.entry;
  }

  private writeRevision(stored: StoredEntry, reason: string, retcon: boolean): void {
    const entry = stored.entry;
    stored.revisions.push({
      meta: {
        entry_id: entry.id,
        revision: entry.revision,
        revised_at: FIXED_NOW,
        reason,
        retcon,
        origin: entry.origin,
      },
      // The state **after** the write, so revision *n* is what the entry was at revision *n*.
      // `needs_review` is excluded: it is a note about the entry's surroundings, and restoring
      // must not drag a neighbour's old disturbance back.
      state: {
        kind: entry.kind,
        name: entry.name,
        summary: entry.summary,
        body_md: entry.body_md,
        attributes: entry.attributes,
        status: entry.status,
        origin: entry.origin,
        revision: entry.revision,
        updated_at: entry.updated_at,
        deleted_at: entry.deleted_at,
      },
    });
  }

  /** Set `needs_review` on every dependent, naming what moved. No revision is written on them. */
  private flagDependents(entry: Entry): string[] {
    const flagged: string[] = [];
    const reason = `${entry.name} changed at revision ${entry.revision}`;
    for (const link of this.liveLinksOf(entry.id)) {
      const otherId = link.from_entry === entry.id ? link.to_entry : link.from_entry;
      const dependent = this.entries.get(otherId);
      if (!dependent || dependent.entry.deleted_at !== null || flagged.includes(otherId)) {
        continue;
      }
      dependent.entry = { ...dependent.entry, needs_review: true, review_reason: reason };
      flagged.push(otherId);
    }
    return flagged.sort();
  }

  /** A link is live when it is not deleted **and neither endpoint is** (ruling 9). */
  private isLiveLink(link: Link): boolean {
    if (link.deleted_at !== null) {
      return false;
    }
    const from = this.entries.get(link.from_entry)?.entry;
    const to = this.entries.get(link.to_entry)?.entry;
    return from?.deleted_at === null && to?.deleted_at === null;
  }

  private liveLinksOf(entryId: string): Link[] {
    return [...this.links.values()].filter(
      (link) =>
        this.isLiveLink(link) && (link.from_entry === entryId || link.to_entry === entryId),
    );
  }

  /**
   * One link as it reads from one entry's end.
   *
   * The label comes from the served definition, so a symmetric relation reads the same both ways
   * because its definition repeats its label — rather than because anything here decided to.
   */
  private viewOf(link: Link, entryId: string): LinkView {
    const forward = link.from_entry === entryId;
    const otherId = forward ? link.to_entry : link.from_entry;
    const other = this.entries.get(otherId)?.entry;
    const definition: RelationDefinition | undefined = this.bibleSchema().relations.find(
      (relation) => relation.relation === link.relation,
    );
    return {
      link: { ...link },
      end: forward ? 'from' : 'to',
      other_id: otherId,
      other_name: other?.name ?? otherId,
      other_kind: other?.kind ?? '',
      label: forward
        ? (definition?.label ?? link.relation)
        : (definition?.inverse_label ?? link.relation),
    };
  }

  /** Two rows say the same thing when the pair and the relation match, in either order. */
  private sameStatement(
    link: Link,
    other: { from_entry: string; to_entry: string; relation: string },
  ): boolean {
    if (link.relation !== other.relation) {
      return false;
    }
    return (
      (link.from_entry === other.from_entry && link.to_entry === other.to_entry) ||
      (link.from_entry === other.to_entry && link.to_entry === other.from_entry)
    );
  }

  /** An entry's citations, each carrying the anchor **as it reads now**. */
  private citationsOf(entryId: string): Citation[] {
    const citations: Citation[] = [];
    for (const citation of this.citations) {
      if (citation.entry_id !== entryId) {
        continue;
      }
      const anchor = this.anchors.get(citation.anchor_id);
      if (!anchor) {
        continue;
      }
      const document = this.documents.get(anchor.document_id);
      citations.push({
        entry_id: entryId,
        anchor: this.withEffectiveStatus(anchor),
        role: citation.role,
        created_at: citation.created_at,
        document_id: anchor.document_id,
        document_title: document?.meta.title ?? '',
      });
    }
    return citations;
  }

  /**
   * Where an entry sits in the book — derived from its `source` anchor and never stored.
   *
   * Chapter order, then position. A source in a soft-deleted chapter places nothing: the passage
   * is away, and a position in a chapter no reader can reach would sort the entry into a book it
   * is not in.
   */
  private narrativePosition(
    entryId: string,
    citations: readonly Citation[],
  ): EntryDetail['narrative_position'] {
    let best: { document_id: string; order_index: number; from_pos: number } | null = null;
    for (const citation of citations) {
      if (citation.role !== 'source') {
        continue;
      }
      const document = this.documents.get(citation.document_id);
      if (!document || document.meta.deleted_at !== null) {
        continue;
      }
      const candidate = {
        document_id: citation.document_id,
        order_index: document.meta.order_index,
        from_pos: citation.anchor.from_pos,
      };
      if (
        best === null ||
        candidate.order_index < best.order_index ||
        (candidate.order_index === best.order_index && candidate.from_pos < best.from_pos)
      ) {
        best = candidate;
      }
    }
    return best === null ? null : { entry_id: entryId, ...best };
  }

  private requireEntry(entryId: string, includeDeleted = false): StoredEntry {
    const stored = this.entries.get(entryId);
    if (!stored || (!includeDeleted && stored.entry.deleted_at !== null)) {
      throw new ApiError(
        404,
        ERROR_CODES.entryNotFound,
        `no entry '${entryId}' in this workspace`,
        null,
      );
    }
    return stored;
  }

  private requireLink(linkId: string): Link {
    const link = this.links.get(linkId);
    if (!link) {
      throw new ApiError(
        404,
        ERROR_CODES.linkNotFound,
        `no link '${linkId}' in this workspace`,
        null,
      );
    }
    return link;
  }

  /** D19, applied to entries: a stale revision writes nothing and carries its own code. */
  private guardRevision(entry: Entry, presented: number): void {
    if (entry.revision !== presented) {
      throw new ApiError(
        409,
        ERROR_CODES.entryVersionConflict,
        `entry ${entry.id} is at revision ${entry.revision}, not ${presented}; ` +
          'reload before saving',
        {
          entry_id: entry.id,
          presented_revision: presented,
          current_revision: entry.revision,
          updated_at: entry.updated_at,
        },
      );
    }
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

/** A copy, so a caller mutating what it was handed cannot reach into the store. */
function copyEntry(entry: Entry): Entry {
  return { ...entry, attributes: { ...entry.attributes } };
}

/** `ORDER BY name COLLATE NOCASE, created_at, id` — the order the entry list comes back in. */
function byName(a: Entry, b: Entry): number {
  const left = a.name.toLowerCase();
  const right = b.name.toLowerCase();
  if (left !== right) {
    return left < right ? -1 : 1;
  }
  if (a.created_at !== b.created_at) {
    return a.created_at < b.created_at ? -1 : 1;
  }
  return a.id < b.id ? -1 : 1;
}

/**
 * The `q` filter: a `LIKE` over names, aliases, and summaries.
 *
 * A filter, not search — Phase 5 owns search, and this is deliberately as dumb as `LIKE` is.
 */
function matches(entry: Entry, wanted: string): boolean {
  if (entry.name.toLowerCase().includes(wanted) || entry.summary.toLowerCase().includes(wanted)) {
    return true;
  }
  const aliases = entry.attributes['aliases'];
  return (
    Array.isArray(aliases) &&
    aliases.some((alias) => typeof alias === 'string' && alias.toLowerCase().includes(wanted))
  );
}
