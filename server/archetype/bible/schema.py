"""The kind and relation definition - D26's one place (P3-5, pulled forward into Group A).

This module is the **single** written record of which fields each of the seven kinds has and which
kinds each of the twelve relations joins. ``specs/bible.md`` names the *vocabularies* and
deliberately does not list their *members*, because a second copy in prose is a second place for
the same list to disagree. ``GET /api/bible/schema`` serves this module's JSON dump; the client
renders one generic form from it. Adding a field to a kind is therefore a change to **one file and
one contract fixture**, and nothing else.

The field-type list is **closed**, in the same way and for the same reason the editor's node list
is (D1): each type is a case that the form renderer, the validator here, Phase 6's tool
declaration, and Phase 7's proposal renderer must *each* handle, so a seventh is four pieces of
work rather than one. A field that does not fit one of the six becomes a ``long_text`` and a
backlog entry ([phase-3-plan](../../specs/phase-3-plan.md) section 6).

Why this is not a shared test fixture
-------------------------------------

``server/tests/fixtures/schema/closed_schema.json`` is a **test artifact**: it holds two
independent implementations of the editor schema to one list. This definition is **runtime data
with a single implementation** that the client *fetches*. Copying it into ``web/src`` to import at
build time would create the very second copy D26 exists to prevent.

Purity
------

:func:`validate` does no I/O. It checks the shape of an ``entry_ref`` - that the value is a
well-formed entry id - but whether that entry exists, is live, and is of a kind the field allows
needs the database, so the caller passes ``kind_of``. The split keeps this module usable from a
test, from Phase 6's agent, and from a route without any of them opening a project file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Protocol

from ..ids import IdPrefix, is_id

__all__ = [
    "BIBLE_SCHEMA",
    "ENTRY_KINDS",
    "KIND_NAMES",
    "MAX_ATTRIBUTES_BYTES",
    "MAX_FIELD_TEXT_CHARS",
    "MAX_LIST_ITEMS",
    "MAX_STORY_TIME_CHARS",
    "PRECEDES",
    "RELATIONS",
    "RELATION_NAMES",
    "EntryKind",
    "FieldDefinition",
    "FieldType",
    "InvalidAttributesError",
    "KindDefinition",
    "KindLookup",
    "RelationDefinition",
    "definition_for",
    "relation_for",
    "schema_json",
    "validate",
]

# -- constants (specs/bible.md section 5) -------------------------------------------------------

#: One ``text`` field, and one item of a ``list_of_text``.
MAX_FIELD_TEXT_CHARS: Final[int] = 200

#: Items in one ``list_of_text``. Aliases and epithets; past this it is prose and wants
#: ``long_text``.
MAX_LIST_ITEMS: Final[int] = 64

#: A story-time ``label`` or ``era``, and a link's ``since`` or ``until``. All four are free text
#: a person reads, and none of them ever sorts.
MAX_STORY_TIME_CHARS: Final[int] = 120

#: The serialized ``attributes_json``, checked after validation. A bound on the blob as a whole,
#: in addition to the per-field bounds, because the field list can grow.
MAX_ATTRIBUTES_BYTES: Final[int] = 32 * 1024


class EntryKind:
    """The seven kinds. ``kind`` is chosen at creation and immutable (specs/bible.md section 1)."""

    CHARACTER: Final[str] = "character"
    PLACE: Final[str] = "place"
    ITEM: Final[str] = "item"
    FACTION: Final[str] = "faction"
    EVENT: Final[str] = "event"
    THREAD: Final[str] = "thread"
    FACT: Final[str] = "fact"


class FieldType:
    """The six field types. Closed, and enforced by a test on both sides of the wire."""

    TEXT: Final[str] = "text"
    LONG_TEXT: Final[str] = "long_text"
    LIST_OF_TEXT: Final[str] = "list_of_text"
    ENUM: Final[str] = "enum"
    ENTRY_REF: Final[str] = "entry_ref"
    STORY_TIME: Final[str] = "story_time"

    #: Exactly six. A seventh fails a test here and in the client's renderer.
    ALL: Final[frozenset[str]] = frozenset(
        {"text", "long_text", "list_of_text", "enum", "entry_ref", "story_time"}
    )


class InvalidAttributesError(ValueError):
    """An attribute map does not match its kind's definition. Nothing was written.

    Carries ``field`` so the client can say which input is wrong rather than rejecting the form
    as a whole - the acceptance run's step 3 asks for a message naming the field.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class KindLookup(Protocol):
    """Resolves an entry id to its kind, or ``None`` when it is unknown or not live."""

    def __call__(self, entry_id: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    """One field of one kind."""

    name: str
    type: str
    label: str
    required: bool = False
    help: str = ""
    #: ``enum`` only: the declared set. Empty for every other type.
    members: tuple[str, ...] = ()
    #: ``entry_ref`` only: the kinds this field may point at. Empty for every other type.
    kinds: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Every key, every time - including the two that only one field type uses (P3-11).

        A ``text`` field carries ``members: []`` and ``kinds: []`` it will never fill. That is
        deliberate: the client renders one generic form over this, and a shape whose keys depend
        on the value of another key is one every consumer has to branch on - including the
        contract test, which compares key sets exactly.
        """
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label,
            "required": self.required,
            "help": self.help,
            "members": list(self.members),
            "kinds": list(self.kinds),
        }


@dataclass(frozen=True, slots=True)
class KindDefinition:
    """One kind's fields, in the order a form renders them."""

    kind: str
    label: str
    plural: str
    fields: tuple[FieldDefinition, ...]

    def field(self, name: str) -> FieldDefinition | None:
        return next((field for field in self.fields if field.name == name), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "plural": self.plural,
            "fields": [field.as_dict() for field in self.fields],
        }


@dataclass(frozen=True, slots=True)
class RelationDefinition:
    """One relation, and the kinds it may join in each direction.

    ``symmetric`` is declared rather than inferred, so Phase 8's adjacency matrix asks the
    vocabulary which relations to mirror instead of carrying its own list of them
    (phase-3-plan section 2, ruling 7).
    """

    relation: str
    label: str
    #: How the relation reads from the other end - "member of" / "has member". A symmetric
    #: relation reads the same both ways, and says so by repeating its label.
    inverse_label: str
    from_kinds: tuple[str, ...]
    to_kinds: tuple[str, ...]
    symmetric: bool = False

    def joins(self, from_kind: str, to_kind: str) -> bool:
        """True when this relation may run from ``from_kind`` to ``to_kind``."""
        if from_kind in self.from_kinds and to_kind in self.to_kinds:
            return True
        # A symmetric relation is stored once and read from both ends, so the pair is legal in
        # either order; an asymmetric one is not, and reversing it is a different statement.
        return self.symmetric and from_kind in self.to_kinds and to_kind in self.from_kinds

    def as_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation,
            "label": self.label,
            "inverse_label": self.inverse_label,
            "from_kinds": list(self.from_kinds),
            "to_kinds": list(self.to_kinds),
            "symmetric": self.symmetric,
        }


# -- the definition ---------------------------------------------------------------------------
#
# This is the part that changes when a kind gains a field. Nothing else does.

_CHARACTER_KINDS: Final[tuple[str, ...]] = (EntryKind.CHARACTER,)
_PLACE_KINDS: Final[tuple[str, ...]] = (EntryKind.PLACE,)
_EVENT_KINDS: Final[tuple[str, ...]] = (EntryKind.EVENT,)
_ACTOR_KINDS: Final[tuple[str, ...]] = (EntryKind.CHARACTER, EntryKind.FACTION)
_EVERY_KIND: Final[tuple[str, ...]] = (
    EntryKind.CHARACTER,
    EntryKind.PLACE,
    EntryKind.ITEM,
    EntryKind.FACTION,
    EntryKind.EVENT,
    EntryKind.THREAD,
    EntryKind.FACT,
)

_ALIASES = FieldDefinition(
    name="aliases",
    type=FieldType.LIST_OF_TEXT,
    label="Also known as",
    help="Other names this is called. The bible is not a namespace and does not key off any of "
    "them.",
)

ENTRY_KINDS: Final[tuple[KindDefinition, ...]] = (
    KindDefinition(
        kind=EntryKind.CHARACTER,
        label="Character",
        plural="Characters",
        fields=(
            _ALIASES,
            FieldDefinition(
                name="role",
                type=FieldType.ENUM,
                label="Role",
                members=("protagonist", "antagonist", "supporting", "minor", "chorus"),
            ),
            FieldDefinition(name="pronouns", type=FieldType.TEXT, label="Pronouns"),
            FieldDefinition(
                name="age",
                type=FieldType.TEXT,
                label="Age",
                help="Free text. 'about forty' is an answer; so is 'seventeen at the fire'.",
            ),
            FieldDefinition(name="appearance", type=FieldType.LONG_TEXT, label="Appearance"),
            FieldDefinition(
                name="voice",
                type=FieldType.LONG_TEXT,
                label="Voice",
                help="How they speak, and what they never say.",
            ),
            FieldDefinition(name="wants", type=FieldType.LONG_TEXT, label="What they want"),
            FieldDefinition(
                name="home",
                type=FieldType.ENTRY_REF,
                label="Home",
                kinds=_PLACE_KINDS,
                help="Where they are from. Being somewhere at a particular time is a link, not "
                "this field.",
            ),
        ),
    ),
    KindDefinition(
        kind=EntryKind.PLACE,
        label="Place",
        plural="Places",
        fields=(
            _ALIASES,
            FieldDefinition(
                name="place_type",
                type=FieldType.ENUM,
                label="Type",
                members=(
                    "region",
                    "settlement",
                    "building",
                    "room",
                    "wilderness",
                    "vessel",
                    "otherworld",
                ),
            ),
            FieldDefinition(
                name="region", type=FieldType.ENTRY_REF, label="Within", kinds=_PLACE_KINDS
            ),
            FieldDefinition(name="description", type=FieldType.LONG_TEXT, label="Description"),
            FieldDefinition(
                name="atmosphere",
                type=FieldType.LONG_TEXT,
                label="Atmosphere",
                help="What it feels like to be there.",
            ),
        ),
    ),
    KindDefinition(
        kind=EntryKind.ITEM,
        label="Item",
        plural="Items",
        fields=(
            _ALIASES,
            FieldDefinition(
                name="item_type",
                type=FieldType.ENUM,
                label="Type",
                members=("weapon", "document", "heirloom", "tool", "artifact", "garment", "other"),
            ),
            FieldDefinition(name="description", type=FieldType.LONG_TEXT, label="Description"),
            FieldDefinition(name="significance", type=FieldType.LONG_TEXT, label="Why it matters"),
        ),
    ),
    KindDefinition(
        kind=EntryKind.FACTION,
        label="Faction",
        plural="Factions",
        fields=(
            _ALIASES,
            FieldDefinition(
                name="faction_type",
                type=FieldType.ENUM,
                label="Type",
                members=("family", "guild", "order", "government", "crew", "cult", "other"),
            ),
            FieldDefinition(
                name="seat", type=FieldType.ENTRY_REF, label="Seat", kinds=_PLACE_KINDS
            ),
            FieldDefinition(name="purpose", type=FieldType.LONG_TEXT, label="What it wants"),
            FieldDefinition(name="description", type=FieldType.LONG_TEXT, label="Description"),
        ),
    ),
    KindDefinition(
        kind=EntryKind.EVENT,
        label="Event",
        plural="Events",
        fields=(
            FieldDefinition(
                name="story_time",
                type=FieldType.STORY_TIME,
                label="When",
                help="A label to read, an optional sort key to order by, an optional era. No "
                "calendar is ever parsed.",
            ),
            FieldDefinition(
                name="event_type",
                type=FieldType.ENUM,
                label="Type",
                members=("scene", "offstage", "backstory", "turning_point", "other"),
            ),
            FieldDefinition(
                name="certainty",
                type=FieldType.ENUM,
                label="Certainty",
                members=("established", "implied", "disputed"),
            ),
            FieldDefinition(name="consequences", type=FieldType.LONG_TEXT, label="Consequences"),
        ),
    ),
    KindDefinition(
        kind=EntryKind.THREAD,
        label="Thread",
        plural="Threads",
        fields=(
            FieldDefinition(
                name="thread_type",
                type=FieldType.ENUM,
                label="Type",
                members=("main", "subplot", "mystery", "romance", "arc"),
            ),
            FieldDefinition(
                name="state",
                type=FieldType.ENUM,
                label="State",
                help="Where the thread has got to. Unrelated to the entry's own status, which is "
                "the proposal lifecycle.",
                members=("setup", "developing", "complicating", "resolved", "abandoned"),
            ),
            FieldDefinition(
                name="question", type=FieldType.LONG_TEXT, label="The question it poses"
            ),
            FieldDefinition(name="resolution", type=FieldType.LONG_TEXT, label="How it resolves"),
        ),
    ),
    KindDefinition(
        kind=EntryKind.FACT,
        label="Fact",
        plural="Facts",
        fields=(
            FieldDefinition(
                name="statement",
                type=FieldType.LONG_TEXT,
                label="What is true",
                required=True,
            ),
            FieldDefinition(
                name="fact_type",
                type=FieldType.ENUM,
                label="Type",
                members=("rule", "history", "custom", "cosmology", "language", "other"),
            ),
            FieldDefinition(
                name="certainty",
                type=FieldType.ENUM,
                label="Certainty",
                members=("established", "implied", "disputed"),
            ),
            FieldDefinition(
                name="scope",
                type=FieldType.TEXT,
                label="Where it holds",
                help="'the northern provinces', 'after the flood'. Free text.",
            ),
        ),
    ),
)

RELATIONS: Final[tuple[RelationDefinition, ...]] = (
    RelationDefinition(
        relation="knows",
        label="knows",
        inverse_label="knows",
        from_kinds=_CHARACTER_KINDS,
        to_kinds=_CHARACTER_KINDS,
        symmetric=True,
    ),
    RelationDefinition(
        relation="related_to",
        label="is related to",
        inverse_label="is related to",
        from_kinds=_CHARACTER_KINDS,
        to_kinds=_CHARACTER_KINDS,
        symmetric=True,
    ),
    RelationDefinition(
        relation="member_of",
        label="is a member of",
        inverse_label="has as a member",
        from_kinds=_CHARACTER_KINDS,
        to_kinds=(EntryKind.FACTION,),
    ),
    RelationDefinition(
        relation="allied_with",
        label="is allied with",
        inverse_label="is allied with",
        from_kinds=(EntryKind.FACTION,),
        to_kinds=(EntryKind.FACTION,),
        symmetric=True,
    ),
    RelationDefinition(
        relation="opposes",
        label="opposes",
        inverse_label="is opposed by",
        from_kinds=_ACTOR_KINDS,
        to_kinds=_ACTOR_KINDS,
    ),
    RelationDefinition(
        relation="owns",
        label="owns",
        inverse_label="is owned by",
        from_kinds=_ACTOR_KINDS,
        to_kinds=(EntryKind.ITEM,),
    ),
    RelationDefinition(
        relation="located_in",
        label="is in",
        inverse_label="contains",
        from_kinds=(EntryKind.CHARACTER, EntryKind.FACTION, EntryKind.PLACE, EntryKind.ITEM),
        to_kinds=_PLACE_KINDS,
    ),
    RelationDefinition(
        relation="participates_in",
        label="takes part in",
        inverse_label="involves",
        from_kinds=_ACTOR_KINDS,
        to_kinds=_EVENT_KINDS,
    ),
    RelationDefinition(
        relation="occurs_at",
        label="happens at",
        inverse_label="is where",
        from_kinds=_EVENT_KINDS,
        to_kinds=_PLACE_KINDS,
    ),
    RelationDefinition(
        relation="precedes",
        label="comes before",
        inverse_label="comes after",
        from_kinds=_EVENT_KINDS,
        to_kinds=_EVENT_KINDS,
    ),
    RelationDefinition(
        relation="advances",
        label="advances",
        inverse_label="is advanced by",
        from_kinds=_EVENT_KINDS,
        to_kinds=(EntryKind.THREAD,),
    ),
    RelationDefinition(
        relation="concerns",
        label="concerns",
        inverse_label="is the subject of",
        from_kinds=(EntryKind.FACT,),
        to_kinds=_EVERY_KIND,
    ),
)

#: The relation D28's ordering module reads. Every other relation is inert to it.
PRECEDES: Final[str] = "precedes"

_KINDS_BY_NAME: Final[dict[str, KindDefinition]] = {
    definition.kind: definition for definition in ENTRY_KINDS
}
_RELATIONS_BY_NAME: Final[dict[str, RelationDefinition]] = {
    definition.relation: definition for definition in RELATIONS
}

#: Every kind name, for validation and for the list route's filter.
KIND_NAMES: Final[frozenset[str]] = frozenset(_KINDS_BY_NAME)

#: Every relation name.
RELATION_NAMES: Final[frozenset[str]] = frozenset(_RELATIONS_BY_NAME)


def _check_definition() -> None:
    """Hold the definition to its own rules at import time, not at first use.

    Every one of these is a mistake somebody makes while adding a kind, and each would otherwise
    surface as a confusing refusal in a form months later.
    """
    if len(FieldType.ALL) != 6:
        raise RuntimeError(
            f"the field-type list is closed at six and holds {len(FieldType.ALL)} (D26). Adding "
            "one is a change to the client's renderer, the validator, Phase 6's tool "
            "declaration, and Phase 7's proposal renderer - not to this list alone."
        )
    for definition in ENTRY_KINDS:
        seen: set[str] = set()
        for field in definition.fields:
            where = f"{definition.kind}.{field.name}"
            if field.type not in FieldType.ALL:
                raise RuntimeError(f"{where} has unknown type {field.type!r}")
            if field.name in seen:
                raise RuntimeError(f"{definition.kind} declares {field.name!r} twice")
            seen.add(field.name)
            if field.type == FieldType.ENUM and not field.members:
                raise RuntimeError(f"{where} is an enum with no members")
            if field.type != FieldType.ENUM and field.members:
                raise RuntimeError(f"{where} declares members but is not an enum")
            if field.type == FieldType.ENTRY_REF and not field.kinds:
                raise RuntimeError(f"{where} is an entry_ref to no kinds")
            if field.type != FieldType.ENTRY_REF and field.kinds:
                raise RuntimeError(f"{where} declares kinds but is not an entry_ref")
            for kind in field.kinds:
                if kind not in _KINDS_BY_NAME:
                    raise RuntimeError(f"{where} points at unknown kind {kind!r}")
    for relation in RELATIONS:
        for kind in relation.from_kinds + relation.to_kinds:
            if kind not in _KINDS_BY_NAME:
                raise RuntimeError(f"relation {relation.relation!r} names unknown kind {kind!r}")
        if relation.symmetric and set(relation.from_kinds) != set(relation.to_kinds):
            raise RuntimeError(
                f"relation {relation.relation!r} is symmetric but joins different kinds in each "
                "direction, which cannot be read from both ends"
            )


_check_definition()


def definition_for(kind: str) -> KindDefinition:
    """The definition for ``kind``.

    Raises:
        InvalidAttributesError: If ``kind`` is not one of the seven.
    """
    definition = _KINDS_BY_NAME.get(kind)
    if definition is None:
        raise InvalidAttributesError(
            f"unknown entry kind {kind!r}; expected one of {sorted(KIND_NAMES)}", field="kind"
        )
    return definition


def relation_for(relation: str) -> RelationDefinition:
    """The definition for ``relation``.

    Raises:
        InvalidAttributesError: If ``relation`` is not in the closed vocabulary.
    """
    definition = _RELATIONS_BY_NAME.get(relation)
    if definition is None:
        raise InvalidAttributesError(
            f"unknown relation {relation!r}; expected one of {sorted(RELATION_NAMES)}",
            field="relation",
        )
    return definition


# -- validation -------------------------------------------------------------------------------


def _refuse(field: str, message: str) -> None:
    raise InvalidAttributesError(f"{field}: {message}", field=field)


def _text(field: FieldDefinition, value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        _refuse(field.name, f"expected a string, got {type(value).__name__}")
    if len(value) > limit:
        _refuse(field.name, f"is {len(value)} characters, over the {limit}-character limit")
    return value


def _validate_field(field: FieldDefinition, value: Any, kind_of: KindLookup | None) -> Any:
    """One field's value, normalised. Refuses rather than coercing."""
    if field.type == FieldType.TEXT:
        return _text(field, value, limit=MAX_FIELD_TEXT_CHARS)

    if field.type == FieldType.LONG_TEXT:
        # Bounded by MAX_ATTRIBUTES_BYTES over the blob as a whole rather than per field: a
        # per-field limit here would be a second number to keep in step with that one.
        if not isinstance(value, str):
            _refuse(field.name, f"expected a string, got {type(value).__name__}")
        return value

    if field.type == FieldType.LIST_OF_TEXT:
        if not isinstance(value, list):
            _refuse(field.name, f"expected a list of strings, got {type(value).__name__}")
        if len(value) > MAX_LIST_ITEMS:
            _refuse(field.name, f"has {len(value)} items, over the {MAX_LIST_ITEMS}-item limit")
        for index, item in enumerate(value):
            if not isinstance(item, str):
                _refuse(field.name, f"item {index} is a {type(item).__name__}, not a string")
            if len(item) > MAX_FIELD_TEXT_CHARS:
                _refuse(
                    field.name,
                    f"item {index} is {len(item)} characters, over the "
                    f"{MAX_FIELD_TEXT_CHARS}-character limit",
                )
        return list(value)

    if field.type == FieldType.ENUM:
        if not isinstance(value, str):
            _refuse(field.name, f"expected one of {list(field.members)}, got a non-string")
        if value not in field.members:
            _refuse(field.name, f"{value!r} is not one of {list(field.members)}")
        return value

    if field.type == FieldType.ENTRY_REF:
        if not isinstance(value, str) or not is_id(value, IdPrefix.ENTRY):
            _refuse(field.name, f"expected an entry id, got {value!r}")
        if kind_of is not None:
            target_kind = kind_of(value)
            if target_kind is None:
                _refuse(field.name, f"no live entry {value!r} in this project")
            if target_kind not in field.kinds:
                _refuse(
                    field.name,
                    f"points at a {target_kind}, but this field allows {list(field.kinds)}",
                )
        return value

    if field.type == FieldType.STORY_TIME:
        return _validate_story_time(field, value)

    # Unreachable while _check_definition holds, and a loud failure rather than a silent pass if
    # it ever does not.
    raise RuntimeError(f"no validator for field type {field.type!r}")


def _validate_story_time(field: FieldDefinition, value: Any) -> dict[str, Any]:
    """D28's three parts, all optional, and nothing else.

    ``sort_key`` is a number rather than an integer precisely so an event can be inserted between
    two others without renumbering. ``bool`` is excluded because ``True`` is an ``int`` in Python
    and a sort key of ``True`` is a typo, not an ordering.
    """
    if not isinstance(value, dict):
        _refuse(field.name, f"expected an object with label, sort_key, and era, got {value!r}")
    unknown = set(value) - {"label", "sort_key", "era"}
    if unknown:
        _refuse(field.name, f"has unknown keys {sorted(unknown)}; expected label, sort_key, era")

    result: dict[str, Any] = {}
    for key in ("label", "era"):
        raw = value.get(key)
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str):
            _refuse(field.name, f"{key} must be a string, got {type(raw).__name__}")
        if len(raw) > MAX_STORY_TIME_CHARS:
            _refuse(
                field.name,
                f"{key} is {len(raw)} characters, over the {MAX_STORY_TIME_CHARS}-character limit",
            )
        result[key] = raw

    sort_key = value.get("sort_key")
    if sort_key is not None:
        if isinstance(sort_key, bool) or not isinstance(sort_key, int | float):
            _refuse(field.name, f"sort_key must be a number, got {sort_key!r}")
        result["sort_key"] = float(sort_key)
    return result


def validate(kind: str, attributes: Any, *, kind_of: KindLookup | None = None) -> dict[str, Any]:
    """The attribute map for ``kind``, validated and normalised.

    Total, and **refusing rather than coercing**: an attribute the definition does not declare is
    an error, not a silent drop. ``attributes_json`` is a blob in storage but it is not a
    free-form bag, and the moment it becomes one, the served definition stops describing what is
    actually in the file.

    Args:
        kind: One of the seven.
        attributes: The map to validate. ``None`` is read as empty.
        kind_of: Resolves an entry id to its kind, for ``entry_ref`` fields. Without it the shape
            of a reference is checked but its target is not - which is the right answer for a
            pure caller and the wrong one for a store.

    Returns:
        A new map holding only declared fields, with empty values omitted.

    Raises:
        InvalidAttributesError: For an unknown kind, an unknown field, a value of the wrong type,
            an ``enum`` value outside its declared set, an ``entry_ref`` to a kind the field does
            not allow, a missing required field, or an oversized blob.
    """
    definition = definition_for(kind)
    if attributes is None:
        attributes = {}
    if not isinstance(attributes, dict):
        raise InvalidAttributesError(
            f"attributes must be an object, got {type(attributes).__name__}", field="attributes"
        )

    declared = {field.name for field in definition.fields}
    unknown = sorted(set(attributes) - declared)
    if unknown:
        raise InvalidAttributesError(
            f"{definition.kind} does not declare {unknown[0]!r}; its fields are {sorted(declared)}",
            field=unknown[0],
        )

    result: dict[str, Any] = {}
    for field in definition.fields:
        if field.name not in attributes:
            if field.required:
                _refuse(field.name, "is required")
            continue
        value = attributes[field.name]
        if value is None or value == "" or value == [] or value == {}:
            # An emptied field is an absent field. Storing "" and absent as different states
            # would give every form two ways to say nothing, and the client no way to choose.
            if field.required:
                _refuse(field.name, "is required")
            continue
        result[field.name] = _validate_field(field, value, kind_of)

    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    size = len(encoded.encode("utf-8"))
    if size > MAX_ATTRIBUTES_BYTES:
        raise InvalidAttributesError(
            f"attributes are {size} bytes, over the {MAX_ATTRIBUTES_BYTES}-byte limit",
            field="attributes",
        )
    return result


# -- the served definition (P3-11) --------------------------------------------------------------


def schema_json() -> dict[str, Any]:
    """D26's definition as plain JSON - what ``GET /api/bible/schema`` serves.

    Project-independent by construction: the vocabulary is the product's, not a manuscript's.
    """
    return {
        "field_types": sorted(FieldType.ALL),
        "kinds": [definition.as_dict() for definition in ENTRY_KINDS],
        "relations": [relation.as_dict() for relation in RELATIONS],
    }


#: The definition as a value, for callers that want it without a function call.
BIBLE_SCHEMA: Final[dict[str, Any]] = schema_json()
