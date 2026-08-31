-- 002_anchors_and_snapshots.sql - Phase 2 (P2-1, D22, D23).
--
-- Forward-only (D20) and extension-only (outline section 7): one column added to `document`,
-- two tables added. Nothing is repurposed and nothing is removed. Tested against
-- tests/fixtures/db/v001_phase1.sqlite, a real Phase 1 project file captured before this
-- migration existed.
--
-- No transaction control here - the runner owns BEGIN/COMMIT.

-- D22: a soft delete. NULL means live; a timestamp means the chapter is out of every list,
-- outline, export, and count, while its row and its text stay exactly where they were. Every
-- read path filters on this one predicate.
ALTER TABLE document ADD COLUMN deleted_at TEXT;

-- A durable reference to a range of manuscript text (D21).
--
-- `from_pos`/`to_pos` are ProseMirror positions and are the fast path, not the truth: the truth
-- is `quote`, matched in `text_plain` and disambiguated by `prefix` and `suffix`. The server
-- re-resolves every anchor of a document from that document's own text on every write, and its
-- answer is authoritative; these columns are a cache of the last write's answer.
--
-- `status` holds the *text-match* answer only - `ok` or `stale`. `orphaned` is derived on read
-- from the owning document's `deleted_at`, never stored: a soft delete changes no text, so the
-- cached text answer stays exactly as true while the chapter is away as it was before it went,
-- and restoring is correct without re-running the resolver (phase-2-plan section 7).
CREATE TABLE anchor (
    id               TEXT PRIMARY KEY,                    -- anc_...
    project_id       TEXT NOT NULL REFERENCES project(id),
    document_id      TEXT NOT NULL REFERENCES document(id),
    from_pos         INTEGER NOT NULL,                    -- ProseMirror positions, the fast path
    to_pos           INTEGER NOT NULL,
    quote            TEXT NOT NULL,
    prefix           TEXT NOT NULL,
    suffix           TEXT NOT NULL,
    status           TEXT NOT NULL,                       -- ok | stale
    label            TEXT NOT NULL DEFAULT '',
    document_version INTEGER NOT NULL,                    -- the version those positions held at
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    checked_at       TEXT NOT NULL                        -- when resolution last ran
);

-- A versioned copy of one chapter (D23). Taken on handover, on demand, and before anything
-- destructive; deduplicated by `content_hash`; `handover` snapshots are pruned to the newest 25
-- per document, and manual and pre-* snapshots are kept forever.
CREATE TABLE snapshot (
    id           TEXT PRIMARY KEY,                        -- snp_...
    project_id   TEXT NOT NULL REFERENCES project(id),
    document_id  TEXT NOT NULL REFERENCES document(id),
    taken_at     TEXT NOT NULL,
    reason       TEXT NOT NULL,   -- handover|manual|pre-restore|pre-delete|pre-import
    label        TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,                           -- sha-256 of content_json; dedupe
    word_count   INTEGER NOT NULL,
    version      INTEGER NOT NULL                         -- the document version this content was
);

-- The editor loads one document's anchors in position order; the Marks tab finds what needs
-- repair across the project; the snapshot list reads newest-first for one chapter.
CREATE INDEX idx_anchor_document       ON anchor(document_id, from_pos);
CREATE INDEX idx_anchor_project_status ON anchor(project_id, status);
CREATE INDEX idx_snapshot_document     ON snapshot(document_id, taken_at DESC);
