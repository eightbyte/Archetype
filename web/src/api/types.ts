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

import type { Heading, ProseMirrorDocument } from '../editor/projection';

export type { Heading, ProseMirrorDocument };

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

/** The `code` values the client branches on. Others are possible; treat them as unexpected. */
export const ERROR_CODES = {
  projectNotFound: 'project_not_found',
  documentNotFound: 'document_not_found',
  anchorNotFound: 'anchor_not_found',
  invalidAnchorRange: 'invalid_anchor_range',
  versionConflict: 'version_conflict',
  invalidDocument: 'invalid_document',
  payloadTooLarge: 'payload_too_large',
  validation: 'validation_error',
  internal: 'internal_error',
} as const;
