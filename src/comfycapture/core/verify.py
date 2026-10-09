"""Verification replay after recording.

Replays the steps headless and, per targeted step, checks every recorded selector candidate against the
live DOM with real Playwright locators. Candidates that miss, match several elements or match a different
element are dropped. The recording is the first page load and this replay the second, so an id that is
no longer found here changed between loads and is reported as unstable.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from comfycapture.core import ir, runner, selectors
from comfycapture.core.models import Action, Selector, SelectorKind, Step, Target

if TYPE_CHECKING:
    from playwright.sync_api import Page

REFERENCE_ORDER = (SelectorKind.TEST_ID, SelectorKind.ID, SelectorKind.CSS)


@dataclass(frozen=True, slots=True)
class Verification:
    steps: tuple[Step, ...]
    outcomes: tuple[runner.StepOutcome, ...]

    @property
    def failed(self) -> runner.StepOutcome | None:
        return next((outcome for outcome in self.outcomes if not outcome.passed), None)


def reference_order(candidates: Iterable[Selector]) -> list[Selector]:
    ordered = list(candidates)
    return sorted(
        ordered,
        key=lambda selector: (
            REFERENCE_ORDER.index(selector.kind)
            if selector.kind in REFERENCE_ORDER
            else len(REFERENCE_ORDER),
            selector.suspicious,
        ),
    )


def verify_target(page: Page, step: Step, test_id_attributes: tuple[str, ...], timeout_ms: int) -> Step:
    from playwright.sync_api import Error

    if step.target is None:
        return step
    ordered = reference_order(step.target.candidates)
    try:
        reference, _ = runner.resolve_target(
            page, step.id, Target(ordered[0], tuple(ordered[1:])), timeout_ms
        )
        handle = reference.element_handle(timeout=timeout_ms)
    except (runner.ReplayError, Error):
        return replace(step, note=join_notes(step.note, "Could not verify selectors: element not found."))
    if handle is None:
        return step

    kept: list[Selector] = []
    notes: list[str] = []
    for selector in step.target.candidates:
        locator = selectors.to_locator(page, selector)
        try:
            same = locator.count() == 1 and bool(
                locator.evaluate("(element, reference) => element === reference", handle)
            )
        except Error:
            same = False
        if same:
            kept.append(selector)
            continue
        if selector.kind is SelectorKind.ID:
            notes.append(f"id {selector.value!r} changed between page loads; dropped.")

    handle.dispose()
    target = selectors.rank(kept, test_id_attributes)
    if target is None:
        return replace(step, note=join_notes(step.note, "Could not verify selectors: no candidate matched."))
    return replace(step, target=target, note=join_notes(step.note, *notes))


def join_notes(*notes: str | None) -> str | None:
    parts = [note for note in notes if note]
    return " ".join(parts) if parts else None


def verify(
    page: Page,
    steps: Iterable[Step],
    base_url: str,
    resolver: runner.VariableResolver,
    test_id_attributes: tuple[str, ...],
    timeout_ms: int = runner.DEFAULT_TIMEOUT_MS,
    on_step: Callable[[runner.StepOutcome], None] | None = None,
) -> Verification:
    verified: list[Step] = []
    outcomes: list[runner.StepOutcome] = []
    remaining = list(steps)
    while remaining:
        step = remaining.pop(0)
        if step.target is not None and step.action is not Action.UNKNOWN:
            step = verify_target(page, step, test_id_attributes, timeout_ms)
        verified.append(step)
        outcome = runner.execute(page, step, base_url, resolver, timeout_ms)
        outcomes.append(outcome)
        if on_step is not None:
            on_step(outcome)
        if not outcome.passed:
            break
    return Verification(tuple(verified + remaining), tuple(outcomes))


def main(argv: Sequence[str] | None = None) -> int:
    from playwright.sync_api import sync_playwright

    from comfycapture.core.secrets import SecretStore
    from comfycapture.core.session import SessionPayload, emit, outcome_to_dict

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        sys.stderr.write("usage: python -m comfycapture.core.verify <payload.json>\n")
        return 2
    payload = SessionPayload.from_dict(json.loads(Path(arguments[0]).read_text(encoding="utf-8")))
    resolver = runner.VariableResolver(
        payload.variables, SecretStore(payload.project_slug).get, payload.environment.locale
    )
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                **runner.context_options(playwright, payload.device, payload.environment)
            )
            page = context.new_page()
            runner.accept_dialogs(page)
            result = verify(
                page,
                payload.steps,
                payload.base_url,
                resolver,
                payload.test_id_attributes,
                on_step=lambda outcome: emit({"type": "replayed", "outcome": outcome_to_dict(outcome)}),
            )
            browser.close()
    except Exception as error:
        emit({"type": "error", "message": runner.first_line(str(error)), "fatal": True})
        return 1
    message: dict[str, Any] = {"type": "done", "steps": [ir.step_to_dict(step) for step in result.steps]}
    if result.failed is not None:
        message["failed"] = outcome_to_dict(result.failed)
    emit(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
