/**
 * The wire shapes, mirrored from `server/archetype/api/schemas.py` (P1-5, P1-8).
 *
 * These are held to the server's pydantic models by the contract fixtures: the backend suite
 * writes representative responses to `server/tests/fixtures/contract/*.json`, and
 * `src/__tests__/contract.test.ts` checks them against these types. A shape change on either
 * side fails the suite rather than the browser.
 *
 * Field names are snake_case because the wire is snake_case. Renaming them here would add a
 * translation layer whose only job is to be a place where the two sides can drift apart.
 *
 * Wire schemas are extension-only (outline § 7): add a field, never repurpose or remove one.
 */

import type { Heading, ProseMirrorDocument, ProseMirrorNode } from '../editor/projection';

export type { Heading, ProseMirrorDocument, ProseMirrorNode };

/** `GET /api/health`. */
export interface Health {
  status: string;
  version: string;
}

/** A project as the picker sees it. */
export interface ProjectSummary {
  id: string;
  title: string;
  chapter_count: number;
  word_count: number;
  created_at: string;
  updated_at: string;
}

/**
 * A file in the projects directory that is not a usable project.
 *
 * Reported rather than swallowed: one bad file must not take down the list (P1-12). Only the
 * filename comes over the wire — the browser has no business knowing the directory layout.
 */
export interface SkippedFile {
  name: string;
  reason: string;
  detail: string;
}

/** `GET /api/projects`. */
export interface ProjectList {
  projects: ProjectSummary[];
  skipped: SkippedFile[];
}

/** `GET /api/projects/{pid}` and the body of a successful create. */
export interface ProjectDetail {
  project: ProjectSummary;
  documents: DocumentMeta[];
}

/**
 * A document without its content.
 *
 * The list routes return these deliberately: drawing a chapter list must never pull the whole
 * manuscript (P1-5).
 */
export interface DocumentMeta {
  id: string;
  project_id: string;
  order_index: number;
  title: string;
  kind: string;
  headings: Heading[];
  word_count: number;
  version: number;
  created_at: string;
  updated_at: string;
  /**
   * `null` while the chapter is live; a timestamp once it is soft-deleted (D22).
   *
   * Every list route filters the deleted ones out, so this is `null` in all of them. It is what
   * `listDeletedDocuments` exists to show: a chapter with nothing to say when it went is a
   * chapter nobody can decide about.
   */
  deleted_at: string | null;
}

/** `GET /api/projects/{pid}/documents`. */
export interface DocumentList {
  documents: DocumentMeta[];
}

/**
 * `GET /api/documents/{did}` — metadata plus the content the list leaves out.
 *
 * There is no `text_plain`: the client derives it with the projection mirror rather than having
 * every chapter load carry it twice (D18).
 */
export interface Document {
  id: string;
  project_id: string;
  order_index: number;
  title: string;
  kind: string;
  content_json: ProseMirrorDocument;
  headings: Heading[];
  word_count: number;
  version: number;
  created_at: string;
  updated_at: string;
}

/**
 * What a successful `PUT /api/documents/{did}/content` returns (D18, D19).
 *
 * `anchors` carries every anchor the write **moved** — a changed status, a changed position, or
 * both (P2-7, D21). An empty list is the ordinary answer, and it is the one that says the writer
 * typed above their anchors rather than through them. Replace the client's own mapped positions
 * with these: the mapping is for liveness, this is the truth.
 */
export interface SaveResult {
  document_id: string;
  version: number;
  word_count: number;
  headings: Heading[];
  updated_at: string;
  anchors: Anchor[];
}

/** One chapter in the stitched table of contents. */
export interface OutlineChapter {
  document_id: string;
  title: string;
  order_index: number;
  word_count: number;
  headings: Heading[];
}

/** `GET /api/projects/{pid}/outline` — the TOC across the whole manuscript (D2). */
export interface Outline {
  project_id: string;
  chapters: OutlineChapter[];
}

/** The body of the uniform error envelope. */
export interface ErrorBody {
  code: string;
  message: string;
  detail: unknown;
}

/** Every failing response uses this shape. */
export interface ErrorResponse {
  error: ErrorBody;
}

/**
 * What a `409` carries (D19).
 *
 * Enough for the editor to say what happened and offer a reload without a second round trip.
 * It never merges.
 */
export interface VersionConflictDetail {
  document_id: string;
  presented_version: number;
  current_version: number;
  updated_at: string;
}


/**
 * Where a `stale` anchor's passage may have gone (`specs/anchors.md` § 6).
 *
 * Data on a finding, never an action. Nothing applies one; the writer accepts it, which sends a
 * `PATCH` carrying the range like any other re-link.
 */
export interface AnchorSuggestion {
  from_pos: number;
  to_pos: number;
  text: string;
}

/**
 * A durable reference to a range of manuscript text (P2-7, D21).
 *
 * `status` is `ok` | `stale` | `orphaned`. The last is derived from the anchor's chapter being
 * soft-deleted and is never stored (D22), so restoring the chapter brings back exactly the
 * answer the resolver gave.
 *
 * `from_pos`/`to_pos` are the **server's** last conclusion, not a promise about the document
 * this client is holding. The open document's decorations are rebased through ProseMirror's
 * transaction mapping for liveness, and that rebasing is display-only: it is never sent, and it
 * never overrides what a save answers (D21).
 */
export interface Anchor {
  id: string;
  project_id: string;
  document_id: string;
  from_pos: number;
  to_pos: number;
  quote: string;
  prefix: string;
  suffix: string;
  status: string;
  label: string;
  document_version: number;
  created_at: string;
  updated_at: string;
  checked_at: string;
  suggestion: AnchorSuggestion | null;
}

/** `GET /api/documents/{did}/anchors` and `GET /api/projects/{pid}/anchors`. */
export interface AnchorList {
  anchors: Anchor[];
}

/** The statuses an anchor can report. `orphaned` is derived, never stored (D22). */
export const ANCHOR_STATUSES = {
  ok: 'ok',
  stale: 'stale',
  orphaned: 'orphaned',
} as const;

/** One of the three statuses, narrowed. Anything else on the wire is treated as unexpected. */
export type AnchorStatus = (typeof ANCHOR_STATUSES)[keyof typeof ANCHOR_STATUSES];

/** True when `status` is one of the three a reader can be shown. */
export function isAnchorStatus(status: string): status is AnchorStatus {
  return status === 'ok' || status === 'stale' || status === 'orphaned';
}

/**
 * One entry in a chapter's history (P2-3, D23).
 *
 * Content is deliberately absent, for the reason `DocumentMeta` exists: drawing a chapter's
 * history must not pull every version of that chapter across the wire.
 */
export interface SnapshotMeta {
  id: string;
  project_id: string;
  document_id: string;
  taken_at: string;
  reason: string;
  label: string;
  word_count: number;
  version: number;
  size_bytes: number;
}

/** `GET /api/documents/{did}/snapshots` — newest first. */
export interface SnapshotList {
  snapshots: SnapshotMeta[];
}

/** `GET /api/snapshots/{sid}` — one snapshot with the content a preview needs. */
export interface Snapshot extends SnapshotMeta {
  content_json: ProseMirrorDocument;
}

/**
 * What a capture answers, including "nothing was written, and that is correct".
 *
 * A `handover` whose content the newest snapshot already holds is deduplicated (D23), so
 * handing over a chapter nobody touched writes nothing. That is the ordinary answer, not a
 * failure: `captured` is `false` and the history is unchanged.
 */
export interface SnapshotCapture {
  captured: boolean;
  snapshot: SnapshotMeta | null;
}

/**
 * Why a snapshot was taken.
 *
 * The two a client may ask for, and the three the server writes for itself beside the operation
 * each protects against — a client that could ask for one of those could put a `pre-delete` in
 * the history with nothing deleted.
 */
export const SNAPSHOT_REASONS = {
  handover: 'handover',
  manual: 'manual',
  preRestore: 'pre-restore',
  preDelete: 'pre-delete',
  preImport: 'pre-import',
} as const;

/** The reasons a client may ask for. The rest are the server's own. */
export type SnapshotReasonIn = 'handover' | 'manual';

/**
 * How a Markdown file becomes chapters (P2-14).
 *
 * `one-chapter` makes the whole file one chapter and keeps a leading heading in the text -
 * eating it would be reasonable and would break the round trip the two halves promise each
 * other. `split-on-h1` cuts at every top-level H1 and takes each chapter's title from it, which
 * is the shape the combined export writes.
 */
export const IMPORT_MODES = {
  oneChapter: 'one-chapter',
  splitOnH1: 'split-on-h1',
} as const;

export type ImportMode = (typeof IMPORT_MODES)[keyof typeof IMPORT_MODES];

/**
 * One thing an import could not keep, and what became of it (P2-14).
 *
 * Never an error. Where the construct carried words, the words are in the chapter and only the
 * formatting is gone; `detail` says which happened, and `line` points into the file the writer
 * chose. This list is what stops an import being a silent edit of somebody's file.
 */
export interface ImportNotice {
  element: string;
  line: number;
  detail: string;
}

/** What an import created, and what it could not keep. `dropped` is empty far more often. */
export interface MarkdownImport {
  documents: DocumentMeta[];
  dropped: ImportNotice[];
}

/**
 * What a refused reorder carries (P2-2).
 *
 * The completeness check is the concurrency guard, so the refusal says which way the presented
 * list failed to describe the project. The client's answer is to re-read the chapter list, not
 * to correct a field.
 */
export interface ReorderMismatchDetail {
  missing: string[];
  unexpected: string[];
  duplicated: string[];
}

/** The `code` values the client branches on. Others are possible; treat them as unexpected. */
export const ERROR_CODES = {
  projectNotFound: 'project_not_found',
  documentNotFound: 'document_not_found',
  anchorNotFound: 'anchor_not_found',
  snapshotNotFound: 'snapshot_not_found',
  invalidAnchorRange: 'invalid_anchor_range',
  versionConflict: 'version_conflict',
  reorderMismatch: 'reorder_mismatch',
  invalidDocument: 'invalid_document',
  payloadTooLarge: 'payload_too_large',
  validation: 'validation_error',
  internal: 'internal_error',
  entryNotFound: 'entry_not_found',
  linkNotFound: 'link_not_found',
  revisionNotFound: 'revision_not_found',
  entryVersionConflict: 'entry_version_conflict',
  duplicateLink: 'duplicate_link',
  invalidAttributes: 'invalid_attributes',
} as const;

/* -------------------------------------------------------------------------------------------
 * The story bible (P3-9 … P3-11, D25 – D28).
 *
 * Seven kinds share one record, and the difference between them is **data** (D26): the per-kind
 * field list and the relation vocabulary arrive from `GET /api/bible/schema`, and the client
 * renders one generic form over the six field types. Nothing below spells out which kinds exist
 * or which relations there are — a copy here would be the second copy D26 exists to prevent, and
 * it would be the one that drifts.
 * ---------------------------------------------------------------------------------------- */

/** One bible record, in the shape every kind shares. */
export interface Entry {
  id: string;
  project_id: string;
  kind: string;
  name: string;
  summary: string;
  body_md: string;
  /** The per-kind fields, validated server-side against the kind's definition. */
  attributes: Record<string, unknown>;
  status: string;
  origin: string;
  /** Monotonic. The D19 guard, applied to entries — an update presents the one it read. */
  revision: number;
  /**
   * "Something this entry depended on moved" (D27).
   *
   * Orthogonal to `status`: one is the retcon flag, the other is the proposal lifecycle.
   * `superseded` is not the answer to "this entry is out of date".
   */
  needs_review: boolean;
  review_reason: string;
  created_at: string;
  updated_at: string;
  /** `null` while the entry is live; a timestamp once it is soft-deleted (D25). */
  deleted_at: string | null;
}

/**
 * `GET /api/projects/{pid}/entries` and `…/entries/deleted`.
 *
 * `counts` is live and **unfiltered**, so a list showing only the places can still say how many
 * characters there are. `truncated` says the `q` filter hit its cap — a filter that cannot say
 * "there are more" is lying about what it found.
 */
export interface EntryList {
  entries: Entry[];
  counts: Record<string, number>;
  truncated: boolean;
}

/**
 * Where an entry sits in the book, derived from its `source` anchor and never stored.
 *
 * It follows a chapter reorder for free, and an entry with no source anchor simply has none.
 */
export interface NarrativePosition {
  entry_id: string;
  document_id: string;
  order_index: number;
  from_pos: number;
}

/**
 * One citation, carrying the anchor **as it reads now** (P3-7).
 *
 * The anchor's `status` is the effective one, derived server-side in the single place D22 put it
 * — so a citation can never disagree with the *Marks* tab about the same anchor. A `stale` one
 * means the passage that produced this entry has been rewritten.
 */
export interface Citation {
  entry_id: string;
  anchor: Anchor;
  role: string;
  created_at: string;
  document_id: string;
  document_title: string;
}

/** `GET /api/entries/{eid}` — one entry with what points at it and where it sits. */
export interface EntryDetail {
  entry: Entry;
  citations: Citation[];
  /** Live links in either direction. The links themselves are a separate request. */
  link_count: number;
  narrative_position: NarrativePosition | null;
}

/**
 * What an entry write did, including what it disturbed (D27).
 *
 * `flagged` is the point: the writer is told which entries this retcon put into the review queue
 * at the moment it happens. `changed_fields` reports the **computed** answer even when `retcon`
 * was overridden, so an override is legible as one.
 */
export interface EntryWriteResult {
  entry: Entry;
  revision: number;
  retcon: boolean;
  flagged: string[];
  changed_fields: string[];
}

/** One revision's metadata. The history list carries these and never the states. */
export interface RevisionMeta {
  entry_id: string;
  revision: number;
  revised_at: string;
  reason: string;
  retcon: boolean;
  origin: string;
}

/** `GET /api/entries/{eid}/revisions` — newest first, complete from creation. */
export interface RevisionList {
  revisions: RevisionMeta[];
}

/**
 * `GET /api/entries/{eid}/revisions/{n}` — one revision with the state it recorded.
 *
 * `state` is the entry as it was **after** that write, so reading a past state is one row rather
 * than a replay. It carries no `needs_review`: that is a note about the entry's surroundings, and
 * restoring must not drag a neighbour's old disturbance back.
 */
export interface EntryRevision {
  meta: RevisionMeta;
  state: Record<string, unknown>;
}

/**
 * One relationship, as stored.
 *
 * `since` and `until` are free text and are stored, displayed, and **never interpreted** (D9).
 * Nothing sorts by them; the relation that carries ordering power is `precedes`.
 */
export interface Link {
  id: string;
  project_id: string;
  from_entry: string;
  to_entry: string;
  relation: string;
  attributes: Record<string, unknown>;
  since: string | null;
  until: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

/** `GET /api/projects/{pid}/links` — every live link, optionally of one relation. */
export interface LinkList {
  links: Link[];
}

/** Which end of a link an entry is on. */
export const LINK_ENDS = {
  from: 'from',
  to: 'to',
} as const;

export type LinkEnd = (typeof LINK_ENDS)[keyof typeof LINK_ENDS];

/**
 * One link as it reads **from one entry's end**.
 *
 * `label` is how that end reads the relation — "is a member of" from one side, "has as a member"
 * from the other. A symmetric relation reads the same both ways and appears once from each side,
 * never twice from either: it is one row.
 */
export interface LinkView {
  link: Link;
  end: string;
  other_id: string;
  other_name: string;
  other_kind: string;
  label: string;
}

/** `GET /api/entries/{eid}/links` — both directions in one answer. */
export interface EntryLinks {
  links: LinkView[];
}

/** Why an entry points at a passage. `source` is the one narrative position derives from. */
export const CITATION_ROLES = {
  source: 'source',
  mention: 'mention',
  setup: 'setup',
  payoff: 'payoff',
} as const;

export type CitationRole = (typeof CITATION_ROLES)[keyof typeof CITATION_ROLES];

/** What an uncite removed. Zero is an ordinary answer, not a failure. */
export interface CitationRemoved {
  removed: number;
}

/** One entry that cites an anchor — the reverse view, so *Marks* can say it is spoken for. */
export interface CitingEntry {
  entry_id: string;
  kind: string;
  name: string;
  role: string;
  created_at: string;
}

/** `GET /api/anchors/{aid}/entries`. */
export interface AnchorEntries {
  entries: CitingEntry[];
}

/**
 * What *Add to bible* made: an anchor, an entry, and the citation joining them (P3-7).
 *
 * One transaction over three tables, so a stale document version leaves none of them behind. The
 * client sends a range and a version and never a quote — the server derives the words.
 */
export interface EntryFromRange {
  entry: Entry;
  anchor: Anchor;
  role: string;
}

/**
 * One event as the ordering sees it (D28).
 *
 * `label` is what a person reads as "when" and it **never sorts**. `sort_key` is the only number
 * in story-time, and it is a float so an event can be inserted between two others.
 */
export interface StoryEvent {
  entry_id: string;
  name: string;
  label: string;
  sort_key: number | null;
  era: string | null;
}

/** The two contradiction kinds, and there are no others (D28). */
export const CONTRADICTION_KINDS = {
  cycle: 'cycle',
  sortKeyInversion: 'sort_key_inversion',
} as const;

export type ContradictionKind = (typeof CONTRADICTION_KINDS)[keyof typeof CONTRADICTION_KINDS];

/**
 * Something the writer said that cannot all be true at once.
 *
 * The two kinds are **independent**: an edge inside a cycle whose keys also disagree is reported
 * as both, because a writer fixes them differently.
 */
export interface StoryTimeContradiction {
  kind: string;
  events: string[];
  detail: string;
}

/** One era and its rank — the least `sort_key` among its members, or `null` for unplaced. */
export interface StoryTimeEra {
  era: string;
  rank: number | null;
}

/**
 * `GET /api/projects/{pid}/storytime` — the ordering module's three answers, and the eras.
 *
 * `order` and `unplaced` partition the events: every event is in exactly one of them. An event
 * with neither an edge nor a key is unplaced — not appended, not dropped, and never guessed at.
 * A contradiction never costs the rest of the graph.
 */
export interface StoryTime {
  order: StoryEvent[];
  unplaced: StoryEvent[];
  contradictions: StoryTimeContradiction[];
  eras: StoryTimeEra[];
}

/**
 * The six field types a form renders (D26). Closed, and a test on each side of the wire enforces
 * it: a seventh must fail here rather than render nothing.
 */
export const FIELD_TYPES = {
  text: 'text',
  longText: 'long_text',
  listOfText: 'list_of_text',
  enum: 'enum',
  entryRef: 'entry_ref',
  storyTime: 'story_time',
} as const;

export type FieldType = (typeof FIELD_TYPES)[keyof typeof FIELD_TYPES];

/** True when `type` is one of the six the form has a renderer for. */
export function isFieldType(type: string): type is FieldType {
  return (Object.values(FIELD_TYPES) as string[]).includes(type);
}

/**
 * One field of one kind, with every key present whatever the type.
 *
 * `members` is the declared set of an `enum` and empty otherwise; `kinds` is what an `entry_ref`
 * may point at and empty otherwise. Both always arrive, so the renderer branches on `type` alone.
 */
export interface FieldDefinition {
  name: string;
  type: string;
  label: string;
  required: boolean;
  help: string;
  members: string[];
  kinds: string[];
}

/** One kind's fields, **in the order a form renders them**. */
export interface KindDefinition {
  kind: string;
  label: string;
  plural: string;
  fields: FieldDefinition[];
}

/**
 * One relation and the kinds it may join in each direction.
 *
 * `symmetric` is declared rather than inferred, so a relation picker filtered by the two kinds
 * asks the vocabulary instead of keeping its own list.
 */
export interface RelationDefinition {
  relation: string;
  label: string;
  inverse_label: string;
  from_kinds: string[];
  to_kinds: string[];
  symmetric: boolean;
}

/**
 * `GET /api/bible/schema` — D26's definition, and the most load-bearing shape in Phase 3.
 *
 * Project-independent: the vocabulary is the product's, not a manuscript's. Everything in the
 * Bible tab renders from it, so its contract fixture is what fails when a kind gains a field and
 * the client was not told.
 */
export interface BibleSchema {
  field_types: string[];
  kinds: KindDefinition[];
  relations: RelationDefinition[];
}

/** What an entry's `409` carries (D19, ruling 3). The form stops and offers the server's copy. */
export interface EntryVersionConflictDetail {
  entry_id: string;
  presented_revision: number;
  current_revision: number;
  updated_at: string;
}

/** What a refused attribute, kind, relation, or role carries. `field` names the input. */
export interface InvalidAttributesDetail {
  field: string | null;
}

/** What a refused duplicate link carries: the live link that already says the same thing. */
export interface DuplicateLinkDetail {
  link_id: string;
}
