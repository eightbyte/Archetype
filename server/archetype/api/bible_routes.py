"""The bible half of the ``/api`` router (P3-9, P3-10, P3-11).

The same rules as :mod:`archetype.api.routes`, and the same shape: resolve the scope, call the
store, shape the answer. Every rule that matters - the D19 guard on a revision, the retcon
computation, the three-way live-link predicate, the one transaction behind *Add to bible* - lives
in :mod:`archetype.bible`, so Phase 6's agent loop gets the same behaviour without going through
HTTP (api-contract section 1).

A second module rather than a second router: the prefix, the error envelope, and the ordering
guarantees are the API's, not the bible's. ``create_app`` includes both, and the static mount is
still registered last.

Three route families and one that belongs to none of them:

* **entries** - the record, its history, and the review queue;
* **links and citations** - the bible's two joins, one to itself and one to the manuscript;
* **story-time** - D28's three answers over the project's events;
* **the schema** - ``GET /api/bible/schema``, the one route in the API with **no project scope**,
  because the vocabulary is the product's and not a manuscript's (D26).

Bare ``{eid}`` and ``{lid}`` resolve through the existing locator - one more prefix over one
mechanism, never a second mechanism.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from ..bible.citations import CitationStore
from ..bible.entries import SEARCH_LIMIT, EntryStore
from ..bible.links import LinkStore
from ..bible.schema import ENTRY_KINDS, RELATIONS, FieldType
from ..bible.timeline import project_timeline
from ..projects.store import ProjectHandle
from .bible_schemas import (
    AnchorEntriesOut,
    BibleSchemaOut,
    CitationCreateIn,
    CitationOut,
    CitationRemovedOut,
    CitationRoleIn,
    CitingEntryOut,
    EntryCreateIn,
    EntryDetailOut,
    EntryFromRangeIn,
    EntryFromRangeOut,
    EntryLinksOut,
    EntryListOut,
    EntryOut,
    EntryStatusFilter,
    EntryUpdateIn,
    EntryWriteOut,
    KindDefinitionOut,
    LinkCreateIn,
    LinkListOut,
    LinkOut,
    LinkPatchIn,
    LinkViewOut,
    NarrativePositionOut,
    RelationDefinitionOut,
    ReviewClearIn,
    RevisionListOut,
    RevisionMetaOut,
    RevisionOut,
    RevisionRestoreIn,
    StoryTimeOut,
)
from .deps import get_locator, open_project
from .errors import error_responses

__all__ = ["router"]

router = APIRouter(prefix="/api")


# -- the served definition (P3-11, D26) -------------------------------------------------------


@router.get(
    "/bible/schema",
    tags=["bible"],
    summary="The kinds, their fields, and the relation vocabulary",
    response_model=BibleSchemaOut,
)
def get_bible_schema() -> BibleSchemaOut:
    """D26's definition as JSON - **project-independent**, and the same bytes for every caller.

    Everything in the Bible tab reads this, and so will Phase 7's proposal renderer. Adding a
    field to a kind is a change to ``archetype/bible/schema.py`` and this route's contract
    fixture, and to nothing else - which is the whole of what D26 bought.
    """
    return BibleSchemaOut(
        field_types=sorted(FieldType.ALL),
        kinds=[KindDefinitionOut.of(definition) for definition in ENTRY_KINDS],
        relations=[RelationDefinitionOut.of(relation) for relation in RELATIONS],
    )


# -- entries (P3-9) ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/entries",
    tags=["bible"],
    summary="The project's entries, filtered",
    response_model=EntryListOut,
    responses=error_responses(404, 422),
)
def list_entries(
    request: Request,
    project_id: str,
    kind: str | None = None,
    entry_status: Annotated[EntryStatusFilter | None, Query(alias="status")] = None,
    needs_review: bool | None = None,
    q: str | None = None,
    include_deleted: bool = False,
) -> EntryListOut:
    """One list route carrying every filter, because the filters compose (ruling 4).

    ``q`` is a ``LIKE`` filter over names, aliases, and summaries - a filter, **not** search, and
    deliberately not ``/search``: Phase 5 owns search and owns that route name. It is capped, and
    the cap is reported rather than merely applied.

    ``counts`` is unfiltered and live, so a client showing only the places can still say how many
    characters there are.
    """
    handle = open_project(request, project_id)
    store = EntryStore(handle)
    # One more than the cap, then trimmed: `truncated` is then exact rather than "we returned
    # exactly the limit, so there are probably more" - which is wrong for a project with exactly
    # SEARCH_LIMIT entries, and wrong in the direction that makes a writer look for a row that
    # is already on screen.
    found = store.list(
        kind=kind,
        status=entry_status,
        needs_review=needs_review,
        q=q,
        include_deleted=include_deleted,
        limit=SEARCH_LIMIT + 1,
    )
    truncated = len(found) > SEARCH_LIMIT
    return EntryListOut(
        entries=[EntryOut.of(entry) for entry in found[:SEARCH_LIMIT]],
        counts=store.counts_by_kind(),
        truncated=truncated,
    )


@router.post(
    "/projects/{project_id}/entries",
    tags=["bible"],
    summary="Create an entry",
    status_code=status.HTTP_201_CREATED,
    response_model=EntryOut,
    responses=error_responses(404, 422),
)
def create_entry(request: Request, project_id: str, body: EntryCreateIn) -> EntryOut:
    """Create an entry, and revision 1 with it, in one transaction (D27).

    An unknown kind, an attribute the kind does not declare, one of the wrong type, and a value
    outside a declared ``enum`` set are each a ``422`` naming the field, with **nothing written**.
    """
    handle = open_project(request, project_id)
    entry = EntryStore(handle).create(
        body.kind,
        body.name,
        summary=body.summary,
        body_md=body.body_md,
        attributes=body.attributes,
    )
    return EntryOut.of(entry)


@router.get(
    "/projects/{project_id}/entries/deleted",
    tags=["bible"],
    summary="Soft-deleted entries, most recently deleted first",
    response_model=EntryListOut,
    responses=error_responses(404),
)
def list_deleted_entries(request: Request, project_id: str) -> EntryListOut:
    """The restore surface (D25), on the same footing as *Deleted chapters*.

    A soft delete is only recoverable if there is somewhere to recover it from. Every other read
    path filters these out; this is the one that asks for them.
    """
    handle = open_project(request, project_id)
    store = EntryStore(handle)
    return EntryListOut(
        entries=[EntryOut.of(entry) for entry in store.list_deleted()],
        counts=store.counts_by_kind(),
    )


@router.get(
    "/entries/{entry_id}",
    tags=["bible"],
    summary="One entry with its citations and link count",
    response_model=EntryDetailOut,
    responses=error_responses(404),
)
def get_entry(request: Request, entry_id: str) -> EntryDetailOut:
    """The detail view's read.

    The citations carry each anchor's **current** status, and the narrative position is derived
    from the ``source`` anchor rather than stored - so it follows a chapter reorder for free, and
    an entry with no source simply has none.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    entry = EntryStore(handle).get(entry_id, include_deleted=True)
    citations = CitationStore(handle)
    position = citations.narrative_position(entry_id)
    return EntryDetailOut(
        entry=EntryOut.of(entry),
        citations=[CitationOut.of(citation) for citation in citations.citations(entry_id)],
        link_count=len(LinkStore(handle).for_entry(entry_id)),
        narrative_position=None if position is None else NarrativePositionOut.of(position),
    )


@router.put(
    "/entries/{entry_id}",
    tags=["bible"],
    summary="Edit an entry, presenting the revision it was read at",
    response_model=EntryWriteOut,
    responses=error_responses(404, 409, 422),
)
def update_entry(request: Request, entry_id: str, body: EntryUpdateIn) -> EntryWriteOut:
    """The D19 guard, applied to entries (ruling 3), and D27's retcon answer with it.

    A stale ``revision`` writes nothing and comes back as a ``409`` carrying the current one, so
    the client stops and offers the server's copy. It never merges.

    ``retcon`` is the store's computed answer unless the request overrides it. The response says
    which fields moved and which entries were flagged, so the writer learns what the save did at
    the moment it happens rather than by opening the queue.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    result = EntryStore(handle).update(
        entry_id,
        body.revision,
        retcon=body.retcon,
        reason=body.reason,
        **body.changes(),
    )
    return EntryWriteOut.of(result)


@router.delete(
    "/entries/{entry_id}",
    tags=["bible"],
    summary="Soft-delete an entry",
    response_model=EntryOut,
    responses=error_responses(404),
)
def delete_entry(request: Request, entry_id: str) -> EntryOut:
    """Delete an entry, recoverably (D25).

    Nothing cascades. The row, its revisions, its links, and its citations all stay; the entry
    leaves every list, count, link view, and the review queue, because all of those filter on one
    predicate. Deleting is **not** a retcon - the entry has not changed its claims, it has left
    the bible.

    ``200`` rather than ``204``, for the reason a chapter delete answers with its metadata: the
    client has just been told the entry is gone and needs to say what went and when.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    return EntryOut.of(EntryStore(handle).delete(entry_id))


@router.post(
    "/entries/{entry_id}/restore",
    tags=["bible"],
    summary="Bring a soft-deleted entry back",
    response_model=EntryOut,
    responses=error_responses(404),
)
def restore_entry(request: Request, entry_id: str) -> EntryOut:
    """Undo a delete (D25).

    Its links come back because nothing ever removed them: an endpoint's deletion *hides* a link
    through the three-way predicate rather than writing to it. A link deleted in its own right
    stays deleted. Restoring a live entry is a no-op, not an error.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    return EntryOut.of(EntryStore(handle).restore(entry_id))


@router.post(
    "/entries/{entry_id}/review/clear",
    tags=["bible"],
    summary="Clear the retcon flag on one entry",
    response_model=EntryWriteOut,
    responses=error_responses(404, 409, 422),
)
def clear_entry_review(request: Request, entry_id: str, body: ReviewClearIn) -> EntryWriteOut:
    """The writer says they have looked. **Never a retcon** - not by default, not by override.

    This is the clause that decides whether the queue is usable: without it, clearing a flag on a
    densely linked character re-flags every neighbour and the queue never empties.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    return EntryWriteOut.of(EntryStore(handle).clear_review(entry_id, body.revision))


# -- revisions (P3-9, D27) --------------------------------------------------------------------


@router.get(
    "/entries/{entry_id}/revisions",
    tags=["bible"],
    summary="One entry's history, newest first",
    response_model=RevisionListOut,
    responses=error_responses(404),
)
def list_entry_revisions(request: Request, entry_id: str) -> RevisionListOut:
    """**Metadata only** - never the stored states, the discipline a snapshot list follows.

    Complete from creation: revision 1 is the entry being made. Deliberately not filtered by
    ``deleted_at`` - the history of a deleted entry is what somebody deciding whether to restore
    it wants to see.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    revisions = EntryStore(handle).revisions(entry_id)
    return RevisionListOut(revisions=[RevisionMetaOut.of(meta) for meta in revisions])


@router.get(
    "/entries/{entry_id}/revisions/{number}",
    tags=["bible"],
    summary="One revision's recorded state",
    response_model=RevisionOut,
    responses=error_responses(404),
)
def get_entry_revision(request: Request, entry_id: str, number: int) -> RevisionOut:
    """What a preview reads. The state is the whole point, so this route carries it."""
    handle = get_locator(request).resolve_entry(entry_id)
    return RevisionOut.of(EntryStore(handle).revision(entry_id, number))


@router.post(
    "/entries/{entry_id}/revisions/{number}/restore",
    tags=["bible"],
    summary="Write a revision's state back through the ordinary update path",
    response_model=EntryWriteOut,
    responses=error_responses(404, 409, 422),
)
def restore_entry_revision(
    request: Request, entry_id: str, number: int, body: RevisionRestoreIn
) -> EntryWriteOut:
    """A restore is an ordinary edit (P3-4).

    It bumps ``revision``, appends a new revision at the top of the history rather than rewriting
    it, is guarded by D19, and computes its own retcon answer. One write path, no exceptions -
    ``SnapshotStore.restore``'s rule, one table over.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    result = EntryStore(handle).restore_revision(entry_id, number, body.revision)
    return EntryWriteOut.of(result)


# -- links (P3-10) ----------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/links",
    tags=["bible"],
    summary="Every live link in the project",
    response_model=LinkListOut,
    responses=error_responses(404, 422),
)
def list_links(request: Request, project_id: str, relation: str | None = None) -> LinkListOut:
    """Live means the link is not deleted **and neither endpoint is** (ruling 9).

    An unknown ``relation`` is a ``422`` rather than an empty list: a filter that answers nothing
    for a value it does not understand is one a client debugs as missing data.
    """
    handle = open_project(request, project_id)
    links = LinkStore(handle).list(relation=relation)
    return LinkListOut(links=[LinkOut.of(link) for link in links])


@router.post(
    "/projects/{project_id}/links",
    tags=["bible"],
    summary="Join two entries",
    status_code=status.HTTP_201_CREATED,
    response_model=LinkOut,
    responses=error_responses(404, 409, 422),
)
def create_link(request: Request, project_id: str, body: LinkCreateIn) -> LinkOut:
    """One row, always, whichever way the relation reads (ruling 7).

    A relation is refused **on the side it is offered from**: ``member_of`` runs character to
    faction, and faction to character is a different statement, never silently reversed. The one
    exception is a relation the *definition* marks symmetric, and that answer comes from the
    vocabulary rather than from a list any consumer keeps.
    """
    handle = open_project(request, project_id)
    link = LinkStore(handle).create(
        body.from_entry,
        body.relation,
        body.to_entry,
        since=body.since,
        until=body.until,
        attributes=body.attributes,
    )
    return LinkOut.of(link)


@router.get(
    "/entries/{entry_id}/links",
    tags=["bible"],
    summary="One entry's links, both directions in one answer",
    response_model=EntryLinksOut,
    responses=error_responses(404),
)
def list_entry_links(request: Request, entry_id: str) -> EntryLinksOut:
    """Each marked with which end this entry is on, and labelled the way that end reads it.

    A deleted entry - or one that never existed in this project - has no links to show, and that
    is an empty list rather than an error: the predicate is what hides them, and a read path that
    raised instead would be a second way to answer the same question.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    views = LinkStore(handle).for_entry(entry_id)
    return EntryLinksOut(links=[LinkViewOut.of(view) for view in views])


@router.patch(
    "/links/{link_id}",
    tags=["bible"],
    summary="Change a link's bounds or attributes",
    response_model=LinkOut,
    responses=error_responses(404, 422),
)
def patch_link(request: Request, link_id: str, body: LinkPatchIn) -> LinkOut:
    """**Never the endpoints or the relation.** That is a delete and a create, and both are
    recoverable; editing them in place would let a link's own history describe a relationship it
    never had.
    """
    handle = get_locator(request).resolve_link(link_id)
    return LinkOut.of(LinkStore(handle).update(link_id, **body.changes()))


@router.delete(
    "/links/{link_id}",
    tags=["bible"],
    summary="Soft-delete a link",
    response_model=LinkOut,
    responses=error_responses(404),
)
def delete_link(request: Request, link_id: str) -> LinkOut:
    """Nothing cascades, and neither endpoint is touched (D25)."""
    handle = get_locator(request).resolve_link(link_id)
    return LinkOut.of(LinkStore(handle).delete(link_id))


@router.post(
    "/links/{link_id}/restore",
    tags=["bible"],
    summary="Bring a soft-deleted link back",
    response_model=LinkOut,
    responses=error_responses(404, 409),
)
def restore_link(request: Request, link_id: str) -> LinkOut:
    """Refused with a ``409`` when a live link now says the same thing.

    Which happens when the writer deleted this one, typed it again, and then undid the delete.
    Two identical live rows would double-count in Phase 8's chart, and neither would be the wrong
    one to remove.
    """
    handle = get_locator(request).resolve_link(link_id)
    return LinkOut.of(LinkStore(handle).restore(link_id))


# -- citations (P3-10, P3-7) ------------------------------------------------------------------


@router.post(
    "/entries/{entry_id}/citations",
    tags=["bible"],
    summary="Cite an existing anchor, with a role",
    status_code=status.HTTP_201_CREATED,
    response_model=CitationOut,
    responses=error_responses(404, 422),
)
def cite_anchor(request: Request, entry_id: str, body: CitationCreateIn) -> CitationOut:
    """Point a live entry at an anchor that already exists.

    Citing what is already cited in that role is a no-op rather than an error: the row says the
    same thing either way, and a writer who clicked twice has not made a mistake worth a message.
    A ``stale`` or ``orphaned`` anchor may be cited - that is exactly the anchor an entry wants,
    so it can say the passage behind it has moved.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    citation = CitationStore(handle).cite(entry_id, body.anchor_id, body.role)
    return CitationOut.of(citation)


@router.delete(
    "/entries/{entry_id}/citations/{anchor_id}",
    tags=["bible"],
    summary="Remove a citation, in one role or in all of them",
    response_model=CitationRemovedOut,
    responses=error_responses(404, 422),
)
def uncite_anchor(
    request: Request,
    entry_id: str,
    anchor_id: str,
    role: CitationRoleIn | None = None,
) -> CitationRemovedOut:
    """The **anchor stays**. It is a fact about the manuscript, and *Marks* is where one is
    removed; the entry keeps what a person typed and loses one reason to believe it.

    Without a role, every role this entry cites that anchor in. Removing a citation that is not
    there returns zero rather than a ``404``.
    """
    handle = get_locator(request).resolve_entry(entry_id)
    removed = CitationStore(handle).uncite(entry_id, anchor_id, role=role)
    return CitationRemovedOut(removed=removed)


@router.get(
    "/anchors/{anchor_id}/entries",
    tags=["bible"],
    summary="Which entries cite this anchor",
    response_model=AnchorEntriesOut,
    responses=error_responses(404),
)
def list_anchor_entries(request: Request, anchor_id: str) -> AnchorEntriesOut:
    """The reverse view, so *Marks* can say an anchor is spoken for before it is deleted."""
    handle = get_locator(request).resolve_anchor(anchor_id)
    citing = CitationStore(handle).entries_for_anchor(anchor_id)
    return AnchorEntriesOut(entries=[CitingEntryOut.of(entry) for entry in citing])


@router.post(
    "/documents/{document_id}/entries",
    tags=["bible"],
    summary="Create an entry from a selection, with the anchor and the citation",
    status_code=status.HTTP_201_CREATED,
    response_model=EntryFromRangeOut,
    responses=error_responses(404, 409, 422),
)
def create_entry_from_range(
    request: Request, document_id: str, body: EntryFromRangeIn
) -> EntryFromRangeOut:
    """*Add to bible* - the interaction the whole product is arranged around, in its manual form.

    One transaction over three tables (``B1``): the anchor carries the D19 guard, so a **stale
    document version leaves no anchor, no entry, and no citation**. The client sends a range and a
    version and never a quote; the server derives the words, exactly as marking a passage does
    (ruling 8).
    """
    handle = get_locator(request).resolve(document_id)
    created = CitationStore(handle).create_from_range(
        document_id,
        from_pos=body.from_pos,
        to_pos=body.to_pos,
        version=body.version,
        kind=body.kind,
        name=body.name,
        summary=body.summary,
        body_md=body.body_md,
        attributes=body.attributes,
        label=body.label,
        role=body.role,
    )
    return EntryFromRangeOut.of(created)


# -- story-time (P3-10, D28) ------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/storytime",
    tags=["bible"],
    summary="The project's events, ordered, with what could not be placed and what disagrees",
    response_model=StoryTimeOut,
    responses=error_responses(404),
)
def get_storytime(request: Request, project_id: str) -> StoryTimeOut:
    """The pure module's answer over this project's events, and nothing added to it.

    Every event appears in exactly one of ``order`` and ``unplaced``. A contradiction never costs
    the rest of the graph: a cycle is reported *and* everything outside it is still ordered.

    Phase 3 renders no timeline - Phase 8 owns that. This route exists because a stored shape with
    no consumer is a shape nobody has proved sufficient.
    """
    handle: ProjectHandle = open_project(request, project_id)
    return StoryTimeOut.of(project_timeline(handle))
