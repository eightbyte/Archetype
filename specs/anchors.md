# Archetype — Anchors

**Status:** Specification · built in P2-5 to P2-8, reconciled with the code at P2-15 ·
**Version:** 1.2 · **Date:** 2026-08-31
**Parent:** [`specs/project-outline.md`](project-outline.md) ·
**Decisions:** [`specs/development-phases.md`](development-phases.md) § 1 (D1, D18, **D21**, **D22**)
**Plan:** [`specs/phase-2-plan.md`](phase-2-plan.md) — this document is `P2-4`; it governs `P2-5`
through `P2-8`, and the four places the code corrected it are marked here and cross-referenced to
that plan's § 7 (`B1`–`B5`)
**Companions:** [`specs/data-model.md`](data-model.md) § 3 (the `anchor` table) ·
`server/archetype/manuscript/projection.py` (the docstring that fixes `text_plain`)

An **anchor** is a durable reference to a range of manuscript text. The writer selects a passage;
the anchor keeps pointing at that passage while the writer edits around it, reflows it, moves the
chapter, deletes the chapter and puts it back, restores an old version of it, or replaces the
whole file from a Markdown import.

The outline calls this the single hardest technical problem in the project (§ 4.2) and the top
entry in its risk table (§ 9). The reason is not that it is difficult to make anchors mostly work.
It is that **an anchor that is wrong does not fail.** It quietly cites the wrong paragraph, in a
bible entry the writer trusts, forever. Nothing above Phase 2 detects it, and no later phase can
repair it.

So the promise this document makes is narrow and absolute:

> **An anchor that reports `ok` points at text equal to its quote. There is no case in which the
> resolver returns `ok` and is wrong.**

Everything else here — how much editing an anchor survives, how good the suggestions are, how
fast resolution runs — is a quality that can be improved later. That one is a correctness
property, it is asserted across the whole corpus as a property rather than per case (`P2-8`), and
it is the acceptance bar for the phase.

---

## 1. What an anchor is, and what it is not

### The record

| Field | Type | Role |
|---|---|---|
| `id` | `anc_…` | Identity |
| `project_id`, `document_id` | ids | Scope. An anchor lives in exactly one document |
| `from_pos`, `to_pos` | ProseMirror positions | **The fast path, not the truth.** Where the quote was at `document_version` |
| `quote` | text | The anchored text, taken from `text_plain`. **This is what the anchor means** |
| `prefix`, `suffix` | text | Up to `CONTEXT_CHARS` of `text_plain` either side. What tells two identical sentences apart |
| `status` | `ok` \| `stale` | The last resolution's answer about the text |
| `label` | text | The writer's note on it. Free text, may be empty |
| `document_version` | integer | The version those positions were true at |
| `created_at`, `updated_at`, `checked_at` | timestamps | `checked_at` is when resolution last ran, which may be long after `updated_at` |

The client never sends `quote`, `prefix`, or `suffix`. It sends a range and a version; **the
server derives the text from the stored content** (`P2-7`). A client cannot create an anchor whose
quote disagrees with the manuscript, because it is never asked what the manuscript says.

### What it promises

- If its exact text is still in the document and can be identified unambiguously, the anchor finds
  it, wherever it has moved to.
- If it cannot, the anchor says so — `stale` — and **keeps its old positions**. It does not move
  to somewhere approximately right.
- Its status is a statement about the document as it is *now*, recomputed on every write and on
  every read, never latched (§ 5).

### What it does not promise

Stated in as many words, because each of these is a thing someone will reasonably assume:

- **It does not survive its passage being deleted.** Deleting the anchored text makes the anchor
  `stale`. That is the correct outcome and not a bug to be fixed by matching harder.
- **It does not track meaning.** It matches characters. Rewriting a sentence to say the same thing
  differently breaks the anchor, and should.
- **It is not a range of blocks.** One contiguous run of text, inside one document. No anchor to a
  chapter, a heading, or a scene; no anchor spanning two documents. A heading is addressed by its
  ordinal, which the projection already derives on every save
  ([phase-2-plan](phase-2-plan.md) § 2, ruling 1).
- **It is not a lock, and it is not a reservation.** It confers no rights over the text it points
  at. The writer owns the words (D12).
- **Its positions are a cache.** `from_pos`/`to_pos` are what the last resolution concluded. A
  reader that has not re-resolved must not treat them as current.
- **It is not stable across a change to the projection rules.** `text_plain` is the coordinate
  space anchors live in, so changing how a node projects moves every anchor in every project. That
  is why the projection's rules are a written specification with a shared fixture corpus behind
  them, and why changing one is a spec change (`P1-7`, `P1-10`).

---

## 2. The two coordinate systems

An anchor is **authored** in ProseMirror positions — that is what a selection gives you and what a
decoration needs — and **matched** in `text_plain` offsets, because that is where the quote and its
context live. These are different spaces, and the relationship between them is not linear across a
document.

### ProseMirror positions, briefly

Position `0` is before the document's first child. Entering or leaving any node costs one
position. A text node of *n* characters spans *n* positions. A leaf node — `horizontalRule`,
`hardBreak` — occupies exactly one.

### `text_plain` offsets

Defined entirely by `projection.py`, whose docstring is the authority. What matters here:

- Each `paragraph` and `heading` contributes **one block** of text, with its marks dropped.
- A `horizontalRule` contributes a block reading `* * *` (`SCENE_BREAK`), five characters.
- A `hardBreak` contributes one newline **inside** a block.
- Blocks are joined by `BLOCK_SEPARATOR` — exactly one blank line, `"\n\n"`.
- **A block that comes out empty is dropped**, so two separators never sit next to each other and
  an empty paragraph contributes nothing at all.
- Each line of a block is trimmed and empty lines within a block are dropped, so a block can never
  forge a block boundary.

### Why they cannot be related by arithmetic

Two sibling paragraphs are two positions apart (leave the first, enter the second) and two
characters apart in `text_plain` (`\n\n`). A paragraph that closes a blockquote is *three*
positions from the next paragraph (leave the paragraph, leave the blockquote, enter the next
paragraph) and still two characters. A `horizontalRule` is one position and five characters.
The offset between the two spaces therefore changes at every block boundary, by an amount that
depends on the nesting the writer happens to have made.

They **are** linear *within* a text block: a text node contributes its length to both, and a
`hardBreak` contributes one position and one newline. So the conversion is a lookup of which block
an offset is in, followed by arithmetic inside it. That is the block index.

### The block index (`P2-5`)

`Projection` gains `blocks: tuple[Block, ...]`, produced by the **same walk** that produces
`text_plain` — not a second walk, because two walks over the same tree are two chances to disagree
about what a block is, and an index that disagrees with the text it indexes makes every anchor in
the project subtly wrong at once.

| Field | Meaning |
|---|---|
| `pm_from`, `pm_to` | The ProseMirror positions of the block's **content** — for a text block, one past the position of the node itself |
| `text_from`, `text_to` | The block's span in `text_plain`, excluding the separators around it |
| `mappable` | Whether an anchor may begin or end inside this block, and whether an offset in it converts to a position |
| `raw` | The block's inline text *before* the projection trimmed it. Not part of the index as such: it is what makes the walk below a function of the projection alone, so nothing downstream has to hold the document JSON to convert a position (phase-2-plan § 7, B1) |

**`mappable` is false for a `horizontalRule`.** It reads as five characters that nobody typed and
occupies one position; there is no honest correspondence between the two, and no anchor may begin
or end inside it or span across one. It is the only non-mappable block type in the closed schema
(`P1-10`), and a node added to that schema must be given an answer here in the same change.

An empty paragraph or heading contributes no block to `text_plain`; it appears in the index with a
zero-length text span so that positions on either side of it convert correctly, and it is not
mappable, because there is nothing in it to anchor.

### The two conversions

Both are pure, both are tested at their edges (`P2-5`):

**`text_offset → pm_position`.** Find the block whose `[text_from, text_to]` contains the offset,
then walk that block's inline nodes, adding each text node's length and one for each `hardBreak`,
until the block-relative offset is consumed. An offset that falls in the `BLOCK_SEPARATOR`
*between* two blocks converts to the end of the preceding block — not the start of the following
one — so that a range and its end never straddle a boundary in different directions. An offset
inside a non-mappable block has no position.

> The walk, not arithmetic, is the specification. In the overwhelmingly common case — a block
> whose lines needed no trimming — the walk is exactly `pm_from + (offset - text_from)`, and an
> implementation is free to take that shortcut when the block's projected length equals the length
> of the text its inline nodes hold. It must not take it otherwise: the projection trims each line
> and drops empty ones, so a paragraph carrying a stray trailing space is shorter in `text_plain`
> than in the document, and arithmetic would silently point one character early for every
> character that was trimmed away.

**`pm_range → text_span`.** The same, in reverse, for both ends. A range whose ends fall in
different blocks is a real range; the text span runs from the first to the last and includes the
separators between them.

An end that falls where there is no mappable text — before the first block, inside an empty
paragraph, in the structure between two blocks — snaps toward the text the range **encloses**: a
start forward, an end backward. Snapping both ends backward, which is what "the same, in reverse"
says if read literally, would mean *select all* (`from_pos = 0`, a position inside no block at
all) yields no range, so an anchor over the whole of a first paragraph could not be made. The
directional snap can only shrink a range onto real words; it never widens one, and it never
invents text (phase-2-plan § 7, B2).

A range that **spans** a scene break is refused by this conversion rather than only at creation
(§ 8), so the rule lives in one place. The distinction it draws is the block's *text*: a
`horizontalRule` reads as five characters nobody typed, so a quote across one would carry them,
while an empty paragraph contributes nothing and spanning one is ordinary. Both are non-mappable;
only the first is unspannable (phase-2-plan § 7, B3).

---

## 3. Constants

Every one of these appears in the code under the name it has here.

| Name | Value | Why this value |
|---|---|---|
| `CONTEXT_CHARS` | `48` | Roughly a line of prose either side. Long enough that two occurrences of the same sentence are almost always told apart by it; short enough that editing *near* the anchor does not destroy all of it, and that the storage cost is 96 characters per anchor rather than a paragraph |
| `MAX_QUOTE_CHARS` | `4000` | About two long paragraphs. An anchor over more than that is really "a section", which Phase 2 deliberately does not have (§ 1). It also bounds the per-anchor cost of the scan |
| `MIN_CONTEXT_SCORE` | `12` | The least surrounding agreement that counts as disambiguation in step 4 — two or three words. Below that, "context" is a coincidence of common words |
| `WIN_MARGIN` | `8` | How far the winner must beat the runner-up by. Two candidates in near-identical surroundings both lose, and the writer is asked |
| `MAX_SUGGESTION_CHARS` | `4 × len(quote) + 2 × CONTEXT_CHARS` | The largest span that may be offered as a suggestion (§ 6). Beyond it, the writer replaced far more than the anchored passage and pointing at all of it is noise. Spelled in the code as `max_suggestion_chars(quote)`, a function: its value depends on the anchor, and a module constant cannot |
| `RESOLUTION_BUDGET_MS` | `250` | The whole-document budget in `P2-7`'s test: 200 anchors over 100,000 characters, median of five runs. It exists to catch a **change of algorithmic class**, not to benchmark a machine, so it is set generously and a failure means the resolver got cleverer and slower |

Module constants, not settings: a setting is a promise to support every value of it, and none of
these has a second value anyone wants ([phase-2-plan](phase-2-plan.md) § 2, ruling 8).

---

## 4. The whitespace normal form

**Matching is whitespace-normalised; offsets are not.** Reflowing a paragraph — joining two lines,
splitting one, changing a `hardBreak` to a space — must not break an anchor, because the writer
did not touch a word of it. But the anchor must still come back as a range in the *real* text.

So resolution works in a normalised copy and maps its answer back.

### `normalise(text) → (normal, starts, ends)`

- Every maximal run of Unicode whitespace becomes a **single space** (U+0020).
- Nothing else changes. **Matching is case-sensitive** and no punctuation is folded: a quote is
  the writer's words, and `Grey` is not `grey`.
- Nothing is trimmed from the ends, because trimming would silently shift every offset after it.
- `starts[i]` is the offset in `text` of the first character of whatever produced `normal[i]`;
  `ends[i]` is one past the last. For a collapsed run these differ by the run's full length.

The normalised copy of a document's `text_plain` is built **once per resolution pass**, not once
per anchor. That is what keeps re-resolution linear in the number of anchors rather than quadratic
(§ 7).

### Mapping a normalised match back

A match at `[i, j)` in `normal` becomes the real span `[starts[i], ends[j - 1])`. That span is
then **trimmed inward** so it begins and ends on a non-whitespace character: a collapsed run at
either edge of the match would otherwise pull the span across whitespace the writer would not
consider part of their passage. If trimming empties the span, the candidate is discarded — it
matched nothing but whitespace.

Getting this wrong in one direction breaks anchors on reflow; getting it wrong in the other makes
two genuinely different passages compare equal. Both directions are in the `P2-8` corpus.

---

## 5. The matching ladder

Tried in order. The **first** step that produces a confident answer wins; a step that is not
confident falls through rather than guessing.

Everything below happens in normalised space, against the normalised `quote`, `prefix`, and
`suffix`. A quote that is empty after normalisation cannot be created (§ 8) and, if one is
somehow found in storage, resolves to `stale` without any search.

### Step 0 — the document is gone

If the document does not exist, the anchor is dangling and is a bug in whatever deleted the row.
If the document is **soft-deleted** (D22), the anchor reads as `orphaned`.

`orphaned` is **derived on read from `document.deleted_at`, never written into the anchor row**
(`archetype/manuscript/anchors/status.py`). A soft delete changes no manuscript text, so the
anchor's stored answer about the text stays exactly as true while the chapter is away as it was
before it went — which is why restoring a chapter returns every one of its anchors to the status
the resolver actually gave, with nothing re-derived and nothing invented.

### Step 1 — the fast path

The stored `[from_pos, to_pos]`, converted through the current block index, yields text whose
normalised form is exactly `quote`.

→ **`ok`**, positions unchanged. One conversion and one string comparison, which is what makes the
common case — nothing above this anchor changed — nearly free.

If `document_version` still equals the document's version, this step is *certain* to succeed
unless something wrote text without going through `save_content`; it is still checked, because
that is precisely the case anchors exist to survive.

### Step 2 — context-unique

`prefix + quote + suffix` occurs **exactly once** in the normalised text.

→ **`ok`**, relocated to the quote's span within that occurrence.

This is the strongest evidence available: the passage and both its surroundings are intact and
unique together.

### Step 3 — quote-unique

`quote` occurs **exactly once**.

→ **`ok`**, relocated.

The surroundings changed but the passage is unique in the document, so there is nothing it could
be confused with. This is the step that carries "the writer rewrote the paragraph above it".

### Step 4 — quote-ambiguous, decided by context

`quote` occurs several times. Each occurrence is scored:

```
score(candidate) = common_suffix_length(text_before_candidate, prefix)
                 + common_prefix_length(text_after_candidate,  suffix)
```

— that is, how many characters of the stored `prefix` still run up to this candidate, plus how
many characters of the stored `suffix` still run on from it. Each term is bounded by
`CONTEXT_CHARS`, so the maximum is `len(prefix) + len(suffix)`.

A candidate wins only if **both** hold:

1. `score ≥ MIN_CONTEXT_SCORE`, and
2. `score ≥ second_best + WIN_MARGIN`.

→ **`ok`**, relocated — otherwise fall through to step 5.

Two consequences worth stating, because both are deliberate:

- An anchor created with **no** context (at the very start and end of a short document, so that
  `prefix` and `suffix` are both empty) can never clear `MIN_CONTEXT_SCORE`, so a duplicated
  quote makes it `stale`. That is correct: there is genuinely no evidence to choose with.
- Two candidates in near-identical surroundings — the same sentence in two near-identical
  passages — both lose. The writer is asked. This is the case the whole ladder exists to refuse.

### Step 5 — no clear winner

→ **`stale`**. Positions are left exactly where they were, and a *suggestion* may be attached
(§ 6). The suggestion is never applied.

### The one invariant

Before any step returns `ok`, the resolver **re-reads the text at the span it is about to return
and checks that its normalised form equals `quote`.** Not because the steps are expected to be
wrong, but because this check is the difference between "we believe the algorithm is correct" and
"the output is verified". It is cheap — one substring comparison — and it is the mechanical
guarantee behind the promise at the top of this document.

If that check fails, the answer is `stale`, not the span.

---

## 6. The suggestion protocol

A `stale` anchor may carry a suggested range, so that repairing it is a click rather than a hunt.
A suggestion is **data attached to a finding, never an action.** Nothing in the server applies
one; the writer accepts it through `PATCH /api/anchors/{aid}` (`P2-10`), which re-derives the
quote and context from the new range like any other re-link.

**Suggestions are computed from the surroundings, not from a fuzzy match on the quote.** This is
deliberate. A fuzzy quote match is exactly the machinery that, under pressure to reduce the number
of stale anchors, turns into automatic repointing — and a wrong automatic repoint is invisible.
Matching on the *unedited surroundings* of an *edited* passage is both the common case and the one
where the evidence is real.

The rule:

1. Take the normalised `prefix` and `suffix`.
2. If `prefix` is non-empty, it must occur **exactly once**; the region starts at the end of that
   occurrence. If it is empty, the region starts at the document start.
3. If `suffix` is non-empty, it must occur **exactly once at or after** that point; the region
   ends at the start of that occurrence. If it is empty, the region ends at the document end.
4. At least one of `prefix` and `suffix` must be non-empty — otherwise the "suggestion" is the
   whole document.
5. The region, mapped back to real offsets and trimmed (§ 4), is the suggestion, unless it is
   empty or longer than `MAX_SUGGESTION_CHARS`, in which case there is none.

Two substring searches, bounded by construction. No scoring, no threshold to tune, and no way for
it to grow into a matcher.

A `stale` anchor with no suggestion is a perfectly ordinary outcome. The UI offers *Pick manually*
and *Delete*, and says plainly that it does not know where the passage went.

---

## 7. Where resolution runs, and what it costs

`archetype/manuscript/anchors/resolve.py` is **pure** — `(anchor record, document) → resolution` —
in the same sense `projection.py` is pure and for the same reasons: every case is data, the corpus
drives it directly, and Phase 6's agent gets identical behaviour without going through HTTP. It
imports nothing from `archetype.projects` and nothing from `archetype.api`.

It runs in exactly two places:

- **Inside the save transaction**, for every anchor of the document being written, so the stored
  status is right no matter who wrote — the editor, a snapshot restore, a file changed behind the
  app's back, or a Phase 6 accepted proposal (D21). `SaveResultOut` carries back every anchor
  whose status or position moved, which saves the client a round trip on the request that happens
  most often.
- **On read**, without persisting, so a document opened after its file changed behind the app's
  back reports what is true now rather than what was true at the last write.

Markdown **import** is not in that list, and the reason is worth stating: it goes through
`DocumentStore.create`, never `save_content` (phase-2 plan § 2, ruling 5). A chapter an import
has just made has no anchors in it, so there is nothing to resolve. That stays true only while
import creates rather than replaces; the day it can overwrite a chapter it will be a save like
any other, and re-resolution will already be waiting for it.

**There is one implementation, not two.** Unlike the projection, the client gets no mirror: for
the open document ProseMirror's transaction mapping is exact and free, and after a reload the
server's answer arrives with the document. The client's mapping is **display-only** — it is never
sent and never overrides a text match (D21).

### Cost

Resolution of one document is `O(A × N)` in the worst case — `A` anchors over `N` characters — and
runs on every autosave. The things that keep the constant small:

- The normalised text and its offset arrays are built **once per pass**, not per anchor.
- Step 1 is one conversion and one comparison, and it is the answer for every anchor the edit did
  not reach — which, while someone is typing, is nearly all of them.
- `MAX_QUOTE_CHARS` bounds each search.

`P2-7` asserts `RESOLUTION_BUDGET_MS` at 200 anchors over 100,000 characters. A resolver that gets
cleverer and slower is then caught by the suite rather than by a writer whose typing has started
to stutter.

---

## 8. What is refused at creation

`POST /api/documents/{did}/anchors` carries `{from_pos, to_pos, version, label?}` and nothing else.
Refused, with nothing written:

| Refused | Because |
|---|---|
| `from_pos == to_pos` | A zero-length anchor has no quote, so it has nothing to match on and could never be verified |
| A range outside the document | It does not describe anything |
| A range beginning or ending in a non-mappable block, or spanning one | Its ends have no honest offset (§ 2) |
| A quote longer than `MAX_QUOTE_CHARS` | § 3 |
| A quote that is empty or only whitespace after normalisation | Same reason as zero-length: nothing to match |
| A `version` that is not the document's current one | `409`, exactly as a save is. An anchor over text that has since changed is an anchor over text nobody looked at (D19) |

The same rules apply to a re-link (`PATCH`), which re-derives quote and context from the new range.

---

## 9. Lifecycle

```
                    resolution finds the quote
              ┌───────────────────────────────────┐
              │                                   │
              ▼                                   │
          ┌──────┐   quote gone or ambiguous   ┌───────┐
   ──────▶│  ok  │ ──────────────────────────▶ │ stale │
  create  └──────┘                             └───────┘
              │                                   │
              │   the document is soft-deleted    │
              └───────────────┬───────────────────┘
                              ▼
                        ┌──────────┐
                        │ orphaned │   (derived, not stored — D22)
                        └──────────┘
                              │  the chapter is restored
                              ▼
                    back to whichever of ok / stale
                        the row already held
```

**Status is recomputed, never latched.** An undo that restores a deleted passage returns its
anchor to `ok` on the next save. `stale` is a statement about the text as it is now, not a mark
the anchor carries for the rest of its life. This is why the corpus includes "the document is
emptied, then restored by undo" as a case, and why the resolver has no notion of an anchor having
"been" stale.

An anchor is only ever removed by the writer deleting it.

---

## 10. The test corpus (`P2-8`)

The corpus is written **from this document**, not recorded from the code. A corpus generated by
running the implementation asserts that the code does what it does.

`server/tests/fixtures/anchors/cases.json`, in the shape the projection corpus established: each
case is *(document before, anchored range, document after, expected outcome)*. It covers, at
minimum:

| Case | Expected |
|---|---|
| An edit far above the range | `ok`, moved |
| An edit far below | `ok`, unmoved |
| An edit immediately before | `ok` |
| An edit immediately after | `ok` |
| An edit **inside** the range | `stale` |
| The quote deleted | `stale` |
| The quote duplicated elsewhere afterwards | `ok` — context decides (step 4) |
| The quote already appearing twice at creation | `ok` — created with distinguishing context |
| A paragraph split through the range, with nothing added | `ok` — the separator normalises, exactly as it does for a merge |
| A paragraph split through the range, with new words written into the gap | `stale` |
| Two paragraphs merged across it | `ok` — the separator normalises |
| A reflow changing only whitespace | `ok`, same characters |
| The document emptied | `stale` |
| The document emptied and restored by undo | `ok` again — status is not latched |
| The chapter deleted, then restored | `orphaned`, then exactly the status it held before |

> **Corrected in P2-6.** This table first said a paragraph split through the range yields
> `stale`, which contradicts both the row beneath it and § 4. A split and a merge are the same
> operation seen from two sides — one turns a space into a separator, the other a separator into
> a space — and a normal form cannot collapse whitespace in one direction only. Keeping the
> original reading would mean matching on block structure as well as characters, which makes the
> *merge* case stale too and gives up the reflow guarantee § 4 exists for. What is genuinely
> stale is a split with **new words written into the gap**, because then the passage is no longer
> contiguous; the corpus carries both (phase-2-plan § 7, B4).

Plus:

- **Property tests** over generated edits: for a corpus of documents and anchors, applying *N*
  random edits that do not touch the anchored text leaves the anchor `ok` and pointing at the same
  characters. The exit criterion stated as a property rather than as an anecdote.
- **The negative property, which matters more:** across every case in the corpus, an anchor that
  ends `ok` points at text whose normalised form equals its quote. Asserted once over the whole
  corpus rather than per case, so a case added later is covered by it without anyone remembering.

---

## 11. Deliberate extension points

Recorded so that taking one is a decision rather than a discovery, and so that not taking one is
not mistaken for an oversight.

| Point | When it would be taken |
|---|---|
| **Client-supplied mapped positions as a tie-break hint** | If the `P2-8` corpus shows step 4 losing cases that ProseMirror's mapping would have kept. It stays a *hint* — never an answer, and never able to override a text match (D21) |
| **A per-block edit list in the index** | If the walk in § 2 shows up in the `P2-7` budget. It would make the conversion arithmetic again for trimmed blocks |
| **Compressed `content_json`** | A Phase 9 storage measurement, not a Phase 2 guess |
| **Anchors over structural ranges** (a heading, a scene, a chapter) | Phase 3 or later, if the bible turns out to want them. It is a different record, not a looser version of this one |

And one thing that is **not** an extension point: relaxing step 4's thresholds so that fewer
anchors go `stale`. Every individual loosening looks reasonable, the pressure to make one is
constant, and the failure it produces is invisible. That is why the thresholds are written down
here with their reasoning, and why the negative property is asserted across the whole corpus.
