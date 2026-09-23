"""Selector strategy: ranking recorded candidates and turning selectors into Playwright locators.

Priority for a target's primary: test attribute (in project order) > authored id > label > role + name >
placeholder > suspicious id > CSS path.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from browsertests.core.models import Selector, SelectorKind, Target

if TYPE_CHECKING:
    from playwright.sync_api import Frame, Locator, Page

GENERATED_ID_PREFIXES = (
    "wire-",
    "livewire-",
    "headlessui-",
    "radix-",
    "react-",
    "mui-",
    "mantine-",
    "ember",
    "ext-gen",
    "yui_",
    "data-v-",
    "ui-id-",
    "select2-",
    "filament-",
)
NUMERIC_ONLY = re.compile(r"^\d+$")
REACT_USE_ID = re.compile(r"^:[\w-]+:$|^«[\w-]+»$")
HASH_SEGMENT = re.compile(
    r"(?:^|[-_:.])(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{6,}(?:$|[-_:.])", re.IGNORECASE
)
TRAILING_COUNTER = re.compile(r"[-_]\d+$")
UUID_LIKE = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}", re.IGNORECASE)

KIND_ORDER = {
    SelectorKind.TEST_ID: 0,
    SelectorKind.ID: 1,
    SelectorKind.LABEL: 2,
    SelectorKind.ROLE: 3,
    SelectorKind.PLACEHOLDER: 4,
    SelectorKind.CSS: 6,
}
SUSPICIOUS_ID_RANK = 5


def is_suspicious_id(value: str) -> bool:
    lowered = value.lower()
    if NUMERIC_ONLY.match(value) or REACT_USE_ID.match(value) or ":" in value:
        return True
    if lowered.startswith(GENERATED_ID_PREFIXES):
        return True
    if UUID_LIKE.search(value):
        return True
    return bool(HASH_SEGMENT.search(value) or TRAILING_COUNTER.search(value))


def selector_from_candidate(candidate: Mapping[str, Any]) -> Selector | None:
    try:
        kind = SelectorKind(candidate.get("kind"))
    except ValueError:
        return None
    value = str(candidate.get("value") or "").strip()
    if not value:
        return None
    if kind is SelectorKind.ROLE and not candidate.get("role"):
        return None
    if kind is SelectorKind.TEST_ID and not candidate.get("attribute"):
        return None
    return Selector(
        kind=kind,
        value=value,
        attribute=candidate.get("attribute"),
        role=candidate.get("role"),
        suspicious=kind is SelectorKind.ID and is_suspicious_id(value),
    )


def rank_key(selector: Selector, test_id_attributes: tuple[str, ...]) -> tuple[int, int]:
    if selector.kind is SelectorKind.TEST_ID:
        attribute = selector.attribute or ""
        position = test_id_attributes.index(attribute) if attribute in test_id_attributes else 99
        return (KIND_ORDER[selector.kind], position)
    if selector.kind is SelectorKind.ID and selector.suspicious:
        return (SUSPICIOUS_ID_RANK, 0)
    return (KIND_ORDER[selector.kind], 0)


def rank(selectors: Iterable[Selector], test_id_attributes: tuple[str, ...]) -> Target | None:
    unique: list[Selector] = []
    for selector in selectors:
        if selector not in unique:
            unique.append(selector)
    if not unique:
        return None
    ordered = sorted(unique, key=lambda selector: rank_key(selector, test_id_attributes))
    return Target(primary=ordered[0], fallbacks=tuple(ordered[1:]))


def target_from_candidates(
    candidates: Iterable[Mapping[str, Any]], test_id_attributes: tuple[str, ...]
) -> Target | None:
    selectors = [selector_from_candidate(candidate) for candidate in candidates]
    return rank([selector for selector in selectors if selector is not None], test_id_attributes)


def css_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_locator(scope: Page | Frame, selector: Selector) -> Locator:
    match selector.kind:
        case SelectorKind.TEST_ID:
            return scope.locator(f"[{selector.attribute}={css_string(selector.value)}]")
        case SelectorKind.ID:
            return scope.locator(f"[id={css_string(selector.value)}]")
        case SelectorKind.LABEL:
            return scope.get_by_label(selector.value, exact=True)
        case SelectorKind.ROLE:
            return scope.get_by_role(selector.role, name=selector.value, exact=True)
        case SelectorKind.PLACEHOLDER:
            return scope.get_by_placeholder(selector.value, exact=True)
        case SelectorKind.CSS:
            return scope.locator(selector.value)


def describe(selector: Selector) -> str:
    match selector.kind:
        case SelectorKind.TEST_ID:
            return f"[{selector.attribute}={css_string(selector.value)}]"
        case SelectorKind.ID:
            return f"#{selector.value}"
        case SelectorKind.LABEL:
            return f"label {css_string(selector.value)}"
        case SelectorKind.ROLE:
            return f"{selector.role} {css_string(selector.value)}"
        case SelectorKind.PLACEHOLDER:
            return f"placeholder {css_string(selector.value)}"
        case SelectorKind.CSS:
            return selector.value
