# Archetype — The Story Bible

**Status:** Specification · written at `P3-1`, **before** the code it governs ·
**Version:** 1.0 · **Date:** 2026-09-02
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1
(D5, D9, **D25**, **D26**, **D27**, **D28**, D19, D22)
**Plan:** [`specs/phase-3-plan.md`](phase-3-plan.md) — this document is `P3-1`; it governs `P3-2`
through `P3-8`, and any place the code corrects it is marked here and cross-referenced to that
plan's § 7
**Companions:** [`specs/data-model.md`](data-model.md) § 3 (the four tables) ·
[`specs/anchors.md`](anchors.md) (what a citation points through) ·
`server/archetype/bible/schema.py` (the definition that holds the *members* of every vocabulary
named here)

The **story bible** is the structured record of the narrative: who is in it, where it happens,
what happened, and what is true. Phase 3 builds it entirely by hand. Phase 7's agent writes into
it as proposals (D5), Phase 8 draws the timeline and the interaction chart from it, and continuity
checking is checked *against* it.

An anchor's promise is that it never points at the wrong passage. A bible entry cannot make a
promise of that shape, because an entry is a **claim a person made**, not a derivation — nothing
in it is computed from the manuscript, and no amount of care makes a typed sentence true. So the
promise this document makes is a different one, about what happens when a claim stops being true:

> **When an established fact moves, everything the data knows to depend on it is flagged, and the
> writer is told exactly what flagged it and why.**

And the honest limit is stated in the same breath, because a flag that silently misses is worse
than no flag at all:

> **A dependency the data does not know about is not flagged.** A link is a dependency. A mention
> in prose is not.

Everything else here — how many kinds there are, which fields each has, how good the ordering is —
is a quality that can be improved later. Those two are the contract.

---

## 1. What an entry is, and what it is not

### The record

One table, one shape, seven kinds (D26). The difference between a character and a place is
**data**, not a second table and not a second form.

| Field | Type | Role |
|---|---|---|
| `id` | `ent_…` | Identity |
| `project_id` | `prj_…` | Scope. An entry lives in exactly one project |
| `kind` | one of seven | What sort of thing this is. Chosen at creation and **immutable** |
| `name` | text | What the thing is called. **Not unique** |
| `summary` | text | One line. What the browser list shows, and what Phase 6 puts in a context budget |
| `body_md` | text | The prose. Markdown **as text, not as a schema** — an entry is a note, not a manuscript |
| `attributes_json` | JSON object | The per-kind fields, validated against the definition (§ 2) |
| `status` | `proposed` \| `accepted` \| `rejected` \| `superseded` | The proposal lifecycle (§ 9) |
| `origin` | `user` \| `agent` | Who produced it. Always `user` in Phase 3 |
| `revision` | integer | Monotonic. The D19 guard, applied to entries |
| `needs_review` | boolean | The retcon flag (§ 6) |
| `review_reason` | text | What set it, in words a person can act on |
| `created_at`, `updated_at` | timestamps | UTC ISO-8601, as everywhere |
| `deleted_at` | timestamp or `NULL` | `NULL` = live (D25) |

`body_md` is stored and returned as characters. Nothing parses it, nothing projects it, and it is
**not** the manuscript's closed schema (D1) — that schema exists so anchors, chunking, and export
each have a finite list of node types to handle, and none of those three touches an entry. An
entry that wants a bullet list gets one by the writer typing `-`.

### The seven kinds

`character` · `place` · `item` · `faction` · `event` · `thread` · `fact`.

`kind` is **immutable after creation.** Not "discouraged" — refused. Every attribute an entry
holds was validated against that kind's field definition, so changing the kind would leave the
entry carrying fields its new kind does not declare, and there are only two ways out of that: drop
them silently, which destroys typed work with no record, or keep them, which puts data in
`attributes_json` that the served definition does not describe and quietly ends the guarantee D26
exists to make. A person who typed the wrong kind creates the right one and deletes the wrong one,
which is recoverable in both directions (D25).

### What an entry promises

- It says what it says, and it says it durably. Every write is recoverable from the revision
  history, from creation onward (§ 6).
- Its citations point at real passages, with each anchor's **current** status shown (§ 8) — so an
  entry whose source text has been rewritten says so on its face.
- Its links are real relationships someone typed, in a closed vocabulary, and both ends see the
  same link (§ 4).
- When it changes in a way that could move established facts, its live link-neighbours are flagged
  and told why (§ 6).

### What an entry does **not** promise

Stated as plainly as `anchors.md` § 1 states its own limits, because each of these is a thing
somebody will reasonably assume:

- **It is not a namespace, and names are not unique.** Two characters may be called Mira. The
  bible is a record of a story, and stories do that on purpose. Nothing keys off `name`, nothing
  deduplicates by it, and the client must never present a name as an identifier.
- **A citation is not a guarantee that the passage still says what the entry says.** It is a
  pointer to a passage plus that pointer's current health. An `ok` anchor means the *quoted text*
  is still there; it means nothing whatever about whether the entry's claim about it is still
  true. Only a person can decide that, which is what the review queue is for.
- **Nothing in an entry is derived from the manuscript by anything but a person.** No entity
  detection, no auto-linking, no inference from prose. In Phase 3 that is because there is no AI;
  from Phase 7 it is because every agent write is a proposal (D5). An entry never quietly acquires
  a field because the text implied one.
- **`needs_review` is not correctness.** It means "something this is linked to moved". An entry
  with no flag is not verified; it is merely not recently disturbed.
- **Story-time is not a date.** It does not sort by itself, it does not parse, and two entries
  with story-time are not thereby comparable (§ 7).
- **A link's `since` and `until` bounds are stored, displayed, and never interpreted.** Nothing in
  Phase 3 or Phase 8 sorts by them. They are free text a person reads. A bound that looked
  orderable and was not would be worse than one that plainly is not.

---

## 2. The field-type vocabulary, and where the members live

There are exactly **six** field types. The list is closed, in the same way and for the same reason
the editor's node list is (D1): each type is a case that the form renderer, the server validator,
Phase 6's tool declaration, and Phase 7's proposal renderer must **each** handle, so a seventh is
four pieces of work, not one. A test fails when one appears without them.

| Type | Holds | Rendered as |
|---|---|---|
| `text` | A short string, at most `MAX_FIELD_TEXT_CHARS` | One line |
| `long_text` | A paragraph or more | A textarea |
| `list_of_text` | Aliases, traits, epithets — at most `MAX_LIST_ITEMS` entries, each at most `MAX_FIELD_TEXT_CHARS` | An add/remove list of lines |
| `enum` | Exactly one of a fixed set **the field declares** | A select |
| `entry_ref` | The id of another entry, constrained to the kinds **the field declares** | A picker filtered to those kinds |
| `story_time` | § 7's `label` + optional `sort_key` + optional `era` | Three inputs, all optional |

A field that does not fit one of these six becomes a `long_text` and a backlog entry. It does not
become a seventh type. That is the rule which keeps the generic form a renderer instead of a
schema language ([phase-3-plan](phase-3-plan.md) § 6).

### Where the members live — and where they must not

This document names the **vocabularies**. It does **not** list which fields each kind has, nor
which kinds each relation joins.

Those are D26's served definition: `server/archetype/bible/schema.py`, served by
`GET /api/bible/schema`, and pinned by a contract fixture. A second copy in prose here would be a
third place for the same list to disagree — exactly what `specs/markdown.md` was refused for being
(`CLAUDE.md`). Adding a field to a kind must be a change to **one file and one fixture**, and it
stops being that the moment this document repeats it.

So: seven kinds, named above. Six field types, named above. Twelve relations, named in § 4. Their
members, their labels, their required flags, their enum sets, and their permitted kinds are the
definition's, and only the definition's.

The contrast with `server/tests/fixtures/schema/closed_schema.json` is worth stating, because the
two look alike and are not. That file is a **test artifact** holding two independent
implementations to one list. This definition is **runtime data with a single implementation** that
the client fetches. Copying it into `web/src` to import at build time would create the very second
copy D26 exists to prevent.

---

## 3. An `entry_ref` is a field; a link is a relationship

Both connect two entries, and the distinction is deliberate.

A **field** is a property of the entry that owns it. It is single-valued, it has no identity of
its own, it cannot be dated, and it disappears when the owning entry does. An item's `owner` field
says something about the item.

A **link** is a relationship with its own row, its own id (`lnk_…`), its own story-time bounds, its
own attributes, and its own place in Phase 8's chart. A character `owns` an item says something
about neither one alone.

**The tie-break: where both would be defensible, the link wins**, because only a link can be dated
and only a link appears in the chart. An `entry_ref` field is for a fact so structural that dating
it would be strange — the region a place sits inside, the home a character keeps.

This is why an event has no `place` field: an event happening somewhere is `occurs_at`, a link.

---

## 4. The relation vocabulary

Twelve relations, closed for the same reasons as the field types. Every one declares, in the
definition and not here, which kinds it may join **in each direction** and whether it is
`symmetric`.

`knows` · `related_to` · `member_of` · `allied_with` · `opposes` · `owns` · `located_in` ·
`participates_in` · `occurs_at` · `precedes` · `advances` · `concerns`

`precedes`, between two events, is the one § 7's ordering module reads. Every other relation is
inert to it.

### Direction and symmetry (phase-3-plan § 2, ruling 7)

**A link is directed in storage and may be symmetric in meaning.** `entry_link` always stores one
row, with a `from_entry` and a `to_entry`. A relation the definition marks `symmetric` is stored
once and **read from both ends** as the same link.

Storing a symmetric relation twice would mean two rows that can disagree — one deleted and one
not, one bounded and one not — and a Phase 8 adjacency matrix that double-counts. Declaring it in
the vocabulary means Phase 8 asks the definition which relations to mirror instead of carrying its
own list of them.

`for_entry(entry_id)` therefore returns **both directions in one answer**, each marked with which
end this entry is on. Every consumer wants both, and computing it in two places is how the two
halves come to disagree.

### What is refused

- A relation not in the vocabulary.
- An endpoint whose `kind` is not one the relation joins **on that side**. `member_of` runs
  character → faction; faction → character is a different statement and is refused, not silently
  reversed.
- An endpoint that does not exist, or is soft-deleted.
- A duplicate of a live link with the same `(from_entry, relation, to_entry)` — and, for a
  symmetric relation, the same pair **in either order**.

Each refusal writes nothing.

### What cannot be edited

A link's **endpoints and its relation are not editable.** Changing either is a delete and a
create, and both are recoverable. Editing them in place would let a link's own history describe a
relationship it never had — the same reasoning that keeps `kind` immutable in § 1.

Its bounds and its attributes are editable.

---

## 5. Constants

Every one appears in the code under the name given here.

| Constant | Value | Why that value |
|---|---|---|
| `MAX_NAME_CHARS` | 200 | Matches the chapter and project title limit. A name is a name |
| `MAX_SUMMARY_CHARS` | 500 | One line, generously read. It is what a context budget spends on an entry (Phase 6), so it is bounded on purpose rather than by taste |
| `MAX_BODY_BYTES` | 65 536 | An entry is a note, not a manuscript — the manuscript limit is 2 MB and lives on `document`. 64 KB is some ten thousand words of notes, and refuses a chapter pasted into the wrong box |
| `MAX_ATTRIBUTES_BYTES` | 32 768 | The serialized `attributes_json`, checked after validation. A bound on the blob as a whole, in addition to the per-field bounds, because the field list can grow |
| `MAX_FIELD_TEXT_CHARS` | 200 | One `text` field, and one item of a `list_of_text` |
| `MAX_LIST_ITEMS` | 64 | Items in one `list_of_text`. Aliases and epithets; past this it is prose and wants `long_text` |
| `MAX_STORY_TIME_CHARS` | 120 | A story-time `label` or `era`, and a link's `since` or `until`. All four are free text a person reads |
| `MAX_REASON_CHARS` | 500 | A revision `reason` and an entry's `review_reason` |
| `SEARCH_LIMIT` | 200 | The cap on the `q` filter's result set (phase-3-plan § 2, ruling 4). A bible is hundreds of rows; a filter that cannot say "there are more" is lying, so the cap is a real limit and the route reports reaching it |

None of these is a configuration key (phase-3-plan § 2, ruling 6). A setting is a promise to
support every value of it, and none of these has a second value anyone wants.

---

## 6. Revisions and the retcon rule (D27)

### Every write records a revision

A revision holds the entry's **full state after the change**. So revision *n* is what the entry
*was* at revision *n*, and **revision 1 is its creation**. Reconstructing any past state is
reading one row, not replaying a chain.

**Nothing is deduplicated and nothing is pruned.** The contrast with snapshots (D23) is deliberate
and holds on both counts: a `handover` snapshot is 300 KB that nobody asked for, so it is
deduplicated and capped at 25; an entry revision is two kilobytes that somebody deliberately
typed, so it is kept.

`revisions(entry_id)` returns **metadata only** — never the stored states. That is the discipline
`SnapshotStore.list` already follows, and for the same reason: a history list is read constantly
and the states are large.

`restore_revision(entry_id, n, revision)` writes the old state back **through the ordinary update
path**. A restore is therefore an ordinary edit: it bumps `revision`, appends a new revision at
the top of the history rather than rewriting it, is guarded by D19, and **computes its own retcon
answer** like any other write. One write path, no exceptions — `SnapshotStore.restore`'s rule, one
table over.

### The concurrency guard

D19's, applied unchanged. `entry.revision` is monotonic; an update presents the revision it was
read at; a stale one is refused with `409` and **nothing is written**. The client stops, says so,
and offers the server's copy. It never merges.

### What a retcon is

A **retcon** is a write the author marks as moving established facts. Only a retcon flags anything.

The store **computes** the default answer:

| Changed | Retcon by default |
|---|---|
| `name` | **yes** |
| `attributes_json` | **yes** |
| `status` | **yes** |
| `summary` only | no |
| `body_md` only | no |
| `needs_review` / `review_reason` only | no — see below |

**The request may override the answer in either direction**, and the client shows the computed
default with its reason on the save control, so a retcon is a visible act rather than a silent
consequence. That is D12's posture — the writer sees what is about to happen and decides — applied
to the bible.

Flagging on every edit was rejected: fixing a typo in a body would flag every neighbour, the flag
would become noise within a day, and **a noisy flag is an ignored flag**, which is the exact
failure this mechanism exists to prevent (outline § 9's "stale conclusions after a retcon").

### What a dependent is — exactly

> **A dependent of entry *E* is any entry joined to *E* by a live link, in either direction.**

Live means § 9's three-way predicate: the link is not deleted, and neither endpoint is deleted.
Direction does not matter — a retcon to a character moves facts for the faction it belongs to and
for the character that belongs to it alike.

That is the only relationship the data actually knows. Inferring dependents from prose mentions
was rejected: it is retrieval wearing a costume, it is Phase 5's machinery arriving two phases
early with no index behind it, and it would make the flag's behaviour depend on how a name happens
to be spelled in a sentence.

Flagging sets `needs_review` and writes a `review_reason` naming **the entry and the revision that
caused it**, so the queue tells a writer what to go and look at rather than only that something
happened. A dependent that is already flagged has its reason replaced by the newer one: the most
recent disturbance is the one worth chasing, and an entry accumulating reasons nobody trims is a
second thing to maintain.

**Flagging a dependent does not write a revision on the dependent.** `needs_review` is not a claim
the entry makes; it is a note about the entry's surroundings. Writing a revision for it would fill
a densely linked character's history with rows recording that a neighbour changed, which is
precisely the noise this rule exists to keep out of the history.

### Clearing a review is not a retcon

`clear_review(entry_id, revision)` is the writer saying they have looked. It writes a revision like
any other edit, it is guarded by D19 like any other edit, and it is **never** a retcon — not by
default and not by override.

This is the clause to get right. Without it, clearing a flag on a densely linked character
re-flags every one of its neighbours, and the queue never empties. A review queue that regenerates
itself as it is worked through is worse than none, because it teaches the writer that the queue
does not mean anything.

---

## 7. Story-time (D28, D9 made concrete)

### It is a partial order, not a number

Two things carry story-time information, and neither is a date:

1. **An event's `story_time` attribute** — a `label` (free text, and the only part that is ever
   displayed as "when"), an optional numeric `sort_key`, and an optional `era` name. All three are
   optional; an event may have none.
2. **`precedes` links between events** — the explicit ordering constraints.

**No calendar is ever parsed, and none is ever required** (D9). A secondary-world calendar does not
parse, and requiring one would make story-time unusable for exactly the manuscripts this product
exists for. `label` is what a person wrote: *"the third night of the flood"*, *"eleven years
before"*, *"Midwinter, 1204"*. It is characters. It never sorts.

### The three forms an event's placement can take

| The event has | It is |
|---|---|
| A `sort_key`, or an incident `precedes` edge, or both | **Placed** — it appears in the order |
| Neither | **Unplaced** — D9's tray |
| A `label` and nothing else | **Unplaced.** A label is for reading, not for sorting |

### What the ordering module returns

`archetype/bible/storytime.py` is **pure** in the sense `projection.py` and `anchors/resolve.py`
are: `(events, precedes-edges) → ordering`, no database, no I/O. Phase 6's agent and Phase 8's view
therefore get identical answers without going through HTTP, and the corpus that proves it is JSON.

It returns exactly three things and never more:

- **The order** — a topological sort over `precedes`, refined by `sort_key` among events the edges
  leave unordered, with a stable final fallback so two runs never disagree.
- **The unplaced** — the events above.
- **The contradictions** — of which there are **exactly two kinds, and no others**:
  1. a **cycle** in `precedes`, reported with the cycle's members;
  2. a **`sort_key` inversion**: an edge `A precedes B` where both carry a `sort_key` and A's is
     the greater.

### What it must never do

**It must never invent an order** (D9, in as many words). An event it cannot place is reported as
unplaced — not appended, not dropped, not sorted by name or creation date.

And a contradiction never costs the rest of the graph: **a cycle is reported as a cycle and
everything outside it is still ordered.** A timeline that refuses to draw anything because two
events disagree is a timeline nobody can use to find the disagreement.

The invariant, asserted once over the whole corpus rather than per case:

> **Every returned order respects every non-contradictory edge.**

### Eras

An **era is not a stored entity.** It is a name on an event, exactly as `label` is.

Eras order by the **least `sort_key` among their members**. An era whose members all lack a
`sort_key` has no rank, and that is **not a contradiction** — it is an era nobody has placed yet.
Eras are otherwise a display grouping and carry no ordering power of their own: two events in the
same era are ordered by the same rules as any other two.

---

## 8. Citations — where the bible meets the manuscript

A citation is a row in `entry_anchor`: `(entry_id, anchor_id, role)`, with `role` one of
`source` · `mention` · `setup` · `payoff`. An entry may cite an anchor in more than one role, and
that is the primary key.

This is the phase where anchors acquire their first real consumer. An entry's detail view lists
its citations with **each anchor's current status**, read through `AnchorStore` — which is where
`stale` stops being an abstraction: the passage that produced this entry has been rewritten, and
the writer can see that *before* trusting the entry.

### Creating an entry from a selection

*Add to bible* sends a **ProseMirror range and a document version**, exactly as marking a passage
does. The server derives the quote (phase-3-plan § 2, ruling 8).

The anchor is minted through `AnchorStore.create` and by **no other means**. A second creation path
is where a client-supplied quote sneaks in, and an anchor whose quote the client chose is an anchor
that can disagree with the manuscript from the moment it exists.

It is **one transaction**: mint the anchor, create the entry, cite it with role `source`. A stale
document version is refused with the same `409` a save is, and **nothing is written** — not the
anchor, not the entry, not the citation.

### Narrative position is derived, never stored

An entry's position in the book comes from its `source` anchor: the anchor's document
`order_index`, then its `from_pos`. It is computed on read.

So it **moves when the writer reorders chapters, for free**, and an entry with no `source` anchor
simply has no narrative position — which is exactly D9's unplaced tray arriving from the data
rather than from a flag somebody has to maintain.

### The two deletions do not reach each other

- **Deleting an anchor removes its citations and leaves the entries.** The entry stays, with one
  fewer reason to believe it.
- **Soft-deleting an entry leaves its citations and its anchors untouched.** An anchor is a fact
  about the manuscript; an entry is not.

Neither operation touches the other's rows beyond that. And a *chapter* deleted takes nothing
away: its anchors read `orphaned` (D22, derived from `deleted_at` and never written), so the
citation says the passage is away rather than gone, and restoring the chapter returns every
citation to the status it held.

---

## 9. The live predicates (D25, phase-3-plan § 2, ruling 9)

Deleting an entry or a link is a **soft delete**, exactly as D22 made deleting a chapter one. The
row, its revisions, its links, and its citations all stay. Restoring is one click, and it brings
back exactly the links the entry had.

**An entry is live when `deleted_at IS NULL`.** That is the whole of it, and every read path
filters on it: the list, the counts, the review queue, the link views, the citation views, and the
dependent computation in § 6.

**A link is live when the link is not deleted *and neither endpoint is deleted*.** Three
conditions, one predicate, written **once** and spliced into every query that reads links.

This is the Phase 2 lesson one table wider. Forgetting one leg puts a soft-deleted character back
into a relationship view and, in Phase 8, into the interaction matrix — where it surfaces as a
wrong chart and is reported as a Phase 8 bug, two phases from the query that caused it. One test
asserts a link to a deleted entry is absent from **every read path together**, for the same reason
`P2-2`'s does: a predicate that leaks in one query is invisible until it is expensive.

Restoring an entry does **not** restore links that were deleted in their own right. A link deleted
deliberately stays deleted; only the ones hidden by the endpoint's deletion come back. The two are
distinguishable because the link's own `deleted_at` is untouched by an endpoint's delete — nothing
cascades, which is what makes restore exact.

---

## 10. Status, origin, and the vocabulary with no writer

`status` is `proposed` | `accepted` | `rejected` | `superseded`. `origin` is `user` | `agent`.

**Everything a person types is `accepted`, and `origin` is always `user` in Phase 3.** The other
three statuses and the `agent` origin are written into the vocabulary here and have **no writer in
this phase** — exactly as `pre-import` was registered in Phase 2 with nothing to write it
([phase-2-plan](phase-2-plan.md) § 7, `D1`). They exist so that Phase 7's proposal queue lands in
a shape the storage, the API, and the client already understand, rather than as a migration.

Nothing in Phase 3 may *use* them as a general-purpose state field. In particular, `superseded` is
not the answer to "this entry is out of date" — that is `needs_review`, and the two are
**orthogonal on purpose**: `status` is the proposal lifecycle, and `needs_review` is "something
this depended on moved". An entry can be `accepted` and flagged, which is the common case after a
retcon and the entire point of the queue.

---

## 11. Deliberate extension points

Named so that a later phase recognises the seam rather than inventing one beside it.

| Seam | For | Phase |
|---|---|---|
| `status` beyond `accepted`, and `origin: agent` | The proposal queue; per-kind auto-accept toggles ship off (D5) | 7 |
| `entry_revision.origin` | Distinguishing an agent's accepted proposal from a typed edit in the history | 7 |
| `entry_link.attributes_json` | Relationship strength or sentiment on a link, if Phase 8's chart ever wants it | 8, or backlog |
| The `q` filter on the entry list | Replaced by, never renamed to, Phase 5's `/search`. This filter is a `LIKE` over `name`, aliases, and `summary`, and is honest about being a filter (phase-3-plan § 2, ruling 4) | 5 |
| A `merge` of two entries | Extraction produces near-duplicates; a person typing does not, so it is not built here | 7 |
| `sort_key` as a float | It is a number, not an integer, precisely so an event can be inserted between two others without renumbering | — |

---

## 12. Corrections

*Where the code corrected this document, the correction is recorded here and cross-referenced to
[`specs/phase-3-plan.md`](phase-3-plan.md) § 7 — the discipline `anchors.md` carries for its four.
A specification that describes something the code no longer does is a bug.*

**None yet.** This document precedes the code it governs.
