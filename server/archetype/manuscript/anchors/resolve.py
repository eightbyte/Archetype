"""The anchor resolver: where a stored quote is in the document as it now is (P2-6, D21).

Pure. ``(anchor record, projection) -> resolution``, in the same sense
:mod:`archetype.manuscript.projection` is pure and for the same reasons: every case is data, the
corpus in ``tests/fixtures/anchors/cases.json`` drives it directly, and Phase 6's agent gets
identical behaviour without going through HTTP. It imports nothing from ``archetype.projects``
and nothing from ``archetype.api``.

``specs/anchors.md`` is the specification. This docstring is the same rules restated where the
code is, as ``projection.py``'s docstring does for the projection - not a summary of them.

The promise
-----------

    **An anchor that reports ``ok`` points at text equal to its quote. There is no case in
    which the resolver returns ``ok`` and is wrong.**

Everything else here - how much editing an anchor survives, how good a suggestion is, how fast a
pass runs - is a quality that can be improved later. That one cannot be detected later, because
a wrong anchor does not fail: it quietly cites the wrong paragraph in a bible entry the writer
trusts, forever. It is held up by :func:`_confirmed`, which re-reads the text at the span it is
about to return and compares it to the quote before **any** step is allowed to say ``ok``.

The ladder
----------

Tried in order; the first step that produces a confident answer wins, and a step that is not
confident falls through rather than guessing. Everything below happens in normalised space
(section 4 of the spec, :func:`normalise` here).

1. **Fast path.** The stored positions still yield exactly ``quote`` -> ``ok``, positions
   unchanged. One conversion and one comparison, which is what makes the common case - nothing
   above this anchor changed - nearly free.
2. **Context-unique.** ``prefix + quote + suffix`` occurs exactly once -> ``ok``, relocated.
   The strongest evidence available: the passage and both its surroundings, intact and unique
   together.
3. **Quote-unique.** ``quote`` occurs exactly once -> ``ok``, relocated. This is the step that
   carries "the writer rewrote the paragraph above it".
4. **Quote-ambiguous.** Each occurrence is scored on how much of ``prefix`` still runs up to it
   and how much of ``suffix`` still runs on from it. A candidate wins only if it clears
   :data:`MIN_CONTEXT_SCORE` **and** beats the runner-up by :data:`WIN_MARGIN`.
5. **No clear winner** -> ``stale``, positions left exactly where they were, with a *suggestion*
   attached when one can be computed. The suggestion is never applied.

Step 0 of the spec - the document is gone - is not here. ``orphaned`` is derived from the
owning document's ``deleted_at`` by :mod:`archetype.manuscript.anchors.status` and is never a
text answer, so a soft-deleted chapter's anchors are not re-resolved at all: nothing about the
text changed.

What this module will not become
--------------------------------

**A fuzzy matcher.** Steps 2 to 4 are exact string searches; step 4's tie-break is the only
scoring in the module and it decides *between* exact occurrences, never whether an inexact one
is close enough. The suggestion in section 6 is computed from the anchor's *unedited
surroundings*, not from a fuzzy match on its quote, precisely because a quote matcher is the
machinery that turns into automatic repointing under the standing pressure to reduce the number
of stale anchors - and a wrong automatic repoint is invisible. Relaxing step 4's thresholds is
named in ``specs/anchors.md`` section 11 as the one thing that is **not** an extension point.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from ..projection import Projection, pm_range_to_text_span, text_offset_to_pm_position
from .status import AnchorStatus

__all__ = [
    "CONTEXT_CHARS",
    "MAX_QUOTE_CHARS",
    "MIN_CONTEXT_SCORE",
    "RESOLUTION_BUDGET_MS",
    "WIN_MARGIN",
    "AnchorRangeError",
    "AnchorRecord",
    "Extraction",
    "Normalised",
    "Resolution",
    "ResolutionContext",
    "Suggestion",
    "collapse",
    "context_for",
    "extract",
    "max_suggestion_chars",
    "normalise",
    "resolve",
    "resolve_all",
]

#: How much ``text_plain`` either side of the quote an anchor stores. Roughly a line of prose:
#: long enough that two occurrences of the same sentence are almost always told apart by it,
#: short enough that editing *near* the anchor does not destroy all of it.
CONTEXT_CHARS: Final[int] = 48

#: The longest quote an anchor may hold - about two long paragraphs. An anchor over more than
#: that is really "a section", which Phase 2 deliberately does not have.
MAX_QUOTE_CHARS: Final[int] = 4000

#: The least surrounding agreement that counts as disambiguation in step 4 - two or three words.
#: Below that, "context" is a coincidence of common words.
MIN_CONTEXT_SCORE: Final[int] = 12

#: How far step 4's winner must beat the runner-up by. Two candidates in near-identical
#: surroundings both lose, and the writer is asked.
WIN_MARGIN: Final[int] = 8

#: The whole-document resolution budget asserted by ``tests/test_anchor_store.py``: 200 anchors
#: over 100,000 characters. It exists to catch a **change of algorithmic class**, not to
#: benchmark a machine, so it is set generously and a failure means the resolver got cleverer
#: and slower.
RESOLUTION_BUDGET_MS: Final[int] = 250

#: Every maximal run of Unicode whitespace, which the normal form collapses to one space.
_WHITESPACE_RUN: Final[re.Pattern[str]] = re.compile(r"\s+")


def max_suggestion_chars(quote: str) -> int:
    """``MAX_SUGGESTION_CHARS`` - the longest span that may be offered as a suggestion.

    Spelled as a function rather than a number because its value depends on the quote:
    ``4 x len(quote) + 2 x CONTEXT_CHARS``. Beyond it, the writer replaced far more than the
    anchored passage and pointing at all of it is noise.
    """
    return 4 * len(quote) + 2 * CONTEXT_CHARS


class AnchorRangeError(ValueError):
    """A range cannot become an anchor. Carries the reason, which is shown to the writer.

    Every case is listed in ``specs/anchors.md`` section 8. Raised before anything is written.
    """


@dataclass(frozen=True, slots=True)
class AnchorRecord:
    """What the resolver needs from an anchor row, and nothing else.

    ``document_version`` is deliberately absent. The spec notes that when it still equals the
    document's version the fast path is certain to succeed unless something wrote text without
    going through ``save_content`` - and that is precisely the case anchors exist to survive, so
    step 1 is checked either way and the version would only be a branch nobody may take.
    """

    from_pos: int
    to_pos: int
    quote: str
    prefix: str = ""
    suffix: str = ""


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Where a ``stale`` anchor's passage may have gone. Data on a finding, never an action."""

    from_pos: int
    to_pos: int
    text: str


@dataclass(frozen=True, slots=True)
class Resolution:
    """What the resolver concluded about one anchor, against one version of the text."""

    status: str
    from_pos: int
    to_pos: int
    #: Which rung of the ladder answered: 1 to 4 for ``ok``, 5 for ``stale``, 0 for an anchor
    #: with no quote to search for. Diagnostic - the tests assert each rung is reachable.
    step: int
    suggestion: Suggestion | None = None

    @property
    def is_ok(self) -> bool:
        return self.status == AnchorStatus.OK

    def moved_from(self, anchor: AnchorRecord) -> bool:
        """Whether this resolution puts the anchor somewhere other than where it was."""
        return (self.from_pos, self.to_pos) != (anchor.from_pos, anchor.to_pos)


@dataclass(slots=True)
class Normalised:
    """A normalised copy of some text, and the offsets it came from (spec section 4).

    ``starts[i]`` is the offset in the original of the first character of whatever produced
    ``normal[i]``; ``ends[i]`` is one past its last. For a collapsed run of whitespace those
    differ by the run's full length, which is what lets a match in normalised space be mapped
    back to a span in the real text.
    """

    normal: str
    starts: list[int] = field(default_factory=list)
    ends: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """One document, ready to resolve any number of anchors against.

    Built **once per pass** by :func:`context_for`. Building it per anchor is what would make
    re-resolution quadratic in the number of anchors instead of linear.
    """

    projection: Projection
    text: Normalised


# -- the normal form (spec section 4) ---------------------------------------------------------


def normalise(text: str) -> Normalised:
    """Collapse every run of whitespace to one space, remembering where each piece came from.

    Nothing else changes. **Matching is case-sensitive** and no punctuation is folded: a quote
    is the writer's words, and ``Grey`` is not ``grey``. Nothing is trimmed from the ends,
    because trimming would silently shift every offset after it.
    """
    parts: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    position = 0

    for run in _WHITESPACE_RUN.finditer(text):
        run_from, run_to = run.span()
        if run_from > position:
            parts.append(text[position:run_from])
            starts.extend(range(position, run_from))
            ends.extend(range(position + 1, run_from + 1))
        parts.append(" ")
        starts.append(run_from)
        ends.append(run_to)
        position = run_to

    if position < len(text):
        parts.append(text[position:])
        starts.extend(range(position, len(text)))
        ends.extend(range(position + 1, len(text) + 1))

    return Normalised(normal="".join(parts), starts=starts, ends=ends)


def collapse(text: str) -> str:
    """The same rule as :func:`normalise`, for text whose offsets nobody needs."""
    return _WHITESPACE_RUN.sub(" ", text)


def context_for(projection: Projection) -> ResolutionContext:
    """The normalised view of one document. Build it once, resolve every anchor against it."""
    return ResolutionContext(projection=projection, text=normalise(projection.text_plain))


# -- creating an anchor (spec section 8) ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Extraction:
    """A range turned into an anchor's text, with the positions the quote actually occupies.

    The positions come back from the text, not from the request: a selection that ran into the
    whitespace at the end of a paragraph, or began before the first block, stores the range of
    the words it enclosed. That is what makes the fast path a comparison the anchor can win.
    """

    from_pos: int
    to_pos: int
    text_from: int
    text_to: int
    quote: str
    prefix: str
    suffix: str


def extract(projection: Projection, from_pos: int, to_pos: int) -> Extraction:
    """Derive an anchor's quote and context from a ProseMirror range.

    The client sends a range and a version; **the server derives the text from the stored
    content**. A client cannot create an anchor whose quote disagrees with the manuscript,
    because it is never asked what the manuscript says.

    Raises:
        AnchorRangeError: For every case in ``specs/anchors.md`` section 8 except the stale
            version, which is the caller's guard: a zero-length range, a range outside the
            document, a range beginning or ending in a non-mappable block or spanning one, a
            quote over :data:`MAX_QUOTE_CHARS`, and a quote that is empty or only whitespace.
    """
    if from_pos == to_pos:
        raise AnchorRangeError("an anchor needs a range of text, not a cursor position")
    if to_pos < from_pos:
        raise AnchorRangeError("the range ends before it begins")

    span = pm_range_to_text_span(projection, from_pos, to_pos)
    if span is None:
        raise AnchorRangeError(
            "that range has no honest place in the text - it lies outside the document, or "
            "begins, ends, or spans a scene break"
        )

    text = projection.text_plain
    text_from, text_to = _trimmed(text, *span)
    if text_from >= text_to:
        raise AnchorRangeError("that range holds no text to anchor")

    quote = text[text_from:text_to]
    if len(quote) > MAX_QUOTE_CHARS:
        raise AnchorRangeError(
            f"an anchor may cover at most {MAX_QUOTE_CHARS} characters; that range covers "
            f"{len(quote)}"
        )
    if not collapse(quote).strip():
        raise AnchorRangeError("that range holds no text to anchor")

    quote_from = text_offset_to_pm_position(projection, text_from)
    quote_to = text_offset_to_pm_position(projection, text_to)
    if quote_from is None or quote_to is None:  # pragma: no cover - the span converted already
        raise AnchorRangeError("that range has no honest place in the text")

    return Extraction(
        from_pos=quote_from,
        to_pos=quote_to,
        text_from=text_from,
        text_to=text_to,
        quote=quote,
        prefix=text[max(0, text_from - CONTEXT_CHARS) : text_from],
        suffix=text[text_to : text_to + CONTEXT_CHARS],
    )


# -- the ladder (spec section 5) --------------------------------------------------------------


def resolve(anchor: AnchorRecord, context: ResolutionContext) -> Resolution:
    """Where ``anchor``'s quote is in the document ``context`` describes.

    Status is **recomputed, never latched**: an undo that restores a deleted passage returns its
    anchor to ``ok`` on the next pass. ``stale`` is a statement about the text as it is now, not
    a mark the anchor carries for the rest of its life - which is why nothing here reads the
    anchor's stored status.
    """
    quote = collapse(anchor.quote)
    if not quote.strip():
        # Refused at creation, so this is a row from somewhere else. There is nothing to search
        # for, and no search is made.
        return Resolution(AnchorStatus.STALE, anchor.from_pos, anchor.to_pos, step=0)

    prefix = collapse(anchor.prefix)
    suffix = collapse(anchor.suffix)
    normal = context.text.normal

    # Step 1 - the fast path. The stored positions, read through the current index.
    span = pm_range_to_text_span(context.projection, anchor.from_pos, anchor.to_pos)
    if span is not None and collapse(context.projection.text_plain[span[0] : span[1]]) == quote:
        return Resolution(AnchorStatus.OK, anchor.from_pos, anchor.to_pos, step=1)

    # Step 2 - context-unique.
    if prefix or suffix:
        hits = _occurrences(normal, prefix + quote + suffix)
        if len(hits) == 1:
            start = hits[0] + len(prefix)
            found = _confirmed(context, quote, start, start + len(quote), step=2)
            if found is not None:
                return found

    # Step 3 and step 4 share the search: where the quote occurs, and how often.
    hits = _occurrences(normal, quote)
    if len(hits) == 1:
        found = _confirmed(context, quote, hits[0], hits[0] + len(quote), step=3)
        if found is not None:
            return found

    if len(hits) > 1:
        winner = _best_by_context(normal, hits, len(quote), prefix, suffix)
        if winner is not None:
            found = _confirmed(context, quote, winner, winner + len(quote), step=4)
            if found is not None:
                return found

    # Step 5 - no clear winner. The positions stay exactly where they were.
    return Resolution(
        AnchorStatus.STALE,
        anchor.from_pos,
        anchor.to_pos,
        step=5,
        suggestion=_suggest(context, anchor.quote, prefix, suffix),
    )


def resolve_all(anchors: Iterable[AnchorRecord], projection: Projection) -> list[Resolution]:
    """Resolve many anchors against one document, building the normalised text once."""
    context = context_for(projection)
    return [resolve(anchor, context) for anchor in anchors]


def _confirmed(
    context: ResolutionContext, quote: str, normal_from: int, normal_to: int, *, step: int
) -> Resolution | None:
    """Turn a match in normalised space into a verified ``ok``, or into nothing.

    **This is the one gate.** Every step that would return ``ok`` comes through here, and it
    re-reads the text at the span it is about to return and checks that its normalised form
    equals the quote. Not because the steps are expected to be wrong, but because this check is
    the difference between "we believe the algorithm is correct" and "the output is verified".
    It costs one substring comparison.
    """
    text = context.projection.text_plain
    span = _real_span(context, normal_from, normal_to)
    if span is None:
        return None

    text_from, text_to = span
    if collapse(text[text_from:text_to]) != quote:
        return None

    from_pos = text_offset_to_pm_position(context.projection, text_from)
    to_pos = text_offset_to_pm_position(context.projection, text_to)
    if from_pos is None or to_pos is None:
        return None
    return Resolution(AnchorStatus.OK, from_pos, to_pos, step=step)


def _best_by_context(
    normal: str, hits: list[int], quote_length: int, prefix: str, suffix: str
) -> int | None:
    """Step 4: the occurrence whose surroundings still agree with the anchor's, if one wins.

    ``score`` is how many characters of the stored ``prefix`` still run up to the candidate plus
    how many of the stored ``suffix`` still run on from it. Each term is bounded by the stored
    context, so the maximum is ``len(prefix) + len(suffix)``.

    An anchor created with no context at all can never clear :data:`MIN_CONTEXT_SCORE`, so a
    duplicated quote makes it ``stale``. That is correct: there is genuinely no evidence to
    choose with.
    """
    scores = sorted(
        (
            _common_suffix_length(normal[:hit], prefix)
            + _common_prefix_length(normal[hit + quote_length :], suffix),
            hit,
        )
        for hit in hits
    )
    best_score, best_hit = scores[-1]
    runner_up = scores[-2][0]

    if best_score < MIN_CONTEXT_SCORE or best_score < runner_up + WIN_MARGIN:
        return None
    return best_hit


# -- the suggestion protocol (spec section 6) -------------------------------------------------


def _suggest(context: ResolutionContext, quote: str, prefix: str, suffix: str) -> Suggestion | None:
    """Where the passage may have gone, computed from its *surroundings*.

    Two exact substring searches, bounded by construction. No scoring, no threshold to tune, and
    no way for it to grow into a matcher - which is the point. A ``stale`` anchor with no
    suggestion is a perfectly ordinary outcome, and the UI says plainly that it does not know
    where the passage went.
    """
    if not prefix and not suffix:
        # Without either, the "suggestion" would be the whole document.
        return None

    normal = context.text.normal

    region_from = 0
    if prefix:
        hits = _occurrences(normal, prefix)
        if len(hits) != 1:
            return None
        region_from = hits[0] + len(prefix)

    if suffix:
        hits = [hit for hit in _occurrences(normal, suffix) if hit >= region_from]
        if len(hits) != 1:
            return None
        region_to = hits[0]
    else:
        region_to = len(normal)

    span = _real_span(context, region_from, region_to)
    if span is None:
        return None

    text_from, text_to = span
    if text_to - text_from > max_suggestion_chars(quote):
        return None

    from_pos = text_offset_to_pm_position(context.projection, text_from)
    to_pos = text_offset_to_pm_position(context.projection, text_to)
    if from_pos is None or to_pos is None:
        return None

    return Suggestion(
        from_pos=from_pos,
        to_pos=to_pos,
        text=context.projection.text_plain[text_from:text_to],
    )


# -- small pure helpers -----------------------------------------------------------------------


def _real_span(
    context: ResolutionContext, normal_from: int, normal_to: int
) -> tuple[int, int] | None:
    """Map a match in normalised space back to a span of the real text, trimmed inward.

    A collapsed run at either edge of a match would otherwise pull the span across whitespace
    the writer would not consider part of their passage. If trimming empties the span, the
    candidate matched nothing but whitespace and is discarded.
    """
    if normal_to <= normal_from or normal_from < 0 or normal_to > len(context.text.normal):
        return None
    text_from, text_to = _trimmed(
        context.projection.text_plain,
        context.text.starts[normal_from],
        context.text.ends[normal_to - 1],
    )
    return None if text_from >= text_to else (text_from, text_to)


def _trimmed(text: str, text_from: int, text_to: int) -> tuple[int, int]:
    """Pull a span inward until it begins and ends on a non-whitespace character."""
    while text_from < text_to and text[text_from].isspace():
        text_from += 1
    while text_to > text_from and text[text_to - 1].isspace():
        text_to -= 1
    return text_from, text_to


def _occurrences(haystack: str, needle: str) -> list[int]:
    """Every start offset at which ``needle`` occurs, **overlaps included**.

    ``str.count`` counts non-overlapping occurrences, so it would call ``aa`` unique in ``aaa``
    and step 3 would relocate to the first of two. Uniqueness is the whole evidence steps 2 and
    3 rest on, so it is counted honestly.
    """
    if not needle:
        return []
    hits: list[int] = []
    at = haystack.find(needle)
    while at != -1:
        hits.append(at)
        at = haystack.find(needle, at + 1)
    return hits


def _common_prefix_length(text: str, other: str) -> int:
    limit = min(len(text), len(other))
    length = 0
    while length < limit and text[length] == other[length]:
        length += 1
    return length


def _common_suffix_length(text: str, other: str) -> int:
    limit = min(len(text), len(other))
    length = 0
    while length < limit and text[-1 - length] == other[-1 - length]:
        length += 1
    return length
