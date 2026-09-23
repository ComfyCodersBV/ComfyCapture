"""Runs a selection of stored tests against one environment and reports the results.

Per test: a fresh browser context (device emulation, environment settings, consent cookies, basic auth,
the login session), the project's setup test, then the test itself. A test that fails is retried; one
that passes on a retry is flaky. A trace and a screenshot are kept only for a final failure.
"""

from __future__ import annotations

import contextlib
import queue
import shutil
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from browsertests.core import ir, runner
from browsertests.core.models import Environment, Project, RunRecord, RunStatus, Step, StoredTest
from browsertests.core.session import outcome_to_dict

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Playwright

    from browsertests.core.db import RunRepository

DEFAULT_RETRIES = 1
DEFAULT_WORKERS = 2
RETENTION_DAYS = 14

Emit = Callable[[dict[str, Any]], None]


class ConfigurationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SuitePlan:
    project: Project
    environment: Environment
    tests: tuple[StoredTest, ...]
    artifact_root: Path
    setup: StoredTest | None = None
    login: StoredTest | None = None
    headed: bool = False
    retries: int = DEFAULT_RETRIES
    timeout_ms: int = runner.DEFAULT_TIMEOUT_MS
    workers: int = DEFAULT_WORKERS


@dataclass(frozen=True, slots=True)
class TestResult:
    __test__ = False

    stored: StoredTest
    status: RunStatus
    duration_ms: int
    attempts: int = 1
    failed_step_id: str | None = None
    message: str | None = None
    artifact_path: str | None = None
    drifted_steps: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test": self.stored.test.id,
            "name": self.stored.test.name,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
            "failed_step_id": self.failed_step_id,
            "message": self.message,
            "artifact_path": self.artifact_path,
            "drifted_steps": list(self.drifted_steps),
        }


def playwright_version() -> str:
    from playwright._repo_version import version

    return str(version)


def missing_references(plan: SuitePlan, resolver: runner.VariableResolver) -> list[str]:
    tests = [stored.test for stored in (*plan.tests, plan.setup, plan.login) if stored is not None]
    missing: list[str] = []
    for test in tests:
        for name in ir.placeholders(test):
            try:
                resolver.resolve("{{" + name + "}}")
            except runner.MissingVariableError as error:
                if str(error) not in missing:
                    missing.append(str(error))
    credential = plan.environment.config.http_credentials
    if credential and not http_credentials(credential, resolver):
        missing.append(f"HTTP credentials secret {credential!r} is not configured as 'user:password'.")
    return missing


def http_credentials(secret_name: str, resolver: runner.VariableResolver) -> dict[str, str] | None:
    try:
        value = resolver.resolve("{{secret:" + secret_name + "}}")
    except runner.MissingVariableError:
        return None
    if ":" not in value:
        return None
    username, password = value.split(":", 1)
    return {"username": username, "password": password}


def cookies_for(environment: Environment) -> list[dict[str, Any]]:
    origin = urlsplit(environment.base_url)
    url = f"{origin.scheme}://{origin.netloc}"
    result = []
    for entry in environment.config.cookies:
        if "=" not in entry:
            continue
        name, value = entry.split("=", 1)
        result.append({"name": name.strip(), "value": value.strip(), "url": url})
    return result


class SuiteRunner:
    def __init__(self, plan: SuitePlan, resolver: runner.VariableResolver, emit: Emit | None = None) -> None:
        self._plan = plan
        self._resolver = resolver
        self._lock = threading.Lock()
        target = emit or (lambda _message: None)

        def locked(message: dict[str, Any]) -> None:
            with self._lock:
                target(message)

        self._emit = locked
        self.browser_version = ""

    def run(self) -> list[TestResult]:
        from playwright.sync_api import sync_playwright

        missing = missing_references(self._plan, self._resolver)
        if missing:
            raise ConfigurationError(" ".join(missing))

        storage = None
        if self._plan.login is not None:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=not self._plan.headed)
                try:
                    storage = self._login(playwright, browser)
                except ConfigurationError as error:
                    return [self._error(stored, str(error)) for stored in self._plan.tests]
                finally:
                    browser.close()

        pending: queue.Queue[tuple[int, StoredTest]] = queue.Queue()
        for index, stored in enumerate(self._plan.tests):
            pending.put((index, stored))
        results: dict[int, TestResult] = {}
        workers = max(1, min(self._plan.workers, len(self._plan.tests)))
        threads = [
            threading.Thread(target=self._work, args=(pending, results, storage)) for _ in range(workers)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return [results[index] for index in range(len(self._plan.tests))]

    def _work(
        self, pending: queue.Queue[tuple[int, StoredTest]], results: dict[int, TestResult], storage: Any
    ) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not self._plan.headed)
            self.browser_version = browser.version
            while True:
                try:
                    index, stored = pending.get_nowait()
                except queue.Empty:
                    break
                self._emit({"type": "test_started", "test": stored.test.id, "name": stored.test.name})
                try:
                    result = self._run_test(playwright, browser, stored, storage)
                except Exception as error:
                    result = self._error(stored, runner.first_line(str(error)))
                with self._lock:
                    results[index] = result
                self._emit({"type": "test_finished", "result": result.to_dict()})
            browser.close()

    def _context(
        self, playwright: Playwright, browser: Browser, stored: StoredTest, storage: Any
    ) -> BrowserContext:
        environment = self._plan.environment
        options = runner.context_options(playwright, stored.test.device, environment.config)
        options.pop("default_browser_type", None)
        if storage is not None:
            options["storage_state"] = storage
        credential = environment.config.http_credentials
        if credential:
            options["http_credentials"] = http_credentials(credential, self._resolver)
        context = browser.new_context(**options)
        cookies = cookies_for(environment)
        if cookies:
            context.add_cookies(cookies)
        return context

    def _login(self, playwright: Playwright, browser: Browser) -> Any:
        login = self._plan.login
        if login is None:
            return None
        self._emit({"type": "login_started", "name": login.test.name})
        context = self._context(playwright, browser, login, None)
        page = context.new_page()
        runner.accept_dialogs(page)
        outcomes = runner.replay(
            page,
            login.test.steps,
            self._plan.environment.base_url,
            self._resolver,
            timeout_ms=self._plan.timeout_ms,
        )
        if outcomes and not outcomes[-1].passed:
            context.close()
            raise ConfigurationError(
                f"Login test {login.test.name!r} failed at step {outcomes[-1].step_id}: {outcomes[-1].message}"
            )
        storage = context.storage_state()
        context.close()
        return storage

    def _run_test(
        self, playwright: Playwright, browser: Browser, stored: StoredTest, storage: Any
    ) -> TestResult:
        environment = self._plan.environment
        if stored.test.destructive and not environment.allow_destructive:
            return TestResult(
                stored,
                RunStatus.SKIPPED,
                0,
                attempts=0,
                message=f"REFUSED: destructive test, and environment {environment.name!r} does not allow "
                "destructive tests.",
            )

        attempts = 1 + max(0, self._plan.retries)
        started = time.monotonic()
        failure: tuple[str | None, str | None, str | None] = (None, None, None)
        for attempt in range(1, attempts + 1):
            final = attempt == attempts
            passed, drifted, failure = self._attempt(
                playwright, browser, stored, storage, keep_artifacts=final
            )
            if passed:
                status = RunStatus.FLAKY if attempt > 1 else RunStatus.PASSED
                message = f"Passed on attempt {attempt} of {attempts}." if attempt > 1 else None
                if drifted:
                    drift = (
                        "Selector drift at steps " + ", ".join(drifted) + ": a fallback selector was used."
                    )
                    message = f"{message} {drift}" if message else drift
                return TestResult(
                    stored,
                    status,
                    runner.elapsed_ms(started),
                    attempt,
                    message=message,
                    drifted_steps=drifted,
                )
        step_id, message, artifact = failure
        return TestResult(
            stored,
            RunStatus.FAILED,
            runner.elapsed_ms(started),
            attempts,
            failed_step_id=step_id,
            message=message,
            artifact_path=artifact,
        )

    def _attempt(
        self, playwright: Playwright, browser: Browser, stored: StoredTest, storage: Any, keep_artifacts: bool
    ) -> tuple[bool, tuple[str, ...], tuple[str | None, str | None, str | None]]:
        context = self._context(playwright, browser, stored, storage)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.new_page()
        runner.accept_dialogs(page)
        base_url = self._plan.environment.base_url

        def on_step(outcome: runner.StepOutcome) -> None:
            self._emit({"type": "step", "test": stored.test.id, "outcome": outcome_to_dict(outcome)})

        setup_steps: tuple[Step, ...] = self._plan.setup.test.steps if self._plan.setup else ()
        outcomes = runner.replay(
            page, setup_steps, base_url, self._resolver, timeout_ms=self._plan.timeout_ms
        )
        if outcomes and not outcomes[-1].passed:
            message = f"Setup test failed at step {outcomes[-1].step_id}: {outcomes[-1].message}"
            return False, (), self._fail(context, page, stored, None, message, keep_artifacts)

        outcomes = runner.replay(
            page,
            stored.test.steps,
            base_url,
            self._resolver,
            on_step=on_step,
            timeout_ms=self._plan.timeout_ms,
        )
        if outcomes and not outcomes[-1].passed:
            return (
                False,
                (),
                self._fail(context, page, stored, outcomes[-1].step_id, outcomes[-1].message, keep_artifacts),
            )
        context.tracing.stop()
        context.close()
        return True, tuple(outcome.step_id for outcome in outcomes if outcome.drifted), (None, None, None)

    def _fail(
        self,
        context: BrowserContext,
        page: Any,
        stored: StoredTest,
        step_id: str | None,
        message: str | None,
        keep_artifacts: bool,
    ) -> tuple[str | None, str | None, str | None]:
        if not keep_artifacts:
            context.tracing.stop()
            context.close()
            return step_id, message, None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        directory = self._plan.artifact_root / f"{stamp}-{stored.test.id[:8]}"
        directory.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(Exception):
            page.screenshot(
                path=str(directory / "failure.png"),
                full_page=True,
                mask=[page.locator("input[type=password]")],
            )
        context.tracing.stop(path=str(directory / "trace.zip"))
        context.close()
        return step_id, message, str(directory)

    @staticmethod
    def _error(stored: StoredTest, message: str) -> TestResult:
        return TestResult(stored, RunStatus.ERROR, 0, attempts=0, message=message)


def record_results(
    runs: RunRepository,
    environment: Environment,
    results: Iterable[TestResult],
    started_at: str,
    browser_version: str,
) -> list[RunRecord]:
    version = playwright_version()
    records = []
    for result in results:
        records.append(
            runs.add(
                RunRecord(
                    id=None,
                    test_id=result.stored.id,
                    environment_id=environment.id or 0,
                    status=result.status,
                    started_at=started_at,
                    duration_ms=result.duration_ms,
                    playwright_version=version,
                    browser_version=browser_version,
                    failed_step_id=result.failed_step_id,
                    message=result.message,
                    artifact_path=result.artifact_path,
                )
            )
        )
    return records


def prune_artifacts(
    runs: RunRepository, retention_days: int = RETENTION_DAYS, now: datetime | None = None
) -> int:
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    pruned = 0
    for run in runs.with_artifacts_before(cutoff):
        if run.artifact_path:
            shutil.rmtree(run.artifact_path, ignore_errors=True)
        if run.id is not None:
            runs.clear_artifact(run.id)
            pruned += 1
    return pruned


def exit_code(results: Iterable[TestResult]) -> int:
    statuses = [result.status for result in results]
    if RunStatus.FAILED in statuses:
        return 1
    if RunStatus.ERROR in statuses or RunStatus.SKIPPED in statuses:
        return 2
    return 0
