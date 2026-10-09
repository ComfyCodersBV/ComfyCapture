from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from comfycapture.core import fake, selectors
from comfycapture.core.models import Action, Device, EnvironmentConfig, Step, Target

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page, Playwright

DEFAULT_TIMEOUT_MS = 10_000
POLL_INTERVAL_MS = 100
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_:.-]*)\s*\}\}")
SECRET_PREFIX = "secret:"


class ReplayError(Exception):
    def __init__(self, step_id: str, message: str) -> None:
        super().__init__(message)
        self.step_id = step_id


class MissingVariableError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StepOutcome:
    step_id: str
    passed: bool
    duration_ms: int
    selector_index: int | None = None
    message: str | None = None

    @property
    def drifted(self) -> bool:
        return bool(self.selector_index)


class VariableResolver:
    def __init__(
        self,
        variables: Mapping[str, str] | None = None,
        secrets: Callable[[str], str | None] | None = None,
        locale: str | None = None,
    ) -> None:
        self._variables = dict(variables or {})
        self._secrets = secrets
        self._locale = locale
        self._fakes = fake.FakeValues(locale)

    def fresh(self, locale: str | None = None) -> VariableResolver:
        return VariableResolver(self._variables, self._secrets, locale or self._locale)

    def resolve(self, text: str) -> str:
        return PLACEHOLDER.sub(lambda match: self._lookup(match.group(1)), text)

    def _lookup(self, name: str) -> str:
        if fake.is_reference(name):
            try:
                return self._fakes.value(name)
            except fake.UnknownFakeKindError as error:
                raise MissingVariableError(str(error)) from error
        if name.startswith(SECRET_PREFIX):
            secret_name = name[len(SECRET_PREFIX) :]
            value = self._secrets(secret_name) if self._secrets else None
            if value is None:
                raise MissingVariableError(f"Secret {secret_name!r} is not configured.")
            return value
        if name not in self._variables:
            raise MissingVariableError(f"Variable {name!r} is not configured.")
        return self._variables[name]


def absolute_url(url: str, base_url: str) -> str:
    if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.IGNORECASE):
        return url
    return base_url.rstrip("/") + "/" + url.lstrip("/")


def context_options(
    playwright: Playwright, device: Device, config: EnvironmentConfig, fit_window: bool = False
) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if device.is_mobile:
        options.update(playwright.devices[device.name or ""])
    elif fit_window:
        options["no_viewport"] = True
    else:
        options["viewport"] = {"width": device.width, "height": device.height}
    if config.locale:
        options["locale"] = config.locale
    if config.timezone:
        options["timezone_id"] = config.timezone
    if config.ignore_https_errors:
        options["ignore_https_errors"] = True
    return options


def resolve_target(page: Page, step_id: str, target: Target, timeout_ms: int) -> tuple[Locator, int]:
    from playwright.sync_api import Error

    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        for index, selector in enumerate(target.candidates):
            locator = selectors.to_locator(page, selector)
            try:
                if locator.count() == 1:
                    return locator, index
            except Error:
                continue
        if time.monotonic() >= deadline:
            tried = ", ".join(selectors.describe(selector) for selector in target.candidates)
            raise ReplayError(step_id, f"No selector matched exactly one element: {tried}")
        page.wait_for_timeout(POLL_INTERVAL_MS)


def perform(page: Page, step: Step, base_url: str, resolver: VariableResolver, timeout_ms: int) -> int | None:
    from playwright.sync_api import expect

    if step.action is Action.UNKNOWN:
        raise ReplayError(step.id, f"Step {step.id} is not replayable: {step.raw}")
    if step.action is Action.NAVIGATE:
        page.goto(absolute_url(resolver.resolve(step.url or "/"), base_url), timeout=timeout_ms * 3)
        return None
    if step.target is None:
        raise ReplayError(step.id, f"Step {step.id} has no target.")

    locator, index = resolve_target(page, step.id, step.target, step.timeout_ms or timeout_ms)
    value = resolver.resolve(step.value) if step.value is not None else ""
    step_timeout = step.timeout_ms or timeout_ms

    match step.action:
        case Action.CLICK:
            locator.click(timeout=step_timeout)
        case Action.DBLCLICK:
            locator.dblclick(timeout=step_timeout)
        case Action.TAP:
            locator.tap(timeout=step_timeout)
        case Action.FILL:
            locator.fill(value, timeout=step_timeout)
        case Action.PRESS:
            locator.press(value, timeout=step_timeout)
        case Action.CHECK:
            locator.check(timeout=step_timeout)
        case Action.UNCHECK:
            locator.uncheck(timeout=step_timeout)
        case Action.SELECT_OPTION:
            locator.select_option(value.split(",") if "," in value else value, timeout=step_timeout)
        case Action.HOVER:
            locator.hover(timeout=step_timeout)
        case Action.SET_INPUT_FILES:
            locator.set_input_files([path for path in value.split(",") if path], timeout=step_timeout)
        case Action.ASSERT_VISIBLE:
            expect(locator).to_be_visible(timeout=step_timeout)
        case Action.ASSERT_TEXT:
            expect(locator).to_contain_text(value, timeout=step_timeout)
        case Action.ASSERT_VALUE:
            expect(locator).to_have_value(value, timeout=step_timeout)
        case Action.ASSERT_CHECKED:
            expect(locator).to_be_checked(checked=step.checked is not False, timeout=step_timeout)
    return index


def execute(
    page: Page, step: Step, base_url: str, resolver: VariableResolver, timeout_ms: int = DEFAULT_TIMEOUT_MS
) -> StepOutcome:
    from playwright.sync_api import Error

    started = time.monotonic()
    try:
        index = perform(page, step, base_url, resolver, timeout_ms)
    except (ReplayError, MissingVariableError, Error, AssertionError) as error:
        return StepOutcome(step.id, False, elapsed_ms(started), message=first_line(str(error)))
    return StepOutcome(step.id, True, elapsed_ms(started), selector_index=index)


def accept_dialogs(page: Page) -> None:
    page.on("dialog", lambda dialog: dialog.accept())


def replay(
    page: Page,
    steps: Iterable[Step],
    base_url: str,
    resolver: VariableResolver,
    on_step: Callable[[StepOutcome], None] | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> list[StepOutcome]:
    outcomes: list[StepOutcome] = []
    for step in steps:
        outcome = execute(page, step, base_url, resolver, timeout_ms)
        outcomes.append(outcome)
        if on_step is not None:
            on_step(outcome)
        if not outcome.passed:
            break
    return outcomes


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def first_line(message: str) -> str:
    lines = [line.strip() for line in message.strip().splitlines() if line.strip()]
    return lines[0] if lines else "Unknown error"
