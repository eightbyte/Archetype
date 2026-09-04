"""Wire shapes for the bible routes (P3-9, P3-10, P3-11).

The Phase 1 rules apply unchanged (:mod:`archetype.api.schemas`): pydantic here, mirrored
TypeScript in ``web/src/api/types.ts``, the two held together by the contract fixtures, and every
schema **extension-only**. A separate module only because the bible adds as many shapes again as
Phases 1 and 2 put together, and one 1,900-line file is one nobody reads.

**The two closed vocabularies are not restated here.** ``kind`` and ``relation`` arrive as plain
strings and are refused by :mod:`archetype.bible.schema` - the one place their members are written
down (D26). A ``Literal`` of the seven kinds in this file would be the second copy that decision
exists to prevent, and it would be the copy that drifts, because the client fetches the other one.

What *is* restated is the vocabulary a module constant owns rather than the served definition:
:data:`EntryStatusFilter` and :data:`CitationRoleIn` spell out what
:class:`~archetype.bible.entries.EntryStatus` and
:class:`~archetype.bible.citations.CitationRole` hold, so that FastAPI refuses an unknown one with
the envelope and OpenAPI documents the set. ``test_entry_routes.py`` holds the two spellings
together, exactly as ``AnchorStatusFilter`` is held (P2-7).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..bible.citations import Citation, CitingEntry, CreatedFromRange, NarrativePosition
from ..bible.entries import (
    MAX_NAME_CHARS,
    MAX_REASON_CHARS,
    MAX_SUMMARY_CHARS,
    Entry,
    EntryRevision,
    RevisionMeta,
    WriteResult,
    checked_body,
    clean_text,
)
from ..bible.links import Link, LinkView
from ..bible.schema import (
    MAX_STORY_TIME_CHARS,
    FieldDefinition,
    KindDefinition,
    RelationDefinition,
)
from ..bible.storytime import StoryEvent, StoryTimeContradiction
from ..bible.timeline import ProjectTimeline
from ..manuscript.anchors.store import MAX_LABEL_LENGTH, clean_label
from .schemas import AnchorOut, Wire

__all__ = [
    "AnchorEntriesOut",
    "BibleSchemaOut",
    "CitationCreateIn",
    "CitationOut",
    "CitationRemovedOut",
    "CitationRoleIn",
    "CitingEntryOut",
    "EntryCreateIn",
    "EntryDetailOut",
    "EntryFromRangeIn",
    "EntryFromRangeOut",
    "EntryLinksOut",
    "EntryListOut",
    "EntryOut",
    "EntryStatusFilter",
    "EntryUpdateIn",
    "EntryWriteOut",
    "FieldDefinitionOut",
    "KindDefinitionOut",
    "LinkCreateIn",
    "LinkListOut",
    "LinkOut",
    "LinkPatchIn",
    "LinkViewOut",
    "NarrativePositionOut",
    "RelationDefinitionOut",
    "RevisionListOut",
    "RevisionMetaOut",
    "RevisionOut",
    "RevisionRestoreIn",
    "ReviewClearIn",
    "StoryEventOut",
    "StoryTimeContradictionOut",
    "StoryTimeEraOut",
    "StoryTimeOut",
]

#: The proposal lifecycle, as a filter. ``accepted`` is the only value anything writes in Phase 3
#: - the other three are Phase 7's and have no writer (plan section 3) - but all four are readable,
#: because a filter that cannot ask for a status the column can hold is a filter that will need
#: changing the moment one exists.
EntryStatusFilter = Literal["proposed", "accepted", "rejected", "superseded"]

#: Why an entry points at a passage. ``source`` is the one narrative position derives from.
CitationRoleIn = Literal["source", "mention", "setup", "payoff"]


# -- entries (P3-9) ---------------------------------------------------------------------------


class EntryOut(Wire):
    """One bible record, in the shape every kind shares (D26).

    ``attributes`` is the per-kind map, already validated against the kind's definition - which
    the client renders a form from, and which is served by ``GET /api/bible/schema``.

    ``needs_review`` and ``review_reason`` are **orthogonal to** ``status``: one says something
    this entry depended on moved (D27), the other is the proposal lifecycle. ``superseded`` is
    not the answer to "this entry is out of date".
    """

    id: str
    project_id: str
    kind: str
    name: str
    summary: str
    body_md: str
    attributes: dict[str, Any]
    status: str
    origin: str
    revision: int
    needs_review: bool
    review_reason: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None

    @classmethod
    def of(cls, entry: Entry) -> EntryOut:
        return cls(
            id=entry.id,
            project_id=entry.project_id,
            kind=entry.kind,
            name=entry.name,
            summary=entry.summary,
            body_md=entry.body_md,
            attributes=entry.attributes,
            status=entry.status,
            origin=entry.origin,
            revision=entry.revision,
            needs_review=entry.needs_review,
            review_reason=entry.review_reason,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            deleted_at=entry.deleted_at,
        )


class EntryListOut(Wire):
    """``GET /api/projects/{pid}/entries`` - the filtered list, and two things beside it.

    ``counts`` is the number of **live** entries of each kind, unfiltered, so the tab can say how
    many characters there are while showing only the places. Every kind appears, including the
    ones with none.

    ``truncated`` says the ``q`` filter hit its cap (``SEARCH_LIMIT``). A filter that cannot say
    "there are more" is lying about what it found, which is the whole reason the cap is reported
    rather than merely applied (``specs/bible.md`` section 5).
    """

    entries: list[EntryOut]
    counts: dict[str, int]
    truncated: bool = False


class NarrativePositionOut(Wire):
    """Where an entry sits in the book, derived from its ``source`` anchor and never stored.

    It moves when the writer reorders chapters, for free, and an entry with no ``source`` anchor
    simply has none - which is D9's unplaced tray arriving from the data rather than from a flag
    somebody maintains.
    """

    entry_id: str
    document_id: str
    order_index: int
    from_pos: int

    @classmethod
    def of(cls, position: NarrativePosition) -> NarrativePositionOut:
        return cls(
            entry_id=position.entry_id,
            document_id=position.document_id,
            order_index=position.order_index,
            from_pos=position.from_pos,
        )


class CitationOut(Wire):
    """One citation, carrying the anchor **as it reads now** (P3-7).

    The status on that anchor is the effective one - ``ok``, ``stale``, or ``orphaned`` - derived
    in the one place D22 put it, so a citation can never disagree with the *Marks* tab about the
    same anchor. This is where ``stale`` stops being an abstraction: the passage that produced
    this entry has been rewritten, and the writer sees that before trusting the entry.
    """

    entry_id: str
    anchor: AnchorOut
    role: str
    created_at: str
    document_id: str
    document_title: str

    @classmethod
    def of(cls, citation: Citation) -> CitationOut:
        return cls(
            entry_id=citation.entry_id,
            anchor=AnchorOut.of(citation.anchor),
            role=citation.role,
            created_at=citation.created_at,
            document_id=citation.document_id,
            document_title=citation.document_title,
        )


class EntryDetailOut(Wire):
    """``GET /api/entries/{eid}`` - one entry with what points at it and where it sits.

    ``link_count`` is the number of live links on the entry in **either** direction, which is
    what a detail header shows; the links themselves are ``GET /api/entries/{eid}/links``, because
    a list of them is a panel of its own and is not read every time an entry is opened.
    """

    entry: EntryOut
    citations: list[CitationOut]
    link_count: int
    narrative_position: NarrativePositionOut | None = None


class EntryCreateIn(Wire):
    """``POST /api/projects/{pid}/entries``.

    ``status`` and ``origin`` are deliberately absent. Everything a person types is ``accepted``
    and ``user``; ``proposed``, ``rejected``, ``superseded``, and ``agent`` are registered in the
    vocabulary with **no writer in this phase**, exactly as the ``pre-*`` snapshot reasons are
    (P2-3). A route that accepted them would be that writer.

    ``kind`` is a plain string on purpose: it is refused by the served definition, which is the
    one place the seven are written down (D26).
    """

    kind: str
    name: str = Field(max_length=MAX_NAME_CHARS)
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    body_md: str = ""
    attributes: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return clean_text(value, limit=MAX_NAME_CHARS, what="name", allow_empty=False)

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, value: str) -> str:
        return clean_text(value, limit=MAX_SUMMARY_CHARS, what="summary")

    @field_validator("body_md")
    @classmethod
    def _check_body(cls, value: str) -> str:
        return checked_body(value)


class EntryUpdateIn(Wire):
    """``PUT /api/entries/{eid}`` - the D19 guard, applied to entries (ruling 3).

    Every content field is **optional and distinguishable from absent**: a request that does not
    mention ``summary`` must not blank it, and one that sends ``attributes: {}`` must clear them.
    :meth:`changes` reads pydantic's ``model_fields_set`` to tell the two apart, which is the same
    distinction ``UNSET`` makes inside the store.

    ``kind`` is absent because it is immutable (``specs/bible.md`` section 1), and ``status``
    because Phase 3 has no writer for the three that are not ``accepted``.

    ``retcon`` overrides the store's computed answer in either direction; ``null`` - the default -
    takes the computed one. The client shows that default with the reason it came up checked, so
    a retcon is a visible act rather than a silent consequence (D12's posture, D27).
    """

    revision: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=MAX_NAME_CHARS)
    summary: str | None = Field(default=None, max_length=MAX_SUMMARY_CHARS)
    body_md: str | None = None
    attributes: dict[str, Any] | None = None
    retcon: bool | None = None
    reason: str = Field(default="", max_length=MAX_REASON_CHARS)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_text(value, limit=MAX_NAME_CHARS, what="name", allow_empty=False)

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_text(value, limit=MAX_SUMMARY_CHARS, what="summary")

    @field_validator("body_md")
    @classmethod
    def _check_body(cls, value: str | None) -> str | None:
        return None if value is None else checked_body(value)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        return clean_text(value, limit=MAX_REASON_CHARS, what="reason")

    @model_validator(mode="after")
    def _something_to_do(self) -> EntryUpdateIn:
        # Checked through `changes()` rather than against `model_fields_set`, so that a request
        # presenting only `name: null` is refused rather than writing a revision that records no
        # change. A revision is a person's deliberate act; an empty one is noise in the one
        # history a writer consults.
        if not self.changes():
            raise ValueError("nothing to change: send a name, a summary, a body, or attributes")
        return self

    def changes(self) -> dict[str, Any]:
        """The fields this request actually presented, as keyword arguments for the store.

        An absent field is absent from the dict, so the store's ``UNSET`` default applies and the
        stored value is kept. A field sent as ``null`` is a client sending the wrong thing rather
        than asking to clear one - there is no nullable content field on an entry - so it is
        dropped here too rather than reaching the store as ``None``.
        """
        presented = self.model_fields_set & {"name", "summary", "body_md", "attributes"}
        return {
            field: getattr(self, field) for field in presented if getattr(self, field) is not None
        }


class ReviewClearIn(Wire):
    """``POST /api/entries/{eid}/review/clear`` - the writer says they have looked.

    Presents the revision like any other write, because it bumps one. It is **never a retcon**,
    not by default and not by override: a queue that re-flags every neighbour as it is worked
    through is a queue that never empties and stops meaning anything (P3-4).
    """

    revision: int = Field(ge=1)


class RevisionRestoreIn(Wire):
    """``POST /api/entries/{eid}/revisions/{n}/restore``.

    ``revision`` is the entry's current revision, not the one being restored: a restore goes
    through the ordinary update path, so it is guarded by D19, appends to history rather than
    rewriting it, and computes its own retcon answer.
    """

    revision: int = Field(ge=1)


class EntryWriteOut(Wire):
    """What an entry write did, including what it disturbed (D27).

    ``flagged`` is the point: the writer is told which entries this retcon put into the review
    queue at the moment it happens, rather than discovering it by opening the queue.

    ``changed_fields`` is which of the retcon-bearing fields actually moved, and it reports the
    **computed** answer even when the request overrode it - so an override is legible as one.
    """

    entry: EntryOut
    revision: int
    retcon: bool
    flagged: list[str]
    changed_fields: list[str]

    @classmethod
    def of(cls, result: WriteResult) -> EntryWriteOut:
        return cls(
            entry=EntryOut.of(result.entry),
            revision=result.revision,
            retcon=result.retcon,
            flagged=list(result.flagged),
            changed_fields=list(result.changed_fields),
        )


class RevisionMetaOut(Wire):
    """One revision's metadata. What the history list carries - never the stored state.

    The discipline ``SnapshotMetaOut`` already follows: a history list is read constantly and the
    states are the large part of it.
    """

    entry_id: str
    revision: int
    revised_at: str
    reason: str
    retcon: bool
    origin: str

    @classmethod
    def of(cls, meta: RevisionMeta) -> RevisionMetaOut:
        return cls(
            entry_id=meta.entry_id,
            revision=meta.revision,
            revised_at=meta.revised_at,
            reason=meta.reason,
            retcon=meta.retcon,
            origin=meta.origin,
        )


class RevisionListOut(Wire):
    """``GET /api/entries/{eid}/revisions`` - newest first, complete from creation.

    Not filtered by ``deleted_at``: the history of a deleted entry is exactly what somebody
    deciding whether to restore it wants to see.
    """

    revisions: list[RevisionMetaOut]


class RevisionOut(Wire):
    """``GET /api/entries/{eid}/revisions/{n}`` - one revision with the state it recorded.

    ``state`` holds the entry as it was **after** that write, so revision *n* is what the entry
    was at revision *n* and reading a past state is one row rather than a replay. It deliberately
    excludes ``needs_review`` and ``review_reason``: those are notes about the entry's
    surroundings, and restoring must not drag a neighbour's old disturbance back.
    """

    meta: RevisionMetaOut
    state: dict[str, Any]

    @classmethod
    def of(cls, revision: EntryRevision) -> RevisionOut:
        return cls(meta=RevisionMetaOut.of(revision.meta), state=revision.state)


# -- links (P3-10) ----------------------------------------------------------------------------


class LinkOut(Wire):
    """One relationship, as stored.

    ``since`` and ``until`` are free text and are **stored, displayed, and never interpreted**
    (D9). Nothing in Phase 3 or Phase 8 sorts by them; the relation that carries ordering power
    is ``precedes``, and it does so through the ordering module, which reads edges.
    """

    id: str
    project_id: str
    from_entry: str
    to_entry: str
    relation: str
    attributes: dict[str, Any]
    since: str | None
    until: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None = None

    @classmethod
    def of(cls, link: Link) -> LinkOut:
        return cls(
            id=link.id,
            project_id=link.project_id,
            from_entry=link.from_entry,
            to_entry=link.to_entry,
            relation=link.relation,
            attributes=link.attributes,
            since=link.since,
            until=link.until,
            created_at=link.created_at,
            updated_at=link.updated_at,
            deleted_at=link.deleted_at,
        )


class LinkListOut(Wire):
    """``GET /api/projects/{pid}/links`` - every live link, optionally of one relation."""

    links: list[LinkOut]


class LinkViewOut(Wire):
    """One link as it reads **from one entry's end**.

    ``end`` is ``from`` or ``to``, and ``label`` is how that end reads the relation - "is a member
    of" from one side, "has as a member" from the other. A symmetric relation reads the same both
    ways because its definition repeats its label, and it appears once from each side rather than
    twice from either: it is one row (ruling 7).
    """

    link: LinkOut
    end: str
    other_id: str
    other_name: str
    other_kind: str
    label: str

    @classmethod
    def of(cls, view: LinkView) -> LinkViewOut:
        return cls(
            link=LinkOut.of(view.link),
            end=view.end,
            other_id=view.other_id,
            other_name=view.other_name,
            other_kind=view.other_kind,
            label=view.label,
        )


class EntryLinksOut(Wire):
    """``GET /api/entries/{eid}/links`` - both directions in one answer.

    Every consumer wants both, and computing it twice is how the two halves come to disagree.
    """

    links: list[LinkViewOut]


class LinkCreateIn(Wire):
    """``POST /api/projects/{pid}/links``. The field order is the sentence: *from* **relation**
    *to*.

    ``relation`` is a plain string, refused by the closed vocabulary rather than by a ``Literal``
    here - the same reason ``kind`` is (D26). A relation is refused **on the side it is offered
    from**: ``member_of`` runs character to faction, and faction to character is a different
    statement, never silently reversed.
    """

    from_entry: str
    relation: str
    to_entry: str
    since: str | None = Field(default=None, max_length=MAX_STORY_TIME_CHARS)
    until: str | None = Field(default=None, max_length=MAX_STORY_TIME_CHARS)
    attributes: dict[str, Any] | None = None


class LinkPatchIn(Wire):
    """``PATCH /api/links/{lid}`` - bounds and attributes, and nothing else.

    The endpoints and the relation are **absent on purpose**: changing either is a delete and a
    create, and both are recoverable. Editing them in place would let a link's own history
    describe a relationship it never had, which is ``kind``'s immutability one table over.

    No revision is presented, because a link has none - the D19 guard lives on the entry.
    """

    since: str | None = Field(default=None, max_length=MAX_STORY_TIME_CHARS)
    until: str | None = Field(default=None, max_length=MAX_STORY_TIME_CHARS)
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _something_to_do(self) -> LinkPatchIn:
        # As the entry's, and for the milder version of the same reason: a patch that resolves to
        # no change would still move `updated_at`, which is a row saying somebody edited it.
        if not self.changes():
            raise ValueError("nothing to change: send since, until, or attributes")
        return self

    def changes(self) -> dict[str, Any]:
        """The presented fields, as store keyword arguments.

        Unlike an entry's, a bound **is** nullable: ``since: null`` clears it, and that is the
        only way to. So a presented ``None`` is passed through rather than dropped, and
        ``attributes`` - which is not nullable - is dropped when it comes as ``null``.
        """
        changes: dict[str, Any] = {
            field: getattr(self, field) for field in self.model_fields_set & {"since", "until"}
        }
        if "attributes" in self.model_fields_set and self.attributes is not None:
            changes["attributes"] = self.attributes
        return changes


# -- citations (P3-10) ------------------------------------------------------------------------


class CitationCreateIn(Wire):
    """``POST /api/entries/{eid}/citations`` - cite an anchor that already exists.

    The anchor is minted by ``AnchorStore`` and by no other means (ruling 8). This route joins an
    entry to one; ``POST /api/documents/{did}/entries`` is the one that makes both at once.
    """

    anchor_id: str
    role: CitationRoleIn = "source"


class CitationRemovedOut(Wire):
    """What an uncite removed. Zero is an ordinary answer, not a failure.

    The **anchor stays**: it is a fact about the manuscript, and the *Marks* tab is where one is
    removed. Removing a citation that is not there is not an error.
    """

    removed: int


class CitingEntryOut(Wire):
    """One entry that cites an anchor - the reverse view, so *Marks* can say it is spoken for.

    Live entries only: a soft-deleted entry is absent from every read path, and this is one. It is
    also what makes deleting an anchor honest about what it will leave behind.
    """

    entry_id: str
    kind: str
    name: str
    role: str
    created_at: str

    @classmethod
    def of(cls, citing: CitingEntry) -> CitingEntryOut:
        return cls(
            entry_id=citing.entry_id,
            kind=citing.kind,
            name=citing.name,
            role=citing.role,
            created_at=citing.created_at,
        )


class AnchorEntriesOut(Wire):
    """``GET /api/anchors/{aid}/entries``."""

    entries: list[CitingEntryOut]


class EntryFromRangeIn(Wire):
    """``POST /api/documents/{did}/entries`` - *Add to bible* (P3-7).

    A **range and a version**, never a quote: the server derives the words, exactly as marking a
    passage does (ruling 8). A stale version is refused with the same ``409`` a save gets, and
    nothing at all is written - not the anchor, not the entry, not the citation.
    """

    from_pos: int = Field(ge=0)
    to_pos: int = Field(ge=0)
    version: int = Field(ge=1)
    kind: str
    name: str = Field(max_length=MAX_NAME_CHARS)
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    body_md: str = ""
    attributes: dict[str, Any] | None = None
    label: str = Field(default="", max_length=MAX_LABEL_LENGTH)
    role: CitationRoleIn = "source"

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return clean_text(value, limit=MAX_NAME_CHARS, what="name", allow_empty=False)

    @field_validator("summary")
    @classmethod
    def _clean_summary(cls, value: str) -> str:
        return clean_text(value, limit=MAX_SUMMARY_CHARS, what="summary")

    @field_validator("body_md")
    @classmethod
    def _check_body(cls, value: str) -> str:
        return checked_body(value)

    @field_validator("label")
    @classmethod
    def _clean_label(cls, value: str) -> str:
        return clean_label(value)


class EntryFromRangeOut(Wire):
    """What *Add to bible* made: an anchor, an entry, and the citation joining them."""

    entry: EntryOut
    anchor: AnchorOut
    role: str

    @classmethod
    def of(cls, created: CreatedFromRange) -> EntryFromRangeOut:
        return cls(
            entry=EntryOut.of(created.entry),
            anchor=AnchorOut.of(created.anchor),
            role=created.role,
        )


# -- story-time (P3-10, D28) ------------------------------------------------------------------


class StoryEventOut(Wire):
    """One event as the ordering sees it. Everything but the id is optional.

    ``label`` is what a person reads as "when" and it **never sorts**; ``sort_key`` is the only
    number in story-time, and it is a float so an event can be inserted between two others
    without renumbering.
    """

    entry_id: str
    name: str
    label: str
    sort_key: float | None
    era: str | None

    @classmethod
    def of(cls, event: StoryEvent) -> StoryEventOut:
        return cls(
            entry_id=event.id,
            name=event.name,
            label=event.label,
            sort_key=event.sort_key,
            era=event.era,
        )


class StoryTimeContradictionOut(Wire):
    """Something the writer said that cannot all be true at once.

    Exactly two kinds and no others (D28): ``cycle`` and ``sort_key_inversion``. They are
    **independent** - an edge inside a cycle whose keys also disagree is reported as both, because
    a writer fixes them differently.
    """

    kind: str
    events: list[str]
    detail: str

    @classmethod
    def of(cls, contradiction: StoryTimeContradiction) -> StoryTimeContradictionOut:
        return cls(
            kind=contradiction.kind,
            events=list(contradiction.events),
            detail=contradiction.detail,
        )


class StoryTimeEraOut(Wire):
    """One era and its rank - the least ``sort_key`` among its members, or ``null``.

    An era is not a stored entity; it is a name on an event. An era whose members all lack a key
    has no rank, and **that is not a contradiction**: it is an era nobody has placed yet.
    """

    era: str
    rank: float | None


class StoryTimeOut(Wire):
    """``GET /api/projects/{pid}/storytime`` - the ordering module's three answers, and the eras.

    ``order`` and ``unplaced`` partition the events: every event appears in exactly one of them,
    always. An event with neither an edge nor a key is unplaced - not appended, not dropped, and
    never guessed at (D9).

    A contradiction never costs the rest of the graph: a cycle is reported *and* everything
    outside it is still ordered, because a timeline that refuses to draw anything until two events
    agree is a timeline nobody can use to find the disagreement.
    """

    order: list[StoryEventOut]
    unplaced: list[StoryEventOut]
    contradictions: list[StoryTimeContradictionOut]
    eras: list[StoryTimeEraOut]

    @classmethod
    def of(cls, timeline: ProjectTimeline) -> StoryTimeOut:
        by_id = {event.id: event for event in timeline.events}
        return cls(
            order=[StoryEventOut.of(by_id[event_id]) for event_id in timeline.ordering.order],
            unplaced=[StoryEventOut.of(by_id[event_id]) for event_id in timeline.ordering.unplaced],
            contradictions=[
                StoryTimeContradictionOut.of(item) for item in timeline.ordering.contradictions
            ],
            eras=[
                StoryTimeEraOut(era=era, rank=rank) for era, rank in sorted(timeline.eras.items())
            ],
        )


# -- the served definition (P3-11, D26) -------------------------------------------------------


class FieldDefinitionOut(Wire):
    """One field of one kind, with every key present whatever the type.

    ``members`` is the declared set of an ``enum`` and empty otherwise; ``kinds`` is what an
    ``entry_ref`` may point at and empty otherwise. Both are always sent, because a shape whose
    keys depend on the value of another key is one every consumer has to branch on.
    """

    name: str
    type: str
    label: str
    required: bool
    help: str
    members: list[str]
    kinds: list[str]

    @classmethod
    def of(cls, field: FieldDefinition) -> FieldDefinitionOut:
        return cls(**field.as_dict())


class KindDefinitionOut(Wire):
    """One kind's fields, **in the order a form renders them**."""

    kind: str
    label: str
    plural: str
    fields: list[FieldDefinitionOut]

    @classmethod
    def of(cls, definition: KindDefinition) -> KindDefinitionOut:
        return cls(
            kind=definition.kind,
            label=definition.label,
            plural=definition.plural,
            fields=[FieldDefinitionOut.of(field) for field in definition.fields],
        )


class RelationDefinitionOut(Wire):
    """One relation, the kinds it joins in each direction, and whether it is symmetric.

    ``symmetric`` is declared rather than inferred, so a client filtering the relation picker -
    and, in Phase 8, an adjacency matrix deciding what to mirror - asks the vocabulary instead of
    keeping its own list (ruling 7).
    """

    relation: str
    label: str
    inverse_label: str
    from_kinds: list[str]
    to_kinds: list[str]
    symmetric: bool

    @classmethod
    def of(cls, definition: RelationDefinition) -> RelationDefinitionOut:
        return cls(**definition.as_dict())


class BibleSchemaOut(Wire):
    """``GET /api/bible/schema`` - D26's definition, and the most load-bearing shape in Phase 3.

    **Project-independent**: the vocabulary is the product's, not a manuscript's, which is why
    this is the one route in the API with no project scope and the one that answers the same bytes
    for every caller.

    Everything in Groups C and D reads it, and so will Phase 7's proposal renderer. Its contract
    fixture is what fails when a kind gains a field and the client was not told.
    """

    field_types: list[str]
    kinds: list[KindDefinitionOut]
    relations: list[RelationDefinitionOut]
