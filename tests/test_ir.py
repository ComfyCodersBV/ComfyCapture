from __future__ import annotations

import pytest

from browsertests.core import ir
from browsertests.core.models import Action, Device, DeviceKind, Selector, SelectorKind, Step, Target, Test


def sample_test() -> Test:
    return Test(
        id="0c9f",
        name="Guest checkout",
        tags=("CINF-19", "checkout"),
        device=Device(kind=DeviceKind.MOBILE, name="iPhone 13"),
        steps=(
            Step(id="s1", action=Action.NAVIGATE, url="/products/42"),
            Step(
                id="s2",
                action=Action.TAP,
                target=Target(
                    primary=Selector(SelectorKind.TEST_ID, "add-to-cart", attribute="dusk"),
                    fallbacks=(
                        Selector(SelectorKind.ROLE, "Add to cart", role="button"),
                        Selector(SelectorKind.ID, "wire-8f2a1c", suspicious=True),
                    ),
                ),
            ),
            Step(
                id="s3",
                action=Action.FILL,
                target=Target(primary=Selector(SelectorKind.LABEL, "Email")),
                value="{{customer_email}}",
            ),
            Step(id="s4", action=Action.UNKNOWN, raw="drag from .a to .b"),
        ),
    )


def test_document_round_trips() -> None:
    test = sample_test()

    assert ir.loads(ir.dumps(test)) == test


def test_newer_schema_version_is_refused() -> None:
    document = ir.to_document(sample_test())
    document["schema_version"] = ir.SCHEMA_VERSION + 1

    with pytest.raises(ir.UnsupportedSchemaVersionError):
        ir.from_document(document)


def test_older_schema_version_is_migrated(monkeypatch: pytest.MonkeyPatch) -> None:
    document = ir.to_document(sample_test())
    document["schema_version"] = 1
    document["title"] = document.pop("name")
    monkeypatch.setattr(ir, "SCHEMA_VERSION", 2)
    monkeypatch.setitem(ir.MIGRATIONS, 1, lambda old: {**old, "name": old.pop("title")})

    assert ir.from_document(document).name == "Guest checkout"


@pytest.mark.parametrize(
    "step",
    [
        {"id": "s1", "action": "navigate"},
        {"id": "s1", "action": "click"},
        {"id": "s1", "action": "fill", "target": {"primary": {"kind": "label", "value": "Email"}}},
        {"id": "s1", "action": "teleport"},
        {"action": "click"},
    ],
)
def test_invalid_steps_are_rejected(step: dict) -> None:
    document = ir.to_document(sample_test())
    document["steps"] = [step]

    with pytest.raises(ir.InvalidDocumentError):
        ir.from_document(document)


def test_duplicate_step_ids_are_rejected() -> None:
    document = ir.to_document(sample_test())
    document["steps"] = [document["steps"][0], document["steps"][0]]

    with pytest.raises(ir.InvalidDocumentError):
        ir.from_document(document)


def test_tags_are_normalised() -> None:
    assert ir.normalize_tags([" cinf-19", "CINF-19", "checkout", "", "Checkout"]) == (
        "CINF-19",
        "checkout",
        "Checkout",
    )


def test_placeholders_are_collected() -> None:
    assert ir.placeholders(sample_test()) == ("customer_email",)
