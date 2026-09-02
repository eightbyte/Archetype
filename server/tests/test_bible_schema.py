"""The kind and relation definition, and the closed field-type list (D26).

``archetype/bible/schema.py`` is P3-5's module, landed early because P3-3 cannot refuse an
undeclared attribute without it (phase-3-plan section 7, ``A1``). These are the tests that go with
it as it stands: the closed list, the definition's internal consistency, and validation's
refusals. P3-5 completes the item with the JSON dump as a contract fixture and the client-side
half of the closed-list enforcement.

The closed-list tests matter more than they look. Each field type is a case that the form
renderer, the validator, Phase 6's tool declaration, and Phase 7's proposal renderer must *each*
handle - so a seventh added quietly is three silent omissions, and the failure mode is a form that
renders a field as nothing at all.
"""

from __future__ import annotations

import pytest

from archetype.bible.schema import (
    BIBLE_SCHEMA,
    ENTRY_KINDS,
    MAX_ATTRIBUTES_BYTES,
    MAX_FIELD_TEXT_CHARS,
    MAX_LIST_ITEMS,
    MAX_STORY_TIME_CHARS,
    RELATIONS,
    EntryKind,
    FieldType,
    InvalidAttributesError,
    definition_for,
    relation_for,
    schema_json,
    validate,
)

# -- the closed lists ----------------------------------------------------------------------------

#: Restated here rather than derived from the module, so that adding a type fails *this* test
#: rather than being silently accepted by a check that reads the same list it is checking.
EXPECTED_FIELD_TYPES = {"text", "long_text", "list_of_text", "enum", "entry_ref", "story_time"}

EXPECTED_KINDS = ["character", "place", "item", "faction", "event", "thread", "fact"]

EXPECTED_RELATIONS = [
    "knows",
    "related_to",
    "member_of",
    "allied_with",
    "opposes",
    "owns",
    "located_in",
    "participates_in",
    "occurs_at",
    "precedes",
    "advances",
    "concerns",
]


def test_there_are_exactly_six_field_types() -> None:
    assert set(FieldType.ALL) == EXPECTED_FIELD_TYPES
    assert len(FieldType.ALL) == 6, (
        "the field-type list is closed (D26). A seventh is a change to the client's renderer, "
        "the validator, Phase 6's tool declaration, and Phase 7's proposal renderer - not to "
        "this list alone. Amend specs/bible.md section 2 and this test together."
    )


def test_there_are_seven_kinds_and_twelve_relations() -> None:
    assert [definition.kind for definition in ENTRY_KINDS] == EXPECTED_KINDS
    assert [definition.relation for definition in RELATIONS] == EXPECTED_RELATIONS


def test_every_field_type_is_used_by_some_kind() -> None:
    """The acceptance run's step 2 asks that all six appear across the seven forms.

    A type nothing uses is a renderer case nobody exercises, which is the same thing as an
    untested one.
    """
    used = {field.type for definition in ENTRY_KINDS for field in definition.fields}
    assert used == EXPECTED_FIELD_TYPES


def test_every_field_declares_a_known_type_and_a_label() -> None:
    for definition in ENTRY_KINDS:
        for field in definition.fields:
            assert field.type in FieldType.ALL, f"{definition.kind}.{field.name}"
            assert field.label, f"{definition.kind}.{field.name} has no label to render"


def test_an_enum_declares_members_and_an_entry_ref_declares_kinds() -> None:
    for definition in ENTRY_KINDS:
        for field in definition.fields:
            if field.type == FieldType.ENUM:
                assert field.members, f"{definition.kind}.{field.name}"
                assert len(set(field.members)) == len(field.members), "members are distinct"
            else:
                assert not field.members
            if field.type == FieldType.ENTRY_REF:
                assert field.kinds, f"{definition.kind}.{field.name}"
                assert all(kind in EXPECTED_KINDS for kind in field.kinds)
            else:
                assert not field.kinds


def test_a_symmetric_relation_joins_the_same_kinds_in_both_directions() -> None:
    """Otherwise "read from both ends" has no meaning (ruling 7)."""
    for relation in RELATIONS:
        if relation.symmetric:
            assert set(relation.from_kinds) == set(relation.to_kinds), relation.relation
            assert relation.label == relation.inverse_label, (
                f"{relation.relation} reads the same from both ends, so it says so"
            )


def test_relations_join_only_declared_kinds() -> None:
    for relation in RELATIONS:
        for kind in relation.from_kinds + relation.to_kinds:
            assert kind in EXPECTED_KINDS, relation.relation


def test_precedes_runs_between_two_events() -> None:
    """D28's ordering module reads this relation and no other."""
    precedes = relation_for("precedes")
    assert precedes.from_kinds == (EntryKind.EVENT,)
    assert precedes.to_kinds == (EntryKind.EVENT,)
    assert precedes.symmetric is False


# -- what a relation joins -------------------------------------------------------------------------


def test_a_relation_refuses_a_pair_it_does_not_join() -> None:
    """Acceptance step 5: a ``place`` that ``knows`` an ``item`` cannot be built."""
    knows = relation_for("knows")
    assert knows.joins(EntryKind.CHARACTER, EntryKind.CHARACTER)
    assert not knows.joins(EntryKind.PLACE, EntryKind.ITEM)


def test_an_asymmetric_relation_is_not_legal_reversed() -> None:
    """``member_of`` runs character to faction; the reverse is a different statement."""
    member_of = relation_for("member_of")
    assert member_of.joins(EntryKind.CHARACTER, EntryKind.FACTION)
    assert not member_of.joins(EntryKind.FACTION, EntryKind.CHARACTER)


def test_a_symmetric_relation_is_legal_in_either_order() -> None:
    assert relation_for("knows").joins(EntryKind.CHARACTER, EntryKind.CHARACTER)
    allied = relation_for("allied_with")
    assert allied.joins(EntryKind.FACTION, EntryKind.FACTION)


def test_an_unknown_kind_or_relation_is_refused() -> None:
    with pytest.raises(InvalidAttributesError, match="unknown entry kind"):
        definition_for("dragon")
    with pytest.raises(InvalidAttributesError, match="unknown relation"):
        relation_for("befriends")


# -- validation, without a database ----------------------------------------------------------------


def test_validation_is_pure_and_checks_only_the_shape_of_a_reference() -> None:
    """Without ``kind_of`` the target is not checked - which is right for a pure caller."""
    validated = validate(EntryKind.CHARACTER, {"home": "ent_abcdefgh0000"})
    assert validated == {"home": "ent_abcdefgh0000"}

    with pytest.raises(InvalidAttributesError, match="expected an entry id"):
        validate(EntryKind.CHARACTER, {"home": "not-an-id"})
    with pytest.raises(InvalidAttributesError, match="expected an entry id"):
        validate(EntryKind.CHARACTER, {"home": "doc_abcdefgh0000"})


def test_validation_consults_kind_of_when_it_is_given_one() -> None:
    # Bodies drawn from ids.ALPHABET - no i, l, o, or u - so these are well-formed ids rather
    # than merely plausible strings.
    a_place = "ent_2b3c4d5e6f7g"
    an_item = "ent_8h9j0k1m2n3p"

    def kind_of(entry_id: str) -> str | None:
        return {a_place: EntryKind.PLACE, an_item: EntryKind.ITEM}.get(entry_id)

    assert validate(EntryKind.CHARACTER, {"home": a_place}, kind_of=kind_of)
    with pytest.raises(InvalidAttributesError, match="points at a item"):
        validate(EntryKind.CHARACTER, {"home": an_item}, kind_of=kind_of)
    with pytest.raises(InvalidAttributesError, match="no live entry"):
        validate(EntryKind.CHARACTER, {"home": "ent_zzzzzzzzzzzz"}, kind_of=kind_of)


def test_none_and_an_empty_map_are_the_same_thing() -> None:
    assert validate(EntryKind.CHARACTER, None) == {}
    assert validate(EntryKind.CHARACTER, {}) == {}


def test_a_non_object_attribute_map_is_refused() -> None:
    with pytest.raises(InvalidAttributesError, match="must be an object"):
        validate(EntryKind.CHARACTER, ["role", "protagonist"])


@pytest.mark.parametrize(
    ("attributes", "message"),
    [
        ({"pronouns": "x" * (MAX_FIELD_TEXT_CHARS + 1)}, "over the 200-character limit"),
        ({"aliases": ["x"] * (MAX_LIST_ITEMS + 1)}, "over the 64-item limit"),
        ({"aliases": ["x" * (MAX_FIELD_TEXT_CHARS + 1)]}, "item 0 is"),
        ({"aliases": [1, 2]}, "item 0 is a int"),
    ],
)
def test_the_per_field_bounds_hold(attributes: dict, message: str) -> None:
    with pytest.raises(InvalidAttributesError, match=message):
        validate(EntryKind.CHARACTER, attributes)


def test_the_whole_blob_is_bounded_as_well_as_each_field() -> None:
    """Because the field list can grow, and per-field limits alone do not bound the total."""
    with pytest.raises(InvalidAttributesError, match=f"over the {MAX_ATTRIBUTES_BYTES}-byte"):
        validate(EntryKind.CHARACTER, {"appearance": "x" * (MAX_ATTRIBUTES_BYTES + 1)})


# -- story-time (D28) ------------------------------------------------------------------------------


def test_story_time_takes_three_optional_parts() -> None:
    assert validate(EntryKind.EVENT, {"story_time": {"label": "the third night"}}) == {
        "story_time": {"label": "the third night"}
    }
    assert validate(
        EntryKind.EVENT, {"story_time": {"label": "Midwinter", "sort_key": 12, "era": "The Flood"}}
    ) == {"story_time": {"label": "Midwinter", "era": "The Flood", "sort_key": 12.0}}


def test_a_sort_key_is_a_number_so_an_event_can_be_inserted_between_two_others() -> None:
    validated = validate(EntryKind.EVENT, {"story_time": {"sort_key": 2.5}})
    assert validated["story_time"]["sort_key"] == 2.5


def test_a_boolean_is_not_a_sort_key() -> None:
    """``True`` is an ``int`` in Python, and a sort key of ``True`` is a typo, not an ordering."""
    with pytest.raises(InvalidAttributesError, match="sort_key must be a number"):
        validate(EntryKind.EVENT, {"story_time": {"sort_key": True}})


def test_a_story_time_label_is_never_parsed_only_bounded() -> None:
    """No calendar is ever parsed, and none is ever required (D9)."""
    for label in ("the third night of the flood", "eleven years before", "Midwinter, 1204"):
        assert validate(EntryKind.EVENT, {"story_time": {"label": label}})["story_time"] == {
            "label": label
        }
    with pytest.raises(InvalidAttributesError, match=f"over the {MAX_STORY_TIME_CHARS}-character"):
        validate(EntryKind.EVENT, {"story_time": {"label": "x" * (MAX_STORY_TIME_CHARS + 1)}})


def test_an_unknown_story_time_key_is_refused() -> None:
    with pytest.raises(InvalidAttributesError, match="unknown keys"):
        validate(EntryKind.EVENT, {"story_time": {"date": "1204-12-21"}})


# -- the served definition -------------------------------------------------------------------------


def test_the_dump_carries_everything_the_client_needs_to_render_a_form() -> None:
    dumped = schema_json()
    assert set(dumped) == {"field_types", "kinds", "relations"}
    assert set(dumped["field_types"]) == EXPECTED_FIELD_TYPES

    for kind in dumped["kinds"]:
        assert set(kind) == {"kind", "label", "plural", "fields"}
        for field in kind["fields"]:
            assert {"name", "type", "label", "required"} <= set(field)
            if field["type"] == "enum":
                assert field["members"]
            if field["type"] == "entry_ref":
                assert field["kinds"]

    for relation in dumped["relations"]:
        assert set(relation) == {
            "relation",
            "label",
            "inverse_label",
            "from_kinds",
            "to_kinds",
            "symmetric",
        }


def test_the_dump_is_project_independent_and_stable() -> None:
    """It is the one route in the API that answers the same bytes for every caller (P3-11)."""
    assert schema_json() == schema_json()
    assert BIBLE_SCHEMA == schema_json()


def test_field_order_is_the_order_a_form_renders() -> None:
    character = definition_for(EntryKind.CHARACTER)
    assert [field.name for field in character.fields][0] == "aliases"
    dumped = next(k for k in schema_json()["kinds"] if k["kind"] == "character")
    assert [field["name"] for field in dumped["fields"]] == [
        field.name for field in character.fields
    ]
