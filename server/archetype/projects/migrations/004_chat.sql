-- 004_chat.sql - Phase 4, where a conversation lives (P4-4, D30).
--
-- Forward-only (D20) and extension-only (outline section 7): two tables added, nothing
-- repurposed, nothing removed, and **not one column changed** on any of the nine tables Phases 1
-- to 3 built. Phase 4 adds no manuscript and no bible behaviour; it reads both through the stores
-- that already exist and writes to neither.
--
-- Tested against tests/fixtures/db/v003_phase3.sqlite, a real Phase 3 project file - two live
-- chapters with anchors, one soft-deleted chapter that also carries an anchor, two snapshots, a
-- bible with all four of its tables populated (including an entry created *from a range*, a
-- retcon that left a dependent flagged, and a soft-deleted entry) - captured before this
-- migration was written. A version-1 file therefore migrates three steps in one open, and the
-- earlier migrations' own fixture tests are unchanged.
--
-- No transaction control here - the runner owns BEGIN/COMMIT.

-- A chat conversation (D30). Project-scoped like everything else (D6) and soft-deleted like
-- everything else (D22, D25): the row and its messages stay, and restoring is one act.
--
-- **A Phase 4 turn is explicitly not a Phase 6 run.** Phase 6's `run` table, when it arrives,
-- will *reference a message* rather than replace one - a run is what produced one assistant
-- turn. Writing that shape now would be a schema guessed two phases early, bent around a
-- completion that has no plan and no tool calls, and D20's forward-only rule makes guessing
-- wrong a migration to undo rather than an edit.
--
-- There is no `version` column and no D19 guard. A conversation has no concurrent-edit surface:
-- messages are appended, never rewritten, and the title is the only mutable field on it.
CREATE TABLE conversation (
    id          TEXT PRIMARY KEY,                    -- cnv_...
    project_id  TEXT NOT NULL REFERENCES project(id),
    title       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT                                 -- NULL = live (D22, D25)
);

-- One turn. Appended, never edited: an assistant message is a record of what was said and what
-- it cost, and editing one would make the transcript a claim about a conversation that never
-- happened.
--
-- `context_json` is what makes a bad answer diagnosable (plan section 2, ruling 5): the
-- selection, how much of the surrounding chapter came with it, which bible entries were included
-- and why, and the token estimate - the same thing the panel shows *before* sending. The
-- outline's standing invariant is "the composed context is recorded on the run record"; Phase 4
-- has no run record, so it lands here, and Phase 6's run will reference this row.
--
-- `usage_json` holds the port's Usage as the provider reported it. Absent usage means "not
-- reported" and not "free" (specs/providers.md section 2), so the panel says so rather than
-- drawing a confident zero.
--
-- `error_code` carries one of the six provider error codes when a turn failed (ruling 4). A
-- failed answer is **persisted**: a turn that went wrong is visible in the history rather than
-- being a gap the writer has to remember, and the code is what says why.
--
-- `stop_reason` is the port's normalised vocabulary and is how a **cancelled** turn stays
-- distinguishable from a complete one after a reload (D11, section 8 step 7). It is not in the
-- plan's DDL sketch; the deviation and its argument are phase-4-plan section 7, `A1`.
--
-- `provider` and `model` are recorded per message rather than per conversation, because D34's
-- whole point is that swapping providers is a settings change with no code change - so two
-- consecutive turns in one conversation may legitimately have come from different models, and a
-- transcript that could not say which would make section 8's step 12 unreadable.
CREATE TABLE message (
    id              TEXT PRIMARY KEY,                -- msg_...
    conversation_id TEXT NOT NULL REFERENCES conversation(id),
    ord             INTEGER NOT NULL,                -- position in the conversation
    role            TEXT NOT NULL,                   -- user|assistant|system
    content         TEXT NOT NULL,
    context_json    TEXT NOT NULL DEFAULT '{}',      -- what was composed and sent (ruling 5)
    provider        TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    usage_json      TEXT NOT NULL DEFAULT '{}',
    stop_reason     TEXT NOT NULL DEFAULT '',        -- the port's closed set; '' = not finished
    error_code      TEXT NOT NULL DEFAULT '',        -- one of the six (ruling 4); '' = no failure
    created_at      TEXT NOT NULL
);

-- The panel lists one project's live conversations newest first, and opens one in `ord`.
CREATE INDEX idx_conversation_project ON conversation(project_id, updated_at);
CREATE UNIQUE INDEX idx_message_conversation ON message(conversation_id, ord);
