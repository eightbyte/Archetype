-- 001_init.sql - Phase 1 schema (P1-3).
--
-- Forward-only (D20). Later migrations add tables and columns; they never repurpose or remove
-- one of these (outline section 7). No transaction control here - the runner owns BEGIN/COMMIT.

CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL          -- UTC ISO-8601
);

CREATE TABLE project (
    id            TEXT PRIMARY KEY,   -- prj_...
    title         TEXT NOT NULL,
    created_at    TEXT NOT NULL,      -- UTC ISO-8601
    updated_at    TEXT NOT NULL,
    settings_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE document (
    id            TEXT PRIMARY KEY,   -- doc_...
    project_id    TEXT NOT NULL REFERENCES project(id),
    order_index   INTEGER NOT NULL,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'chapter',
    content_json  TEXT NOT NULL,      -- TipTap/ProseMirror JSON (D1, D15)
    text_plain    TEXT NOT NULL,      -- derived server-side on save (D18)
    headings_json TEXT NOT NULL,      -- derived server-side on save (D18)
    word_count    INTEGER NOT NULL,   -- derived server-side on save (D18)
    version       INTEGER NOT NULL,   -- concurrency guard; a stale save is 409 (D19)
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- The document list and the outline both read chapters in order for one project.
-- Deliberately not UNIQUE: Phase 2 reorder needs to move rows through transient duplicates.
CREATE INDEX idx_document_project_order ON document(project_id, order_index);
