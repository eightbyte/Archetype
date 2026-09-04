-- 003_bible.sql - Phase 3, the story bible (P3-2, D25, D26, D27, D28).
--
-- Forward-only (D20) and extension-only (outline section 7): four tables added, nothing
-- repurposed, nothing removed, and **not one column changed on `document`, `anchor`, or
-- `snapshot`**. Phase 3 adds no manuscript behaviour; it reads anchors through AnchorStore and
-- creates them through AnchorStore.create, which is the only path there has ever been.
--
-- Tested against tests/fixtures/db/v002_phase2.sqlite, a real Phase 2 project file - two live
-- chapters with anchors in both, one soft-deleted chapter that also carries an anchor, and two
-- snapshots - captured before this migration was written. A version-1 file therefore migrates
-- two steps in one open, and migration 002's own test against v001_phase1.sqlite is unchanged.
--
-- No transaction control here - the runner owns BEGIN/COMMIT.

-- One uniform record for all seven kinds (D26). The difference between a character and a place
-- is `kind` plus the contents of `attributes_json`, validated against the per-kind definition in
-- archetype/bible/schema.py and served by GET /api/bible/schema. Seven tables would mean seven
-- of every store, route, form, and - in Phase 7 - seven branches in one review queue.
--
-- `kind` is immutable after creation: every attribute the row holds was validated against that
-- kind's field list, so changing it would either destroy typed work silently or leave data in
-- `attributes_json` the served definition does not describe (specs/bible.md section 1).
--
-- `status` and `origin` carry vocabularies with no writer in this phase. Everything a person
-- types is 'accepted' and 'user'; 'proposed', 'rejected', 'superseded', and 'agent' are Phase
-- 7's, registered here so the proposal queue lands in a shape storage already understands -
-- exactly as 'pre-import' was registered in Phase 2 with nothing to write it.
--
-- `needs_review` is orthogonal to `status`: one is the proposal lifecycle, the other is
-- "something this depended on moved" (D27).
CREATE TABLE entry (
    id              TEXT PRIMARY KEY,                    -- ent_...
    project_id      TEXT NOT NULL REFERENCES project(id),
    kind            TEXT NOT NULL,                       -- character|place|item|faction|event|thread|fact
    name            TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    body_md         TEXT NOT NULL DEFAULT '',            -- Markdown as text, not as a schema
    attributes_json TEXT NOT NULL DEFAULT '{}',          -- the per-kind fields (D26)
    status          TEXT NOT NULL,                       -- proposed|accepted|rejected|superseded
    origin          TEXT NOT NULL,                       -- user|agent
    revision        INTEGER NOT NULL,                    -- monotonic; the D19 guard
    needs_review    INTEGER NOT NULL DEFAULT 0,          -- the retcon flag (D27)
    review_reason   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    deleted_at      TEXT                                 -- NULL = live (D25)
);

-- Every entry write records one of these, holding the entry's full state AFTER the change - so
-- revision n is what the entry was at revision n, and revision 1 is its creation. Reading any
-- past state is one row, not a replay.
--
-- Nothing here is deduplicated and nothing is pruned, which is the deliberate opposite of D23's
-- handover snapshot on both counts: that is 300 KB nobody asked for, and this is two kilobytes
-- somebody typed.
--
-- `retcon` records whether this write flagged dependents. It is the store's computed answer
-- unless the request overrode it (D27), and it is what the history shows the writer.
CREATE TABLE entry_revision (
    entry_id      TEXT NOT NULL REFERENCES entry(id),
    revision      INTEGER NOT NULL,                      -- 1 is creation
    revised_at    TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    retcon        INTEGER NOT NULL DEFAULT 0,            -- did this write flag dependents?
    origin        TEXT NOT NULL,                         -- user|agent
    snapshot_json TEXT NOT NULL,                         -- the entry's full state AFTER the change
    PRIMARY KEY (entry_id, revision)
);

-- A relationship between two entries, from the closed vocabulary (D26).
--
-- Directed in storage, and possibly symmetric in meaning: a relation the definition marks
-- `symmetric` is stored ONCE and read from both ends. Storing it twice would mean two rows that
-- can disagree, and a Phase 8 adjacency matrix that double-counts.
--
-- `since` and `until` are story-time bounds (D9): free text, stored, displayed, and never
-- interpreted. Nothing in Phase 3 or Phase 8 sorts by them.
--
-- A link is live only when it is not deleted AND NEITHER ENDPOINT is deleted - the three-way
-- predicate (D25). It lives in exactly one place in the code; forgetting a leg puts a deleted
-- character back into a relationship view and surfaces two phases later as a wrong chart.
CREATE TABLE entry_link (
    id              TEXT PRIMARY KEY,                    -- lnk_...
    project_id      TEXT NOT NULL REFERENCES project(id),
    from_entry      TEXT NOT NULL REFERENCES entry(id),
    to_entry        TEXT NOT NULL REFERENCES entry(id),
    relation        TEXT NOT NULL,                       -- from the closed vocabulary (D26)
    attributes_json TEXT NOT NULL DEFAULT '{}',
    since           TEXT,                                -- story-time bounds (D9), free text
    until           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    deleted_at      TEXT                                 -- NULL = live (D25)
);

-- A citation: an entry pointing at the passage that produced it, through a Phase 2 anchor.
--
-- An entry may cite one anchor in more than one role, which is why all three columns are the
-- key. Deleting an anchor removes its citations and leaves the entries; soft-deleting an entry
-- leaves its citations and its anchors untouched. An entry's narrative position is DERIVED from
-- its `source` anchor's document order_index and from_pos, and is never stored - so it moves
-- when the writer reorders chapters, for free.
CREATE TABLE entry_anchor (
    entry_id   TEXT NOT NULL REFERENCES entry(id),
    anchor_id  TEXT NOT NULL REFERENCES anchor(id),
    role       TEXT NOT NULL,                            -- source|mention|setup|payoff
    created_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, anchor_id, role)
);

-- The browser lists one project's entries of one kind by name; the review queue finds the
-- flagged ones; the link views read from each end; the Marks tab asks what cites an anchor.
CREATE INDEX idx_entry_project_kind  ON entry(project_id, kind, name);
CREATE INDEX idx_entry_review        ON entry(project_id, needs_review);
CREATE INDEX idx_link_from           ON entry_link(from_entry, relation);
CREATE INDEX idx_link_to             ON entry_link(to_entry, relation);
CREATE INDEX idx_entry_anchor_anchor ON entry_anchor(anchor_id);
