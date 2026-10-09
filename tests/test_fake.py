from __future__ import annotations

import pytest

from comfycapture.core import runner


def test_a_fake_reference_keeps_its_value_within_one_run() -> None:
    resolver = runner.VariableResolver()

    first = resolver.resolve("{{fake:email}}")

    assert "@" in first
    assert resolver.resolve("{{ fake:email }}") == first
    assert resolver.resolve("{{fake:email:2}}") != first


def test_a_fresh_resolver_draws_new_fake_values_but_keeps_variables() -> None:
    resolver = runner.VariableResolver({"host": "shop.test"})
    first = resolver.resolve("{{fake:uuid}}")

    fresh = resolver.fresh("en-US")

    assert fresh.resolve("{{fake:uuid}}") != first
    assert fresh.resolve("{{host}}") == "shop.test"


def test_an_unknown_fake_kind_is_a_missing_variable() -> None:
    with pytest.raises(runner.MissingVariableError, match="nope"):
        runner.VariableResolver().resolve("{{fake:nope}}")


def test_an_unsupported_locale_falls_back() -> None:
    assert runner.VariableResolver(locale="xx-YY").resolve("{{fake:name}}")
