from __future__ import annotations

import pytest

from comfycapture.core import selectors
from comfycapture.core.models import SelectorKind


@pytest.mark.parametrize(
    "value",
    [":r3:", "wire-8f2a1c", "input-7", "headlessui-menu-item-42", "12345", "ember1043", "a1b2c3d4-aaaa-bbbb"],
)
def test_generated_ids_are_suspicious(value: str) -> None:
    assert selectors.is_suspicious_id(value)


@pytest.mark.parametrize("value", ["email", "checkout-button", "main-nav", "input-email", "step2"])
def test_authored_ids_are_trusted(value: str) -> None:
    assert not selectors.is_suspicious_id(value)


def test_candidates_are_ranked_by_priority() -> None:
    target = selectors.target_from_candidates(
        [
            {"kind": "css", "value": "form > button"},
            {"kind": "role", "role": "button", "value": "Pay"},
            {"kind": "id", "value": "wire-8f2a1c"},
            {"kind": "label", "value": "Pay now"},
            {"kind": "test_id", "attribute": "data-testid", "value": "pay"},
            {"kind": "test_id", "attribute": "dusk", "value": "pay-button"},
            {"kind": "id", "value": "pay"},
        ],
        ("dusk", "data-testid"),
    )

    assert [(selector.kind, selector.value) for selector in target.candidates] == [
        (SelectorKind.TEST_ID, "pay-button"),
        (SelectorKind.TEST_ID, "pay"),
        (SelectorKind.ID, "pay"),
        (SelectorKind.LABEL, "Pay now"),
        (SelectorKind.ROLE, "Pay"),
        (SelectorKind.ID, "wire-8f2a1c"),
        (SelectorKind.CSS, "form > button"),
    ]
    assert target.fallbacks[4].suspicious


def test_incomplete_candidates_are_dropped() -> None:
    target = selectors.target_from_candidates(
        [{"kind": "role", "value": "Pay"}, {"kind": "text", "value": "Pay"}, {"kind": "css", "value": " "}],
        (),
    )

    assert target is None


def test_disabled_selector_kinds_are_left_out_but_css_stays() -> None:
    candidates = [
        {"kind": "id", "value": "pay"},
        {"kind": "role", "role": "button", "value": "Pay"},
        {"kind": "css", "value": "form > button"},
    ]

    target = selectors.target_from_candidates(candidates, (), allowed_kinds=(SelectorKind.ROLE,))

    assert [selector.kind for selector in target.candidates] == [SelectorKind.ROLE, SelectorKind.CSS]
