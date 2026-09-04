"""P1-3 - prefixed short-token IDs (outline section 7)."""

from __future__ import annotations

import pytest

from archetype.ids import (
    ALPHABET,
    ID_LENGTH,
    IdPrefix,
    is_id,
    new_id,
    parse_prefix,
    random_token,
)

BATCH = 20_000


def test_ids_carry_their_prefix() -> None:
    assert new_id(IdPrefix.PROJECT).startswith("prj_")
    assert new_id(IdPrefix.DOCUMENT).startswith("doc_")
    assert new_id(IdPrefix.ANCHOR).startswith("anc_")
    assert new_id(IdPrefix.ENTRY).startswith("ent_")
    assert new_id(IdPrefix.RUN).startswith("run_")


def test_the_body_uses_only_the_declared_alphabet() -> None:
    for _ in range(200):
        body = new_id(IdPrefix.DOCUMENT).split("_", 1)[1]
        assert len(body) == ID_LENGTH
        assert set(body) <= set(ALPHABET)


def test_the_alphabet_excludes_ambiguous_glyphs() -> None:
    assert len(ALPHABET) == 32
    assert len(set(ALPHABET)) == 32
    for glyph in "ilou":
        assert glyph not in ALPHABET


def test_ids_are_unique_across_a_large_batch() -> None:
    ids = {new_id(IdPrefix.DOCUMENT) for _ in range(BATCH)}
    assert len(ids) == BATCH


def test_a_shorter_body_can_be_requested_for_filename_suffixes() -> None:
    value = new_id(IdPrefix.PROJECT, length=8)
    assert len(value.split("_", 1)[1]) == 8


@pytest.mark.parametrize("prefix", ["", "P", "prj_", "project_id", "pr1", "toolongprefix"])
def test_a_malformed_prefix_is_rejected(prefix: str) -> None:
    with pytest.raises(ValueError):
        new_id(prefix)


def test_a_body_shorter_than_eight_characters_is_rejected() -> None:
    with pytest.raises(ValueError):
        new_id(IdPrefix.PROJECT, length=7)


def test_parse_prefix_round_trips() -> None:
    assert parse_prefix(new_id(IdPrefix.ENTRY)) == "ent"


@pytest.mark.parametrize(
    "value",
    ["", "prj", "prj_", "prj_short", "prj_ILLEGALCHARS", "_abcdefghijkl", "prj_abcdefghijkl!"],
)
def test_parse_prefix_rejects_malformed_values(value: str) -> None:
    assert parse_prefix(value) is None
    assert not is_id(value)


def test_is_id_checks_the_expected_prefix() -> None:
    project_id = new_id(IdPrefix.PROJECT)
    assert is_id(project_id)
    assert is_id(project_id, IdPrefix.PROJECT)
    assert not is_id(project_id, IdPrefix.DOCUMENT)


def test_random_token_has_no_length_floor() -> None:
    # A token is a disambiguator, not an identity - the project filename suffix uses six.
    token = random_token(6)
    assert len(token) == 6
    assert set(token) <= set(ALPHABET)


def test_random_token_rejects_a_zero_length() -> None:
    with pytest.raises(ValueError):
        random_token(0)


def test_registered_prefixes_are_distinct() -> None:
    declared = {
        IdPrefix.PROJECT,
        IdPrefix.DOCUMENT,
        IdPrefix.ANCHOR,
        IdPrefix.SNAPSHOT,
        IdPrefix.ENTRY,
        IdPrefix.LINK,
        IdPrefix.RUN,
    }
    assert declared == set(IdPrefix.ALL)
    assert len(IdPrefix.ALL) == 7
