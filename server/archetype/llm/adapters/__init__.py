"""Provider adapters - the **only** place a provider SDK may be imported (P4-5, P4-6).

phase-4-plan section 2, ruling 2, and specs/providers.md section 11: no provider SDK is imported
outside this package. Not in a route, not in a store, not in a test that is not an adapter test.
An SDK type that escapes into a route is how "nothing above the port knows which provider is in
play" quietly stops being true, and it does not announce itself - the app goes on working until
the second provider is configured.

The rule is enforced by ``tests/test_llm_port.py::test_no_provider_sdk_is_imported_outside_the_
adapters_package``, which walks the import graph of ``archetype/`` rather than trusting a code
review to notice.

Empty in Group A. ``anthropic.py`` lands at P4-5 and ``openai_compat.py`` at P4-6; the registry
that constructs one of them from settings is P4-8, and it is the only place a provider is built.
"""

from __future__ import annotations

__all__: list[str] = []
