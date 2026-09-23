from __future__ import annotations

from browsertests.core import ir, selectors
from browsertests.core.models import Action, Step


def target_text(step: Step) -> str:
    if step.action is Action.NAVIGATE:
        return step.url or ""
    if step.action is Action.UNKNOWN:
        return step.raw or ""
    if step.target is None:
        return ""
    return selectors.describe(step.target.primary)


def value_text(step: Step) -> str:
    if step.action is Action.ASSERT_CHECKED:
        return "checked" if step.checked is not False else "not checked"
    return step.value or ""


def attention(step: Step) -> list[str]:
    reasons: list[str] = []
    if step.action is Action.UNKNOWN:
        reasons.append("unknown step")
    if step.target is not None:
        if step.target.primary.suspicious:
            reasons.append("primary is a generated-looking id")
        if not step.target.fallbacks:
            reasons.append("no fallback selectors")
    if step.note:
        reasons.append(step.note)
    return reasons


def tag_text(tag: str) -> str:
    return f"🎫 {tag}" if ir.is_ticket_tag(tag) else tag
