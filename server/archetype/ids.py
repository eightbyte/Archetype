"""Prefixed short-token IDs (P1-3, outline section 7).

Every entity carries a greppable, prefixed identifier: ``prj_``, ``doc_``, ``anc_``, ``ent_``,
``run_``. The body is drawn from a Crockford-style base32 alphabet with the ambiguous glyphs
(``i``, ``l``, ``o``, ``u``) removed, so an ID read aloud or copied out of a log survives the
trip.

Twelve body characters over a 32-symbol alphabet is 60 bits of entropy - collision-resistant far
past the scale of a single-user manuscript, and short enough to skim in a log line.
"""

from __future__ import annotations

import re
import secrets
from typing import Final

__all__ = [
    "ALPHABET",
    "ID_LENGTH",
    "IdPrefix",
    "is_id",
    "new_id",
    "parse_prefix",
    "random_token",
]

#: Crockford base32, lowercase, minus the ambiguous glyphs. Exactly 32 symbols.
ALPHABET: Final[str] = "0123456789abcdefghjkmnpqrstvwxyz"

#: Characters in the random body, excluding the prefix and separator.
ID_LENGTH: Final[int] = 12

_PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z]{2,8}$")


class IdPrefix:
    """The registered prefixes. Later phases add to this list; they never reuse one."""

    PROJECT: Final[str] = "prj"
    DOCUMENT: Final[str] = "doc"
    ANCHOR: Final[str] = "anc"
    ENTRY: Final[str] = "ent"
    RUN: Final[str] = "run"

    #: Every prefix known to the current schema, for validation and log greps.
    ALL: Final[frozenset[str]] = frozenset({"prj", "doc", "anc", "ent", "run"})


def random_token(length: int) -> str:
    """A bare random string over :data:`ALPHABET`, with no prefix and no identity claim.

    For disambiguators - the suffix on a project filename, say - where an ID would imply the
    value identifies something. IDs have a minimum length; a token does not.

    Raises:
        ValueError: If ``length`` is under 1.
    """
    if length < 1:
        raise ValueError(f"token length must be at least 1, got {length}")
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def new_id(prefix: str, *, length: int = ID_LENGTH) -> str:
    """Return a fresh ID such as ``prj_4k2h9wq0mzbt``.

    Args:
        prefix: A short lowercase token, e.g. ``IdPrefix.PROJECT``.
        length: Body length in characters. Defaults to :data:`ID_LENGTH`.

    Raises:
        ValueError: If the prefix is not 2-8 lowercase letters, or the length is under 8.
    """
    if not _PREFIX_PATTERN.match(prefix):
        raise ValueError(f"prefix must be 2-8 lowercase letters, got {prefix!r}")
    if length < 8:
        raise ValueError(f"id body must be at least 8 characters, got {length}")
    return f"{prefix}_{random_token(length)}"


def parse_prefix(value: str) -> str | None:
    """The prefix of a well-formed ID, or ``None`` if ``value`` is not one."""
    prefix, separator, body = value.partition("_")
    if not separator or not _PREFIX_PATTERN.match(prefix) or len(body) < 8:
        return None
    if any(char not in ALPHABET for char in body):
        return None
    return prefix


def is_id(value: str, prefix: str | None = None) -> bool:
    """True if ``value`` is a well-formed ID, optionally of a specific ``prefix``."""
    found = parse_prefix(value)
    if found is None:
        return False
    return found == prefix if prefix is not None else True
