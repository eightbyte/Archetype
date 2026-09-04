# Phase 3 — Story Bible (manual)

**Status:** **COMPLETE (2026-09-04)** — § 2 **ruled**: D25–D29 are binding and promoted to the
register, both reversals accepted, closing backlog `Q2` and `Q7`. **All four groups delivered**
(`P3-1` … `P3-15`), and **§ 8's fifteen-step acceptance run passed on 2026-09-04**, run by hand
against the single-process build. Two steps passed with findings (§ 7, `E1` and `E2`); `E2` is a
real display defect the run found in the one edit shape no test makes, fixed with two new tests
and step 12 re-run against the fix. **All ten exit criteria in § 5 are met.** Both suites green —
**1,147 backend, 526 frontend**.
**Version:** 1.5 · **Date:** 2026-09-04
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1
**Writes:** `specs/bible.md` (P3-1) · completes [`specs/data-model.md`](data-model.md) and extends
[`specs/api-contract.md`](api-contract.md) (P3-15)
**Settles:** backlog `Q2` (entry deletion) and `Q7` (H1 in chapter bodies)

---

## 1. What this phase is for

Phase 1 made Archetype a place you can write. Phase 2 made what you wrote **referenceable**.
Phase 3 makes it **known**.

The story bible is the structured record of the narrative: who is in it, where it happens, what
happened, what is true. It is the thing the agent maintains in Phase 7, the thing the timeline and
the interaction chart are drawn from in Phase 8, and the thing continuity checking is checked
*against*. All of that is later. This phase builds it **by hand**, completely, with no AI anywhere
near it — because the outline's third principle is that every AI feature has a manual path first,
and because an extraction run in Phase 7 needs a real API to target and a real review surface to
land in (development-phases § 2, ordering constraints).

Four things arrive together:

- **The entry** — one uniform record with a `kind` discriminator, so that one store, one search,
  one revision history, and (in Phase 7) one review queue serve all seven kinds. Seven bespoke
  tables would mean seven of each.
- **Links** — the relationships between entries, with optional story-time bounds (D9). The
  interaction chart and the timeline are *derived* from links and events in Phase 8, not
  separately maintained, so the links have to be right here.
- **Citations** — an entry points at the passage that produced it, through a Phase 2 anchor. This
  is the phase where anchors acquire their first real consumer, and where the whole Phase 2 budget
  either pays for itself or does not.
- **Revisions and retcon** — editing an entry writes history, and a change that moves established
  facts flags the entries that depended on them. The outline calls stale conclusions after a retcon
  a top-eight risk (§ 9): a continuity check against an outdated record is worse than no check.

The acceptance bar is the outline's, unchanged: **build a bible for a test story entirely by hand,
then retcon an entry and see its dependents flagged.** Not "the tables exist" — *usable by hand*,
because Phase 7's job is to feed a surface a writer already trusts.

**One thing this phase is not allowed to become.** Seven kinds, each with its own fields, each with
its own form, is how this phase turns into a quarter of hand-written UI that all does the same
thing slightly differently. § 2's D26 is the answer: the record is uniform, the per-kind field list
is **data served by the API**, and the client renders one generic form over a closed set of six
field types. Adding an eighth kind is then a data change, and Phase 7's proposals land in the same
shape as a typed one.

### Non-goals for Phase 3

Named explicitly, because each is a plausible thing to drift into:

- **No AI, no chat, no WebSocket, no provider, no extraction.** Still not even a stub route
  (api-contract § 12). The `proposed` and `rejected` entry statuses and the `agent` origin are
  written into the vocabulary and have **no writer in this phase** — exactly as `pre-import` was
  registered in Phase 2 with nothing to write it ([phase-2-plan](phase-2-plan.md) § 7, `D1`).
- **No FTS5, no embeddings, no vector index, no `/search` route.** Phase 3's entry search is a
  `LIKE` filter over names, aliases, and summaries, reached as a *filter parameter on the entry
  list*. Phase 5 owns search, and it owns the route name (§ 2, ruling 4).
- **No timeline view and no interaction chart.** Phase 8 owns both. Phase 3 stores story-time and
  delivers the pure ordering module underneath a timeline (P3-8), and renders neither.
- **No bible export, and no bible in the Markdown export.** D15's two exports are the manuscript;
  the project bundle is Phase 9.
- **No entity detection.** Nothing scans prose for names and offers to make an entry. That is
  extraction, it is Phase 7, and it is on the far side of the proposal queue (D5).
- **No auto-linking.** A link is typed by a person. An entry mentioning another entry's name in its
  body creates nothing.
- **No merge or dedup of entries.** Phase 7 needs it because extraction produces near-duplicates;
  a person typing does not.
- **No new manuscript behaviour.** Phase 3 adds no route, column, or rule to `document`,
  `anchor`, or `snapshot`, and does not touch the save protocol. It reads anchors through
  `AnchorStore` and creates them through `AnchorStore.create` — the only path there has ever been.
- **No styling investment beyond legibility**, as in Phases 1 and 2.

---

## 2. Confirm before code

The same reasoning as Phase 1's § 2 and Phase 2's: a ruling made before files exist costs nothing,
and the same ruling made in Phase 7 is a migration. Five of these become binding register entries,
and two settle backlog questions that are due this phase.

**Two of them reverse a recorded leaning** (`Q2` and `Q7`). Both reversals were argued below rather
than assumed, and both were put to the writer as reversals; both were accepted on 2026-09-01.

### Register entries — D25 to D29

**Ruled by the writer on 2026-09-01, all five as recommended, including both reversals.** They are
promoted to [`specs/development-phases.md`](development-phases.md) § 1, which is where they now
bind; this table stays as the reasoning behind them.

| ID | Proposed decision | Recommendation | Alternative considered | Where it bites if wrong |
|---|---|---|---|---|
| **D25** | What deleting a bible entry does (**settles `Q2`**) | **A soft delete, exactly as D22.** `entry` and `entry_link` each carry a nullable `deleted_at`; the row, its revisions, its links, and its citations all stay. The entry leaves every list, count, and link view; restoring it is one click and brings its links back with it. | `Q2`'s recorded leaning — revision history is enough, `superseded` covers retcons. **Recommended against, on a structural argument rather than a preference:** an entry is the target of *links*, and a hard delete either cascades those links away or leaves them dangling — which is the identical argument D22 made about snapshots pointing at a removed document, and it was a release blocker then. Revision history is also the wrong tool: it is a record of what an entry *said*, and making it double as the recovery path means a route that lists the revisions of a row that no longer exists. One nullable column and one predicate, twice, is the same cheap price D22 paid, and it leaves the app with **one** deletion idiom rather than two. | The migration, every entry and link query, the link predicate, the review queue |
| **D26** | How the seven kinds differ, and where that difference is written | **The record is uniform and the difference is data.** One `entry` table with a `kind` discriminator and an `attributes_json` blob; the per-kind field list and the link relation vocabulary live in **one server-side definition**, served by `GET /api/bible/schema`, and the client renders one generic form over a **closed set of six field types** (`text`, `long_text`, `list_of_text`, `enum`, `entry_ref`, `story_time`). Adding a kind, a field, or a relation is a change to that definition and nothing else. The field-type list is closed and a test enforces it, in the same way and for the same reason the editor's node list is (D1). | A pydantic model per kind, with seven request schemas and seven forms. Rejected: it multiplies every future change by seven, and Phase 7's proposal queue would need a branch per kind to render a proposed entry. The middle option — models on the server, generic forms on the client — was also rejected, because then the field list exists twice and the second copy is the one that drifts. | The whole client surface, the wire schemas, Phase 7's proposal rendering, Phase 8's chart |
| **D27** | What a revision is, and what a retcon flags | **Every entry write records a revision; only a write marked as a *retcon* flags dependents.** A revision stores the entry's full state **after** the change, so revision *n* is what the entry was at revision *n*, and revision 1 is its creation. Nothing is deduplicated and nothing is pruned — an entry is kilobytes and every revision is a person's deliberate act, which is the opposite of a `handover` snapshot on both counts (D23). **A dependent is an entry joined to the changed one by a live link, in either direction** — the only relationship the data actually knows. Flagging sets `needs_review` with a reason naming the entry and the revision that caused it; the writer clears it. The store *computes* whether a write is a retcon — true when `name`, `attributes_json`, or `status` changed, false for a `summary`- or `body_md`-only edit — and the request may override the answer in either direction. | Flag on every edit (the outline § 4.3 wording taken literally). Rejected: fixing a typo in a body would flag every neighbour, the flag becomes noise within a day, and a noisy flag is an ignored flag — which is the failure mode this exists to prevent. Also rejected: inferring dependents from prose mentions, which is retrieval wearing a costume, and is Phase 5's machinery arriving three phases early with no index behind it. | The revision table, the review queue, Phase 7's findings, and whether the writer trusts the flag |
| **D28** | How story-time is stored and ordered (**D9 made concrete**) | **Story-time is a partial order, not a number.** An `event` carries an optional `story_time` attribute — `label` (free text, what is displayed), an optional numeric `sort_key`, and an optional `era` name — and **ordering constraints are links**: `precedes` between two events. A pure module (P3-8) returns the topological order refined by `sort_key`, the events it could not place, and the **contradictions**, of which there are exactly two kinds: a cycle in `precedes`, and an edge `A precedes B` where both carry a `sort_key` and `A`'s is the greater. An era is **not** a stored entity: it is a name on an event, and eras order by the least `sort_key` among their members. No calendar is ever parsed, and none is ever required (D9). | Absolute timestamps with a real date type. Rejected outright: a secondary-world calendar does not parse, and requiring one would make story-time unusable for exactly the manuscripts this product is for. Also rejected: deferring the ordering module to Phase 8. A stored shape with no consumer is a shape nobody has proved sufficient, and Phase 8 would discover its gaps as a migration — which is the argument Phase 2 made for building the destructive text paths alongside the resolver rather than after it. | Migration 003's attribute shape, the link vocabulary, and every line of Phase 8's timeline |
| **D29** | Whether H1 is reserved for chapter titles (**settles `Q7`**) | **No. The editor keeps three heading levels and `D15` stands.** The combined export goes on writing body headings one level down; the per-chapter export, which is the half that promises a round trip, goes on being untouched. | `Q7`'s recorded leaning — probably yes, remove the ambiguity at the source. **Recommended against, on evidence the leaning did not have:** the manuscript that exposed the collision had an H1 in a chapter body *because that is how this writer writes*, so reserving H1 removes a level in active use to save a notice on a body H3 in the one file that never promised a round trip. It would also cost a closed-schema change (D1), a migration rewriting every H1 already typed, and a heading control offering two levels where three are expected — all in a phase that otherwise does not touch the editor. `Q7` closes as **resolved, not adopted**; the reasoning stays on the record so a future reversal is a deliberate act. | The closed schema, migration 003's scope, and whether the phase touches the editor at all |

### Conventions and smaller rulings

Cheap to change now, awkward once files exist.

| | Ruling | Why, and what it costs to reverse |
|---|---|---|
| **1** | **`specs/bible.md` is written, at P3-1, before the code it governs.** It fixes the record and its lifecycle, the field-type and relation vocabularies, story-time and the ordering rules, the revision and retcon rules, and what an entry does **not** promise. | The P2-4 discipline, applied where it earns its place. Three later phases read from this document and none of them can read it out of a docstring: Phase 6's tools declare it, Phase 7 writes into it, Phase 8 renders it. Note the ordering difference from P2-4, which came *after* its migration: here the spec fixes the storage shape, so it comes first. **What it must not do is restate the per-kind field lists** — those are D26's served definition, and a second copy in prose is the third place to disagree that `specs/markdown.md` was refused for being (`CLAUDE.md`). It describes the *vocabulary*; the definition holds the *members*. |
| **2** | **New ID prefix `lnk_` for links**, registered in `archetype/ids.py` and `IdPrefix.ALL` in the same change as the migration. `ent_` is already registered and unused; Phase 3 is what uses it. Revisions are identified by `(entry_id, revision)`, not by an ID of their own. | Prefixes are never reused for a different entity (data-model § 2), and the P2 ruling-7 pattern. A revision is not independently addressable — it is always reached through its entry — so minting an ID for one would be an identity nobody dereferences. |
| **3** | **An entry's concurrency guard is D19's, applied unchanged.** `entry.revision` is monotonic, an update presents the revision it was read at, and a stale one is refused with `409`. | The writer will have the bible open in one pane and the manuscript in another, and Phase 7 will write proposals against entries the writer is editing. One guard, one shape, one error the client already handles. Skipping it here means retrofitting it in Phase 7 into a store that Phase 7 is also learning to write to. |
| **4** | **Phase 3's entry search is a `LIKE` filter on the list route**, `GET /api/projects/{pid}/entries?q=`, over `name`, aliases, and `summary`. It is **not** `/search`, and it does not touch FTS5. | Phase 5 owns search and owns that route name. A Phase 3 `/search` that later means something else is a route a client comes to depend on with the wrong meaning — the reason api-contract § 12 refuses stub routes. A bible is hundreds of rows; `LIKE` is correct at that size and is honest about being a filter. |
| **5** | **The *Marks* tab stays exactly as it is.** Phase 2's ruling 6 left open whether it would narrow once the Bible tab existed; it does not. | They answer different questions. *Marks* is every anchor in the project, including the ones no entry cites, and it is the only place a `stale` anchor gets repaired. The Bible tab shows **one entry's** citations and their status. Narrowing *Marks* to a stale-anchor surface would delete the only view of an anchor that is fine but uncited, which is most of them. |
| **6** | **Phase 3 adds no configuration keys.** Field-type and relation vocabularies, the review-flag rule, and the search filter's cap are module constants and served data, as `MAX_CONTENT_BYTES` and `CONTEXT_CHARS` are. | A setting is a promise to support every value of it. None of these has a second value anyone wants yet — and the two vocabularies are closed *on purpose*, so making them configurable would be undoing D26 through the back door. |
| **7** | **A link is directed in storage and may be symmetric in meaning.** The relation definition declares `symmetric`, and a symmetric relation is stored once and read from both ends. | Storing `knows` twice means two rows that can disagree, and a chart that double-counts. Declaring it means Phase 8's adjacency matrix gets the answer from the vocabulary instead of hard-coding a list of relations it should mirror. |
| **8** | **The bible creates anchors through `AnchorStore.create` and by no other means.** *Add to bible* from a selection sends a ProseMirror range and a document version, exactly as marking a passage does, and the server derives the quote. | `save_content` is the only path by which manuscript text changes; `AnchorStore.create` is the only path by which an anchor is minted. A second creation path is where a client-supplied quote sneaks in, and an anchor whose quote the client chose is an anchor that can disagree with the manuscript from the moment it exists (api-contract § 7). |
| **9** | **A soft-deleted entry's links are hidden but not deleted, and the live predicate is a three-way join.** A link is live when the link is not deleted **and neither endpoint is deleted**. | The Phase 2 lesson, one table wider. Forgetting one leg puts a deleted character back into a relationship view and, in Phase 8, into the interaction matrix — where it surfaces as a wrong chart and gets reported as a Phase 8 bug. It is one predicate, in one place, with one test that asserts absence from every read path together (P3-6). |

---

## 3. The bible record in brief

The full specification is `specs/bible.md` (P3-1), written **before** the code it governs. This
section is the shape the work items are sized against, and is the part a reviewer needs to judge
them.

### The uniform record

| Field | Role |
|---|---|
| `kind` | `character` \| `place` \| `item` \| `faction` \| `event` \| `thread` \| `fact`. Chosen at creation and **immutable** — changing it would invalidate every attribute the entry holds |
| `name` | What the thing is called. Not unique; two characters may share a name, and the bible is not a namespace |
| `summary` | One line. What the browser list shows, and what Phase 6 puts in a context budget |
| `body_md` | The prose. Markdown as text, not as a schema — an entry is a note, not a manuscript |
| `attributes_json` | The per-kind fields, validated against D26's served definition |
| `status` | `proposed` \| `accepted` \| `rejected` \| `superseded`. Everything a person types is `accepted`; the other three are Phase 7's, and have no writer in Phase 3 |
| `origin` | `user` \| `agent`. Always `user` in Phase 3 |
| `revision` | Monotonic. The D19 guard, applied to entries (§ 2, ruling 3) |
| `needs_review`, `review_reason` | The retcon flag and what set it. Orthogonal to `status`: one is the proposal lifecycle, the other is "something this depended on moved" |
| `deleted_at` | Nullable. `NULL` = live (D25) |

### The six field types, and what each is for

Closed, and enforced by a test on both sides of the wire.

| Type | Holds | Rendered as |
|---|---|---|
| `text` | A short string | One line |
| `long_text` | A paragraph or more | A textarea |
| `list_of_text` | Aliases, traits, epithets | An add/remove list of lines |
| `enum` | One of a fixed set the field declares | A select |
| `entry_ref` | Another entry, constrained to declared kinds | A picker filtered to those kinds |
| `story_time` | D28's `label` + optional `sort_key` + optional `era` | Three inputs, all optional |

An `entry_ref` is a *field*, not a link. The distinction is deliberate and `bible.md` must state it:
a field is a property of the entry that owns it (an item's `owner`), and a link is a relationship
with its own identity, its own story-time bounds, and its own place in the chart (a character
`owns` an item). Where both would be defensible, the link wins, because only a link can be dated.

### Links

`(from_entry, relation, to_entry)` plus optional `since` / `until` story-time bounds (D9) and a
free `attributes_json`. The relation vocabulary is closed (D26) and each relation declares the
kinds it may join and whether it is symmetric (§ 2, ruling 7). Twelve relations are proposed in
`bible.md`; `precedes`, between two events, is the one D28's ordering module reads.

### Citations

`entry_anchor(entry_id, anchor_id, role)`, with `role` in `source` | `mention` | `setup` | `payoff`.
An entry's detail view lists its citations with each anchor's **current** status, which is where a
`stale` anchor stops being an abstraction: the passage that produced this entry has been rewritten,
and the writer can see that before trusting the entry.

Two consequences worth stating up front, because both are places a design could quietly go wrong:

- **An entry's narrative position is derived from its `source` anchor, never stored.** So it moves
  when the writer reorders chapters, for free, and an entry with no anchor simply has no narrative
  position — which is exactly D9's unplaced tray, arriving from the data rather than from a flag.
- **Deleting an anchor does not delete the entry it produced.** The citation goes; the entry stays,
  with one fewer reason to believe it. The reverse also holds: soft-deleting an entry leaves its
  anchors alone, because an anchor is a fact about the manuscript and an entry is not.

---

## 4. Work Items

Fifteen items in four groups. The **Done when** line is the acceptance bar — an item without its
tests is not done (outline § 8).

### Group A — The record (P3-1 → P3-4)

---

**P3-1 · `specs/bible.md`**

The specification, written **before** Group A's migration, in the shape `projection.py`'s docstring
and `anchors.md` established: the rules stated once, in prose, so that two readers and one test
corpus can agree on them. It settles, at minimum:

- The uniform record and the seven kinds, and why `kind` is immutable;
- The **vocabulary** of field types (six) and of relations (twelve), and the rule that the
  *members* live in D26's served definition and not in this document (§ 2, ruling 1);
- The `entry_ref`-versus-link distinction, and the tie-break that favours a link;
- The revision rule, the retcon rule, and the exact definition of a dependent (D27);
- Story-time: the three forms, the two contradiction kinds, and how eras derive their order (D28);
- The live predicates — for an entry, and the three-way one for a link (§ 2, ruling 9);
- What an entry does **not** promise, in as many words: it is not a namespace, it is not unique by
  name, a citation is not a guarantee that the passage still says what the entry says, and nothing
  in it is derived from the manuscript by anything but a person.

*Done when:* the document exists; P3-5's definition is written *from* it; every constant and every
vocabulary member it names appears in the code under that name.

---

**P3-2 · Migration 003, and the fixture database that guards it**

`003_bible.sql` — four tables, and the second real migration.

```sql
CREATE TABLE entry (
    id              TEXT PRIMARY KEY,                    -- ent_...
    project_id      TEXT NOT NULL REFERENCES project(id),
    kind            TEXT NOT NULL,                       -- character|place|item|faction|event|thread|fact
    name            TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    body_md         TEXT NOT NULL DEFAULT '',
    attributes_json TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL,                       -- proposed|accepted|rejected|superseded
    origin          TEXT NOT NULL,                       -- user|agent
    revision        INTEGER NOT NULL,                    -- monotonic; the D19 guard (ruling 3)
    needs_review    INTEGER NOT NULL DEFAULT 0,          -- the retcon flag (D27)
    review_reason   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    deleted_at      TEXT                                 -- NULL = live (D25)
);

CREATE TABLE entry_revision (
    entry_id     TEXT NOT NULL REFERENCES entry(id),
    revision     INTEGER NOT NULL,                       -- 1 is creation
    revised_at   TEXT NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    retcon       INTEGER NOT NULL DEFAULT 0,             -- did this write flag dependents?
    origin       TEXT NOT NULL,                          -- user|agent
    snapshot_json TEXT NOT NULL,                         -- the entry's full state AFTER the change
    PRIMARY KEY (entry_id, revision)
);

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

CREATE TABLE entry_anchor (
    entry_id   TEXT NOT NULL REFERENCES entry(id),
    anchor_id  TEXT NOT NULL REFERENCES anchor(id),
    role       TEXT NOT NULL,                            -- source|mention|setup|payoff
    created_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, anchor_id, role)
);

CREATE INDEX idx_entry_project_kind  ON entry(project_id, kind, name);
CREATE INDEX idx_entry_review        ON entry(project_id, needs_review);
CREATE INDEX idx_link_from           ON entry_link(from_entry, relation);
CREATE INDEX idx_link_to             ON entry_link(to_entry, relation);
CREATE INDEX idx_entry_anchor_anchor ON entry_anchor(anchor_id);
```

Extension-only (outline § 7): four tables added, nothing repurposed, and **not one column changed
on `document`, `anchor`, or `snapshot`**. `lnk_` is registered in `archetype/ids.py` and in
`IdPrefix.ALL` in the same change.

Capture `server/tests/fixtures/db/v002_phase2.sqlite` the way `v001_phase1.sqlite` was captured —
by a committed script beside it, not by a paragraph of instructions ([phase-2-plan](phase-2-plan.md)
§ 7, `A6`) — holding a real Phase 2 project: two chapters, anchors in both, a snapshot, and one
soft-deleted chapter, so that the migration is tested against a file with the D22 predicate already
in play. Migration 002's test against `v001_phase1.sqlite` keeps running unchanged, so a v1 file
now migrates two steps in one open.

*Done when:* a v2 fixture migrates to v3 with its documents, anchors, and snapshots intact and
readable through their stores; a v1 fixture migrates all the way to v3 in one open; a fresh file
reaches v3 in one open; re-opening is a no-op; `latest_version()` is 3 and the consecutive-from-001
check still passes.

---

**P3-3 · `EntryStore` — the uniform record**

`archetype/bible/entries.py`, scoped by the same `ProjectHandle` every other store is, and carrying
every rule (api-contract § 1):

- `create(kind, name, ...)` — validates attributes against the kind's definition (P3-5), writes the
  entry and revision 1 in one transaction, and refuses an unknown kind or an undeclared attribute.
- `get(entry_id)`, `list(kind=, status=, needs_review=, q=, include_deleted=)` — one list method
  carrying every filter, including ruling 4's `LIKE` search over `name`, aliases, and `summary`.
- `update(entry_id, revision, ...)` — the D19 guard re-read under the write lock, a revision written
  inside the same transaction, and the retcon computation of D27. `kind` is not updatable.
- `delete(entry_id)` / `restore(entry_id)` — the D25 soft delete, with the same shape D22 gave
  chapters: nothing cascades, a revision records it, and `list_deleted()` is the restore surface.
- Every read path filters `deleted_at IS NULL` by default, and **one test asserts a deleted entry is
  absent from all of them together** — the list, the review queue, the link views, and the citation
  views — because a predicate that leaks surfaces as a wrong count and is reported as a different
  bug (the Phase 2 lesson, `P2-2`).

An attribute the definition does not declare is a `422`, not a silent drop: `attributes_json` is a
blob in storage but it is **not** a free-form bag, and the moment it becomes one, D26's served
definition stops describing what is actually in the file.

*Done when:* CRUD round-trips for all seven kinds; an unknown kind, an unknown attribute, an
attribute of the wrong type, and an `enum` value outside its declared set are each refused with
nothing written; a stale `revision` is refused with `409` and nothing written; a deleted entry is
absent from every read path and returns unchanged from `restore`.

---

**P3-4 · Revisions, retcon, and the review queue (D27)**

The half of `EntryStore` that makes an edit recoverable and its consequences visible.

- Every write records a revision holding the entry's **full post-change state**, numbered from 1.
  Nothing is deduplicated and nothing is pruned, and the contrast with D23 is deliberate: a
  `handover` snapshot is 300 KB that nobody asked for, and an entry revision is two kilobytes that
  somebody typed.
- `revisions(entry_id)` — metadata only, never the snapshots, the discipline `SnapshotStore.list`
  already follows (api-contract § 3).
- `revision(entry_id, n)` — one revision's state, for preview and diff.
- `restore_revision(entry_id, n, revision)` — writes the old state back **through `update`**, so a
  restore is an ordinary edit: it bumps `revision`, records a new revision, is guarded by D19, and
  computes its own retcon answer. One write path, no exceptions — `SnapshotStore.restore`'s rule,
  one table over.
- **The retcon computation.** True when `name`, `attributes_json`, or `status` changed; false for a
  `summary`- or `body_md`-only edit; overridable in either direction by the request. When true, every
  entry joined by a **live** link in either direction (§ 2, ruling 9) has `needs_review` set with a
  reason naming the entry and the revision.
- `clear_review(entry_id, revision)` — the writer says they have looked. It writes a revision like
  any other edit and is not itself a retcon, so clearing a flag never flags the neighbours back.

That last clause is the one to get right: without it, clearing a review flag on a densely linked
character re-flags everything it touches, and the queue never empties.

*Done when:* an edit to `body_md` alone writes a revision and flags nobody; an edit to an attribute
flags every live link-neighbour in both directions and no one else; a request may force the flag on
or off; a deleted neighbour is not flagged and a deleted link does not carry a flag; clearing a
review flags nothing; restoring revision *n* reproduces that state exactly and appends rather than
rewrites history.

---

### Group B — Structure over the record (P3-5 → P3-8)

---

**P3-5 · The kind and relation definition (D26)**

`archetype/bible/schema.py` — the one place the seven kinds' fields and the twelve relations are
written down, and the module every other part of the phase reads.

- A `FieldType` enum of exactly six members, and a test that fails if a seventh appears without the
  client's renderer growing a case for it — the closed-list discipline the editor schema already
  lives under (D1), for the identical reason: each type is a case the form, the validator, the
  Phase 6 tool declaration, and the Phase 7 proposal renderer must each handle.
- A `KindDefinition` per kind: its fields, each with a type, a label, whether it is required, and —
  for `enum` and `entry_ref` — its declared members or kinds.
- A `RelationDefinition` per relation: the kinds it may join in each direction, and `symmetric`.
- `validate(kind, attributes)` — total, and refusing rather than coercing.
- A JSON dump of the whole definition, which is what P3-11 serves and what the contract fixture
  pins.

The shared-fixture pattern is deliberately **not** used here, and the difference from
`closed_schema.json` is worth stating: the editor's closed schema is a *test artifact* holding two
implementations to a list, whereas this definition is *runtime data with one implementation* that
the client fetches. Copying it into `web/src` to be imported at build time would create the second
copy D26 exists to prevent.

*Done when:* every kind in `bible.md` has a definition and every definition is in `bible.md`'s
vocabulary; validation refuses an unknown field, a wrong type, an out-of-set `enum`, and an
`entry_ref` to a kind the field does not allow; a seventh field type fails a test on both sides of
the wire; the JSON dump is a contract fixture.

---

**P3-6 · `LinkStore` — relationships**

`archetype/bible/links.py`. Create, list, update the bounds, soft delete, restore.

- A link is refused when the relation is not in the vocabulary, when either endpoint's kind is not
  one the relation joins, when an endpoint does not exist or is deleted, or when it duplicates a
  live link with the same `(from, relation, to)` — and, for a symmetric relation, the same pair in
  either order.
- `for_entry(entry_id)` returns both directions in one answer, each marked with which end the entry
  is on, because every consumer wants both and computing it twice is how the two halves disagree.
- **The three-way live predicate** (§ 2, ruling 9), in one place, with one test asserting a link to
  a soft-deleted entry is absent from `for_entry`, from the project link list, from the dependent
  computation in P3-4, and from P3-8's ordering, **together**.
- `since` and `until` are free text story-time bounds (D9). They are stored, displayed, and not
  interpreted — nothing in Phase 3 or Phase 8 sorts by them, and `bible.md` says so, because a bound
  that looks orderable and is not is worse than one that plainly is not.

*Done when:* every refusal above happens with nothing written; a symmetric relation is stored once
and read from both ends; the live predicate holds across all four read paths together; deleting an
entry hides its links and restoring the entry brings exactly those links back.

---

**P3-7 · Citations — entries and anchors meet**

`archetype/bible/citations.py`, plus the one flow that makes anchors pay for themselves.

- `cite(entry_id, anchor_id, role)` and `uncite(...)` over `entry_anchor`.
- `citations(entry_id)` — each anchor with its **current** status, read through `AnchorStore`, which
  means a `stale` or `orphaned` anchor is visible on the entry that depends on it.
- `create_from_range(document_id, from_pos, to_pos, version, kind, name, ...)` — one transaction
  that mints an anchor through `AnchorStore.create` (§ 2, ruling 8), creates the entry, and cites it
  with role `source`. A stale document version is refused with the same `409` a save is, and
  **nothing is written** — not the anchor, not the entry.
- `entries_for_anchor(anchor_id)` — the reverse, so *Marks* can say an anchor is cited and by what,
  and so deleting an anchor can say what it will leave behind.
- **Deleting an anchor removes its citations and leaves the entries.** Soft-deleting an entry leaves
  its citations and its anchors untouched. Neither operation touches the other's rows beyond that.

The narrative position of an entry is derived here, from its `source` anchor's document
`order_index` and `from_pos`, and is not stored. An entry with no `source` anchor has none.

*Done when:* an entry created from a selection has exactly one anchor whose quote the server
derived; a stale version refuses the whole operation with nothing written; an entry's citations
report the anchor's live status including `orphaned` when its chapter is deleted; deleting the
anchor leaves the entry; a chapter restored returns its cited anchors to the status they held.

---

**P3-8 · Story-time ordering (D28)**

`archetype/bible/storytime.py` — **pure**, in the same sense `projection.py` and
`anchors/resolve.py` are, and for the same reasons: `(events, precedes-edges) → ordering`, driven
by a JSON corpus rather than a database, every case data, and Phase 6's agent and Phase 8's view
get identical behaviour without going through HTTP.

It returns three things and never more:

- **The order** — a topological sort over `precedes`, with `sort_key` as the tiebreak among
  otherwise unordered events, and a stable fallback so two runs never disagree.
- **The unplaced** — events with neither an incident `precedes` edge nor a `sort_key`. D9's tray.
- **The contradictions** — exactly two kinds, and no others: a cycle in `precedes` (reported with
  the cycle's members), and an edge `A precedes B` where both carry a `sort_key` and A's is greater.

Eras order by the least `sort_key` among their members and are otherwise a display grouping; an era
whose members carry no key has no rank, and that is not a contradiction.

**What it must never do is invent an order** (D9, in as many words). An unplaceable event is
reported as unplaced. A cycle is reported as a cycle and the rest of the graph is still ordered —
because a timeline that refuses to draw anything because two events disagree is a timeline nobody
can use to find the disagreement.

`server/tests/fixtures/bible/storytime/cases.json` states each case as its events, its edges, and
the three answers, hand-written from `bible.md` rather than from the implementation — the P2-8
discipline, which is the only thing that makes a corpus evidence rather than a transcript.

*Done when:* the corpus passes both ways; a cycle is reported without losing the orderable
remainder; a `sort_key` inversion across an edge is reported and the edge still orders the pair;
the order is stable across runs; a property over the whole corpus asserts that **every returned
order respects every non-contradictory edge** — asserted once over all cases, not per case, so a
case added later is covered without anyone remembering (the P2-8 rule).

---

### Group C — The API (P3-9 → P3-11)

---

**P3-9 · Entry routes**

Under the existing `/api` router, with the uniform error envelope and no domain logic (api-contract
§ 1):

| Route | Does |
|---|---|
| `GET /api/projects/{pid}/entries` | List, with `kind`, `status`, `needs_review`, `q`, and `include_deleted` filters (ruling 4) |
| `POST /api/projects/{pid}/entries` | Create |
| `GET /api/entries/{eid}` | One entry, with its citations and link counts |
| `PUT /api/entries/{eid}` | Update, presenting `revision`; optional `retcon` override and `reason` |
| `DELETE /api/entries/{eid}` | Soft delete (D25) |
| `POST /api/entries/{eid}/restore` | Undo it |
| `GET /api/projects/{pid}/entries/deleted` | The restore surface |
| `GET /api/entries/{eid}/revisions` | History, metadata only |
| `GET /api/entries/{eid}/revisions/{n}` | One revision's state |
| `POST /api/entries/{eid}/revisions/{n}/restore` | Write it back through `update` |
| `POST /api/entries/{eid}/review/clear` | Clear the retcon flag |

A bare `{eid}` resolves to its project file through the existing `locator`, extended to entries the
way it already resolves documents, anchors, and snapshots — one more prefix, not a second mechanism.

*Done when:* every route is exercised over the real application; the `409`, the `422`, and the
`404` each carry the envelope; the filters compose; the contract fixtures are written and the
frontend type-checks them.

---

**P3-10 · Link and citation routes**

| Route | Does |
|---|---|
| `GET /api/projects/{pid}/links` | Every live link in the project, filterable by `relation` |
| `POST /api/projects/{pid}/links` | Create |
| `GET /api/entries/{eid}/links` | Both directions, each marked with which end this entry is on |
| `PATCH /api/links/{lid}` | Bounds and attributes. Never the endpoints or the relation — that is a different link |
| `DELETE /api/links/{lid}` / `POST /api/links/{lid}/restore` | Soft delete and undo |
| `POST /api/entries/{eid}/citations` | Cite an existing anchor, with a role |
| `DELETE /api/entries/{eid}/citations/{aid}` | Uncite |
| `POST /api/documents/{did}/entries` | **Create an entry from a selection** (P3-7): a range, a version, a kind, a name |
| `GET /api/anchors/{aid}/entries` | What cites this anchor |
| `GET /api/projects/{pid}/storytime` | P3-8's three answers over the project's events |

Changing a link's endpoints or its relation is deliberately absent: it is a delete and a create, and
both are recoverable. Allowing it in place would mean a link's history could describe a
relationship it never had.

*Done when:* as P3-9, plus: the from-selection route refuses a stale version having written
nothing, and the storytime route's answer matches the pure module's for the same data.

---

**P3-11 · The schema route, and the documentation of the wire**

`GET /api/bible/schema` — D26's definition as JSON: the kinds, their fields, the field types, and
the relation vocabulary. **Project-independent**, which is why it carries no project scope: the
vocabulary is the product's, not a manuscript's.

It is the one route in the API that answers the same bytes for every caller, so it is also the one
worth an `ETag`; that is a nicety, not a requirement, and cutting it is the right call if it costs
more than a line.

Everything in Groups C and D reads this, and so does Phase 7's proposal renderer. The contract
fixture for it is therefore the most load-bearing one in the phase: it is what fails when a kind
gains a field and the client was not told.

*Done when:* the route answers the definition; a contract fixture pins it; the frontend type-checks
the fixture and renders every field type in it; adding a field to a kind changes exactly one file
and one fixture.

---

### Group D — The application and close-out (P3-12 → P3-15)

---

**P3-12 · The Bible tab — browsing and the review queue**

The fifth tab stops being a placeholder. A `BibleContext` beside the existing three (D10), holding
the project's entries and the schema definition, with a pure reducer as `projectReducer` is.

- The list, grouped by kind or flat, with the kind filter, the status filter, and the search box
  (ruling 4). Counts per kind, so "how many characters are there" is answered without scrolling.
- **The review queue** — entries with `needs_review`, each showing what flagged it, with *Reviewed*
  clearing one. This is half of the phase's exit criterion and it is not a badge on a list: a
  retcon's whole point is that the writer walks the consequences, so the queue is a place they can
  work through, and it empties.
- Deleted entries, and restoring one, on the same footing as *Deleted chapters*.

*Done when:* the list filters and searches without a refetch per keystroke; the review queue lists
exactly the flagged entries and empties as they are cleared; a deleted entry can be found and
restored; the tab has its own error boundary and a failure in it leaves the editor working (the
P1-12 rule).

---

**P3-13 · The entry detail view, the generic form, and history**

The single largest client surface in the phase, and the one D26 exists to keep finishable.

- **One form, rendered from the schema** (P3-11), with one component per field type — six, closed,
  and a test that a type without a renderer fails loudly rather than rendering nothing.
- Name, summary, and body on every kind; attributes below, in the definition's order.
- Save presents the `revision` and handles the `409` the way the editor already does: it stops,
  says so, and offers the server's copy. It never merges (D19).
- **The retcon control** sits on the save: the computed default, shown as a checkbox with the reason
  it is checked, so a retcon is a visible act rather than a silent consequence. This is the D12
  posture applied to the bible — the writer sees what is about to happen and decides.
- Revision history per entry: what changed and when, a preview of any revision, and restore. A real
  field-by-field diff is **desirable, not required**; if the preview lands and the diff does not,
  that is the correct thing to cut, and it is recorded here so cutting it is a decision rather than
  a shortfall (the P2-12 rule).

*Done when:* every field type renders, edits, and round-trips; an unknown field type fails a test;
a `409` is surfaced and does not lose the writer's typing; the retcon checkbox reflects the computed
default and can be overridden; a revision can be previewed and restored.

---

**P3-14 · Links, citations, and *Add to bible***

The three surfaces that connect the bible to everything else.

- **Links on an entry**: both directions in one list, add with a relation picker filtered by the
  two kinds (so an illegal link cannot be built rather than being refused after the fact), story-time
  bounds, and delete.
- **Citations on an entry**: each with its quote, its chapter, its role, and its **status** — and a
  `stale` one links straight to the *Marks* repair flow rather than growing a second one (ruling 5).
  Clicking a citation opens its chapter and scrolls to the passage, through the jump that already
  exists.
- ***Add to bible*** in the editor's selection control, beside *Mark passage* and *Re-link here*
  (`SelectionActions.tsx`). Choose a kind, type a name, and the server does P3-7's one transaction.
  This is the interaction the whole product is arranged around — the outline's § 1 "selecting text
  and asking a question about it", in its manual form — and it is the step the acceptance run
  spends the most time on.

*Done when:* a link can be created only where the vocabulary allows it; an entry created from a
selection appears in the Bible tab with its citation, and the citation's highlight is in the editor;
a citation navigates to its passage; a `stale` citation is visibly stale and reaches the repair
flow.

---

**P3-15 · The documentation pass, and the phase close**

The P1-15 and P2-15 discipline. Every document that describes something Phase 3 changed is brought
level with the code **in the same change**, not afterwards:

- [`specs/data-model.md`](data-model.md) — § 3 gains the four tables as built, § 7 loses the Phase 3
  block it sketched, § 6 gains the entry write rules and both live predicates. The outline calls
  this the phase where the data model is *completed*, and § 7's remaining blocks are Phases 5 and 6.
- [`specs/api-contract.md`](api-contract.md) — a new section per route group, and § 11's "Bible
  entries, links, revisions" row struck through the way Phase 2's four were.
- `specs/bible.md` — reconciled with what was actually built, with every correction marked and
  cross-referenced to § 7's deviations, as `anchors.md` carries its four.
- [`specs/development-phases.md`](development-phases.md) — D25 to D29 promoted to § 1 if ruled;
  the Phase 3 row closed; § 3's Phase 3 sketch replaced by a pointer to this plan.
- [`specs/backlog.md`](backlog.md) — `Q2` and `Q7` moved to § 3 with their rulings.
- [`specs/project-outline.md`](project-outline.md) — § 5's sketch superseded for four more tables;
  `specs/bible.md` added to the child documents; the phase table's Phase 3 row brought level.
- `CLAUDE.md` — what exists, where it lives, and the invariants this phase established.
- Then § 8's acceptance run, by hand, against the single-process build.

*Done when:* every document above matches the code; both suites are green; § 5's criteria all hold;
§ 8's table is filled in step by step with what actually happened.

---

## 5. Exit Criteria

Phase 3 is done when **all** of these hold. **All ten are met** — 1 to 7 by § 8's run on
2026-09-04, 8 and 9 by the suites, 10 by `P3-15`'s documentation pass. The verdict on each is in
the line that states it.

1. **A bible for a test story can be built entirely by hand** — at least one entry of all seven
   kinds, links between them, and citations into the manuscript — using only the UI.
2. **Retconning an entry flags its dependents**, exactly the entries joined to it by a live link;
   they appear in the review queue with the reason; clearing one flags nothing further; and an edit
   that is not a retcon flags nobody.
3. **Every entry write is recoverable.** Revision history is complete from creation, any revision
   can be previewed and restored, and restoring is an ordinary edit that appends to history.
4. **A deleted entry is gone from every list, count, and link view; its data is not**, and restoring
   it brings back exactly the links it had (D25, ruling 9).
5. **An entry can be created from a selection**, and it carries an anchor whose quote the *server*
   derived; the citation reports the anchor's live status, including `stale` after the passage is
   rewritten and `orphaned` when its chapter is deleted.
6. **The seven kinds differ only in data.** Adding a field to a kind is a change to one server-side
   definition and its contract fixture, and the form renders it with no client change (D26).
7. **Story-time orders what it can and refuses to invent the rest** (D28): the corpus passes, cycles
   and `sort_key` inversions are reported, unplaced events are listed, and a property over the whole
   corpus holds that every returned order respects every non-contradictory edge.
8. **Migration 003 runs against a captured version-2 fixture database** in a test, with its
   documents, anchors, and snapshots intact afterward, and a version-1 file migrates all the way
   in one open (D20).
9. `pytest` and `vitest` are both **green**, and P3-8 and P3-4 have tests covering their edges —
   contradictions, empty graphs, dense link neighbourhoods — not just their happy paths.
10. `specs/bible.md` exists and describes what was built; the seven other documents in P3-15 match
    the code.

**Manual acceptance script** (run by hand at the phase boundary; written out step by step, with
what each step must show, in § 8, where its results go):

open the Phase 2 test manuscript → **create a character from a selection** and confirm the anchor,
the highlight, and the citation → create an entry of each remaining kind by hand → **link** them,
and confirm an illegal relation cannot be built → give two events story-time and a `precedes`
constraint, then contradict it and see the contradiction reported → **retcon** the character —
change an attribute — and watch its link-neighbours land in the review queue → clear one and confirm
nothing new is flagged → **edit only the body** of another entry and confirm nobody is flagged →
open the revision history, preview an old revision, and **restore** it → **rewrite the passage** a
citation points at and confirm the citation reads `stale` on the entry → repair it from *Marks* and
confirm the entry agrees → **delete a chapter** holding a cited anchor and confirm the citation reads
`orphaned`, then restore it → **delete an entry** with links, confirm it leaves every view, and
restore it → reload and confirm all of it survived.

---

## 6. Risks in this phase

| Risk | Why it bites | Mitigation |
|---|---|---|
| **The generic form becomes a framework.** Six field types is a renderer; the eleventh is a schema language, and the pressure to add one is a single field that does not quite fit. | It is the classic way a phase like this doubles. And a form framework nobody chose is a dependency with no maintainer and no tests but its own. | D26 closes the type list, and a test fails when a seventh appears (P3-5). A field that does not fit becomes `long_text` and a backlog entry, not a new type. |
| **The retcon flag is noisy, so it is ignored.** Every edit flagging every neighbour trains the writer to clear the queue without reading it. | A flag nobody reads is worse than no flag: it makes the review queue look like a safety net that is not catching anything, which is the outline's own "stale conclusions" risk with an extra step. | D27's default is field-sensitive and the writer sees and can override it on every save (P3-13). Clearing a review is explicitly not a retcon (P3-4). |
| **The retcon flag is silent, so it misses.** The mirror image, and the more dangerous one: a definition of "dependent" that is too narrow means a change nothing appears to depend on. | Silence looks like correctness. Phase 7's continuity findings would then be computed against records nobody was told to re-check. | The definition is exact and stated (D27, `bible.md`), and the honest limit is stated with it: **a dependency the data does not know about is not flagged**, and prose mentions are not links. Phase 5's retrieval is what would widen it, and that is named as its phase. |
| **Soft delete leaks, now across four tables and a join.** One query that forgets an endpoint's `deleted_at` puts a deleted entry back into a link view. | The Phase 2 lesson, one table wider — and in Phase 8 it surfaces as a wrong interaction chart and gets reported as a Phase 8 bug. | Ruling 9's three-way predicate in one place, and one test asserting absence from every read path **together** (P3-3, P3-6). |
| **The seven-kind UI is the largest client surface yet**, and it is at the end of the phase. | Groups A to C could all land and the phase still not be demonstrable, because every exit criterion is a thing a person does in a browser. | D26 makes Group D one form and one list rather than seven of each. P3-13's diff is pre-marked as the cut. Group D is sequenced so P3-12 and P3-13 are usable before P3-14 begins. |
| **Story-time is designed for a timeline nobody has drawn yet** (P3-8). | Phase 8 discovers the shape is insufficient, and fixing it is a migration on a bible a writer has been filling in for two phases. | The ordering module ships **in this phase**, with a corpus, so the shape has a consumer that proves it sufficient — the same argument Phase 2 made for building the destructive text paths beside the resolver. If it is cut, D28's storage shape ships unproven and that is the risk being accepted. |
| **Anchors meet real use for the first time.** Every Phase 2 assumption about `stale` gets tested by a writer who now has something that *depends* on the answer. | If citations turn out to go stale constantly during ordinary writing, the bible's citations become noise — and that is a Phase 2 verdict arriving in Phase 3. | § 8 spends four of its steps here on purpose. A high stale rate is a finding to record in § 7 and take to the resolver's thresholds, not something to paper over on the entry view. |
| **Phase 3 quietly starts building Phase 5 or Phase 7.** Search wants to be real search; the review queue wants to be a proposal queue. | Both are one small step from where this phase ends, and both would ship without the index or the provider that makes them correct. | Ruling 4 fixes search as a filter and reserves the route name. § 1's non-goals name extraction, dedup, and merge as Phase 7's, and the `proposed` status ships with no writer. |

---

## 7. As-Built Deviations

*Every divergence from this plan is recorded here in the same change that makes it, with what
happened and why (outline § 13).*

**Group A, delivered 2026-09-02.** Four deviations, all in the sequencing and shape of the code
rather than in what it does; none touches a `D<n>`.

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **A1** | `P3-3` / `P3-5` | `archetype/bible/schema.py` is `P3-5`, in Group B. | **Landed in Group A**, complete, with its own tests (`tests/test_bible_schema.py`). `P3-3`'s acceptance bar is that an unknown kind, an undeclared attribute, a wrong type, and an out-of-set `enum` are *each refused with nothing written* — none of which can be done without the definition. The plan already knew this (`P3-3` cites "the kind's definition (P3-5)"); only the group boundary moved. **`P3-5` is not closed by this**: it still owes the JSON dump as a contract fixture, and the client-side half of the closed-list enforcement, neither of which exists until Group C has a route and Group D a renderer. |
| **A2** | `P3-5` | "A `FieldType` **enum** of exactly six members." | **A constants class with a `Final[frozenset]` of members**, matching `AnchorStatus` and `SnapshotReason` rather than introducing a second idiom for the same job. The closure is enforced the way the plan asks — `_check_definition()` raises at import if the list is not six, and `test_bible_schema.py` restates the six independently so that widening the list fails a test rather than being confirmed by a check that reads the list it is checking. |
| **A3** | `P3-3` / `P3-6` | Ruling 9's three-way live-link predicate lives "in one place"; the plan names `links.py` (`P3-6`) as the module. | **`archetype/bible/predicates.py`**, a module the plan did not name. `P3-4`'s retcon computation needs the predicate and is in Group A; `LinkStore` is in Group B. Putting it in `entries.py` would have forced `links.py` to import it back for the *entry* predicate, which is the import cycle `anchors/__init__` exists to avoid. One small module both import is the honest answer, and it keeps ruling 9's "one place" literally true. |
| **A4** | `P3-2` | Migration 002's test against `v001_phase1.sqlite` "keeps running unchanged". | **One assertion changed**: it asserted `migrate(conn) == 2`, and `migrate` now runs to the latest version, so it asserts `latest_version()`. The test's subject — a real Phase 1 file carried forward with every word of its manuscript intact — is unchanged, and it now also covers the two-steps-in-one-open case, which had never been exercised. Recorded because a changed assertion is a deliberate act (`CLAUDE.md`, Testing). |

**Group B, delivered 2026-09-02.** Seven deviations. `B2` is the only one that changes behaviour
outside the bible, and it changes it in the one place the specification already said it must.

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **B1** | `P3-7` | "One transaction that mints an anchor through `AnchorStore.create` (§ 2, ruling 8), creates the entry, and cites it." | `AnchorStore.create` and `EntryStore.create` each gained a **connection-scoped twin**, `create_within(conn, …)`, and each `create` is now that method plus a transaction. Three stores cannot share a transaction across three connections, and the alternative — a second `INSERT INTO anchor` in `citations.py` — is exactly the second minting path ruling 8 forbids. So there is still **one** place an `anchor` row is written and one place an `entry` row and its revision 1 are, and *Add to bible* is genuinely atomic: a stale version leaves no anchor, no entry, and no citation. |
| **B2** | `P3-7` | "Deleting an anchor removes its citations and leaves the entries" — stated in the bible's half of the phase. | It had to be implemented **inside `AnchorStore.delete`'s transaction**, which is the one column of Phase 3 that touches manuscript code. Not a preference: `entry_anchor.anchor_id` is a real foreign key and `PRAGMA foreign_keys` is on, so without it deleting a cited anchor *fails* rather than leaving a stale view. The cleanup is `citations.uncite_anchor_within(conn, …)`, reached by a **deferred import** — the same shape `documents.py` uses for the `pre-delete` snapshot, and for the same reason: a citation is *of* an anchor, so bible → manuscript is the static edge and the incidental direction is the one that gives way. |
| **B3** | `P3-3` / `P3-8` | `EntryStore.list` caps every result set at `SEARCH_LIMIT`. | It gained `limit: int \| None = SEARCH_LIMIT`, and P3-8's ordering passes `None`. `bible.md` § 5 says the cap is on **the `q` filter's** result set; a timeline that silently stopped at two hundred events would report a *wrong order*, not a slow one, and no caller could tell. Every other caller is unchanged. |
| **B4** | `P3-8` | The corpus is "hand-written from `bible.md` rather than from the implementation". | To do that honestly, **`bible.md` § 7 had to be made exact first** — it is now at version 1.1, with "The tiebreak, exactly" (four numbered rules) and the note that the two contradiction kinds are independent. "Refined by `sort_key`" leaves a real choice, and a corpus cannot state an expected order while the document leaves it open; a corpus written from the code instead would be a transcript (the P2-8 rule). Written **before** `storytime.py`. Two of the twenty expectations were wrong as first written and were corrected before the module was run against them — one had ordered a pair by their keys where an edge said otherwise, and one expected a cycle to report only a cycle when its closing edge inverts too; both were these rules applied carelessly rather than the code disagreeing with them. |
| **B5** | `P3-8` | "It returns three things and never more." | Held literally: `Ordering` carries the order, the unplaced, and the contradictions. The era rule `bible.md` § 7 states is a **separate pure function**, `era_ranks(events)`, rather than a fourth field — so the rule has an implementation and corpus cases without widening the answer Phase 8 reads. |
| **B6** | `P3-6` | — | **Refusals the plan did not name, both added deliberately.** A link from an entry **to itself** is refused: it would make an entry its own dependent, and `_dependents` already excluded it defensively. And a **restore that would duplicate a live link** is refused — delete a link, type it again, undo the delete, and two identical rows would double-count in Phase 8's chart with neither being the wrong one to remove. |
| **B7** | — | — | **Shared plumbing, moved rather than copied.** `touch_project` now lives in `projects/db.py` (three stores need it; `documents.py` keeps its own private copy, untouched). `entries._Unset` became `Unset` and `EntryStore._require` became `require`, because `links.py` presents the same "not presented" distinction and `citations.py` must read an entry **inside the transaction that cites it** — a guard checked outside the transaction it guards is a race (the P1-6 rule). |

**Group C, delivered 2026-09-02.** Seven deviations. None changes a `D<n>`; `C3` and `C4` are the
two that a reviewer should read, because both are D26 being taken literally rather than loosely.

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **C1** | `P3-9` – `P3-11` | "Under the existing `/api` router" — read as: in `api/routes.py`, with the wire shapes in `api/schemas.py`. | **Two new modules, `api/bible_routes.py` and `api/bible_schemas.py`**, both under the same `/api` prefix and included by `create_app` before the static mount. The bible adds as many shapes again as Phases 1 and 2 put together; one 1,900-line `schemas.py` is one nobody reads. Nothing else moved: the prefix, the envelope, the ordering guarantee, and `deps.py` are unchanged, so "the existing router" is true of the surface even though it is now written in two files. `schemas._Wire` became `schemas.Wire` so the second module can extend the one base rather than declare a second `extra="forbid"`. |
| **C2** | `P3-10` | `GET /api/projects/{pid}/storytime` reads "P3-8's three answers over the project's events" — with no module named for the reading. | **`archetype/bible/timeline.py`**, a module the plan did not name: `project_timeline(handle)` is two store reads and one call into the pure module. It is not in the route because a route carries no domain logic and because Phase 6's agent and Phase 8's timeline must get the same answer without going through HTTP; it is not in `storytime.py` because that module is **pure** and importing a store into it would end that. It holds no ordering rule of its own, and `Ordering` is passed through unwidened — `B5` stays literally true, with `era_ranks` beside it rather than inside it. |
| **C3** | `P3-9` / `P3-10` | — | **The wire does not restate the two closed vocabularies.** `kind` and `relation` arrive as plain `str` and are refused by `bible/schema.py`, which answers `422 invalid_attributes` naming the field. A `Literal` of the seven kinds in `bible_schemas.py` would be the second copy D26 exists to prevent — and the copy that drifts, because the client fetches the other one. What **is** restated is what a module constant owns rather than the served definition: `EntryStatusFilter` and `CitationRoleIn` spell out `EntryStatus.ALL` and `CitationRole.ALL`, held to them by a test, exactly as `AnchorStatusFilter` is (P2-7). |
| **C4** | `P3-9` | "`POST /api/projects/{pid}/entries` — Create". | **`status` and `origin` are not accepted, by create or by update.** § 3 says `proposed`, `rejected`, `superseded`, and `agent` have **no writer in Phase 3**; a route that accepted one would be that writer, which is the rule the `pre-*` snapshot reasons already follow (P2-3, `D1`). They stay readable — `?status=` filters on all four — because a filter that cannot ask for a value the column can hold needs changing the moment one exists. `kind` is absent from `PUT` for the separate reason that it is immutable. |
| **C5** | `P3-11` | "It is … the one worth an `ETag`; that is a nicety, not a requirement, and cutting it is the right call if it costs more than a line." | **Cut, on the plan's own terms.** A conditional `304` needs the route to return a bare `Response`, which costs the `response_model` and with it the generated schema for the most load-bearing shape in the phase — the opposite trade to the one the sentence had in mind. The definition is a few kilobytes and the client fetches it once per session. |
| **C6** | `P3-9` | The route table's answers, read narrowly: a list is a list, one entry is one entry. | **Three fields the table did not name, each because a Group D surface needs it and the alternative is a second request per keystroke.** `EntryListOut.counts` is the **live, unfiltered** per-kind count, so the tab answers "how many characters" while showing only the places (`P3-12` asks for exactly this). `EntryListOut.truncated` reports the `q` cap rather than merely applying it — and it is exact, because the route asks for `SEARCH_LIMIT + 1` and trims, so a project with exactly two hundred matches does not claim there are more. `EntryDetailOut.narrative_position` exposes the answer `P3-7` already computes; without it the derived position has no consumer until Phase 8, and a stored shape with no consumer is one nobody has proved sufficient. |
| **C7** | `P3-5` | `FieldDefinition.as_dict()` emitted `help`, `members`, and `kinds` only when they were non-empty. | **Every key, every time.** The client renders one generic form over this, and a shape whose key set depends on the value of another key is one every consumer branches on — including the contract test, which compares key sets exactly. Two smaller moves in the same spirit: `entries._checked_body` became public `checked_body`, so the wire model applies the byte limit rather than restating it and an oversized body is a `422` rather than a `500`; and `test_entries.sample_value` moved to `conftest.py`, because the route suite rounds all seven kinds through one call too and needs the required fields filled the same generic way. |

**Group D, delivered 2026-09-03.** Eight deviations. `D1` is the one a reviewer should read first,
because it is a surface this plan's § 1 arguably ruled *out* and § 8 requires; `D3` and `D5` are
the two that put a rule in a second place, each with the argument for why that stays honest.

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **D1** | `P3-12` | Nothing. § 1's non-goals say "**no timeline view** … Phase 3 stores story-time and delivers the pure ordering module underneath a timeline (P3-8), and renders neither." | **A story-time readout landed in the Bible tab** — `StoryTimeCheck.tsx`, a fourth view beside the entries, the review queue, and the deleted tray. § 8's steps 6 and 7 require the contradiction to be "reported naming both events" and the unplaced event to be "listed as unplaced", and neither is demonstrable against a route nothing calls. So the non-goal is read as what it says — no *timeline*: there is no axis, no scale, nothing positioned by a number, and no drawing of any kind. It is three lists and a sentence: the order, the unplaced, the contradictions, plus the eras. Phase 8 still owns the timeline, and it will replace this rather than extend it. The alternative was to ship D28's storage shape with a consumer no person can look at, which is the risk table's own "designed for a timeline nobody has drawn yet" with the mitigation removed. |
| **D2** | `P3-13` | "The single largest client surface in the phase" — with no ruling on **where** it is drawn. | **A master–detail inside the Bible tab**: opening an entry replaces the tab's four views, and *← All entries* comes back. Not a dialog, and not a takeover of the editor region. A dialog would need a focus trap and an escape contract this app has nowhere else; taking the editor region would hide the manuscript, which four of § 8's steps need on screen at the same time as the bible. The panel is resizable to 560 px (`MAX_PANE_WIDTH`), which is a usable form width, and the divider already persists that choice. The default 280 px is cramped for an eight-field form, and that is the cost being accepted; § 8 is where it gets judged. |
| **D3** | `P3-13` | "The retcon control sits on the save: **the computed default**, shown as a checkbox with the reason it is checked." | The default is **computed by the store and predicted by the client**, which is a second statement of D27's rule — the thing D26 is otherwise arranged to prevent. It is unavoidable: the box has to be right *before* the save, and only the client knows what is in the form. What makes it honest is that the prediction never decides. `retconFields()` drives the checkbox and its sentence; the form sends `retcon` **only when the writer has moved the box**, so an ordinary save carries no override at all and the store's own answer stands, and the response's `changed_fields` is what the writer is then told. Recorded in `specs/bible.md` § 6 and § 12 as its one correction. |
| **D4** | `P3-13` | "A real field-by-field diff is **desirable, not required**; if the preview lands and the diff does not, that is the correct thing to cut." | **Cut, on the plan's own terms — but not to nothing.** There is no word-level diff. What landed instead is a field-level marker: the preview says which of *Name*, *Summary*, *Notes*, and *Fields* the revision holds differently from the record as it stands now. That is four comparisons and one line of CSS, and it answers the question a writer deciding whether to restore is actually asking. A word-level diff is a backlog entry, not a shortfall. |
| **D5** | `P3-12` – `P3-14` | The fake client "does not resolve anchors and must never grow a resolver", and by extension holds no rule of its own. | **The fake computes the retcon answer and the entries it flags**, and nothing else in the bible. The resolver was refused a place there because it is a ladder with tuned thresholds and a corpus, so a second one would be "a rule nobody wrote down"; D27's is two sentences that *are* written down, and the review queue is the phase's headline surface — staging its answer would leave every queue test asserting against a script. The fake still **does not** validate attributes, kinds, or relations (one validator, `bible/schema.py`, with its own tests; a test that needs a refusal stages one) and **does not** order events (one topological sort with a twenty-case corpus; `stageStoryTime` says what the server answered). It also does not hand-write the served definition: `getBibleSchema` returns the **contract fixture**, so the client tests render the real seven kinds and a kind that gains a field reaches them in the commit that puts it on the wire. |
| **D6** | `P3-12` | "A `BibleContext` … holding the project's entries and the schema definition." | It holds **three** lists, not one: the browse list, the review queue, and the deleted tray. The queue is read separately with `needs_review=true` rather than being a mode of the browse list, because it has to be right whatever the writer is currently filtering by — a queue you can only see by clearing your filters is a queue nobody works through. What it deliberately does **not** hold is the open entry's detail, its links, or its revisions: those belong to the one record being looked at, and a second copy of that entry beside the one in the list would exist only for the two to disagree. `openId` is the whole of what the reducer knows about the detail view. |
| **D7** | `P3-12` | "The list filters and searches without a refetch per keystroke." | Read as a **debounce on the server-side filter**, not as client-side filtering. The `q`, `kind`, and `status` filters all go to the route (ruling 4, and the reason `counts` is unfiltered — `C6`); the search box waits 200 ms, and choosing a kind or a status goes out at once, because those are single deliberate clicks and waiting after one reads as lag. Filtering on the client instead would have made `truncated` meaningless and left the route's filters with no consumer until Phase 6. Every **write** refreshes the list unconditionally, for the same reason: working out on the client which writes change list membership means re-implementing the route's filters, and that copy is the one that drifts. |
| **D8** | — | — | **Two touches outside the bible, both small and both deliberate.** `SelectionActions.tsx` gained a third action (*Add to bible*) and two props, and `DocumentContext` gained `addToBible` — which flushes, reads the open chapter and its version, and calls the one route, exactly as `createAnchor` does. It does **not** tell the bible: `EditorRegion` does that, so the document layer keeps its single upward dependency single. `Workspace.test.tsx`'s tab-strip assertion changed from "three tabs say when they arrive" to "two", and now checks the Timeline placeholder names Phase 8; the tab strip itself is unchanged and still five, as P1-9 fixed it. Recorded because a changed assertion is a deliberate act (`CLAUDE.md`, Testing). |

**The acceptance run, 2026-09-04.** Two findings, both from § 8. `E2` is the one that matters: it
is a real defect, in the one case the Phase 2 corpus never made, found by a person doing the thing
the corpus abstracts.

| # | Item | Planned | As built, and why |
|---|---|---|---|
| **E1** | § 8 step 3 | "Try to give an entry an attribute value its `enum` does not declare, and an `entry_ref` to the wrong kind. **Both are refused with a message naming the field.**" | **The step cannot be performed by hand, and that is the correct outcome rather than a gap.** `EntryFields.tsx` renders an `enum` as a `<select>` over exactly `field.members` and an `entry_ref` as a `<select>` over the candidates of the declared kinds, so no gesture exists that offers a value outside either set — the writer's note reads *"no ability to add or select outside of the dropdown provided."* The step was written expecting the server's `422` to be reachable from the UI; it is not, for the same reason step 5's illegal link is not, and D26's whole point is that the served definition makes the illegal choice **unbuildable**. The refusal still exists and is still load-bearing, because the routes are what Phase 7's proposals will arrive through rather than the form — it is covered by `test_bible_schema.py`, `test_entries.py`, and `test_entry_routes.py`, each asserting the refusal names the field and writes nothing. **What is genuinely untested by hand is the client's field-level error rendering** (`FieldShell`'s `error`), which now has no manual path at all; `entryForm.test.tsx` is the only thing standing under it, and it is recorded here beside `C7` and `C8`'s list of surfaces no test reaches — this being the mirror case, a surface no *person* can reach. Step 3 is left in § 8 unchanged: a step that cannot fail is worth knowing about, and it will be able to fail again the moment a route grows a writer the form does not mediate. |
| **E2** | `P2-9` / § 8 step 12 | A `stale` anchor is drawn from its stored positions like any other, distinguished by a wavy underline in `--alarm`. § 8 step 12 asks only that the highlight "has **not** moved somewhere approximately right". | **The display rule was wrong, and the wavy underline was the whole of the problem.** The finding: rewriting a marked passage *wholesale* — new sentences, not a tweak, which is the one edit shape the Phase 2 corpus never makes — leaves the anchor drawn as a **range over words it never referred to**. Measured against real ProseMirror: replacing the passage with something longer leaves the underline over `"counted the mast"`, a mid-word fragment of the new sentence; with something shorter it clamps onto `"."`; and typing over the selection maps the range *onto the replacement*, so it never collapses and no `⚑` marker ever appears. That last point is why the writer reported no highlight where the code plainly draws one — a wavy red underline in a `contenteditable` **is** the browser's spellcheck idiom, so the mark was being read as a spelling squiggle rather than as a mark. Two answers were put to the writer: draw a stale anchor as the collapsed marker instead (dropping a range the server itself calls "true at no version", `anchors/rewrite.py`), or keep the range and restyle it. **Ruled: keep the range, restyle it** — so the positions stay the server's answer, unedited, and how the mark *reads* becomes the whole of the guard. `.anchor-stale` is now a tinted `--alarm` wash under a solid 2 px rule: not a thing prose does to itself, and it survives the line wrap an inline decoration has to cross. Two tests were added to `anchorPlugin.test.ts` pinning the wholesale-rewrite case in both halves — the live replacement and the server's answer on reload — because the absence of that case is what let this ship. `specs/anchors.md` § 1 carries it as one more thing an anchor does **not** promise. **The geometry is unchanged and the honest limit is now written down**: a `stale` anchor's range is not a claim about the text under it, and no consumer may read it as one. |

---

## 8. Manual Acceptance — the phase-boundary run

§ 5's script, written out step by step with what each step must show. It is here, rather than in a
scratch file, for the reason Phase 2's § 8 earned twice over: **it is the only thing standing under
the surfaces no test reaches.** In this phase those are the pointer gestures the Phase 2 run already
identified (`C7`, `C8` — jsdom cannot make a text selection, so *Add to bible* is covered in two
halves that meet at a typed boundary), and the one thing no fixture can stage: **whether a hand-built
bible is actually usable**, which is the exit criterion in the outline's own words.

Run it against the **single-process build** — the shape the product ships in (`P1-14`, D7) — so that
the static mount, the API, and the app are the same process a writer would run:

```powershell
cd web; npm run build
cd server; .\.venv\Scripts\python.exe -m archetype     # http://127.0.0.1:8787
```

**Result: run by hand on 2026-09-04 against the single-process build. All fifteen steps passed.**
Two of them passed *with findings*, recorded in § 7 as `E1` and `E2` the way Phase 2's step 13
recorded `D15`:

- **Step 3 could not be performed as written** — the UI gives no way to offer an illegal value, so
  the refusal it asks for is unreachable by hand (`E1`). The step is left in the table with what
  actually happened, because a step that cannot fail is worth knowing about.
- **Step 12 found the display rule for a `stale` anchor was wrong** (`E2`), in the case no test
  reached: a passage rewritten *wholesale* rather than edited. It was fixed and step 12 re-run,
  which is what the Phase 2 precedent asks for.

It earned its keep on the second of those. The Phase 2 anchor corpus edits a character or a word
everywhere it touches this path, and a wholesale rewrite maps differently — so a `stale` anchor was
drawing a range over words it had never referred to, and no test on either side of the wire said
so.

| # | Do this | It must | Outcome |
|---|---|---|---|
| **1** | Open the Phase 2 test manuscript. Select a passage describing a character and use *Add to bible*; choose `character` and give a name. | The entry appears in the Bible tab with one citation; the passage is highlighted in the editor; the citation shows the quote the **server** derived, not one the client sent. | **Passed.** |
| **2** | Create one entry of each remaining kind by hand: `place`, `item`, `faction`, `event`, `thread`, `fact`. | Each form shows that kind's fields and nothing else, all six field types appear across the seven forms, and each entry saves and reappears after a tab switch. | **Passed.** |
| **3** | Try to give an entry an attribute value its `enum` does not declare, and an `entry_ref` to the wrong kind. | Both are refused with a message naming the field. Nothing is written. | **Passed, and the step could not be performed as written** — see `E1`. *"No ability to add or select outside of the dropdown provided."* An `enum` is a `<select>` of its declared members and an `entry_ref` a `<select>` of the candidate kinds, so there is no gesture that offers an illegal value. What the step confirmed is the stronger property step 5 states: unbuildable, not refused. The server's refusal is real and covered by `test_bible_schema.py` and `test_entry_routes.py`. |
| **4** | Link the character to the faction (`member_of`), to another character (`knows`), and to the event (`participates_in`). | Each link appears on **both** entries. The symmetric one (`knows`) appears once from each side, not twice from either. | **Passed.** |
| **5** | Try to build a link the vocabulary does not allow — a `place` that `knows` an `item`. | The relation is not offered for that pair. An illegal link cannot be built, rather than being refused after the fact. | **Passed** — *"selection list only offered `contains` for a place and item link."* |
| **6** | Give two events a `sort_key` and a `precedes` link consistent with it. Then edit one key so the order contradicts the link. | Before: both events are ordered and nothing is reported. After: the contradiction is reported naming both events, and the rest of the events are **still ordered**. | **Passed.** |
| **7** | Create a third event with neither a key nor a constraint. | It is listed as unplaced, not ordered arbitrarily and not dropped (D9). | **Passed.** |
| **8** | **Retcon the character**: change an attribute, and save with the retcon box as it comes up. | The box was **already checked**, with the reason shown. Every entry linked to the character — in either direction — is in the review queue with a reason naming the character and the revision. Nothing unlinked is flagged. | **Passed.** |
| **9** | Clear the review flag on one of them. | It leaves the queue. **Nothing new is flagged** — clearing is not itself a retcon. | **Passed.** |
| **10** | Edit another entry's **body only** and save. | A revision is written and **nobody is flagged**. This is the half of D27 that keeps the queue worth reading. | **Passed.** |
| **11** | Open the character's revision history, preview the revision before the retcon, and restore it. | The old state comes back; the restore is a **new** revision at the top of the history rather than a rewrite of it; and the restore computes its own retcon answer. | **Passed.** |
| **12** | Go to the manuscript and **rewrite the passage** the character's citation points at — new sentences, not a tweak. Wait for the save, then reload. | The citation on the entry reads `stale`, and its highlight has **not** moved somewhere approximately right. The entry itself is untouched. | **Passed, and it found the phase's one real bug** — see `E2`. *"There is no highlight in the text anymore, but everything is updating and pointing as I would have expected."* The citation, the status, and the entry were all correct; the **highlight** was not. It was still being drawn, as a wavy red underline — the browser's own spellcheck idiom, which is why it did not read as a mark — over whatever words now occupied the old offsets. Restyled, and the step **re-run against the fix: passed**, the mark now legible as a flagged region. |
| **13** | Repair the anchor from the *Marks* tab. | It returns to `ok`, and the entry's citation agrees without a separate repair step — one anchor, two views (ruling 5). | **Passed.** |
| **14** | **Delete the chapter** holding a cited anchor, then restore it. | While deleted: the citation reads `orphaned` and the entry says why. After restore: it returns to the status it held. | **Passed.** |
| **15** | **Delete the character entry**, then restore it. Reload the page. | Deleted: it leaves the list, the counts, the review queue, and **both ends of every link**. Restored: it comes back with its links, its citations, and its full revision history. After the reload, everything above is still true. | **Passed.** |
