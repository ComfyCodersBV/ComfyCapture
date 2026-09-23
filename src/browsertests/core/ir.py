"""The test format: the IR document is the source of truth for a test.

`to_document` / `from_document` convert between `Test` and a plain JSON-compatible dict. `from_document`
migrates older schema versions forward and refuses newer ones.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from browsertests.core.models import (
    TARGETED_ACTIONS,
    VALUE_ACTIONS,
    Action,
    Device,
    DeviceKind,
    Selector,
    SelectorKind,
    Step,
    Target,
    Test,
)

SCHEMA_VERSION = 1
TICKET_PATTERN = re.compile(r"^[A-Za-z]+-\d+$")
PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_:.-]*)\s*\}\}")

Document = dict[str, Any]
Migration = Callable[[Document], Document]

MIGRATIONS: dict[int, Migration] = {}


class InvalidDocumentError(ValueError):
    pass


class UnsupportedSchemaVersionError(InvalidDocumentError):
    pass


def new_test_id() -> str:
    return str(uuid.uuid4())


def new_step_id() -> str:
    return f"s{uuid.uuid4().hex[:8]}"


def is_ticket_tag(tag: str) -> bool:
    return TICKET_PATTERN.match(tag) is not None


def normalize_tags(tags: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for tag in tags:
        cleaned = tag.strip()
        if not cleaned:
            continue
        if is_ticket_tag(cleaned):
            cleaned = cleaned.upper()
        if cleaned not in normalized:
            normalized.append(cleaned)
    return tuple(normalized)


def placeholders(test: Test) -> tuple[str, ...]:
    names: list[str] = []
    for step in test.steps:
        for text in (step.value, step.url):
            if text is None:
                continue
            for name in PLACEHOLDER_PATTERN.findall(text):
                if name not in names:
                    names.append(name)
    return tuple(names)


def selector_to_dict(selector: Selector) -> Document:
    document: Document = {"kind": selector.kind.value, "value": selector.value}
    if selector.attribute is not None:
        document["attribute"] = selector.attribute
    if selector.role is not None:
        document["role"] = selector.role
    if selector.suspicious:
        document["suspicious"] = True
    return document


def selector_from_dict(document: Document) -> Selector:
    kind = SelectorKind(document["kind"])
    if kind is SelectorKind.ROLE and not document.get("role"):
        raise InvalidDocumentError("A role selector needs a role.")
    if kind is SelectorKind.TEST_ID and not document.get("attribute"):
        raise InvalidDocumentError("A test_id selector needs an attribute.")
    return Selector(
        kind=kind,
        value=str(document.get("value", "")),
        attribute=document.get("attribute"),
        role=document.get("role"),
        suspicious=bool(document.get("suspicious", False)),
    )


def target_to_dict(target: Target) -> Document:
    return {
        "primary": selector_to_dict(target.primary),
        "fallbacks": [selector_to_dict(selector) for selector in target.fallbacks],
    }


def target_from_dict(document: Document) -> Target:
    return Target(
        primary=selector_from_dict(document["primary"]),
        fallbacks=tuple(selector_from_dict(item) for item in document.get("fallbacks", [])),
    )


def step_to_dict(step: Step) -> Document:
    document: Document = {"id": step.id, "action": step.action.value}
    if step.url is not None:
        document["url"] = step.url
    if step.target is not None:
        document["target"] = target_to_dict(step.target)
    if step.value is not None:
        document["value"] = step.value
    if step.checked is not None:
        document["checked"] = step.checked
    if step.timeout_ms is not None:
        document["timeout_ms"] = step.timeout_ms
    if step.raw is not None:
        document["raw"] = step.raw
    if step.note is not None:
        document["note"] = step.note
    return document


def step_from_dict(document: Document) -> Step:
    step_id = document.get("id")
    if not isinstance(step_id, str) or not step_id:
        raise InvalidDocumentError("Every step needs a string id.")
    try:
        action = Action(document.get("action"))
    except ValueError as error:
        raise InvalidDocumentError(f"Step {step_id}: unknown action {document.get('action')!r}.") from error

    target = target_from_dict(document["target"]) if document.get("target") else None
    step = Step(
        id=step_id,
        action=action,
        target=target,
        url=document.get("url"),
        value=document.get("value"),
        checked=document.get("checked"),
        timeout_ms=document.get("timeout_ms"),
        raw=document.get("raw"),
        note=document.get("note"),
    )
    validate_step(step)
    return step


def validate_step(step: Step) -> None:
    if step.action is Action.NAVIGATE and not step.url:
        raise InvalidDocumentError(f"Step {step.id}: navigate needs a url.")
    if step.action in TARGETED_ACTIONS and step.target is None:
        raise InvalidDocumentError(f"Step {step.id}: {step.action.value} needs a target.")
    if step.action in VALUE_ACTIONS and step.value is None:
        raise InvalidDocumentError(f"Step {step.id}: {step.action.value} needs a value.")


def device_to_dict(device: Device) -> Document:
    if device.is_mobile:
        return {"kind": device.kind.value, "name": device.name}
    document: Document = {"kind": device.kind.value, "width": device.width, "height": device.height}
    if device.fullscreen:
        document["fullscreen"] = True
    return document


def device_from_dict(document: Document | None) -> Device:
    if not document:
        return Device()
    kind = DeviceKind(document.get("kind", DeviceKind.DESKTOP.value))
    if kind is DeviceKind.MOBILE:
        name = document.get("name")
        if not name:
            raise InvalidDocumentError("A mobile device needs a Playwright device name.")
        return Device(kind=kind, name=name)
    return Device(
        kind=kind,
        width=int(document.get("width", 1440)),
        height=int(document.get("height", 900)),
        fullscreen=bool(document.get("fullscreen", False)),
    )


def to_document(test: Test) -> Document:
    return {
        "schema_version": SCHEMA_VERSION,
        "id": test.id,
        "name": test.name,
        "description": test.description,
        "tags": list(test.tags),
        "destructive": test.destructive,
        "device": device_to_dict(test.device),
        "steps": [step_to_dict(step) for step in test.steps],
    }


def migrate(document: Document) -> Document:
    version = document.get("schema_version")
    if not isinstance(version, int) or version < 1:
        raise InvalidDocumentError("The document has no valid schema_version.")
    if version > SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"Schema version {version} is newer than this installation supports ({SCHEMA_VERSION})."
        )
    while version < SCHEMA_VERSION:
        document = MIGRATIONS[version](document)
        version += 1
        document["schema_version"] = version
    return document


def from_document(document: Document) -> Test:
    document = migrate(dict(document))
    test_id = document.get("id")
    name = document.get("name")
    if not isinstance(test_id, str) or not test_id:
        raise InvalidDocumentError("The test needs a string id.")
    if not isinstance(name, str) or not name.strip():
        raise InvalidDocumentError("The test needs a name.")

    steps = tuple(step_from_dict(item) for item in document.get("steps", []))
    step_ids = [step.id for step in steps]
    if len(step_ids) != len(set(step_ids)):
        raise InvalidDocumentError("Step ids must be unique within a test.")

    return Test(
        id=test_id,
        name=name.strip(),
        description=str(document.get("description", "")),
        tags=normalize_tags(document.get("tags", [])),
        destructive=bool(document.get("destructive", False)),
        device=device_from_dict(document.get("device")),
        steps=steps,
    )


def dumps(test: Test) -> str:
    return json.dumps(to_document(test), indent=2, ensure_ascii=False) + "\n"


def loads(text: str) -> Test:
    return from_document(json.loads(text))
