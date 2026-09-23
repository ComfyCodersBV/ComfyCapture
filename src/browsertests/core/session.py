"""Recording session subprocess.

Run as `python -m browsertests.core.session <payload.json>`. Writes JSON lines to stdout
(`status`, `replayed`, `steps`, `error`, `done`) and stops when it reads `stop` on stdin or when the
browser is closed. Keeping the browser in its own process keeps the desktop event loop free.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from browsertests.core import ir, runner
from browsertests.core.models import Device, EnvironmentConfig, Step
from browsertests.core.recorder import Recorder
from browsertests.core.secrets import SecretStore

POLL_MS = 100


@dataclass(frozen=True, slots=True)
class SessionPayload:
    base_url: str
    test_id_attributes: tuple[str, ...]
    project_slug: str = ""
    start_path: str = "/"
    device: Device = field(default_factory=Device)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    steps: tuple[Step, ...] = ()
    variables: dict[str, str] = field(default_factory=dict)
    headless: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "test_id_attributes": list(self.test_id_attributes),
            "project_slug": self.project_slug,
            "start_path": self.start_path,
            "device": ir.device_to_dict(self.device),
            "environment": {
                "locale": self.environment.locale,
                "timezone": self.environment.timezone,
                "ignore_https_errors": self.environment.ignore_https_errors,
                "http_credentials": self.environment.http_credentials,
            },
            "steps": [ir.step_to_dict(step) for step in self.steps],
            "variables": self.variables,
            "headless": self.headless,
        }

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> SessionPayload:
        return cls(
            base_url=document["base_url"],
            test_id_attributes=tuple(document.get("test_id_attributes") or ("data-testid",)),
            project_slug=document.get("project_slug", ""),
            start_path=document.get("start_path") or "/",
            device=ir.device_from_dict(document.get("device")),
            environment=EnvironmentConfig(**(document.get("environment") or {})),
            steps=tuple(ir.step_from_dict(step) for step in document.get("steps", [])),
            variables=dict(document.get("variables") or {}),
            headless=bool(document.get("headless", False)),
        )


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def outcome_to_dict(outcome: runner.StepOutcome) -> dict[str, Any]:
    return {
        "step_id": outcome.step_id,
        "passed": outcome.passed,
        "duration_ms": outcome.duration_ms,
        "selector_index": outcome.selector_index,
        "message": outcome.message,
    }


def watch_stdin(stop: threading.Event) -> None:
    for line in sys.stdin:
        if line.strip() == "stop":
            break
    stop.set()


def record(payload: SessionPayload, stop: threading.Event) -> tuple[Step, ...]:
    from playwright.sync_api import sync_playwright

    secrets = SecretStore(payload.project_slug)
    resolver = runner.VariableResolver(payload.variables, secrets.get)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=payload.headless)
        context = browser.new_context(
            **runner.context_options(playwright, payload.device, payload.environment)
        )
        recorder = Recorder(
            context,
            payload.base_url,
            payload.test_id_attributes,
            mobile=payload.device.is_mobile,
            steps=payload.steps,
            on_change=lambda steps: emit(
                {"type": "steps", "steps": [ir.step_to_dict(step) for step in steps]}
            ),
        )
        recorder.install()
        page = context.new_page()

        if payload.steps:
            emit({"type": "status", "status": "replaying"})
            outcomes = runner.replay(
                page,
                payload.steps,
                payload.base_url,
                resolver,
                on_step=lambda outcome: emit({"type": "replayed", "outcome": outcome_to_dict(outcome)}),
            )
            if outcomes and not outcomes[-1].passed:
                emit(
                    {
                        "type": "error",
                        "message": f"Replay failed at step {outcomes[-1].step_id}: {outcomes[-1].message}",
                    }
                )
            recorder.recording = True
        else:
            recorder.recording = True
            page.goto(runner.absolute_url(payload.start_path, payload.base_url))

        emit({"type": "status", "status": "recording"})
        emit({"type": "steps", "steps": [ir.step_to_dict(step) for step in recorder.steps]})

        while not stop.is_set() and browser.is_connected():
            open_pages = [candidate for candidate in context.pages if not candidate.is_closed()]
            if not open_pages:
                break
            try:
                open_pages[0].wait_for_timeout(POLL_MS)
            except Exception:
                continue

        steps = recorder.steps
        if browser.is_connected():
            browser.close()
        return steps


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        sys.stderr.write("usage: python -m browsertests.core.session <payload.json>\n")
        return 2
    payload = SessionPayload.from_dict(json.loads(Path(arguments[0]).read_text(encoding="utf-8")))
    stop = threading.Event()
    threading.Thread(target=watch_stdin, args=(stop,), daemon=True).start()
    try:
        steps = record(payload, stop)
    except Exception as error:
        emit({"type": "error", "message": runner.first_line(str(error)), "fatal": True})
        return 1
    emit({"type": "done", "steps": [ir.step_to_dict(step) for step in steps]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
